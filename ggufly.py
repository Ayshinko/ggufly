import ctypes
import json
import msvcrt
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
import sys
import unicodedata
from typing import NamedTuple
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser


DATA = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "GGUFly Windows"
CONFIG = DATA / "settings.json"
DEFAULT_PROFILE = {"context": 4096, "gpu_layers": 99, "port": 8080}
ENGINE_NAME = "llama-server.exe"
RELEASES_URL = "https://github.com/ggml-org/llama.cpp/releases"
HTTP = build_opener(ProxyHandler({}))


def path_input(value):
    return Path(os.path.expandvars(value.strip().strip('"'))).expanduser().resolve()


def load_config():
    defaults = {
        "engine": "", "directory": str(Path.home() / "Models"),
        "model": "", "profiles": {}, "presets": {}, "extra_models": [],
    }
    if CONFIG.exists():
        defaults.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    return defaults


def save_config(config):
    DATA.mkdir(parents=True, exist_ok=True)
    temp = DATA / f"settings.{os.getpid()}.tmp"
    temp.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(CONFIG)


def find_engine(config):
    if config["engine"]:
        configured = Path(config["engine"])
        if configured.is_absolute() and configured.name.lower() == ENGINE_NAME and configured.is_file():
            return configured
    for entry in os.get_exec_path():
        directory = Path(os.path.expandvars(entry.strip('"')))
        if directory.is_absolute():
            candidate = directory / ENGINE_NAME
            if candidate.is_file():
                return candidate
    return None


def model_files(directory):
    for folder, subdirs, names in os.walk(directory):
        subdirs.sort(key=str.casefold)
        for name in sorted(names, key=str.casefold):
            filename = name.lower()
            if not filename.endswith(".gguf") or filename.startswith("mmproj") or filename.endswith("-vocab.gguf"):
                continue
            part = re.search(r"-(\d{5})-of-\d{5}\.gguf$", name, re.IGNORECASE)
            if part is None or int(part[1]) == 1:
                yield Path(folder) / name


def get_profile(config):
    profiles = config["profiles"]
    return DEFAULT_PROFILE | profiles.get("", {}) | profiles.get(config["model"], {})


def start(config, profile):
    engine = find_engine(config)
    if engine is None:
        raise ValueError("llama-server.exe not found. Press D to download or G to set its path.")
    model = Path(config["model"])
    if not model.is_file():
        raise ValueError("Select a GGUF model first.")
    with model.open("rb") as handle:
        if handle.read(4) != b"GGUF":
            raise ValueError(f"Invalid GGUF header in {model}")
    port = profile["port"]
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            raise ValueError(f"Local port {port} is in use. Choose another port in settings.") from error
    command = [
        str(engine), "-m", str(model), "--host", "127.0.0.1", "--port", str(port),
        "-c", str(profile["context"]), "-ngl", str(profile["gpu_layers"]),
    ]
    command.extend(extra_args(engine, profile))
    DATA.mkdir(parents=True, exist_ok=True)
    log = DATA / f"server-{time.time_ns()}.log"
    with log.open("wb") as handle:
        handle.write((subprocess.list2cmdline(command) + "\n\n").encode("utf-8"))
        handle.flush()
        process = subprocess.Popen(command, cwd=engine.parent, stdin=subprocess.DEVNULL,
                                   stdout=handle, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
    return process, f"http://127.0.0.1:{port}", log, model.name


def ready(url):
    try:
        with HTTP.open(f"{url}/health", timeout=0.5) as response:
            return json.load(response).get("status") == "ok"
    except (OSError, URLError, ValueError):
        return False


def stop(process):
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)


class Option(NamedTuple):
    group: str
    key: str
    label: str
    flag: str
    values: tuple | str


