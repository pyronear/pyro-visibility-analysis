"""Rank candidate sites by what they actually add.

Raw covered area answers "how much does this site see". It does not answer the
two questions that decide a deployment:

  - how much of the land **that matters** does it see? Coverage over farmland is
    worth less than coverage over zones under an obligation légale de
    débroussaillement (OLD). Where there is no OLD — some départements have none — the
    zone of interest is the département itself: half of what the cameras there
    see falls outside it, and the raw union would overstate the result twofold.
  - how much does it add to what is **already deployed**? A site duplicating an
    existing camera is worth less than a weaker site over a blind spot.

So this reports, per site: total area, the area inside each zone of interest,
and both again counted only outside what the already-deployed cameras see. Then
it runs a greedy selection on the marginal area of one designated zone — at each
step the site adding the most *new* ground there.

Sites marked `EN PLACE` in the Owner column form the baseline.

Usage:
    uv run python prioritise_sites.py                          # OLD, as before
    uv run python prioritise_sites.py --dept 77 --picks 5
    uv run python prioritise_sites.py --zones dept --dept 77   # no OLD available
    uv run python prioritise_sites.py --zones dept,old --objectif old
"""

import argparse
import glob
import os
import unicodedata

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas/rasterio imports

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402

from config import REGION  # noqa: E402
from analysis_shape.gestionnaires import categoriser, charger  # noqa: E402
from analysis_shape.zones import load_zones  # noqa: E402

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")


def nfc(value):
    """macOS stores filenames in NFD, sites.csv is NFC — compare on NFC."""
    return unicodedata.normalize("NFC", str(value))


def viewshed_paths(region):
    folder = os.path.join("data", region, "output", "viewsheds_geotiff")
    paths = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.tif"))):
        name = nfc(os.path.basename(path))[len("viewshed_"):-len(".tif")]
        paths[name] = path
    return paths


