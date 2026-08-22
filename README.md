# free-llm-tracker

Statischer Tracker für kostenlose LLM-API-Modelle: t/s (gemessen), Intelligence-Score, Provider-Links. Läuft vollautomatisch via GitHub Actions (6h Cron) + GitHub Pages.

## Datenquellen (alle ohne eigene Token-Kosten)

| Quelle | Was | Key |
|---|---|---|
| OpenRouter `/api/v1/models` | Free-Erkennung (`pricing==0`), Kontext, Links | keiner |
| llm-benchmarks.com `/api/processed` | Gemessene t/s + TTFT (30min-Refresh) | keiner |
| Artificial Analysis v2 API | Intelligence Index, t/s für First-Party-Hosts | `ARTIFICIAL_ANALYSIS_API_KEY` (free account, 1000 req/day) |

## Aufbau

```
collector.py   # sammelt + joint die Quellen -> data/latest.json (+ History-Anhang)
build_site.py  # rendert index.html aus data/latest.json
.github/workflows/update.yml  # Cron: collect -> build -> commit -> Pages deploy
```

## AA-Key setzen (optional, aber empfohlen)

GitHub Repo → Settings → Secrets and variables → Actions → New repository secret:
`ARTIFICIAL_ANALYSIS_API_KEY`. Free Account auf artificialanalysis.ai anlegen, Key unter
https://artificialanalysis.ai/account generieren. Ohne Key läuft alles weiter, nur ohne
Intelligence-Spalte.

## Lokal testen

```bash
python3 collector.py && python3 build_site.py
```
