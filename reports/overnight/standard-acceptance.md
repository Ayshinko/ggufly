# Standard GGUF Acceptance

**Date:** 2026-09-27

## Model
- Path: `/mnt/Storage/Model/openbmb/MiniCPM5-2B-GGUF/MiniCPM5-2B-Q8_0.gguf`
- Size: 2.5 GB
- Architecture: MiniCPM5 (2B params)
- Quantization: Q8_0

## Runtime
- Binary: `/usr/bin/llama-server`
- Version: 0.4.0-dev (build 10809, commit 5266f24da7)
- Source: System/Arch Linux package

## Configuration
- Context: 2048
- GPU layers: 99
- Flash Attention: on
- Cache K/V: q8_0
- Batch: 1024
- UBatch: 256
- Temperature: 0
- Slots: 1

## Results
- Startup time: 4s
- /health: OK
- /v1/models: Returns model ID
- Prompt tokens: 20
- Generated tokens: 40
- Response: "GGUFLY STANDARD OK" (exact expected)
- VRAM during inference: 3302 MB
- VRAM after stop: 741 MB (clean release)

## API
- GET /health — ✓ OK
- GET /v1/models — ✓ Returns model list
- POST /v1/chat/completions — ✓ Returns completion

**Result: PASS**