CACHE_TYPES = ("f16", "bf16", "f32", "q8_0", "q4_0", "q4_1", "q5_0", "q5_1", "iq4_nl")
OPTIONS = [
    Option("Runtime", "context", "Context size", "", (int, 0, 2097152)),
    Option("Runtime", "gpu_layers", "GPU layers", "", (int, 0, 999)),
    Option("Runtime", "threads", "CPU threads", "--threads", (int, -1, 1024)),
    Option("Runtime", "flash", "Flash Attention", "--flash-attn", ("auto", "on", "off")),
    Option("Runtime", "batch", "Batch size", "--batch-size", (int, 1, 2097152)),
    Option("Runtime", "ubatch", "Microbatch size", "--ubatch-size", (int, 1, 2097152)),
    Option("Runtime", "parallel", "Parallel slots", "--parallel", (int, 1, 1024)),
    Option("Cache", "cache_k", "KV cache K type", "--cache-type-k", CACHE_TYPES),
    Option("Cache", "cache_v", "KV cache V type", "--cache-type-v", CACHE_TYPES),
    Option("Sampling", "temperature", "Temperature", "--temp", (float, 0, 10)),
    Option("Sampling", "top_p", "Top-P", "--top-p", (float, 0, 1)),
    Option("Sampling", "top_k", "Top-K", "--top-k", (int, 0, 2097152)),
    Option("Sampling", "min_p", "Min-P", "--min-p", (float, 0, 1)),
    Option("Sampling", "repeat_penalty", "Repetition penalty", "--repeat-penalty", (float, 0, 10)),
    Option("Generation", "reasoning_budget", "Reasoning token budget", "--reasoning-budget", (int, -1, 2097152)),
    Option("Generation", "output_tokens", "Maximum output tokens", "--predict", (int, -1, 2097152)),
    Option("Vision", "vision", "Vision projector mode", "", ("auto", "off")),
    Option("Vision", "projector", "Projector file", "--mmproj", "gguf"),
    Option("MTP", "mtp", "Embedded MTP", "--spec-type", ("draft-mtp", "mtp")),
    Option("MTP", "draft_tokens", "Maximum draft tokens", "", (int, 1, 1024)),
    Option("LoRA", "lora", "LoRA file", "", "gguf"),
    Option("LoRA", "lora_scale", "LoRA scale", "", (float, 0, 100)),
    Option("Server", "port", "Local port", "", (int, 1024, 65535)),
]
ARROWS = {"H": "up", "P": "down", "G": "home", "O": "end", "S": "del", "K": "left", "M": "right"}
INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()
ANSI = False


class Status(NamedTuple):
    text: str
    color: int


