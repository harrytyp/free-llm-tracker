# free-llm-tracker — Projektregeln (Revision 3, 2026-08-22)

## Architektur
- **Daten** (collector + benchmark → data/, GitHub Pages): `collector.py`, `benchmark.py`, `build_site.py`
- **Router** (`router/`): llm-mini-router — OpenAI-kompatibler Endpoint, Routing nach Kriterien, Auto-Fallback, Load-Aware-Verteilung
- Beides in EINEM Repo harrytyp/free-llm-tracker.

## Messquellen (alle extern, kein Selbst-Messen)
1. **AA Free-API** (`/api/v2/data/llms/models`, Key nötig): Intelligence Index + t/s + TTFT für 610 Modelle. **Genau 1 Call pro Durchgang** (Kolja: sparsam!).
2. **AA Provider-Seiten** (öffentlich): t/s pro Provider pro Modell (Cerebras, Groq, ...).
3. **llm-benchmarks.com Provider-Seiten** (öffentlich): 30-Tage-Messungen pro Provider (deepinfra 128 Modelle, openrouter 282, ...).
4. **OpenRouter Endpoints-API** (Key nötig): Live-Uptime + P50 t/s (30-min-Fenster).

## Datenqualitätsregeln
- t/s/intel = **historische Benchmarks** (30-Tage), NIE als Live-Wert ausgeben.
- Live-Status = OpenRouter `uptime_last_30m` + Cooldown nach 429 (Router).
- Deprecated Modelle werden komplett entfernt (nicht nur markiert).
- AA-Slug-Mapping: dots→dashes, Suffix-Stripping, Prefix-Match.

## Router-Regeln (router/)
- Stdlib only, keine Dependencies.
- Keys nur aus Env (OPENROUTER_API_KEY, GROQ_API_KEY, ...).
- Kriterien im Request-Body unter `router` (mode, min_tps, min_intel, provider, model).
- Auto-Fallback: 429/5xx → nächster Kandidat, Cooldown 10 min.
- Load-Aware: weighted-random aus Top-5 (nicht immer Rank 1 — 100 User würden sonst dasselbe Modell ratelimitieren).
- Verifikation: Nach Änderung lokalen Start + echten Chat-Completion testen.

## Workflow
- `.github/workflows/update.yml`: collect → benchmark (mit AA+OR Secrets) → build → commit → Pages deploy, alle 6h.
- Ohne Secrets: benchmark wird übersprungen, deploy läuft trotzdem.
- Secrets im GitHub-UI setzen: `OPENROUTER_API_KEY`, `ARTIFICIAL_ANALYSIS_API_KEY`.
