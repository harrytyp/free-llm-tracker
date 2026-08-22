#!/usr/bin/env python3
"""llm-mini-router — super lightweight auto-routing LLM gateway.

ONE OpenAI-compatible endpoint (/v1/chat/completions). For each request it:
  1. Picks the best model from the free-llm-tracker data according to criteria
     (intelligence, min tps, provider, mode: smartest/fastest/balanced)
  2. Streams the request to the chosen provider (OpenAI-compatible)
  3. On failure/rate-limit, auto-falls back to the next best model

Data source: free-llm-tracker latest.json + benchmarks.json (fetched from
GitHub Pages raw on start, refreshable via GET /refresh).

Runtime: Python stdlib only (http.server, urllib). No deps, no framework.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import urllib.request
import urllib.error
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- Config ---------------------------------------------------------------

PORT = int(os.environ.get("MINI_ROUTER_PORT", "8080"))
HOST = os.environ.get("MINI_ROUTER_HOST", "127.0.0.1")  # localhost default = safe

# Tracker data URLs (raw from GitHub Pages = static, no build)
DATA_URL = os.environ.get(
    "TRACKER_DATA_URL",
    "https://harrytyp.github.io/free-llm-tracker/data/latest.json",
)
BENCH_URL = os.environ.get(
    "TRACKER_BENCH_URL",
    "https://harrytyp.github.io/free-llm-tracker/data/benchmarks.json",
)

# Providers we can route to. Each needs an OpenAI-compatible base_url.
# Key env: OPENROUTER_API_KEY etc. Add more by extending this dict.
# Free model lists come from the free-llm-tracker data (OmniRoute catalog).
#
# NOTE (2026-08): The 17 "keyless" providers in OmniRoute (puter, blackbox,
# agy, duckduckgo-web, qwen-web, felo-web, pollinations...) are WEB FRONTENDS
# without OpenAI-compatible APIs — they cannot be routed by this gateway.
# Real API routing requires a key-based provider below. Keys are free tiers,
# no credit card (Groq, Cerebras, Mistral, Google AI Studio, GitHub Models...).
PROVIDERS = {
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "OPENROUTER_API_KEY",
        "model_prefix": ("", "openrouter/"),
    },
    "deepinfra": {
        "base_url": "https://api.deepinfra.com/v1/openai",
        "key_env": "DEEPINFRA_API_KEY",
    },
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "key_env": "NVIDIA_API_KEY",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
    },
    "cerebras": {
        "base_url": "https://api.cerebras.ai/v1",
        "key_env": "CEREBRAS_API_KEY",
    },
    "fireworks": {
        "base_url": "https://api.fireworks.ai/inference/v1",
        "key_env": "FIREWORKS_API_KEY",
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "key_env": "TOGETHER_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "key_env": "SILICONFLOW_API_KEY",
    },
    "hyperbolic": {
        "base_url": "https://api.hyperbolic.xyz/v1",
        "key_env": "HYPERBOLIC_API_KEY",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "key_env": "MISTRAL_API_KEY",
    },
    "cohere": {
        "base_url": "https://api.cohere.ai/v1",
        "key_env": "COHERE_API_KEY",
    },
    "sambanova": {
        "base_url": "https://api.sambanova.ai/v1",
        "key_env": "SAMBANOVA_API_KEY",
    },
    "novita": {
        "base_url": "https://api.novita.ai/v3/openai",
        "key_env": "NOVITA_API_KEY",
    },
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_env": "GOOGLE_API_KEY",
    },
    "github-models": {
        "base_url": "https://models.github.ai/api/rest",
        "key_env": "GITHUB_MODELS_KEY",
    },
    "cloudflare-ai": {
        "base_url": "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/v1",
        "key_env": "CLOUDFLARE_API_TOKEN",
    },
    "kilo-gateway": {
        "base_url": "https://api.kilo-gateway.ai/v1",
        "key_env": "KILO_GATEWAY_API_KEY",
    },
    "manifest": {
        "base_url": "https://app.manifest.build/v1",
        "key_env": "MANIFEST_API_KEY",
    },
}

CACHE_TTL = int(os.environ.get("MINI_ROUTER_CACHE_TTL", "3600"))  # 1h data cache

# --- Data model -----------------------------------------------------------

DATA = {"models": [], "bench": {}, "loaded_at": 0}

# Models currently rate-limited / failing: model_id -> cooldown_until (epoch)
COOLDOWN: dict[str, float] = {}
COOLDOWN_SECONDS = int(os.environ.get("MINI_ROUTER_COOLDOWN", "600"))  # 10 min
# Live uptime snapshot from OpenRouter endpoints API (model_id -> uptime)
LIVE: dict[str, dict] = {"uptime": {}, "fetched_at": 0}
LIVE_TTL = int(os.environ.get("MINI_ROUTER_LIVE_TTL", "600"))  # 10 min live cache
MAX_FALLBACKS_DEFAULT = 8  # OpenRouter free tier is often rate-limited; try more

# USAGE STATS (learned from real requests, NOT benchmarks):
# model_id -> {"ok": n, "fail": n, "latency_ms": [..], "last_ok": epoch}
USAGE: dict[str, dict] = {}
# models with >= this many successes are "proven" and ranked above untested
PROVEN_OK = int(os.environ.get("MINI_ROUTER_PROVEN_OK", "3"))

# --- Persistence (usage → GitHub Pages data/usage.json) --------------------
USAGE_FILE = os.environ.get(
    "MINI_ROUTER_USAGE_FILE",
    "/opt/data/projects/free-llm-tracker/data/usage.json",
)
USAGE_SAVE_INTERVAL = int(os.environ.get("MINI_ROUTER_SAVE_INTERVAL", "60"))
# Auto-push via GitHub API: Teil des Routers (kein Cron). Nur bei Änderung.
PUSH_INTERVAL = int(os.environ.get("MINI_ROUTER_PUSH_INTERVAL", "300"))
_last_save = 0.0
_last_push = 0.0
_last_pushed_sha = None  # SHA des letzten gepushten Inhalts (Änderungserkennung)


def load_usage() -> None:
    """Load persisted usage stats (survives router restarts)."""
    global USAGE
    try:
        if os.path.exists(USAGE_FILE):
            with open(USAGE_FILE) as f:
                data = json.load(f)
            USAGE = data.get("usage", {})
            # cooldowns from last run still valid
            for mid, until in (data.get("cooldowns") or {}).items():
                if until > time.time():
                    COOLDOWN[mid] = until
            print(f"[router] loaded usage: {len(USAGE)} models, "
                  f"{len([c for c in COOLDOWN if COOLDOWN[c] > time.time()])} on cooldown")
    except Exception as e:
        print(f"[router] usage load failed: {e}", file=sys.stderr)


def save_usage(force: bool = False) -> None:
    """Persist usage + cooldowns (throttled to every SAVE_INTERVAL sec)."""
    global _last_save
    now = time.time()
    if not force and now - _last_save < USAGE_SAVE_INTERVAL:
        return
    _last_save = now
    try:
        os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
        payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "usage": USAGE,
            "cooldowns": {mid: until for mid, until in COOLDOWN.items() if until > now},
        }
        tmp = USAGE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=1)
        os.replace(tmp, USAGE_FILE)
    except Exception as e:
        print(f"[router] usage save failed: {e}", file=sys.stderr)


def push_usage() -> None:
    """Push usage.json to GitHub via the Contents API (part of the router).

    Called after save_usage; throttled to PUSH_INTERVAL and only when the
    content changed (SHA compare). Token from env (GITHUB_TOKEN/HERMES_GIT_TOKEN),
    never in code. Failures are logged, never crash the router.
    """
    global _last_push, _last_pushed_sha
    now = time.time()
    if now - _last_push < PUSH_INTERVAL:
        return
    _last_push = now
    if not os.path.exists(USAGE_FILE):
        return
    token = (os.environ.get("HERMES_GIT_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if not token:
        print("[router] push skipped: no GITHUB_TOKEN/HERMES_GIT_TOKEN in env")
        return
    repo = os.environ.get("MINI_ROUTER_GITHUB_REPO", "harrytyp/free-llm-tracker")
    path = "data/usage.json"
    api = f"https://api.github.com/repos/{repo}/contents/{path}"

    try:
        content = open(USAGE_FILE, "rb").read()
        import hashlib
        sha = hashlib.sha1(content).hexdigest()
        if sha == _last_pushed_sha:
            return  # nichts geändert
        b64 = base64.b64encode(content).decode()

        # aktuellen SHA holen (für Update statt Create)
        req = urllib.request.Request(api, headers={"Authorization": f"Bearer {token}",
                                                    "User-Agent": "llm-mini-router/1.0",
                                                    "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                existing = json.loads(r.read().decode())
                file_sha = existing.get("sha")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                print(f"[router] push: GET failed {e.code}, retry later")
                return
            file_sha = None  # Datei existiert noch nicht

        payload = {
            "message": f"usage update {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}",
            "content": b64,
        }
        if file_sha:
            payload["sha"] = file_sha
        req = urllib.request.Request(
            api,
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "llm-mini-router/1.0",
                     "Accept": "application/vnd.github+json"},
            method="PUT",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode())
            _last_pushed_sha = sha
            print(f"[router] ⇧ usage.json pushed to GitHub ({resp.get('commit', {}).get('sha', '?')[:8]})")
    except urllib.error.HTTPError as e:
        print(f"[router] push failed: HTTP {e.code}: {e.read().decode()[:200]}")
    except Exception as e:
        print(f"[router] push failed: {e}")


def fetch_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "llm-mini-router/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def load_data(force: bool = False) -> None:
    """Load tracker data (latest.json + benchmarks.json) with TTL cache."""
    now = time.time()
    if not force and now - DATA["loaded_at"] < CACHE_TTL and DATA["models"]:
        return
    try:
        latest = fetch_json(DATA_URL)
        models = latest.get("models", [])
        # benchmarks: intelligence + tps per model
        bench = {}
        try:
            b = fetch_json(BENCH_URL)
            results = b.get("results", {})
            aa = (results.get("__aa") or {}).get("models", {}) or {}
            llmbench = (results.get("__llmbench") or {}).get("providers", {}) or {}
            bench["__aa"] = aa
            bench["__llmbench"] = llmbench
            for mid, entry in results.items():
                if mid.startswith("__"):
                    continue
                if entry.get("providers"):
                    provs = sorted(entry["providers"], key=lambda p: p.get("tps") or 0, reverse=True)
                    bench[mid] = {"tps": provs[0].get("tps"), "intel": None,
                                  "providers": provs}
                elif entry.get("tps") is not None:
                    bench[mid] = {"tps": entry.get("tps"), "intel": None}
        except Exception:
            pass
        DATA["models"] = models
        DATA["bench"] = bench
        DATA["loaded_at"] = now
        print(f"[router] data loaded: {len(models)} models, {len(bench)} benchmarks")
    except Exception as e:
        print(f"[router] data load failed: {e}", file=sys.stderr)


def aa_slug_for(model_id: str) -> str | None:
    aa = DATA["bench"].get("__aa", {})
    mid = model_id.lower().rstrip(":free").split("/")[-1]
    if mid in aa:
        return mid
    slug = mid.replace(".", "-")
    if slug in aa:
        return slug
    for aas in aa:
        if mid.startswith(aas) or aas.startswith(mid):
            return aas
    return None


def fetch_live_uptime() -> None:
    """Fetch live uptime for OpenRouter free models (1 call, 10-min cache).

    The endpoints API returns uptime_last_30m per model — the LIVE availability,
    unlike the historical t/s benchmarks. Used to rank candidates.
    """
    now = time.time()
    if now - LIVE["fetched_at"] < LIVE_TTL and LIVE["uptime"]:
        return
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return
    try:
        d = fetch_json("https://openrouter.ai/api/v1/models", timeout=20)
        free_ids = [m["id"] for m in d.get("data", [])
                    if str((m.get("pricing") or {}).get("prompt", "1")) == "0"
                    and str((m.get("pricing") or {}).get("completion", "1")) == "0"]
        uptime = {}
        for mid in free_ids[:40]:  # budget: first 40 free models
            try:
                ep = fetch_json(f"https://openrouter.ai/api/v1/models/{mid}/endpoints", timeout=15)
                data = ep.get("data", ep)
                for e in data.get("endpoints", []):
                    up = e.get("uptime_last_30m")
                    if up is not None:
                        uptime[mid] = round(up, 3)
            except Exception:
                pass
        LIVE["uptime"] = uptime
        LIVE["fetched_at"] = now
        print(f"[router] live uptime: {len(uptime)} models")
    except Exception as e:
        print(f"[router] uptime fetch failed: {e}", file=sys.stderr)


def in_cooldown(model_id: str) -> bool:
    return COOLDOWN.get(model_id, 0) > time.time()


def mark_failed(model_id: str) -> None:
    """Put a failed/rate-limited model on cooldown."""
    COOLDOWN[model_id] = time.time() + COOLDOWN_SECONDS
    print(f"[router] ⛔ {model_id} on cooldown for {COOLDOWN_SECONDS}s")


def model_metrics(m: dict) -> dict:
    """Return {intel, tps, ttft, price} for a model using all data sources."""
    mid = m["id"].lower().rstrip(":free")
    intel = None
    tps = None
    ttft = None

    # 1. AA intelligence
    slug = aa_slug_for(m["id"])
    if slug:
        am = DATA["bench"]["__aa"].get(slug, {})
        intel = am.get("intelligence_index")
        if tps is None:
            tps = am.get("tps")
        ttft = am.get("ttft_s")

    # 2. Direct benchmark entry
    entry = DATA["bench"].get(m["id"]) or DATA["bench"].get(mid)
    if entry:
        if tps is None:
            tps = entry.get("tps")
        if not intel:
            intel = entry.get("intel")

    # 3. llm-benchmarks fallback
    if tps is None:
        base = mid.split("/")[-1].replace(".", "-").replace("_", "-")
        for key, val in DATA["bench"].get("__llmbench", {}).items():
            if base in key or key in base:
                tps = val.get("tps")
                break

    return {"intel": intel, "tps": tps, "ttft": ttft}


def pick_model(criteria: dict) -> dict:
    """Choose the best model per criteria.

    criteria keys:
      mode: 'smartest' | 'fastest' | 'balanced' (default 'balanced')
      min_tps: float (default 0)
      min_intel: float (default 0)
      provider: str (optional, filter)
      model: str (optional, exact model id override)
    """
    models = DATA["models"]
    if not models:
        raise RuntimeError("no model data loaded — run /refresh")

    # exact model override
    if criteria.get("model"):
        mid = criteria["model"].lower()
        for m in models:
            if m["id"].lower() == mid:
                return m, "exact-match"
        raise RuntimeError(f"model not found: {criteria['model']}")

    min_tps = float(criteria.get("min_tps", 0))
    min_intel = float(criteria.get("min_intel", 0))
    provider = criteria.get("provider")
    mode = criteria.get("mode", "balanced")

    # Only consider providers that have a configured API key (or are keyless-public)
    def provider_available(pname: str) -> bool:
        if pname == "openrouter":
            return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        pcfg = PROVIDERS.get(pname)
        if not pcfg:
            return False
        key_env = pcfg.get("key_env")
        if not key_env:
            return True  # public keyless
        return bool(os.environ.get(key_env, "").strip())

    scored = []
    for m in models:
        if provider and m.get("provider", "").lower() != provider.lower():
            continue
        # skip deprecated
        if m.get("free_status") == "deprecated-not-on-openrouter":
            continue
        pname = m.get("provider", "")
        if not provider_available(pname):
            continue
        met = model_metrics(m)
        tps = met["tps"] or 0
        intel = met["intel"] or 0
        if tps < min_tps:
            continue
        if intel < min_intel:
            continue
        scored.append((m, met))

    if not scored:
        raise RuntimeError(f"no model matches criteria: {criteria}")

    # RANK = INTELLIGENCE (quality) × USAGE DATA (availability/latency).
    # Kolja: intelligence is essential — combined with real usage learning.
    # Availability layer (from real requests):
    #   0 = proven (>= PROVEN_OK successes) — working right now
    #   1 = untested (no failures yet) — neutral
    #   2 = failed before (not on cooldown) — last resort
    # Within each group, mode decides the quality score:
    #   smartest → intelligence index
    #   fastest  → measured latency (usage) / benchmark tps fallback
    #   balanced → 60% intelligence + 40% speed (latency or tps)
    def avail_group(mid: str) -> int:
        u = USAGE.get(mid)
        if not u:
            return 1
        if u.get("ok", 0) >= PROVEN_OK:
            return 0
        if u.get("fail", 0) > 0:
            return 2
        return 1

    # Providers with a configured key are more reliable (own quota, not shared
    # OpenRouter free pool). Give their models a small availability bonus.
    def provider_bonus(m) -> float:
        pname = m.get("provider", "")
        pcfg = PROVIDERS.get(pname)
        if pcfg and os.environ.get(pcfg.get("key_env", ""), "").strip():
            return -0.5  # prefer key-backed providers (own rate limits)
        return 0.0
    def median_latency(mid: str):
        u = USAGE.get(mid)
        if not u or not u.get("latency_ms"):
            return None
        lat = sorted(u["latency_ms"])
        return lat[len(lat)//2]

    max_intel = max((x[1]["intel"] or 0) for x in scored) or 1
    max_tps = max((x[1]["tps"] or 0) for x in scored) or 1

    def quality_score(m, met) -> float:
        intel_n = (met["intel"] or 0) / max_intel
        lat = median_latency(m["id"])
        if lat is not None:
            speed_n = 1.0 - min(lat / 10000.0, 1.0)  # <10s = faster better
        else:
            speed_n = (met["tps"] or 0) / max_tps  # fallback: benchmark tps
        if mode == "smartest":
            return intel_n + 0.1 * speed_n
        if mode == "fastest":
            return speed_n + 0.1 * intel_n
        return 0.6 * intel_n + 0.4 * speed_n

    scored.sort(key=lambda x: (avail_group(x[0]["id"]) + provider_bonus(x[0]), -quality_score(x[0], x[1])))

    return scored


# --- Routing --------------------------------------------------------------

def route_request(body: dict, stream: bool) -> dict | None:
    """Pick model, stream to provider with AUTO-FALLBACK on failure.

    model="auto" (or "mini-router/auto") → router picks per criteria (default).
    model=<concrete id> (e.g. "openai/gpt-oss-120b") → route exactly there.
    Tries up to MAX_FALLBACKS candidates in order; on 429/5xx/connection
    error moves to the next best model.
    """
    criteria = body.get("router", {}) or {}
    model_field = str(body.get("model", "")).lower()

    # Manual override: concrete model id (not auto) → exact routing
    is_auto = model_field in ("auto", "mini-router/auto", "", "minirouter/auto")
    if not is_auto:
        # strip provider prefix if given (mini-router/auto → auto)
        if "/" in model_field and model_field.split("/", 1)[0] in ("mini-router", "minirouter"):
            model_field = model_field.split("/", 1)[1]
        criteria["model"] = model_field  # exact match
    elif not criteria.get("mode") and not criteria.get("model"):
        criteria["mode"] = "balanced"

    MAX_FALLBACKS = int(os.environ.get("MINI_ROUTER_MAX_FALLBACKS", str(MAX_FALLBACKS_DEFAULT)))
    last_err = None

    # Build candidate list once (best first)
    candidates = candidate_models(criteria)
    if not candidates:
        raise RuntimeError(f"no model matches criteria: {criteria}")

    # Single-user optimization: ALWAYS try the BEST model first (deterministic).
    # No load-spreading — that was wrong for a single user. Fallback only on failure.
    tried = []
    for rank, (m, match_type) in enumerate(candidates[:MAX_FALLBACKS]):
        model_id = m["id"]
        provider_name = m.get("provider", "openrouter")
        tried.append(model_id)

        pcfg = PROVIDERS.get(provider_name)
        if not pcfg:
            if "/" in model_id or ":free" in model_id:
                pcfg = PROVIDERS["openrouter"]
                provider_name = "openrouter"
            else:
                last_err = RuntimeError(f"no routing config for provider {provider_name}")
                continue

        key = os.environ.get(pcfg["key_env"], "").strip()
        if not key:
            last_err = RuntimeError(f"no API key for provider {provider_name}")
            continue

        out_body = {k: v for k, v in body.items() if k not in ("router",)}
        out_body["model"] = model_id

        url = f"{pcfg['base_url']}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(out_body).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
                "User-Agent": "llm-mini-router/1.0",
            },
            method="POST",
        )
        try:
            t0 = time.monotonic()
            resp = urllib.request.urlopen(req, timeout=120)
            data = json.loads(resp.read().decode())
            latency_ms = (time.monotonic() - t0) * 1000
            # record success in usage stats
            u = USAGE.setdefault(model_id, {"ok": 0, "fail": 0, "latency_ms": [], "last_ok": 0})
            u["ok"] += 1
            u["latency_ms"] = (u["latency_ms"] + [round(latency_ms)])[-50:]
            u["last_ok"] = time.time()
            # annotate which model actually served
            data["_router"] = {"model": model_id, "provider": provider_name, "tried": tried,
                               "latency_ms": round(latency_ms)}
            print(f"[router] ✓ {model_id} via {provider_name} (rank {rank+1}, {latency_ms:.0f}ms)")
            save_usage()
            push_usage()
            return data
        except urllib.error.HTTPError as e:
            last_err = e
            u = USAGE.setdefault(model_id, {"ok": 0, "fail": 0, "latency_ms": [], "last_ok": 0})
            u["fail"] += 1
            mark_failed(model_id)
            print(f"[router] ✗ {model_id}: HTTP {e.code}, falling back")
            save_usage()
            push_usage()
        except Exception as e:
            last_err = e
            u = USAGE.setdefault(model_id, {"ok": 0, "fail": 0, "latency_ms": [], "last_ok": 0})
            u["fail"] += 1
            mark_failed(model_id)
            print(f"[router] ✗ {model_id}: {e}, falling back")

    raise RuntimeError(f"all {len(tried)} candidates failed: {tried} — last: {last_err}")


def candidate_models(criteria: dict) -> list[tuple]:
    """Return ranked [(model, metrics)] list per criteria (best first)."""
    models = DATA["models"]
    if not models:
        raise RuntimeError("no model data loaded — run /refresh")

    if criteria.get("model"):
        mid = criteria["model"].lower()
        # exact matches — prefer one with available provider key
        exact = [m for m in models if m["id"].lower() == mid]
        if exact:
            for m in exact:
                pname = m.get("provider", "")
                pcfg = PROVIDERS.get(pname)
                if pcfg and os.environ.get(pcfg.get("key_env", ""), "").strip():
                    return [(m, model_metrics(m))]
            return [(exact[0], model_metrics(exact[0]))]
        # flexible: provider/model split → match provider + model separately
        if "/" in mid:
            prov_part, model_part = mid.split("/", 1)
            # collect all flexible matches, prefer one with available key
            matches = []
            for m in models:
                if m["id"].lower() == model_part and m.get("provider", "").lower() == prov_part:
                    matches.append(m)
            for m in models:
                if m["id"].lower() == model_part and m not in matches:
                    matches.append(m)
            for m in models:
                if (m["id"].lower() == mid or m["id"].lower().endswith("/" + model_part)) and m not in matches:
                    matches.append(m)
            if matches:
                # prefer provider with configured key
                for m in matches:
                    pname = m.get("provider", "")
                    pcfg = PROVIDERS.get(pname)
                    if pcfg and os.environ.get(pcfg.get("key_env", ""), "").strip():
                        return [(m, model_metrics(m))]
                return [(matches[0], model_metrics(matches[0]))]
        raise RuntimeError(f"model not found: {criteria['model']}")

    min_tps = float(criteria.get("min_tps", 0))
    min_intel = float(criteria.get("min_intel", 0))
    provider = criteria.get("provider")
    mode = criteria.get("mode", "balanced")
    # DEFAULT: free-only routing (no costs!). Set allow_paid=true to include paid.
    allow_paid = bool(criteria.get("allow_paid", False))

    def provider_available(pname: str) -> bool:
        if pname == "openrouter":
            return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
        pcfg = PROVIDERS.get(pname)
        if not pcfg:
            return False
        key_env = pcfg.get("key_env")
        if not key_env:
            return True
        return bool(os.environ.get(key_env, "").strip())

    scored = []
    for m in models:
        if provider and m.get("provider", "").lower() != provider.lower():
            continue
        if m.get("free_status") == "deprecated-not-on-openrouter":
            continue
        if in_cooldown(m["id"]):
            continue  # recently rate-limited, skip
        pname = m.get("provider", "")
        if not provider_available(pname):
            continue
        # FREE-ONLY guard: skip paid models unless explicitly allowed.
        # Free proof = OmniRoute catalog free_type (the trusted source):
        # recurring-*, keyless, one-time with monthly_tokens == 0.
        is_free = (
            m.get("free_status") == "verified-free"
            or str(m.get("id", "")).endswith(":free")
            or m.get("free_type") == "keyless"
            or m.get("free_type") in ("recurring-monthly", "recurring-daily",
                                      "recurring-uncapped", "recurring-credit",
                                      "one-time-initial")
        )
        if not allow_paid and not is_free:
            continue
        met = model_metrics(m)
        tps = met["tps"] or 0
        intel = met["intel"] or 0
        if tps < min_tps:
            continue
        if intel < min_intel:
            continue
        # live uptime bonus: prefer models with high recent uptime
        met["uptime"] = LIVE["uptime"].get(m["id"], 1.0)
        scored.append((m, met))

    if not scored:
        return []

    if mode == "smartest":
        scored.sort(key=lambda x: (x[1]["intel"] or 0, x[1]["tps"] or 0), reverse=True)
    elif mode == "fastest":
        scored.sort(key=lambda x: (x[1]["tps"] or 0, x[1]["intel"] or 0), reverse=True)
    else:
        max_intel = max((s[1]["intel"] or 0) for s in scored) or 1
        max_tps = max((s[1]["tps"] or 0) for s in scored) or 1
        scored.sort(key=lambda x: 0.5 * ((x[1]["intel"] or 0) / max_intel)
                    + 0.5 * ((x[1]["tps"] or 0) / max_tps), reverse=True)

    return scored


# --- HTTP server ----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[http] {self.address_string()} {fmt % args}")

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "models": len(DATA["models"])})
        elif self.path == "/refresh":
            load_data(force=True)
            self._send_json(200, {"status": "refreshed", "models": len(DATA["models"])})
        elif self.path == "/usage":
            # usage-learned stats (real request outcomes, not benchmarks)
            self._send_json(200, {"usage": USAGE})
        elif self.path == "/models":
            # list available models with metrics (the data API)
            out = []
            for m in DATA["models"][:500]:
                met = model_metrics(m)
                out.append({
                    "id": m["id"], "provider": m.get("provider", ""),
                    "free_type": m.get("free_type", ""), "free_status": m.get("free_status", ""),
                    "intel": met["intel"], "tps": met["tps"], "ttft": met["ttft"],
                    "live_uptime": LIVE["uptime"].get(m["id"]),
                    "cooldown": int(COOLDOWN.get(m["id"], 0) - time.time()) if in_cooldown(m["id"]) else 0,
                })
            self._send_json(200, {"models": out})
        elif self.path in ("/v1/models", "/api/v1/models"):
            # OpenAI-format model list (Hermes provider detection)
            ids = ["auto"] + [m["id"] for m in DATA["models"][:300]]
            self._send_json(200, {"object": "list", "data": [{"id": i, "object": "model"} for i in ids]})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self._send_json(404, {"error": "not found"})
            return
        try:
            body = self._read_body()
            resp = route_request(body, stream=False)
            self._send_json(200, resp)
        except urllib.error.HTTPError as e:
            err = e.read().decode()[:500]
            self._send_json(e.code, {"error": err})
        except Exception as e:
            self._send_json(500, {"error": str(e)})


def main() -> int:
    load_data()
    load_usage()  # persistierte Nutzungsdaten + Cooldowns wiederherstellen
    fetch_live_uptime()  # live availability snapshot (10-min cache)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[router] listening on http://{HOST}:{PORT}")
    print(f"[router] endpoint: POST /v1/chat/completions")
    print(f"[router] health:   GET /health")
    print(f"[router] models:   GET /models  (filterable data API)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[router] shutdown")
    return 0


if __name__ == "__main__":
    sys.exit(main())
