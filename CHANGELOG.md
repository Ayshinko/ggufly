# Changelog

## 3.5.1 — 2026-09-26

- **vLLM + Mirai S integration:** Complete backend management for HuggingFace
  directory models and Mirai S trellis-quantized models.
- **Mirai S plugin installer:** Installs isolated Mirai S wheel into PMM-managed
  plugin directory. Uses `--no-deps` to avoid copying vLLM/torch/CUDA libraries
  into the plugin target. Uses managed `$VLLM_VENV/bin/python -m pip`.
- **Model-local plugin storage:** Plugin site-packages stored under
  `<model-dir>/.pmm/plugins/<plugin>/site-packages`. No Python packages written
  into the model directory itself (safetensors, config, etc. remain untouched).
- **Directory model support:** `preflight()` now accepts both files (GGUF) and
  directories (HF/Mirai S) as CURRENT_MODEL.
- **Backend-aware settings menu:** llama.cpp-specific settings (GPU layers, KV
  cache, Vision, MTP, LoRA) only shown when Backend=llama.cpp. vLLM settings
  (GPU memory util, max model len, max sequences) shown when Backend=vLLM.
- **Removed user-facing "Auto":** Auto is an internal concept only. Menus show
  concrete backend/plugin choices. Old configs with `BACKEND=Auto` or
  `PLUGIN=Auto` are safely migrated.
- **Plugin selection now separate from installation:** `backend_plugin_compatible`
  only checks structural model compatibility (requires `is_mirai_package`, not
  `is_mirai_model_dir`). Installation availability belongs in `ensure_plugin()`.
- **Context → max-model-len sync:** Setting "Context size" for vLLM backend
  synchronizes to `--max-model-len`.
- **PMM_PLUGIN_ROOT override:** Environment variable allows pointing plugin
  storage to a different filesystem (e.g. writable path when `$HOME` is read-only).
- **PMM-managed llama-server discovery:** `SERVER_BIN` now automatically finds
  llama-server in PMM's managed `BACKENDS_DIR` after `ensure_backend` installation.
- **LLAMA_DIR candidates:** Added `$BACKENDS_DIR/llama.cpp/llama-server` to the
  auto-discovery candidate list.
- **Python 3.11.16 managed vLLM venv:** vLLM 0.30.0, safetensors 0.8.0,
  huggingface_hub 1.33.0, torch 2.13.0+cu130.
- **Improved GPU port conflict handling:** Interactive choice to pick a different
  port when the default is occupied.
- **Clearer launch error messages:** Failed vLLM startup reports "vLLM server
  exited before becoming ready" (not "llama-server").
- **Verification exception visibility:** Import failures show the real Python
  exception traceback.
- **ZERO shell heredoc warnings:** All embedded Python heredocs inside `$()`
  replaced with `python3 -c` inline code.
- **122 automated tests:** Python unittest (116) + bash integration (6), all PASS.
- **Regression tests for:** External model root (`PMM_MODEL_ROOT`), directory
  model preflight, Mirai runtime path resolution, state persistence, plugin
  verification, top-level function scope, heredoc warning check,
  `PMM_PLUGIN_ROOT` override.

- **Fixed startup crash:** Removed `plugin_name` unbound variable from main_menu()
  that caused PMM to exit immediately on launch under strict `set -u` mode.
- **Fixed TUI separator corruption:** Added locale-aware fallback (━ with UTF-8,
  ═ with ASCII, - in non-TTY). Added terminal width validation to prevent
  invalid character generation.
- **Fixed vLLM auto-install:** `ensure_backend()` now correctly skips the
  `SERVER_BIN` shortcut for vLLM backend. Previously, finding any existing
  llama-server caused ensure_backend to return success without installing vLLM.
- **Removed duplicate vLLM check:** `validate_settings()` no longer checks
  vLLM availability (the old manual-install message). Auto-install is handled
  entirely by `ensure_backend()` with gum confirm prompt.
- **Python compatibility detection:** vLLM installer now explicitly searches
  for Python 3.12/3.11/3.10/3.9/3.8 before creating the venv. System
  Python 3.14 produces a clear error message with install guidance.
- **Colored dashboard enhancement:** Model panel shows Backend and Plugin status
  with color coding (green=installed, yellow=missing, magenta=Mirai S installed,
  gray=no plugin).
