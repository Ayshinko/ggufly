=== GGUFly Mirai S Real Inference Acceptance Test (v2) ===
Date: Sun Sep 27 01:50:36 AM CEST 2026
Model: /mnt/Storage/Model/Mirai/Qwen3.8-27B-S-mirai.gguf
Server: /tmp/mirai-src/build-cuda/bin/llama-server

## Preflight Checks
✅ Model exists: 11G
✅ Server: 0.00.000.528 I srv  llama_server: initializing ... version: 0.5.0-dev (build 1, commit b59ae80) 

## Model Type Detection
{
  "format": "not_found",
  "reason": "Path does not exist: info"
}

## Starting Server
Port: 8175
PID: 399434
✅ Ready after 10s

## GPU Memory After Load
Used: 9807 MB / 12282 MB

## Inference Test
{
    "index": 0,
    "content": "<think>\nThe user is asking a simple arithmetic question and wants a brief answer. 2+2=4.\n</think>\n\n4",
    "tokens": [],
    "id_slot": 3,
    "stop": true,
    "model": "/mnt/Storage/Model/Mirai/Qwen3.8-27B-S-mirai.gguf",
    "tokens_predicted": 28,
    "tokens_evaluated": 20,
    "generation_settings": {
        "seed": 4294967295,
        "temperature": 0.0,
        "dynatemp_range": 0.0,
        "dynatemp_exponent": 1.0,
        "top_k": 20,
        "top_p": 0.949999988079071,
        "min_p": 0.05000000074505806,
        "top_n_sigma": -1.0,
        "xtc_probability": 0.0,
        "xtc_threshold": 0.10000000149011612,
        "typical_p": 1.0,
        "repeat_last_n": 64,
        "repeat_penalty": 1.0,
        "presence_penalty": 0.0,
        "frequency_penalty": 0.0,
        "dry_multiplier": 0.0,
        "dry_base": 1.75,
        "dry_allowed_length": 2,
        "dry_penalty_last_n": 64,
        "dry_sequence_breakers": [
            "\n",
            ":",
            "\"",
            "*"
        ],
        "mirostat": 0,
        "mirostat_tau": 5.0,
        "mirostat_eta": 0.10000000149011612,
        "adaptive_target": -1.0,
        "adaptive_decay": 0.8999999761581421,
        "stop": [],
        "max_tokens": 50,
        "n_predict": 50,
        "n_keep": 0,
        "n_discard": 0,
        "ignore_eos": false,
        "stream": false,
        "logit_bias": [],
        "n_probs": 0,
        "min_keep": 0,
        "grammar": "",
        "grammar_lazy": false,
        "grammar_triggers": [],
        "preserved_tokens": [],
        "chat_format": "Content-only",
        "reasoning_format": "deepseek",
        "reasoning_in_content": false,
        "generation_prompt": "",
        "samplers": [
            "penalties",
            "dry",
            "top_n_sigma",
            "top_k",
            "typ_p",
            "top_p",
            "min_p",
            "xtc",
            "temperature"
        ],
        "speculative.types": "none",
        "timings_per_token": false,
        "post_sampling_probs": false,
        "backend_sampling": false,
        "lora": []
    },
    "prompt": "<|im_start|>user\nHello! What is 2+2? Answer briefly.<|im_end|>\n<|im_start|>assistant\n",
    "has_new_line": true,
    "truncated": false,
    "stop_type": "eos",
    "stopping_word": "",
    "tokens_cached": 47,
    "timings": {
        "cache_n": 0,
        "prompt_n": 20,
        "prompt_ms": 125.829,
        "prompt_per_token_ms": 6.291449999999999,
        "prompt_per_second": 158.94587098363652,
        "predicted_n": 28,
        "predicted_ms": 1024.726,
        "predicted_per_token_ms": 37.95281481481482,
        "predicted_per_second": 26.348506820359784
    }
}

### Content
<think>
The user is asking a simple arithmetic question and wants a brief answer. 2+2=4.
</think>

4

✅ PASS

## Timing
Prompt: 158.9 t/s
Generation: 26.3 t/s

## Shutdown
Stopped

## GPU Memory After Release
Used: 774 MB / 12282 MB

---
**Mirai S Acceptance Test Complete**
