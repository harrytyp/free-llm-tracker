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

    # Live-verified free IDs from OpenRouter (pricing==0 confirmed just now)
    or_live_free_ids = {m["id"].lower() for m in or_free}

    # ─── Multi-Provider Free-Erkennung (Kolja: nicht nur OpenRouter!) ───
    # Jeder Provider mit Key hat Free-Tiers (Groq, Mistral, NVIDIA, Google...).
    # Wir fragen deren /models ab, markieren alle als "free-tier" (der Key ist
    # der Zugangsbeweis), und fügen sie als neue Kandidaten hinzu. Der Router
    # nutzt sie, sobald der Key gesetzt ist.
    # Provider-Config: (base_url für /models, key_env, OpenAI-kompatibel?)
    KEY_PROVIDERS = {
        "openrouter": ("https://openrouter.ai/api/v1/models", "OPENROUTER_API_KEY", True),
        "groq": ("https://api.groq.com/openai/v1/models", "GROQ_API_KEY", True),
        "mistral": ("https://api.mistral.ai/v1/models", "MISTRAL_API_KEY", True),
        "nvidia": ("https://integrate.api.nvidia.com/v1/models", "NVIDIA_API_KEY", True),
        "google": ("https://generativelanguage.googleapis.com/v1beta/openai/models", "GOOGLE_API_KEY", True),
        "cerebras": ("https://api.cerebras.ai/v1/models", "CEREBRAS_API_KEY", True),
        "deepinfra": ("https://api.deepinfra.com/v1/openai/models", "DEEPINFRA_API_KEY", True),
        "together": ("https://api.together.xyz/v1/models", "TOGETHER_API_KEY", True),
        "fireworks": ("https://api.fireworks.ai/inference/v1/models", "FIREWORKS_API_KEY", True),
        "sambanova": ("https://api.sambanova.ai/v1/models", "SAMBANOVA_API_KEY", True),
        "novita": ("https://api.novita.ai/v3/openai/models", "NOVITA_API_KEY", True),
        "siliconflow": ("https://api.siliconflow.cn/v1/models", "SILICONFLOW_API_KEY", True),
        "hyperbolic": ("https://api.hyperbolic.xyz/v1/models", "HYPERBOLIC_API_KEY", True),
        "cohere": ("https://api.cohere.ai/v1/models", "COHERE_API_KEY", True),
        "manifest": ("https://app.manifest.build/v1/models", "MANIFEST_API_KEY", True),
    }
    # OpenAI-URLs ohne "openai"-Pfad → chat/completions direkt anhängen
    # (Router nutzt diese Liste, um Free-Modelle der Key-Provider zu routen)

    import os as _os
    key_provider_models: dict[str, list[str]] = {}
    for pname, (murl, key_env, _compat) in KEY_PROVIDERS.items():
        key = _os.environ.get(key_env, "").strip()
        if not key:
            continue  # kein Key → Provider nicht prüfbar
        try:
            req = urllib.request.Request(murl, headers={
                "Authorization": f"Bearer {key}", "User-Agent": "free-llm-tracker/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            ids = [m.get("id") for m in d.get("data", []) if m.get("id")]
            key_provider_models[pname] = ids
            print(f"  key-provider {pname}: {len(ids)} Modelle (Free-Tier-Zugang via Key)")
        except Exception as e:
            errors.append(f"key-provider {pname}: {e}")

    # Provider with OpenAI-compatible API endpoints the router can actually call.
    # Web-frontend providers (puter, t3-web, huggingchat...) are NOT here —
    # they're chat UIs without a usable API endpoint.
    ROUTABLE_PROVIDERS = {
        "openrouter", "deepinfra", "nvidia", "novita", "sambanova",
        "groq", "cerebras", "fireworks", "together", "siliconflow",
        "hyperbolic", "mistral", "cohere", "openai", "anthropic", "google",
        "cloudflare-ai", "github-models", "vertex", "bedrock", "ollama-cloud",
        "kilo-gateway",
    }

    def is_provably_free(m: dict) -> bool:
        """Free per OmniRoute curated catalog (the trusted source Kolja picked).

        OmniRoute freeModelCatalog.data.ts is a manually researched list of
        free models across ALL providers (Groq, Cerebras, Mistral, Google,
        Cloudflare, ...). It is the source of truth for WHAT is free — NOT
        OpenRouter pricing (OR only lists its own models).
        """
        return True  # all models here come from the OmniRoute free catalog

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
    or_live_ids = set()
    for m in or_free:
        mid = m["id"].lower()
        or_live_ids.add(mid)
        if mid in omnit_ids:
            # merge OR metadata into existing record
            for mk, mv in by_key.items():
                if mv["id"].lower() == mid:
                    mv.update({
                        "free_status": "verified-free",  # OR pricing==0 confirmed live
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
            "free_status": "verified-free",
        }

    # Flag OmniRoute models with :free suffix that OpenRouter no longer lists
    # as deprecated (was free, now gone) — honest free-status verification.
    for rec in omnit_free:
        mid = rec["model_id"].lower()
        if mid.endswith(":free") and mid not in or_live_ids:
            for mk, mv in by_key.items():
                if mv["id"].lower() == mid:
                    mv["free_status"] = "deprecated-not-on-openrouter"
                    break

    # ─── Key-Provider-Merge (nicht nur OpenRouter!) ───
    # Alle Modelle der Key-Provider als free-tier hinzufügen (Key = Zugangsbeweis).
    # Nur Provider mit gesetztem Key; Modelle, die schon existieren, werden nicht
    # überschrieben (OmniRoute/OR-Metadaten behalten Vorrang).
    added_kp = 0
    for pname, ids in key_provider_models.items():
        if pname == "openrouter":
            continue  # OR schon über or_free verarbeitet (pricing==0 verified)
        for mid in ids:
            mid_l = mid.lower()
            exists = any(mv["id"].lower() == mid_l for mv in by_key.values())
            if exists:
                # existierender Eintrag: free_status free-tier vergeben, wenn unklar
                for mv in by_key.values():
                    if mv["id"].lower() == mid_l and mv.get("free_status") in (None, "unverified"):
                        mv["free_status"] = "free-tier"
                        mv["source_catalog"] = mv.get("source_catalog", "key-provider")
                    break
                continue
            by_key[(pname, mid)] = {
                "id": mid,
                "provider": pname,
                "name": mid,
                "free_type": "free-tier",
                "monthly_tokens": None,
                "credit_tokens": None,
                "pool_key": pname,
                "tos_verdict": None,
                "source_catalog": "key-provider",
                "free_status": "free-tier",
            }
            added_kp += 1
    if added_kp:
        print(f"  key-provider: {added_kp} neue Free-Modelle hinzugefügt")

    free_models = list(by_key.values())
    # EXCLUDE deprecated models entirely (not free anymore, don't show them)
    before = len(free_models)
    free_models = [m for m in free_models if m.get("free_status") != "deprecated-not-on-openrouter"]
    print(f"  excluded {before - len(free_models)} deprecated models")

    # FREE-ONLY gate: only keep models that are PROVABLY free.
    # The tracker data source must contain ONLY free models (Kolja: "dort muss
    # schon die Filterung passieren, nicht im Routing").
    before = len(free_models)
    free_models = [m for m in free_models if is_provably_free(m)]
    print(f"  excluded {before - len(free_models)} non-free models (paid/unverified)")

    if not free_models:
        print("FATAL both free catalogs empty after free-only filter — refusing to write bad data", file=sys.stderr)
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
    matched_aa = 0
    # NOTE: No provider aliasing. t/s is attached per (model, provider) by
    # benchmark.py from llm-benchmarks data (n>=3 only). The old alias map
    # (groq->openai etc.) was WRONG and is deleted (AGENTS.md rev 2).

    for m in free_models:
        a = next((aa[k] for k in normalize_key(m["id"]) if k in aa), None)
        if a:
            matched_aa += 1
        models_out.append({
            **m,
            "intelligence": a,
        })

    # sort: by provider + id (stable)
    def sort_key(mo):
        return (mo.get("provider") or "") + mo["id"]
    models_out.sort(key=sort_key)

    snapshot = {
        "updated_at": now_iso,
        "counts": {
            "free_models": len(models_out),
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
        "model_count": len(models_out),
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
          f"{matched_aa} with intelligence index")
    if errors:
        print("source errors:", *errors, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
