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
import re
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


def scrape_aa_providers(model_slug: str) -> list[dict]:
    """Fetch AA /models/{slug}/providers page, parse provider t/s table.

    AA publicly benchmarks every model against ALL providers (Groq, Cerebras,
    DeepInfra, Together, Fireworks, ...) with output speed (t/s), TTFT, price.
    HTML uses: <img alt="ProviderName"> ... <span class="...">VALUE</span><span ...>t/s</span>
    Returns [{provider, tps, ttft_s}] or [] on failure.
    """
    url = f"https://artificialanalysis.ai/models/{model_slug}/providers"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode()
    except Exception:
        return []

    # Find "Fastest" section (top providers with t/s)
    # Pattern: alt="ProviderName" ... >NUM</span><span ...>t/s</span>
    fastest_idx = html.find("Fastest")
    if fastest_idx < 0:
        return []
    section = html[fastest_idx:fastest_idx + 30000]

    pattern = re.compile(
        r'alt="([^"]+)"[^>]*>.*?'
        r'<span class="(?:font-medium|text-neutral-700)">([\d.]+)</span>'
        r'<span[^>]*>\s*<!-- -->t/s</span>',
        re.DOTALL)
    rows = []
    for m in pattern.finditer(section):
        prov, tps = m.group(1).strip(), float(m.group(2))
        if tps > 10000:
            continue
        rows.append({"provider": prov, "tps": round(tps, 1), "ttft_s": None})

    # Dedupe by provider name
    seen = {}
    for r in rows:
        if r["provider"] not in seen:
            seen[r["provider"]] = r
    return list(seen.values())


# AA slug conversion: our model id -> AA page slug
def aa_slug(model_id: str) -> str | None:
    """Map OpenRouter/OmniRoute model id to Artificial Analysis slug."""
    mid = model_id.lower().rstrip(":free").split("/")[-1]
    # known mappings (curated from search)
    known = {
        "glm-5.2": "glm-5-2",
        "glm-5.1": "glm-5-1",
        "gpt-oss-20b": "gpt-oss-20b",
        "gpt-oss-120b": "gpt-oss-120b",
        "gpt-oss-120b-medium": "gpt-oss-120b",
        "gemma-4-31b-it": "gemma-4-31b",
        "gemma-4-26b-a4b-it": "gemma-4-26b",
        "llama-3.3-70b-instruct": "llama-3-3-instruct-70b",
        "llama-3.1-8b-instruct": "llama-3-1-instruct-8b",
        "llama-3.1-70b-instruct": "llama-3-1-instruct-70b",
        "nemotron-3-nano-30b-a3b": "nemotron-3-nano-30b",
        "nemotron-3-super-120b-a12b": "nemotron-3-super-120b",
        "nemotron-3-ultra-550b-a55b": "nemotron-3-ultra-550b",
        "deepseek-v4-pro": "deepseek-v4-pro",
        "laguna-s-2.1": "laguna-s-2-1",
        "ox-alpha": "ox-alpha",
    }
    if mid in known:
        return known[mid]
    # fallback: replace dots with dashes, strip -it/-instruct suffixes
    slug = mid.replace(".", "-")
    slug = re.sub(r"-(it|instruct|chat|preview)$", "", slug)
    return slug if len(slug) > 3 else None


