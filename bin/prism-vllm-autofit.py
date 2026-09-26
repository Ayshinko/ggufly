#!/usr/bin/env python3
"""
prism-vllm-autofit.py — PMM vLLM Auto-Fit VRAM helper.

Queries GPU state, calculates a safe KV cache allocation, and manages
a persistent cache of successful profiles for faster subsequent loads.

Usage:
    prism-vllm-autofit.py gpu-info
        → JSON: {"total_mib": 12282, "used_mib": 2841, "free_mib": 9441}

    prism-vllm-autofit.py calc-kv <free_mib> <safe_reserve_mib> <model_id> [<cached_kv_bytes>]
        → JSON: {"kv_cache_bytes": 8589934592, "from_cache": false, "retry_step_mib": 256}

    prism-vllm-autofit.py cache-get <profile_key>
        → JSON: {"kv_cache_bytes": 8589934592, "max_model_len": 24576, "gpu_total_mib": 12282}

    prism-vllm-autofit.py cache-set <profile_key> <kv_cache_bytes> <max_model_len> <gpu_total_mib>
        → exit 0 on success

    prism-vllm-autofit.py cache-invalidate
        → removes cache entries whose recorded gpu_total_mib differs from current total
"""

import json
import os
import subprocess
import sys
import hashlib


# ── nvidia-smi query ───────────────────────────────────────────────────

