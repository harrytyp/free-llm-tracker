#!/usr/bin/env python3
"""Aggregate per-provider stats from data/latest.json -> data/providers.json.

Runs after collector.py. Reproducible: every run rebuilds from scratch.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main() -> int:
    latest = json.loads((DATA / "latest.json").read_text())
    models = latest["models"]

    by_provider: dict[str, dict] = defaultdict(lambda: {
        "count": 0,
        "measured": 0,
        "tps_values": [],
        "top_models": [],
        "free_types": defaultdict(int),
    })

    for m in models:
        prov = m.get("provider", "unknown")
        sp = m.get("speed") or {}
        entry = by_provider[prov]
        entry["count"] += 1
        if sp.get("tps_mean"):
            entry["measured"] += 1
            entry["tps_values"].append(sp["tps_mean"])
        entry["free_types"][m.get("free_type", "recurring-monthly")] += 1
        if len(entry["top_models"]) < 5:
            entry["top_models"].append({
                "id": m["id"],
                "tps": sp.get("tps_mean"),
                "name": m.get("name", m["id"]),
            })

    # Sort top_models by tps desc
    for prov, entry in by_provider.items():
        entry["top_models"].sort(key=lambda x: x["tps"] or 0, reverse=True)
        entry["avg_tps"] = round(sum(entry["tps_values"]) / len(entry["tps_values"]), 2) if entry["tps_values"] else None
        entry["free_types"] = dict(entry["free_types"])

    # Sort providers by count desc
    sorted_providers = sorted(by_provider.items(), key=lambda x: x[1]["count"], reverse=True)

    out = {
        "updated_at": latest["updated_at"],
        "total_providers": len(sorted_providers),
        "providers": [
            {"provider": prov, **data} for prov, data in sorted_providers
        ],
    }

    (DATA / "providers.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"OK wrote providers.json: {len(sorted_providers)} providers")
    for prov, data in sorted_providers[:10]:
        print(f"  {prov}: {data['count']} models, {data['measured']} measured, avg {data['avg_tps']} t/s")


if __name__ == "__main__":
    main()