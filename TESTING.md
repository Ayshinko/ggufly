# GGUFly Test Suite

Checks use temporary HOME/XDG directories, synthetic GGUF headers, fake backend
help and test-owned Python HTTP servers or sleep processes. Existing model files,
custom inference backends, running inference services and system configuration
are not modified. No real model is loaded and no benchmark is executed.

## Automated checks (fixture-based)

- `bash -n` syntax: PASS for `bin/ggufly`, `bin/ggufly-runtime-manager`,
  `install.sh`, `uninstall.sh`, `packaging/build-release.sh` and `tests/test.sh`.
- Python syntax/AST compilation: PASS for `bin/ggufly-model-detect.py`,
  `bin/ggufly-backend-info.py`, `bin/ggufly-gguf-info.py`,
  `bin/prism-lora-ab-score.py`
- Python regression suite: **80 tests PASS**
  (`test_metadata.py` ×4, `test_backend_info.py` ×10, `test_runtime.py` ×53,
   `test_download.py` ×12, `test_gum_tui.py` ×1).
- Shell integration suite (`tests/test.sh`): PASS.
- `git diff --check`: PASS (no whitespace errors).

Run from the repository root:

```bash
bash -n bin/ggufly bin/ggufly-runtime-manager install.sh uninstall.sh tests/test.sh packaging/build-release.sh
bash tests/test.sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py' -v
git diff --check
```

## Coverage

Existing tests cover:
- Backend-help parsing (aliases, boolean, wrapped, ANSI, removed, composite)
- Model scanning/exclusions, split shards, HuggingFace directories
- Escaped config and per-model profile round trips (with new BACKEND/PLUGIN fields)
- Config-provenance tracking, `SPEC_*` migration
- Session-only backend override, atomic persistence
- MTP mode/draft flag variants, vision projector selection
- Process identity, lifecycle locks, port occupancy
- Ready/failed/timed-out starts, cancelled/invalid/valid switches
- `--api-ready`, `--dry-run`, `--state`, `--clear-state`
- Install, second-install rejection, uninstall, retained data

New coverage (1.0.0-dev):
- Model format detection (GGUF, HuggingFace, Mirai S)
- GPU/environment detection (compute cap, CUDA, Python ABI)
- Backend manager status tracking (llama.cpp, vLLM, Mirai S)
- Bootstrap installer (online mode, offline mode)
- Auto-install flow (non-interactive skip, interactive confirm)
- Compatibility manifest parsing

## End-user acceptance tests (manual)

See "End-User Acceptance Tests" in the README for the complete test matrix.
These require a clean environment or a real GPU and are not automated.

## Not yet tested (requires real hardware / clean environment)

- Test A: Clean-install GGUF + llama.cpp auto-download
- Test B: Clean-install HF model + vLLM auto-download
- Test C: Mirai S plugin auto-install and inference
- Test D: Incompatible model/backend rejection
- Test E: Backend switching
- Test F: Install recovery and clean removal
- Real GPU inference with llama.cpp MTP, vLLM, and Mirai S
- Actual download and SHA256 verification of backend releases

These tests are documented but require NVIDIA GPU hardware and internet access
at install time. No mock substitutes for real installation and inference exist.

## Verification run

```bash
# Syntax
bash -n bin/ggufly bin/ggufly-runtime-manager install.sh uninstall.sh tests/test.sh packaging/build-release.sh

# Shell integration
bash tests/test.sh

# Python regression (80 tests)
python3 -m unittest discover -s tests -p 'test_*.py' -v

# Whitespace
git diff --check
```