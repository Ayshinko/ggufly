#!/usr/bin/env bash
# ggufly-runtime-registry.sh — GGUFly runtime registry library
#
# Provides functions to manage the runtime registry: registration, discovery,
# llama-server binary discovery, capability probing, and caching.
#
# Registry location: $RUNTIME_REGISTRY_DIR/*.conf
# Backend root:      $BACKENDS_DIR/llama.cpp/
#
# Each .conf file is a simple key=value Bash-safe snippet:
#   id=standard
#   display_name=Standard llama.cpp
#   folder=~/.local/share/ggufly/backends/llama.cpp/standard/current
#   managed=true
#   binary=<optional explicit llama-server path>
#   source_repo=https://github.com/ggml-org/llama.cpp
#   source_ref=b5098
#
# Capability cache: $STATE_DIR/capability-cache/*.json
#
set -uo pipefail

# ── Resolve paths ─────────────────────────────
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ggufly"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/ggufly"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"

RUNTIME_REGISTRY_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/ggufly/runtimes"
BACKENDS_DIR="$DATA_HOME/ggufly/backends"
LLAMA_BACKENDS_DIR="$BACKENDS_DIR/llama.cpp"
CAP_CACHE_DIR="$STATE_DIR/capability-cache"

mkdir -p "$RUNTIME_REGISTRY_DIR" "$LLAMA_BACKENDS_DIR" "$CAP_CACHE_DIR"

# ── Helpers ───────────────────────────────────

expanded_path() {
    local path="$1"
    # Expand ~ safely
    path="${path/#\~/$HOME}"
    # Resolve symlinks if file exists, otherwise just return expanded
    if [ -e "$path" ]; then
        readlink -f "$path" 2>/dev/null || echo "$path"
    else
        echo "$path"
    fi
}

conf_safe_value() {
    printf '%s' "$1" | sed 's/[^a-zA-Z0-9_\/.\-]/_/g'
}

sanitize_runtime_id() {
    # Only allow shell/path-safe characters
    printf '%s' "$1" | sed 's/[^a-zA-Z0-9._-]/_/g' | sed 's/^[^a-zA-Z0-9]/_/'
}

# ── Runtime Registry ──────────────────────────

