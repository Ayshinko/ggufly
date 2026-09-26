"""Small synthetic headers test renamed models and malformed input."""
import importlib.util
import pathlib
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'info', pathlib.Path(__file__).parents[1] / 'bin/ggufly-gguf-info.py')
info = importlib.util.module_from_spec(spec)
spec.loader.exec_module(info)


class MetadataTests(unittest.TestCase):
    def test_types(self):
        for ftype, label in ((0, "F32"), (15, "Q4_K_M"), (27, "IQ3_M"), (28, "IQ2_S"), (40, "Q1_0"), (41, "Q2_0"), (128, "Unknown (128)"), (129, "Unknown (129)")):
            with tempfile.NamedTemporaryFile() as file:
                key = b'general.file_type'
                file.write(b'GGUF' + struct.pack('<IQQ', 3, 0, 1))
                file.write(struct.pack('<Q', len(key)) + key)
                file.write(struct.pack('<II', 4, ftype))
                file.flush()
                metadata = info.inspect(file.name)
                self.assertEqual(metadata['general.file_type'], ftype)
                self.assertEqual(metadata['quantization'], label)

    def test_truncation(self):
        with tempfile.NamedTemporaryFile() as file:
            file.write(b'GGUF')
            file.flush()
            with self.assertRaises(ValueError):
                info.inspect(file.name)

    def test_rejects_unsupported_headers_and_excessive_counts(self):
        for header in (b'NOPE' + struct.pack('<IQQ', 3, 0, 0),
                       b'GGUF' + struct.pack('<IQQ', 1, 0, 0),
                       b'GGUF' + struct.pack('<IQQ', 3, 0, 100001)):
            with self.subTest(header=header), tempfile.NamedTemporaryFile() as file:
                file.write(header)
                file.flush()
                with self.assertRaises(ValueError):
                    info.inspect(file.name)

    def test_invalid_file_type(self):
        with tempfile.NamedTemporaryFile() as file:
            key = b'general.file_type'
            file.write(b'GGUF' + struct.pack('<IQQ', 3, 0, 1))
            file.write(struct.pack('<Q', len(key)) + key)
            file.write(struct.pack('<IQ', 8, 3) + b'bad')
            file.flush()
            with self.assertRaises(ValueError):
                info.inspect(file.name)


if __name__ == '__main__':
    unittest.main()