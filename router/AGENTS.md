# llm-mini-router — Projektregeln

- **Stdlib only**: Keine Dependencies, kein Framework. http.server + urllib.
- **Sparsam**: Routet an Provider weiter, verbraucht selbst keine Tokens außer für Tests.
- **Keys nur aus Env**: Niemals Keys im Code/Repo. Env-Vars: OPENROUTER_API_KEY, GROQ_API_KEY, ...
- **Data Source**: free-llm-tracker GitHub Pages (latest.json + benchmarks.json), 1h Cache, /refresh zum Neuladen.
- **Routing**: Kriterien im Request-Body unter `router` (mode, min_tps, min_intel, provider, model).
- **Auto-Fallback**: Bei 429/5xx/Fehler nächsten Kandidaten probieren (MAX_FALLBACKS, default 3).
- **Verifikationsregel**: Nach Änderung immer lokalen Start + echten Chat-Completion testen (wie "Hello"-Test).

## Stand (2026-08-22)
- router.py funktioniert end-to-end (direktes Routing an OpenRouter bestätigt)
- Auto-Fallback getestet (3 Kandidaten bei Rate-Limit)
- Nächster Schritt: GitHub-Repo harrytyp/llm-mini-router anlegen (Kolja), push, Hermes-Anbindung
