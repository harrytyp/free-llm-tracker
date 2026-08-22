#!/usr/bin/env python3
"""Render a modern, USABLE static site from data/latest.json + data/benchmarks.json.

Design decisions (Kolja: "Seite ist unbenutzbar, absoluter Müll"):
  - CARDS grouped by provider (not one giant table) — scannable
  - Measured models FIRST, then unmeasured
  - Big clear speed numbers, free-status badges, provider detail
  - Search + provider filter + free-type filter
  - Mobile-first, dark, professional
"""
from __future__ import annotations

import html
import json
from collections import defaultdict
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
        "puter": "https://puter.com",
        "pollinations": "https://pollinations.ai",
        "huggingchat": "https://huggingface.co/chat",
        "mistral": "https://mistral.ai",
        "cohere": "https://cohere.com",
    }
    if provider in links:
        return links[provider]
    return f"https://openrouter.ai/{base}"


def provider_link_plain(provider: str) -> str:
    links = {
        "openrouter": "https://openrouter.ai",
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
        "puter": "https://puter.com",
        "pollinations": "https://pollinations.ai",
        "huggingchat": "https://huggingface.co/chat",
        "mistral": "https://mistral.ai",
        "cohere": "https://cohere.com",
    }
    return links.get(provider, f"https://www.google.com/search?q={provider}+AI+API")


_FREE_TAGS = {
    "recurring-monthly": ("monatlich", "#3fb950"),
    "recurring-daily": ("täglich", "#58a6ff"),
    "keyless": ("keylos", "#d29922"),
    "recurring-uncapped": ("uncapped", "#8b949e"),
    "one-time-initial": ("einmalig", "#a371f7"),
    "recurring-credit": ("credit", "#f0883e"),
}

_STATUS = {
    "verified-free": ("✓ free verifiziert", "#3fb950"),
    "deprecated-not-on-openrouter": ("⚠️ deprecated", "#f85149"),
    "unverified": ("❓ unverifiziert", "#d29922"),
}


def model_card(m: dict) -> str:
    sp = m.get("speed") or {}
    tps = sp.get("tps")
    ttft = sp.get("ttft_s")
    prov = m.get("provider", "")
    mid = m["id"]
    name = m.get("name", mid)

    # Speed display
    if tps is not None:
        speed_html = f'<div class="speed"><b>{tps:g}</b><span>t/s</span></div>'
        if ttft is not None:
            speed_html += f'<div class="ttft">TTFT {ttft:g}s</div>'
    else:
        speed_html = '<div class="speed none">–</div><div class="ttft">keine Messung</div>'

    # Provider list for AA models
    prov_detail = ""
    if sp.get("providers"):
        top = sp["providers"][:3]
        prov_detail = '<div class="providers">' + "".join(
            f'<span class="prov-chip">{esc(p["provider"])} <b>{p["tps"]:g}</b> t/s</span>'
            for p in top if p.get("tps")
        ) + "</div>"

    ftype = _FREE_TAGS.get(m.get("free_type", ""), (m.get("free_type", "?"), "#8b949e"))
    status = _STATUS.get(m.get("free_status", "unverified"), ("❓", "#8b949e"))

    ctx = m.get("context_length")
    ctx_html = ""
    if ctx:
        n = float(ctx)
        ctx_html = f'<span class="ctx">{n/1e6:.0f}M</span>' if n >= 1e6 else f'<span class="ctx">{n/1e3:.0f}k</span>'

    budget = ""
    if m.get("monthly_tokens") or m.get("credit_tokens"):
        parts = []
        if m.get("monthly_tokens"):
            parts.append(f'{m["monthly_tokens"]:,}'.replace(",", "."))
        if m.get("credit_tokens"):
            parts.append(f'+{m["credit_tokens"]:,}'.replace(",", "."))
        budget = f'<span class="budget">{"/".join(parts)}</span>'

    return f"""<div class="card" data-id="{esc(mid.lower())}" data-provider="{esc(prov.lower())}" data-ftype="{esc(m.get('free_type',''))}" data-name="{esc(name.lower())}">
  <div class="card-top">
    <div class="card-title">
      <a href="{esc(provider_link(prov, mid))}" target="_blank" rel="noopener">{esc(mid)}</a>
      <span class="ftype" style="color:{ftype[1]}">{esc(ftype[0])}</span>
      <span class="status" style="color:{status[1]}">{esc(status[0])}</span>
      {ctx_html}
      {budget}
    </div>
    <div class="card-provider">
      <a href="{esc(provider_link_plain(prov))}" target="_blank" rel="noopener">{esc(prov)}</a>
    </div>
  </div>
  <div class="card-body">
    {speed_html}
    {prov_detail}
    <div class="card-name">{esc(name)}</div>
  </div>
</div>"""