def get_gpu_info():
    """Query nvidia-smi for GPU memory info. Returns dict with total/used/free in MiB."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total,memory.used,memory.free,name",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return {"error": f"nvidia-smi failed: {result.stderr.strip()}"}

        line = result.stdout.strip().split("\n")[0]
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            return {"error": f"unexpected nvidia-smi output: {line}"}

        total_mib = int(parts[0])
        used_mib = int(parts[1])
        free_mib = int(parts[2])
        gpu_name = parts[3]

        return {
            "total_mib": total_mib,
            "used_mib": used_mib,
            "free_mib": free_mib,
            "gpu_name": gpu_name,
        }
    except FileNotFoundError:
        return {"error": "nvidia-smi not found"}
    except subprocess.TimeoutExpired:
        return {"error": "nvidia-smi timed out"}
    except (ValueError, IndexError) as e:
        return {"error": f"parse error: {e}"}


# ── KV cache calculation ───────────────────────────────────────────────

def calc_kv_cache_bytes(free_mib, safe_reserve_mib, cached_kv_bytes=None):
    """
    Calculate KV cache bytes based on free VRAM and safety reserve.

    free_mib: current free VRAM in MiB
    safe_reserve_mib: VRAM to reserve for desktop/driver in MiB
    cached_kv_bytes: optional previous successful value (starting point)

    Returns dict with kv_cache_bytes, from_cache flag, and retry_step_mib.
    """
    # Ensure reserve is at least 256 MiB
    safe_reserve_mib = max(safe_reserve_mib, 256)

    if cached_kv_bytes is not None and cached_kv_bytes > 0:
        # Start from cached value, but cap at current free - reserve
        max_possible = max(0, free_mib - safe_reserve_mib)
        kv_mib = min(cached_kv_bytes / (1024 * 1024), max_possible)
        from_cache = True
    else:
        # No cache: use most of free VRAM minus reserve
        kv_mib = max(0, free_mib - safe_reserve_mib)
        from_cache = False

    # Convert MiB to bytes
    kv_bytes = int(kv_mib * 1024 * 1024)

    # Align to 256 MiB boundary for cleanliness
    align_bytes = 256 * 1024 * 1024
    kv_bytes = (kv_bytes // align_bytes) * align_bytes

    # Never go below 256 MiB
    kv_bytes = max(kv_bytes, 256 * 1024 * 1024)

    return {
        "kv_cache_bytes": kv_bytes,
        "from_cache": from_cache,
        "retry_step_mib": 256,
        "free_mib_used": kv_mib,
        "safe_reserve_mib": safe_reserve_mib,
    }


# ── Auto-Fit profile cache ─────────────────────────────────────────────

def _cache_path():
    """Return the path to the cache file from PMM state dir or env."""
    env_path = os.environ.get("VLLM_AUTO_FIT_CACHE")
    if env_path:
        return env_path
    state_dir = os.environ.get(
        "XDG_STATE_HOME",
        os.path.expanduser("~/.local/state/prism-model-manager"),
    )
    return os.path.join(state_dir, "vllm-autofit-cache.json")


def _read_cache():
    """Read the full cache dict."""
    path = _cache_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write_cache(data):
    """Write the full cache dict atomically."""
    path = _cache_path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def _profile_key(model_identity, backend, plugin, mtp_state, kv_cache_dtype, gpu_name):
    """Build a deterministic cache key from load parameters."""
    raw = f"{model_identity}|{backend}|{plugin}|{mtp_state}|{kv_cache_dtype}|{gpu_name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cache_get(model_identity, backend, plugin, mtp_state, kv_cache_dtype, gpu_name):
    """Look up a cached Auto-Fit profile. Returns dict or None."""
    cache = _read_cache()
    key = _profile_key(model_identity, backend, plugin, mtp_state, kv_cache_dtype, gpu_name)
    entry = cache.get(key)
    if entry is None:
        return None
    # Sanity: if total VRAM changed (e.g. GPU swap), invalidate
    gpu_info = get_gpu_info()
    if "error" not in gpu_info and entry.get("gpu_total_mib"):
        if abs(entry["gpu_total_mib"] - gpu_info["total_mib"]) > 64:
            return None  # GPU changed
    return entry


def cache_set(model_identity, backend, plugin, mtp_state, kv_cache_dtype,
              gpu_name, kv_cache_bytes, max_model_len, gpu_total_mib):
    """Store a successful Auto-Fit profile."""
    cache = _read_cache()
    key = _profile_key(model_identity, backend, plugin, mtp_state, kv_cache_dtype, gpu_name)
    cache[key] = {
        "kv_cache_bytes": kv_cache_bytes,
        "max_model_len": max_model_len,
        "gpu_total_mib": gpu_total_mib,
    }
    _write_cache(cache)
    return True


def cache_invalidate():
    """Remove cache entries for which the GPU total VRAM no longer matches."""
    cache = _read_cache()
    gpu_info = get_gpu_info()
    if "error" in gpu_info:
        return {"removed": 0, "error": gpu_info["error"]}

    current_total = gpu_info["total_mib"]
    before = len(cache)
    cache = {
        k: v
        for k, v in cache.items()
        if abs(v.get("gpu_total_mib", 0) - current_total) <= 64
    }
    after = len(cache)
    _write_cache(cache)
    return {"removed": before - after, "remaining": after}


# ── CLI dispatcher ────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]

    if command == "gpu-info":
        info = get_gpu_info()
        print(json.dumps(info))
        sys.exit(0 if "error" not in info else 1)

    elif command == "calc-kv":
        # Usage: calc-kv <free_mib> <safe_reserve_mib> <model_id> [cached_kv_bytes]
        if len(sys.argv) < 5:
            print("Usage: calc-kv <free_mib> <safe_reserve_mib> <model_id> [cached_kv_bytes]",
                  file=sys.stderr)
            sys.exit(1)
        free_mib = int(sys.argv[2])
        safe_reserve_mib = int(sys.argv[3])
        model_id = sys.argv[4]
        cached_kv_bytes = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] else None
        result = calc_kv_cache_bytes(free_mib, safe_reserve_mib, cached_kv_bytes)
        print(json.dumps(result))
        sys.exit(0)

    elif command == "cache-get":
        # Usage: cache-get <model_identity> <backend> <plugin> <mtp_state> <kv_cache_dtype> <gpu_name>
        if len(sys.argv) < 8:
            print("Usage: cache-get <model_id> <backend> <plugin> <mtp> <kv_dtype> <gpu_name>",
                  file=sys.stderr)
            sys.exit(1)
        entry = cache_get(sys.argv[2], sys.argv[3], sys.argv[4],
                          sys.argv[5], sys.argv[6], sys.argv[7])
        if entry:
            print(json.dumps(entry))
            sys.exit(0)
        else:
            print("null")
            sys.exit(0)

    elif command == "cache-set":
        # Usage: cache-set <model_id> <backend> <plugin> <mtp> <kv_dtype> <gpu_name>
        #         <kv_cache_bytes> <max_model_len> <gpu_total_mib>
        if len(sys.argv) < 10:
            print("Usage: cache-set <model_id> <backend> <plugin> <mtp> <kv_dtype> <gpu_name>"
                  " <kv_bytes> <max_model_len> <gpu_total_mib>",
                  file=sys.stderr)
            sys.exit(1)
        cache_set(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
                  sys.argv[6], sys.argv[7], int(sys.argv[8]),
                  int(sys.argv[9]), int(sys.argv[10]))
        sys.exit(0)

    elif command == "cache-invalidate":
        result = cache_invalidate()
        print(json.dumps(result))
        sys.exit(0)

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()