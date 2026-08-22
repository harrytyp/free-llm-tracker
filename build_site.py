#!/usr/bin/env python3
"""Render a static index.html from data/latest.json. No build deps, no JS framework."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def fmt_num(x, suffix=""):
    if x is None:
        return "<span class='dim'>–</span>"
    if isinstance(x, float):
        return f"{x:g}{suffix}"
    return f"{x}{suffix}"


def esc(s):
    return html.escape(str(s), quote=True)


def provider_link(provider: str, model_id: str) -> str:
    """Deep link to the provider's page for this model."""
    base = model_id[:-5] if model_id.endswith(":free") else model_id
    if provider == "openrouter":
        return f"https://openrouter.ai/{base}"
    if provider in ("deepseek",):
        return "https://api.deepseek.com"
    if provider == "google":
        return "https://ai.google.dev"
    if provider == "anthropic":
        return "https://anthropic.com"
    if provider == "openai":
        return "https://platform.openai.com"
    if provider == "zai-org" or provider == "zai":
        return "https://www.zhipu.ai"
    # default: search the provider name
    return f"https://www.google.com/search?q={provider}+free+api"


# FreeType badges
_FREE_TAGS = {
    "recurring-monthly": "↻ monatlich",
    "recurring-daily": "↻ täglich",
    "keyless": "🔓 keylos",
    "recurring-uncapped": "∞ uncapped",
    "one-time-initial": "🎁 einmalig",
    "recurring-credit": "💳 credit",
    "discontinued": "💀 eingestellt",
}


def free_badge(ftype: str) -> str:
    label = _FREE_TAGS.get(ftype, ftype or "?")
    cls = "badge-free"
    return f"<span class='badge {cls}'>{esc(label)}</span>"


def ctx_badge(ctx) -> str:
    if not ctx:
        return ""
    n = float(ctx)
    if n >= 1_000_000:
        txt = f"{n/1e6:.0f}M"
    elif n >= 1000:
        txt = f"{n/1e3:.0f}k"
    else:
        txt = str(int(n))
    return f"<span class='badge'>ctx {txt}</span>"


def model_row(m: dict) -> str:
    sp = m.get("speed") or {}
    it = m.get("intelligence") or {}

    tps = sp.get("tps_mean")
    gen_tps = sp.get("gen_tps_mean")
    ttft = sp.get("ttft_s")
    samples = sp.get("samples")
    intel = it.get("intelligence_index")

    if tps:
        speed_cell = f"<b>{tps:g}</b> <span class='dim'>t/s</span>"
    else:
        speed_cell = "<span class='dim'>nicht gemessen</span>"
    gen_cell = fmt_num(gen_tps, " t/s") if gen_tps else "<span class='dim'>–</span>"
    ttft_cell = fmt_num(ttft, "s") if ttft else "<span class='dim'>–</span>"
    samples_cell = fmt_num(samples) if samples else "<span class='dim'>–</span>"
    intel_cell = f"<b>{intel:g}</b>" if intel else "<span class='dim'>–</span>"

    ctx = m.get("context_length")
    ctx_cell = ctx_badge(ctx)

    badges = (free_badge(m.get("free_type", "recurring-monthly"))
              + " " + ctx_cell).strip()

    mt = fmt_num(m.get("monthly_tokens"), "k") if m.get("monthly_tokens") else None
    ct = fmt_num(m.get("credit_tokens"), "k") if m.get("credit_tokens") else None

    budget_parts = [p for p in (f"monat {mt}" if mt else None, f"credit {ct}" if ct else None) if p]
    budget_cell = "<span class='dim'>" + "/".join(budget_parts) + "</span>" if budget_parts else "<span class='dim'>k.A.</span>"

    provider = esc(m.get("provider", ""))

    return (
        "<tr>"
        f'<td class="name"><a href="{esc(provider_link(m.get("provider",""), m["id"]))}">{esc(m["id"])}</a>'
        f"<br><small class='dim'>{esc(m.get('name',''))}</small><br>"
        f"{badges}</td>"
        f"<td><small>{provider}</small><br>{budget_cell}</td>"
        f"<td>{speed_cell}</td>"
        f"<td>{gen_cell}</td>"
        f"<td>{ttft_cell}</td>"
        f"<td>{samples_cell}</td>"
        f"<td>{intel_cell}</td>"
        f"</tr>"
    )


