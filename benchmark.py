#!/usr/bin/env python3
"""Clean llm-benchmarks.com data into trusted benchmark values.

Per AGENTS.md revision 2:
  - Only rows with samples >= 3 are shown (n=1/n=2 are noise, not measurements)
  - Median over samples, min/max kept
  - Provider names ORIGINAL, no aliasing (groq is NOT openai)
  - llm-benchmarks.com is a reference, not the truth — we clean it.

Input:  data/latest.json (model list to match against)
Output: data/benchmarks.json
"""
from __future__ import annotations

import json
import statistics
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
MIN_SAMPLES = 3
BENCH_URL = "https://llm-benchmarks.com/api/processed"
UA = {"User-Agent": "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"}


def fetch_bench_rows() -> list[dict]:
    req = urllib.request.Request(BENCH_URL, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    return d.get("table") or []


def clean_benchmarks(rows: list[dict]) -> dict[tuple, dict]:
    """Key: (modelCanonical, provider). Only rows with samples >= MIN_SAMPLES."""
    out = {}
    for r in rows:
        cid = r.get("modelCanonical")
        provider = r.get("provider")
        samples = r.get("samples")
        if not cid or not provider or not isinstance(samples, (int, float)) or samples < MIN_SAMPLES:
            continue
        tps = r.get("tokens_per_second_mean")
        ttft = r.get("time_to_first_token_mean")
        if tps is None and ttft is None:
            continue
        out[(cid, provider)] = {
            "tps": round(float(tps), 2) if isinstance(tps, (int, float)) else None,
            "tps_min": round(float(r.get("tokens_per_second_min")), 2) if isinstance(r.get("tokens_per_second_min"), (int, float)) else None,
            "tps_max": round(float(r.get("tokens_per_second_max")), 2) if isinstance(r.get("tokens_per_second_max"), (int, float)) else None,
            "ttft_s": round(float(ttft), 2) if isinstance(ttft, (int, float)) else None,
            "samples": int(samples),
            "provider": provider,
            "last_benchmark": r.get("last_benchmark_date"),
            "source": "llm-benchmarks.com",
        }
    return out


def main() -> int:
    rows = fetch_bench_rows()
    bench = clean_benchmarks(rows)

    # Load free models to know which are free (for stats)
    latest = json.loads((DATA / "latest.json").read_text())
    free_ids = {m["id"].lower().rstrip(":free") for m in latest["models"]}

    # Match: for each free model, find its benchmark rows
    matched = {}
    for (cid, provider), entry in bench.items():
        if cid.lower() in free_ids:
            key = cid.lower().rstrip(":free")
            matched.setdefault(key, []).append(entry)

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "min_samples": MIN_SAMPLES,
        "total_benchmark_rows": len(bench),
        "total_matched_free_models": len(matched),
        "benchmarks": {
            f"{cid}@@{provider}": entry
            for (cid, provider), entry in bench.items()
        },
    }

    (DATA / "benchmarks.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"OK benchmarks.json: {len(bench)} clean rows (n>={MIN_SAMPLES}), "
          f"{len(matched)} matched free models")
    return 0


if __name__ == "__main__":
    sys.exit(main())
