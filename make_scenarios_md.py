"""Write docs/scenarios-<region>.md from each generated scenario's meta.json.

The QGIS layer metadata is easy to miss, so the authoritative list of which
sites make up which scenario lives in a markdown file next to the analysis.

Everything region-specific — which regions hold the viewsheds, the zone of
interest and its area — is read back from `data/<region>/scenarios.json` and
from the scenarios themselves, so this reports what was actually built rather
than what the script was written for.

    uv run python make_scenarios_md.py --region example
"""

import argparse
import csv
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analysis_shape.gestionnaires import categoriser, charger  # noqa: E402
from analysis_shape.names import site_name  # noqa: E402

# Labels for the owner categories, in reading order.
ETIQUETTES = {"en place": "*en place*", "public": "public",
              "delegataire": "délégataire", "operateur": "**opérateur**",
              "prive": "**privé**"}


def owners(regions):
    table = {}
    for region in regions:
        path = os.path.join("data", region, "sites.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                name = site_name(row["Name"])
                deployed = str(row.get("Status", "")).strip() == "EN PLACE"
                table[name] = (row.get("Owner", ""), row.get("Height", ""),
                               deployed)
    return table


def status(owner, deployed, categories):
    if deployed:
        return ETIQUETTES["en place"]
    categorie = categoriser(owner, categories)
    return ETIQUETTES.get(categorie, categorie)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True,
                        help="region holding scenarios.json and the scenarios")
    args = parser.parse_args()

    config_path = os.path.join("data", args.region, "scenarios.json")
    if not os.path.exists(config_path):
        raise SystemExit(f"❌ {config_path} not found")
    with open(config_path, encoding="utf-8") as handle:
        config = json.load(handle)

    OUT = os.path.join("data", args.region, "output")
    categories = charger(args.region)
    table = owners(config["regions"])
    metas = []
    for folder in sorted(glob.glob(os.path.join(OUT, "scenario_*"))):
        meta_path = os.path.join(folder, "meta.json")
        if not os.path.exists(meta_path):
            continue
        with open(meta_path, encoding="utf-8") as handle:
            metas.append(json.load(handle))
    if not metas:
        raise SystemExit(f"❌ no scenario under {OUT} — run "
                         f"scenario_layers.py --all first")

    # The zone's label and area come from the scenarios themselves: they
    # describe what was computed, not what the config says today.
    libelle_zone = metas[0].get("zone_libelle", "zone d'enjeu")
    zone_km2 = metas[0].get("zone_km2")
    reference = (f"**{zone_km2:,.0f} km² — {libelle_zone}**".replace(",", " ")
                 if zone_km2 else f"la {libelle_zone}")

    lines = [
        "# Scénarios — composition détaillée",
        "",
        "Généré par `make_scenarios_md.py` à partir des scénarios produits par",
        f"`scenario_layers.py`. Les pourcentages sont exprimés en part de",
        f"{reference}.",
        "",
        f"| scénario | sites | couvert | triangulé | "
        f"total couvert | total triangulé |",
        "|---|---:|---:|---:|---:|---:|",
    ]

    for meta in metas:
        lines.append(
            f"| `{meta['label']}` | {meta['n_sites']} | "
            f"{meta['pct_couvert']} % | {meta['pct_triangule']} % | "
            f"{meta.get('km2_total_couvert', 0):.0f} km² | "
            f"{meta.get('km2_total_triangule', 0):.0f} km² |")

    for meta in metas:
        # The km2_old_* keys predate generic zones of interest.
        libelle = meta.get("zone_libelle", "zone d'enjeu")
        couvert = meta.get("km2_zone_couvert", meta.get("km2_old_couvert", 0))
        triangule = meta.get("km2_zone_triangule", meta.get("km2_old_triangule", 0))
        lines += [
            "",
            f"## `{meta['label']}`",
            "",
            f"**{meta['n_sites']} sites**",
            "",
            f"- {libelle} : **{meta['pct_couvert']} % couverts** "
            f"({couvert:.0f} km²), **{meta['pct_triangule']} % triangulés** "
            f"({triangule:.0f} km²)",
            f"- toutes zones : **{meta.get('km2_total_couvert', 0):.0f} km² couverts**, "
            f"dont **{meta.get('km2_total_triangule', 0):.0f} km² triangulés**",
            "",
            "| # | site | statut | hauteur | propriétaire |",
            "|---:|---|---|---:|---|",
        ]
        for index, site in enumerate(meta["sites"], 1):
            owner, height, deployed = table.get(site, ("", "", False))
            # find_anfr_candidates.py prefixes ANFR labels with PUBLIC /
            # OPERATEUR; the prefix duplicates the status column, so only the
            # owner is kept.
            clean = str(owner)
            for prefixe in ("PUBLIC ", "OPERATEUR ", "PRIVE "):
                if clean.startswith(prefixe):
                    clean = clean[len(prefixe):]
            lines.append(f"| {index} | {site} | {status(owner, deployed, categories)} "
                         f"| {height} m | {clean} |")

    os.makedirs("docs", exist_ok=True)
    out_path = os.path.join("docs", f"scenarios-{args.region}.md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"✅ {out_path} — {len(metas)} scenarios")


if __name__ == "__main__":
    main()
