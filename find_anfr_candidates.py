"""Find new high points from the ANFR register, ranked by what they could add.

A SDIS list of high points is what the SDIS already knows about. It is rarely
the best set available: on one test département the ANFR register turned up 24
further candidates, and several outranked the original list. On another the 14
known points saturate at 82.5 % of the département, so anything beyond that has
to come from elsewhere.

The register is exhaustive but far too large to viewshed blindly — 1 739
supports in a single département. This narrows it down in four passes:

  nature & height   only structures a camera can actually use
  ownership         `TPO_ID` sorts public (commune, syndicat des eaux, SDIS,
                    département) from tower operators, who charge for access
  novelty           drop anything standing next to a site already in sites.csv
  blind-spot score  rank on how much *currently uncovered* zone lies within
                    detection range — the cheap geometric upper bound on what a
                    site could add, computed without running a single viewshed

The score is an upper bound, not a prediction: it ignores terrain entirely. Its
job is to cut 1 739 supports down to a shortlist worth the compute, after which
the real viewsheds decide. Sites are thinned so two candidates never sit within
`--ecart` of each other, which would otherwise fill the list with neighbours
scoring nearly the same.

Output is `candidats_anfr.csv`, in the sites.csv format, ready to append.

    uv run python find_anfr_candidates.py --region example   # dept from scenarios.json
"""

import argparse
import csv
import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path

from proj_env import use_bundled_proj

use_bundled_proj()

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import REGION, VIEWSHED_RADIUS_M  # noqa: E402
from analysis_shape.zones import load_zone, region_dept  # noqa: E402

REPO = Path(__file__).resolve().parent

# SUP_NATURE.txt. Lattice masts, towers and water towers carry a camera; an
# « immeuble » or a « local technique » is a rooftop with no guarantee of
# access or of a clear horizon, so they are left out.
NATURES_UTILES = {
    "4": "château d'eau", "11": "mât béton", "12": "mât métallique",
    "21": "pylône", "22": "pylône autoportant", "23": "pylône autostable",
    "24": "pylône haubané", "25": "pylône treillis", "26": "pylône tubulaire",
    "33": "tour hertzienne", "42": "mât", "43": "fût",
    # A building or a technical room already carries an antenna, so roof
    # access has been negotiated at least once: excluding them automatically
    # (access not guaranteed, cluttered urban horizon) dropped very real high
    # points. Kept, leaving later scenarios to drop them case by case if a
    # site survey contradicts the hope.
    "38": "immeuble", "39": "local technique",
}

# TPO_ID → whether access is negotiated with a public body or bought from an
# operator. The distinction drives cost and is a structural criterion, not a
# detail: operator sites carry recurring fees.
PROPRIETAIRES_PUBLICS = {
    "1", "3", "6", "7", "10", "11", "13", "15", "17", "18", "20", "23",
    "24", "25", "26", "34", "35", "39",
}

to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform


def norm(value):
    return unicodedata.normalize("NFC", str(value)).strip()


def load_reference_table(path, encoding="utf-8"):
    table = {}
    for line in Path(path).read_text(encoding=encoding).splitlines()[1:]:
        if ";" in line:
            key, label = line.split(";", 1)
            table[key.strip()] = label.strip()
    return table


def insee_dept(props, dept):
    """True when the support's commune belongs to `dept`.

    The etalab export drops the leading zero of INSEE codes: a 02xxx code
    arrives as 2xxx, which `startswith("21")` happily claims for the 21.
    That pulled six supports 130 to 230 km away into the dept 21 pool and blew
    the DEM extent up from 800 to 3 200 Mpx. Pad both sides before comparing —
    Corsica ("2A004") is already five characters, so padding leaves it alone.
    """
    code = str(props.get("COM_CD_INSEE") or "").strip()
    if not code:
        return False
    return code.zfill(5).startswith(str(dept).strip().zfill(2))


def load_supports(path, dept):
    """ANFR supports of one département, one per distinct structure.

    The export is a geojson with one feature per line, so it is read as a
    stream: loading 77 MB to keep one département would be wasteful, and
    several stations share a single support.
    """
    supports, seen = [], set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip().rstrip(",")
            if not line.startswith('{ "type": "Feature"'):
                continue
            feature = json.loads(line)
            props = feature["properties"]
            if not insee_dept(props, dept):
                continue
            lon, lat = feature["geometry"]["coordinates"]
            key = (round(lat, 5), round(lon, 5), props.get("SUP_NM_HAUT"))
            if key in seen:
                continue
            seen.add(key)
            x, y = to_l93(lon, lat)
            address = " ".join(
                str(props[k]) for k in
                ("ADR_LB_LIEU", "ADR_LB_ADD1", "ADR_LB_ADD2", "ADR_LB_ADD3")
                if props.get(k))
            supports.append({
                "sup_id": props.get("SUP_ID"), "lat": lat, "lon": lon,
                "x": x, "y": y,
                "hauteur": props.get("SUP_NM_HAUT"),
                "nat_id": str(props.get("NAT_ID")),
                "tpo_id": str(props.get("TPO_ID")),
                "insee": str(props.get("COM_CD_INSEE")),
                "adresse": address,
            })
    return supports


