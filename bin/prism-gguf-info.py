#!/usr/bin/env python3
"""Read bounded GGUF metadata, without loading tensor data or importing gguf."""
import json
import struct
import sys


# general.file_type is llama_ftype, NOT ggml_type or ggml_ftype.
# Reference: ggml-org/llama.cpp and PrismML-Eng/llama.cpp include/llama.h.
QUANTIZATIONS = {
    0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 7: 'Q8_0',
    8: 'Q5_0', 9: 'Q5_1', 10: 'Q2_K', 11: 'Q3_K_S', 12: 'Q3_K_M',
    13: 'Q3_K_L', 14: 'Q4_K_S', 15: 'Q4_K_M', 16: 'Q5_K_S',
    17: 'Q5_K_M', 18: 'Q6_K', 19: 'IQ2_XXS', 20: 'IQ2_XS',
    21: 'Q2_K_S', 22: 'IQ3_XS', 23: 'IQ3_XXS', 24: 'IQ1_S',
    25: 'IQ4_NL', 26: 'IQ3_S', 27: 'IQ3_M', 28: 'IQ2_S',
    29: 'IQ2_M', 30: 'IQ4_XS', 31: 'IQ1_M', 32: 'BF16',
    36: 'TQ1_0', 37: 'TQ2_0', 38: 'MXFP4_MOE', 39: 'NVFP4',
    40: 'Q1_0', 41: 'Q2_0',
}


def inspect(path):
    with open(path, 'rb') as stream:
        def read(size):
            if size > 16 * 1024 * 1024 or stream.tell() + size > 64 * 1024 * 1024:
                raise ValueError('metadata inspection limit exceeded')
            value = stream.read(size)
            if len(value) != size:
                raise ValueError('truncated GGUF')
            return value

        def number(fmt):
            return struct.unpack('<' + fmt, read(struct.calcsize(fmt)))[0]

        def string():
            return read(number('Q')).decode('utf-8')

        def value(kind, depth=0):
            if depth > 2:
                raise ValueError('nested metadata limit exceeded')
            formats = {0: 'B', 1: 'b', 2: 'H', 3: 'h', 4: 'I', 5: 'i',
                       6: 'f', 7: '?', 10: 'Q', 11: 'q', 12: 'd'}
            if kind in formats:
                return number(formats[kind])
            if kind == 8:
                return string()
            if kind == 9:
                subtype, count = number('I'), number('Q')
                if count > 1_000_000:
                    raise ValueError('array limit exceeded')
                for _ in range(count):
                    value(subtype, depth + 1)
                return None
            raise ValueError('unknown metadata type')

        if read(4) != b'GGUF' or number('I') not in (2, 3):
            raise ValueError('unsupported GGUF header')
        number('Q')  # tensor count: tensor payloads are never read
        count = number('Q')
        if count > 100_000:
            raise ValueError('metadata entry limit exceeded')
        metadata = {}
        for _ in range(count):
            key = string()
            item = value(number('I'))
            if key in ('general.file_type', 'general.name', 'general.architecture', 'split.count', 'split.no', 'mirai.version') or key.endswith('.context_length') or key.startswith('mirai.'):
                metadata[key] = item
        ftype = metadata.get('general.file_type')
        if ftype is not None and (type(ftype) is not int or ftype < 0):
            raise ValueError('general.file_type must be a nonnegative integer')
        metadata['quantization'] = QUANTIZATIONS.get(ftype, f'Unknown ({ftype})')

        # Detect Mirai GGUF from metadata
        if metadata.get('mirai.version') is not None:
            metadata['format'] = 'mirai_s_gguf'
        # Also detect from tensor names if metadata not present - fall back to filename hints
        elif ftype in (36, 37, 38, 39):
            # TQ1_0, TQ2_0 etc may be Mirai
            pass
        else:
            metadata['format'] = 'gguf'

        return metadata


if __name__ == '__main__':
    try:
        print(json.dumps(inspect(sys.argv[1])))
    except (OSError, ValueError, UnicodeError, struct.error, IndexError) as exc:
        print(f'GGUF metadata unavailable: {exc}', file=sys.stderr)
        sys.exit(1)
