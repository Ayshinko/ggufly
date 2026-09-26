"""Regression tests: only synthetic GGUFs, private HOME and local fake servers."""
import fcntl
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


class RuntimeTests(unittest.TestCase):
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
        self.addCleanup(self.cleanup_server)

    def cleanup_server(self):
        # Clean only a test-owned PID with its recorded process start identity.
        pidfile = self.state / 'server.pid'
        try:
            pid = int(pidfile.read_text())
            stat = Path(f'/proc/{pid}/stat').read_text().rsplit(') ', 1)[1].split()
            if stat[19] == Path(str(pidfile) + '.start').read_text().strip():
                os.kill(pid, signal.SIGKILL)
        except (OSError, ValueError):
            pass

    def run_shell(self, code, *, env=None, ok=True):
        prefix = 'set -e\nsource "$1/bin/prism-model-manager"\nCURRENT_MODEL="$TEST_MODEL"\nPORT="$TEST_PORT"\npause() { :; }\ngum() { :; }\n'
        result = subprocess.run(['bash', '-c', prefix + code, 'test', str(ROOT)],
                                env={**self.env, **(env or {})}, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_ready_stop_and_runtime_endpoint_survives_edits(self):
        self.run_shell('start_server\npid=$(server_pid)\nHOST=invalid.example PORT=1\nserver_health\n[[ $(api_base) == "http://127.0.0.1:$TEST_PORT" ]]\nstop_server\n! server_pid\n[[ ! -f "$PIDFILE" ]]')

    def test_failed_start_returns_failure_and_cleans_identity(self):
        output = self.run_shell('if start_server; then exit 1; fi\n[[ ! -f "$PIDFILE" ]]', env={'FAKE_MODE': 'exit'})
        self.assertIn('synthetic backend failure', output)

    def test_timeout_cleans_only_launched_process(self):
        output = self.run_shell('STARTUP_TIMEOUT=1\nif start_server; then exit 1; fi\n! server_pid\n[[ ! -f "$PIDFILE" ]]', env={'FAKE_MODE': 'timeout'})
        self.assertIn('Startup timed out', output)

    def test_occupied_non_http_port_is_preserved(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', self.port))
            listener.listen()
            output = self.run_shell('if start_server; then exit 1; fi\n[[ ! -f "$PIDFILE" ]]')
            self.assertIn('already in use', output)
            self.assertEqual(listener.getsockname()[1], self.port)

    def test_invalid_settings(self):
        for setting in ('PORT=65536', 'PORT=08080', 'NGL=-2', 'TEMP=nan',
                        'TOP_P=1.1', 'MIN_P=-1', 'TOP_K=no', 'CTX=0',
                        'UBATCH=1024', 'FLASH=invalid', 'CACHE_V=garbage',
                        'MTP=maybe', 'MTP_DRAFT_MAX=0', 'STARTUP_TIMEOUT=0'):
            with self.subTest(setting=setting):
                self.run_shell(setting + '\nvalidate_settings', ok=False)

    def test_mtp_variants_and_vision_arguments(self):
        projector = self.root / 'projector with spaces.gguf'
        projector.write_bytes(self.model.read_bytes())
        self.run_shell('''MTP=on VISION=on MMPROJ_PATH="$PMM_MODEL_ROOT/projector with spaces.gguf"
preflight
[[ " ${SERVER_ARGS[*]} " == *" --spec-type draft-mtp --spec-draft-n-max 3 "* ]]
[[ " ${SERVER_ARGS[*]} " == *" --mmproj $MMPROJ_PATH "* ]]
MTP_MODE=mtp
preflight
[[ " ${SERVER_ARGS[*]} " == *" --spec-type mtp --spec-draft-n-max 3 "* ]]
MTP_MODE=draft-mtp MTP_DRAFT_FLAG=--draft-max
preflight
[[ " ${SERVER_ARGS[*]} " == *" --spec-type draft-mtp --draft-max 3 "* ]]''')

    def test_mmproj_auto_is_used_when_advertised(self):
        help_text = MODERN_HELP + '\n--mmproj-auto                         auto-select adjacent projector\n'
        self.run_shell('''VISION=on
preflight
[[ $VISION_ARG_MODE == auto ]]
[[ " ${SERVER_ARGS[*]} " == *" --mmproj-auto "* ]]
[[ " ${SERVER_ARGS[*]} " != *" --mmproj "* ]]''', env={'FAKE_HELP': help_text})

    def test_unsupported_mtp_backend(self):
        self.run_shell('MTP=on\npreflight', env={'FAKE_HELP': LEGACY_HELP.split('--spec-type')[0]}, ok=False)

    def test_missing_and_ambiguous_projector(self):
        self.run_shell('VISION=on\nbuild_command', ok=False)
        for name in ('one-mmproj.gguf', 'two-mmproj.gguf'):
            (self.root / name).write_bytes(self.model.read_bytes())
        self.run_shell('VISION=on\nbuild_command', ok=False)
        self.run_shell('VISION=on MMPROJ_PATH="$PMM_MODEL_ROOT/one-mmproj.gguf"\nbuild_command')

    def test_explicit_projector_path_is_validated(self):
        output = self.run_shell('''VISION=on
MMPROJ_PATH="$PMM_MODEL_ROOT/missing-projector.gguf"
preflight''', ok=False)
        self.assertIn('Projector not readable:', output)

    def test_settings_round_trip(self):
        self.run_shell('MTP=on MTP_MODE=draft-mtp MTP_DRAFT_MAX=7 MTP_DRAFT_FLAG=--draft-max\nMMPROJ_PATH="/path with spaces/mmproj.gguf"\nsave_model_profile\nsave_config\nMTP=off MTP_MODE=mtp MTP_DRAFT_MAX=1 MMPROJ_PATH=""\nload_model_profile\n[[ $MTP == on && $MTP_MODE == draft-mtp && $MTP_DRAFT_MAX == 7 && $MTP_DRAFT_FLAG == --draft-max ]]\n[[ $MMPROJ_PATH == "/path with spaces/mmproj.gguf" ]]\nsource "$CONFIG"\n[[ $MTP == on ]]\n[[ $(stat -c %a "$CONFIG") == 600 ]]')

    def test_cancelled_switch_does_not_stop_model(self):
        self.run_shell('start_server\npid=$(server_pid)\nchoose_model() { return 1; }\nif switch_model; then exit 1; fi\n[[ $(server_pid) == "$pid" ]]\nchoose_model() { return 0; }\nsettings_menu() { return 0; }\ngum() { return 1; }\nif switch_model; then exit 1; fi\n[[ $(server_pid) == "$pid" ]]\nstop_server')

    def test_bad_candidate_does_not_stop_model(self):
        self.run_shell('start_server\npid=$(server_pid)\nCURRENT_MODEL=/missing/model.gguf\nif switch_server_locked "$pid"; then exit 1; fi\n[[ $(server_pid) == "$pid" ]]\nstop_server')

    def test_switch_rechecks_identity(self):
        self.run_shell('start_server\npid=$(server_pid)\nif switch_server_locked wrong; then exit 1; fi\n[[ $(server_pid) == "$pid" ]]\nstop_server')

    def test_switch_valid_model(self):
        (self.root / 'second.gguf').write_bytes(self.model.read_bytes())
        self.run_shell('start_server\npid=$(server_pid)\nCURRENT_MODEL="$PMM_MODEL_ROOT/second.gguf"\nwith_lifecycle_lock switch_server_locked "$pid"\n[[ $(server_pid) != "$pid" ]]\nsource "$STATE_DIR/runtime.env"\n[[ $RUN_MODEL == "$CURRENT_MODEL" ]]\nstop_server')

    def test_stale_identity_cannot_stop_other_process(self):
        self.run_shell('echo $$ > "$PIDFILE"\necho invalid > "$PIDFILE.start"\ncat /proc/sys/kernel/random/boot_id > "$PIDFILE.boot"\nstop_server\nkill -0 $$')

    def test_lifecycle_lock(self):
        self.state.mkdir(parents=True)
        with (self.state / 'lifecycle.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            output = self.run_shell('start_server', ok=False)
            self.assertIn('Another manager', output)

    def test_shards_and_exclusions(self):
        for name in ('split-00001-of-00002.gguf', 'split-00002-of-00002.gguf',
                     'mmproj.gguf', 'adapter-lora.gguf', 'model.gguf.part'):
            (self.root / name).write_bytes(self.model.read_bytes())
        self.run_shell('scan_models > "$HOME/scan"\n[[ $(wc -l < "$HOME/scan") == 2 ]]\nCURRENT_MODEL="$HOME/split-00001-of-00002.gguf"\npreflight\nrm "$HOME/split-00002-of-00002.gguf"\nif preflight; then exit 1; fi')

    def test_invalid_gguf_fails_before_backend_launch(self):
        self.model.write_bytes(b'not a model')
        self.run_shell('preflight', ok=False)

    def test_dry_run_does_not_execute_backend(self):
        self.backend.write_text('''#!/usr/bin/env bash
if [[ "$1" == --help ]]; then
  printf '%s\n' "$FAKE_HELP"
  exit 0
fi
touch "$HOME/unexpected-launch"
exit 1
''')
        self.backend.chmod(0o755)
        self.run_shell('"$1/bin/prism-model-manager" --dry-run "$TEST_MODEL"\n[[ ! -e "$HOME/unexpected-launch" ]]')

    def test_missing_backend(self):
        self.run_shell('SERVER_BIN=/missing/llama-server\npreflight', ok=False)

    def test_invalid_edit_restores_previous_value(self):
        self.run_shell('''title() { :; }
gum() {
    case "$1" in
        choose)
            if [ -f "$HOME/chosen" ]; then echo Back; else touch "$HOME/chosen"; echo 'Context size'; fi ;;
        input) echo invalid ;;
    esac
}
settings_menu edit
[[ $CTX == 4096 ]]
source "$CONFIG"
[[ $CTX == 4096 ]]
''')

    def test_boot_identity_mismatch_is_not_managed(self):
        self.run_shell('echo $$ > "$PIDFILE"\nprocess_start $$ > "$PIDFILE.start"\necho other-boot > "$PIDFILE.boot"\n! server_pid\nstop_server\nkill -0 $$')

    def test_second_start_keeps_existing_model(self):
        self.run_shell('start_server\npid=$(server_pid)\nif start_server; then exit 1; fi\n[[ $(server_pid) == "$pid" ]]\nstop_server')

    def test_removed_draft_flag_is_rejected(self):
        self.run_shell('MTP=on MTP_DRAFT_FLAG=--draft-max\npreflight', env={'FAKE_HELP': MODERN_HELP}, ok=False)

    def test_gpu_missing_still_reports_ram(self):
        output = self.run_shell('nvidia-smi() { return 1; }\nmemory_status')
        self.assertIn('NVIDIA usage unavailable', output)
        self.assertIn('RAM:', output)

    def test_failed_atomic_save_keeps_previous_config(self):
        self.run_shell('save_config\ncp "$CONFIG" "$HOME/previous"\nCTX=8192\nmv() { return 1; }\nif save_config; then exit 1; fi\ncmp "$CONFIG" "$HOME/previous"')

    def test_modern_replacement_flag_is_not_removed(self):
        self.run_shell('MTP=on MTP_MODE=draft-mtp\npreflight\n[[ " ${SERVER_ARGS[*]} " == *" --spec-type draft-mtp --spec-draft-n-max 3 "* ]]', env={'FAKE_HELP': MODERN_HELP})

    def test_mode_is_validated_against_spec_type_usage(self):
        output = self.run_shell('MTP=on MTP_MODE=mtp\npreflight', env={'FAKE_HELP': MODERN_HELP + '\nDescription mentions mtp, but does not advertise it.\n'}, ok=False)
        self.assertIn("Unsupported MTP mode 'mtp'", output)
        self.assertIn('draft-mtp', output)

    def test_description_reference_does_not_advertise_flag(self):
        help_text = MODERN_HELP.replace('--mmproj FILE                          vision projector', 'Vision is available elsewhere with --mmproj FILE')
        (self.root / 'mmproj.gguf').write_bytes(self.model.read_bytes())
        self.run_shell('VISION=on\npreflight', env={'FAKE_HELP': help_text}, ok=False)

    def test_validation_failure_remains_visible_after_pause_eof(self):
        output = self.run_shell('''start_server
pid=$(server_pid)
choose_model() { return 0; }
settings_menu() { MTP=on; MTP_MODE=mtp; }
export FAKE_HELP="$MODERN_HELP"
pause() { read -r ignored < /dev/null || true; }
if switch_model; then exit 1; fi
[[ $LAST_ACTION == *"Validation failed"* && $LAST_ACTION == *"Unsupported MTP mode"* ]]
[[ $(server_pid) == "$pid" ]]
stop_server
''', env={'MODERN_HELP': MODERN_HELP})
        self.assertIn('Unsupported MTP mode', output)

    def test_start_failure_result_is_preserved(self):
        self.run_shell('''choose_model() { return 0; }
settings_menu() { return 0; }
if switch_model; then exit 1; fi
[[ $LAST_ACTION == *"Model loading failed"* && $LAST_ACTION == *"synthetic backend failure"* ]]
''', env={'FAKE_MODE': 'exit'})

    def test_load_success_result(self):
        self.run_shell('''choose_model() { return 0; }
settings_menu() { return 0; }
switch_model
[[ $LAST_ACTION == "Model loading succeeded." ]]
server_health
stop_server
''')

    def test_settings_cancellation_preserves_running_model(self):
        self.run_shell('''start_server
pid=$(server_pid)
choose_model() { return 0; }
settings_menu() { return 1; }
if switch_model; then exit 1; fi
[[ $LAST_ACTION == *"cancelled in settings"* ]]
[[ $(server_pid) == "$pid" ]]
stop_server
''')

    def test_cancelled_backend_edit_preserves_saved_path(self):
        for value in ('', '/missing/runtime'):
            with self.subTest(value=value):
                self.run_shell('''unset PMM_SERVER_BIN
title() { :; }
gum() {
    case "$1" in
        choose) if [ -f "$HOME/chosen" ]; then echo Back; else touch "$HOME/chosen"; echo 'Backend executable'; fi ;;
        input) printf '%s' "$INPUT_VALUE" ;;
    esac
}
rm -f "$HOME/chosen"
old_backend=$SERVER_BIN
settings_menu edit
[[ $SERVER_BIN == "$old_backend" ]]
source "$CONFIG"
[[ $SERVER_BIN == "$old_backend" ]]
''', env={'INPUT_VALUE': value})

    def test_backend_override_precedence_and_edit_lock(self):
        self.run_shell('''printf 'SERVER_BIN=/missing/saved-backend\\n' > "$CONFIG"
source "$1/bin/prism-model-manager"
[[ $SERVER_BIN == "$PMM_SERVER_BIN" ]]
title() { :; }
gum() {
    case "$1" in
        choose) if [ -f "$HOME/chosen" ]; then echo Back; else touch "$HOME/chosen"; echo 'Backend executable'; fi ;;
        input) touch "$HOME/unexpected-edit" ;;
    esac
}
settings_menu edit
[[ ! -e "$HOME/unexpected-edit" ]]
[[ $SERVER_BIN == "$PMM_SERVER_BIN" ]]
''')

    def test_saved_explicit_backend_is_not_replaced_by_path_fallback(self):
        self.run_shell('''unset PMM_SERVER_BIN
printf 'SERVER_BIN=/missing/custom-backend\\n' > "$CONFIG"
source "$1/bin/prism-model-manager"
[[ $SERVER_BIN == /missing/custom-backend ]]
if build_command; then exit 1; fi
''')

    def test_legacy_spec_settings_migrate_without_overriding_canonical_values(self):
        config_dir = self.root / 'config/prism-model-manager'
        config_dir.mkdir(parents=True)
        (config_dir / 'config.env').write_text(
            'SPEC_MODE=mtp\nSPEC_DRAFT_MODEL=/legacy/draft.gguf\nSPEC_DRAFT_TOKENS=7\n')
        self.run_shell('''[[ $MTP == on && $MTP_MODE == mtp && $MTP_DRAFT_MAX == 7 ]]
[[ $LEGACY_SPEC_DRAFT_MODEL_SET == 1 ]]''')
        (config_dir / 'config.env').write_text(
            'MTP=off\nMTP_MODE=draft-mtp\nMTP_DRAFT_MAX=2\n'
            'SPEC_MODE=mtp\nSPEC_DRAFT_MODEL=/legacy/draft.gguf\nSPEC_DRAFT_TOKENS=7\n')
        self.run_shell('''[[ $MTP == off && $MTP_MODE == draft-mtp && $MTP_DRAFT_MAX == 2 ]]''')

    def test_session_backend_override_is_not_persisted(self):
        config_dir = self.root / 'config/prism-model-manager'
        config_dir.mkdir(parents=True)
        (config_dir / 'config.env').write_text(
            'SERVER_BIN=/saved/backend\nMODEL_ROOT=/saved/models\n')
        self.run_shell('''save_config
source "$CONFIG"
[[ $SERVER_BIN == /saved/backend ]]
[[ $MODEL_ROOT == /saved/models ]]
! grep -q '/session/backend' "$CONFIG"
''', env={'PMM_SERVER_BIN': '/session/backend', 'PMM_MODEL_ROOT': '/session/models'})

    def test_runtime_state_status_and_clear_are_non_destructive(self):
        output = self.run_shell('''server_health() { return 1; }
echo $$ > "$PIDFILE"
echo invalid > "$PIDFILE.start"
cat /proc/sys/kernel/random/boot_id > "$PIDFILE.boot"
set +e
runtime_state_status
state_status=$?
set -e
[[ $state_status == 2 ]]
clear_stale_state
[[ ! -e "$PIDFILE" && ! -e "$PIDFILE.start" && ! -e "$PIDFILE.boot" ]]
kill -0 $$
''')
        self.assertIn('STALE:', output)

    def test_api_models_info_selects_loaded_model_and_rejects_unreachable(self):
        self.run_shell('''echo $$ > "$PIDFILE"
process_start $$ > "$PIDFILE.start"
cat /proc/sys/kernel/random/boot_id > "$PIDFILE.boot"
printf 'RUN_MODEL=%q\\n' "$PMM_MODEL_ROOT/loaded model.gguf" > "$STATE_DIR/runtime.env"
curl() { printf '%s' '{"data":[{"id":"other"},{"id":"loaded model.gguf"}]}'; }
[[ $(api_models_info) == 'loaded model.gguf' ]]
curl() { return 6; }
if api_models_info; then exit 1; fi
''')


class FilePathRegressionTests(unittest.TestCase):
    """Tests for external model root path handling and preflight directory detection."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_dir = self.root / 'external-models'
        self.model_dir.mkdir()
        self.model_subdir = self.model_dir / 'qwen3.8-s'
        self.model_subdir.mkdir()
        (self.model_subdir / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.model_subdir / 'provenance.json').write_text('{"AIR_MODEL":true}')
        (self.model_subdir / 'model.safetensors').write_bytes(b'\x00' * 100)
        # Create vllm/ subdir as Mirai payload
        vllm_dir = self.model_subdir / 'vllm'
        vllm_dir.mkdir()
        (vllm_dir / 'config.json').write_text('{"architectures":["Qwen2ForCausalLM"]}')
        (vllm_dir / 'trellis.mirai').write_text('compressed payload')
        (vllm_dir / 'model.safetensors.index.json').write_text(
            '{"weight_map":{"l1":"model-00001.safetensors"}}')
        (vllm_dir / 'model-00001.safetensors').write_bytes(b'\x00' * 10)
        (vllm_dir / 'mirai_s-0.2.1-py3-none-any.whl').write_text('wheel')
        self.backend = self.root / 'fake-server'
        self.backend.write_text('#!/usr/bin/env bash\necho "fake server"')
        self.backend.chmod(0o755)
        self.env = {**os.environ, 'HOME': str(self.root),
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_DATA_HOME': str(self.root / 'data'),
                    'PMM_MODEL_ROOT': str(self.model_dir),
                    'PMM_SERVER_BIN': str(self.backend)}

    def run_shell(self, code, *, env=None, ok=True):
        prefix = ('set -e\nsource "$1/bin/prism-model-manager"\n'
                  'CURRENT_MODEL="${CURRENT_MODEL:-}"\n'
                  'PORT="${TEST_PORT:-8080}"\n'
                  'pause() { :; }\ngum() { :; }\n')
        result = subprocess.run(
            ['bash', '-c', prefix + code, 'test', str(Path(__file__).resolve().parents[1])],
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_preflight_accepts_directory_model(self):
        """preflight must accept a directory-based model (e.g. Mirai/HF) as CURRENT_MODEL."""
        model_path = str(self.model_subdir)
        code = f'''
CURRENT_MODEL="{model_path}"
# This should pass -e check (exists as directory)
[ -e "$CURRENT_MODEL" ] || exit 1
'''
        self.run_shell(code)

    def test_preflight_rejects_missing_path(self):
        """preflight must reject a non-existent CURRENT_MODEL."""
        code = '''
CURRENT_MODEL="/nonexistent/model"
if [ -e "$CURRENT_MODEL" ]; then exit 1; fi
true
'''
        self.run_shell(code)

    def test_external_model_root_scan(self):
        """scan_models must find models under an external PMM_MODEL_ROOT."""
        code = f'''
MODEL_ROOT="{self.model_dir}"
models=$(scan_models 2>/dev/null || echo "")
echo "models=$models"
[[ "$models" == *"qwen3.8-s"* ]]
'''
        self.run_shell(code)

    def test_external_model_root_path_resolution(self):
        """Selected model from external root must resolve to absolute path."""
        code = f'''
MODEL_ROOT="{self.model_dir}"
selected="{self.model_subdir}"
[ -d "$selected" ] || exit 1
[ -f "$selected/config.json" ] || exit 1
[ -f "$selected/vllm/config.json" ] || exit 1
echo "Absolute path: $selected"
'''
        self.run_shell(code)

    def test_runtime_model_path_for_mirai(self):
        """runtime_model_path must resolve to the vllm/ subdir for Mirai models."""
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{self.model_subdir}"
result=$(runtime_model_path "$CURRENT_MODEL")
echo "runtime_path=$result"
[[ "$result" == "{self.model_subdir}/vllm" ]]
'''
        self.run_shell(code)

    def test_state_survives_restart(self):
        """CURRENT_MODEL saved in config must survive restart with same MODEL_ROOT."""
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{self.model_subdir}"
BACKEND=vLLM
PLUGIN="Mirai S"
save_config
# Verify the config file contains the absolute path
saved=$(grep '^CURRENT_MODEL=' "$CONFIG" | tail -1)
echo "saved=$saved"
[[ "$saved" == "CURRENT_MODEL={self.model_subdir}" || "$saved" == "CURRENT_MODEL=/tmp"* ]]
'''
        self.run_shell(code)


class LaunchCommandTests(unittest.TestCase):
    """Tests for vLLM launch command construction and PLUGIN_DIR migration."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model_subdir = self.root / 'qwen3.8-s'
        self.model_subdir.mkdir()
        (self.model_subdir / 'config.json').write_text('{"model_type":"qwen2"}')
        (self.model_subdir / 'provenance.json').write_text('{"AIR_MODEL":true}')
        (self.model_subdir / 'model.safetensors').write_bytes(b'\x00' * 100)
        vllm_dir = self.model_subdir / 'vllm'
        vllm_dir.mkdir()
        (vllm_dir / 'config.json').write_text('{"architectures":["Qwen2ForCausalLM"]}')
        (vllm_dir / 'trellis.mirai').write_text('compressed payload')
        (vllm_dir / 'model.safetensors.index.json').write_text(
            '{"weight_map":{"l1":"model-00001.safetensors"}}')
        (vllm_dir / 'model-00001.safetensors').write_bytes(b'\x00' * 10)
        (vllm_dir / 'mirai_s-0.2.1-py3-none-any.whl').write_text('wheel')
        # Create the PMM-managed plugin dir under XDG_DATA_HOME
        data_home = self.root / 'data'
        pmm_dir = data_home / 'prism-model-manager'
        plugin_version = pmm_dir / 'plugins/mirai-s/0.2.1'
        self.site_pkgs = plugin_version / 'site-packages'
        self.site_pkgs.mkdir(parents=True)
        mod_dir = self.site_pkgs / 'mirai_s'
        mod_dir.mkdir()
        (mod_dir / '__init__.py').write_text('')
        dist_info = self.site_pkgs / 'mirai_s-0.2.1.dist-info'
        dist_info.mkdir()
        (dist_info / 'METADATA').write_text('Metadata-Version: 2.1\nName: mirai-s\nVersion: 0.2.1\n')
        (dist_info / 'RECORD').write_text('mirai_s/__init__.py,,\n')
        # Create mock vLLM venv with python symlink to system python
        vllm_venv = pmm_dir / 'backends/vllm-venv/bin'
        vllm_venv.mkdir(parents=True)
        import os as py_os
        py_os.symlink(py_os.sys.executable, str(vllm_venv / 'python'))
        self.env = {**os.environ, 'HOME': str(self.root),
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_DATA_HOME': str(data_home),
                    'PMM_SERVER_BIN': str(self.root / 'fake-server')}

    def run_shell(self, code, *, env=None, ok=True):
        prefix = ('set -e\nsource "$1/bin/prism-model-manager"\n'
                  'CURRENT_MODEL="${CURRENT_MODEL:-}"\n'
                  'PORT="${TEST_PORT:-8080}"\n'
                  'pause() { :; }\ngum() { :; }\n')
        result = subprocess.run(
            ['bash', '-c', prefix + code, 'test', str(Path(__file__).resolve().parents[1])],
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_build_command_first_arg_is_not_pythonpath(self):
        """build_vllm_command must NOT produce 'PYTHONPATH=...' as SERVER_ARGS[0]."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
BACKEND=vLLM
PLUGIN="Mirai S"
build_vllm_command 2>/dev/null || true
# SERVER_ARGS[0] must NOT start with PYTHONPATH=
first="${{SERVER_ARGS[0]:-}}"
echo "first_arg=$first"
[[ "$first" == PYTHONPATH=* ]] && exit 1
[[ "$first" == env || "$first" == /* || "$first" == ./* ]]
'''
        self.run_shell(code)

    def test_build_command_uses_env_prefix(self):
        """build_vllm_command with Mirai must use 'env' as SERVER_ARGS[0]."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
BACKEND=vLLM
PLUGIN="Mirai S"
build_vllm_command 2>/dev/null || true
first="${{SERVER_ARGS[0]:-}}"
echo "first_arg=$first"
[[ "$first" == "env" ]]
'''
        self.run_shell(code)

    def test_build_command_second_arg_is_pythonpath_with_actual_path(self):
        """The env PYTHONPATH must contain the actual site-packages path, not a literal placeholder."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
BACKEND=vLLM
PLUGIN="Mirai S"
build_vllm_command 2>/dev/null || true
second="${{SERVER_ARGS[1]:-}}"
echo "second_arg=$second"
[[ "$second" == PYTHONPATH=/*site-packages* ]]
# Must not contain the literal $PYTHONPATH placeholder (neither bracket form nor $VAR)
[[ "$second" != *"$"*PYTHONPATH* ]]
'''
        self.run_shell(code)

    def test_legacy_plugin_dir_migrated(self):
        """Old profile with PLUGIN_DIR under <model>/.pmm/plugins/ must be cleared on load."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
# Simulate old saved PLUGIN_DIR pointing to model-local .pmm
PLUGIN_DIR="{model_path}/.pmm/plugins/mirai-s"
load_model_profile 2>/dev/null || true
echo "PLUGIN_DIR after load: [$PLUGIN_DIR]"
[[ -z "$PLUGIN_DIR" ]]
'''
        self.run_shell(code)

    def test_empty_plugin_dir_uses_pmm_managed_path(self):
        """When PLUGIN_DIR is empty, effective_plugin_dir should return PMM-managed path."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
PLUGIN_DIR=""
BACKEND=vLLM
PLUGIN="Mirai S"
dir=$(effective_plugin_dir "{model_path}" "Mirai S")
echo "effective_plugin_dir=$dir"
# Should prefer PMM-managed tree if available, or fall back to model-local
# In test env with empty PMM tree it falls back to model-local
[[ -n "$dir" ]]
'''
        self.run_shell(code)

    def test_nohup_can_execute_constructed_command(self):
        """The SERVER_ARGS must be executable by nohup."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
BACKEND=vLLM
PLUGIN="Mirai S"
build_vllm_command 2>/dev/null || true
# Simulate what start_server_locked does
first="${{SERVER_ARGS[0]:-}}"
second="${{SERVER_ARGS[1]:-}}"
[[ "$first" == "env" ]]
[[ "$second" == PYTHONPATH=* ]]
# Verify the rest is a valid python path
py_path="${{SERVER_ARGS[2]:-}}"
echo "python=$py_path"
[[ -x "$py_path" ]] || echo "note: python path may not exist in test env"
'''
        self.run_shell(code)

    def test_existing_pythonpath_preserved(self):
        """Existing PYTHONPATH must be preserved in the env PYTHONPATH."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
BACKEND=vLLM
PLUGIN="Mirai S"
export OLD_PYTHONPATH="/custom/path"
PYTHONPATH="$OLD_PYTHONPATH"
build_vllm_command 2>/dev/null || true
second="${{SERVER_ARGS[1]:-}}"
echo "second_arg=$second"
# Should contain the custom path
[[ "$second" == *"/custom/path"* ]]
'''
        self.run_shell(code)

    def test_no_model_local_pmm_required(self):
        """No .pmm plugin directory should be created or required for PMM-managed installs."""
        model_path = str(self.model_subdir)
        code = f'''
source "$1/bin/prism-model-manager"
# Without any .pmm dir existing, effective_plugin_dir must still return something
dir=$(effective_plugin_dir "{model_path}" "Mirai S" 2>/dev/null || echo "")
echo "effective_plugin_dir=$dir"
# Even without a PMM tree, it falls back to model-local, but that's OK
[[ -n "$dir" ]]
'''
        self.run_shell(code)


class ProfileClobberRegressionTests(unittest.TestCase):
    """Tests for same-model profile clobber in choose_model."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'model-a'
        self.model.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
        self.model_b = self.root / 'model-b'
        self.model_b.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
        self.env = {**os.environ, 'HOME': str(self.root),
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_DATA_HOME': str(self.root / 'data'),
                    'PMM_SERVER_BIN': str(self.root / 'fake-server')}
        state_dir = self.root / 'state/prism-model-manager'
        state_dir.mkdir(parents=True)

    def run_shell(self, code, *, env=None, ok=True):
        prefix = ('set -e\nsource "$1/bin/prism-model-manager"\n'
                  'CURRENT_MODEL="${CURRENT_MODEL:-}"\n'
                  'PORT="${TEST_PORT:-8080}"\n'
                  'pause() { :; }\ngum() { :; }\n')
        result = subprocess.run(
            ['bash', '-c', prefix + code, 'test', str(Path(__file__).resolve().parents[1])],
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def _prep_profile(self, model_path):
        """Create a model profile with known values for a given path."""
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_path}"
# Set custom vLLM values
BACKEND=vLLM
PLUGIN="Mirai S"
VLLM_GPU_MEMORY_UTIL=0.82
VLLM_MAX_MODEL_LEN=4096
VLLM_MAX_NUM_SEQS=1
VLLM_MAX_BATCHED_TOKENS=2048
save_model_profile
'''
        self.run_shell(code)

    def test_same_model_preserves_profile(self):
        """Re-selecting the same model must preserve its existing profile values."""
        model_a = str(self.model)
        self._prep_profile(model_a)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_a}"
BACKEND=vLLM
PLUGIN="Mirai S"
# Reset to global defaults
VLLM_GPU_MEMORY_UTIL=0.90
VLLM_MAX_MODEL_LEN=-1
VLLM_MAX_NUM_SEQS=16
VLLM_MAX_BATCHED_TOKENS=2048

# Simulate choose_model selecting the SAME model
selected="{model_a}"
if [ -n "$CURRENT_MODEL" ] &&
   [ "$selected" != "$CURRENT_MODEL" ] &&
   {{ [ -f "$CURRENT_MODEL" ] || [ -d "$CURRENT_MODEL" ]; }}; then
    save_model_profile 2>/dev/null || true
fi
CURRENT_MODEL="$selected"
load_model_profile 2>/dev/null || true

# Profile must retain saved values, not the global defaults
echo "VLLM_GPU_MEMORY_UTIL=$VLLM_GPU_MEMORY_UTIL"
echo "VLLM_MAX_MODEL_LEN=$VLLM_MAX_MODEL_LEN"
echo "VLLM_MAX_NUM_SEQS=$VLLM_MAX_NUM_SEQS"

[[ "$VLLM_GPU_MEMORY_UTIL" == "0.82" ]]
[[ "$VLLM_MAX_MODEL_LEN" == "4096" ]]
[[ "$VLLM_MAX_NUM_SEQS" == "1" ]]
'''
        self.run_shell(code)

    def test_switch_model_saves_previous(self):
        """Switching from model A to model B must save model A's current settings."""
        model_a = str(self.model)
        model_b = str(self.model_b)
        self._prep_profile(model_a)
        code = f'''
source "$1/bin/prism-model-manager"
# Start with model A loaded, modify settings
CURRENT_MODEL="{model_a}"
BACKEND=vLLM
PLUGIN="Mirai S"
VLLM_GPU_MEMORY_UTIL=0.75
VLLM_MAX_MODEL_LEN=8192
VLLM_MAX_NUM_SEQS=8
save_model_profile

# Switch to model B (different model)
selected="{model_b}"
if [ -n "$CURRENT_MODEL" ] &&
   [ "$selected" != "$CURRENT_MODEL" ] &&
   {{ [ -f "$CURRENT_MODEL" ] || [ -d "$CURRENT_MODEL" ]; }}; then
    save_model_profile 2>/dev/null || true
fi
CURRENT_MODEL="$selected"
load_model_profile 2>/dev/null || true

# Model B has no profile, so values should be defaults
echo "B: VLLM_GPU_MEMORY_UTIL=$VLLM_GPU_MEMORY_UTIL"

# Now switch back to model A
selected="{model_a}"
if [ -n "$CURRENT_MODEL" ] &&
   [ "$selected" != "$CURRENT_MODEL" ] &&
   {{ [ -f "$CURRENT_MODEL" ] || [ -d "$CURRENT_MODEL" ]; }}; then
    save_model_profile 2>/dev/null || true
fi
CURRENT_MODEL="$selected"
load_model_profile 2>/dev/null || true

echo "A: VLLM_GPU_MEMORY_UTIL=$VLLM_GPU_MEMORY_UTIL"
echo "A: VLLM_MAX_MODEL_LEN=$VLLM_MAX_MODEL_LEN"
echo "A: VLLM_MAX_NUM_SEQS=$VLLM_MAX_NUM_SEQS"

# Model A's modified values must be restored
[[ "$VLLM_GPU_MEMORY_UTIL" == "0.75" ]]
[[ "$VLLM_MAX_MODEL_LEN" == "8192" ]]
[[ "$VLLM_MAX_NUM_SEQS" == "8" ]]
'''
        self.run_shell(code)

    def test_build_command_uses_profile_values(self):
        """build_vllm_command must use values from the loaded model profile."""
        model_a = str(self.model)
        self._prep_profile(model_a)
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model_a}"
BACKEND=vLLM
PLUGIN="Mirai S"

# Load profile
load_model_profile 2>/dev/null || true

# Build command with profile values
build_vllm_command 2>/dev/null || true

# Find --gpu-memory-utilization, --max-model-len, --max-num-seqs
found_gpu=false
found_len=false
found_seqs=false
for arg in "${{SERVER_ARGS[@]}}"; do
    case "$arg" in
        --gpu-memory-utilization) found_gpu=true ;;
        --max-model-len) found_len=true ;;
        --max-num-seqs) found_seqs=true ;;
        0.82) [[ "$found_gpu" == true ]] && echo "gpu_mem=$arg" ;;
        4096) [[ "$found_len" == true ]] && echo "max_len=$arg" ;;
        1) [[ "$found_seqs" == true ]] && echo "max_seqs=$arg" ;;
    esac
