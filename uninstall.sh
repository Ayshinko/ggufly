#!/usr/bin/env bash
# uninstall.sh — GGUFly 1.0.0-dev Uninstaller
#
# Removes only files installed by GGUFly. Configuration, models, logs,
# downloaded backends and user data are preserved unless --all is specified.
#
# Legacy Prism Model Manager files installed by PMM v3/v4 are also removed.
#
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
PMM_BIN="$PREFIX/bin"
GGUFLY_SHARE_DIR="$PREFIX/share/ggufly"
FLAG="${1:-}"

REMOVED=0
KEPT=0

echo "=== GGUFly Uninstaller ==="

# ── Core GGUFly files ─────────────────────────

for name in ggufly ggufly-runtime-manager \
            ggufly-runtime-registry.sh \
            ggufly-model-detect.py \
            ggufly-gguf-info.py ggufly-backend-info.py \
            ggufly-runtime-manager-launcher; do
    target="$PMM_BIN/$name"
    if [ -f "$target" ] || [ -L "$target" ]; then
        rm -f "$target"
        echo "  Removed:    $target"
        REMOVED=$((REMOVED + 1))
    fi
done

# Symlinks
for sym in ggly pmm; do
    if [ -L "$PMM_BIN/$sym" ]; then
        rm -f "$PMM_BIN/$sym"
        echo "  Removed:    $PMM_BIN/$sym"
        REMOVED=$((REMOVED + 1))
    fi
done

# Legacy PMM files (v3/v4 era)
for deprecated in prism-model-manager prism-backend-manager \
                  prism-runtime-registry.sh \
                  prism-model-detect.py prism-gguf-info.py prism-backend-info.py \
                  prism-model-manager-launcher \
                  prism-backend-detect.py prism-lora-ab-score.py prism-vllm-autofit.py; do
    target="$PMM_BIN/$deprecated"
    if [ -f "$target" ] || [ -L "$target" ]; then
        rm -f "$target"
        echo "  Removed:    $target (legacy PMM)"
        REMOVED=$((REMOVED + 1))
    fi
done

# ── Share data ────────────────────────────────

if [ -d "$GGUFLY_SHARE_DIR" ]; then
    rm -rf "$GGUFLY_SHARE_DIR"
    echo "  Removed:    $GGUFLY_SHARE_DIR"
    REMOVED=$((REMOVED + 1))
fi

# Legacy PMM share data
LEGACY_SHARE_DIR="$PREFIX/share/prism-model-manager"
if [ -d "$LEGACY_SHARE_DIR" ]; then
    rm -rf "$LEGACY_SHARE_DIR"
    echo "  Removed:    $LEGACY_SHARE_DIR (legacy PMM)"
    REMOVED=$((REMOVED + 1))
fi

# ── Desktop entries ──────────────────────────

APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
for desktop in ggufly.desktop ggufly-terminal.desktop; do
    if [ -f "$APPS_DIR/$desktop" ]; then
        rm -f "$APPS_DIR/$desktop"
        echo "  Removed:    $APPS_DIR/$desktop"
        REMOVED=$((REMOVED + 1))
    fi
done

# Legacy PMM desktop entries
for desktop in prism-model-manager.desktop prism-model-manager-terminal.desktop; do
    if [ -f "$APPS_DIR/$desktop" ]; then
        rm -f "$APPS_DIR/$desktop"
        echo "  Removed:    $APPS_DIR/$desktop (legacy PMM)"
        REMOVED=$((REMOVED + 1))
    fi
done

# Omarchy
OMARCHY_APPS="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy/applications"
if [ -f "$OMARCHY_APPS/ggufly.desktop" ]; then
    rm -f "$OMARCHY_APPS/ggufly.desktop"
    echo "  Removed:    $OMARCHY_APPS/ggufly.desktop"
    REMOVED=$((REMOVED + 1))
fi
if [ -f "$OMARCHY_APPS/prism-model-manager.desktop" ]; then
    rm -f "$OMARCHY_APPS/prism-model-manager.desktop"
    echo "  Removed:    $OMARCHY_APPS/prism-model-manager.desktop (legacy PMM)"
    REMOVED=$((REMOVED + 1))
fi

echo ""
echo "=== Uninstall Complete ==="
echo "  Files removed:  $REMOVED"
echo "  Files kept:      $KEPT"
echo ""

if [ "$FLAG" = "--all" ]; then
    echo "--- Removing data directories ---"
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ggufly"
    STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ggufly"
    BACKENDS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/ggufly/backends"
    RUNTIMES_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ggufly/runtimes"

    for dir in "$CONFIG_DIR" "$STATE_DIR" "$RUNTIMES_DIR"; do
        if [ -d "$dir" ]; then
            rm -rf "$dir"
            echo "  Removed:    $dir"
        fi
    done
    if [ -d "$BACKENDS_DIR" ]; then
        echo "  WARNING: Backends directory contains downloaded llama.cpp runtimes."
        if command -v gum >/dev/null 2>&1; then
            if gum confirm "Remove backends directory?"; then
                rm -rf "$BACKENDS_DIR"
                echo "  Removed:    $BACKENDS_DIR"
            fi
        else
            echo "  Skipped:    $BACKENDS_DIR (use --all again to confirm)"
        fi
    fi

    echo ""
    echo "--- Removing legacy PMM data directories ---"
    for dir in \
        "${XDG_CONFIG_HOME:-$HOME/.config}/prism-model-manager" \
        "${XDG_STATE_HOME:-$HOME/.local/state}/prism-model-manager" \
        "${XDG_DATA_HOME:-$HOME/.local/share}/prism-model-manager/models"; do
        if [ -d "$dir" ]; then
            rm -rf "$dir"
            echo "  Removed:    $dir (legacy PMM)"
        fi
    done
    echo ""
    echo "To also remove model files: rm -rf \$HOME/.local/share/ggufly/models"
fi

echo ""
echo "Configuration preserved: ${XDG_CONFIG_HOME:-$HOME/.config}/ggufly"
echo "Logs preserved:          ${XDG_STATE_HOME:-$HOME/.local/state}/ggufly"
echo ""
echo "To fully remove all data: $0 --all"