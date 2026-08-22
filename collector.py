#!/usr/bin/env python3
"""Collect free-LLM data from OpenRouter, llm-benchmarks.com and Artificial Analysis.

Writes:
  data/latest.json   - current snapshot (models + sources + meta)
  data/history.jsonl - one line per successful run (append), pruned to 90 days

Design goals:
- Never crash on a single source failing: each fetch is independent.
- Zero token cost: only public catalog/benchmark endpoints are queried.
- AA key optional (env ARTIFICIAL_ANALYSIS_API_KEY): adds intelligence index.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HISTORY_MAX_DAYS = 90
HISTORY_KEEP_RUNS = 2000

UA = {"User-Agent": "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"}


def http_get_json(url: str, headers: dict | None = None, timeout: int = 30):
    h = dict(UA)
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def fetch_openrouter() -> list[dict]:
    """All models with prompt==0 AND completion==0 pricing => free."""
    d = http_get_json("https://openrouter.ai/api/v1/models")
    out = []
    for m in d.get("data", []):
        p = m.get("pricing") or {}
        try:
            is_free = str(p.get("prompt", "1")) == "0" and str(p.get("completion", "1")) == "0"
        except Exception:
            is_free = False
        if not is_free:
            continue
        # skip non-text models (image/audio) when detectable
        modality = (m.get("architecture") or {}).get("modality", "")
        if modality and "text" not in modality.split("->")[0]:
            continue
        out.append({
            "id": m["id"],
            "name": m.get("name", m["id"]),
            "context_length": m.get("context_length"),
            "created": m.get("created"),
            "description": (m.get("description") or "")[:280],
            "supported_parameters": m.get("supported_parameters", []),
            "modality": modality,
        })
    return out


_OMNIRoute_CATALOG_URL = (
    "https://raw.githubusercontent.com/diegosouzapw/OmniRoute/main/"
    "open-sse/config/freeModelCatalog.data.ts"
)


def fetch_omnitroute_free() -> list[dict]:
    """Parse OmniRoute's curated free-model catalog (523 records).

    Source of truth for WHAT is free across providers — kept manually
    researched in-repo at diegosouzapw/OmniRoute (2026-07-20 snapshot).
    Returns records with provider, modelId, monthlyTokens, freeType, tos, poolKey.
    Never crashes on parse failure — caller falls back to OpenRouter pricing filter.
    """
    import re
    req = urllib.request.Request(_OMNIRoute_CATALOG_URL, headers={
        "User-Agent": "free-llm-tracker/1.0 (+https://github.com/harrytyp/free-llm-tracker)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        txt = r.read().decode()
    # Match each record { provider: "x", modelId: "y", ..., freeType: "z" }
    rec_re = re.compile(
        r'\{[^}]*?provider:\s*"([^"]+)"[^}]*?modelId:\s*"([^"]+)"[^}]*?displayName:\s*"([^"]+)"'
        r'[^}]*?monthlyTokens:\s*(\d+)[^}]*?freeType:\s*"([^"]+)"[^}]*?poolKey:\s*"([^"]+)"[^}]*?\}',
        re.DOTALL)
    credits_re = re.compile(r'creditTokens:\s*(\d+)')
    tos_re = re.compile(r'tos:\s*\{[^}]*?verdict:\s*"([^"]+)"')
    out = []
    for m in rec_re.finditer(txt):
        provider, model_id, display, monthly, ftype, pool = m.groups()
        block = m.group(0)
        monthly_n = int(monthly)
        cred_m = credits_re.search(block)
        credit_n = int(cred_m.group(1)) if cred_m else None
        tos_m = tos_re.search(block)
        out.append({
            "provider": provider,
            "model_id": model_id,
            "display_name": display,
            "monthly_tokens": monthly_n,
            "credit_tokens": credit_n,
            "free_type": ftype,                # recurring-monthly / keyless / one-time-initial / recurring-uncapped / recurring-credit / recurring-daily / discontinued
            "pool_key": pool,
            "tos_verdict": tos_m.group(1) if tos_m else None,
        })
    # Filter out discontinued — they're historical entries, not usable
    out = [r for r in out if r["free_type"] != "discontinued"]
    return out


def fetch_benchmarks() -> dict[tuple, dict]:
    """llm-benchmarks.com measured speeds keyed by (modelCanonical, provider).

    t/s is provider-dependent (e.g. gpt-4o via OpenRouter vs. direct OpenAI
    differ by 2-3x), so the key is the (model, provider) pair, not model alone.
    """
    d = http_get_json("https://llm-benchmarks.com/api/processed")
    rows = d.get("table") or []
    out = {}
    for r in rows:
        cid = r.get("modelCanonical")
        provider = r.get("provider")
        if not cid or not provider:
            continue
        tps = r.get("tokens_per_second_mean")
        gen_tps = r.get("generated_tokens_per_second_mean")
        ttft = r.get("time_to_first_token_mean")
        samples = r.get("samples")
        if tps is None and gen_tps is None:
            continue
        entry = {
            "tps_mean": _num(tps),
            "tps_min": _num(r.get("tokens_per_second_min")),
            "tps_max": _num(r.get("tokens_per_second_max")),
            "gen_tps_mean": _num(gen_tps),
            "ttft_s": _num(ttft),
            "samples": int(samples) if isinstance(samples, (int, float)) else None,
            "provider_slug": provider,
            "last_benchmark": r.get("last_benchmark_date"),
        }
        # keep the row with more samples per (model, provider)
        prev = out.get((cid, provider))
        if prev is None or (entry["samples"] or 0) >= (prev["samples"] or 0):
            out[(cid, provider)] = entry
    return out


def fetch_aa(key: str | None) -> dict[str, dict]:
    """Artificial Analysis v2: intelligence index + median tps, keyed by lowercase slug."""
    if not key:
        return {}
    d = http_get_json(
        "https://artificialanalysis.ai/api/v2/data/llms/models",
        headers={"x-api-key": key},
        timeout=45,
    )
    out = {}
    for m in d.get("data", []):
        slug = (m.get("slug") or "").lower()
        if not slug:
            continue
        ev = m.get("evaluations") or {}
        out[slug] = {
            "intelligence_index": ev.get("artificial_analysis_intelligence_index"),
            "coding_index": ev.get("artificial_analysis_coding_index"),
            "aa_tps_median": _num(m.get("median_output_tokens_per_second")),
            "aa_ttft_s": _num(m.get("median_time_to_first_token_seconds")),
        }
    return out


# --- OpenRouter id <-> AA slug matching -------------------------------------

_OR_STRIP_PREFIXES = ("openrouter/",)


def normalize_key(model_id: str) -> list[str]:
    """Generate candidate lookup keys for a model id across sources."""
    base = model_id.lower()
    keys = [base]
    for p in _OR_STRIP_PREFIXES:
        if base.startswith(p):
            keys.append(base[len(p):])
    # strip openrouter ":free" suffix for cross-source matching
    if base.endswith(":free"):
        keys.append(base[:-5])
        for p in _OR_STRIP_PREFIXES:
            if keys[-1].startswith(p):
                keys.append(keys[-1][len(p):])
    return keys


def _num(x):
    try:
        return round(float(x), 2) if x is not None else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    errors: list[str] = []

    # 1a. OmniRoute curated free catalog (authoritative WHAT-is-free list, 523 recs)
    omnit_free: list[dict] = []
    try:
        omnit_free = fetch_omnitroute_free()
    except Exception as e:
        errors.append(f"omni-free-catalog: {e}")

    # 1b. OpenRouter free-by-pricing (catch free models OmniRoute doesn't catalog yet)
    try:
        or_free = fetch_openrouter()
    except Exception as e:
        or_free = []
        errors.append(f"openrouter: {e}")

    # Merge: build keyed by (provider, model_id) so OpenRouter augments OmniRoute
    by_key: dict[tuple, dict] = {}
    omnit_ids: set[str] = set()
    for rec in omnit_free:
        key = (rec["provider"], rec["model_id"])
        by_key[key] = {
            "id": rec["model_id"],
            "provider": rec["provider"],
            "name": rec["display_name"],
            "free_type": rec["free_type"],
            "monthly_tokens": rec["monthly_tokens"],
            "credit_tokens": rec["credit_tokens"],
            "pool_key": rec["pool_key"],
            "tos_verdict": rec["tos_verdict"],
            "source_catalog": "omniroute",
        }
        omnit_ids.add(rec["model_id"].lower())
    # Add OpenRouter free models not already present (by id)
    for m in or_free:
        mid = m["id"].lower()
        if mid in omnit_ids:
            # merge OR metadata into existing record
            for mk, mv in by_key.items():
                if mv["id"].lower() == mid:
                    mv.update({
                        "context_length": m.get("context_length"),
                        "description": (m.get("description") or "")[:280],
                        "supported_parameters": m.get("supported_parameters", []),
                        "modality": (m.get("architecture") or {}).get("modality", ""),
                    })
                omnit_ids.add(mid)
            continue
        # new from OR
        by_key[(m["id"].lower(), m["id"])] = {
            "id": m["id"],
            "provider": "openrouter",
            "name": m.get("name", m["id"]),
            "free_type": "recurring-monthly",
            "monthly_tokens": None,
            "credit_tokens": None,
            "pool_key": "openrouter",
            "tos_verdict": None,
            "context_length": m.get("context_length"),
            "description": (m.get("description") or "")[:280],
            "supported_parameters": m.get("supported_parameters", []),
            "modality": (m.get("architecture") or {}).get("modality", ""),
            "source_catalog": "openrouter",
        }

    free_models = list(by_key.values())
    if not free_models:
        print("FATAL both free catalogs empty — refusing to write bad data", file=sys.stderr)
        return 1

    # 2. Benchmarks (optional source)
    bench: dict = {}
    try:
        bench = fetch_benchmarks()
    except Exception as e:
        errors.append(f"llm-benchmarks: {e}")

    # 3. Artificial Analysis (optional source, needs key)
    aa: dict = {}
    aa_key = os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", "").strip()
    if aa_key:
        try:
            aa = fetch_aa(aa_key)
        except Exception as e:
            errors.append(f"artificial-analysis: {e}")

    # Join
    models_out = []
    matched_bench = matched_aa = 0
    # Provider alias: OmniRoute provider names -> llm-benchmarks provider slugs
    _PROVIDER_ALIASES = {
        "openrouter": "openrouter",
        "google": "google",
        "openai": "openai",
        "anthropic": "openai",
        "deepseek": "openai",
        "meta-llama": "openai",
        "mistral": "openai",
        "z-ai": "openai",
        "nvidia": "openai",
        "groq": "openai",
        "cerebras": "openai",
        "sambanova": "openai",
        "fireworks": "openai",
        "together": "openai",
        "hyperbolic": "openai",
        "novita": "openai",
        "deepinfra": "openai",
        "siliconflow": "openai",
        "chutes": "openai",
        "vllm": "openai",
        "ollama": "openai",
        "bedrock": "bedrock",
    }

    def _bench_for(model_id: str, provider: str) -> dict | None:
        """Look up measured speed for (model, provider), falling back to any provider."""
        mid = model_id.lower().rstrip(":free")
        # direct (model, provider) match
        for (cid, pslug), entry in bench.items():
            if cid.lower() == mid and pslug == provider:
                return entry
        # provider-alias match
        alias = _PROVIDER_ALIASES.get(provider)
        if alias:
            for (cid, pslug), entry in bench.items():
                if cid.lower() == mid and pslug == alias:
                    return entry
        # any provider for this model
        for (cid, pslug), entry in bench.items():
            if cid.lower() == mid:
                return entry
        return None

    for m in free_models:
        b = _bench_for(m["id"], m.get("provider", ""))
        if b:
            matched_bench += 1
        a = next((aa[k] for k in normalize_key(m["id"]) if k in aa), None)
        if a:
            matched_aa += 1
        models_out.append({
            **m,
            "speed": b,
            "intelligence": a,
        })

    # sort: measured speed desc (None last), then name
    def sort_key(mo):
        s = mo["speed"]
        return (
            0 if s and s.get("tps_mean") else 1,
            -(s["tps_mean"] if s and s.get("tps_mean") else 0),
            (mo["provider"] or "") + mo["id"],
        )
    models_out.sort(key=sort_key)

    snapshot = {
        "updated_at": now_iso,
        "counts": {
            "free_models": len(models_out),
            "with_measured_speed": matched_bench,
            "with_intelligence": matched_aa,
            "from_omniroute": len(omnit_free),
            "from_openrouter": len(or_free),
        },
        "source_errors": errors,
        "sources": {
            "omni_free_catalog": _OMNIRoute_CATALOG_URL,
            "openrouter": "https://openrouter.ai/api/v1/models",
            "benchmarks": "https://llm-benchmarks.com/api/processed",
            "intelligence": "https://artificialanalysis.ai/api/v2/data/llms/models",
        },
        "models": models_out,
    }

    DATA.mkdir(parents=True, exist_ok=True)

    # history append (only meaningful runs) + prune
    hist_path = DATA / "history.jsonl"
    line = json.dumps({
        "ts": now_iso,
        "counts": snapshot["counts"],
        "speeds": {
            m["id"]: {"tps": (m["speed"] or {}).get("tps_mean"), "gen_tps": (m["speed"] or {}).get("gen_tps_mean")}
            for m in models_out
        },
    }, separators=(",", ":"))
    lines = []
    if hist_path.exists():
        lines = [l for l in hist_path.read_text().splitlines() if l.strip()]
    lines.append(line)
    # prune: keep only last 90 days + last 2000 runs
    cutoff = (now - timedelta(days=HISTORY_MAX_DAYS)).strftime("%Y-%m-%d")
    kept = [l for l in lines if l[6:16] >= cutoff][-HISTORY_KEEP_RUNS:]
    hist_path.write_text("\n".join(kept) + "\n")

    (DATA / "latest.json").write_text(json.dumps(snapshot, indent=1))

    print(f"OK {now_iso}: {len(models_out)} free models, "
          f"{matched_bench} with measured speed, {matched_aa} with intelligence index")
    if errors:
        print("source errors:", *errors, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
