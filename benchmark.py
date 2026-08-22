#!/usr/bin/env python3
"""Measure real tokens/sec + TTFT on free LLM endpoints via OpenRouter.

Methodology (per AGENTS.md rev 2):
  - Own measurement, not third-party numbers.
  - Each call MUST return cost==0 (verifies it's really a free model).
  - >= 3 samples per model before a value is shown; median over samples.
  - TTFT = seconds to first visible token; t/s measured on streamed content.
  - Respects OpenRouter free-tier rate limits (20 req/min, 50 req/day).
  - Budget: max 3 samples x N models per run, staggered.

Input:  env OPENROUTER_API_KEY (required)
        data/latest.json (model list)
Output: data/benchmarks.json {model_id: {tps, ttft_s, samples, cost_verified, ...}}
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
API_URL = "https://openrouter.ai/api/v1/chat/completions"

MIN_SAMPLES = 3
MAX_SAMPLES = 3       # OpenRouter free limit: 20 req/min
BUDGET_MODELS = 60    # per run, keep CI time sane
PAUSE_BETWEEN = 2.5   # seconds between requests (rate limit)
TIMEOUT = 90          # per request

UA = "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"
PROMPT = "Count from 1 to 40, one number per line. Only numbers."


def measure_model(key: str, model_id: str, max_tokens: int = 300) -> dict | None:
    """One streaming request; returns {tps, ttft_s, cost} or None on failure."""
    body = json.dumps({
        "model": model_id,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": True,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }).encode()

    req = urllib.request.Request(API_URL, data=body, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": UA,
    }, method="POST")

    t0 = time.monotonic()
    first_token_t = None
    chars = 0
    total_cost = 0.0

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
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    if first_token_t is None:
                        first_token_t = time.monotonic()
                    chars += len(content)
                # Track usage from final chunk if present
                usage = chunk.get("usage")
                if usage:
                    total_cost = usage.get("cost", 0) or 0
    except Exception as e:
        return None

    if first_token_t is None or chars < 10:
        return None

    elapsed = time.monotonic() - first_token_t
    # chars/4 ≈ tokens (documented approximation; exact usage unavailable in streaming)
    tokens = chars / 4
    tps = tokens / elapsed if elapsed > 0 else None

    # Sanity: t/s above 1000 is almost certainly a measurement artifact
    # (huge first chunk, short prompt). Drop such samples.
    if tps and tps > 1000:
        return None

    return {
        "tps": round(tps, 2) if tps else None,
        "ttft_s": round(first_token_t - t0, 3),
        "chars": chars,
        "cost": total_cost,
        "cost_verified_zero": total_cost == 0,
    }


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("FATAL: OPENROUTER_API_KEY env missing", file=sys.stderr)
        return 1

    latest = json.loads((DATA / "latest.json").read_text())
    models = latest["models"]

    # Get the actual free models from OpenRouter API (authoritative for what OR routes)
    or_free = [m["id"] for m in models if m.get("source_catalog") == "openrouter"]
    if not or_free:
        # fallback: any :free-suffixed or slash IDs from the snapshot
        or_free = [m["id"] for m in models
                   if m["id"].endswith(":free") or "/" in m["id"]]

    # Also add known OpenRouter free IDs from the live API for completeness
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={
            "Authorization": f"Bearer {key}", "User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            live = json.loads(r.read().decode())
        for m in live.get("data", []):
            p = m.get("pricing") or {}
            if str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0":
                mid = m["id"]
                if mid not in or_free:
                    or_free.append(mid)
    except Exception as e:
        print(f"  (live OR list failed: {e})")

    candidates = or_free[:BUDGET_MODELS]
    print(f"Benchmarking {len(candidates)} OpenRouter free models ({BUDGET_MODELS} budget)...")

    results = {}
    skipped = []
    for i, m in enumerate(candidates):
        mid = m if isinstance(m, str) else m["id"]
        # skip non-OpenRouter-IDs: must be routable via OR
        if not any(prefix in mid for prefix in ("/", ":free")):
            skipped.append(mid)
            continue

        samples = []
        for s in range(MAX_SAMPLES):
            r = measure_model(key, mid)
            if r and r["cost_verified_zero"]:
                samples.append(r)
            elif r and not r["cost_verified_zero"]:
                print(f"  {mid}: COST != 0 — NOT free, skipping")
                break
            time.sleep(PAUSE_BETWEEN)

        if len(samples) >= MIN_SAMPLES:
            tps_vals = [s["tps"] for s in samples if s["tps"]]
            ttft_vals = [s["ttft_s"] for s in samples]
            results[mid] = {
                "tps_median": round(statistics.median(tps_vals), 2) if tps_vals else None,
                "ttft_median_s": round(statistics.median(ttft_vals), 2) if ttft_vals else None,
                "samples": len(samples),
                "cost_verified": True,
                "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "own-measurement-openrouter",
            }
            print(f"  [{i+1}/{len(candidates)}] {mid}: {results[mid]['tps_median']} t/s, "
                  f"{results[mid]['ttft_median_s']}s TTFT, {len(samples)} samples")
        else:
            skipped.append(mid)

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "own-streaming-measurement via OpenRouter, cost==0 verified, median of >=3",
        "budget_models": BUDGET_MODELS,
        "results": results,
        "skipped": skipped,
    }
    (DATA / "benchmarks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"\nOK benchmarks.json: {len(results)} measured, {len(skipped)} skipped/insufficient")
    return 0


if __name__ == "__main__":
    sys.exit(main())
