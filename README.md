# Prism Model Manager

> A focused Linux TUI for managing GGUF models through llama.cpp.

[![Latest release](https://img.shields.io/github/release/Ayshinko/prism-model-manager/latest?label=Release&logo=github&logoColor=black&color=72af9d&borderColor=black)](https://github.com/Ayshinko/prism-model-manager/releases/latest)
[![License: MIT](https://img.shields.io/github/license/Ayshinko/prism-model-manager?logo=github&logoColor=black&color=72af9d&borderColor=black)](https://opensource.org/licenses/MIT)
[![Platform: Linux](https://img.shields.io/badge/Linux-x86_64-007ACC?logo=linux&logoColor=white&borderColor=black)](https://github.com/Ayshinko/prism-model-manager)

Prism Model Manager is a terminal UI for running and managing GGUF models on
NVIDIA GPUs. It wraps the Prism llama.cpp fork and handles model discovery,
per-model profiles, server lifecycle, inference settings, live logs, VRAM
monitoring, chat tests and benchmarks — all without maintaining long server
commands manually.

A companion branch, **`experimental/vllm`**, provides extended support for
vLLM, HuggingFace Safetensors and the Mirai S compressed-weight plugin.

**Independent community project. Not affiliated with, endorsed by, or
maintained by PrismML or Mirai Labs.**

<p align="center">
  <img src="assets/prism-model-manager-showcase.png" width="100%" alt="Prism Model Manager">
</p>

Version **4.0.0**, licensed under the [MIT License](LICENSE).

Originally developed on **Omarchy / Arch Linux**. The launcher uses standard
Linux command-line tools and does not depend on Hyprland or an Omarchy desktop
session. Other distributions may work with the dependencies below; they have not
been validated by the maintainer.

## Screenshots

<p align="center">
  <img src="assets/screenshots/main-menu.png" width="900" alt="Prism Model Manager main menu">
</p>

<p align="center">
  <img src="assets/screenshots/model-settings.png" width="900" alt="Prism Model Manager model settings">
</p>

<p align="center">
  <img src="assets/screenshots/model-picker.png" width="900" alt="Prism Model Manager model picker">
</p>

<p align="center">
  <img src="assets/screenshots/benchmark.png" width="900" alt="Prism Model Manager benchmark">
</p>

## What it does

- Discover and switch GGUF models
- Auto-download the llama.cpp backend on first use
- Save individual model profiles
- Configure context, GPU layers, batch size, KV cache and sampling
- Start / stop the Prism llama.cpp server
- Follow live server logs
- Display NVIDIA VRAM/utilization and system RAM usage
- MTP speculative decoding support
- Vision projector support with backend capability checks
- LoRA configuration and A/B scoring
- Validate settings and ports before launch; report failure
- Run quick chat tests on the running model
- Launch the Web UI
- Report local API base URL, reachability and running model ID
- Run raw speed benchmarks
- Process safety: PID tracking, boot identity, port conflict detection
- Colored terminal dashboard with status indicators
- Per-model profile persistence across restarts

## Quick start

### Option 1 (recommended) — Standard online release (small download)

Download the latest PMM release:

```bash
# Download and extract the standard bootstrap package (~60 KB)
wget https://github.com/Ayshinko/prism-model-manager/releases/latest/download/prism-model-manager-4.0.0-linux-x86_64-standard.tar.gz
tar xzf prism-model-manager-4.0.0-linux-x86_64-standard.tar.gz
cd prism-model-manager-4.0.0-linux-x86_64-standard

# Install PMM scripts only
./install.sh
export PATH="$HOME/.local/bin:$PATH"

# Launch — backend downloads on first use
pmm
```

### Option 2 — Offline release (includes bundled llama.cpp)

For systems without internet access at install time:

```bash
# Download the offline package (~49 MB)
wget https://github.com/Ayshinko/prism-model-manager/releases/latest/download/prism-model-manager-4.0.0-linux-x86_64-offline.tar.gz
tar xzf prism-model-manager-4.0.0-linux-x86_64-offline.tar.gz
cd prism-model-manager-4.0.0-linux-x86_64-offline

# Install with bundled llama.cpp backend
./install.sh --offline
export PATH="$HOME/.local/bin:$PATH"
pmm
```

### Option 3 — Git clone (development)

```bash
git clone https://github.com/Ayshinko/prism-model-manager.git
cd prism-model-manager
git checkout main
./install.sh
export PATH="$HOME/.local/bin:$PATH"
pmm
```

## Dependencies

Linux, Bash 4.4+, gum, curl, jq, less, Python 3.8+ (standard library only),
GNU coreutils/findutils, procps-ng (`watch`). `unzip` is required for
downloading llama.cpp releases. `xdg-open` is optional for the browser UI.
NVIDIA monitoring requires a working driver and `nvidia-smi`.

**NVIDIA GPU required for CUDA inference.** A compatible NVIDIA driver is
needed (R525+ for CUDA 12). The installer downloads the llama.cpp backend on
first use. Backend binaries are version-pinned and verified by SHA256 checksums.
NVIDIA CUDA driver and runtime libraries are **not** bundled and must be
installed separately.

On Arch Linux / Omarchy, install missing userland dependencies:

```bash
sudo pacman -S --needed git bash gum curl jq less python coreutils findutils procps-ng util-linux xdg-utils shellcheck
```

## Extended vLLM Edition

This release is the focused **GGUF / llama.cpp edition**.

For users experimenting with HuggingFace Safetensors models, vLLM runtime
management, and the Mirai S compressed-weight plugin:

- **Branch:** [`experimental/vllm`](https://github.com/Ayshinko/prism-model-manager/tree/experimental/vllm)
- **Command:** `pmm-vllm` (side-by-side with official `pmm`)
- **Desktop entry:** "Prism Model Manager — vLLM (Experimental)"

The extended edition includes all features of this release plus:
- vLLM 0.30.0 managed Python environment
- HuggingFace / Safetensors model directory support
- Mirai S plugin with `--no-deps` managed installs
- GPU memory utilization control
- KV cache dtype selection
- Max model length (Auto / numeric)
- Enforce eager mode (`--enforce-eager`) for low-VRAM GPUs
- Backend-aware Settings and Status dashboard

The extended edition is maintained separately and may diverge from the focused
official release.

## Comparison with earlier releases

PMM versions 3.2–3.5 were multi-backend products supporting both llama.cpp
and vLLM. Starting with v4.0.0, the **official edition** focuses exclusively
on GGUF models through llama.cpp, providing a simpler and more polished
experience for the primary use case.

Users who need vLLM, HuggingFace, or Mirai S support should use the
[`experimental/vllm`](https://github.com/Ayshinko/prism-model-manager/tree/experimental/vllm)
branch, which preserves the complete multi-backend implementation including
all real-host validated fixes from the v3.5.x development line.