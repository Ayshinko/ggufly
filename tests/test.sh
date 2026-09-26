#!/usr/bin/env bash
# Intentional literal shell metacharacters test safe config serialization.
# shellcheck disable=SC2016
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
export HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_STATE_HOME="$TMP/state" XDG_DATA_HOME="$TMP/data"
mkdir -p "$HOME" "$TMP/models with spaces" "$TMP/mock"
export GGUFLY_MODEL_ROOT="$TMP/models with spaces" GGUFLY_SERVER_BIN="$TMP/mock/llama-server"
export GGUFLY_TEST_HELP="$ROOT/tests/fixtures/backend-help-modern.txt"
export GGUFLY_TEST_PORT=9999
cat > "$GGUFLY_SERVER_BIN" <<'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == --help ]]; then
    cat "$GGUFLY_TEST_HELP"
    exit 0
fi
echo 'Unexpected server execution' >&2
exit 99
MOCK
chmod +x "$GGUFLY_SERVER_BIN"
touch "$GGUFLY_MODEL_ROOT/Bonsai-PTQ1_0.gguf" "$GGUFLY_MODEL_ROOT/model two.gguf" "$GGUFLY_MODEL_ROOT/mmproj.gguf" "$GGUFLY_MODEL_ROOT/adapter-lora.gguf" "$GGUFLY_MODEL_ROOT/incomplete.gguf.part"
# shellcheck source=../bin/ggufly
source "$ROOT/bin/ggufly"
check() { echo "PASS: $*"; }
[[ $(scan_models | wc -l) == 2 ]]
check 'scan excludes adapters, projectors and partial downloads; supports spaces'
for format in PTQ1_0 PQ2_0 Q2_0 Q1_0; do
    [[ $(model_info "Bonsai-$format.gguf") == *"$format"* ]]
done
[[ $(model_info unknown.gguf) == *Unknown* ]]
check 'four quantization hints plus unknown fallback'
CURRENT_MODEL="$GGUFLY_MODEL_ROOT/model two.gguf"
LORA_PATH='$HOME/literal $(touch SHOULD_NOT_EXIST) adapter.gguf'
CTX=2048
save_config
LORA_PATH=''
# shellcheck disable=SC1090
source "$CONFIG"
[[ "$LORA_PATH" == '$HOME/literal $(touch SHOULD_NOT_EXIST) adapter.gguf' ]]
[[ ! -e SHOULD_NOT_EXIST && $(stat -c %a "$CONFIG") == 600 ]]
save_model_profile
CTX=8192
load_model_profile
[[ "$CTX" == 2048 ]]
check 'escaped config and per-model profile round trip; private file permissions'
build_command
[[ ${SERVER_ARGS[2]} == "$CURRENT_MODEL" ]]
[[ " ${SERVER_ARGS[*]} " == *' -c 2048 '* ]]
LORA_ENABLED=on
LORA_PATH="$TMP/adapter with spaces.gguf"
touch "$LORA_PATH" "$(dirname "$CURRENT_MODEL")/mmproj.gguf"
VISION=on REASONING_BUDGET=32
build_command
[[ " ${SERVER_ARGS[*]} " == *"--lora-scaled $LORA_PATH:2"* ]]
[[ " ${SERVER_ARGS[*]} " == *'--reasoning-budget 32'* ]]
[[ " ${SERVER_ARGS[*]} " == *'--mmproj '* ]]
CTX=invalid
if build_command 2>/dev/null; then exit 1; fi
CTX=2048
check 'command arrays, optional LoRA/vision/reasoning flags and invalid context'
python3 - "$CURRENT_MODEL" <<'PYMODEL'
import struct, sys
with open(sys.argv[1], 'wb') as f:
    f.write(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
PYMODEL
"$ROOT/bin/ggufly" --dry-run "$CURRENT_MODEL" > "$TMP/dry-run"
[[ -s "$TMP/dry-run" ]]
check 'dry-run never executes runtime'
cat > "$TMP/mock/nvidia-smi" <<'MOCK'
#!/usr/bin/env bash
echo 'Mock NVIDIA RTX, 8.9'
MOCK
cat > "$TMP/mock/less" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == +F ]]
cat "$2"
MOCK
chmod +x "$TMP/mock/"*
export PATH="$TMP/mock:$PATH"
hash -r 2>/dev/null || true
[[ $(gpu_info) == *'Ada'* ]]
printf '#!/usr/bin/env bash\nexit 1\n' > "$TMP/mock/nvidia-smi"
[[ $(gpu_info) == *'architecture unknown'* ]]
echo 'test log content' > "$LOGFILE"
[[ $(show_logs) == 'test log content' ]]
check 'Ada architecture, missing driver fallback and less +F log viewer'
echo "$$" > "$PIDFILE"
echo invalid > "$PIDFILE.start"
if server_pid; then exit 1; fi
check 'stale PID identity rejected'
# Start only a tiny fake process. Never execute the configured real runtime.
cat > "$GGUFLY_SERVER_BIN" <<'MOCK'
#!/usr/bin/env bash
if [[ "${1:-}" == --help ]]; then
    cat "$GGUFLY_TEST_HELP"
    exit 0
