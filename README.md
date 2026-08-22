# free-llm-tracker

**Der einzige automatische Tracker aller免费 LLM-API-Modelle** — mit gemessener
Geschwindigkeit (t/s), Intelligence-Score, Provider-Links und Token-Budget.
Aktualisiert alle 6h via GitHub Actions + GitHub Pages. **Keine Tokens nötig, keine Kosten.**

## Live

https://harrytyp.github.io/free-llm-tracker/

## Was ist das?

Ein reproduzierbarer, automatischer Index aller免费 LLM-Modelle. Jeder Lauf
(alle 6h) fragt dieselben öffentlichen Quellen neu, mergt die Ergebnisse und
stellt eine sortierte, filterbare Tabelle bereit. Neue Modelle, die ein Provider
hinzufügt, erscheinen beim nächsten Lauf automatisch — ohne manuelle Pflege.

**Aktuell erfasst:** 531免费 Modelle · 81 Provider · 63 mit gemessenen t/s · 0 mit Intelligence (Key nötig)

## Warum das nützt

- **Keine manuelle Recherche mehr:** Statt 20 Repos durchsuchen zu mustern, fragt
  der Tracker die kuratierte Free-Liste von OmniRoute + OpenRouters Live-API.
- **t/s ist provider-abhängig** (z.B. `gpt-4o` via OpenRouter vs. direkt bei OpenAI
  unterscheidet sich 2-3×). Der Tracker zeigt pro (Modell, Provider) gemessen.
- **Reproduzierbar:** Jeder Lauf ist determiniert — gleiche Quellen, gleiche Logik,
  gleiche Ausgabe. Geschichte in `data/history.jsonl` nachvollziehbar.

## Datenquellen (alle öffentlich, ohne Key)

| Quelle | Was | Key |
|---|---|---|
| [OmniRoute free-catalog.data.ts](https://github.com/diegosouzapw/OmniRoute/blob/main/open-sse/config/freeModelCatalog.data.ts) | Kuratierte Free-Liste (516 Einträge, gepflegt per 50-Agenten-Studie) | keiner |
| [OpenRouter `/api/v1/models`](https://openrouter.ai/api/v1/models) | Free-Erkennung (`pricing==0`), Kontext, Provider-Links | keiner |
| [llm-benchmarks.com `/api/processed`](https://llm-benchmarks.com) | Gemessene t/s + TTFT (30min-Refresh, ~100 Modell/Provider-Kombis) | keiner |
| [Artificial Analysis v2 API](https://artificialanalysis.ai/api-reference) | Intelligence Index, t/s für First-Party-Hosts | `ARTIFICIAL_ANALYSIS_API_KEY` (free account, 1000 req/day) |

## Aufbau

```
collector.py     # sammelt + joint die Quellen -> data/latest.json (+ history.jsonl)
build_site.py    # rendert index.html aus data/latest.json
build_providers.py # aggregiert Provider-Statistiken -> data/providers.json
.github/workflows/update.yml  # Cron: collect -> build -> commit -> Pages deploy
```

## AA-Key setzen (optional, aber empfohlen)

GitHub Repo → Settings → Secrets and variables → Actions → New repository secret:
`ARTIFICIAL_ANALYSIS_API_KEY`. Free Account auf [artificialanalysis.ai](https://artificialanalysis.ai/account)
anlegen, Key generieren. Ohne Key läuft alles weiter, nur ohne Intelligence-Spalte.

## Lokal testen

```bash
python3 collector.py && python3 build_site.py && python3 build_providers.py
```

## Lizenz

MIT — siehe [LICENSE](LICENSE).