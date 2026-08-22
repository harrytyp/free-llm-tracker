# llm-mini-router

**Super lightweight auto-routing LLM gateway** — ONE OpenAI-compatible endpoint
for all your free models. Picks the best model per criteria (intelligence, speed),
streams to the provider, auto-falls back when one is rate-limited.

Runtime: **Python stdlib only** (`http.server`, `urllib`). No deps, no framework,
~400 lines. Runs as a single process.

## How it works

```
Your tools (Hermes, Claude Code, Cursor...)
        │  POST /v1/chat/completions   (OpenAI format)
        ▼
┌─────────────────────────────┐
│  llm-mini-router (:8080)    │
│  - picks best model per     │
│    criteria (from tracker   │
│    data: intel, tps, ctx)   │
│  - auto-fallback on 429/5xx │
└─────────────────────────────┘
        │  streams to chosen provider
        ▼
   OpenRouter / Groq / Cerebras / DeepInfra / ...
```

## Quick start

```bash
# 1. Set provider keys
export OPENROUTER_API_KEY="sk-or-..."
# add more providers as you get keys:
export GROQ_API_KEY="..."
export CEREBRAS_API_KEY="..."

# 2. Start
python3 router.py
# → listening on http://127.0.0.1:8080
```

## Routing criteria (in the request body)

```json
{
  "model": "auto",
  "messages": [{"role": "user", "content": "..."}],
  "router": {
    "mode": "smartest",        // smartest | fastest | balanced (default)
    "min_tps": 50,             // only models with >= 50 t/s
    "min_intel": 40,           // only models with intelligence >= 40
    "provider": "groq"         // optional: restrict to one provider
  }
}
```

Examples:
- `{"mode": "smartest"}` — the most intelligent model available
- `{"mode": "fastest", "min_intel": 30}` — fastest model with decent intelligence
- `{"router": {"model": "poolside/laguna-s-2.1:free"}}` — exact model override

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/v1/chat/completions` | OpenAI-compatible chat (routed) |
| GET | `/health` | Liveness + model count |
| GET | `/models` | All models with intel/tps/ttft (the data API) |
| GET | `/refresh` | Reload tracker data now |

## Data source

Pulls `latest.json` + `benchmarks.json` from the
[free-llm-tracker](https://github.com/harrytyp/free-llm-tracker) GitHub Pages
(static, no API keys needed). Refreshed every hour or via `/refresh`.

## Config (env vars)

| Var | Default | Purpose |
|---|---|---|
| `MINI_ROUTER_PORT` | 8080 | Listen port |
| `MINI_ROUTER_HOST` | 127.0.0.1 | Bind host (localhost = safe) |
| `MINI_ROUTER_MAX_FALLBACKS` | 3 | Candidates to try on failure |
| `MINI_ROUTER_CACHE_TTL` | 3600 | Data cache TTL (seconds) |
| `TRACKER_DATA_URL` | harrytyp pages | Override tracker data URL |
| `OPENROUTER_API_KEY` | — | OpenRouter key (needed for OR models) |
| `GROQ_API_KEY` | — | Groq key (enables Groq models) |
| `CEREBRAS_API_KEY` | — | Cerebras key |
| `DEEPINFRA_API_KEY` | — | DeepInfra key |
| `NVIDIA_API_KEY` | — | NVIDIA key |

## 🔑 Keys besorgen (Kolja) — Free-Tiers, keine Kreditkarte

Der Router routet zu jedem Provider, dessen Key gesetzt ist. Je mehr Keys, desto
mehr Modelle + bessere Auto-Verteilung (verschiedene Rate-Limits = mehr Last).

| Provider | Free-Modelle (Beispiele) | Limit | Key holen bei |
|---|---|---|---|
| **Groq** | llama-3.3-70b, qwen3-32b, gpt-oss-120b | 14.400 req/day, 6.000 TPM | console.groq.com |
| **Cerebras** | gpt-oss-120b, glm-4.7 | ~30.000 TPM | cloud.cerebras.ai |
| **Google AI Studio** | gemini-flash (bestes free closed) | free quota | aistudio.google.com |
| **GitHub Models** | GPT, Llama, Mix | rate limits | github.com/settings/tokens |
| **Mistral** | magistral, devstral | ~50.000 TPM | console.mistral.ai |
| **DeepInfra** | viele Open-Modelle | free tier | deepinfra.com |
| **NVIDIA** | nemotron, llama | free tier | build.nvidia.com |
| **Cloudflare** | viele | 10.000 Neurons/Tag | dash.cloudflare.com |
| **Together** | llama, qwen | free tier | together.ai |
| **OpenRouter** | 22 Free-Modelle | 20 req/min | openrouter.ai |

**Key setzen:** `export GROQ_API_KEY="..."` vor dem Router-Start (oder in `.env`).

> **Warum keine keyless Provider?** Die 17 "keyless" Provider in der OmniRoute-Liste
> (puter, blackbox, agy, duckduckgo-web, qwen-web, pollinations...) sind Web-Frontends
> ohne OpenAI-kompatible API — sie sind Chat-Webseiten, keine Dienste. Der Router
> kann nur echte API-Endpoints anbinden.

## Connect Hermes

Hermes → Custom endpoint (laut offizieller Doku):

```bash
hermes model
# Select "Custom endpoint (self-hosted / VLLM / etc.)"
# Enter URL: http://127.0.0.1:8080/v1
# Skip API key (or any dummy — the router uses its own provider keys)
# Enter model name: auto   ← the router picks the best model per criteria
```

In `config.yaml` landen dann:

```yaml
model:
  default: auto
  provider: custom
  base_url: http://127.0.0.1:8080/v1
  api_key: dummy   # router uses its own keys
```

Der Router ist OpenAI-kompatibel, also kann Hermes ihn wie jeden OpenAI-Endpoint
nutzen. `model: auto` = der Router entscheidet (Kriterien aus `router`-Feld im
Request, oder Default balanced).

## Why not OmniRoute/9router?

They're great but heavy (Node monoliths, dashboards, MCP servers). This is
~400 lines of stdlib Python: one endpoint, your data, your criteria, no bloat.