def existing_sites(region):
    path = REPO / "data" / region / "sites.csv"
    if not path.exists():
        return []
    out = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            x, y = to_l93(float(row["Longitude"]), float(row["Latitude"]))
            out.append({"name": norm(row["Name"]), "x": x, "y": y})
    return out


def blind_mask(region, zone, baseline_path):
    """Zone cells not yet seen by the existing deployment."""
    if not os.path.exists(baseline_path):
        print(f"   ℹ️  {baseline_path} missing — score computed over the whole zone")
        return zone.mask.copy()
    with rasterio.open(baseline_path) as src:
        band = src.read(1)
        if src.nodata is not None:
            band = np.where(band == src.nodata, 0, band)
    return zone.mask & ~(band > 0)


def score_supports(supports, blind, transform, cell_km2, radius_m):
    """Uncovered area within detection range of each support, in km².

    A plain disc: no terrain, no line of sight. It answers "is there anything
    left to see from here at all", which is enough to reject the many supports
    surrounded by already-covered ground.
    """
    inv = ~transform
    height, width = blind.shape
    # Integral image: the disc is approximated by its bounding square, which is
    # 27 % too generous but turns each lookup into four array reads instead of
    # a mask over a few million cells.
    integral = blind.cumsum(axis=0).cumsum(axis=1)

    def window_sum(r0, r1, c0, c1):
        r0, c0 = max(r0, 0), max(c0, 0)
        r1, c1 = min(r1, height - 1), min(c1, width - 1)
        if r1 < r0 or c1 < c0:
            return 0
        total = integral[r1, c1]
        if r0 > 0:
            total -= integral[r0 - 1, c1]
        if c0 > 0:
            total -= integral[r1, c0 - 1]
        if r0 > 0 and c0 > 0:
            total += integral[r0 - 1, c0 - 1]
        return int(total)

    pixel_m = abs(transform.a)
    reach = int(radius_m / pixel_m)
    for support in supports:
        col, row = inv * (support["x"], support["y"])
        col, row = int(col), int(row)
        cells = window_sum(row - reach, row + reach, col - reach, col + reach)
        support["score_km2"] = round(cells * cell_km2, 1)