- **Startup regression test:** Added set -u startup safety test to shell suite.
- **Version 3.4.0 release:** Published to GitHub with standard (60 KB) and
  offline (49 MB) release archives.

## 3.3.0 — 2026-09-26

- **Self-contained backend management:** PMM now automatically downloads and
  installs inference backends. No manual llama.cpp, vLLM, or Python venv setup
  required for end users.
- **llama.cpp backend installer:** Automatic discovery of existing llama-server
  binaries (Prism fork, system, pacman). GitHub release download fallback with
  version pinning and SHA256 verification.
- **vLLM backend installer:** Creates isolated Python virtual environment,
  detects GPU compute capability and CUDA version, installs the correct vLLM
  wheel (CUDA 12/13), and verifies installation.
- **Mirai S plugin installer:** Downloads from the official HuggingFace repo,
  verifies wheel integrity, checks GPU VRAM and disk space, and installs into
  the vLLM venv.
- **Bootstrap installer:** New install.sh supports online (scripts only, ~200 KB)
  and offline (with bundled llama.cpp, ~130 MB) modes. Backends downloaded on
  first use.
- **Model format detection:** New prism-model-detect.py identifies GGUF,
  HuggingFace, and Mirai S formats. The settings menu now shows "Format" field.
- **Backend management menu:** TUI menu item "🔧 Backend Management" shows
  status of all backends and provides install/remove operations.
- **Auto-install flow:** When loading a model whose backend is missing, PMM
  prompts to install it automatically, shows progress, and validates the result.
- **GPU/environment detection:** New prism-backend-detect.py reports GPU name,
  VRAM, compute capability, CUDA version, Python ABI, and compatibility status.
- **Compatibility manifest:** compatibility.json pins backend versions,
  checksums, supported architectures, and system requirements.
- **Per-model backend/plugin:** Continued from v3.2.x with enhanced persistence.
- **Preserved all existing functionality:** Bonsai PTQ1/PQ2, MTP, vision,
  LoRA, GPU monitoring, process safety.
- **Updated build-release.sh:** Produces standard (online-only) and offline
  release archives for distribution.

## 3.2.0 — 2026-09-26

- **vLLM backend:** Optional vLLM inference backend with dedicated Python virtual
  environment. Detected automatically when the selected model is a HuggingFace
  directory (containing `config.json` and safetensors). vLLM is not required for
  existing GGUF/llama.cpp users and is never installed without user action.
- **Mirai S plugin:** Optional inference plugin for vLLM-compatible Mirai S models.
  Provides speculative decoding (MTP) via vLLM's `--speculative-config` flag.
  Automatically detected and enabled when a Mirai S model directory is selected.
- **Model settings menu:** Added "Backend" and "Plugin" entries at the top of the
  model settings screen. Options: Auto / llama.cpp / vLLM (Backend) and Auto /
  None / Mirai S (Plugin). Compatible combinations are enforced. Normal GGUF
  defaults to llama.cpp; Mirai S models default to vLLM + Mirai S.
- **Per-model backend/plugin persistence:** BACKEND and PLUGIN selections are
  saved in each model's profile and restored on re-selection.
- **Model scanner:** Now discovers HuggingFace/vLLM model directories (with
  `config.json` and safetensors) alongside GGUF files.
- **Optimized defaults for RTX 4070 SUPER (12 GB):** Mirai S starts with MTP
  disabled and conservative context sizing by default.
- **Preserved existing functionality:** All existing Prism llama.cpp backend,
  Bonsai PTQ1/PQ2, GGUF models, MTP, reasoning budget, vision, process safety,
  and GPU monitoring remain unchanged.
- **Compatibility validation:** Backend and plugin availability is checked before
  model loading. Unsupported settings are blocked with clear error messages.
- **Documentation:** Updated README with vLLM installation instructions, Mirai S
  requirements, and simplified settings menu documentation.

## 3.0.1 — 2026-09-22

- **Integrated release archive:** First archive bundling PMM 3.0 and a verified
  PR218-compatible llama-server backend. Users no longer need to download, build
  or locate llama-server separately.
- **One-step installer:** Verifies CPU architecture, CUDA runtime, backend SHA256
  and archive integrity. Sets the bundled PR218 backend as the default for fresh
  installations. Asks before replacing an existing custom backend path.