def main() -> int:
    latest = json.loads((DATA / "latest.json").read_text())
    bench_raw = json.loads((DATA / "benchmarks.json").read_text())
    models = latest["models"]
    counts = latest["counts"]
    updated = latest["updated_at"]

    bench_raw_data = bench_raw.get("results", {})
    # llm-benchmarks provider summary (30-day measurements)
    llmbench = (bench_raw_data.get("__llmbench") or {}).get("providers", {}) if bench_raw_data.get("__llmbench") else {}
    for m in models:
        mid = m["id"].lower().rstrip(":free")
        entry = bench_raw_data.get(m["id"]) or bench_raw_data.get(mid)
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
        # llm-benchmarks fallback: match by model basename
        if not (m["speed"] or {}).get("tps"):
            base = mid.split("/")[-1].replace(".", "-").replace("_", "-")
            # try direct and normalized match
            for key, val in llmbench.items():
                if base in key or key in base:
                    m["speed"] = {"tps": val.get("tps"), "ttft_s": (val.get("ttft_ms") or 0) / 1000 if val.get("ttft_ms") else None,
                                  "source": f"llmbench-{val.get('provider')}"}
                    break

    # Group by provider, sort providers by measured count desc
    by_prov = defaultdict(list)
    for m in models:
        by_prov[m.get("provider", "?")].append(m)
    for p in by_prov:
        by_prov[p].sort(key=lambda x: (0 if (x.get("speed") or {}).get("tps") else 1,
                                       -(x["speed"]["tps"] if (x.get("speed") or {}).get("tps") else 0),
                                       x["id"]))
    providers_sorted = sorted(by_prov.items(),
                              key=lambda kv: sum(1 for m in kv[1] if (m.get("speed") or {}).get("tps")),
                              reverse=True)

    # HTML sections per provider
    sections = []
    for prov, ms in providers_sorted:
        measured = sum(1 for m in ms if (m.get("speed") or {}).get("tps"))
        cards = "".join(model_card(m) for m in ms)
        sections.append(f"""<section class="provider-group" data-provider="{esc(prov.lower())}">
  <h2 class="provider-head">
    <a href="{esc(provider_link_plain(prov))}" target="_blank" rel="noopener">{esc(prov)}</a>
    <span class="count">{len(ms)} Modelle</span>
    <span class="count measured">📊 {measured} gemessen</span>
  </h2>
  <div class="card-grid">{cards}</div>
</section>""")
    sections_html = "\n".join(sections)

    total_measured = sum(1 for m in models if (m.get("speed") or {}).get("tps"))
    verified = sum(1 for m in models if m.get("free_status") == "verified-free")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    page = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Free LLM Tracker — {counts['free_models']} Free-Modelle</title>
