# GGUFly — Hugging Face Promotion Guide

**Project:** GGUFly  
**Repository:** [https://github.com/Ayshinko/ggufly](https://github.com/Ayshinko/ggufly)  
**Version:** 1.0.0-dev  
**Status:** Promotion copy — NOT yet published to any HF model card.

---

## Overview

GGUFly is a Linux TUI for managing GGUF models and llama.cpp-compatible runtimes. This document provides ready-to-use promotional text for Hugging Face model cards, organized by model category.

---

## Generic GGUF Model Card Section

Paste the following into any GGUF model card's "Usage" section:

### Run with GGUFly

[GGUFly](https://github.com/Ayshinko/ggufly) is a Linux terminal UI for managing GGUF models and llama.cpp runtimes.

```bash
# Install
git clone https://github.com/Ayshinko/ggufly.git
cd ggufly
./install.sh

# Launch
ggufly
```

Features:
- Discover GGUF models, scan codec/architecture metadata
- Select and configure runtime fork (Standard, PrismML/Bonsai, Mirai S, or any external llama.cpp build)
- Per-model profile persistence (context, GPU layers, KV cache, MTP, etc.)
- Capability auto-detection from actual llama-server binary
- Server lifecycle (start/stop/switch/health/logs)
- OpenAI-compatible API endpoint
- GPU/VRAM monitoring, chat test, benchmark

**Status:** Compatible with GGUFly.  
*(Replace with "Tested with GGUFly" only if you have personally verified the combination.)*

---

## Bonsai / PTQ1_0 / PQ2_0 Model Card Section

### Run with GGUFly + PrismML/Bonsai Runtime

For Bonsai PTQ1_0 and PQ2_0 ternary quantized models, use the PrismML/Bonsai llama.cpp runtime fork.

1. Install GGUFly
2. Launch GGUFly, go to Settings → Runtime fork → PrismML / Bonsai
3. Select your Bonsai GGUF model
4. Configure settings (recommended: NGL=99, FLASH=on, CTX=40960, BATCH=2048, UBATCH=512)
5. Start the server

**Tested combinations:**

| Model | Runtime | MTP | Context | Result |
|-------|---------|-----|---------|--------|
| Ternary-Bonsai-2-27B-PTQ1_0-MTP-Q8_0 | PrismML/Bonsai | Off | 40960 | Verified |
| Ternary-Bonsai-2-27B-PTQ1_0-MTP-Q8_0 | PrismML/Bonsai | On (draft-mtp, n_max=2) | 40960 | Verified |

---

## Swift Bonsai 2 27B Katana Model Card Section

### Run with GGUFly

Compatible with GGUFly using the PrismML/Bonsai runtime fork.

```bash
ggufly
# Settings -> Runtime fork -> PrismML / Bonsai
# Select Swift-Bonsai-2-27B-Katana-MTP-GGUF model
# Start
```

**Recommended settings (RTX 4070 SUPER 12 GB):**
- GPU layers: 99
- Flash Attention: on
- Context: 40960
- Batch: 2048
- UBatch: 512
- MTP: on (draft-mtp, n_max=2)

---

## Mirai S Model Card Section

### Run with GGUFly + Mirai S Runtime

For Mirai S compressed-weight models, use the Mirai S llama.cpp fork.

1. Install GGUFly
2. Build/obtain the Mirai S `llama-server` binary
3. In GGUFly, go to Settings → Runtime fork → Add runtime folder...
4. Point to the directory containing the Mirai S llama-server
5. Select your Mirai S GGUF model
6. Start

**Recommended settings (RTX 4070 SUPER 12 GB):**
- GPU layers: 99
- Flash Attention: on
- Context: 73728
- KV K/V: q8_0
- MTP: off (VRAM-limited)

---

## Wording Guide

When adding "Run with GGUFly" sections to model cards:

| Wording | When to use |
|---------|-------------|
| "Compatible with GGUFly" | Any GGUF model that works with a standard llama-server. Safe default. |
| "Tested with GGUFly" | Only if you have personally launched this exact model file through GGUFly and verified inference works. |
| "Recommended by GGUFly" | Do not use. GGUFly does not recommend models. |

---

## Badge

```markdown
[![GGUFly](https://img.shields.io/badge/GGUFly-Manage_Your_GGUFs-72af9d?logo=linux)](https://github.com/Ayshinko/ggufly)
```

---

## DO NOT

- Claim GGUFly "supports" a model you have not personally tested
- Use "Prism Model Manager" or "PMM" in new promotional text
- Reference old repository URLs (Ayshinko/prism-model-manager)
- Claim GGUFly is affiliated with PrismML, Mirai Labs, or any model publisher

---

*Prepared 2026-09-27. Not yet published to any Hugging Face repository.*