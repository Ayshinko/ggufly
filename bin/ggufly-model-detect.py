#!/usr/bin/env python3
"""GGUFly model format detection helper — GGUF-focused edition.

Detects model format, architecture, codec, and compatibility.
Output is JSON for consumption by the GGUFly shell script.

Accepts a path argument (file). Returns:
  format: 'gguf' | 'gguf_shard' | 'mirai_s_gguf' | 'unknown'
  name: human-readable model name
  architecture: model architecture string
  parameters_b: estimated parameter count in billions
  codec: quantization/codec format
  context_length: maximum context length if known
  file_count: number of relevant weight files
  total_size_mib: total size of weight files in MiB
  reason: explanation string
"""
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path


# Extended GGML type to codec name mapping including Mirai types
GGML_TYPES = {
    0: 'F32', 1: 'F16', 2: 'Q4_0', 3: 'Q4_1', 4: 'Q4_2', 5: 'Q4_3',
    6: 'Q5_0', 7: 'Q8_0', 8: 'Q5_0', 9: 'Q5_1',
    10: 'Q2_K', 11: 'Q3_K_S', 12: 'Q3_K_M', 13: 'Q3_K_L',
    14: 'Q4_K_S', 15: 'Q4_K_M', 16: 'Q5_K_S', 17: 'Q5_K_M', 18: 'Q6_K',
    19: 'IQ2_XXS', 20: 'IQ2_XS', 21: 'Q2_K_S', 22: 'IQ3_XS', 23: 'IQ3_XXS',
    24: 'IQ1_S', 25: 'IQ4_NL', 26: 'IQ3_S', 27: 'IQ3_M', 28: 'IQ2_S',
    29: 'IQ2_M', 30: 'IQ4_XS', 31: 'IQ1_M', 32: 'BF16',
    # Extended/custom types
    # Note: GGML type IDs (tensor level) differ from llama_ftype (file level).
    # These are GGML type IDs (from ggml.h):
    #   TQ1_0 = 34, TQ2_0 = 35 (ternary in Mirai fork)
    #   MS_V4T8 = 90, MS_V2T4 = 91, MS_V2T6 = 92, MS_I3 = 93 (Mirai S)
    34: 'TQ1_0', 35: 'TQ2_0',
    38: 'MXFP4_MOE', 39: 'NVFP4',
    40: 'Q1_0', 41: 'Q2_0',
}

# Mirai-specific GGML types (custom type enum from alesha-pro/llama.cpp-mirai-s)
# Source: ggml/include/ggml.h lines 434-438, commit b59ae80
#   GGML_TYPE_MS_V4T8 = 90
#   GGML_TYPE_MS_V2T4 = 91
#   GGML_TYPE_MS_V2T6 = 92
#   GGML_TYPE_MS_I3   = 93
MIRAI_GGML_TYPES = {
    90: 'MS_V4T8',
    91: 'MS_V2T4',
    92: 'MS_V2T6',
    93: 'MS_I3',
}


def get_gguf_info(path):
    """Read GGUF metadata (delegates to ggufly-gguf-info.py)."""
    script_dir = Path(__file__).resolve().parent
    gguf_info = script_dir / 'ggufly-gguf-info.py'

    if not gguf_info.exists():
        gguf_info = Path(os.environ.get('GGUFLY_BIN_DIR', '')) / 'ggufly-gguf-info.py'

    if not gguf_info.exists():
        gguf_info = Path(os.environ.get('PMM_BIN_DIR', '')) / 'prism-gguf-info.py'

    if not gguf_info.exists():
        return None

    try:
        result = subprocess.run(
            [sys.executable, str(gguf_info), path],
            capture_output=True, text=True, timeout=15)
        if result.returncode == 0:
            return json.loads(result.stdout)
        return None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None