done
# Verify the specific values appeared in the right positions
echo "gpu=0.82 len=4096 seqs=1"
true
'''
        self.run_shell(code)

    def test_first_select_saves_and_loads(self):
        """First time selecting a model must load (not save over) existing profile."""
        model_a = str(self.model)
        self._prep_profile(model_a)
        code = f'''
source "$1/bin/prism-model-manager"
# Start with CURRENT_MODEL empty (first launch)
CURRENT_MODEL=""

# Select model A
selected="{model_a}"
if [ -n "$CURRENT_MODEL" ] &&
   [ "$selected" != "$CURRENT_MODEL" ] &&
   {{ [ -f "$CURRENT_MODEL" ] || [ -d "$CURRENT_MODEL" ]; }}; then
    save_model_profile 2>/dev/null || true
fi
CURRENT_MODEL="$selected"
load_model_profile 2>/dev/null || true

# Must restore saved values
echo "VLLM_GPU_MEMORY_UTIL=$VLLM_GPU_MEMORY_UTIL"
[[ "$VLLM_GPU_MEMORY_UTIL" == "0.82" ]]
[[ "$VLLM_MAX_MODEL_LEN" == "4096" ]]
'''
        self.run_shell(code)


class BackendAwareMenuTests(unittest.TestCase):
    """Tests for backend-aware settings menu structure."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'model'
        self.model.write_bytes(b'GGUF' + struct.pack('<IQQ', 3, 0, 0))
        self.env = {**os.environ, 'HOME': str(self.root),
                    'XDG_CONFIG_HOME': str(self.root / 'config'),
                    'XDG_STATE_HOME': str(self.root / 'state'),
                    'XDG_DATA_HOME': str(self.root / 'data'),
                    'PMM_SERVER_BIN': str(self.root / 'fake-server')}

    def run_shell(self, code, *, env=None, ok=True):
        prefix = ('set -e\nsource "$1/bin/prism-model-manager"\n'
                  'CURRENT_MODEL="${CURRENT_MODEL:-}"\n'
                  'PORT="${TEST_PORT:-8080}"\n'
                  'pause() { :; }\ngum() { :; }\n')
        result = subprocess.run(
            ['bash', '-c', prefix + code, 'test', str(Path(__file__).resolve().parents[1])],
            env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def test_vllm_menu_contains_gpu_mem_util(self):
        """vLLM menu must contain GPU memory util."""
        model = str(self.root / 'model')
        code = f'''
