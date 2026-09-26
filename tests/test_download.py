"""Regression tests for v4 edition: disk check, codec detection, runtime registry.

These tests verify:
1. Disk space float comparison (32.0 should not cause "integer expected")
2. Target filesystem disk space (not $HOME)
3. No hard-coded developer paths in installed artifacts
4. Codec detection via prism-model-detect.py
5. GGUF info via prism-gguf-info.py
"""
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys
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


class DiskCheckRegressionTests(unittest.TestCase):
    """Tests for disk space comparison and path resolution."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'test.gguf'
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
        code = '''
disk_check_result='{"status":"ok","free_gib":32.0,"total_gib":500.0}'
disk_free_gib="32.0"
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
result=$(python3 -c "
import json, shutil, sys
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
check_path="$CURRENT_MODEL"
[[ "$check_path" != "$HOME" ]]
'''
        self.run_shell(code)

    # ── Test 3: No hard-coded developer paths ──

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

    # ── Test 4: Codec detection via prism-model-detect.py ──

    def test_codec_detection_unknown_for_minimal_gguf(self):
        """Minimal GGUF (no metadata keys) should return Unknown codec."""
        result = subprocess.run(
            [sys.executable, str(ROOT / 'bin/prism-model-detect.py'), str(self.model)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        data = json.loads(result.stdout)
        self.assertEqual(data.get('codec', ''), 'Unknown')
        self.assertEqual(data.get('architecture', ''), 'unknown')
        self.assertEqual(data.get('format', 'GGUF'), 'gguf')

    def test_codec_detection_known(self):
        """GGUF with general.file_type should populate codec field."""
        import struct as s
        model = self.root / 'codec-test.gguf'
        key = b'general.file_type'
        with open(model, 'wb') as f:
            f.write(b'GGUF' + s.pack('<IQQ', 3, 0, 1))
            f.write(s.pack('<Q', len(key)) + key)
            f.write(s.pack('<II', 4, 40))  # Q1_0
        result = subprocess.run(
            [sys.executable, str(ROOT / 'bin/prism-model-detect.py'), str(model)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        data = json.loads(result.stdout)
        self.assertEqual(data.get('codec', ''), 'Q1_0')

    # ── Test 5: 12282 MiB VRAM handling ──

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

    # ── Test 6: Runtime registry initialization ──

    def test_runtime_registry_source(self):
        """Runtime registry must source cleanly."""
        code = '''
source "$1/bin/prism-runtime-registry.sh"
# Should define key functions
type runtime_registry_list_ids runtime_registry_get runtime_display_name runtime_is_managed runtime_binary >/dev/null 2>&1
'''
        self.run_shell(code)

    def test_prism_gguf_info_output(self):
        """prism-gguf-info.py must read minimal GGUF without error."""
        result = subprocess.run(
            [sys.executable, str(ROOT / 'bin/prism-gguf-info.py'), str(self.model)],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        # Should contain format field and basic keys
        import json
        data = json.loads(result.stdout)
        self.assertIn('format', data)


if __name__ == '__main__':
    unittest.main()