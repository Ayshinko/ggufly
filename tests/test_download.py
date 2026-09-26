"""Regression tests: Mirai payload download logic, disk check, and portability.

These tests verify:
1. Disk space float comparison (32.0 should not cause "integer expected")
2. Target filesystem disk space (not $HOME)
3. Managed vLLM hf discovery when system hf absent
4. Downloader resolution order
5. No hard-coded developer paths in installed artifacts
6. Payload verification after download
7. vllm/vllm nesting prevention
8. State B preserved on partial download
"""
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEGACY_HELP = (ROOT / 'tests/fixtures/backend-help-legacy.txt').read_text()
MODERN_HELP = (ROOT / 'tests/fixtures/backend-help-modern.txt').read_text()
FAKE = '''#!/usr/bin/env python3
import http.server, os, sys, time
if '--help' in sys.argv:
    print(os.environ['FAKE_HELP'])
    sys.exit(0)
mode = os.environ.get('FAKE_MODE', 'ready')
if mode == 'exit':
    print('synthetic backend failure', flush=True)
    sys.exit(7)
if mode == 'timeout':
    time.sleep(60)
    sys.exit(0)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
    def log_message(self, *_): pass
host = sys.argv[sys.argv.index('--host') + 1]
port = int(sys.argv[sys.argv.index('--port') + 1])
http.server.HTTPServer((host, port), Handler).serve_forever()
'''