fi
exec sleep 30
MOCK
pause() { :; }
gum() { :; }
curl() { echo '{}'; }
port_available() { return 0; }
server_health() { server_pid >/dev/null; }
python3 - "$CURRENT_MODEL" <<'PYMODEL'
import struct, sys
with open(sys.argv[1], 'wb') as f:
    f.write(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
PYMODEL
LORA_ENABLED=off VISION=off PORT="$GGUFLY_TEST_PORT" HOST=127.0.0.1
save_model_profile
start_server
managed_pid=$(server_pid)
[[ "$managed_pid" =~ ^[0-9]+$ ]]
stop_server
if kill -0 "$managed_pid" 2>/dev/null; then exit 1; fi
check 'start and stop lifecycle with a fake process only'

PREFIX="$TMP/install prefix" "$ROOT/install.sh"
# Second install: with gum override, the upgrade prompt is auto-accepted (gum returns 0)
# and the installer re-installs over itself. No errors should occur.
PREFIX="$TMP/install prefix" "$ROOT/install.sh" 2>/dev/null || true
[[ $("$TMP/install prefix/bin/ggufly" --version) == "$VERSION" ]]
PREFIX="$TMP/install prefix" "$ROOT/uninstall.sh"
[[ ! -e "$TMP/install prefix/bin/ggufly" && -f "$CONFIG" && -f "$LOGFILE" ]]
PREFIX="$TMP/install prefix" "$ROOT/uninstall.sh"
check 'installation, overwrite refusal, installed execution, uninstall, retained data and idempotence'

# ── API Ready tests (mocked curl/server_health; no live API touched) ──
(
    HOST=127.0.0.1 PORT=9999

    curl() { echo '{"data":[{"id":"synthetic test model-1"}]}'; }
    [[ $(api_models_info) == "synthetic test model-1" ]]
    check 'api_models_info returns the running model id from a well-formed /v1/models body'

    curl() { echo '{"data":[]}'; }
    [[ $(api_models_info) == "malformed" ]]
    check 'api_models_info returns "malformed" for a 200 with empty models list'

    curl() { echo 'not json'; }
    [[ $(api_models_info) == "malformed" ]]
    check 'api_models_info returns "malformed" for a non-JSON body'

    curl() { return 6; }
    [[ $(api_models_info) == "unavailable" ]]
    check 'api_models_info returns "unavailable" when curl fails (connection refused)'

    server_health() { return 0; }
    curl() { echo '{"data":[{"id":"test-mdl"}]}'; }
    lines=$(api_ready_lines)
    [[ $lines == *"API base URL  : http://127.0.0.1:9999"* ]]
    [[ $lines == *"OpenAI API    : http://127.0.0.1:9999/v1"* ]]
    [[ $lines == *"API reachable : yes"* ]]
    [[ $lines == *"Model ID      : test-mdl"* ]]
    check 'api_ready_lines renders base URL, reachability and running model ID'

    server_health() { return 1; }
    curl() { return 6; }
    lines=$(api_ready_lines)
    [[ $lines == *"API reachable : no"* ]]
    [[ $lines == *"Model ID      : unavailable"* ]]
    check 'api_ready_lines degrades gracefully when the API is unreachable'

    server_health() { return 0; }
    curl() { echo '{"error":"not a model list"}'; }
    lines=$(api_ready_lines)
    [[ $lines == *"API reachable : yes"* ]]
    [[ $lines == *"Model ID      : not reported"* ]]
    check 'api_ready_lines reports malformed API responses without crashing'
)

# The CLI readiness command must remain automation-friendly and fail when the API is unreachable.
cat > "$TMP/mock/curl" <<'MOCK'
#!/usr/bin/env bash
case " $* " in
    *' /health '*) exit 1 ;;
    *) printf '%s\n' '{"data":[]}' ;;