def extra_args(engine, profile):
    args = []
    for option in OPTIONS:
        value = profile.get(option.key)
        if value is None or not option.flag or option.key == "projector" and profile.get("vision") == "off":
            continue
        if option.values == "gguf" and not Path(value).is_file():
            raise ValueError(f"{option.label} not found at {value}")
        args.extend((option.flag, str(value)))

    vision = profile.get("vision")
    if vision == "off":
        args.append("--no-mmproj")
    elif vision == "auto" and not profile.get("projector"):
        args.append("--mmproj-auto")

    lora = profile.get("lora")
    if lora:
        if not Path(lora).is_file():
            raise ValueError(f"LoRA file not found at {lora}")
        scale = profile.get("lora_scale")
        args.extend(("--lora", lora) if scale is None else ("--lora-scaled", f"{lora}:{scale}"))

    if not args:
        return args
    help_result = subprocess.run([str(engine), "--help"], cwd=engine.parent, capture_output=True,
                                 encoding="utf-8", errors="replace", timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    usage = {}
    for line in help_result.stdout.splitlines():
        flags = re.match(r"^(-{1,2}[\w-]+(?:,\s*-{1,2}[\w-]+)*)", line)
        if flags:
            usage.update((flag.strip(), line) for flag in flags[1].split(","))
    mtp = profile.get("mtp")
    if mtp:
        modes = re.search(r"--spec-type\s+(\S+)", usage.get("--spec-type", ""))
        if not modes or mtp not in modes[1].strip("[]{}").split(","):
            raise ValueError(f"This engine does not support MTP mode {mtp}. Reset it in settings.")
        draft_flag = "--spec-draft-n-max" if "--spec-draft-n-max" in usage else "--draft-max"
        if profile.get("draft_tokens") is not None:
            args.extend((draft_flag, str(profile["draft_tokens"])))
    for arg in args:
        if arg.startswith("--") and arg not in usage:
            raise ValueError(f"This llama-server does not support {arg}. Reset the setting or change engines.")
    if profile.get("flash"):
        choices = re.search(r"--flash-attn\s+\[([\w|]+)\]", usage["--flash-attn"])
        if not choices or profile["flash"] not in choices[1].split("|"):
            raise ValueError("This engine does not support the selected Flash Attention mode. Reset it or change engines.")
    return args


def option_value(value):
    return "Engine default" if value is None else str(value)


def edit_value(option, current):
    if option.values == "gguf":
        hint = "Enter the full path to a GGUF file."
    elif isinstance(option.values[0], type):
        _, low, high = option.values
        hint = f"Enter a value from {low} to {high}."
    else:
        hint = "Choices  " + " / ".join(option.values)
    frame([f"GGUFly  /  Edit {option.label}", f"Current value  {option_value(current)}", hint,
           "Leave blank to keep the current value.", ""])
    value = input("New value > ").strip()
    if not value:
        return current
    if option.values == "gguf":
        return gguf_path(value)
    if isinstance(option.values[0], type):
        convert, low, high = option.values
        number = convert(value.replace(",", "."))
        if low <= number <= high and not (option.key == "threads" and number == 0):
            return number
    elif value.lower() in option.values:
        return value.lower()
    raise ValueError(f"Invalid value for {option.label}. {hint}")


def keypress(timeout=None):
    if not INTERACTIVE:
        return input("> ").strip().lower() or "enter"
    if timeout is not None:
        deadline = time.monotonic() + timeout
        while not msvcrt.kbhit():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return ""
            time.sleep(min(remaining, 0.05))
    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        return ARROWS.get(msvcrt.getwch(), "")
    if key == "\x03":
        raise KeyboardInterrupt
    return {"\r": "enter", "\n": "enter", "\x1b": "esc"}.get(key, key.lower())


def clip(text, width):
    result = []
    for char in str(text):
        if ord(char) < 32:
            char = " "
        width -= 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
        if width < 0:
            break
        result.append(char)
    return "".join(result)


def frame(lines):
    width, height = shutil.get_terminal_size((110, 32))
    width = max(1, width - 1)
    screen = "\n".join(render_status(line, width) if isinstance(line, Status) else clip(line, width)
                       for line in lines[-max(1, height - 1):])
    if ANSI:
        print("\x1b[H\x1b[J" + screen, flush=True)
    else:
        print(screen, flush=True)


def render_status(status, width=None):
    text = status.text if width is None else clip(status.text, width)
    return f"\x1b[{status.color}m{text}\x1b[0m" if ANSI else text


def viewport(rows, cursor, reserved):
    room = max(1, shutil.get_terminal_size((110, 32)).lines - reserved - 3)
    top = min(max(0, cursor - room // 2), max(0, len(rows) - room))
    shown = [f"{'›' if i == cursor else ' '} {rows[i]}" for i in range(top, min(top + room, len(rows)))]
    if top or top + room < len(rows):
        shown.append(f"  {cursor + 1}/{len(rows)}")
    return shown


def move(cursor, key, count):
    if not count:
        return 0
    return {"up": (cursor - 1) % count, "down": (cursor + 1) % count,
            "home": 0, "end": count - 1}.get(key, cursor)


def read_text(prompt):
    print()
    if not INTERACTIVE:
        return input(f"{prompt}> ").strip()
    print(f"{prompt}  [Esc cancel]> ", end="", flush=True)
    chars = []
    while True:
        char = msvcrt.getwch()
        if char == "\r":
            return "".join(chars).strip()
        if char == "\x1b":
            return None
        if char == "\x03":
            raise KeyboardInterrupt
        if char in ("\x00", "\xe0"):
            msvcrt.getwch()
        elif char == "\b" and chars:
            chars.pop()
            print("\b \b", end="", flush=True)
        elif char.isprintable():
            chars.append(char)
            print(char, end="", flush=True)


def confirm(message):
    frame([message, "", "Enter Confirm   Esc Cancel"])
    return keypress() == "enter"


def gguf_path(value):
    model = path_input(value)
    if model.suffix.lower() != ".gguf" or not model.is_file():
        raise ValueError(f"GGUF file not found at {model}")
    return str(model)


class Manager:
    def __init__(self):
        self.config = load_config()
        self.process = None
        self.url = ""
        self.log = None
        self.running_model = ""
        self.items = []
        self.cursor = 0
        self.refresh()

    def refresh(self, preferred=None):
        current = preferred or (self.items[self.cursor] if self.items else ("", self.config["model"]))
        files = dict.fromkeys(str(file) for file in model_files(self.config["directory"]))
        for path in [*self.config["extra_models"], self.config["model"]]:
            if path and Path(path).is_file():
                files.setdefault(path, None)
        self.items = [(name, preset["model"]) for name, preset in self.config["presets"].items()]
        self.items.extend(("", path) for path in files)
        self.cursor = self.items.index(current) if current in self.items else min(self.cursor, max(0, len(self.items) - 1))

    def save(self, **changes):
        updated = self.config | changes
        save_config(updated)
        self.config = updated

    def profile(self, item):
        name, model = item
        if name:
            return DEFAULT_PROFILE | self.config["presets"][name]["options"]
        return get_profile(self.config | {"model": model})

    def status(self):
        if self.process is None:
            return Status("○ Stopped", 91)
        code = self.process.poll()
        if code is not None:
            return Status(f"○ Exited (code {code})", 91)
        details = f"  {self.running_model}  {self.url}/v1"
        if ready(self.url):
            return Status("● Running" + details, 92)
        return Status("◌ Loading" + details, 93)

    def launch(self, item, profile):
        if self.process is not None and self.process.poll() is None:
            return "A server is already running. Press X to stop it first."
        self.process, self.url, self.log, self.running_model = start(self.config | {"model": item[1]}, profile)
        self.monitor()
        return ""

    def monitor(self):
        if ANSI:
            print("\x1b[?1049l", end="", flush=True)
        print("\nGGUFly  /  Server log   ·   C Chat   X Stop   Esc Back", flush=True)
        last_status = None
        next_status_check = 0
        try:
            if self.log is None:
                print(render_status(self.status()), flush=True)
                print("No server log yet for this session.", flush=True)
                keypress()
                return
            with self.log.open("rb") as handle:
                while True:
                    if time.monotonic() >= next_status_check:
                        status = self.status()
                        if status != last_status:
                            print(render_status(status), flush=True)
                            last_status = status
                        next_status_check = time.monotonic() + 1
                    lines = []
                    for _ in range(256):
                        position = handle.tell()
                        raw = handle.readline()
                        if not raw:
                            break
                        if not raw.endswith(b"\n") and self.process is not None and self.process.poll() is None:
                            handle.seek(position)
                            break
                        line = raw.rstrip(b"\r\n").decode("utf-8", errors="replace")
                        lines.append("".join(char for char in line if char.isprintable() or char == "\t"))
                    if lines:
                        print("\n".join(lines), flush=True)
                    key = keypress(0.25)
                    if key in ("esc", "q", "enter"):
                        return
                    if key == "c":
                        if self.process is not None and self.process.poll() is None and ready(self.url):
                            webbrowser.open(self.url)
                        else:
                            print("The server is still loading or stopped.", flush=True)
                    if key == "x":
                        print(self.stop_service(), flush=True)
                        next_status_check = 0
        finally:
            if ANSI:
                print("\x1b[?1049h", end="", flush=True)

    def stop_service(self):
        if self.process is not None and self.process.poll() is None:
            stop(self.process)
            self.process = None
            return "Server stopped."
        return "No server is running."

    def save_as(self, item, options):
        name = read_text("New preset name")
        if not name:
            return ""
        if name in self.config["presets"]:
            return "A preset with this name already exists."
        presets = self.config["presets"] | {name: {"model": item[1], "options": options.copy()}}
        self.save(presets=presets)
        self.refresh((name, item[1]))
        return f"Saved preset '{name}'."

    def edit(self, item):
        name, model = item
        saved = self.profile(item)
        draft = saved.copy()
        cursor, notice = 0, ""
        while True:
            option = OPTIONS[cursor]
            field, label = option.key, option.label
            rows = [f"[{item.group}] {item.label}  {option_value(draft.get(item.key))}{'  *' if draft.get(item.key) != saved.get(item.key) else ''}"
                    for item in OPTIONS]
            dirty = draft != saved
            frame([f"GGUFly  /  {name or Path(model).name}  /  Settings" + ("  * Unsaved" if dirty else ""), "",
                   *viewport(rows, cursor, 8), "", notice,
                   "↑/↓ Select   Enter Edit   ←/→ Change choice   D Reset   R Reset all",
                   "S Save   A Save as preset   L Launch   Esc Back"])
            key = keypress()
            notice = ""
            try:
                cursor = move(cursor, key, len(rows))
                if key == "enter" or key in ("left", "right"):
                    value = draft.get(field)
                    if key == "enter":
                        value = edit_value(option, value)
                    elif isinstance(option.values, tuple) and isinstance(option.values[0], str):
                        choices = (None, *option.values)
                        current = choices.index(value) if value in choices else 0
                        value = choices[(current + (1 if key == "right" else -1)) % len(choices)]
                    else:
                        continue
                    if value is None:
                        draft.pop(field, None)
                    else:
                        draft[field] = value
                    if draft.get(field) != saved.get(field):
                        notice = f"{label} → {option_value(value)}. Press S to save."
                elif key == "d":
                    if field in DEFAULT_PROFILE:
                        draft[field] = DEFAULT_PROFILE[field]
                    else:
                        draft.pop(field, None)
                elif key == "r":
                    draft = DEFAULT_PROFILE.copy()
                elif key == "s":
                    if name:
                        presets = self.config["presets"] | {name: {"model": model, "options": draft.copy()}}
                        self.save(presets=presets)
                    else:
                        self.save(profiles=self.config["profiles"] | {model: draft.copy()}, model=model)
                    saved, notice = draft.copy(), "Settings saved for the next launch."
                elif key == "a":
                    notice = self.save_as(item, draft)
                elif key == "l":
                    notice = self.launch(item, draft)
                elif key in ("esc", "q"):
                    if not dirty or confirm("Discard unsaved changes?"):
                        return
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                notice = str(error)

    def change_engine(self):
        frame(["GGUFly  /  Engine", str(find_engine(self.config) or "llama-server.exe not found"), "",
               "Enter Set path   A Detect from PATH   D Download   Esc Back"])
        key = keypress()
        if key == "a":
            self.save(engine="")
        elif key == "d":
            webbrowser.open(RELEASES_URL)
        elif key == "enter":
            value = read_text("Full path to llama-server.exe")
            if value:
                exe = path_input(value)
                if exe.name.lower() != ENGINE_NAME or not exe.is_file():
                    raise ValueError(f"llama-server.exe not found at {exe}")
                self.save(engine=str(exe))

    def change_folder(self):
        value = read_text(f"Model folder [{self.config['directory']}]")
        if value:
            directory = path_input(value)
            if not directory.is_dir():
                raise ValueError(f"Model folder not found at {directory}")
            self.save(directory=str(directory))
            self.refresh()

    def add_file(self):
        value = read_text("Full path to a GGUF file")
        if value:
            path = gguf_path(value)
            files = list(dict.fromkeys([*self.config["extra_models"], path]))
            self.save(extra_models=files, model=path)
            self.refresh(("", path))

    def change_preset(self, item, key):
        if not item or not item[0]:
            return "Select a saved preset first."
        name, model = item
        presets = self.config["presets"].copy()
        if key == "del":
            if not confirm(f"Delete preset '{name}'? The model file will be kept."):
                return ""
            del presets[name]
            self.save(presets=presets)
            self.refresh()
            return "Preset deleted."
        new_name = read_text(f"New preset name [{name}]")
        if not new_name or new_name == name:
            return ""
        if new_name in presets:
            return "A preset with this name already exists."
        presets[new_name] = presets.pop(name)
        self.save(presets=presets)
        self.refresh((new_name, model))
        return "Preset renamed."

    def home(self):
        notice = ""
        last_screen = None
        while True:
            engine = find_engine(self.config)
            item = self.items[self.cursor] if self.items else None
            top = ["GGUFly Windows  /  llama.cpp", self.status(),
                   f"Engine  {engine or 'llama-server.exe not found · G Set path / D Download'}",
                   f"Model folder  {self.config['directory']}", ""]
            rows = [f"[{'Preset' if name else 'Model'}]  {name or Path(model).name}" for name, model in self.items]
            bottom = ["", item[1] if item else "", notice,
                      "↑/↓ Select   Enter Settings   N Rename   Del Delete preset   R Refresh",
                      "X Stop   C Chat   M Logs   V VRAM   F Folder   O Add file   G Engine   Q Quit"]
            screen = top + (viewport(rows, self.cursor, len(top) + len(bottom)) if rows else ["  No GGUF models found. Press F to choose a folder or O to add a file."]) + bottom
            if screen != last_screen:
                frame(screen)
                last_screen = screen
            key = keypress(1)
            if not key:
                continue
            notice = ""
            last_screen = None
            try:
                self.cursor = move(self.cursor, key, len(self.items))
                if key in ("enter", "e") and item:
                    self.edit(item)
                elif key in ("n", "del"):
                    notice = self.change_preset(item, key)
                elif key == "r":
                    self.refresh()
                    notice = "Model list refreshed."
                elif key == "x":
                    notice = self.stop_service()
                elif key == "c":
                    if self.process is not None and self.process.poll() is None and ready(self.url):
                        webbrowser.open(self.url)
                    else:
                        notice = "The server is still loading or stopped."
                elif key == "m":
                    self.monitor()
                elif key == "v":
                    gpu = shutil.which("nvidia-smi.exe")
                    if not gpu:
                        notice = "nvidia-smi not found."
                    else:
                        result = subprocess.run([gpu, "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                                                 "--format=csv"], capture_output=True, text=True, errors="replace",
                                                timeout=8, check=True)
                        frame(["GGUFly  /  VRAM", "", *result.stdout.splitlines(), "", "Press any key to go back."])
                        keypress()
                elif key == "f":
                    self.change_folder()
                elif key == "o":
                    self.add_file()
                elif key == "g":
                    self.change_engine()
                elif key == "d" and not engine:
                    webbrowser.open(RELEASES_URL)
                elif key in ("q", "esc"):
                    if self.process is None or self.process.poll() is not None or confirm("Quit GGUFly and stop the server?"):
                        return
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                notice = f"Error: {error}"


def main():
    global ANSI
    if INTERACTIVE:
        kernel = ctypes.windll.kernel32
        kernel.GetStdHandle.restype = ctypes.c_void_p
        handle = ctypes.c_void_p(kernel.GetStdHandle(-11))
        mode = ctypes.c_uint()
        ANSI = bool(kernel.GetConsoleMode(handle, ctypes.byref(mode)) and kernel.SetConsoleMode(handle, mode.value | 4))
        if ANSI:
            print("\x1b[?1049h", end="", flush=True)
    manager = None
    try:
        manager = Manager()
        manager.home()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if ANSI:
            print("\x1b[?1049l", end="", flush=True)
            kernel.SetConsoleMode(handle, mode.value)
            ANSI = False
        if manager and manager.process is not None:
            stop(manager.process)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit(f"GGUFly could not continue. {error}") from error
