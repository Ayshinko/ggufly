"""Exercise real gum rendering and editing with stdout captured, stderr on a PTY."""
import os
from pathlib import Path
import select
import shutil
import signal
import tempfile
import time
import unittest


@unittest.skipUnless(os.name == 'posix' and shutil.which('gum'), 'requires real gum and a PTY')
class GumTerminalTests(unittest.TestCase):
    def test_visible_editing_and_cancel(self):
        import fcntl
        import pty
        import struct
        import termios

        source = Path(__file__).resolve().parents[1] / 'bin/prism-model-manager'
        cases = (
            (b'\x01\x0b8192', b'\r', b'8192'),  # Ctrl+A, Ctrl+K: replace
            (b'\x7f', b'\r', b'409'),           # Backspace at end
            (b'\x01\x1b[C\x1b[3~', b'\r', b'496'),  # Delete after first digit
            (b'8192', b'\x1b', b'4096'),        # Esc cancels appended text
            (b'8192', b'\x03', b'4096'),        # Ctrl+C cancels
        )
        for editing, submit, expected in cases:
            with self.subTest(editing=editing, submit=submit), tempfile.TemporaryDirectory() as home:
                pid, fd = pty.fork()
                if pid == 0:
                    os.environ.update(HOME=home, XDG_CONFIG_HOME=home+'/config',
                                      XDG_STATE_HOME=home+'/state', XDG_DATA_HOME=home+'/data',
                                      TERM='xterm-256color', LC_ALL='C.UTF-8')
                    os.execvp('bash', ['bash', '-c',
                        'source "$1"; CTX=4096; '
                        'edit_input CTX --value="$CTX"; '
                        'printf "\\nRESULT=%s\\n" "$CTX"', 'test', str(source)])
                data = bytearray()

                def read_until(predicate, timeout=5):
                    deadline = time.monotonic() + timeout
                    while time.monotonic() < deadline:
                        if select.select([fd], [], [], 0.1)[0]:
                            try:
                                chunk = os.read(fd, 65536)
                            except OSError:
                                break
                            data.extend(chunk)
                            if b'\x1b[6n' in chunk:
                                os.write(fd, b'\x1b[1;1R')
                            if predicate(bytes(data)):
                                return
                    self.fail('Missing terminal output: ' + repr(bytes(data)))

                try:
                    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 100, 0, 0))
                    read_until(lambda text: b'> 4096' in text)
                    # gum uses a styled software cursor rather than the hardware cursor.
                    self.assertIn(b'\x1b[', data)
                    before = bytes(data)
                    os.write(fd, editing)
                    read_until(lambda text: text != before)
                    os.write(fd, submit)
                    read_until(lambda text: b'RESULT=' + expected + b'\r\n' in text)
                finally:
                    os.close(fd)
                    if os.waitpid(pid, os.WNOHANG)[0] == 0:
                        os.kill(pid, signal.SIGTERM)
                        os.waitpid(pid, 0)