def read_mask(path):
    """Binary visibility mask, nodata treated as not visible."""
    with rasterio.open(path) as src:
        band = src.read(1)
        if src.nodata is not None:
            band = np.where(band == src.nodata, 0, band)
    return band > 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--dept", default="036",
                        help="département code, used to filter the OLD layer "
                             "and to build the « dept » zone")
    parser.add_argument("--zones", default="old",
                        help="comma-separated zones of interest to report: "
                             "old, dept, or any data/<region>/zones/<name>.gpkg")
    parser.add_argument("--objectif", default=None,
                        help="zone the greedy selection maximises "
                             "(default: the first one listed)")
    parser.add_argument("--picks", type=int, default=5,
                        help="how many sites the greedy selection should pick")
    args = parser.parse_args()

    table = charger(args.region)

    sites = pd.read_csv(os.path.join("data", args.region, "sites.csv"),
                        delimiter=";")
    sites["Name"] = sites["Name"].map(nfc)

    # « Already installed » and « who manages the support » are two different
    # things. Older sites.csv files mixed them in Owner; those with a Status
    # column keep them apart, which lets installed sites be categorised too.
    if "Status" in sites.columns:
        deployed = set(sites.loc[
            sites["Status"].astype(str).str.strip() == "EN PLACE", "Name"])
    else:
        deployed = set(sites.loc[
            sites["Owner"].astype(str).str.strip() == "EN PLACE", "Name"])

    def category(owner):
        return categoriser(owner, table)

    paths = viewshed_paths(args.region)
    missing = set(sites["Name"]) - set(paths)
    if missing:
        print(f"⚠️  no viewshed for: {', '.join(sorted(missing))}\n")

    reference = next(iter(paths.values()))
    with rasterio.open(reference) as src:
        cell_km2 = abs(src.transform.a * src.transform.e) / 1e6

    names = [n.strip() for n in args.zones.split(",") if n.strip()]
    zones = load_zones(args.region, names, reference, args.dept)
    objectif = next((z for z in zones if z.name == (args.objectif or names[0])), None)
    if objectif is None:
        raise SystemExit(f"❌ « {args.objectif} » is not among the loaded zones "
                         f"({', '.join(names)})")
    for zone in zones:
        print(f"Zone « {zone.name} » : {zone.reference_km2:,.0f} km²")
    print(f"Objectif de la sélection : « {objectif.name} »\n")

    # Baseline: what the deployed cameras already see.
    baseline = None
    for name in deployed:
        if name not in paths:
            continue
        mask = read_mask(paths[name])
        baseline = mask if baseline is None else (baseline | mask)
    if baseline is None:
        baseline = np.zeros_like(objectif.mask)
    blind = ~baseline

    print(f"Déjà en place ({len(deployed)} caméras) : "
          f"{baseline.sum() * cell_km2:,.0f} km² au total")
    for zone in zones:
        seen = zone.covered_km2(baseline)
        print(f"   dont « {zone.name} » : {seen:,.0f} km² "
              f"({100 * seen / zone.reference_km2:.1f} % de la zone)")
    print()

    owners = dict(zip(sites["Name"], sites["Owner"]))
    rows = []
    for name, path in paths.items():
        mask = read_mask(path)
        row = {
            "site": name,
            "categorie": category(owners.get(name, "")),
            "gestion": owners.get(name, ""),
            "deployed": name in deployed,
            "km2": mask.sum() * cell_km2,
            "new_km2": (mask & blind).sum() * cell_km2,
        }
        for zone in zones:
            row[f"km2_{zone.name}"] = zone.covered_km2(mask)
            row[f"new_km2_{zone.name}"] = zone.covered_km2(mask & blind)
            row[f"pct_{zone.name}"] = (100 * zone.covered_km2(mask)
                                       / zone.reference_km2)
        rows.append(row)
    table = pd.DataFrame(rows)

    obj_new = f"new_km2_{objectif.name}"
    candidates = table[~table["deployed"]].sort_values(obj_new, ascending=False)
    width = max(len(s) for s in table["site"])
    print(f"Candidats, classés par « {objectif.name} » NOUVEAU apporté "
          f"(hors de ce que voient les caméras en place)\n")
    header = f"{'site':<{width}} {'gestion':>10} {'total':>7}"
    for zone in zones:
        header += f" {zone.name[:7]:>7} {'%':>6}"
    header += f" {'nouveau':>8} {'nouv ' + objectif.name[:4]:>9}"
    print(header)
    for row in candidates.itertuples():
        line = (f"{row.site:<{width}} {row.categorie:>10} "
                f"{getattr(row, 'km2'):>7.0f}")
        for zone in zones:
            line += (f" {getattr(row, f'km2_{zone.name}'):>7.0f}"
                     f" {getattr(row, f'pct_{zone.name}'):>5.1f}%")
        line += (f" {row.new_km2:>8.0f} {getattr(row, obj_new):>9.0f}")
        print(line)

    objectif_km2 = objectif.reference_km2

    def greedy(pool, label):
        """Repeatedly take the site adding the most of `objectif` not yet covered."""
        print(f"\n{label}\n")
        covered = baseline.copy()
        remaining = dict(pool)
        results = []
        for step in range(1, args.picks + 1):
            best, best_gain, best_mask = None, -1, None
            for name, path in remaining.items():
                mask = read_mask(path)
                gain = objectif.covered_km2(mask & ~covered)
                if gain > best_gain:
                    best, best_gain, best_mask = name, gain, mask
            if best is None or best_gain <= 0:
                break
            covered |= best_mask
            del remaining[best]
            total = objectif.covered_km2(covered)
            results.append((best, best_gain, total))
            print(f"  {step}. {best:<{width}} +{best_gain:>6.0f} km² "
                  f"→ cumul {total:>6.0f} km² "
                  f"({100 * total / objectif_km2:.1f} % de « {objectif.name} »)")
        return results

    all_pool = {r.site: paths[r.site] for r in candidates.itertuples()}
    public_pool = {r.site: paths[r.site] for r in candidates.itertuples()
                   if r.categorie == "public"}

    open_run = greedy(all_pool, f"Scénario A — tous les sites ({args.picks} choix)")
    public_run = greedy(public_pool,
                        f"Scénario B — sites publics uniquement ({args.picks} choix)")

    if open_run and public_run:
        print("\nCe que les sites opérateurs achètent\n")
        for step in range(min(len(open_run), len(public_run))):
            a, b = open_run[step][2], public_run[step][2]
            print(f"  a {step + 1} site(s) : tous {a:>6.0f} km² "
                  f"({100 * a / objectif_km2:4.1f} %)  |  publics {b:>6.0f} km² "
                  f"({100 * b / objectif_km2:4.1f} %)  |  ecart {a - b:>+5.0f} km²")

    out = os.path.join("data", args.region, "output", "priorisation.csv")
    table.sort_values(obj_new, ascending=False).round(1).to_csv(
        out, sep=";", index=False)
    print(f"\n✅ {out}")


if __name__ == "__main__":
    main()
