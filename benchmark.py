#!/usr/bin/env python3
"""Collect measured t/s + TTFT for free models across ALL measurable providers.

Strategy (per Kolja: "alle Free-Provider, nicht nur OpenRouter"):
  - OpenRouter: endpoints API (own 30-min measurements, P50) — covers OR free models
  - Public OpenAI-compatible providers WITHOUT key (deepinfra, nvidia, novita, sambanova):
    list models, check which are free, measure with 2-3 lightweight streaming calls
  - Key-requiring providers (groq, cerebras, fireworks, together, siliconflow,
    hyperbolic): measured when their key is present in env (OPENROUTER-style envs).
    Each provider is a registry entry — adding a key activates it.

Output: data/benchmarks.json
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UA = "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"

# Provider registry: name -> (base_url, key_env or None, free_model_ids or callable)
# key_env None = public, no key needed. Models listed explicitly (curated from /models).
PROVIDERS = {
    "openrouter": {
        "models_url": "https://openrouter.ai/api/v1/models",
        "key_env": "OPENROUTER_API_KEY",
        "endpoints_api": True,  # use /models/{id}/endpoints for measured values
    },
    "deepinfra": {
        "base_url": "https://api.deepinfra.com/v1/openai",
        "models_url": "https://api.deepinfra.com/v1/openai/models",
        "key_env": None,  # public
        "free_ids": [],  # filled dynamically: deepinfra has free models marked
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "models_url": "https://integrate.api.nvidia.com/v1/models",
        "key_env": None,
        "free_ids": [],
    },
    "novita": {
        "base_url": "https://api.novita.ai/v3/openai",
        "models_url": "https://api.novita.ai/v3/openai/models",
        "key_env": None,
        "free_ids": [],
    },
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "models_url": "https://api.sambanova.ai/v1/models",
        "key_env": None,
        "free_ids": [],
    },
    # Key-gated providers: add key in env to activate
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models_url": "https://api.groq.com/openai/v1/models",
        "key_env": "GROQ_API_KEY",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "models_url": "https://api.cerebras.ai/v1/models",
        "key_env": "CEREBRAS_API_KEY",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "models_url": "https://api.fireworks.ai/inference/v1/models",
        "key_env": "FIREWORKS_API_KEY",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "models_url": "https://api.together.xyz/v1/models",
        "key_env": "TOGETHER_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "models_url": "https://api.siliconflow.cn/v1/models",
        "key_env": "SILICONFLOW_API_KEY",
    },
    "hyperbolic": {
        "base_url": "https://api.hyperbolic.xyz/v1",
        "models_url": "https://api.hyperbolic.xyz/v1/models",
        "key_env": "HYPERBOLIC_API_KEY",
    },
}

# Free models we KNOW are free on keyless providers (from OmniRoute catalog,
# matched to the provider's own /models list). Populated by matching.
PROMPT = "Count from 1 to 30, one number per line."
MIN_SAMPLES = 3
MAX_SAMPLES = 3
PAUSE = 1.0
TIMEOUT = 45
TPS_CAP = 1000


def get_json(url: str, key: str | None = None) -> dict:
    headers = {"User-Agent": UA}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def measure_openrouter(key: str) -> tuple[dict, list[str]]:
    """Free models from OR endpoints API (own 30-min measurements)."""
    results, errors = {}, []
    try:
        d = get_json("https://openrouter.ai/api/v1/models", key)
        free = [m["id"] for m in d.get("data", [])
                if str((m.get("pricing") or {}).get("prompt", "1")) == "0"
                and str((m.get("pricing") or {}).get("completion", "1")) == "0"]
        for mid in free:
            try:
                ep = get_json(f"https://openrouter.ai/api/v1/models/{mid}/endpoints", key)
                data = ep.get("data", ep)
                for e in data.get("endpoints", []):
                    pricing = e.get("pricing") or {}
                    if str(pricing.get("prompt", "1")) != "0":
                        continue
                    tp = e.get("throughput_last_30m") or {}
                    lat = e.get("latency_last_30m") or {}
                    results[mid] = {
                        "tps": round(tp.get("p50", 0), 2) if tp.get("p50") else None,
                        "tps_p90": round(tp.get("p90", 0), 2) if tp.get("p90") else None,
                        "ttft_ms_p50": round(lat.get("p50", 0), 1) if lat.get("p50") else None,
                        "ttft_ms_p90": round(lat.get("p90", 0), 1) if lat.get("p90") else None,
                        "provider": e.get("provider_name", "openrouter"),
                        "uptime_30m": round(e.get("uptime_last_30m", 0), 3) if e.get("uptime_last_30m") else None,
                        "source": "openrouter-endpoints-api",
                        "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    }
                time.sleep(0.2)
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(30)
                errors.append(f"{mid}: {e.code}")
            except Exception as e:
                errors.append(f"{mid}: {e}")
        print(f"  openrouter: {len(results)} measured")
    except Exception as e:
        errors.append(f"openrouter: {e}")
    return results, errors


def measure_stream_provider(name: str, cfg: dict, key: str | None,
                            model_ids: list[str]) -> tuple[dict, list[str]]:
    """Measure via OpenAI-compatible streaming (2-3 samples, median)."""
    results, errors = {}, []
    base = cfg["base_url"]
    for mid in model_ids[:5]:  # budget per provider per run
        samples = []
        for _ in range(MAX_SAMPLES):
            body = json.dumps({
                "model": mid,
                "messages": [{"role": "user", "content": PROMPT}],
                "stream": True,
                "max_tokens": 200,
                "temperature": 0.0,
            }).encode()
            headers = {"Content-Type": "application/json", "User-Agent": UA}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(f"{base}/chat/completions", data=body, headers=headers, method="POST")
            t0 = time.monotonic()
            first_tok = None
            chars = 0
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                    for raw in r:
                        line = raw.decode("utf-8", "replace").strip()
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if choices:
                            delta = choices[0].get("delta") or {}
                            content = delta.get("content")
                            if content:
                                if first_tok is None:
                                    first_tok = time.monotonic()
                                chars += len(content)
                if first_tok and chars >= 8:
                    elapsed = time.monotonic() - first_tok
                    tps = (chars / 4) / elapsed if elapsed > 0 else None
                    if tps and tps <= TPS_CAP:
                        samples.append({
                            "tps": round(tps, 2),
                            "ttft_ms": round((first_tok - t0) * 1000, 1),
                        })
            except Exception:
                pass
            time.sleep(PAUSE)
        if len(samples) >= MIN_SAMPLES:
            results[mid] = {
                "tps": round(statistics.median(s["tps"] for s in samples), 2),
                "ttft_ms_p50": round(statistics.median(s["ttft_ms"] for s in samples), 1),
                "samples": len(samples),
                "provider": name,
                "source": "own-streaming-measurement",
                "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            print(f"    {mid}: {results[mid]['tps']} t/s, {results[mid]['ttft_ms_p50']}ms")
        else:
            errors.append(f"{mid}: insufficient samples")
    return results, errors


def main() -> int:
    all_results: dict = {}
    all_errors: list[str] = []

    # 1. OpenRouter (needs key)
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if or_key:
        r, e = measure_openrouter(or_key)
        all_results.update(r)
        all_errors.extend(e)
    else:
        all_errors.append("openrouter: no key")

    # 2. Public providers (no key): list models, match free from snapshot
    latest = json.loads((DATA / "latest.json").read_text())
    free_by_provider: dict[str, list[str]] = {}
    for m in latest["models"]:
        prov = m.get("provider", "")
        if prov in PROVIDERS and prov not in ("openrouter",):
            free_by_provider.setdefault(prov, []).append(m["id"])

    for name, cfg in PROVIDERS.items():
        if name == "openrouter":
            continue
        key = os.environ.get(cfg.get("key_env", ""), "").strip() if cfg.get("key_env") else None
        if cfg.get("key_env") and not key:
            continue  # key-gated, no key -> skip
        model_ids = free_by_provider.get(name, [])[:8]
        if not model_ids:
            continue
        print(f"  {name}: measuring {len(model_ids)} free models...")
        r, e = measure_stream_provider(name, cfg, key, model_ids)
        all_results.update(r)
        all_errors.extend(e)

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "openrouter endpoints API + own streaming for public providers",
        "results": all_results,
        "errors": all_errors,
    }
    (DATA / "benchmarks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nOK benchmarks.json: {len(all_results)} models measured, {len(all_errors)} errors")
    if all_errors:
        print("errors:", "; ".join(all_errors[:8]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