def thin(candidates, min_gap_m):
    """Keep the best candidate of any cluster closer than `min_gap_m`."""
    kept = []
    for candidate in candidates:  # already sorted best first
        if all(math.hypot(candidate["x"] - k["x"], candidate["y"] - k["y"])
               >= min_gap_m for k in kept):
            kept.append(candidate)
    return kept


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--dept", default=None,
                        help="département code, e.g. 77 (default: \"dept\" in "
                             "data/<region>/scenarios.json)")
    parser.add_argument("--anfr", type=Path,
                        default=Path.home() / "Downloads" / "SUP_SUPPORT.geojson")
    parser.add_argument("--refs", type=Path,
                        default=Path.home() / "Downloads"
                        / "20250131-export-etalab-ref-1-")
    parser.add_argument("--zone", default="dept",
                        help="zone of interest used for the score (default: dept)")
    parser.add_argument("--hauteur-min", type=float, default=30.0)
    parser.add_argument("--ecart", type=float, default=3000.0,
                        help="minimum distance between two kept candidates (m)")
    parser.add_argument("--proche-existant", type=float, default=500.0,
                        help="below this distance, a support counts as already listed")
    parser.add_argument("--top", type=int, default=25,
                        help="number of candidates written to the CSV")
    parser.add_argument("--publics-seulement", action="store_true")
    parser.add_argument("--max-operateurs", type=int, default=None,
                        help="caps operator supports in the list; the rest is "
                             "filled with public ones. Recurring access cost is a "
                             "structuring criterion, not a detail")
    args = parser.parse_args()

    # The ANFR register is filtered by département: no default makes sense.
    args.dept = region_dept(args.region, args.dept)
    if not args.dept:
        raise SystemExit(f"❌ no département: set \"dept\" in "
                         f"data/{args.region}/scenarios.json, or pass --dept")

    if not args.anfr.exists():
        raise SystemExit(f"❌ ANFR export not found: {args.anfr}")

    natures = load_reference_table(args.refs / "SUP_NATURE.txt")
    proprios = load_reference_table(args.refs / "SUP_PROPRIETAIRE.txt")

    print(f"▶ ANFR, département {args.dept}")
    supports = load_supports(args.anfr, args.dept)
    print(f"  {len(supports)} distinct supports")

    kept = [s for s in supports if s["nat_id"] in NATURES_UTILES]
    print(f"  {len(kept)} of a usable kind")
    kept = [s for s in kept if (s["hauteur"] or 0) >= args.hauteur_min]
    print(f"  {len(kept)} at least {args.hauteur_min:.0f} m tall")

    for support in kept:
        support["public"] = support["tpo_id"] in PROPRIETAIRES_PUBLICS
        support["proprietaire"] = proprios.get(support["tpo_id"], "inconnu")
        support["nature"] = natures.get(support["nat_id"], "?")
    if args.publics_seulement:
        kept = [s for s in kept if s["public"]]
        print(f"  {len(kept)} with a public owner")

    already = existing_sites(args.region)
    kept = [s for s in kept
            if all(math.hypot(s["x"] - e["x"], s["y"] - e["y"])
                   >= args.proche_existant for e in already)]
    print(f"  {len(kept)} away from the {len(already)} sites already listed")

    viewsheds = sorted((REPO / "data" / args.region / "output"
                        / "viewsheds_geotiff").glob("*.tif"))
    if not viewsheds:
        raise SystemExit("❌ no viewshed — run compute_viewsheds.py first")
    reference = str(viewsheds[0])
    zone = load_zone(args.region, args.zone, reference, args.dept)
    with rasterio.open(reference) as src:
        transform = src.transform
        cell_km2 = abs(src.transform.a * src.transform.e) / 1e6

    fusion = (REPO / "data" / args.region / "output" / "fusion"
              / "fusion_or_all_sites.tif")
    blind = blind_mask(args.region, zone, str(fusion))
    print(f"\n  zone « {zone.name} »: {zone.reference_km2:,.0f} km², "
          f"of which {blind.sum() * cell_km2:,.0f} km² not covered today")

    score_supports(kept, blind, transform, cell_km2, VIEWSHED_RADIUS_M)
    kept.sort(key=lambda s: (-s["score_km2"], -(s["hauteur"] or 0)))
    thinned = thin(kept, args.ecart)

    if args.max_operateurs is None:
        shortlist = thinned[:args.top]
    else:
        # The quota applies walking down the sorted list: keep the best
        # operator sites up to the cap, then take public ones only. Merit order
        # is therefore preserved within each category.
        shortlist, operateurs = [], 0
        for support in thinned:
            if len(shortlist) >= args.top:
                break
            if not support["public"]:
                if operateurs >= args.max_operateurs:
                    continue
                operateurs += 1
            shortlist.append(support)

    out = REPO / "data" / args.region / "candidats_anfr.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Name", "Latitude", "Longitude", "Owner", "Height"])
        for support in shortlist:
            # A motorway address sometimes carries a '/' (« A6 >Paris/Aire de
            # Service »): this name becomes a file name (viewshed.py), where a
            # '/' reads as a missing subfolder. gdal.Create() then fails
            # silently (returns None), and the QGIS plugin crashes on it
            # without saying why. Cleaned here, at the source.
            label = re.sub(r'[/\\:*?"<>|]', '-',
                           norm(support["adresse"]).replace(";", ","))[:40] or "no address"
            writer.writerow([
                f"ANFR {support['sup_id']} - {label}",
                round(support["lat"], 6), round(support["lon"], 6),
                ("PUBLIC" if support["public"] else "OPERATEUR")
                + f" {support['proprietaire']}".replace(";", ","),
                round(float(support["hauteur"]), 1),
            ])

    print(f"\n{'score':>7} {'height':>6}  {'access':<10} {'kind':<18} owner")
    for support in shortlist:
        print(f"{support['score_km2']:>7.0f} {support['hauteur']:>5.0f}m  "
              f"{'public' if support['public'] else 'OPERATOR':<10} "
              f"{support['nature'][:18]:<18} {support['proprietaire'][:28]}")

    publics = sum(1 for s in shortlist if s["public"])
    print(f"\n✅ {out.relative_to(REPO)} — {len(shortlist)} candidates, "
          f"{publics} public, {len(shortlist) - publics} operator")
    print("   The score is an upper bound ignoring terrain: it sorts, it does not")
    print("   conclude. Append these rows to sites.csv and rerun compute_viewsheds.py.")

    # Shortlist breakdown: useful to spot, before running a single viewshed,
    # whether one kind of support or one owner dominates enough to skew the
    # reading (e.g. a flood of urban buildings, or a single operator locking
    # up every usable structure).
    par_nature = Counter(s["nature"] for s in shortlist)
    par_proprio = Counter(s["proprietaire"] for s in shortlist)
    print(f"\n   breakdown by kind ({len(par_nature)} kinds):")
    for nature, n in par_nature.most_common():
        print(f"     {n:3d}  {nature}")
    print(f"\n   breakdown by owner ({len(par_proprio)} distinct):")
    for proprio, n in par_proprio.most_common():
        print(f"     {n:3d}  {proprio}")


if __name__ == "__main__":
    main()
