#!/usr/bin/env bash
# build-release.sh — Build PMM 3.5.1 Release Archive
#
# Usage: ./packaging/build-release.sh [--offline] [OUTDIR]
#
# Modes:
#   standard (default):  PMM scripts + compatibility manifest.
#                         llama.cpp and vLLM downloaded on first use.
#                         Small archive (~200 KB).
#
#   --offline:           Standard + bundled llama.cpp CUDA build.
#                         Larger archive (~130 MB + PMM scripts).
#                         Suitable for systems without internet at install time.
#
# Output (in OUTDIR, default dist/):
#   prism-model-manager-3.5.1-linux-x86_64-standard.tar.gz   (~200 KB)
#   prism-model-manager-3.5.1-linux-x86_64-offline.tar.gz    (~130 MB)
#   ...sha256
#   ...sha256.manifest
#
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
OUTDIR="${2:-$ROOT/dist}"
OFFLINE=0

if [ "${1:-}" = "--offline" ]; then
    OFFLINE=1
    ARCHIVE_NAME="prism-model-manager-3.0-linux-x86_64-cuda"
elif [ -n "${1:-}" ] && [ "${1#--}" != "offline" ]; then
    OUTDIR="$1"
fi

PMM_VER=$(cd "$ROOT" && git describe --tags --always 2>/dev/null || echo "3.4.0")
STANDARD_NAME="prism-model-manager-${PMM_VER}-linux-x86_64-standard"
OFFLINE_NAME="prism-model-manager-${PMM_VER}-linux-x86_64-offline"

echo "=== PMM ${PMM_VER} Release Builder ==="
echo "Root:      $ROOT"
echo "Output:    $OUTDIR"
echo "Mode:      $([ "$OFFLINE" = 1 ] && echo 'OFFLINE (bundled llama.cpp)' || echo 'STANDARD (online-only)')"
echo ""

# ── 1. Validate PMM source ───────────────────

[ -d "$ROOT/bin" ] || { echo "ERROR: PMM bin/ not found"; exit 1; }
[ -f "$ROOT/bin/prism-model-manager" ] || { echo "ERROR: prism-model-manager missing"; exit 1; }
[ -f "$ROOT/bin/prism-backend-manager" ] || { echo "ERROR: prism-backend-manager missing"; exit 1; }
[ -f "$ROOT/compatibility.json" ] || { echo "ERROR: compatibility.json missing"; exit 1; }
echo "PMM source:     OK"

# ── 2. Staging ────────────────────────────────

STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

