#!/usr/bin/env bash
# install.sh — GGUFly 1.0.0-dev Bootstrap Installer
#
# Installs GGUFly: GGUF-focused, runtime-registry architecture,
# llama.cpp managed-runtime backends (standard/prism/mirai).
#
# Usage:
#   ./install.sh                    # Online bootstrap (GGUFly scripts only)
#   ./install.sh --offline          # Self-contained archive mode
#   ./install.sh --help             # Show help
#
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREFIX="${PREFIX:-$HOME/.local}"
PMM_BIN="$PREFIX/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ggufly"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ggufly"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
BACKENDS_DIR="$DATA_HOME/ggufly/backends"
VERSION="1.0.0-dev"

OFFLINE_MODE=0
for arg in "$@"; do
    case "$arg" in
        --offline) OFFLINE_MODE=1 ;;
        --help)
            echo "GGUFly $VERSION Installer"
            echo ""
            echo "Usage: $0 [--offline] [--help]"
            echo ""
            echo "  --offline    Install bundled llama.cpp backend (full release archive)"
            echo "  PREFIX=path  Install to a custom prefix (default: \$HOME/.local)"
            exit 0
            ;;
    esac
done

echo "=== GGUFly $VERSION Installer ==="
echo "Mode:      $([ "$OFFLINE_MODE" = 1 ] && echo 'OFFLINE (bundled backend)' || echo 'ONLINE (download backends on first use)')"
echo "Prefix:    $PREFIX"
echo "Root:      $ROOT"
echo ""

# ── 1. Preflight ──────────────────────────────

# Architecture
ARCH=$(uname -m)
if [ "$ARCH" != "x86_64" ]; then
    echo "ERROR: This package supports x86_64 only (detected: $ARCH)." >&2
    exit 1
fi

# OS
if [ "$(uname -s)" != "Linux" ]; then
    echo "ERROR: Linux is required (detected: $(uname -s))." >&2
    exit 1
fi

# Dependencies
MISSING=""
for tool in bash curl jq less python3 sha256sum find xargs; do
    command -v "$tool" >/dev/null 2>&1 || MISSING="$MISSING $tool"
done
if [ -n "$MISSING" ]; then
    echo "ERROR: Missing required tools:$MISSING" >&2
    echo ""
    echo "On Arch Linux / Omarchy:"
    echo "  sudo pacman -S --needed bash curl jq less python coreutils findutils" >&2
    exit 1
fi

echo "Architecture:   OK ($ARCH)"
echo "System:         OK (Linux)"
echo "Dependencies:   OK"
echo ""

# Existing check
EXISTING_GGUFLY="$PMM_BIN/ggufly"
if [ -f "$EXISTING_GGUFLY" ] || [ -L "$EXISTING_GGUFLY" ]; then
    CURRENT_VER=$("$EXISTING_GGUFLY" --version 2>/dev/null || echo "unknown")
    echo "Existing GGUFly installation detected: $EXISTING_GGUFLY (v$CURRENT_VER)"
    if command -v gum >/dev/null 2>&1; then
        if ! gum confirm "Upgrade to GGUFly v$VERSION?"; then
            echo "Installation cancelled."
            exit 0
        fi
    else
        echo "Press Enter to upgrade, or Ctrl-C to cancel."
        read -r || true
    fi
fi

# ── 2. Create directories ─────────────────────

mkdir -p "$PMM_BIN" "$CONFIG_DIR" "$STATE_DIR" \
    "$CONFIG_DIR/model-profiles" \
    "$BACKENDS_DIR/llama.cpp/standard" \
    "$BACKENDS_DIR/llama.cpp/prism" \
    "$BACKENDS_DIR/llama.cpp/mirai" \
    "$STATE_DIR/downloads"

# ── 3. Install core files ─────────────────

echo "--- Installing core ---"

for name in ggufly ggufly-runtime-manager \
            ggufly-runtime-registry.sh \
            ggufly-model-detect.py \
            ggufly-gguf-info.py ggufly-backend-info.py; do
    src="$ROOT/bin/$name"
    if [ -f "$src" ]; then
        install -m 755 "$src" "$PMM_BIN/$name"
        echo "  Installed: $PMM_BIN/$name"
    else
        echo "  WARNING: Skipping missing file: $src"
    fi
done

# Compatibility manifest
COMPAT_DEST="$PREFIX/share/ggufly"
mkdir -p "$COMPAT_DEST"
if [ -f "$ROOT/compatibility.json" ]; then
    install -m 644 "$ROOT/compatibility.json" "$COMPAT_DEST/compatibility.json"
    echo "  Installed: $COMPAT_DEST/compatibility.json"
fi

# Symlinks — primary CLI + convenience aliases
ln -sf "$PMM_BIN/ggufly" "$PMM_BIN/ggfly"
echo "  Created:    $PMM_BIN/ggfly -> ggufly"
ln -sf "$PMM_BIN/ggufly" "$PMM_BIN/pmm"
echo "  Created:    $PMM_BIN/pmm -> ggufly (deprecated alias)"

# Desktop launcher
LAUNCHER_SCRIPT="$PMM_BIN/ggufly-launcher"
cat > "$LAUNCHER_SCRIPT" << 'LAUNCHER'
#!/usr/bin/env bash
PMM="$HOME/.local/bin/ggufly"
for term in ghostty kitty alacritty wezterm foot gnome-terminal; do
    if command -v "$term" >/dev/null 2>&1; then
        exec "$term" -e "$PMM" 2>/dev/null || exec "$term" "$PMM"
    fi