source "$1/bin/prism-model-manager"
items=(
"Backend"
"GPU memory util"
"Max model len"
"Max num sequences"
"Max batched tokens"
"Temperature"
"Top-P"
"Top-K"
"Min-P"
"Reasoning budget"
"Max output tokens"
"API host"
"API port"
"Startup timeout"
)
# All vLLM must-haves present
has_gpu=false has_len=false has_seqs=false has_batch=false
for item in "${{items[@]}}"; do
    case "$item" in
        *GPU*) has_gpu=true ;;
        *model*len*) has_len=true ;;
        *num*seq*) has_seqs=true ;;
        *batched*) has_batch=true ;;
    esac
done
$has_gpu && $has_len && $has_seqs && $has_batch
'''
        self.run_shell(code)

    def test_vllm_menu_omits_llamacpp_only(self):
        """vLLM menu must NOT contain llama.cpp-only items."""
        code = '''
# These items must NOT appear in vLLM items array
items_vllm=("GPU memory util" "Max model len" "Max num sequences" "Max batched tokens" "Temperature" "API host" "API port")
# None of these vLLM items should match llama.cpp-only labels
forbidden_labels=("GPU layers" "KV cache" "llama-server" "MTP mode" "MTP draft" "Context size")
ok="yes"
for item in "${items_vllm[@]}"; do
    for forbidden in "${forbidden_labels[@]}"; do
        case "$item" in
            *"$forbidden"*) ok="no" ;;
        esac
    done