<meta name="description" content="Alle Free LLM-API-Modelle mit gemessenen t/s, Free-Status und Provider-Statistiken. Automatisch aktualisiert.">
<style>
:root {{
  --bg:#0a0e14; --bg2:#111720; --bg3:#1a2230; --border:#243044;
  --fg:#e6edf3; --dim:#8b98a8; --accent:#58a6ff; --ok:#3fb950; --warn:#d29922; --danger:#f85149;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:1400px; margin:0 auto; padding:20px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:20px; }}
h1 {{ font-size:26px; font-weight:700; }}
h1 span {{ color:var(--accent); }}
.sub {{ color:var(--dim); font-size:13px; margin-top:2px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:10px; margin-bottom:16px; }}
.stat {{ background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:12px 14px; }}
.stat b {{ display:block; font-size:22px; color:#fff; }}
.stat span {{ color:var(--dim); font-size:12px; }}
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; position:sticky; top:0; background:var(--bg); padding:8px 0; z-index:10; }}
.search {{ flex:1; min-width:200px; background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:10px 14px; color:var(--fg); font-size:14px; }}
.search:focus {{ outline:none; border-color:var(--accent); }}
select, .btn {{ background:var(--bg2); border:1px solid var(--border); border-radius:10px; padding:10px 14px; color:var(--fg); font-size:13px; cursor:pointer; }}
select:focus {{ outline:none; border-color:var(--accent); }}
.btn:hover {{ border-color:var(--accent); }}
.provider-group {{ margin-bottom:28px; }}
.provider-head {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; padding-bottom:8px; border-bottom:1px solid var(--border); }}
.provider-head a {{ color:var(--fg); text-decoration:none; font-size:18px; font-weight:600; }}
.provider-head a:hover {{ color:var(--accent); }}
.count {{ color:var(--dim); font-size:12px; background:var(--bg2); border-radius:10px; padding:2px 8px; }}
.count.measured {{ color:var(--accent); }}
.card-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:10px; }}
.card {{ background:var(--bg2); border:1px solid var(--border); border-radius:12px; padding:14px; transition:border-color .15s; }}
.card:hover {{ border-color:var(--accent); }}
.card-top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
.card-title a {{ color:var(--fg); text-decoration:none; font-weight:600; font-size:14px; word-break:break-all; }}
.card-title a:hover {{ color:var(--accent); }}
.ftype, .status, .ctx, .budget {{ display:inline-block; font-size:10px; border-radius:8px; padding:1px 6px; margin-left:4px; background:var(--bg3); }}
.ctx {{ color:var(--dim); }}
.budget {{ color:var(--dim); }}
.card-provider a {{ color:var(--dim); text-decoration:none; font-size:12px; white-space:nowrap; }}
.card-provider a:hover {{ color:var(--accent); }}
.card-body {{ margin-top:10px; display:flex; flex-direction:column; gap:6px; }}
.speed {{ font-size:22px; }}
.speed b {{ font-size:28px; color:var(--ok); }}
.speed span {{ color:var(--dim); font-size:13px; margin-left:4px; }}
.speed.none {{ color:var(--dim); font-size:22px; }}
.ttft {{ color:var(--dim); font-size:12px; }}
.providers {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:4px; }}
.prov-chip {{ background:var(--bg3); border-radius:8px; padding:2px 8px; font-size:11px; color:var(--dim); }}
.prov-chip b {{ color:var(--fg); }}
.card-name {{ color:var(--dim); font-size:12px; }}
.empty {{ text-align:center; color:var(--dim); padding:60px; font-size:16px; }}
footer {{ margin-top:30px; color:var(--dim); font-size:12px; text-align:center; }}
footer a {{ color:var(--accent); }}
@media (max-width:700px) {{
  .card-grid {{ grid-template-columns:1fr; }}
  .wrap {{ padding:12px; }}
  h1 {{ font-size:20px; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div>
    <h1>Free LLM <span>Tracker</span></h1>
    <p class="sub">Alle kostenlosen LLM-API-Modelle · gemessene t/s · Free-Status · automatisch aktualisiert</p>
  </div>
  <a class="btn" href="https://github.com/harrytyp/free-llm-tracker" target="_blank" rel="noopener">GitHub ↗</a>
</header>

<div class="stats">
  <div class="stat"><b>{counts['free_models']}</b><span>Free-Modelle</span></div>
  <div class="stat"><b>{total_measured}</b><span>mit gemessenen t/s</span></div>
  <div class="stat"><b>{verified}</b><span>free verifiziert</span></div>
  <div class="stat"><b>{updated[11:16]} UTC</b><span>Stand {updated[:10]}</span></div>
</div>

<div class="controls">
  <input class="search" id="search" placeholder="Suchen: Modell, Provider…">
  <select id="provider-filter"><option value="">Alle Provider</option></select>
  <select id="status-filter">
    <option value="">Alle Status</option>
    <option value="verified-free">✓ Verifiziert</option>
    <option value="unverified">❓ Unverifiziert</option>
  </select>
  <select id="measured-filter">
    <option value="">Alle Modelle</option>
    <option value="measured">Nur gemessene</option>
    <option value="unmeasured">Nur ohne Messung</option>
  </select>
</div>

<div id="content">
{sections_html}
</div>

<div class="empty" id="empty" style="display:none">Keine Modelle gefunden.</div>

<footer>
  <p>Quellen: OmniRoute free-catalog · OpenRouter · Artificial Analysis Provider-Benchmarks · llm-benchmarks.com</p>
  <p><a href="https://github.com/harrytyp/free-llm-tracker">Quellcode</a> · Entwickelt von harrytyp</p>
</footer>
</div>

<script>
function filterModels() {{
  const q = document.getElementById('search').value.toLowerCase().trim();
  const prov = document.getElementById('provider-filter').value.toLowerCase();
  const status = document.getElementById('status-filter').value;
  const measured = document.getElementById('measured-filter').value;

  // Populate provider dropdown on load
  if (document.getElementById('provider-filter').options.length === 1) {{
    const provs = new Set();
    document.querySelectorAll('.provider-group').forEach(s => provs.add(s.dataset.provider));
    [...provs].sort().forEach(p => {{
      const opt = document.createElement('option');
      opt.value = p; opt.textContent = p;
      document.getElementById('provider-filter').appendChild(opt);
    }});
  }}

  let visible = 0;
  document.querySelectorAll('.provider-group').forEach(section => {{
    const sProv = section.dataset.provider;
    if (prov && sProv !== prov) {{ section.style.display = 'none'; return; }}
    let sectionVisible = false;
    section.querySelectorAll('.card').forEach(card => {{
      const text = (card.dataset.id + ' ' + card.dataset.name + ' ' + card.dataset.provider).toLowerCase();
      const matchesQ = !q || text.includes(q);
      const matchesStatus = !status || card.dataset.status === status;
      const hasTps = card.querySelector('.speed b') !== null;
      const matchesMeasured = !measured || (measured === 'measured' && hasTps) || (measured === 'unmeasured' && !hasTps);
      const show = matchesQ && matchesStatus && matchesMeasured;
      card.style.display = show ? '' : 'none';
      if (show) {{ sectionVisible = true; visible++; }}
    }});
    section.style.display = sectionVisible ? '' : 'none';
  }});
  document.getElementById('empty').style.display = visible ? 'none' : 'block';
}}
document.getElementById('search').addEventListener('input', filterModels);
document.getElementById('provider-filter').addEventListener('change', filterModels);
document.getElementById('status-filter').addEventListener('change', filterModels);
document.getElementById('measured-filter').addEventListener('change', filterModels);
filterModels();
</script>
</body>
</html>
"""

    out = ROOT / "index.html"
    out.write_text(page)
    print(f"OK wrote {out} ({len(page)} bytes, {len(models)} models, {total_measured} measured)")


if __name__ == "__main__":
    main()
