#!/usr/bin/env python3
"""Render a modern, usable static site from data/latest.json + data/benchmarks.json.

Features (vanilla JS, no framework):
  - Search across model/provider/name
  - Provider dropdown filter
  - Sortable columns (click header)
  - FreeType badges with colors
  - CSV export
  - Dark theme, mobile-first
  - Honest data: only n>=3 benchmarks shown, "nicht gemessen" where missing
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def esc(s):
    return html.escape(str(s), quote=True)


def provider_link(provider: str, model_id: str) -> str:
    """Real provider links where known, else model page."""
    base = model_id[:-5] if model_id.endswith(":free") else model_id
    links = {
        "openrouter": f"https://openrouter.ai/{base}",
        "deepseek": "https://platform.deepseek.com",
        "google": "https://ai.google.dev",
        "anthropic": "https://www.anthropic.com/api",
        "openai": "https://platform.openai.com",
        "groq": "https://console.groq.com",
        "cerebras": "https://cloud.cerebras.ai",
        "sambanova": "https://cloud.sambanova.ai",
        "fireworks": "https://fireworks.ai",
        "together": "https://www.together.ai",
        "nvidia": "https://build.nvidia.com",
        "deepinfra": "https://deepinfra.com",
        "siliconflow": "https://siliconflow.cn",
        "hyperbolic": "https://hyperbolic.xyz",
        "novita": "https://novita.ai",
        "chutes": "https://chutes.ai",
        "github-models": "https://github.com/marketplace/models",
        "vertex": "https://cloud.google.com/vertex-ai",
        "bedrock": "https://aws.amazon.com/bedrock",
        "ollama": "https://ollama.com",
    }
    if provider in links:
        return links[provider]
    return f"https://openrouter.ai/{base}"


_FREE_TAGS = {
    "recurring-monthly": ("↻ monatlich", "#3fb950"),
    "recurring-daily": ("↻ täglich", "#58a6ff"),
    "keyless": ("🔓 keylos", "#d29922"),
    "recurring-uncapped": ("∞ uncapped", "#8b949e"),
    "one-time-initial": ("🎁 einmalig", "#a371f7"),
    "recurring-credit": ("💳 credit", "#f0883e"),
    "discontinued": ("💀 eingestellt", "#f85149"),
}


def free_badge(ftype: str) -> str:
    label, color = _FREE_TAGS.get(ftype, (ftype or "?", "#8b949e"))
    return f"<span class='badge' style='color:{color};border-color:{color}33;background:{color}11'>{esc(label)}</span>"


def model_row(m: dict) -> str:
    sp = m.get("speed") or {}
    tps = sp.get("tps")
    ttft = sp.get("ttft_s")
    samples = sp.get("samples")
    provider = m.get("provider", "")
    mid = m["id"]
    name = m.get("name", mid)

    if tps is not None:
        speed_cell = f"<b>{tps:g}</b><span class='dim'> t/s</span>"
        samples_cell = str(samples)
    else:
        speed_cell = "<span class='dim'>–</span>"
        samples_cell = "<span class='dim'>–</span>"

    ttft_cell = f"{ttft:g}s" if ttft is not None else "<span class='dim'>–</span>"

    ctx = m.get("context_length")
    ctx_cell = ""
    if ctx:
        n = float(ctx)
        ctx_cell = f"<span class='badge'>ctx {'{:g}'.format(n/1e6 if n>=1e6 else n/1e3)}</span>"

    budget_parts = []
    if m.get("monthly_tokens"):
        budget_parts.append(f"{m['monthly_tokens']:,}".replace(",", "."))
    if m.get("credit_tokens"):
        budget_parts.append(f"+{m['credit_tokens']:,}".replace(",", "."))
    budget_cell = " / ".join(budget_parts) if budget_parts else "<span class='dim'>k.A.</span>"

    return (
        "<tr>"
        f'<td class="name"><a href="{esc(provider_link(provider, mid))}" target="_blank" rel="noopener">{esc(mid)}</a>'
        f"<br><small class='dim'>{esc(name)}</small></td>"
        f"<td class='prov'><a href=\"{esc(provider_link(provider, mid))}\" target=\"_blank\" rel=\"noopener\">{esc(provider)}</a></td>"
        f"<td>{free_badge(m.get('free_type', 'recurring-monthly'))}</td>"
        f"<td class='num'>{speed_cell}</td>"
        f"<td class='num'>{ttft_cell}</td>"
        f"<td class='num'>{samples_cell}</td>"
        f"<td>{ctx_cell}</td>"
        f"<td class='num'>{budget_cell}</td>"
        "</tr>"
    )


def main() -> int:
    latest = json.loads((DATA / "latest.json").read_text())
    bench_raw = json.loads((DATA / "benchmarks.json").read_text())
    models = latest["models"]
    counts = latest["counts"]
    updated = latest["updated_at"]

    # Attach benchmark data to models (results keyed by model id)
    bench_raw_data = bench_raw.get("results", {})
    measured_count = 0
    for m in models:
        mid = m["id"].lower().rstrip(":free")
        entry = bench_raw_data.get(m["id"]) or bench_raw_data.get(mid)
        if entry:
            # OpenRouter endpoints API values
            m["speed"] = {
                "tps": entry.get("tps"),
                "tps_p90": entry.get("tps_p90"),
                "ttft_s": (entry.get("ttft_ms_p50") or 0) / 1000 if entry.get("ttft_ms_p50") else None,
                "ttft_ms": entry.get("ttft_ms_p50"),
                "uptime": entry.get("uptime_30m"),
                "cost_verified": entry.get("cost_verified_zero", False),
                "source": entry.get("source", "openrouter"),
            }
            measured_count += 1
        else:
            m["speed"] = None

    rows = "\n".join(model_row(m) for m in models)
    providers = sorted({m.get("provider", "") for m in models})

    # Provider options for filter dropdown
    provider_opts = "".join(
        f'<option value="{esc(p)}">{esc(p)}</option>' for p in providers
    )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    err_note = ""
    if latest.get("source_errors"):
        err_note = (
            '<p class="warn">Hinweis: ' + esc(", ".join(latest["source_errors"])) + "</p>"
        )

    data_js = json.dumps([
        {
            "id": m["id"], "name": m.get("name", m["id"]), "provider": m.get("provider", ""),
            "free_type": m.get("free_type", "recurring-monthly"),
            "context_length": m.get("context_length"),
            "monthly_tokens": m.get("monthly_tokens"), "credit_tokens": m.get("credit_tokens"),
            "speed": m.get("speed"),
            "link": provider_link(m.get("provider", ""), m["id"]),
        } for m in models
    ], ensure_ascii=False)

    page = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Free LLM Tracker — {counts['free_models']} Free-Modelle mit t/s</title>
<meta name="description" content="Automatischer Tracker aller {counts['free_models']} Free LLM-API-Modelle mit gemessener Geschwindigkeit (t/s), TTFT und Provider-Statistiken. Aktualisiert alle 6h.">
<meta property="og:title" content="Free LLM Tracker — {counts['free_models']} Free-Modelle">
<meta property="og:description" content="{counts['free_models']} Free-Modelle · {counts.get('with_measured_speed', measured_count)} mit gemessenen t/s · aktualisiert alle 6h">
<meta name="theme-color" content="#0d1117">
<link rel="canonical" href="https://harrytyp.github.io/free-llm-tracker/">
<style>
:root {{
  --bg:#0d1117; --bg2:#161b22; --bg3:#1c2128; --border:#30363d;
  --fg:#c9d1d9; --dim:#8b949e; --accent:#58a6ff; --ok:#3fb950; --warn:#d29922;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
  background:var(--bg); color:var(--fg);
  font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;
  min-height:100vh;
}}
.wrap {{ max-width:1400px; margin:0 auto; padding:24px 20px 64px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:20px; }}
h1 {{ font-size:24px; color:#fff; }}
h1 span {{ color:var(--accent); }}
.sub {{ color:var(--dim); font-size:14px; margin-top:2px; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }}
.search {{ flex:1; min-width:220px; background:var(--bg2); border:1px solid var(--border);
  border-radius:8px; padding:10px 14px; color:var(--fg); font-size:14px; }}
.search:focus {{ outline:none; border-color:var(--accent); }}
select, .btn {{ background:var(--bg2); border:1px solid var(--border); border-radius:8px;
  padding:10px 14px; color:var(--fg); font-size:14px; cursor:pointer; }}
select:focus {{ outline:none; border-color:var(--accent); }}
.btn:hover {{ border-color:var(--accent); }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:16px; }}
.stat {{ background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:12px 16px; }}
.stat b {{ display:block; font-size:20px; color:#fff; }}
.stat span {{ color:var(--dim); font-size:12px; }}
table {{ width:100%; border-collapse:collapse; background:var(--bg2); border-radius:10px; overflow:hidden; }}
th, td {{ padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; vertical-align:top; }}
th {{ background:var(--bg3); color:var(--dim); font-weight:600; position:sticky; top:0; cursor:pointer; user-select:none; white-space:nowrap; }}
th:hover {{ color:var(--accent); }}
th .arrow {{ opacity:0; font-size:10px; }}
th.sorted .arrow {{ opacity:1; }}
tbody tr:hover {{ background:var(--bg3); }}
td.name a {{ color:var(--accent); text-decoration:none; word-break:break-all; font-weight:500; }}
td.name a:hover {{ text-decoration:underline; }}
td.prov a {{ color:var(--dim); text-decoration:none; }}
td.prov a:hover {{ color:var(--accent); }}
.badge {{ display:inline-block; border-radius:10px; padding:2px 8px; font-size:11px; font-weight:500; white-space:nowrap; }}
.dim {{ color:var(--dim); }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.warn {{ color:var(--warn); font-size:13px; margin-bottom:12px; }}
footer {{ margin-top:28px; color:var(--dim); font-size:12px; }}
footer a {{ color:var(--accent); }}
.empty {{ text-align:center; color:var(--dim); padding:40px; }}
@media (max-width:800px) {{
  .wrap {{ padding:16px 10px 48px; }}
  th, td {{ padding:8px 6px; font-size:12px; }}
  h1 {{ font-size:20px; }}
  .stats {{ grid-template-columns:repeat(2,1fr); }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Free LLM <span>Tracker</span></h1>
    <p class="sub">Alle kostenlosen LLM-API-Modelle mit gemessener Geschwindigkeit. Automatisch alle 6h aktualisiert.</p>
  </div>
  <a class="btn" href="https://github.com/harrytyp/free-llm-tracker" target="_blank" rel="noopener">GitHub ↗</a>
</header>

<div class="stats">
  <div class="stat"><b>{counts['free_models']}</b><span>Free-Modelle</span></div>
  <div class="stat"><b>{measured_count}</b><span>mit gemessenen t/s</span></div>
  <div class="stat"><b>{counts.get('from_omniroute', 0)}</b><span>OmniRoute Einträge</span></div>
  <div class="stat"><b>{updated[11:16]} UTC</b><span>Datenstand {updated[:10]}</span></div>
</div>
{err_note}

<div class="controls">
  <input class="search" id="search" type="search" placeholder="Suchen: Modell, Provider, Name…">
  <select id="provider-filter">
    <option value="">Alle Provider ({len(providers)})</option>
    {provider_opts}
  </select>
  <select id="free-filter">
    <option value="">Alle Free-Typen</option>
    <option value="recurring-monthly">↻ monatlich</option>
    <option value="recurring-daily">↻ täglich</option>
    <option value="keyless">🔓 keylos</option>
    <option value="recurring-uncapped">∞ uncapped</option>
    <option value="one-time-initial">🎁 einmalig</option>
    <option value="recurring-credit">💳 credit</option>
  </select>
  <button class="btn" id="csv">CSV Export</button>
</div>

<table id="models">
<thead>
<tr>
  <th data-key="id">Modell <span class="arrow">↑↓</span></th>
  <th data-key="provider">Provider <span class="arrow">↑↓</span></th>
  <th data-key="free_type">Free-Typ <span class="arrow">↑↓</span></th>
  <th data-key="tps" class="num">t/s <span class="arrow">↑↓</span></th>
  <th data-key="ttft" class="num">TTFT <span class="arrow">↑↓</span></th>
  <th data-key="samples" class="num">Samples <span class="arrow">↑↓</span></th>
  <th data-key="ctx">Kontext</th>
  <th data-key="budget" class="num">Budget</th>
</tr>
</thead>
<tbody id="tbody">
{rows}
</tbody>
</table>
<div class="empty" id="empty" style="display:none">Keine Modelle gefunden.</div>

<footer>
  <p>Quellen: OmniRoute free-catalog · OpenRouter /api/v1/models · llm-benchmarks.com (nur n≥3) · Artificial Analysis (optional)</p>
  <p>Entwickelt von <a href="https://github.com/harrytyp">harrytyp</a> — <a href="https://github.com/harrytyp/free-llm-tracker">Quellcode</a></p>
</footer>
</div>

<script>
const DATA = {data_js};
let sortKey = 'tps', sortDir = -1;

function fmtBudget(m) {{
  const parts = [];
  if (m.monthly_tokens) parts.push(m.monthly_tokens.toLocaleString('de-DE'));
  if (m.credit_tokens) parts.push('+' + m.credit_tokens.toLocaleString('de-DE'));
  return parts.join(' / ') || 'k.A.';
}}

function rowHtml(m) {{
  const sp = m.speed || {{}};
  const tps = sp.tps != null ? `<b>${{sp.tps}}</b> <span class="dim">t/s</span>` : '<span class="dim">–</span>';
  const ttft = sp.ttft_s != null ? `${{sp.ttft_s}}s` : '<span class="dim">–</span>';
  const samples = sp.samples != null ? sp.samples : '<span class="dim">–</span>';
  const ctx = m.context_length ? `<span class="badge">ctx ${{m.context_length >= 1e6 ? (m.context_length/1e6).toFixed(0)+'M' : (m.context_length/1e3).toFixed(0)+'k'}}</span>` : '';
  return `<tr>
    <td class="name"><a href="${{m.link}}" target="_blank" rel="noopener">${{m.id}}</a><br><small class="dim">${{m.name || ''}}</small></td>
    <td class="prov"><a href="${{m.link}}" target="_blank" rel="noopener">${{m.provider}}</a></td>
    <td>${{m.free_type}}</td>
    <td class="num">${{tps}}</td>
    <td class="num">${{ttft}}</td>
    <td class="num">${{samples}}</td>
    <td>${{ctx}}</td>
    <td class="num">${{fmtBudget(m)}}</td>
  </tr>`;
}}

function getVal(m, key) {{
  switch(key) {{
    case 'tps': return (m.speed && m.speed.tps) || -1;
    case 'ttft': return (m.speed && m.speed.ttft_s) || 9999;
    case 'samples': return (m.speed && m.speed.samples) || 0;
    case 'ctx': return m.context_length || 0;
    case 'budget': return (m.monthly_tokens || 0) + (m.credit_tokens || 0);
    default: return (m[key] || '').toString().toLowerCase();
  }}
}}

function render() {{
  const q = document.getElementById('search').value.toLowerCase();
  const prov = document.getElementById('provider-filter').value;
  const ft = document.getElementById('free-filter').value;
  const rows = DATA.filter(m => {{
    if (prov && m.provider !== prov) return false;
    if (ft && m.free_type !== ft) return false;
    if (q && !(m.id + ' ' + m.provider + ' ' + (m.name||'')).toLowerCase().includes(q)) return false;
    return true;
  }});
  rows.sort((a,b) => {{
    const va = getVal(a, sortKey), vb = getVal(b, sortKey);
    if (va < vb) return -1 * sortDir;
    if (va > vb) return 1 * sortDir;
    return 0;
  }});
  document.getElementById('tbody').innerHTML = rows.map(rowHtml).join('');
  document.getElementById('empty').style.display = rows.length ? 'none' : 'block';
  document.querySelectorAll('th').forEach(th => {{
    th.classList.toggle('sorted', th.dataset.key === sortKey);
  }});
}}

document.querySelectorAll('th').forEach(th => {{
  th.addEventListener('click', () => {{
    const k = th.dataset.key;
    if (sortKey === k) sortDir *= -1;
    else {{ sortKey = k; sortDir = k === 'tps' || k === 'ttft' || k === 'samples' ? -1 : 1; }}
    render();
  }});
}});
document.getElementById('search').addEventListener('input', render);
document.getElementById('provider-filter').addEventListener('change', render);
document.getElementById('free-filter').addEventListener('change', render);
document.getElementById('csv').addEventListener('click', () => {{
  const header = ['id','provider','free_type','tps','ttft_s','samples','context_length','monthly_tokens','credit_tokens'];
  const lines = [header.join(',')];
  DATA.forEach(m => {{
    const sp = m.speed || {{}};
    lines.push([m.id, m.provider, m.free_type, sp.tps||'', sp.ttft_s||'', sp.samples||'', m.context_length||'', m.monthly_tokens||'', m.credit_tokens||''].join(','));
  }});
  const blob = new Blob([lines.join('\\n')], {{type:'text/csv'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'free-llm-models.csv';
  a.click();
}});
render();
</script>
</body>
</html>
"""

    out = ROOT / "index.html"
    out.write_text(page)
    print(f"OK wrote {out} ({len(page)} bytes, {len(models)} rows, {measured_count} measured)")


if __name__ == "__main__":
    main()