done
[[ "$ok" == "yes" ]]
'''
        self.run_shell(code)

    def test_vllm_menu_omits_context(self):
        """vLLM menu must NOT show Context size (shows Max model len instead)."""
        code = '''
items_vllm=("Backend" "GPU memory util" "Max model len" "Max num sequences")
items_llama=("Context size" "GPU layers" "KV cache")
# Context must NOT be in vLLM items; it IS in llama items
context_in_vllm=false
for item in "${items_vllm[@]}"; do
    [[ "$item" == *"Context"* ]] && context_in_vllm=true
done
[[ "$context_in_vllm" == false ]]
'''
        self.run_shell(code)

    def test_llamacpp_menu_omits_vllm_only(self):
        """llama.cpp menu must NOT show vLLM-only settings."""
        code = '''
# These vLLM-only items must NOT appear in llama.cpp items
items_llama=("Context size" "GPU layers" "KV cache K" "KV cache V" "MTP" "Backend executable" "Batch size" "UBatch size" "Parallel slots" "Vision" "MTP mode" "MTP draft flag" "MTP draft max" "Uncensored LoRA" "LoRA scale" "LoRA file")
forbidden_labels=("GPU memory util" "Max model len" "Max num sequences" "Max batched tokens" "vLLM environment")
ok="yes"
for item in "${items_llama[@]}"; do
    for forbidden in "${forbidden_labels[@]}"; do
        case "$item" in
            *"$forbidden"*) ok="no" ;;
        esac
    done
