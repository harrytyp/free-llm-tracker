#!/usr/bin/env python3
"""Fetch OpenRouter's OWN measured latency/throughput per free model.

OpenRouter measures every model endpoint continuously (30-min window) and
exposes it via /api/v1/models/{id}/endpoints. We don't need to benchmark
ourselves — OpenRouter's numbers are more reliable (P50/P75/P90/P99 over
many samples) and cover ALL models, not just a subset.

Methodology:
  - For each free model, GET /api/v1/models/{id}/endpoints
  - Extract throughput_last_30m.p50 (t/s) and latency_last_30m.p50 (ms, TTFT)
  - Verify pricing.prompt == "0" && completion == "0" (it's really free)
  - No own token consumption, no rate-limit risk.

Input:  env OPENROUTER_API_KEY (required)
        data/latest.json (model list)
Output: data/benchmarks.json {model_id: {tps, ttft_s, samples, provider, ...}}
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UA = "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"


def get_json(url: str, key: str) -> dict:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {key}", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("FATAL: OPENROUTER_API_KEY env missing", file=sys.stderr)
        return 1

    # 1. Get all free models from OpenRouter live API
    d = get_json("https://openrouter.ai/api/v1/models", key)
    free_models = []
    for m in d.get("data", []):
        p = m.get("pricing") or {}
        if str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0":
            free_models.append(m["id"])
    print(f"OpenRouter free models: {len(free_models)}")

    # 2. For each, fetch endpoints with measured values
    results = {}
    errors = []
    for i, mid in enumerate(free_models):
        url = f"https://openrouter.ai/api/v1/models/{mid}/endpoints"
        try:
            ep = get_json(url, key)
            data = ep.get("data", ep)
            endpoints = data.get("endpoints", [])
            for e in endpoints:
                pricing = e.get("pricing") or {}
                is_free = str(pricing.get("prompt", "1")) == "0" and str(pricing.get("completion", "1")) == "0"
                tp = e.get("throughput_last_30m") or {}
                lat = e.get("latency_last_30m") or {}
                results[mid] = {
                    "tps": round(tp.get("p50", 0), 2) if tp.get("p50") else None,
                    "tps_p90": round(tp.get("p90", 0), 2) if tp.get("p90") else None,
                    "ttft_ms_p50": round(lat.get("p50", 0), 1) if lat.get("p50") else None,
                    "ttft_ms_p90": round(lat.get("p90", 0), 1) if lat.get("p90") else None,
                    "provider": e.get("provider_name", ""),
                    "uptime_30m": round(e.get("uptime_last_30m", 0), 3) if e.get("uptime_last_30m") else None,
                    "cost_verified_zero": is_free,
                    "context_length": e.get("context_length"),
                    "source": "openrouter-endpoints-api",
                    "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
            print(f"  [{i+1}/{len(free_models)}] {mid}: "
                  f"tps={results.get(mid, {}).get('tps')}, "
                  f"ttft={results.get(mid, {}).get('ttft_ms_p50')}ms")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  429 rate limited at {mid}, pausing 30s...")
                time.sleep(30)
            else:
                errors.append(f"{mid}: {e.code}")
        except Exception as e:
            errors.append(f"{mid}: {e}")
        time.sleep(0.3)  # be gentle

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "openrouter endpoints API (own measured 30-min window, P50)",
        "results": results,
        "errors": errors,
    }
    (DATA / "benchmarks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nOK benchmarks.json: {len(results)} models measured, {len(errors)} errors")
    if errors:
        print("errors:", "; ".join(errors[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