def inspect_gguf_tensors(path):
    """Inspect GGUF tensor metadata to detect Mirai-specific types.

    Reads only the tensor info metadata block (not raw tensor data).
    """
    try:
        with open(path, 'rb') as stream:
            def read(size):
                if size > 16 * 1024 * 1024 or stream.tell() + size > 64 * 1024 * 1024:
                    return b''
                return stream.read(size)

            def number(fmt):
                return struct.unpack('<' + fmt, read(struct.calcsize(fmt)))[0]

            def string():
                return read(number('Q')).decode('utf-8', errors='replace')

            header = read(4)
            if header != b'GGUF':
                return None
            version = number('I')
            if version not in (2, 3):
                return None

            tensor_count = number('Q')
            metadata_count = number('Q')

            # Skip metadata kv pairs
            for _ in range(metadata_count):
                _ = string()  # key
                kind = number('I')
                sub_kind = 0
                if kind == 8:  # string
                    _ = string()
                elif kind in (0, 1, 2, 3, 4, 5, 6, 7, 10, 11, 12):
                    _ = read(struct.calcsize('<Q'))  # skip single value
                elif kind == 9:  # array
                    sub_kind = number('I')
                    count_arr = number('Q')
                    if sub_kind == 8:
                        for _ in range(min(count_arr, 100)):
                            _ = string()
                    else:
                        _ = read(struct.calcsize('<Q') * min(count_arr, 100))
                else:
                    break

            if tensor_count > 10000 or tensor_count <= 0:
                return None

            # Read tensor info to detect Mirai-specific types
            tensors = []
            mirai_tensors = []
            unique_types = set()
            for _ in range(min(tensor_count, 500)):
                name = string()
                n_dims = number('I')
                _ = number('Q') * n_dims  # skip dimensions
                ggml_type = number('I')

                unique_types.add(ggml_type)
                tensors.append({'name': name, 'type': ggml_type})

                # Detect Mirai-specific tensors (GGML type IDs 90-93 in Mirai fork)
                if ggml_type >= 90:
                    mirai_tensors.append(name)
                if name.startswith('mirai.'):
                    mirai_tensors.append(name)
                if 'rot' in name or 'head_aux' in name or 'codebook' in name:
                    if ggml_type >= 90 or ggml_type > 41:
                        mirai_tensors.append(name)

            return {
                'tensor_count': min(tensor_count, 500),
                'unique_types': [GGML_TYPES.get(t, MIRAI_GGML_TYPES.get(t, f'custom_{t}')) for t in sorted(unique_types)],
                'mirai_tensors': list(set(mirai_tensors)),
                'has_mirai_type': any(90 <= t <= 93 for t in unique_types),
            }
    except Exception:
        return None


def detect_codec_from_types(unique_types_str, info, tensors_info):
    """Determine the codec from GGUF type information."""
    unique_types = set()

    # Parse from tensor inspection
    if tensors_info:
        for t in tensors_info.get('unique_types', []):
            unique_types.add(t)
        if tensors_info.get('has_mirai_type'):
            return 'Mirai S'

    # Check metadata for Mirai version
    if info:
        mirai_version = info.get('mirai.version')
        if mirai_version is not None:
            return f'Mirai S'

    # Check for Mirai-specific tensor names
    if tensors_info and tensors_info.get('mirai_tensors'):
        mirai_names = tensors_info['mirai_tensors']
        if any('codebook' in n or 'mirai' in n for n in mirai_names):
            return 'Mirai S'

    # Check file_type for Prism/Bonsai codecs (140-179 range)
    if info:
        file_type = info.get('general.file_type')
        if file_type is not None:
            bonsai_map = {
                140: 'PTQ1_0', 141: 'PQ2_0', 142: 'TQ1_0', 143: 'PTQ1_0',
                144: 'PQ2_0', 145: 'TQ2_0', 146: 'PTQ1_0', 147: 'PQ2_0',
            }
            if file_type in bonsai_map:
                return bonsai_map[file_type]

    # Standard quantization detection from metadata
    if info:
        quant = info.get('quantization', 'Unknown')
        if quant != 'Unknown' and quant != 'Unknown (None)':
            return quant

    # Fallback: filename hints for known special codecs
    return 'Unknown'