def collect_aa_measurements(model_ids: list[str]) -> dict:
    """Scrape AA provider tables for all models. Returns {model_id: {providers: [...]}}."""
    out = {}
    for mid in model_ids:
        slug = aa_slug(mid)
        if not slug:
            continue
        rows = scrape_aa_providers(slug)
        if rows:
            out[mid] = {
                "providers": rows,
                "source": "artificialanalysis-provider-benchmarks",
                "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
            best = max(rows, key=lambda r: r["tps"] or 0)
            print(f"    {mid} -> AA slug {slug}: {len(rows)} providers, "
                  f"best {best['provider']} {best['tps']} t/s")
        else:
            print(f"    {mid} -> AA slug {slug}: no data")
        time.sleep(0.5)
    return out


def scrape_llmbench_provider(provider: str) -> list[dict]:
    """Scrape llm-benchmarks.com /providers/{name} page (30-day measured t/s).

    Each provider page lists its models with Avg Toks/Sec, Min, Max, Avg TTF(ms),
    aggregated over the last 30 days from hundreds/thousands of real prompts.
    Returns [{model, tps, tps_min, tps_max, ttft_ms}] or [].
    """
    url = f"https://llm-benchmarks.com/providers/{provider}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            html = r.read().decode()
    except Exception:
        return []

    # Table rows: <a href="/models/{provider}/{slug}">ModelName</a> ... <td>VALUE</td>...
    # After the model link, the cells are: Avg Toks/Sec, Min, Max, Avg TTF(ms)
    rows = []
    # Find each model row: link to model page, then extract numeric cells after it
    for m in re.finditer(r'href="/models/[^"]+">([^<]+)</a>(.*?)</tr>', html, re.DOTALL):
        model = m.group(1).strip()
        cells_html = m.group(2)
        # Extract all numeric cell values in order
        nums = re.findall(r'<td[^>]*>([\d.]+)</td>', cells_html)
        if len(nums) >= 4:
            tps, tps_min, tps_max, ttft = nums[:4]
            rows.append({
                "model": model,
                "tps": round(float(tps), 2),
                "tps_min": round(float(tps_min), 2),
                "tps_max": round(float(tps_max), 2),
                "ttft_ms": round(float(ttft), 1) if float(ttft) > 0 else None,
            })
    return rows


LLMBENCH_PROVIDERS = [
    "anthropic", "bedrock", "cerebras", "deepinfra", "fireworks",
    "google", "groq", "openai", "openrouter", "together",
]


def collect_llmbench_measurements() -> dict:
    """Scrape all llm-benchmarks provider pages. Returns {model_key: {provider, tps, ...}}."""
    out = {}
    for prov in LLMBENCH_PROVIDERS:
        rows = scrape_llmbench_provider(prov)
        if rows:
            print(f"  llm-benchmarks {prov}: {len(rows)} models tracked")
            for r in rows:
                # key: model name lowercased, spaces->dashes
                key = r["model"].lower().replace(" ", "-")
                out[key] = {
                    "provider": prov,
                    "tps": r["tps"],
                    "tps_min": r["tps_min"],
                    "tps_max": r["tps_max"],
                    "ttft_ms": r["ttft_ms"],
                    "source": "llm-benchmarks-provider",
                    "measured_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                }
        time.sleep(0.5)
    return out


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

    # 3. Artificial Analysis provider benchmarks (public, no key) - the KEY source
    #    for "all providers per model": AA measures every provider publicly.
    latest = json.loads((DATA / "latest.json").read_text())
    free_models = latest["models"]

    # 3a. llm-benchmarks.com provider pages (30-day measured t/s per provider)
    print("\n  llm-benchmarks provider pages (30-day measurements)...")
    llmbench = collect_llmbench_measurements()
    all_results["__llmbench"] = {
        "type": "provider-summary",
        "providers": llmbench,
    }
    print(f"  → {len(llmbench)} model measurements across providers")

    # 3b. AA provider benchmarks for unique model basenames
    seen_bases = set()
    aa_targets = []
    for m in free_models:
        base = m["id"].lower().rstrip(":free").split("/")[-1]
        if base in seen_bases:
            continue
        seen_bases.add(base)
        aa_targets.append(m["id"])
        if len(aa_targets) >= 40:  # budget: 40 model pages per run
            break

    print(f"\n  AA provider benchmarks for {len(aa_targets)} models...")
    aa_data = collect_aa_measurements(aa_targets)
    all_results.update(aa_data)

    out = {
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "method": "openrouter endpoints API + AA provider benchmarks (public) + own streaming",
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