build_archive() {
    local archive_name="$1" include_backend="$2"
    local archive_dir="$STAGING/$archive_name"

    rm -rf "$archive_dir"
    mkdir -p "$archive_dir/bin" "$archive_dir/lib" "$archive_dir/share/doc" \
             "$archive_dir/share/manuals"

    echo "--- Building: $archive_name ---"

    # PMM application files
    cp "$ROOT/bin/prism-model-manager" "$archive_dir/bin/"
    cp "$ROOT/bin/prism-backend-manager" "$archive_dir/bin/"
    for py in prism-backend-detect.py prism-model-detect.py \
              prism-lora-ab-score.py prism-gguf-info.py prism-backend-info.py; do
        [ -f "$ROOT/bin/$py" ] && cp "$ROOT/bin/$py" "$archive_dir/bin/"
    done
    echo "  PMM scripts: OK"

    # Compatibility manifest
    cp "$ROOT/compatibility.json" "$archive_dir/compatibility.json"
    echo "  Manifest:    OK"

    # License
    cp "$ROOT/LICENSE" "$archive_dir/LICENSE"

    # Install scripts
    cp "$ROOT/install.sh" "$archive_dir/install.sh"
    cp "$ROOT/uninstall.sh" "$archive_dir/uninstall.sh"

    # Documentation
    cp "$ROOT/README.md" "$archive_dir/share/doc/README.md" 2>/dev/null || true
    cp "$ROOT/CHANGELOG.md" "$archive_dir/share/doc/CHANGELOG.md" 2>/dev/null || true
    cp "$ROOT/TESTING.md" "$archive_dir/share/doc/TESTING.md" 2>/dev/null || true
    cp "$ROOT/examples/config.env.example" "$archive_dir/share/doc/" 2>/dev/null || true

    # Version file
    echo "$PMM_VER" > "$archive_dir/VERSION"

    # Offline: bundle llama.cpp backend
    if [ "$include_backend" = 1 ]; then
        local backend_src="${BONSAI_KERNEL_TEST:-${PWD}/../bonsai-kernel-test}/build-cuda-pr218/bin"
        local local_prism="${PWD}/../prism-llama/build-cuda/bin"

        if [ -f "$backend_src/llama-server" ]; then
            echo "  Bundling backend from: $backend_src"
            cp "$backend_src/llama-server" "$archive_dir/lib/llama-server"
            chmod 755 "$archive_dir/lib/llama-server"

            # Copy shared libraries
            for lib in "$backend_src"/lib*.so*; do
                [ -f "$lib" ] || continue
                cp -a "$lib" "$archive_dir/lib/"
            done

            # Verify
            BACKEND_VER=$("$archive_dir/lib/llama-server" --version 2>&1 | head -1) || {
                echo "  WARNING: Bundled backend may have missing dependencies"
                ldd "$archive_dir/lib/llama-server" 2>&1 | grep "not found" || true
            }
            echo "  Backend:     ${BACKEND_VER:-version unknown}"
        elif [ -f "$local_prism/llama-server" ]; then
            echo "  Bundling backend from: $local_prism"
            cp "$local_prism/llama-server" "$archive_dir/lib/llama-server"
            chmod 755 "$archive_dir/lib/llama-server"
            echo "  Backend:     (local build)"
        else
            echo "  WARNING: No llama-server found to bundle."
            echo "  Set BONSAI_KERNEL_TEST or provide build-cuda-pr218/bin/llama-server"
            mkdir -p "$archive_dir/lib"
        fi

        # Bundle attribution
        cat > "$archive_dir/share/doc/LICENSE-bundled-backend" << 'LICEOF'
Bundled llama-server Backend — Attribution
===========================================
See the README and PMM documentation for full attribution.
This package includes a compiled llama-server binary from
the PrismML-Eng/llama.cpp fork (MIT licensed).
LICEOF
    fi

    # Create archive
    mkdir -p "$OUTDIR"
    cd "$STAGING"

    tar czf "$OUTDIR/$archive_name.tar.gz" "$archive_name"
    cd "$OUTDIR"
    sha256sum "$archive_name.tar.gz" > "$archive_name.tar.gz.sha256"

    # File manifest
    cd "$STAGING/$archive_name"
    find . -type f | sort | while read -r f; do
        sha256sum "$f" >> "$OUTDIR/$archive_name.sha256.manifest"
    done

    local size
    size=$(du -h "$OUTDIR/$archive_name.tar.gz" | awk '{print $1}')
    echo ""
    echo "  Archive:    $OUTDIR/$archive_name.tar.gz"
    echo "  Size:       $size"
    echo "  SHA256:     $(cat "$OUTDIR/$archive_name.tar.gz.sha256" | awk '{print $1}')"
    echo ""
}

# ── 3. Build archives ────────────────────────

build_archive "$STANDARD_NAME" 0

if [ "$OFFLINE" = 1 ]; then
    build_archive "$OFFLINE_NAME" 1
fi

echo "=== Build Complete ==="
echo ""
echo "Standard:       $OUTDIR/$STANDARD_NAME.tar.gz"
[ "$OFFLINE" = 1 ] && echo "Offline:        $OUTDIR/$OFFLINE_NAME.tar.gz"
echo ""
echo "To install:"
echo "  tar xzf $STANDARD_NAME.tar.gz"
echo "  cd $STANDARD_NAME"
echo "  ./install.sh"
[ "$OFFLINE" = 1 ] && echo "  or: ./install.sh --offline"
echo ""
echo "Verification:"
echo "  sha256sum -c $STANDARD_NAME.tar.gz.sha256"
echo ""
echo "Contents:"
echo "  cat $STANDARD_NAME.sha256.manifest"