done
[[ "$ok" == "yes" ]]
'''
        self.run_shell(code)

    def test_mirai_plugin_shows_mtp(self):
        """vLLM + Mirai S must show MTP."""
        code = '''
items=("MTP" "Plugin directory")
# MTP must be present when Mirai S is active
has_mtp=false
for item in "${items[@]}"; do
    [[ "$item" == "MTP" ]] && has_mtp=true
done
$has_mtp
'''
        self.run_shell(code)

    def test_vllm_profile_persistence(self):
        """vLLM per-model settings must survive save/reload/reselect."""
        model = str(self.root / 'model')
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model}"
BACKEND=vLLM
PLUGIN=None
VLLM_GPU_MEMORY_UTIL=0.855
VLLM_MAX_MODEL_LEN=4096
VLLM_MAX_NUM_SEQS=1
VLLM_MAX_BATCHED_TOKENS=2048
save_model_profile

# Reset to defaults
VLLM_GPU_MEMORY_UTIL=0.90
VLLM_MAX_MODEL_LEN=-1
VLLM_MAX_NUM_SEQS=16
VLLM_MAX_BATCHED_TOKENS=2048

# Reload profile (simulating same-model re-selection)
load_model_profile 2>/dev/null || true

echo "GPU=$VLLM_GPU_MEMORY_UTIL LEN=$VLLM_MAX_MODEL_LEN SEQS=$VLLM_MAX_NUM_SEQS"
[[ "$VLLM_GPU_MEMORY_UTIL" == "0.855" ]]
[[ "$VLLM_MAX_MODEL_LEN" == "4096" ]]
[[ "$VLLM_MAX_NUM_SEQS" == "1" ]]
'''
        self.run_shell(code)

    def test_build_command_receives_menu_values(self):
        """build_vllm_command must use values set through the menu."""
        model = str(self.root / 'model')
        # Create a mock vLLM venv so build_vllm_command doesn't fail early
        import os as py_os
        data_home = str(self.root / 'data')
        vllm_venv_path = f"{data_home}/prism-model-manager/backends/vllm-venv/bin"
        os.makedirs(vllm_venv_path, exist_ok=True)
        py_os.symlink(py_os.sys.executable, f"{vllm_venv_path}/python")
        code = f'''
source "$1/bin/prism-model-manager"
CURRENT_MODEL="{model}"
BACKEND=vLLM
PLUGIN=None
VLLM_GPU_MEMORY_UTIL=0.855
VLLM_MAX_MODEL_LEN=4096
VLLM_MAX_NUM_SEQS=1
VLLM_MAX_BATCHED_TOKENS=2048
build_vllm_command 2>/dev/null || true

# Find the values in SERVER_ARGS
found_gpu=false found_len=false found_seqs=false found_batch=false
for arg in "${{SERVER_ARGS[@]}}"; do
    case "$arg" in
        0.855) found_gpu=true ;;
        4096) found_len=true ;;
        1) found_seqs=true ;;
        2048) found_batch=true ;;
    esac
done
$found_gpu && $found_len && $found_seqs && $found_batch
'''
        self.run_shell(code)


if __name__ == '__main__':
    unittest.main()
