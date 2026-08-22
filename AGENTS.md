# free-llm-tracker — Projektregeln (Revision 2, 2026-08-22)

## Kritik von Kolja (Anlass dieser Revision)
- Tabelle unbrauchbar, Seite hässlich, Werte teils falsch, API-Integrationen nicht sinnvoll.
- t/s-Werte von llm-benchmarks.com sind nur bedingt vertrauenswürdig (60% mit n=1).

## Kernentscheidungen
1. **Eigene t/s-Messung statt fremde Benchmarks als Wahrheit:**
   - `benchmark.py` misst TTFT + t/s direkt an den Free-Endpoints (kostet nichts, Modelle gratis).
   - Mehrere Samples pro (Modell, Provider), Median statt Mean, Ausreißer verwerfen.
   - llm-benchmarks.com bleibt nur als **Fallback-Referenz**, nie als Primärquelle.
2. **Provider-Alias-Map ist GELÖSCHT** — t/s wird immer exakt pro (Modell, Provider) gemessen/gespeichert.
3. **Seite ist ein kompletter Neubau:**
   - Suchfeld, Provider-Filter, sortierbare Spalten, FreeType-Badges, CSV-Export, Dark Theme, mobile-first.
   - Kein Jekyll, keine externen Abhängigkeiten, kein Framework. Nur build_site.py.
4. **AA-API korrekt:** Endpoint `/api/v2/data/llms/models` ist **Pro-only**. Free-Tier reicht nicht.
   - Wenn kein Key: Intelligence-Spalte ehrlich als "nicht verfügbar" markieren, nicht "–".
5. **history.jsonl MUSS funktionieren** (war leer) — Trend-Chart auf der Seite braucht echte Daten.

## Datenqualitätsregeln
- Ein Benchmark-Wert gilt nur mit **n >= 3 Samples**. n=1, n=2 → nicht anzeigen.
- Median über Samples, nicht Mean (robust gegen Ausreißer).
- Provider-Namen IMMER original (openrouter, groq, cerebras, ...), nie aliasen.

## Workflow (unverändert)
- `.github/workflows/update.yml`: collect -> benchmark -> build -> commit -> Pages deploy, alle 6h.
- AA-Key als Secret `ARTIFICIAL_ANALYSIS_API_KEY` (optional, Pro-Tier für vollen Zugriff).
