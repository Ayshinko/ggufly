#!/usr/bin/env bash
# uninstall.sh — PMM 3.4.0 Uninstaller
#
# Removes only files installed by PMM. Configuration, models, logs,
# downloaded backends and user data are preserved unless --all is specified.
#
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
PMM_BIN="$PREFIX/bin"
BACKEND_LIB="$PREFIX/lib/prism-llama"
SHARE_DIR="$PREFIX/share/prism-model-manager"
FLAG="${1:-}"

REMOVED=0
KEPT=0

echo "=== Prism Model Manager Uninstaller ==="

# ── Core PMM files ────────────────────────────

for name in prism-model-manager prism-backend-manager prism-backend-detect.py \
            prism-model-detect.py prism-lora-ab-score.py prism-gguf-info.py \
            prism-backend-info.py prism-model-manager-launcher pmm-vllm; do
    target="$PMM_BIN/$name"
    if [ -f "$target" ] || [ -L "$target" ]; then
        rm -f "$target"
        echo "  Removed:    $target"
        REMOVED=$((REMOVED + 1))
    fi
done

# Symlink
if [ -L "$PMM_BIN/pmm" ]; then
    rm -f "$PMM_BIN/pmm"
    echo "  Removed:    $PMM_BIN/pmm"
    REMOVED=$((REMOVED + 1))
fi

# ── Share data ────────────────────────────────

if [ -d "$SHARE_DIR" ]; then
    rm -rf "$SHARE_DIR"
    echo "  Removed:    $SHARE_DIR"
    REMOVED=$((REMOVED + 1))
fi

# ── Backend libraries (only if identical) ─────

if [ -f "$BACKEND_LIB/llama-server" ]; then
    if [ -f "$ROOT/lib/llama-server" ]; then
        ARCHIVE_SHA=$(sha256sum "$ROOT/lib/llama-server" 2>/dev/null | awk '{print $1}')
        INSTALLED_SHA=$(sha256sum "$BACKEND_LIB/llama-server" 2>/dev/null | awk '{print $1}')
        if [ "$ARCHIVE_SHA" = "$INSTALLED_SHA" ]; then
            rm -rf "$BACKEND_LIB"
            echo "  Removed:    $BACKEND_LIB"
            REMOVED=$((REMOVED + 1))
        else
            echo "  Kept (modified): $BACKEND_LIB"
            KEPT=$((KEPT + 1))
        fi
    else
        # No bundled library — remove if it's a symlink to our managed location
        if [ -L "$BACKEND_LIB/llama-server" ]; then
            rm -rf "$BACKEND_LIB"
            echo "  Removed:    $BACKEND_LIB"
            REMOVED=$((REMOVED + 1))
        fi
    fi
fi

# ── Desktop entries ──────────────────────────

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
for desktop in prism-model-manager.desktop prism-model-manager-terminal.desktop \
               prism-model-manager-vllm.desktop; do
    if [ -f "$APPS_DIR/$desktop" ]; then
        rm -f "$APPS_DIR/$desktop"
        echo "  Removed:    $APPS_DIR/$desktop"
        REMOVED=$((REMOVED + 1))
    fi
done

# Omarchy
OMARCHY_APPS="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy/applications"
if [ -f "$OMARCHY_APPS/prism-model-manager.desktop" ]; then
    rm -f "$OMARCHY_APPS/prism-model-manager.desktop"
    echo "  Removed:    $OMARCHY_APPS/prism-model-manager.desktop"
    REMOVED=$((REMOVED + 1))
fi

echo ""
echo "=== Uninstall Complete ==="
echo "  Files removed:  $REMOVED"
echo "  Files kept:      $KEPT"
echo ""

if [ "$FLAG" = "--all" ]; then
    echo "--- Removing data directories ---"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/prism-model-manager"
    STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/prism-model-manager"
    BACKENDS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/prism-model-manager/backends"

    for dir in "$CONFIG_DIR" "$STATE_DIR"; do
        if [ -d "$dir" ]; then
            rm -rf "$dir"
            echo "  Removed:    $dir"
        fi
    done
    if [ -d "$BACKENDS_DIR" ]; then
        echo "  WARNING: Backends directory contains vLLM venv (~4GB) and downloaded backends."
        if command -v gum >/dev/null 2>&1; then
            if gum confirm "Remove backends directory (contains vLLM venv)?"; then
                rm -rf "$BACKENDS_DIR"
                echo "  Removed:    $BACKENDS_DIR"
            fi
        else
            echo "  Skipped:    $BACKENDS_DIR (use --all again to confirm)"
        fi
    fi
    echo ""
    echo "To also remove model files: rm -rf \$HOME/.local/share/prism-model-manager/models"
fi

echo "Configuration preserved: ${XDG_CONFIG_HOME:-$HOME/.config}/prism-model-manager"
echo "Logs preserved:          ${XDG_STATE_HOME:-$HOME/.local/state}/prism-model-manager"
echo ""
echo "To fully remove all data: $0 --all"