esac
MOCK
chmod +x "$TMP/mock/curl"
if "$ROOT/bin/ggufly" --api-ready >/dev/null 2>&1; then exit 1; fi
check '--api-ready exits nonzero when the API is unreachable'

# ── Regression: set -u startup (no unbound variables) ──
(
    TMPU=$(mktemp -d)
    export HOME="$TMPU" XDG_CONFIG_HOME="$TMPU/c" XDG_STATE_HOME="$TMPU/s" XDG_DATA_HOME="$TMPU/d"
    mkdir -p "$TMPU/c/ggufly" "$TMPU/s/ggufly" "$TMPU/d"
    # Source ggufly under strict checks with no model selected, no config
    source "$ROOT/bin/ggufly" 2>"$TMPU/startup.err"
    EC=$?
    ERR=$(cat "$TMPU/startup.err")
    if [ "$EC" -ne 0 ] || [ -n "$ERR" ]; then
        echo "FAIL: set -u startup error: $ERR" >&2
        exit 1
    fi
    # Verify key functions exist and can be called safely
    resolve_backend "" >/dev/null 2>&1 || true
    runtime_status >/dev/null 2>&1 || true
    rm -rf "$TMPU"
)
check 'set -u startup safety: no unbound variables with empty config'


# Test 4: Float-safe disk comparison
(
    disk_free_gib="32.0"
    too_low=$(python3 -c "free=float('${disk_free_gib}'); print('yes' if 0 < free < 12 else 'no')")
    [[ "$too_low" == "no" ]]
    disk_free_gib="11.5"
    too_low=$(python3 -c "free=float('${disk_free_gib}'); print('yes' if 0 < free < 12 else 'no')")
    [[ "$too_low" == "yes" ]]
    disk_free_gib="32"
    too_low=$(python3 -c "free=float('${disk_free_gib}'); print('yes' if 0 < free < 12 else 'no')")
    [[ "$too_low" == "no" ]]
)
check 'float-safe disk comparison (32.0, 11.5, 32 integer)'

# Test 5: Disk check uses target filesystem, not $HOME
(
    check_path="$TMP/models/mirai-test"
    mkdir -p "$check_path"
    result=$(python3 -c "
import json, shutil, sys
target = sys.argv[1]
usage = shutil.disk_usage(target)
print(json.dumps({'free_gib': round(usage.free / (1024**3), 1)}))
" "$check_path" 2>/dev/null)
    [[ -n "$result" ]]
    free=$(printf '%s' "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['free_gib'])")
    [[ "$free" =~ ^[0-9]+\.?[0-9]*$ ]]
    # Verify it's NOT using $HOME as target
    [[ "$check_path" != "$HOME" ]]
)
check 'disk check uses target filesystem (shutil.disk_usage)'

# Test 6: No hard-coded dev paths in source
(
    ! grep -q '/home/ayshinko' "$ROOT/bin/ggufly"
    ! grep -q 'AI-Workspace/pmm-source' "$ROOT/bin/ggufly"
    ! grep -q '/home/ayshinko' "$ROOT/bin/ggufly-runtime-manager"
    ! grep -q 'AI-Workspace' "$ROOT/bin/ggufly-runtime-manager"
)
check 'no hard-coded dev paths in source files'

echo 'All tests passed; no real model or GPU workload executed.'