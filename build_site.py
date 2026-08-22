#!/usr/bin/env python3
"""Render the Free LLM Tracker using the Sentry design system (data-dense dashboard).

Per Kolja: cards are wrong for large lists; needs a real filterable TABLE
with mobile support. Sentry = dark data-dense dashboard aesthetic.
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
    base = model_id[:-5] if model_id.endswith(":free") else model_id
    links = {
        "openrouter": f"https://openrouter.ai/{base}",
        "deepseek": "https://platform.deepseek.com", "google": "https://ai.google.dev",
        "anthropic": "https://www.anthropic.com/api", "openai": "https://platform.openai.com",
        "groq": "https://console.groq.com", "cerebras": "https://cloud.cerebras.ai",
        "sambanova": "https://cloud.sambanova.ai", "fireworks": "https://fireworks.ai",
        "together": "https://www.together.ai", "nvidia": "https://build.nvidia.com",
        "deepinfra": "https://deepinfra.com", "siliconflow": "https://siliconflow.cn",
        "hyperbolic": "https://hyperbolic.xyz", "novita": "https://novita.ai",
        "chutes": "https://chutes.ai", "github-models": "https://github.com/marketplace/models",
        "vertex": "https://cloud.google.com/vertex-ai", "bedrock": "https://aws.amazon.com/bedrock",
        "ollama": "https://ollama.com", "puter": "https://puter.com",
        "pollinations": "https://pollinations.ai", "huggingchat": "https://huggingface.co/chat",
        "mistral": "https://mistral.ai", "cohere": "https://cohere.com",
    }
    return links.get(provider, f"https://openrouter.ai/{base}")


def provider_link_plain(provider: str) -> str:
    links = {
        "openrouter": "https://openrouter.ai", "deepseek": "https://platform.deepseek.com",
        "google": "https://ai.google.dev", "anthropic": "https://www.anthropic.com/api",
        "openai": "https://platform.openai.com", "groq": "https://console.groq.com",
        "cerebras": "https://cloud.cerebras.ai", "sambanova": "https://cloud.sambanova.ai",
        "fireworks": "https://fireworks.ai", "together": "https://www.together.ai",
        "nvidia": "https://build.nvidia.com", "deepinfra": "https://deepinfra.com",
        "siliconflow": "https://siliconflow.cn", "hyperbolic": "https://hyperbolic.xyz",
        "novita": "https://novita.ai", "chutes": "https://chutes.ai",
        "github-models": "https://github.com/marketplace/models",
        "vertex": "https://cloud.google.com/vertex-ai", "bedrock": "https://aws.amazon.com/bedrock",
        "ollama": "https://ollama.com", "puter": "https://puter.com",
        "pollinations": "https://pollinations.ai", "huggingchat": "https://huggingface.co/chat",
        "mistral": "https://mistral.ai", "cohere": "https://cohere.com",
    }
    return links.get(provider, f"https://www.google.com/search?q={provider}+AI+API")


_FREE_TAGS = {
    "recurring-monthly": ("monatlich", "#c2ef4e"),
    "recurring-daily": ("täglich", "#6a5fc1"),
    "keyless": ("keylos", "#d29922"),
    "recurring-uncapped": ("uncapped", "#e5e7eb"),
    "one-time-initial": ("einmalig", "#fa7faa"),
    "recurring-credit": ("credit", "#ffb287"),
}

_STATUS = {
    "verified-free": ("✓ verifiziert", "#c2ef4e"),
    "unverified": ("❓ unverifiziert", "#d29922"),
}


def row_html(m: dict) -> str:
    sp = m.get("speed") or {}
    tps = sp.get("tps")
    ttft = sp.get("ttft_s")
    prov = m.get("provider", "")
    mid = m["id"]
    intel = m.get("intel") or {}

    if tps is not None:
        tps_cell = f'<td class="num tps"><b>{tps:g}</b></td>'
    else:
        tps_cell = '<td class="num dim">–</td>'
    ttft_cell = f'<td class="num">{ttft:g}s</td>' if ttft is not None else '<td class="num dim">–</td>'

    ii = intel.get("intelligence_index")
    if ii is not None:
        # color by score: <30 red, 30-50 yellow, 50-70 green, >70 lime
        color = "#f85149" if ii < 30 else "#d29922" if ii < 50 else "#3fb950" if ii < 70 else "#c2ef4e"
        intel_cell = f'<td class="num intel"><b style="color:{color}">{ii:g}</b></td>'
    else:
        intel_cell = '<td class="num dim">–</td>'

    ftype = _FREE_TAGS.get(m.get("free_type", ""), (m.get("free_type", "?"), "#e5e7eb"))
    status = _STATUS.get(m.get("free_status", "unverified"), ("❓", "#d29922"))

    prov_chips = ""
    if sp.get("providers"):
        tops = sp["providers"][:2]
        prov_chips = '<span class="chips">' + "".join(
            f'<span class="chip">{esc(p["provider"])} <b>{p["tps"]:g}</b></span>'
            for p in tops if p.get("tps")) + '</span>'

    ctx = m.get("context_length")
    ctx_cell = ""
    if ctx:
        n = float(ctx)
        ctx_cell = f'<td class="num">{n/1e6:.1f}M</td>' if n >= 1e6 else f'<td class="num">{n/1e3:.0f}k</td>'
    else:
        ctx_cell = '<td class="num dim">–</td>'

    budget = ""
    if m.get("monthly_tokens") or m.get("credit_tokens"):
        parts = []
        if m.get("monthly_tokens"):
            parts.append(f'{m["monthly_tokens"]:,}'.replace(",", "."))
        if m.get("credit_tokens"):
            parts.append(f'+{m["credit_tokens"]:,}'.replace(",", "."))
        budget = " / ".join(parts)

    return f"""<tr class="mrow" data-id="{esc(mid.lower())}" data-provider="{esc(prov.lower())}" data-ftype="{esc(m.get('free_type',''))}" data-status="{esc(m.get('free_status','unverified'))}" data-tps="{tps if tps is not None else ''}" data-intel="{ii if ii is not None else ''}">
  <td class="model"><a href="{esc(provider_link(prov, mid))}" target="_blank" rel="noopener">{esc(mid)}</a>{prov_chips}</td>
  <td><a class="prov-link" href="{esc(provider_link_plain(prov))}" target="_blank" rel="noopener">{esc(prov)}</a></td>
  <td><span class="tag" style="color:{ftype[1]}">{esc(ftype[0])}</span></td>
  <td><span class="tag" style="color:{status[1]}">{esc(status[0])}</span></td>
  {intel_cell}
  {tps_cell}
  {ttft_cell}
  {ctx_cell}
  <td class="num dim">{budget}</td>
