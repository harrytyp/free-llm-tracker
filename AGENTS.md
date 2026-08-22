# free-llm-tracker — Projektregeln

- Collector ist idempotent: Läuft auch wenn einzelne Quellen down sind (try/except pro Quelle, Ergebnis trotzdem schreiben).
- Secrets: AA-Key NUR als GitHub Secret `ARTIFICIAL_ANALYSIS_API_KEY`, nie in Code/Repo.
- data/history.jsonl wächst append-only (ein JSON pro Lauf, max. 90 Tage behalten via Prune im Collector).
- Site ist statisch, kein JS-Build-Step. build_site.py rendert aus data/latest.json.
- Verifizierungsregel: Nach jedem Collector-Lauf prüfen dass latest.json > 0 free models hat und t/s-Felder numerisch sind — sonst CI failen lassen (Datenqualität vor grünem Build).