- **Desktop integration:** Installs application launcher, terminal launcher and
  Omarchy-compatible .desktop entries.
- **Documentation:** Add full MTP Benchmark Record (docs/MTP-BENCHMARK-RECORD.md),
  integrated archive README, backend provenance documentation, and updated README
  with integrated package installation instructions.
- **Packaging:** `packaging/build-release.sh` script, install/uninstall for the
  integrated archive, license and attribution files for bundled components,
  and local modification patches preserved in `packaging/patches/`.

## 3.0.0 — 2026-09-22

- Default MTP mode to `draft-mtp` (maps to `--spec-type draft-mtp`) and validate
  the selected mode against the backend's advertised `--spec-type` values, plus
  modern speculative-draft flags, instead of trusting free-text settings.
- Parse `llama-server --help` (including aliases, boolean flags, wrapped
  descriptions, ANSI output and removed options) to decide advertised
  capabilities; refuse options or draft flags the backend marks as removed.
  Handle composite usage forms such as `--override-tensor
  <tensor name pattern>=<buffer type>,...` and `-hf [<repo>/]<model>[:quant]`.
- Add embedded-MTP migration for legacy `SPEC_MODE`, `SPEC_DRAFT_MODEL` and
  `SPEC_DRAFT_TOKENS` environment variables, only when the corresponding
  canonical config value was not saved explicitly. Embedded MTP uses no
  sidecar/draft model; a migrated `SPEC_DRAFT_MODEL` emits a warning and keeps
  embedded MTP.
- Support automatic vision selection: empty `MMPROJ_PATH` uses `--mmproj-auto`
  when the backend advertises it, and falls back to a single adjacent
  `*mmproj*.gguf`; an explicit path uses `--mmproj FILE`. Missing or ambiguous
  projectors still block startup.
- Add session-only backend override via `PMM_SERVER_BIN` (and `PMM_MODEL_ROOT`,
  `PMM_PRISM_ROOT`, `PMM_BENCH_BIN`), tracked as session state so it is not
  persisted over an explicitly saved config value; `--state` reports the current
  runtime state and `--clear-state` removes stale state.
- Rewrite preflight to validate executable, model file, inference settings and
  shard completeness before launching, and to resolve backend capabilities from
  the parsed help table rather than regex over raw text.
- Add `--api-ready` (reports API base URL, reachability, model id; exits nonzero
  when unreachable) and `--check` validating the saved selection without launch.
- Track config provenance (which settings were saved vs. environment-provided)
  so migrations and session overrides never overwrite explicit user values.

## 2.0.0 — 2026-09-21

- Validate inference settings and backend help before loading; provide explicit
  errors for missing models/backends, unsupported options and occupied ports.
- Select and preflight a replacement model before confirming a managed shutdown;
  serialize lifecycle changes and recheck process identity before signals.
- Record boot identity and the loaded model/API endpoint, distinguish managed and
  external status, and clean up failed or timed-out launches.
- Add persisted MTP mode/draft controls and explicit vision projector selection;
  reject missing/ambiguous projectors instead of silently falling back to text.
- Correct GGUF file-type interpretation, expose architecture/name/context metadata,
  and validate numbered shard sets while listing only their first shard.
- Display NVIDIA memory/utilization and system RAM snapshots; retain existing
  inference, LoRA, chat, log and benchmark functionality.
- Save profiles/configuration atomically, keep settings available before first
  model selection, and target chat requests at the actual API model ID.
- Add isolated regression coverage for lifecycle, configuration, MTP/vision,
  ports, backend errors, discovery and metadata. Real CUDA inference is not
  certified by these tests. No backend replacement or final release tag.

## 0.1.0 — 2026-09-18

- Package the existing Bash/gum model manager as an independent community project.
- Preserve model selection, per-model profiles, server lifecycle, chat, Web UI,
  VRAM monitoring, benchmarks and live logs.
- Replace machine-specific defaults with XDG paths, environment overrides and
  runtime discovery; keep installation non-destructive.
- Add format compatibility hints, NVIDIA architecture detection and Ada advice.
- Add dry-run command construction, isolated tests and distribution documentation.
- Adopt the MIT License, copyright 2026 Ayshinko.
- Document Omarchy / Arch Linux installation and first-launch configuration.
