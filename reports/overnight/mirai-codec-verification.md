# Mirai Codec Type ID Verification

**Date:** 2026-09-27  
**Purpose:** Resolve the discrepancy between assumed (100-103) and actual Mirai GGML type IDs.

## Source of Truth

Repository: [alesha-pro/llama.cpp-mirai-s](https://github.com/alesha-pro/llama.cpp-mirai-s)  
Pinned commit: `b59ae80f419a5415cb950f2a7b2284a500fe74cb`  
File: `ggml/include/ggml.h`

## Actual GGML_TYPE IDs

```
GGML_TYPE_TQ1_0   = 34   // Ternary ternary quantization
GGML_TYPE_TQ2_0   = 35   // Ternary ternary quantization
GGML_TYPE_MS_V4T8 = 90   // Mirai S V4, 8-bit
GGML_TYPE_MS_V2T4 = 91   // Mirai S V2, 4-bit
GGML_TYPE_MS_V2T6 = 92   // Mirai S V2, 6-bit
GGML_TYPE_MS_I3   = 93   // Mirai S int3
```

## LLAMA_FTYPE (general.file_type) IDs

From `include/llama.h`:

```
LLAMA_FTYPE_MOSTLY_TQ1_0 = 36
LLAMA_FTYPE_MOSTLY_TQ2_0 = 37
LLAMA_FTYPE_MOSTLY_Q1_0  = 40
LLAMA_FTYPE_MOSTLY_Q2_0  = 41
```

## Detector Fix Applied

**File:** `bin/ggufly-model-detect.py`

Before (incorrect):
```python
GGML_TYPES = { ..., 36: 'TQ1_0', 37: 'TQ2_0', ... }
MIRAI_GGML_TYPES = { 100: 'MS_V4T8', 101: 'MS_V2T4', 102: 'MS_V2T6', 103: 'MS_I3' }
has_mirai_type check: 100 <= t <= 103
```

After (correct):
```python
GGML_TYPES = { ..., 34: 'TQ1_0', 35: 'TQ2_0', 38: 'MXFP4_MOE', 39: 'NVFP4', 40: 'Q1_0', 41: 'Q2_0', ... }
MIRAI_GGML_TYPES = { 90: 'MS_V4T8', 91: 'MS_V2T4', 92: 'MS_V2T6', 93: 'MS_I3' }
has_mirai_type check: 90 <= t <= 93
```

Note: the `ggufly-gguf-info.py` QUANTIZATIONS dict (for `general.file_type`) was already correct at:
```python
QUANTIZATIONS = { ..., 36: 'TQ1_0', 37: 'TQ2_0', 40: 'Q1_0', 41: 'Q2_0', ... }
```

## Key Distinction

- `ggufly-gguf-info.py` reads `general.file_type` from GGUF metadata → uses LLAMA_FTYPE enum values (36, 37, 40, 41)
- `ggufly-model-detect.py` tensor inspection reads actual GGML_TYPE IDs from tensor headers → uses GGML_TYPE enum values (34, 35, 90-93)
- These are different enum systems! The detector was incorrectly using file_type values where GGML type values were expected.

## Regression Test

An existing test (`test_codec_detection_known` in `test_download.py`) verifies that `general.file_type=40` maps to `'Q1_0'` through the ggufly-model-detect.py pipeline. This continues to pass after the GGML_TYPE correction because that test path goes through get_gguf_info → ggufly-gguf-info.py which was already correct.