# List all registered runtime IDs
runtime_registry_list_ids() {
    local ids=()
    for f in "$RUNTIME_REGISTRY_DIR"/*.conf; do
        [ -f "$f" ] || continue
        local id
        id=$(grep '^id=' "$f" 2>/dev/null | head -1 | cut -d= -f2-)
        [ -n "$id" ] && printf '%s\n' "$id"
    done
}

# Get a value from a runtime entry by ID and key
runtime_registry_get() {
    local id="$1" key="$2"
    local file="$RUNTIME_REGISTRY_DIR/$id.conf"
    [ -f "$file" ] || return 1
    grep "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2-
}

# Get display name for a runtime ID
runtime_display_name() {
    local id="$1"
    local name
    name=$(runtime_registry_get "$id" "display_name") || return 1
    printf '%s\n' "$name"
}

# Check if a runtime is managed
runtime_is_managed() {
    local id="$1"
    local managed
    managed=$(runtime_registry_get "$id" "managed") || return 1
    [ "$managed" = "true" ]
}

# Get runtime folder path
runtime_folder() {
    local id="$1"
    local folder
    folder=$(runtime_registry_get "$id" "folder") || return 1
    expanded_path "$folder"
}

# Get runtime binary path
runtime_binary() {
    local id="$1"
    local binary
    binary=$(runtime_registry_get "$id" "binary") || return 1
    [ -n "$binary" ] || return 1
    expanded_path "$binary"
}

# Get runtime source repo
runtime_source_repo() {
    local id="$1"
    runtime_registry_get "$id" "source_repo" || true
}

# Get runtime source ref
runtime_source_ref() {
    local id="$1"
    runtime_registry_get "$id" "source_ref" || true
}

# Register a runtime entry
runtime_registry_register() {
    local id="$1" display_name="$2" folder="$3" managed="${4:-false}" binary="${5:-}" source_repo="${6:-}" source_ref="${7:-}"

    local file="$RUNTIME_REGISTRY_DIR/$id.conf"
    local tmpfile
    tmpfile=$(mktemp "$file.XXXXXX") || return 1

    # Write all lines; guard optional statements with || true so set -e
    # does not abort the group and prevent the mv.
    {
        printf 'id=%s\n' "$id"
        printf 'display_name=%s\n' "$display_name"
        printf 'folder=%s\n' "$folder"
        printf 'managed=%s\n' "$managed"
        [ -z "$binary" ] || printf 'binary=%s\n' "$binary"
        [ -z "$source_repo" ] || printf 'source_repo=%s\n' "$source_repo"
        [ -z "$source_ref" ] || printf 'source_ref=%s\n' "$source_ref"
    } > "$tmpfile" && mv -f "$tmpfile" "$file"
}

# Remove a runtime entry from the registry (does NOT delete runtime files)
runtime_registry_unregister() {
    local id="$1"
    local file="$RUNTIME_REGISTRY_DIR/$id.conf"
    [ -f "$file" ] || return 1
    rm -f "$file"
}

# Update a specific key in a runtime entry
runtime_registry_update() {
    local id="$1" key="$2" value="$3"
    local file="$RUNTIME_REGISTRY_DIR/$id.conf"
    [ -f "$file" ] || return 1
    local tmpfile
    tmpfile=$(mktemp "$file.XXXXXX") || return 1

    # Read all lines, update the matching key
    local updated=0
    while IFS= read -r line; do
        if [[ "$line" == "${key}="* ]]; then
            printf '%s=%s\n' "$key" "$value"
            updated=1
        else
            printf '%s\n' "$line"
        fi
    done < "$file" > "$tmpfile"

    [ "$updated" -eq 0 ] && printf '%s=%s\n' "$key" "$value" >> "$tmpfile"
    mv -f "$tmpfile" "$file"
}

# ── Managed Runtime Initialization ────────────

# Initialize built-in managed runtime entries
runtime_registry_init_builtin() {
    local backends_dir="$BACKENDS_DIR/llama.cpp"

    # Standard llama.cpp
    local std_id="standard"
    if [ ! -f "$RUNTIME_REGISTRY_DIR/$std_id.conf" ]; then
        runtime_registry_register \
            "$std_id" \
            "Standard llama.cpp" \
            "$backends_dir/standard/current" \
            "true"
    fi

    # PrismML / Bonsai
    local prism_id="prism"
    if [ ! -f "$RUNTIME_REGISTRY_DIR/$prism_id.conf" ]; then
        runtime_registry_register \
            "$prism_id" \
            "PrismML / Bonsai" \
            "$backends_dir/prism/current" \
            "true"
    fi

    # Mirai S
    local mirai_id="mirai"
    if [ ! -f "$RUNTIME_REGISTRY_DIR/$mirai_id.conf" ]; then
        runtime_registry_register \
            "$mirai_id" \
            "Mirai S" \
            "$backends_dir/mirai/current" \
            "true"
    fi
}

# ── llama-server Discovery ────────────────────

# Find llama-server in a given folder
# Returns the path if exactly one valid executable found
# Returns empty if none or multiple found (caller should handle)
discover_llama_server_in_folder() {
    local folder="$1"
    local expanded
    expanded=$(expanded_path "$folder")
    [ -d "$expanded" ] || return 1

    local candidates=()
    local candidate
    for candidate in \
        "$expanded/bin/llama-server" \
        "$expanded/build/bin/llama-server" \
        "$expanded/build/bin/Release/llama-server" \
        "$expanded/llama-server" \
        ; do
        if [ -x "$candidate" ] && [ -f "$candidate" ]; then
            candidates+=("$candidate")
        fi
    done

    [ "${#candidates[@]}" -eq 0 ] && return 1

    # If exactly one, return it
    if [ "${#candidates[@]}" -eq 1 ]; then
        printf '%s\n' "${candidates[0]}"
        return 0
    fi

    # Multiple candidates: return all on separate lines for caller to resolve
    printf '%s\n' "${candidates[@]}"
    return 2  # Multiple
}

# Check if a binary is a valid llama-server
is_valid_llama_server() {
    local binary="$1"
    [ -x "$binary" ] && [ -f "$binary" ] || return 1
    # Quick version check
    timeout 5 "$binary" --version 2>/dev/null | grep -qi 'llama' && return 0
    # Fallback: check if --help works
    timeout 5 "$binary" --help 2>/dev/null | grep -qi 'ctx-size\|ngl\|model\|port' && return 0
    return 1
}

# ── Capability Probing ────────────────────────

# Get a cache key for a binary (realpath + mtime + size)
capability_cache_key() {
    local binary="$1"
    local real_path
    real_path=$(readlink -f "$binary" 2>/dev/null) || return 1
    local mtime size
    mtime=$(stat -c '%Y' "$real_path" 2>/dev/null) || return 1
    size=$(stat -c '%s' "$real_path" 2>/dev/null) || return 1
    printf '%s' "$real_path" | sha256sum | awk '{print $1}'
    printf '_mtime_%s_size_%s' "$mtime" "$size"
}

# Cache file for capabilities
capability_cache_file() {
    local binary="$1"
    local key
    key=$(capability_cache_key "$binary") || return 1
    printf '%s/%s.json\n' "$CAP_CACHE_DIR" "$key"
}

# Probe a llama-server binary for capabilities
# Returns JSON with advertised flags and metadata
probe_capabilities() {
    local binary="$1" use_cache="${2:-true}"

    # Check cache
    if [ "$use_cache" = "true" ]; then
        local cache_file
        cache_file=$(capability_cache_file "$binary") && [ -f "$cache_file" ] && {
            cat "$cache_file"
            return 0
        }
    fi

    # Get version
    local version=""
    version=$(timeout 5 "$binary" --version 2>&1 | head -5) || version="unknown"

    # Get help output
    local help_text=""
    help_text=$(timeout 10 "$binary" --help 2>&1) || {
        echo '{"error":"help failed","version":"'"$version"'"}'
        return 1
    }

    # Parse capabilities using prism-backend-info.py
    local capabilities
    capabilities=$(echo "$help_text" | python3 "$SCRIPT_DIR/prism-backend-info.py" 2>/dev/null) || {
        # Fallback: minimal capability detection
        capabilities='{}'
    }

    # Detect specific capabilities
    local has_fa="false"
    echo "$help_text" | grep -qi '\-\-flash-attn\|-fa ' && has_fa="true"

    local has_mtp="false"
    echo "$help_text" | grep -qi '\-\-spec-type\|--draft-max\|--spec-draft-n-max\|MTP' && has_mtp="true"

    local has_jinja="false"
    echo "$help_text" | grep -qi '\-\-jinja' && has_jinja="true"

    local has_mmproj="false"
    echo "$help_text" | grep -qi '\-\-mmproj' && has_mmproj="true"

    local has_lora="false"
    echo "$help_text" | grep -qi '\-\-lora' && has_lora="true"

    local has_cache_type="false"
    echo "$help_text" | grep -qi '\-\-cache-type' && has_cache_type="true"

    local has_parallel="false"
    echo "$help_text" | grep -qi '\-np \|--parallel' && has_parallel="true"

    # Detect known special codec support from version/help text
    local known_special_codecs="[]"
    if echo "$version" | grep -qi 'prism\|bonsai\|ptq1_0\|pq2_0\|tq1_0'; then
        known_special_codecs='["PTQ1_0","PQ2_0","TQ1_0","TQ2_0"]'
    fi
    if echo "$version" | grep -qi 'mirai'; then
        known_special_codecs=$(echo "$known_special_codecs" | python3 -c "
import json, sys
codecs = json.load(sys.stdin)
codecs.extend(['Mirai S'])
print(json.dumps(list(set(codecs))))
" 2>/dev/null || echo '["Mirai S"]')
    fi

    local result
    result=$(cat <<JSON
{
    "version": $(echo "$version" | python3 -c "import json,sys; print(json.dumps(sys.stdin.read().strip()))"),
    "binary": "$binary",
    "realpath": "$(readlink -f "$binary" 2>/dev/null || echo "$binary")",
    "parsed_options": $capabilities,
    "capabilities": {
        "flash_attention": $has_fa,
        "mtp": $has_mtp,
        "jinja": $has_jinja,
        "mmproj": $has_mmproj,
        "lora": $has_lora,
        "cache_type": $has_cache_type,
        "parallel_slots": $has_parallel
    },
    "known_special_codecs": $known_special_codecs,
    "probed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
    )

    # Write cache
    local cache_file
    cache_file=$(capability_cache_file "$binary") && {
        echo "$result" > "$cache_file"
    }

    echo "$result"
}

# Display capabilities in a human-friendly way
probe_capabilities_formatted() {
    local binary="$1"
    local caps
    caps=$(probe_capabilities "$binary") || {
        echo "Failed to probe: $binary"
        return 1
    }

    echo "Version: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('version','unknown'))")"
    echo "Flash Attention: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('flash_attention',False))")"
    echo "MTP/Speculative: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('mtp',False))")"
    echo "Jinja: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('jinja',False))")"
    echo "MMProj/Vision: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('mmproj',False))")"
    echo "LoRA: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('lora',False))")"
    echo "Cache Type: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('cache_type',False))")"
    echo "Parallel Slots: $(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('capabilities',{}).get('parallel_slots',False))")"

    local special
    special=$(echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); codecs=d.get('known_special_codecs',[]); print(', '.join(codecs) if codecs else 'none')")
    echo "Special Codecs: $special"
}

# Invalidate capability cache for a binary
invalidate_capability_cache() {
    local binary="$1"
    local cache_file
    cache_file=$(capability_cache_file "$binary" 2>/dev/null) || return 0
    rm -f "$cache_file"
}

# Clear all capability caches
clear_capability_cache() {
    rm -f "$CAP_CACHE_DIR"/*.json
}

# ── Compatibility Model ────────────────────────

# Evaluate compatibility between a codec and a runtime
# Returns: KNOWN_COMPATIBLE, KNOWN_INCOMPATIBLE, UNKNOWN
evaluate_compatibility() {
    local codec="${1:-}" runtime_id="${2:-}"

    [ -n "$codec" ] || { echo "UNKNOWN"; return 0; }
    [ -n "$runtime_id" ] || { echo "UNKNOWN"; return 0; }

    local codec_upper
    codec_upper=$(echo "$codec" | tr '[:lower:]' '[:upper:]')

    # Standard GGUF codecs are compatible with any llama.cpp runtime
    case "$codec_upper" in
        F32|F16|BF16|Q4_0|Q4_1|Q5_0|Q5_1|Q8_0|Q2_K|Q3_K_S|Q3_K_M|Q3_K_L|Q4_K_S|Q4_K_M|Q5_K_S|Q5_K_M|Q6_K)
            echo "KNOWN_COMPATIBLE"
            return 0
            ;;
        IQ1_S|IQ1_M|IQ2_XXS|IQ2_XS|IQ2_S|IQ2_M|IQ3_XS|IQ3_XXS|IQ3_S|IQ3_M|IQ4_NL|IQ4_XS)
            echo "KNOWN_COMPATIBLE"
            return 0
            ;;
    esac

    # Bonsai/Prism-specific codecs
    case "$codec_upper" in
        PTQ1_0|PQ2_0|TQ1_0|TQ2_0)
            local runtime_name
            runtime_name=$(runtime_display_name "$runtime_id" 2>/dev/null || echo "")
            if echo "$runtime_name" | grep -qi 'prism\|bonsai'; then
                echo "KNOWN_COMPATIBLE"
            elif runtime_is_managed "$runtime_id" 2>/dev/null && [ "$runtime_id" = "prism" ]; then
                echo "KNOWN_COMPATIBLE"
            else
                # Check capability cache for special codec support
                local binary
                binary=$(runtime_binary "$runtime_id" 2>/dev/null) || {
                    echo "UNKNOWN"
                    return 0
                }
                local caps
                caps=$(probe_capabilities "$binary" 2>/dev/null) || {
                    echo "UNKNOWN"
                    return 0
                }
                if echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print('PTQ1_0' in d.get('known_special_codecs',[]))" | grep -q true; then
                    echo "KNOWN_COMPATIBLE"
                else
                    echo "KNOWN_INCOMPATIBLE"
                fi
            fi
            return 0
            ;;
    esac

    # Mirai S codec
    case "$codec_upper" in
        MIRAI*|MS_V*)
            local runtime_name
            runtime_name=$(runtime_display_name "$runtime_id" 2>/dev/null || echo "")
            if echo "$runtime_name" | grep -qi 'mirai'; then
                echo "KNOWN_COMPATIBLE"
            elif runtime_is_managed "$runtime_id" 2>/dev/null && [ "$runtime_id" = "mirai" ]; then
                echo "KNOWN_COMPATIBLE"
            else
                local binary
                binary=$(runtime_binary "$runtime_id" 2>/dev/null) || {
                    echo "UNKNOWN"
                    return 0
                }
                local caps
                caps=$(probe_capabilities "$binary" 2>/dev/null) || {
                    echo "UNKNOWN"
                    return 0
                }
                if echo "$caps" | python3 -c "import json,sys; d=json.load(sys.stdin); print('Mirai S' in d.get('known_special_codecs',[]))" | grep -q true; then
                    echo "KNOWN_COMPATIBLE"
                else
                    echo "KNOWN_INCOMPATIBLE"
                fi
            fi
            return 0
            ;;
    esac

    # Unknown codec + known runtime = UNKNOWN (not incompatible!)
    echo "UNKNOWN"
    return 0
}

# Get a recommended runtime for a codec (informational only, does NOT change selection)
recommend_runtime_for_codec() {
    local codec="${1:-}"
    [ -n "$codec" ] || return 1

    local codec_upper
    codec_upper=$(echo "$codec" | tr '[:lower:]' '[:upper:]')

    case "$codec_upper" in
        PTQ1_0|PQ2_0|TQ1_0|TQ2_0)
            echo "PrismML / Bonsai"
            return 0
            ;;
        MIRAI*|MS_V*)
            echo "Mirai S"
            return 0
            ;;
        *)
            echo "Standard llama.cpp"
            return 0
            ;;
    esac
}

# ── External Runtime Registration flow ────────

# Register an external runtime folder
register_external_runtime() {
    local folder="$1" display_name="${2:-}" binary="${3:-}"

    local expanded
    expanded=$(expanded_path "$folder")
    [ -d "$expanded" ] || { echo "ERROR: Directory does not exist: $folder" >&2; return 1; }

    # Generate a unique ID
    local id
    if [ -n "$display_name" ]; then
        id=$(sanitize_runtime_id "$display_name")
    else
        id=$(sanitize_runtime_id "custom-$(date +%s)")
    fi

    # Make sure ID is unique
    local suffix=0
    while [ -f "$RUNTIME_REGISTRY_DIR/$id.conf" ]; do
        suffix=$((suffix + 1))
        if [ -n "$display_name" ]; then
            id=$(sanitize_runtime_id "${display_name}-${suffix}")
        else
            id="custom-$(date +%s)-${suffix}"
        fi
    done

    runtime_registry_register \
        "$id" \
        "${display_name:-Custom Runtime $id}" \
        "$expanded" \
        "false" \
        "$binary"

    printf '%s\n' "$id"
}

# Validate an external runtime
validate_external_runtime() {
    local id="$1"
    local folder binary
    folder=$(runtime_folder "$id") || return 1
    [ -d "$folder" ] || return 1

    # Check for binary
    binary=$(runtime_binary "$id" 2>/dev/null) || {
        binary=$(discover_llama_server_in_folder "$folder" 2>/dev/null) || {
            # Could be multiple or none - try to find any
            local found
            found=$(find "$folder" -name "llama-server" -type f -executable 2>/dev/null | head -1)
            [ -n "$found" ] || return 1
            binary="$found"
        }
    }
    [ -x "$binary" ] || return 1

    # Update binary in registry if not set
    if ! runtime_registry_get "$id" "binary" >/dev/null 2>&1; then
        runtime_registry_update "$id" "binary" "$binary"
    fi

    # Validate it works
    is_valid_llama_server "$binary" || return 1

    # Probe capabilities (cached)
    probe_capabilities "$binary" >/dev/null 2>&1 || true

    return 0
}

# ── Runtime Management ────────────────────────

# Get the installed version of a managed runtime
runtime_installed_version() {
    local id="$1"
    local manifest
    manifest=$(runtime_folder "$id")/manifest.json
    [ -f "$manifest" ] || return 1
    python3 -c "import json; print(json.load(open('$manifest')).get('source_ref','unknown'))" 2>/dev/null || echo "unknown"
}

# Check if a managed runtime is installed
runtime_is_installed() {
    local id="$1"
    runtime_is_managed "$id" || return 1

    local folder
    folder=$(runtime_folder "$id" 2>/dev/null) || return 1
    local expanded
    expanded=$(expanded_path "$folder")
    [ -d "$expanded" ] || return 1

    # Check for binary
    local binary
    binary=$(runtime_binary "$id" 2>/dev/null) || {
        binary=$(discover_llama_server_in_folder "$expanded" 2>/dev/null) || return 1
    }
    [ -x "$binary" ] || return 1

    # Verify it responds
    timeout 3 "$binary" --version >/dev/null 2>&1
}

# ── Main dispatcher when called directly ──────
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    case "${1:-}" in
        list)
            runtime_registry_list_ids
            ;;
        get)
            [ -z "${2:-}" ] && { echo "Usage: $0 get <id> [key]" >&2; exit 1; }
            if [ -n "${3:-}" ]; then
                runtime_registry_get "$2" "$3"
            else
                cat "$RUNTIME_REGISTRY_DIR/$2.conf" 2>/dev/null || echo "not found"
            fi
            ;;
        register)
            local id="${2:-}" name="${3:-}" folder="${4:-}" managed="${5:-false}"
            [ -z "$id" ] && { echo "Usage: $0 register <id> <name> <folder> [managed]" >&2; exit 1; }
            runtime_registry_register "$id" "$name" "$folder" "$managed"
            echo "Registered: $id"
            ;;
        unregister)
            [ -z "${2:-}" ] && { echo "Usage: $0 unregister <id>" >&2; exit 1; }
            runtime_registry_unregister "$2"
            echo "Unregistered: $2"
            ;;
        init)
            runtime_registry_init_builtin
            echo "Built-in runtimes initialized."
            ;;
        discover)
            [ -z "${2:-}" ] && { echo "Usage: $0 discover <folder>" >&2; exit 1; }
            discover_llama_server_in_folder "$2"
            ;;
        probe)
            [ -z "${2:-}" ] && { echo "Usage: $0 probe <binary>" >&2; exit 1; }
            probe_capabilities "$2" "${3:-true}"
            ;;
        probe-formatted)
            [ -z "${2:-}" ] && { echo "Usage: $0 probe-formatted <binary>" >&2; exit 1; }
            probe_capabilities_formatted "$2"
            ;;
        compat)
            [ -z "${2:-}" ] && { echo "Usage: $0 compat <codec> <runtime_id>" >&2; exit 1; }
            evaluate_compatibility "$2" "${3:-}"
            ;;
        recommend)
            [ -z "${2:-}" ] && { echo "Usage: $0 recommend <codec>" >&2; exit 1; }
            recommend_runtime_for_codec "$2"
            ;;
        validate)
            [ -z "${2:-}" ] && { echo "Usage: $0 validate <id>" >&2; exit 1; }
            validate_external_runtime "$2" && echo "Valid: $2" || echo "Invalid: $2"
            ;;
        cache-clear)
            clear_capability_cache
            echo "Capability cache cleared."
            ;;
        installed)
            runtime_is_installed "${2:-}" && echo "installed" || echo "not_installed"
            ;;
        version)
            runtime_installed_version "${2:-}" || echo "unknown"
            ;;
        *)
            echo "Usage: $0 <command> [args]"
            echo ""
            echo "Registry commands:"
            echo "  list                          List registered runtime IDs"
            echo "  get <id> [key]                Get runtime value (or all lines)"
            echo "  register <id> <name> <folder> [managed]  Register runtime"
            echo "  unregister <id>               Remove registry entry (not files)"
            echo "  init                          Initialize built-in runtimes"
            echo ""
            echo "Discovery commands:"
            echo "  discover <folder>             Find llama-server in folder"
            echo "  probe <binary> [cache]        Probe capabilities (JSON)"
            echo "  probe-formatted <binary>       Probe capabilities (human)"
            echo ""
            echo "Compatibility commands:"
            echo "  compat <codec> <runtime_id>   Evaluate compatibility"
            echo "  recommend <codec>             Recommend runtime for codec"
            echo ""
            echo "Validation commands:"
            echo "  validate <id>                 Validate external runtime"
            echo "  installed <id>                Check if managed runtime installed"
            echo "  version <id>                  Get installed version"
            echo "  cache-clear                   Clear capability cache"
            exit 1
            ;;
    esac
fi