done
notify-send "GGUFly" "Run 'ggufly' from your terminal."
exit 1
LAUNCHER
chmod 755 "$LAUNCHER_SCRIPT"
echo "  Installed:  $LAUNCHER_SCRIPT"

# Desktop entries
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS_DIR"
for variant in "" "-terminal"; do
    cat > "$APPS_DIR/ggufly${variant}.desktop" << DESKTOP
[Desktop Entry]
Type=Application
Name=GGUFly${variant:+ (Terminal)}
GenericName=GGUF Model Manager
Comment=Manage GGUF models and llama.cpp runtimes
Exec=${variant:+$PMM_BIN/ggufly}${variant:-$LAUNCHER_SCRIPT}
Icon=utilities-terminal
Terminal=${variant:+true}${variant:-false}
Categories=Development;Utility;
Keywords=GGUF;LLM;AI;llama.cpp;
DESKTOP
done
echo "  Installed:  Desktop entries"

# ── 4. Initialize runtime registry ────────────

if [ -x "$PMM_BIN/ggufly-runtime-registry.sh" ]; then
    "$PMM_BIN/ggufly-runtime-registry.sh" init 2>/dev/null || true
    echo "  Initialized: Runtime registry"
fi

# ── 5. Offline: bundled llama.cpp backend ─────

if [ "$OFFLINE_MODE" = 1 ]; then
    echo ""
    echo "--- Installing bundled llama.cpp backend ---"

    if [ -f "$ROOT/lib/llama-server" ]; then
        install -m 755 "$ROOT/lib/llama-server" "$BACKENDS_DIR/llama.cpp/standard/current/bin/llama-server"
        echo "  Installed: $BACKENDS_DIR/llama.cpp/standard/current/bin/llama-server"

        # Copy shared libraries
        for lib in "$ROOT"/lib/*.so* "${ROOT}"/lib/*.so.*; do
            [ -f "$lib" ] || continue
            install -m 644 "$lib" "$BACKENDS_DIR/llama.cpp/standard/current/bin/"
        done
        echo "  Installed: Shared libraries"

        # Verify
        if "$BACKENDS_DIR/llama.cpp/standard/current/bin/llama-server" --version >/dev/null 2>&1; then
            echo "  Backend: OK"
        else
            echo "  WARNING: Backend may have missing dependencies."
            ldd "$BACKENDS_DIR/llama.cpp/standard/current/bin/llama-server" 2>&1 | grep "not found" || true
        fi
    else
        echo "  WARNING: llama-server not found in archive (lib/)."
        echo "  Backend will be downloaded on first use via: ggufly-runtime-manager install standard"
    fi
fi

# ── 6. Create default config ─────────────────

CONFIG="$CONFIG_DIR/config.env"
if [ ! -f "$CONFIG" ]; then
    cat > "$CONFIG" << CONFIGEOF
# GGUFly $VERSION — Configuration
# Generated by installer on $(date -Iseconds)

# Model directory — set this to your GGUF model location
MODEL_ROOT=${GGUFLY_MODEL_ROOT:-${PMM_MODEL_ROOT:-$HOME/Models}}

# API
HOST=127.0.0.1
PORT=8080
STARTUP_TIMEOUT=180

# Inference defaults
CTX=4096
NGL=99
FLASH=on
BATCH=512
UBATCH=128
PARALLEL=1
TEMP=1.0
TOP_P=0.95
TOP_K=20
MIN_P=0
CACHE_K=f16
CACHE_V=f16

# MTP
MTP=off
MTP_MODE=draft-mtp
MTP_DRAFT_MAX=3
MTP_DRAFT_FLAG=--spec-draft-n-max

# Per-model settings
VISION=off
MMPROJ_PATH=
LORA_ENABLED=off
LORA_SCALE=2
LORA_PATH=

# Advanced
MAX_OUTPUT_TOKENS=-1
REASONING_BUDGET=-1
CONFIGEOF
    chmod 600 "$CONFIG"
    echo "  Created:    $CONFIG (default config)"
else
    echo "  Found:      $CONFIG (existing config preserved)"
fi

# ── 7. PATH reminder ────────────────────────

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Run:  ggufly"
echo "Or:   pmm"
echo ""
echo "To add to PATH:"
echo "  echo 'export PATH=\"\$PATH:$PMM_BIN\"' >> ~/.bashrc"
echo "  export PATH=\"\$PATH:$PMM_BIN\""
echo ""
echo "Quick start:"
echo "  1. Set your model directory in Settings -> Advanced -> Model root"
echo "  2. Install a runtime: ggufly-runtime-manager install standard"
echo "  3. Select a model and a runtime fork"
echo "  4. Start the model"
echo ""
echo "Backend management:"
echo "  ggufly-runtime-manager status           # Show installed runtimes"
echo "  ggufly-runtime-manager install standard  # Install standard llama.cpp"
echo "  ggufly-runtime-manager install prism     # Install PrismML/Bonsai fork"
echo "  ggufly-runtime-manager install mirai     # Install Mirai S fork"
echo ""
echo "Uninstall:  $ROOT/uninstall.sh"