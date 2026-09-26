"""Unit tests for the llama-server help capability parser."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'backend_info', ROOT / 'bin/ggufly-backend-info.py')
backend_info = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend_info)

MODERN_HELP = (ROOT / 'tests/fixtures/backend-help-modern.txt').read_text()


class BackendHelpParserTests(unittest.TestCase):
    def inspect(self, text):
        return backend_info.inspect_help(text)

    def test_boolean_flag_has_empty_usage_and_description(self):
        options = self.inspect('\x1b[32m--jinja\x1b[0m                                enable templates\n')
        self.assertEqual(options['--jinja']['usage'], '')
        self.assertEqual(options['--jinja']['description'], 'enable templates')
        self.assertFalse(options['--jinja']['removed'])

    def test_wrapped_description_and_optional_enum_usage(self):
        options = self.inspect(
            '--spec-type none,draft-simple,draft-mtp\n'
            '                                        comma-separated list of types\n'
            '                                        (default: none)\n')
        option = options['--spec-type']
        self.assertEqual(option['usage'], 'none,draft-simple,draft-mtp')
        self.assertEqual(
            option['description'],
            'comma-separated list of types\n(default: none)')
        self.assertEqual(
            option['values'], ['none', 'draft-simple', 'draft-mtp'])

    def test_removed_aliases_share_usage_description_and_state(self):
        options = self.inspect(
            '--draft, --draft-n, --draft-max N       the argument has been removed. use --spec-draft-n-max\n'
            '                                        replacement text\n')
        for name in ('--draft', '--draft-n', '--draft-max'):
            self.assertEqual(options[name]['usage'], 'N')
            self.assertEqual(
                options[name]['description'],
                'the argument has been removed. use --spec-draft-n-max\nreplacement text')
            self.assertTrue(options[name]['removed'])
        self.assertIs(options['--draft'], options['--draft-n'])

    def test_removed_wording_variants(self):
        options = self.inspect(
            '--old-option                 this option was removed.\n'
            '--gone                     has now been removed.\n'
            '--retired                  is no longer available.\n'
            '--unsupported              is removed from this build.\n')
        self.assertTrue(all(options[name]['removed'] for name in (
            '--old-option', '--gone', '--retired', '--unsupported')))

    def test_prose_flag_mentions_are_not_advertised(self):
        options = self.inspect(
            '--real N                         real option\n'
            'Vision mentions --real N but does not advertise it.\n'
            '--not-advertised N is mentioned in prose.\n')
        self.assertEqual(set(options), {'--real'})
        self.assertEqual(options['--real']['description'], 'real option')

    def test_ansi_tabs_indentation_blank_lines_and_headings(self):
        options = self.inspect(
            '\x1b[31m  --alpha, --beta [on|off|auto]\t\tchoose a mode\x1b[0m\n'
            '\n'
            '----- section ----- \n'
            '  --gamma <0|1>                    strict placement\n')
        self.assertEqual(set(options), {'--alpha', '--beta', '--gamma'})
        self.assertEqual(options['--alpha']['usage'], '[on|off|auto]')
        self.assertEqual(options['--alpha']['values'], ['on', 'off', 'auto'])
        self.assertEqual(options['--gamma']['usage'], '<0|1>')
        self.assertEqual(options['--gamma']['values'], ['0', '1'])

    def test_multiline_alias_declaration(self):
        options = self.inspect(
            '-kvo,  --kv-offload, -nkvo, --no-kv-offload\n'
            '                                        whether to enable KV cache offloading\n'
            '                                        (env: LLAMA_ARG_KV_OFFLOAD)\n')
        self.assertEqual(
            set(options),
            {'-kvo', '--kv-offload', '-nkvo', '--no-kv-offload'})
        self.assertEqual(options['-kvo']['usage'], '')
        self.assertEqual(
            options['-kvo']['description'],
            'whether to enable KV cache offloading\n(env: LLAMA_ARG_KV_OFFLOAD)')

    def test_argument_only_and_complex_usage_forms(self):
        options = self.inspect(
            '--control-vector-layer-range START END\n'
            '--override-tensor <tensor name pattern>=<buffer type>,...\n'
            '--docker-repo [<repo>/]<model>[:quant]\n')
        self.assertEqual(options['--control-vector-layer-range']['usage'], 'START END')
        self.assertEqual(
            options['--override-tensor']['usage'],
            '<tensor name pattern>=<buffer type>,...')
        self.assertEqual(
            options['--docker-repo']['usage'],
            '[<repo>/]<model>[:quant]')

    def test_modern_fixture(self):
        options = self.inspect(MODERN_HELP)
        self.assertEqual(options['--jinja']['usage'], '')
        self.assertEqual(options['--mmproj']['usage'], 'FILE')
        self.assertEqual(
            options['--spec-type']['values'][3], 'draft-mtp')
        for name in ('--draft', '--draft-n', '--draft-max',
                     '--draft-min', '--draft-n-min'):
            self.assertTrue(options[name]['removed'])

    def test_realistic_modern_help_edges(self):
        text = '''----- common params -----
-h,    --help, --usage                  print usage and exit
--version                               show version and build info
-kvo,  --kv-offload, -nkvo, --no-kv-offload
                                        whether to enable KV cache offloading
--cpu-strict <0|1>                      use strict CPU placement
--spec-type none,draft-simple,draft-mtp
                                        comma-separated list of types
--draft, --draft-n, --draft-max N       the argument has been removed.
                                        use --spec-draft-n-max
--mmproj-auto, --no-mmproj, --no-mmproj-auto
                                        whether to use a projector
'''
        options = self.inspect(text)
        self.assertEqual(options['--help']['usage'], '')
        self.assertEqual(options['--kv-offload']['usage'], '')
        self.assertEqual(options['--cpu-strict']['usage'], '<0|1>')
        self.assertEqual(options['--spec-type']['values'], [
            'none', 'draft-simple', 'draft-mtp'])
        self.assertTrue(options['--draft-max']['removed'])
        self.assertEqual(options['--mmproj-auto']['usage'], '')


if __name__ == '__main__':
    unittest.main()