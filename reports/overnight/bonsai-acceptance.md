=== GGUFly Bonsai Real Inference Acceptance Test (Retry) ===
Date: Sun Sep 27 01:43:28 AM CEST 2026
Model: /mnt/Storage/Model/prism-ml/Ternary-Bonsai-2-27B-gguf/Ternary-Bonsai-2-27B-PTQ1_0-MTP-Q8_0-fixed.gguf
Server: /home/ayshinko/AI-Workspace/prism-llama/build-cuda/bin/llama-server

## Preflight Checks
✅ Model exists: 6.0G
✅ Server: version: 0.2.0-dev (build 10706, commit 1a07bfa5f)

## GPU Memory Before
Used: 774 MB / 12282 MB

## Starting Server
PID: 391846
✅ Server fully ready after 8s (HTTP 200)

## GPU Memory After Load
Used: 6581 MB / 12282 MB

## Slot Info
[
    {
        "id": 0,
        "n_ctx": 4096,
        "speculative": false,
        "is_processing": false
    },
    {
        "id": 1,
        "n_ctx": 4096,
        "speculative": false,
        "is_processing": false
    },
    {
        "id": 2,
        "n_ctx": 4096,
        "speculative": false,
        "is_processing": false
    },
    {

## Inference Test
{
    "index": 0,
    "content": "4",
    "tokens": [],
    "id_slot": 3,
    "stop": true,
    "model": "/mnt/Storage/Model/prism-ml/Ternary-Bonsai-2-27B-gguf/Ternary-Bonsai-2-27B-PTQ1_0-MTP-Q8_0-fixed.gguf",
    "tokens_predicted": 2,
    "tokens_evaluated": 29,
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
    "prompt": "<|user|>\nHello! What is 2+2? Answer briefly.<|end|>\n<|assistant|>\n",
    "has_new_line": false,
    "truncated": false,
    "stop_type": "eos",
    "stopping_word": "",
    "tokens_cached": 30,
    "timings": {
        "cache_n": 0,
        "prompt_n": 29,
        "prompt_ms": 355.37,
        "prompt_per_token_ms": 12.254137931034483,
        "prompt_per_second": 81.60508765512002,
        "predicted_n": 2,
        "predicted_ms": 87.113,
        "predicted_per_token_ms": 87.113,
        "predicted_per_second": 11.47934292241112
    }
}

### Content
4

✅ PASS
Tokens/sec: N/A

## Shutdown
Stopped

## GPU Memory After Release
Used: 774 MB / 12282 MB

---
**Bonsai Acceptance Test Complete**