def detect_gguf(path):
    """Detect and describe a GGUF model."""
    info = get_gguf_info(path)
    tensors_info = inspect_gguf_tensors(path)

    name = info.get('general.name', os.path.basename(path)) if info else os.path.basename(path)
    arch = info.get('general.architecture', 'unknown') if info else 'unknown'
    ctx = info.get(f'{arch}.context_length', 0) if info and arch != 'unknown' else 0

    # Detect format
    fmt = 'gguf'
    if info and info.get('format') == 'mirai_s_gguf':
        fmt = 'mirai_s_gguf'
    if tensors_info and tensors_info.get('has_mirai_type'):
        fmt = 'mirai_s_gguf'

    # Determine codec
    codec = detect_codec_from_types(None, info, tensors_info)

    # Estimate parameter count from file size
    size_mib = os.path.getsize(path) / (1024 * 1024)
    params_b = round(size_mib / 500, 1) if size_mib > 0 else 0

    # Context
    format_str = fmt
    reason = f'GGUF: {arch}, {codec}'
    if fmt == 'mirai_s_gguf':
        format_str = 'Mirai S GGUF'
        reason = f'Mirai GGUF: {arch}, {codec}'

    return {
        'format': format_str,
        'name': name,
        'architecture': arch,
        'parameters_b': params_b,
        'codec': codec,
        'context_length': ctx,
        'file_count': 1,
        'file_sizes_mib': [round(size_mib, 1)],
        'total_size_mib': round(size_mib, 1),
        'gguf_info': info,
        'tensor_info': {
            'count': tensors_info['tensor_count'] if tensors_info else 0,
            'types': tensors_info['unique_types'] if tensors_info else [],
            'has_mirai_types': tensors_info['has_mirai_type'] if tensors_info else False,
        } if tensors_info else None,
        'reason': reason,
    }


def detect_gguf_shard(path):
    """Detect and describe a sharded GGUF model (first shard)."""
    result = detect_gguf(path)
    if result:
        result['format'] = 'gguf_shard'
    return result


def detect_file(path_str):
    """Detect model format from the given file path."""
    path = Path(path_str)

    if not path.exists():
        return {'format': 'not_found', 'reason': f'Path does not exist: {path}'}

    # Check for GGUF file
    if path.is_file() and path.suffix.lower() == '.gguf':
        result = detect_gguf(str(path))
        if result:
            return result
        return {'format': 'gguf', 'codec': 'Unknown', 'reason': 'GGUF file detected but metadata unreadable'}

    # Check for GGUF shard
    if path.is_file():
        m = re.match(r'(.+)-(\d{5})-of-(\d{5})\.gguf$', path.name, re.IGNORECASE)
        if m:
            result = detect_gguf(str(path))
            if result:
                result['format'] = 'gguf_shard'
                return result
            return {'format': 'gguf_shard', 'reason': f'GGUF shard: {m.group(2)} of {m.group(3)}'}

    if path.is_file():
        ext = path.suffix.lower()
        return {'format': 'unknown_file', 'reason': f'Unrecognized file: {ext}'}

    if path.is_dir():
        gguf_files = list(path.glob('*.gguf'))
        if gguf_files:
            result = detect_gguf(str(gguf_files[0]))
            if result:
                result['file_count'] = len(gguf_files)
                return result
            return {'format': 'gguf_dir', 'reason': f'Directory with {len(gguf_files)} GGUF file(s)'}
        return {'format': 'unknown_dir', 'reason': 'No GGUF files in directory'}

    return {'format': 'unknown', 'reason': 'Could not determine model format'}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: ggufly-model-detect.py <path>'}), file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    result = detect_file(path)
    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == '__main__':
    main()