def main() -> int:
    latest = json.loads((ROOT / "data" / "latest.json").read_text())
    models = latest["models"]
    counts = latest["counts"]
    updated = latest["updated_at"]
    sources = latest["sources"]

    measured = [m for m in models if (m.get("speed") or {}).get("tps_mean")]
    rows = "\n".join(model_row(m) for m in models)

    # trend sparkline data (last 30 runs, free count + avg measured tps)
    hist_path = ROOT / "data" / "history.jsonl"
    trend_js = "[]"
    if hist_path.exists():
        pts = []
        for line in hist_path.read_text().splitlines()[-30:]:
            try:
                h = json.loads(line)
                speeds = [v["tps"] for v in (h.get("speeds") or {}).values() if v.get("tps")]
                pts.append({
                    "ts": h["ts"],
                    "free": h.get("counts", {}).get("free_models"),
                    "avg_tps": round(sum(speeds) / len(speeds), 2) if speeds else None,
                    "measured": len(speeds),
                })
            except Exception:
                continue
        trend_js = json.dumps(pts)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    err_note = ""
    if latest.get("source_errors"):
        err_note = (
            '<p class="warn">Hinweis: einzelne Quellen hatten Fehler beim letzten Lauf: '
            + esc(", ".join(latest["source_errors"])) + "</p>"
        )

    sources_html = (
        "<tr><td>OmniRoute free-catalog</td><td><a href='"
        + esc(sources.get("omni_free_catalog", "")) + "'>raw data.ts</a></td></tr>"
        "<tr><td>OpenRouter API (free-by-pricing)</td><td><a href='https://openrouter.ai/models?max_price=0'>openrouter.ai</a></td></tr>"
        "<tr><td>Gemessene t/s</td><td><a href='https://llm-benchmarks.com'>llm-benchmarks.com</a> (öffentlich, 30min-Refresh)</td></tr>"
        "<tr><td>Intelligence Index</td><td><a href='https://artificialanalysis.ai'>artificialanalysis.ai</a> (free Key nötig)</td></tr>"
    )

    page = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Free LLM Tracker</title>
<style>
  :root {{ --bg:#0d1117; --fg:#c9d1d9; --dim:#8b949e; --accent:#58a6ff; --ok:#3fb950; --warn:#d29922; }}
  * {{ box-sizing:border-box; }}
  body {{ background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;
         max-width:1280px; margin:0 auto; padding:24px 16px 64px; }}
  h1 {{ font-size:26px; margin:0 0 4px; }}
  h2 {{ font-size:20px; margin:24px 0 10px; }}
  .sub {{ color:var(--dim); margin:0 0 20px; }}
  .stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .stat {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 16px; min-width:110px; }}
  .stat b {{ display:block; font-size:22px; color:var(--accent); }}
  .stat span {{ color:var(--dim); font-size:13px; }}
  table {{ border-collapse:collapse; width:100%; background:#161b22; border-radius:8px; overflow:hidden; }}
  th, td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #21262d; font-size:14px; vertical-align:top; }}
  th {{ background:#1c2128; color:var(--dim); font-weight:600; position:sticky; top:0; }}
  tr:last-child td {{ border-bottom:none; }}
  td.name a {{ color:var(--accent); text-decoration:none; word-break:break-all; }}
  td.name a:hover {{ text-decoration:underline; }}
  .badge {{ display:inline-block; background:#21262d; color:var(--dim); border-radius:10px;
            padding:1px 8px; font-size:11px; margin-right:4px; }}
  .badge-free {{ color:#ffd700; }}
  td small {{ font-size:12px; }}
  .dim {{ color:var(--dim); }}
  .warn {{ color:var(--warn); }}
  .sources td {{ padding:6px 12px; }}
  footer {{ margin-top:28px; color:var(--dim); font-size:13px; }}
  footer a {{ color:var(--accent); }}
  @media (max-width:800px) {{
    table {{ font-size:13px; }}
    td, th {{ padding:8px; }}
  }}
</style>
</head>
<body>
<h1>Free LLM Tracker</h1>
<p class="sub">Alle kostenlosen LLM-API-Modelle — mit gemessener Geschwindigkeit (t/s), Intelligence-Score und Token-Budget.
Automatisch aktualisiert alle 6h via GitHub Actions. Keine Tokens werden verbraucht.</p>

<div class="stats">
  <div class="stat"><b>{counts['free_models']}</b><span>Free-Modelle</span></div>
  <div class="stat"><b>{counts['with_measured_speed']}</b><span>mit gemessenen t/s</span></div>
  <div class="stat"><b>{counts['with_intelligence']}</b><span>mit Intelligence</span></div>
  <div class="stat"><b>{counts.get('from_omniroute',0)}</b><span>OmniRoute Einträge</span></div>
  <div class="stat"><b>{updated[11:16]} UTC</b><span>Datenstand {updated[:10]}</span></div>
</div>
{err_note}
<table>
<thead>
<tr>
  <th>Modell / Provider</th><th>Provider / Budget</th><th>t/s (Stream)</th><th>t/s (generiert)</th>
  <th>TTFT</th><th>Samples</th><th>Intelligence</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>

<h2>Datenquellen</h2>
<table class="sources">
<thead><tr><th>Quelle</th><th>Link</th></tr></thead>
<tbody>
{sources_html}
</tbody>
</table>

<footer>
<p>Dieser Tracker ersetzt manuelle Recherche. Er sammelt die kuratierte Free-Liste von OmniRoute (523 Einträge, gepflegt per 50-Agenten-Studie), OpenRouters Public-API (Free-by-Pricing) und merged sie mit gemessenen Geschwindigkeitswerten von llm-benchmarks.com. Sobald ein Modell hier fehlt, wird es beim nächsten Lauf automatisch wieder aufgenommen.</p>
<p>Entwickelt von <a href="https://github.com/harrytyp">harrytyp</a> — <a href="https://github.com/harrytyp/free-llm-tracker">Quellcode auf GitHub</a></p>
</footer>
<script id="trend-data" type="application/json">{trend_js}</script>
</body>
</html>
"""

    out = ROOT / "index.html"
    out.write_text(page)
    print(f"OK wrote {out} ({len(page)} bytes, {len(models)} rows)")


if __name__ == "__main__":
    main()