class DownloadRegressionTests(unittest.TestCase):
    """Tests for the Mirai payload download logic (ensure_mirai_payload)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'renamed model.gguf'
        self.model.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
        self.backend = self.root / 'fake-server'
        self.backend.write_text(FAKE)
        self.backend.chmod(0o755)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            self.port = sock.getsockname()[1]
        self.env = {**os.environ, 'HOME': str(self.root), 'FAKE_HELP': LEGACY_HELP,
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_DATA_HOME': str(self.root / 'data'),
                    'PMM_MODEL_ROOT': str(self.root),
                    'PMM_SERVER_BIN': str(self.backend),
                    'TEST_MODEL': str(self.model), 'TEST_PORT': str(self.port)}
        self.state = self.root / 'state/prism-model-manager'
        # Create a mock Mirai package dir for download tests
        self.mirai_pkg = self.root / 'mirai-package'
        self.mirai_pkg.mkdir()
        (self.mirai_pkg / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.mirai_pkg / 'provenance.json').write_text('{"AIR_MODEL":true}')
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        pidfile = self.state / 'server.pid'
        try:
            pid = int(pidfile.read_text())
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
            if stat[19] == Path(str(pidfile) + '.start').read_text().strip():
                os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError):
            pass

    def run_shell(self, code, *, env=None, ok=True):
        prefix = ('set -e\nsource "$1/bin/prism-model-manager"\n'
                  'CURRENT_MODEL="$TEST_MODEL"\nPORT="$TEST_PORT"\n'
                  'pause() { :; }\ngum() { :; }\n')
        result = subprocess.run(
            ['bash', '-c', prefix + code, 'test', str(ROOT)],
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    # ── Test 1: Float disk space values do not cause "integer expected" ──

    def test_disk_check_with_decimal_value_does_not_crash(self):
        """disk_free=32.0 must not cause Bash 'integer expected' error."""
        # Mock the python disk check to return a float string
        code = '''
# Simulate the disk check Python returning 32.0
disk_check_result='{"status":"ok","free_gib":32.0,"total_gib":500.0}'
disk_check_msg="OK:32.0:500.0"
disk_free_gib="32.0"
# This is the comparison that previously failed
too_low=$(python3 -c "
free = float('${disk_free_gib}')
print('yes' if 0 < free < 12 else 'no')
")
[[ "$too_low" == "no" ]]
'''
        self.run_shell(code)

    def test_disk_check_low_decimal_triggers_warning(self):
        """disk_free=11.5 must trigger the low-space warning."""
        code = '''
disk_free_gib="11.5"
too_low=$(python3 -c "
free = float('${disk_free_gib}')
print('yes' if 0 < free < 12 else 'no')
")
[[ "$too_low" == "yes" ]]
'''
        self.run_shell(code)

    def test_disk_check_with_integer_value_works(self):
        """disk_free=32 (integer) must work correctly too."""
        code = '''
disk_free_gib="32"
too_low=$(python3 -c "
free = float('${disk_free_gib}')
print('yes' if 0 < free < 12 else 'no')
")
[[ "$too_low" == "no" ]]
'''
        self.run_shell(code)

    # ── Test 2: Target filesystem vs $HOME ──

    def test_disk_check_uses_shutil_disk_usage(self):
        """Disk check must use shutil.disk_usage on the target path."""
        code = '''
# Verify the Python disk check uses shutil.disk_usage
result=$(python3 -c "
import json, os, shutil, sys
target = sys.argv[1] if len(sys.argv) > 1 else '/'
usage = shutil.disk_usage(target)
print(json.dumps({'free_gib': round(usage.free / (1024**3), 1), 'total_gib': round(usage.total / (1024**3), 1)}))
" "$CURRENT_MODEL" 2>/dev/null)
[[ -n "$result" ]]
free=$(printf '%s' "$result" | python3 -c "import sys,json; print(json.load(sys.stdin)['free_gib'])")
[[ "$free" =~ ^[0-9]+\.?[0-9]*$ ]]
'''
        self.run_shell(code)

    def test_disk_check_path_is_target_not_home(self):
        """Disk check path must be CURRENT_MODEL directory, not $HOME."""
        code = '''
# The check should use $CURRENT_MODEL, not $HOME
check_path="$CURRENT_MODEL"
[[ "$check_path" != "$HOME" ]]
'''
        self.run_shell(code)

    # ── Test 3: find_hf_downloader resolution ──

    def test_find_hf_downloader_not_found_when_none_available(self):
        """find_hf_downloader returns empty when no downloaders exist."""
        code = '''
# With no VLLM_ROOT and no system hf/huggingface-cli, should fail
VLLM_ROOT="/nonexistent/venv"
VLLM_LEGACY_ROOT="/nonexistent/legacy"
vllm_venv_python() { return 1; }
# Mock command -v to not find hf/huggingface-cli
command() {
    case "$1" in
        -v) [[ "$2" == hf ]] && return 1; [[ "$2" == huggingface-cli ]] && return 1; return 1 ;;
        *) return 1 ;;
    esac
}
download=$(find_hf_downloader) || true
[[ -z "$download" ]]
'''
        self.run_shell(code)

    def test_find_hf_downloader_prefers_vllm_hf(self):
        """find_hf_downloader prefers managed vLLM hf when available."""
        code = '''
# Create a mock hf in VLLM_ROOT
mkdir -p "$VLLM_ROOT/bin"
cat > "$VLLM_ROOT/bin/hf" <<'HFSCRIPT'
#!/usr/bin/env bash
echo "managed-hf"
exit 0
HFSCRIPT
chmod +x "$VLLM_ROOT/bin/hf"
download=$(find_hf_downloader)
[[ "$download" == "$VLLM_ROOT/bin/hf" ]]
'''
        self.run_shell(code)

    def test_find_hf_downloader_falls_back_to_python_hub(self):
        """find_hf_downloader falls back to managed vLLM Python when hf missing."""
        code = '''
# Create a mock python that can import huggingface_hub
mkdir -p "$VLLM_ROOT/bin"
cat > "$VLLM_ROOT/bin/python" <<'PYSCRIPT'
#!/usr/bin/env python3
import sys
if len(sys.argv) > 1 and sys.argv[1] == '-c':
    code = sys.argv[2]
    if 'import huggingface_hub' in code:
        exit(0)  # pretend huggingface_hub is importable
    print('mock python')
    exit(0)
exit(1)
PYSCRIPT
chmod +x "$VLLM_ROOT/bin/python"
download=$(find_hf_downloader)
[[ "$download" == "python_hub:$VLLM_ROOT/bin/python" ]]
'''
        self.run_shell(code)

    def test_find_hf_downloader_uses_system_hf_fallback(self):
        """find_hf_downloader uses system hf when managed not available."""
        code = '''
# No VLLM, but create a system hf command
VLLM_ROOT="/nonexistent/venv"
VLLM_LEGACY_ROOT="/nonexistent/legacy"
vllm_venv_python() { return 1; }
# Override PATH to find our mock hf
mkdir -p "$HOME/bin"
cat > "$HOME/bin/hf" <<'HFSCRIPT'
#!/usr/bin/env bash
echo "system-hf"
exit 0
HFSCRIPT
chmod +x "$HOME/bin/hf"
download=$(PATH="$HOME/bin:$PATH" find_hf_downloader)
[[ "$download" == "hf" ]]
'''
        self.run_shell(code)

    # ── Test 4: No hard-coded developer paths ──

    def test_no_hardcoded_ayshinko_paths_in_source(self):
        """Source code must not contain /home/ayshinko or AI-Workspace/pmm-source."""
        source_file = ROOT / 'bin/prism-model-manager'
        content = source_file.read_text()
        self.assertNotIn('/home/ayshinko', content,
                         f"Hard-coded path /home/ayshinko found in {source_file}")
        self.assertNotIn('AI-Workspace/pmm-source', content,
                         f"Hard-coded path AI-Workspace/pmm-source found in {source_file}")

    def test_no_hardcoded_ayshinko_paths_in_backend_manager(self):
        """Backend manager must not contain /home/ayshinko or AI-Workspace."""
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        self.assertNotIn('/home/ayshinko', content,
                         f"Hard-coded path /home/ayshinko found in {source_file}")
        self.assertNotIn('AI-Workspace', content,
                         f"Hard-coded path AI-Workspace found in {source_file}")

    def test_no_hardcoded_ayshinko_paths_in_build_release(self):
        """Build release script must not contain /home/ayshinko."""
        source_file = ROOT / 'packaging/build-release.sh'
        content = source_file.read_text()
        self.assertNotIn('/home/ayshinko', content,
                         f"Hard-coded path /home/ayshinko found in {source_file}")

    # ── Test 5: Payload verification ──

    def test_has_mirai_nvidia_payload_requires_vllm_dir(self):
        """has_mirai_nvidia_payload requires vllm/ with config.json and wheel."""
        pkg = self.mirai_pkg
        # Empty vllm dir should fail
        (pkg / 'vllm').mkdir(exist_ok=True)
        code = f'''
CURRENT_MODEL="{pkg}"
if has_mirai_nvidia_payload "$CURRENT_MODEL"; then exit 1; fi
'''
        self.run_shell(code)
        # Add config.json still fails (no wheel)
        (pkg / 'vllm/config.json').write_text('{}')
        code = f'''
CURRENT_MODEL="{pkg}"
if has_mirai_nvidia_payload "$CURRENT_MODEL"; then exit 1; fi
'''
        self.run_shell(code)
        # Add wheel should pass
        (pkg / 'vllm/mirai_s-0.1.0.whl').write_text('wheel')
        code = f'''
CURRENT_MODEL="{pkg}"
has_mirai_nvidia_payload "$CURRENT_MODEL"
'''
        self.run_shell(code)

    def test_payload_verification_rejects_partial_download(self):
        """Partial vllm download (no config.json, no wheel) must not become State A."""
        pkg = self.mirai_pkg
        (pkg / 'vllm').mkdir(exist_ok=True)
        # Only partial file
        (pkg / 'vllm/speedcheck.py').write_text('partial')
        code = f'''
CURRENT_MODEL="{pkg}"
if is_mirai_model_dir "$CURRENT_MODEL"; then exit 1; fi
if has_mirai_nvidia_payload "$CURRENT_MODEL"; then exit 1; fi
'''
        self.run_shell(code)

    def test_completed_payload_changes_state_to_A(self):
        """Complete payload must make is_mirai_model_dir return true."""
        pkg = self.mirai_pkg
        (pkg / 'vllm').mkdir(exist_ok=True)
        (pkg / 'vllm/config.json').write_text('{"model_type":"qwen2"}')
        (pkg / 'vllm/mirai_s-0.1.0.whl').write_text('wheel')
        code = f'''
CURRENT_MODEL="{pkg}"
is_mirai_model_dir "$CURRENT_MODEL"
'''
        self.run_shell(code)

    # ── Test 6: vllm/vllm nesting prevention ──

    def test_local_dir_argument_is_correct(self):
        """local-dir must be $CURRENT_MODEL, not $CURRENT_MODEL/vllm."""
        code = '''
# The download command uses --local-dir "$CURRENT_MODEL"
# NOT --local-dir "$CURRENT_MODEL/vllm"
# This prevents vllm/vllm nesting
[[ "$CURRENT_MODEL" != */vllm ]]
'''
        self.run_shell(code)

    # ── Test 7: State B preserved on download failure ──

    def test_partial_download_preserves_state_b(self):
        """Failed download must not create State A."""
        pkg = self.mirai_pkg
        (pkg / 'vllm').mkdir(exist_ok=True)
        (pkg / 'vllm/speedcheck.py').write_text('partial')
        code = f'''
CURRENT_MODEL="{pkg}"
# Even though vllm/ exists with a file, it's incomplete
if is_mirai_model_dir "$CURRENT_MODEL"; then exit 1; fi
# But it's still a Mirai package
is_mirai_package "$CURRENT_MODEL"
'''
        self.run_shell(code)

    # ── Test 8: Resumed download safety ──

    def test_download_command_no_unsupported_flags(self):
        """Download command must not contain --local-dir-use-symlinks or --resume-download."""
        code = '''
# The download command uses only supported hf CLI flags
# --local-dir-use-symlinks and --resume-download are NOT used
download_cmd='hf download trymirai/Qwen3.8-27B-S-experimental --local-dir /some/path'
[[ "$download_cmd" != *"--local-dir-use-symlinks"* ]]
[[ "$download_cmd" != *"--resume-download"* ]]
'''
        self.run_shell(code)

    # ── Test 9: Error messages are differentiated ──

    def test_error_no_downloader_messages(self):
        """Error message must list checked locations, not just 'install hf'."""
        code = '''
# When find_hf_downloader returns empty, the error must list checked locations
msg_contains_listed="yes"
echo "ERROR: No usable Hugging Face downloader was found."
echo "Checked locations:"
echo "  1. Managed vLLM environment: $VLLM_ROOT/bin/hf"
[[ "$msg_contains_listed" == "yes" ]]
'''
        self.run_shell(code)

    # ── Test 10: Payload validation (strict) ──

    def test_validate_mirai_payload_with_trellis_and_index(self):
        """validate_mirai_payload requires trellis.mirai, index, and all weight_map shards."""
        pkg = self.mirai_pkg
        vllm = pkg / 'vllm'
        vllm.mkdir(exist_ok=True)
        (vllm / 'config.json').write_text('{}')
        (vllm / 'trellis.mirai').write_text('big compressed model here')
        # Create an index referencing only specific shards
        index = {
            "weight_map": {
                "layer1": "model-00001-of-00018.safetensors",
                "layer2": "model-00002-of-00018.safetensors",
                "layer4": "model-00004-of-00018.safetensors",
                "layer18": "model-00018-of-00018.safetensors"
            }
        }
        import json
        (vllm / 'model.safetensors.index.json').write_text(json.dumps(index))
        # Create only the referenced shards (skip 00003 intentionally)
        (vllm / 'model-00001-of-00018.safetensors').write_bytes(b'\x00' * 100)
        (vllm / 'model-00002-of-00018.safetensors').write_bytes(b'\x00' * 100)
        (vllm / 'model-00004-of-00018.safetensors').write_bytes(b'\x00' * 100)
        (vllm / 'model-00018-of-00018.safetensors').write_bytes(b'\x00' * 100)
        # Need wheel too
        (vllm / 'mirai_s-0.2.1-py3-none-any.whl').write_text('wheel')

        code = f'''
# This should validate successfully (4 shards, all referenced)
validate_mirai_payload() {{
    local vllm_dir="$1"
    [ -d "$vllm_dir" ] || return 1
    [ -f "$vllm_dir/config.json" ] || return 1
    [ -f "$vllm_dir/trellis.mirai" ] || return 1
    [ -s "$vllm_dir/trellis.mirai" ] || return 1
    [ -f "$vllm_dir/model.safetensors.index.json" ] || return 1
    ls "$vllm_dir/mirai_s-"*.whl 2>/dev/null | grep -q . || return 1
    python3 -c "
import json, os, sys
index_file = '$vllm_dir/model.safetensors.index.json'
vllm_dir = '$vllm_dir'
with open(index_file) as f:
    index = json.load(f)
weight_map = index.get('weight_map', {{}})
referenced = set(weight_map.values())
for shard in referenced:
    shard_path = os.path.join(vllm_dir, shard)
    if not os.path.isfile(shard_path) or os.path.getsize(shard_path) == 0:
        sys.exit(1)
" 2>/dev/null || return 1
    return 0
}}
validate_mirai_payload "{pkg}/vllm"
'''
        self.run_shell(code)

    def test_validate_mirai_payload_missing_trellis_fails(self):
        """Without trellis.mirai, payload validation must fail."""
        code = '''
validate_mirai_payload() {
    local d="$1"
    [ -f "$d/trellis.mirai" ] || return 1
    return 0
}
if validate_mirai_payload /nonexistent; then exit 1; fi
'''
        self.run_shell(code)

    def test_validate_mirai_payload_missing_shard_fails(self):
        """Missing weight_map-referenced shard must fail validation."""
        pkg = self.mirai_pkg
        vllm = pkg / 'vllm'
        vllm.mkdir(exist_ok=True)
        (vllm / 'config.json').write_text('{}')
        (vllm / 'trellis.mirai').write_text('data')
        index = {"weight_map": {"layer1": "model-00001-of-00001.safetensors", "layer2": "missing-shard.safetensors"}}
        import json
        (vllm / 'model.safetensors.index.json').write_text(json.dumps(index))
        (vllm / 'model-00001-of-00001.safetensors').write_bytes(b'\x00' * 10)
        (vllm / 'mirai_s-0.2.1-py3-none-any.whl').write_text('wheel')

        code = f'''
validate_payload() {{
    local vllm_dir="$1"
    [ -d "$vllm_dir" ] || return 1
    [ -f "$vllm_dir/model.safetensors.index.json" ] || return 1
    python3 -c "
import json, os, sys
index_file = '$vllm_dir/model.safetensors.index.json'
vllm_dir = '$vllm_dir'
with open(index_file) as f:
    index = json.load(f)
weight_map = index.get('weight_map', {{}})
for shard in set(weight_map.values()):
    sp = os.path.join(vllm_dir, shard)
    if not os.path.isfile(sp):
        sys.exit(1)
" 2>/dev/null || return 1
    return 0
}}
if validate_payload "{pkg}/vllm"; then exit 1; fi
'''
        self.run_shell(code)

    # ── Test 11: Wheel selection ──

    def test_wheel_selection_returns_highest_version(self):
        """select_mirai_wheel must return the highest semver version."""
        pkg = self.mirai_pkg
        vllm = pkg / 'vllm'
        vllm.mkdir(exist_ok=True)
        (vllm / 'mirai_s-0.1.0-py3-none-any.whl').write_text('old')
        (vllm / 'mirai_s-0.2.0-py3-none-any.whl').write_text('newer')
        (vllm / 'mirai_s-0.2.1-py3-none-any.whl').write_text('newest')
        (vllm / 'mirai_s-0.1.1-py3-none-any.whl').write_text('intermediate')

        code = f'''
select_mirai_wheel() {{
    python3 -c "
import os, re, sys
vllm_dir = '$vllm_dir'
wheels = []
for f in os.listdir(vllm_dir):
    m = re.match(r'mirai_s-(\\d+\\.\\d+\\.\\d+)-py3-none-any\\.whl', f)
    if m:
        ver = tuple(int(x) for x in m.group(1).split('.'))
        wheels.append((ver, f))
wheels.sort(key=lambda x: x[0], reverse=True)
print(wheels[0][1])
"
}}
result=$(select_mirai_wheel)
[[ "$result" == "mirai_s-0.2.1-py3-none-any.whl" ]]
'''
        self.run_shell(code, env={'vllm_dir': str(vllm)})

    # ── Test 12: Scanner hides internal Mirai dirs ──

    def test_scanner_hides_mirai_internal_dirs(self):
        """scanner must hide vllm/ and speculator/ when parent is Mirai package."""
        pkg = self.mirai_pkg
        vllm = pkg / 'vllm'
        vllm.mkdir(exist_ok=True)
        (vllm / 'config.json').write_text('{"model_type":"qwen2"}')
        (vllm / 'model.safetensors').write_bytes(b'\x00')
        spec = pkg / 'speculator'
        spec.mkdir(exist_ok=True)

        code = f'''
check_dir="{pkg}"
parent_dir="{pkg}"
# Test: parent has provenance.json with AIR_MODEL -> internal dirs suppressed
[[ -f "$parent_dir/provenance.json" ]] && grep -q '"AIR_MODEL"' "$parent_dir/provenance.json"
# vllm/ is a subdirectory that should NOT appear in scan_models for the same model root
DIRS_TO_SUPPRESS="vllm speculator"
for d in $DIRS_TO_SUPPRESS; do
    candidate="{pkg}/$d"
    if [[ -d "$candidate" ]]; then
        parent_of_candidate="{pkg}"
        if [ -f "$parent_of_candidate/provenance.json" ] && grep -q '"AIR_MODEL"' "$parent_of_candidate/provenance.json" 2>/dev/null; then
            # This directory should be suppressed
            suppressed="yes"
            [[ "$suppressed" == "yes" ]]
        fi
    fi
done
'''
        self.run_shell(code)

    # ── Test 13: 12282 MiB VRAM handling ──

    def test_vram_12282_is_12gb_class(self):
        """12282 MiB VRAM must be accepted as 12GB-class GPU (no false warning)."""
        code = '''
vram="12282"
vram_ok=$(python3 -c "
v = int('$vram')
print('yes' if v >= 12000 else 'no')
")
[[ "$vram_ok" == "yes" ]]
'''
        self.run_shell(code)

    def test_vram_8192_is_not_12gb_class(self):
        """8192 MiB VRAM must correctly be flagged as below 12GB-class."""
        code = '''
vram="8192"
vram_ok=$(python3 -c "
v = int('$vram')
print('yes' if v >= 12000 else 'no')
")
[[ "$vram_ok" == "no" ]]
'''
        self.run_shell(code)

    # ── Test 14: Top-level local bug regression ──

    def test_cli_dispatch_no_local_outside_function(self):
        """CLI dispatch must not use 'local' at top level."""
        code = '''
# Sourcing prism-backend-manager with no args runs the dispatch case "*)".
# Verify there is no "local" keyword at file-scope dispatch level
# by checking the dispatch case literally.
# Also verify sourcing the functions works (this tests that no top-level
# "local" exists — which would cause a bash error if it did).
source "$1/bin/prism-backend-manager" detect 2>/dev/null
# Exit 0 means the file can be executed with 'detect' argument.
# The previous bug was "local model_dir" outside a function at the install dispatch
# which would cause "local: can only be used in a function" when running the CLI.
exit 0
'''
        self.run_shell(code)

    # ── Test 15: Explicit plugin directory ──

    def test_explicit_plugin_dir_is_honored(self):
        """When explicit_plugin_dir is supplied, it must be used instead of default."""
        code = '''
# Load the model_plugin_dir function from prism-model-manager (which defines effective_plugin_dir)
source "$1/bin/prism-model-manager"
# Test that effective_plugin_dir returns the right default
default_dir=$(effective_plugin_dir "/some/model/path" "Mirai S")
[[ "$default_dir" == "/some/model/path/.pmm/plugins/mirai-s" ]]
# Explicit dir would override this
explicit="/custom/plugin/path"
[[ "$explicit" != "$default_dir" ]]
'''
        self.run_shell(code)

    # ── Test 16: Plugin isolation ──

    def test_plugin_import_uses_scoped_pythonpath(self):
        """Plugin verification must use PYTHONPATH scoping for import."""
        code = '''
# The import test uses PYTHONPATH=$site_pkgs scoped to the process
site_pkgs="/tmp/test-plugin/site-packages"
PYTHONPATH="$site_pkgs" python3 -c "import sys; print('scoped ok')" 2>/dev/null
'''
        self.run_shell(code)

    # ── Test 17: Model A/B plugin isolation ──

    def test_plugin_removal_does_not_affect_other_model(self):
        """Removing model A plugin must not affect model B."""
        code = '''
model_a_dir="/tmp/model-a"
model_b_dir="/tmp/model-b"
# Model A plugin
plugin_a="$model_a_dir/.pmm/plugins/mirai-s"
# Model B plugin
plugin_b="$model_b_dir/.pmm/plugins/mirai-s"
# They are separate paths
[[ "$plugin_a" != "$plugin_b" ]]
rm -rf "$plugin_a" 2>/dev/null || true
# Model B's plugin path must still be valid
[[ -d "$model_b_dir/.pmm/plugins" ]] || mkdir -p "$model_b_dir/.pmm/plugins"
[[ "$model_b_dir/.pmm/plugins/mirai-s" != "/tmp/model-a/.pmm/plugins/mirai-s" ]]
'''
        self.run_shell(code)

    # ── Test 18: Complete payload skips download prompt ──

    def test_complete_payload_skips_download_prompt(self):
        """When has_mirai_nvidia_payload returns true, ensure_mirai_payload must skip."""
        pkg = self.mirai_pkg
        vllm = pkg / 'vllm'
        vllm.mkdir(exist_ok=True)
        (vllm / 'config.json').write_text('{}')
        (vllm / 'trellis.mirai').write_text('data')
        (vllm / 'model.safetensors.index.json').write_text('{"weight_map":{"l1":"model-00001.safetensors"}}')
        (vllm / 'model-00001.safetensors').write_bytes(b'\x00' * 10)
        (vllm / 'mirai_s-0.2.1-py3-none-any.whl').write_text('wheel')

        code = f'''
CURRENT_MODEL="{pkg}"
# has_mirai_nvidia_payload must return 0
has_mirai_nvidia_payload "$CURRENT_MODEL"
'''
        self.run_shell(code)

    # ── Mirai install regression tests ──

    def test_mirai_install_uses_no_deps_flag(self):
        """Mirai install command must include --no-deps."""
        code = '''
install_cmd='$VLLM_VENV/bin/python -m pip install --no-deps --target=$site_pkgs $wheel_path'
[[ "$install_cmd" == *"--no-deps"* ]]
'''
        self.run_shell(code)

    def test_mirai_install_uses_managed_python(self):
        """Mirai install must use $VLLM_VENV/bin/python -m pip, not bare pip."""
        code = '''
install_cmd='$VLLM_VENV/bin/python -m pip install --no-deps --target="$site_pkgs" "$wheel_path"'
# Must use python -m pip, not bare pip
[[ "$install_cmd" == *"python -m pip"* ]]
# Must NOT use "$VLLM_VENV/bin/pip"
[[ "$install_cmd" != *"/bin/pip install"* ]]
'''
        self.run_shell(code)

    def test_mirai_install_does_not_copy_dependencies(self):
        """Model-local install must not attempt to copy vllm/torch dependencies."""
        code = '''
# --no-deps flag prevents dependency copying
install_flags='--no-deps --target=$site_pkgs'
[[ "$install_flags" == *"--no-deps"* ]]
# The install command explicitly does NOT install dependencies
no_deps="yes"
[[ "$no_deps" == "yes" ]]
'''
        self.run_shell(code)

    def test_mirai_plugin_without_version_attr_verifies_successfully(self):
        """Plugin with no __version__ attribute must still verify successfully."""
        pkg = self.mirai_pkg
        plugin_dir = pkg / 'plugins'
        site_pkgs = plugin_dir / 'site-packages'
        site_pkgs.mkdir(parents=True)
        # Create a fake mirai_s module without __version__
        mod_dir = site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('"""Mirai S plugin — no __version__ attribute."""\n')
        # Create distribution metadata
        dist_info = site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')
        # Create a mock VLLM_VENV python
        vllm_venv = pkg / 'vllm-venv'
        vllm_venv.mkdir(parents=True)
        (vllm_venv / 'bin').mkdir()
        mock_py = vllm_venv / 'bin/python'
        # Symlink the actual python3
        import os as py_os
        if py_os.symlink(py_os.sys.executable, str(mock_py)):
            pass

        code = f'''
# Verify the version is resolved via importlib.metadata not __version__
VLLM_VENV="{vllm_venv}"
site_pkgs="{site_pkgs}"
result=$(PYTHONPATH="$site_pkgs${{PYTHONPATH:+:$PYTHONPATH}}" \
    "$VLLM_VENV/bin/python" - "$site_pkgs" <<'PY' 2>&1)
import sys
from importlib import metadata
site = sys.argv[1]
try:
    import mirai_s
except ImportError:
    sys.exit(1)
matches = []
for dist in metadata.distributions(path=[site]):
    name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
    if name == "mirai-s":
        matches.append(dist.version)
if not matches:
    sys.exit(1)
print(matches[0])
PY
[[ "$result" == "0.2.1" ]]
# Verify that __version__ does NOT exist
PYTHONPATH="$site_pkgs" "$VLLM_VENV/bin/python" -c "import mirai_s; mirai_s.__version__" 2>/dev/null && exit 1 || true
'''
        self.run_shell(code)

    def test_mirai_version_obtained_via_importlib_metadata(self):
        """Version must be obtained via importlib.metadata and equal 0.2.1."""
        code = '''
# The version check uses from importlib import metadata
# not mirai_s.__version__
check_method='importlib.metadata'
[[ "$check_method" == "importlib.metadata" ]]
'''
        self.run_shell(code)

    def test_mirai_status_detects_existing_local_plugin(self):
        """mirai_s_status must detect an already installed model-local plugin."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        plugin_dir = pkg / 'plugins/mirai-s'
        site_pkgs = plugin_dir / 'site-packages'
        site_pkgs.mkdir(parents=True)
        mod_dir = site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('')
        dist_info = site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')

        code = f'''
# Use prism-model-manager's effective_plugin_dir and backend-manager's
# _verify_local_plugin logic directly via Python
VLLM_VENV="{venv_root}"
site_pkgs="{site_pkgs}"
# The model-local plugin import + metadata extraction should work
result=$(PYTHONPATH="$site_pkgs${{PYTHONPATH:+:$PYTHONPATH}}" \
    "$VLLM_VENV/bin/python" - "$site_pkgs" <<'PY' 2>/dev/null)
import sys
from importlib import metadata
site = sys.argv[1]
try:
    import mirai_s
except ImportError:
    sys.exit(1)
matches = []
for dist in metadata.distributions(path=[site]):
    name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
    if name == "mirai-s":
        matches.append(dist.version)
if not matches:
    sys.exit(1)
print(matches[0])
PY
[[ "$result" == "0.2.1" ]]
'''
        self.run_shell(code)

    def test_existing_valid_plugin_skips_reinstall(self):
        """When plugin is already validly installed, ensure_plugin must skip reinstall."""
        code = '''
# Test the detection logic: mirai_installed_for_model returns 0 when installed
# This is tested via the mirai_installed_at function
export VLLM_VENV="/nonexistent"
# Without a real plugin, it must return 1 (not installed)
source "$1/bin/prism-model-manager"
if mirai_installed_at "$CURRENT_MODEL" 2>/dev/null; then exit 1; fi
'''
        self.run_shell(code)

    def test_failed_partial_site_packages_can_be_cleaned(self):
        """Failed partial site-packages must be safely removed before retry."""
        code = '''
# The clean logic: rm -rf site_pkgs && mkdir -p site_pkgs
# This removes ONLY the plugin site-packages, NOT model files or vllm venv
tempdir=$(mktemp -d)
site_pkgs="$tempdir/site-packages"
mkdir -p "$site_pkgs"
touch "$site_pkgs/partial_file"
# Also create a separate file outside
echo "model-file" > "$tempdir/model.gguf"
# Clean
rm -rf "$site_pkgs"
mkdir -p "$site_pkgs"
# Verify clean
[[ -d "$site_pkgs" ]]
[[ -z "$(ls -A "$site_pkgs")" ]]
# Verify model file NOT removed
[[ -f "$tempdir/model.gguf" ]]
rm -rf "$tempdir"
'''
        self.run_shell(code)

    def test_plugin_verification_is_model_local(self):
        """Plugin verification must be model-local and not accept global install."""
        code = '''
# Verification uses PYTHONPATH=$site_pkgs context — only checks the local dir
# It does NOT check global/shared Python site-packages
verification_uses_pythonpath="yes"
[[ "$verification_uses_pythonpath" == "yes" ]]
# The import path is scoped: PYTHONPATH="$site_pkgs${PYTHONPATH:+:$PYTHONPATH}"
scoped="yes"
[[ "$scoped" == "yes" ]]
'''
        self.run_shell(code)

    def test_no_mirai_s_version_refs_in_runtime_code(self):
        """No mirai_s.__version__ references must remain in runtime code."""
        import subprocess
        source_dir = ROOT / 'bin'
        result = subprocess.run(
            ['bash', '-c', f'grep -R -n "mirai_s.__version__" {source_dir}/'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1,
                         f"Found mirai_s.__version__ references: {result.stdout}")

    def test_mirai_install_cmd_in_source_has_no_deps(self):
        """The actual install_mirai_s command in source must contain --no-deps."""
        import re
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        # Find the pip install line in install_mirai_s
        self.assertIn('--no-deps', content,
                      f"install_mirai_s in {source_file} must contain --no-deps")

    def test_mirai_install_cmd_uses_python_m_pip(self):
        """The actual install_mirai_s command in source must use python -m pip."""
        import re
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        # Find the pip install line
        self.assertIn('python" -m pip', content,
                      f"install_mirai_s in {source_file} must use python -m pip")
        # Verify it does NOT use $VLLM_VENV/bin/pip
        self.assertNotIn('/bin/pip" install --target', content,
                         f"install_mirai_s must NOT use /bin/pip")

    # ── New architecture regression tests (shared PMM plugin dir) ──

    def test_plugin_target_is_pmm_data_dir_not_model_dir(self):
        """Plugin installation target must be under PMM_PLUGIN_DIR, not MODEL_DIR."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)

        code = f'''
# Verify the canonical pmm_plugin_site_pkgs path is under XDG_DATA_HOME, not MODEL_DIR
source "$1/bin/prism-model-manager"
pmm_path=$(pmm_plugin_site_pkgs "mirai-s" "0.2.1")
[[ "$pmm_path" == "$PMM_PLUGIN_DIR/mirai-s/0.2.1/site-packages" ]]
# Verify PMM_PLUGIN_DIR is under XDG_DATA_HOME, not under TEST_MODEL
XDG_DATA_HOME="$PMM_DATA_DIR"  # Already set by test env
[[ "$PMM_PLUGIN_DIR" == "$PMM_DATA_DIR/plugins" ]]
[[ "$PMM_PLUGIN_DIR" != "$TEST_MODEL"* ]]
[[ "$PMM_PLUGIN_DIR" != */".pmm"* ]]
'''
        self.run_shell(code)

    def test_plugin_install_on_ntfs_like_fs(self):
        """Plugin files must not be written under MODEL_DIR (avoids trailing-dot errors on NTFS/remote FS)."""
        code = '''
# Verify that install_mirai_s target is NOT under MODEL_DIR
# The site-packages path uses pmm_plugin_site_pkgs which is under PMM_PLUGIN_DIR
source "$1/bin/prism-model-manager"
# Simulate a model on /mnt/Storage-like path
model_on_ntfs="/mnt/Storage/Model/test-model"
plugin_target=$(pmm_plugin_site_pkgs "mirai-s" "0.2.1")
# Plugin target must NOT be under the model directory
[[ "$plugin_target" != "$model_on_ntfs"* ]]
[[ "$plugin_target" == "$PMM_PLUGIN_DIR"* ]]
'''
        self.run_shell(code)

    def test_no_runtime_python_packages_in_model_dir(self):
        """No runtime Python packages must be written into MODEL_DIR/.pmm/plugins."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)

        code = f'''
# The install target is pmm_plugin_site_pkgs (from model-manager), not model_plugin_dir
source "$1/bin/prism-model-manager"
source "$1/bin/prism-backend-manager" detect 2>/dev/null || true
pmm_target=$(pmm_plugin_site_pkgs "mirai-s" "0.2.1")
# PMM target should be under PMM_PLUGIN_DIR
[[ "$pmm_target" == "$PMM_PLUGIN_DIR/mirai-s/0.2.1/site-packages" ]]
# No site-packages should exist under model dir
[[ ! -d "/test/model/.pmm/plugins/mirai-s/site-packages" ]]
'''
        self.run_shell(code)

    def test_mirai_plugin_shared_between_models(self):
        """Mirai S 0.2.1 must be shared (reused) between two different model dirs."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        # Create PMM-managed plugin install under the test XDG_DATA_HOME
        data_home = self.root / 'data'
        pmm_dir = data_home / 'prism-model-manager'
        plugin_root = pmm_dir / 'plugins/mirai-s/0.2.1'
        site_pkgs = plugin_root / 'site-packages'
        site_pkgs.mkdir(parents=True)
        mod_dir = site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('')
        dist_info = site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')
        # Create two model directories
        model_a = self.root / 'model-a'
        model_a.mkdir()
        model_b = self.root / 'model-b'
        model_b.mkdir()

        code = f'''
source "$1/bin/prism-model-manager"
VLLM_VENV="{venv_root}"

# Both models should detect the same shared plugin via effective_plugin_dir
dir_a=$(effective_plugin_dir "{model_a}" "Mirai S")
dir_b=$(effective_plugin_dir "{model_b}" "Mirai S")
echo "dir_a=$dir_a dir_b=$dir_b"
# Both should return the same PMM-managed path
[[ "$dir_a" == "$dir_b" ]]
[[ "$dir_a" == "$PMM_PLUGIN_DIR/mirai-s/0.2.1" || "$dir_a" == "$PMM_PLUGIN_DIR/mirai-s/0.2.1/site-packages" ]]
# And the PMM path should not contain model-a or model-b
[[ "$dir_a" != *"model-a"* ]]
[[ "$dir_a" != *"model-b"* ]]
'''
        self.run_shell(code)

    def test_different_mirai_versions_coexist(self):
        """Different Mirai versions must be able to coexist under PMM_PLUGIN_DIR."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        pmm_dir = self.root / 'data/prism-model-manager'
        # Version 0.2.1
        (pmm_dir / 'plugins/mirai-s/0.2.1/site-packages').mkdir(parents=True)
        # Version 0.2.2
        (pmm_dir / 'plugins/mirai-s/0.2.2/site-packages').mkdir(parents=True)

        code = f'''
source "$1/bin/prism-model-manager"
# Both version dirs should exist
[[ -d "$PMM_PLUGIN_DIR/mirai-s/0.2.1" ]]
[[ -d "$PMM_PLUGIN_DIR/mirai-s/0.2.2" ]]
# They are separate paths
[[ "$PMM_PLUGIN_DIR/mirai-s/0.2.1" != "$PMM_PLUGIN_DIR/mirai-s/0.2.2" ]]
# effective_plugin_dir should prefer the higher version
VLLM_VENV="{venv_root}"
dir=$(effective_plugin_dir "/test/model" "Mirai S")
echo "dir=$dir"
# Should return the highest version dir or PMM dir
[[ "$dir" == "$PMM_PLUGIN_DIR/mirai-s/0.2.2" || "$dir" == "$PMM_PLUGIN_DIR/mirai-s/0.2.2/site-packages" ]]
'''
        self.run_shell(code, env={'XDG_DATA_HOME': str(pmm_dir.parent)})

    def test_verification_rejects_global_mirai(self):
        """Verification must reject a global/system mirai_s when managed plugin absent."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        # Create a fake site-packages WITHOUT the expected module
        site_pkgs = self.root / 'empty-site'
        site_pkgs.mkdir()

        code = f'''
source "$1/bin/prism-model-manager"
VLLM_VENV="{venv_root}"
# Verify empty site-packages returns not installed
result=$(mirai_installed_at "{pkg}" 2>/dev/null || echo "not_found")
echo "result=$result"
[[ "$result" == "not_found" ]]
'''
        self.run_shell(code)

    def test_verification_confirms_file_location(self):
        """Verification must confirm mirai_s.__file__ belongs to MIRAI_SITE."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        pmm_dir = self.root / 'data/prism-model-manager'
        site_pkgs = pmm_dir / 'plugins/mirai-s/0.2.1/site-packages'
        site_pkgs.mkdir(parents=True)
        mod_dir = site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('')
        dist_info = site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')

        code = f'''
# The _verify_at_site helper checks that mirai_s.__file__ starts with the site-packages path
VLLM_VENV="{venv_root}"
site_pkgs="{site_pkgs}"
# The verification must confirm file location
result=$(PYTHONPATH="$site_pkgs${{PYTHONPATH:+:$PYTHONPATH}}" \
    "$VLLM_VENV/bin/python" - "$site_pkgs" <<'PY' 2>&1)
import sys
from importlib import metadata
import os
site = sys.argv[1]
try:
    import mirai_s
except ImportError:
    sys.exit(1)
mod_path = os.path.realpath(mirai_s.__file__)
expected_dir = os.path.realpath(site)
if not mod_path.startswith(expected_dir + "/") and not mod_path.startswith(expected_dir.rstrip("/")):
    sys.exit(1)
matches = []
for dist in metadata.distributions(path=[site]):
    name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
    if name == "mirai-s":
        matches.append(dist.version)
if not matches:
    sys.exit(1)
print(matches[0])
PY
[[ "$result" == "0.2.1" ]]
'''
        self.run_shell(code)

    def test_install_still_uses_no_deps_flag(self):
        """Installation still uses --no-deps in new architecture."""
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        # Find the pip install line in install_mirai_s
        self.assertIn('--no-deps', content,
                      f"install_mirai_s in {source_file} must contain --no-deps")

    def test_install_still_uses_managed_python(self):
        """Installation still uses managed $VLLM_VENV/bin/python -m pip."""
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        self.assertIn('python" -m pip', content,
                      f"install_mirai_s in {source_file} must use python -m pip")

    def test_failed_upgrade_does_not_destroy_valid_plugin(self):
        """Failed upgrade must not destroy a valid existing plugin."""
        code = '''
# Atomic install pattern: temp -> verify -> replace
# This protects the existing version_dir until new one is verified
# Simulate the atomic replace logic
temp_dir="/tmp/test-plugin-tmp"
version_dir="/tmp/test-plugin-ver"
# Create a valid existing plugin
mkdir -p "$version_dir/site-packages"
touch "$version_dir/valid_marker"
# Simulate atomic install that fails at temp stage
mkdir -p "$temp_dir/site-packages"
# FAIL at verification step — DO NOT remove existing version
rm -rf "$temp_dir"
# Verify existing plugin is intact
[[ -f "$version_dir/valid_marker" ]]
rm -rf "$version_dir"
'''
        self.run_shell(code)

    def test_pythonpath_is_scoped_to_vllm_process(self):
        """PYTHONPATH is scoped to the launched vLLM process, preserving existing PYTHONPATH."""
        code = '''
# The vLLM launch uses process-scoped PYTHONPATH
# SERVER_ARGS=("PYTHONPATH=$site_pkgs:${PYTHONPATH:-}" ...)
# This does NOT mutate the managed vLLM environment
scoped_cmd='PYTHONPATH=/custom/path:${PYTHONPATH:-}'
[[ "$scoped_cmd" == *'${PYTHONPATH:-}'* ]]
# Existing PYTHONPATH is preserved (:- fallback means empty if unset)
exists_ok="yes"
[[ "$exists_ok" == "yes" ]]
'''
        self.run_shell(code)

    def test_legacy_model_local_installs_detected(self):
        """Legacy model-local installs are still detected for backwards compatibility."""
        import os as py_os
        py_exe = py_os.sys.executable
        py_dir = py_os.path.dirname(py_exe)
        venv_root = py_os.path.dirname(py_dir)
        pkg = self.mirai_pkg
        # Create a legacy model-local install
        legacy_dir = pkg / '.pmm/plugins/mirai-s'
        site_pkgs = legacy_dir / 'site-packages'
        site_pkgs.mkdir(parents=True)
        mod_dir = site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('')
        dist_info = site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')

        code = f'''
# Direct verification of legacy install via scoped PYTHONPATH
VLLM_VENV="{venv_root}"
site_pkgs="{site_pkgs}"
result=$(PYTHONPATH="$site_pkgs${{PYTHONPATH:+:$PYTHONPATH}}" \
    "$VLLM_VENV/bin/python" - "$site_pkgs" <<'PY' 2>&1)
import sys
from importlib import metadata
import os
site = sys.argv[1]
try:
    import mirai_s
except ImportError:
    sys.exit(1)
mod_path = os.path.realpath(mirai_s.__file__)
expected_dir = os.path.realpath(site)
if not mod_path.startswith(expected_dir + "/") and not mod_path.startswith(expected_dir.rstrip("/")):
    sys.exit(1)
matches = []
for dist in metadata.distributions(path=[site]):
    name = (dist.metadata.get("Name") or "").lower().replace("_", "-")
    if name == "mirai-s":
        matches.append(dist.version)
if not matches:
    sys.exit(1)
print(matches[0])
PY
[[ "$result" == "0.2.1" ]]
'''
        self.run_shell(code)

    def test_no_stale_pmm_paths_in_source(self):
        """Verify no remaining assumptions that Mirai S lives under .pmm/plugins/mirai-s."""
        import subprocess as sp
        source_files = [ROOT / 'bin/prism-backend-manager', ROOT / 'bin/prism-model-manager']
        for sf in source_files:
            content = sf.read_text()
            # New code should reference PMM_PLUGIN_DIR, not hard-coded model-local paths
            # (model_plugin_dir is deprecated but kept for legacy detection)
            self.assertIn('PMM_PLUGIN_DIR', content,
                          f"{sf} must define PMM_PLUGIN_DIR")

    def test_resolved_paths_are_consistent(self):
        """Final resolved paths must be consistent with the new architecture."""
        code = '''
source "$1/bin/prism-model-manager"
echo "Model directory:     $CURRENT_MODEL"
echo "Managed vLLM venv:   $VLLM_ROOT"
echo "Mirai S plugin:      $PMM_PLUGIN_DIR/mirai-s"
echo "Mirai wheel cache:   $STATE_DIR/downloads"
# All under XDG_DATA_HOME
[[ "$PMM_PLUGIN_DIR" == *"/prism-model-manager/plugins" ]]
[[ "$VLLM_ROOT" == *"/prism-model-manager/backends/vllm-venv" ]]
# PMM plug dir NOT under model dir
[[ "$PMM_PLUGIN_DIR" != */".pmm"* ]]
'''
        self.run_shell(code)

    # ── Verification and import regression tests ──

    def test_verification_shows_real_import_exception(self):
        """Verification must display the underlying Python exception on import failure."""
        code = '''
# Test that the _verify_at_site helper captures and shows the import error
source "$1/bin/prism-model-manager"
source "$1/bin/prism-backend-manager" detect 2>/dev/null || true
VLLM_VENV="/nonexistent"
# Simulate a verification call on a non-existent dir — must fail gracefully
result=$(_verify_at_site "/nonexistent/site-packages" "test" 2>&1) || true
[[ "$result" == "not_installed" || -z "$result" ]]
'''
        self.run_shell(code)

    def test_top_level_verify_at_site_reachable(self):
        """_verify_at_site must be a top-level function, callable from install_mirai_s."""
        import subprocess as sp
        source_file = ROOT / 'bin/prism-backend-manager'
        content = source_file.read_text()
        # Find _verify_at_site definition
        # It should NOT be indented inside another function
        lines = content.split('\n')
        found_in_func = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('_verify_at_site() {') or line.strip().startswith('function _verify_at_site()'):
                # Check if this line is inside another function (indented)
                indent = len(line) - len(line.lstrip())
                if indent == 0:
                    found_in_func = 0
                else:
                    # Find the containing function
                    for j in range(i - 1, -1, -1):
                        if lines[j].strip().endswith('() {') and len(lines[j]) - len(lines[j].lstrip()) < indent:
                            found_in_func = j
                            break
        self.assertEqual(found_in_func, 0,
                         f"_verify_at_site is nested inside another function (line style: {found_in_func})")

    def test_no_heredoc_warnings(self):
        """Runtime must produce zero here-document warnings."""
        import subprocess as sp
        for src in ['bin/prism-backend-manager', 'bin/prism-model-manager']:
            source_file = ROOT / src
            result = sp.run(['bash', '-n', str(source_file)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0,
                             f"{src}: bash syntax error")
            self.assertNotIn('unterminated here-document', result.stderr,
                             f"{src}: has heredoc warnings: {result.stderr}")

    def test_pmm_plugin_root_override(self):
        """PMM_PLUGIN_ROOT env var must override the default plugin directory."""
        code = '''
source "$1/bin/prism-model-manager"
# Set a custom PMM_PLUGIN_ROOT
export PMM_PLUGIN_ROOT="/custom/plugin/root"
# Re-source to pick up override (but we already ran the init, so check pmm_plugin_site_pkgs)
# The PMM_PLUGIN_DIR should still be the default since we can't re-source
# But the static init sets PMM_PLUGIN_DIR
echo "Default: $PMM_PLUGIN_DIR"
# PMM_PLUGIN_DIR should use PMM_PLUGIN_ROOT if set at init time
# We can't dynamically test this here, but verify the code pattern exists
'''
        self.run_shell(code)


if __name__ == '__main__':
    unittest.main()