</tr>"""


def main() -> int:
    latest = json.loads((DATA / "latest.json").read_text())
    bench_raw = json.loads((DATA / "benchmarks.json").read_text())
    models = latest["models"]
    counts = latest["counts"]
    updated = latest["updated_at"]

    bench_raw_data = bench_raw.get("results", {})
    llmbench = (bench_raw_data.get("__llmbench") or {}).get("providers", {}) if bench_raw_data.get("__llmbench") else {}
    aa_data = (bench_raw_data.get("__aa") or {}).get("models", {}) if bench_raw_data.get("__aa") else {}

    def aa_slug_for(model_id: str) -> str | None:
        mid = model_id.lower().rstrip(":free").split("/")[-1]
        if mid in aa_data:
            return mid
        slug = mid.replace(".", "-")
        if slug in aa_data:
            return slug
        for aas in aa_data:
            if mid.startswith(aas) or aas.startswith(mid):
                return aas
        return None

    for m in models:
        mid = m["id"].lower().rstrip(":free")
        entry = bench_raw_data.get(m["id"]) or bench_raw_data.get(mid)
        # AA intelligence
        aaslug = aa_slug_for(m["id"])
        intel = None
        if aaslug:
            intel = {
                "intelligence_index": aa_data[aaslug].get("intelligence_index"),
                "coding_index": aa_data[aaslug].get("coding_index"),
                "mmlu_pro": aa_data[aaslug].get("mmlu_pro"),
                "gpqa": aa_data[aaslug].get("gpqa"),
                "tps": aa_data[aaslug].get("tps"),
                "ttft_s": aa_data[aaslug].get("ttft_s"),
                "price": aa_data[aaslug].get("price_1m_blended"),
            }
        m["intel"] = intel
        if entry:
            if entry.get("providers"):
                provs = sorted(entry["providers"], key=lambda p: p.get("tps") or 0, reverse=True)
                m["speed"] = {"tps": provs[0].get("tps"), "ttft_s": provs[0].get("ttft_s"), "providers": provs, "source": "aa"}
            elif entry.get("tps") is not None:
                m["speed"] = {
                    "tps": entry.get("tps"),
                    "ttft_s": (entry.get("ttft_ms_p50") or 0) / 1000 if entry.get("ttft_ms_p50") else None,
                    "source": "openrouter",
                }
            else:
                m["speed"] = None
        else:
            m["speed"] = None
        if not (m["speed"] or {}).get("tps"):
            base = mid.split("/")[-1].replace(".", "-").replace("_", "-")
            for key, val in llmbench.items():
                if base in key or key in base:
                    m["speed"] = {"tps": val.get("tps"),
                                  "ttft_s": (val.get("ttft_ms") or 0) / 1000 if val.get("ttft_ms") else None,
                                  "source": f"llmbench-{val.get('provider')}"}
                    break

    # Sort: measured first, then tps desc
    models.sort(key=lambda x: (0 if (x.get("speed") or {}).get("tps") else 1,
                               -(x["speed"]["tps"] if (x.get("speed") or {}).get("tps") else 0),
                               x["id"]))

    rows = "\n".join(row_html(m) for m in models)
    providers = sorted({m.get("provider", "") for m in models})
    provider_opts = "".join(f'<option value="{esc(p.lower())}">{esc(p)}</option>' for p in providers)

    total_measured = sum(1 for m in models if (m.get("speed") or {}).get("tps"))
    verified = sum(1 for m in models if m.get("free_status") == "verified-free")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Free LLM Tracker — {counts['free_models']} Free-Modelle</title>
<meta name="description" content="Alle Free LLM-API-Modelle: gemessene t/s, TTFT, Kontext, Provider. Filterbar, sortierbar, mobil. Automatisch aktualisiert.">
<link href="https://fonts.googleapis.com/css2?family=Rubik:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {{
  --bg:#1f1633; --bg2:#150f23; --bg3:#2a2145; --border:#362d59;
  --fg:#ffffff; --fg2:#e5e7eb; --dim:#9a8fb8; --accent:#6a5fc1;
  --lime:#c2ef4e; --pink:#fa7faa; --coral:#ffb287; --warn:#d29922;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--fg); font-family:'Rubik',system-ui,sans-serif; font-size:15px; line-height:1.5; }}
.wrap {{ max-width:1400px; margin:0 auto; padding:24px 20px 60px; }}
header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:16px; flex-wrap:wrap; margin-bottom:20px; }}
h1 {{ font-size:26px; font-weight:600; }}
h1 span {{ color:var(--lime); }}
.sub {{ color:var(--dim); font-size:13px; margin-top:2px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(130px,1fr)); gap:10px; margin-bottom:18px; }}
.stat {{ background:var(--bg3); border:1px solid var(--border); border-radius:10px; padding:12px 14px; }}
.stat b {{ display:block; font-size:22px; font-weight:600; }}
.stat span {{ color:var(--dim); font-size:12px; text-transform:uppercase; letter-spacing:0.2px; }}
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:14px; position:sticky; top:0; background:var(--bg); padding:10px 0; z-index:10; border-bottom:1px solid var(--border); }}
.search {{ flex:1; min-width:200px; background:var(--bg3); border:1px solid var(--border); border-radius:8px; padding:10px 14px; color:var(--fg); font-family:inherit; font-size:14px; }}
.search:focus, select:focus {{ outline:none; border-color:var(--accent); }}
select {{ background:var(--bg3); border:1px solid var(--border); border-radius:8px; padding:10px 12px; color:var(--fg); font-family:inherit; font-size:13px; cursor:pointer; }}
.btn {{ background:var(--accent); border:none; border-radius:8px; padding:10px 16px; color:#fff; font-family:inherit; font-size:13px; font-weight:600; text-transform:uppercase; letter-spacing:0.2px; cursor:pointer; }}
.btn:hover {{ background:#7b6fd4; }}
.table-wrap {{ overflow-x:auto; border-radius:10px; border:1px solid var(--border); background:var(--bg2); }}
table {{ width:100%; border-collapse:collapse; min-width:820px; }}
th {{ background:var(--bg3); color:var(--dim); font-size:12px; text-transform:uppercase; letter-spacing:0.3px; font-weight:600; padding:12px 14px; text-align:left; cursor:pointer; user-select:none; white-space:nowrap; }}
th:hover {{ color:var(--lime); }}
th .arr {{ font-size:9px; opacity:0; }}
th.sorted .arr {{ opacity:1; color:var(--lime); }}
td {{ padding:10px 14px; border-top:1px solid var(--border); font-size:13.5px; vertical-align:middle; }}
tbody tr:hover {{ background:var(--bg3); }}
td.model a {{ color:var(--fg); text-decoration:none; font-weight:500; }}
td.model a:hover {{ color:var(--lime); }}
.prov-link {{ color:var(--dim); text-decoration:none; }}
.prov-link:hover {{ color:var(--accent); }}
.num {{ text-align:right; font-family:'JetBrains Mono',monospace; font-variant-numeric:tabular-nums; }}
.tps b {{ color:var(--lime); font-size:16px; }}
.dim {{ color:var(--dim); }}
.tag {{ display:inline-block; font-size:11px; font-weight:500; border-radius:8px; padding:2px 8px; background:var(--bg3); white-space:nowrap; }}
.chips {{ display:block; margin-top:4px; }}
.chip {{ display:inline-block; font-size:10px; color:var(--dim); background:var(--bg3); border-radius:6px; padding:1px 6px; margin-right:3px; white-space:nowrap; }}
.chip b {{ color:var(--fg); }}
.empty {{ text-align:center; color:var(--dim); padding:50px; }}
footer {{ margin-top:24px; color:var(--dim); font-size:12px; text-align:center; }}
footer a {{ color:var(--accent); }}
@media (max-width:700px) {{
  .wrap {{ padding:12px; }}
  h1 {{ font-size:20px; }}
  .stats {{ grid-template-columns:repeat(2,1fr); }}
  td, th {{ padding:8px 10px; font-size:12px; }}
  .controls {{ position:static; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Free LLM <span>Tracker</span></h1>
    <p class="sub">Alle kostenlosen LLM-API-Modelle · gemessene t/s · Free-Status · sortierbar &amp; filterbar</p>
  </div>
  <a class="btn" href="https://github.com/harrytyp/free-llm-tracker" target="_blank" rel="noopener">GitHub ↗</a>
</header>

<div class="stats">
  <div class="stat"><b>{counts['free_models']}</b><span>Free-Modelle</span></div>
  <div class="stat"><b>{total_measured}</b><span>mit t/s</span></div>
  <div class="stat"><b>{verified}</b><span>verifiziert free</span></div>
  <div class="stat"><b>{updated[11:16]} UTC</b><span>Stand {updated[:10]}</span></div>
</div>

<div class="controls">
  <input class="search" id="search" placeholder="Suchen: Modell, Provider, Kontext…">
  <select id="provider-filter"><option value="">Alle Provider ({len(providers)})</option>{provider_opts}</select>
  <select id="status-filter">
    <option value="">Alle Status</option>
    <option value="verified-free">✓ Verifiziert</option>
    <option value="unverified">❓ Unverifiziert</option>
  </select>
  <select id="measured-filter">
    <option value="">Alle Modelle</option>
    <option value="measured">Nur mit t/s</option>
    <option value="unmeasured">Nur ohne t/s</option>
  </select>
  <select id="intel-filter">
    <option value="">Alle Intelligence</option>
    <option value="0-30">&lt;30 (schwach)</option>
    <option value="30-50">30–50 (mittel)</option>
    <option value="50-70">50–70 (stark)</option>
    <option value="70+">70+ (top)</option>
    <option value="none">Ohne Score</option>
  </select>
  <button class="btn" id="csv">CSV</button>
</div>

<div class="table-wrap">
<table id="tbl">
<thead>
<tr>
  <th data-k="id">Modell <span class="arr">▲▼</span></th>
  <th data-k="provider">Provider <span class="arr">▲▼</span></th>
  <th data-k="ftype">Free-Typ <span class="arr">▲▼</span></th>
  <th data-k="status">Status <span class="arr">▲▼</span></th>
  <th data-k="intel" class="num">Intelligence <span class="arr">▲▼</span></th>
  <th data-k="tps" class="num">t/s <span class="arr">▲▼</span></th>
  <th data-k="ttft" class="num">TTFT <span class="arr">▲▼</span></th>
  <th data-k="ctx" class="num">Kontext <span class="arr">▲▼</span></th>
  <th class="num">Budget</th>
</tr>
</thead>
<tbody id="tbody">
{rows}
</tbody>
</table>
</div>
<div class="empty" id="empty" style="display:none">Keine Modelle gefunden.</div>

<footer>
  <p>Quellen: OmniRoute free-catalog · OpenRouter · Artificial Analysis · llm-benchmarks.com · <a href="https://github.com/harrytyp/free-llm-tracker">Quellcode</a></p>
</footer>
</div>

<script>
const ROWS = document.getElementById('tbody');
let sortK = null, sortDir = 1;

function getVal(tr, k) {{
  switch(k) {{
    case 'tps': {{
      const b = tr.querySelector('.tps b');
      return b ? parseFloat(b.textContent) : -1;
    }}
    case 'intel': {{
      const b = tr.querySelector('.intel b');
      return b ? parseFloat(b.textContent) : -1;
    }}
    case 'ttft': {{
      const cells = tr.querySelectorAll('td');
      const t = cells[6] ? cells[6].textContent.replace('s','') : '';
      return t && t !== '–' ? parseFloat(t) : 9999;
    }}
    case 'ctx': {{
      const c = tr.querySelectorAll('td')[7];
      const t = c ? c.textContent : '';
      if (!t || t === '–') return 0;
      if (t.endsWith('M')) return parseFloat(t) * 1e6;
      return parseFloat(t) * 1e3;
    }}
    default: return tr.dataset[k] || '';
  }}
}}

function apply() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  const prov = document.getElementById('provider-filter').value;
  const status = document.getElementById('status-filter').value;
  const measured = document.getElementById('measured-filter').value;
  const intelF = document.getElementById('intel-filter').value;
  let visible = 0;

  [...ROWS.querySelectorAll('.mrow')].forEach(tr => {{
    const id = (tr.dataset.id + ' ' + tr.dataset.provider).toLowerCase();
    const okQ = !q || id.includes(q);
    const okP = !prov || tr.dataset.provider === prov;
    const okS = !status || tr.dataset.status === status;
    const hasTps = tr.dataset.tps !== '';
    const okM = !measured || (measured === 'measured' && hasTps) || (measured === 'unmeasured' && !hasTps);
    // intelligence filter
    const ii = tr.dataset.intel !== '' ? parseFloat(tr.dataset.intel) : null;
    let okI = true;
    if (intelF) {{
      if (intelF === 'none') okI = ii === null;
      else if (ii === null) okI = false;
      else {{
        const [lo, hi] = intelF.split('-').map(x => x === '' || x === '+' ? (x === '+' ? Infinity : 0) : parseFloat(x));
        okI = ii >= lo && (hi === undefined || hi === Infinity || ii < hi);
      }}
    }}
    tr.style.display = okQ && okP && okS && okM && okI ? '' : 'none';
    if (okQ && okP && okS && okM && okI) visible++;
  }});
  document.getElementById('empty').style.display = visible ? 'none' : 'block';
  const rows = [...ROWS.querySelectorAll('.mrow')].filter(t => t.style.display !== 'none');
  if (sortK) {{
    rows.sort((a,b) => {{
      const va = getVal(a, sortK), vb = getVal(b, sortK);
      if (typeof va === 'string' || typeof vb === 'string') return va.localeCompare(vb) * sortDir;
      return (va - vb) * sortDir;
    }});
    rows.forEach(t => ROWS.appendChild(t));
  }}
}}

document.querySelectorAll('th').forEach(th => {{
  th.addEventListener('click', () => {{
    const k = th.dataset.k;
    if (!k) return;
    if (sortK === k) sortDir *= -1;
    else {{ sortK = k; sortDir = (k === 'tps' || k === 'ttft' || k === 'ctx') ? -1 : 1; }}
    document.querySelectorAll('th').forEach(t => t.classList.toggle('sorted', t === th));
    apply();
  }});
}});
document.getElementById('search').addEventListener('input', apply);
document.getElementById('provider-filter').addEventListener('change', apply);
document.getElementById('status-filter').addEventListener('change', apply);
document.getElementById('measured-filter').addEventListener('change', apply);
document.getElementById('intel-filter').addEventListener('change', apply);
document.getElementById('csv').addEventListener('click', () => {{
  const lines = [['id','provider','free_type','free_status','intelligence','tps','ttft_s','context_length'].join(',')];
  [...ROWS.querySelectorAll('.mrow')].forEach(tr => {{
    const cells = tr.querySelectorAll('td');
    const id = cells[0].textContent.trim().split('\\n')[0];
    const prov = cells[1].textContent.trim();
    const ft = cells[2].textContent.trim();
    const st = cells[3].textContent.trim();
    const intel = cells[4].textContent.trim();
    const tps = cells[5].textContent.trim();
    const ttft = cells[6].textContent.trim();
    const ctx = cells[7].textContent.trim();
    lines.push([id, prov, ft, st, intel, tps, ttft, ctx].join(','));
  }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([lines.join('\\n')], {{type:'text/csv'}}));
  a.download = 'free-llm-models.csv'; a.click();
}});
apply();

// ─── Live-Status von usage.json (vom Router via GitHub-API gepusht) ───
// Lädt data/usage.json von GitHub Pages und markiert Zeilen live:
// - Rate-Limited/Cooldown: rotes Badge "⛔ rate-limited (Xs)"
// - Erfolgreich genutzt: grünes Badge "✓ ok (Latenz ms)"
// - Fehler: oranges Badge "⚠ fails"
fetch('data/usage.json', {{cache: 'no-store'}})
  .then(r => r.ok ? r.json() : Promise.reject('no usage.json'))
  .then(usageData => {{
    const now = Math.floor(Date.now() / 1000);
    const usage = usageData.usage || {{}};
    const cooldowns = usageData.cooldowns || {{}};
    [...ROWS.querySelectorAll('.mrow')].forEach(tr => {{
      const id = tr.dataset.id;
      const u = usage[id] || usage[id.replace(/:free$/,'')];
      const cd = cooldowns[id] || cooldowns[id.replace(/:free$/,'')];
      if (!u && !cd) return;
      // Status-Badge in der Status-Zelle (Index 3)
      const statusCell = tr.querySelectorAll('td')[3];
      if (cd && cd > now) {{
        const secs = Math.ceil(cd - now);
        statusCell.innerHTML += ` <span class="tag" style="color:#f85149" title="Live: rate-limited">⛔ RL {{secs}}s</span>`;
        tr.style.opacity = '0.75';
      }} else if (u && u.ok > 0) {{
        const lat = u.latency_ms && u.latency_ms.length ? u.latency_ms[u.latency_ms.length-1] : '';
        statusCell.innerHTML += ` <span class="tag" style="color:#3fb950" title="Live: erfolgreich genutzt">✓ {{u.ok}}/{{u.fail||0}}{{lat ? ' ('+lat+'ms)' : ''}}</span>`;
      }} else if (u && u.fail > 0) {{
        statusCell.innerHTML += ` <span class="tag" style="color:#d29922" title="Live: Fehler">⚠ {{u.fail}} fails</span>`;
      }}
    }});
    // Update-Info im Footer
    const upd = document.getElementById('updated-at');
    if (upd && usageData.updated_at) upd.textContent += ' · Live: ' + usageData.updated_at.replace('T',' ').replace('Z',' UTC');
  }})
  .catch(() => {{ /* kein usage.json (noch) — Seite funktioniert trotzdem */ }});
</script>
</body>
</html>
"""

    out = ROOT / "index.html"
    out.write_text(page)
    print(f"OK wrote {out} ({len(page)} bytes, {len(models)} models, {total_measured} measured)")


if __name__ == "__main__":
    main()
