"""Find new high points, ranked by what they could add.

A SDIS list of high points is what the SDIS already knows about. It is rarely
the best set available: on one test département the ANFR register turned up 24
further candidates, and several outranked the original list. On another the 14
known points saturate at 82.5 % of the département, so anything beyond that has
to come from elsewhere.

Two sources, merged into one list of structures:

  anfr          the ANFR register of radio supports: height, kind and owner,
                but only structures that carry an antenna
  chateaux-eau  BD TOPO water towers (`BDTOPO_V3:reservoir`, nature
                « Château d'eau »), which the register misses when they carry
                no radio equipment. Their owner is not given: they are listed
                as PUBLIC (a commune or a water syndicate), to be corrected by
                hand when a survey says otherwise.

A water tower that does carry antennas is in both. An ANFR support within
`--doublon` of a BD TOPO tower is that tower: one entry is kept, with the BD
TOPO position and height — the structure itself, where ANFR's `SUP_NM_HAUT`
includes the antenna mast and its coordinates are whole DMS seconds (~30 m) —
and the ANFR identifier and owner.

The register is exhaustive but far too large to viewshed blindly — 1 739
supports in a single département. This narrows the list down in four passes,
the same for both sources:

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

Output is `candidats.csv`, in the sites.csv format, ready to append.

    uv run python find_candidates.py --region example   # dept from scenarios.json
    uv run python find_candidates.py --region example --sources anfr

`--around-zone <name>` asks a different question: not « what could fill the
gaps of a département », but « which existing high points could see this one
zone » — a forest, a massif, anything in data/<region>/zones/<name>.gpkg
(fetch_zone.py). It keeps every usable support within detection range of the
zone's outline, whatever its département, since a small zone near a border is
watched from both sides. There is no score and no shortlist: on a zone a few
kilometres wide every support in range would score the whole zone, and at about
a second per viewshed it is cheaper to compute them all and let the greedy
decide. No département and no viewshed are needed beforehand, so this is the
first step of such a region, before the DEM. Supports are listed nearest
first; `--top` and `--ecart` still apply when given.

    uv run python find_candidates.py --region <region> --around-zone <zone>
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
from shapely.geometry import Point  # noqa: E402
from shapely.prepared import prep  # noqa: E402

from config import REGION, VIEWSHED_RADIUS_M  # noqa: E402
from analysis_shape.wfs import bbox_l93, get_features  # noqa: E402
from analysis_shape.zones import _dept_gdf, load_zone, region_dept, zone_geometry  # noqa: E402

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

SOURCES = ("anfr", "chateaux-eau")

WATER_TOWERS = "BDTOPO_V3:reservoir"
# Not built yet: nothing to put a camera on. A tower out of service still stands.
ETATS_ABSENTS = {"En projet", "En construction"}
# The SUP_NATURE code of a water tower, given to BD TOPO towers so that both
# sources read the same downstream.
NAT_CHATEAU_EAU = "4"

to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform
to_wgs = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True).transform


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


def load_supports(path, dept=None, near=None):
    """ANFR supports of one département, one per distinct structure.

    The export is a geojson with one feature per line, so it is read as a
    stream: loading 77 MB to keep one département would be wasteful, and
    several stations share a single support. `near(x, y)` replaces or narrows
    the département filter with a test on Lambert-93 coordinates.
    """
    supports, seen = [], set()
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip().rstrip(",")
            if not line.startswith('{ "type": "Feature"'):
                continue
            feature = json.loads(line)
            props = feature["properties"]
            if dept and not insee_dept(props, dept):
                continue
            lon, lat = feature["geometry"]["coordinates"]
            key = (round(lat, 5), round(lon, 5), props.get("SUP_NM_HAUT"))
            if key in seen:
                continue
            x, y = to_l93(lon, lat)
            if near and not near(x, y):
                continue
            seen.add(key)
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
                "source": "anfr",
            })
    return supports


def _number(value):
    """A BD TOPO attribute as a float, None when missing (NaN in the frame)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return float(value)


def tower_height(row):
    """`hauteur`, else roof minus ground: `hauteur` is empty on some towers."""
    height = _number(row.get("hauteur"))
    if height:
        return height
    roof = (_number(row.get("altitude_maximale_toit"))
            or _number(row.get("altitude_minimale_toit")))
    ground = _number(row.get("altitude_minimale_sol"))
    if roof is not None and ground is not None and roof > ground:
        return round(roof - ground, 1)
    return None


def load_water_towers(bounds, inside):
    """BD TOPO water towers within `bounds` (Lambert-93) passing `inside(x, y)`."""
    gdf = get_features(WATER_TOWERS, BBOX=bbox_l93(*bounds))
    towers, no_height = [], 0
    for _, row in gdf.iterrows():
        if (row.get("nature") != "Château d'eau"
                or row.get("etat_de_l_objet") in ETATS_ABSENTS):
            continue
        centre = row.geometry.centroid
        if not inside(centre.x, centre.y):
            continue
        height = tower_height(row)
        if height is None:
            no_height += 1
            continue
        lon, lat = to_wgs(centre.x, centre.y)
        towers.append({
            # `RESERVOI0000002203289356` → `2203289356`: short, still unique.
            "sup_id": str(row.get("cleabs")).removeprefix("RESERVOI").lstrip("0"),
            "lat": lat, "lon": lon, "x": centre.x, "y": centre.y,
            "hauteur": height, "nat_id": NAT_CHATEAU_EAU, "tpo_id": None,
            "insee": None, "adresse": "château d'eau", "source": "bdtopo",
        })
    if no_height:
        print(f"  ({no_height} water tower(s) without any height, left out)")
    return towers


def merge_water_towers(supports, towers, gap_m):
    """One entry per structure, whichever source lists it.

    The ANFR supports within `gap_m` of a tower are that tower: the nearest
    keeps its identifier and owner and takes the tower's position, height and
    kind; any other one is the same structure listed twice, and goes.
    """
    merged, dropped = 0, set()
    out = list(supports)
    for tower in towers:
        same = sorted(
            ((math.hypot(s["x"] - tower["x"], s["y"] - tower["y"]), i)
             for i, s in enumerate(out)
             if s["source"] == "anfr" and i not in dropped),
            key=lambda pair: pair[0])
        same = [i for d, i in same if d <= gap_m]
        if not same:
            out.append(tower)
            continue
        keep = out[same[0]]
        keep.update({k: tower[k] for k in ("lat", "lon", "x", "y", "hauteur", "nat_id")})
        keep["source"] = "anfr+bdtopo"
        dropped.update(same[1:])
        merged += 1
    out = [s for i, s in enumerate(out) if i not in dropped]
    print(f"  {len(towers)} BD TOPO water towers: {merged} already in ANFR "
          f"(merged, {len(dropped)} duplicate support(s) dropped), "
          f"{len(towers) - merged} new")
    return out


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


def select(candidates, top, max_operateurs):
    """The first `top` candidates (all when None), operator sites capped."""
    if max_operateurs is None:
        return candidates[:top]
    # The quota applies walking down the sorted list: keep the best
    # operator sites up to the cap, then take public ones only. Merit order
    # is therefore preserved within each category.
    shortlist, operateurs = [], 0
    for support in candidates:
        if top is not None and len(shortlist) >= top:
            break
        if not support["public"]:
            if operateurs >= max_operateurs:
                continue
            operateurs += 1
        shortlist.append(support)
    return shortlist


def write_candidates(shortlist, region):
    out = REPO / "data" / region / "candidats.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        # « \n » like sites.csv: the csv module's default « \r\n » survived an
        # append to sites.csv as a stray « \r », read back as an empty row.
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(["Name", "Latitude", "Longitude", "Owner", "Height"])
        for support in shortlist:
            # A motorway address sometimes carries a '/' (« A6 >Paris/Aire de
            # Service »): this name becomes a file name (viewshed.py), where a
            # '/' reads as a missing subfolder. gdal.Create() then fails
            # silently (returns None), and the QGIS plugin crashes on it
            # without saying why. Cleaned here, at the source.
            label = re.sub(r'[/\\:*?"<>|]', '-',
                           norm(support["adresse"]).replace(";", ","))[:40] or "no address"
            prefix = "BDTOPO" if support["source"] == "bdtopo" else "ANFR"
            writer.writerow([
                f"{prefix} {support['sup_id']} - {label}",
                round(support["lat"], 6), round(support["lon"], 6),
                ("PUBLIC" if support["public"] else "OPERATEUR")
                + f" {support['proprietaire']}".replace(";", ","),
                round(float(support["hauteur"]), 1),
            ])
    return out


def report(shortlist, out, note):
    publics = sum(1 for s in shortlist if s["public"])
    print(f"\n✅ {out.relative_to(REPO)} — {len(shortlist)} candidates, "
          f"{publics} public, {len(shortlist) - publics} operator")
    print(note)
    # Shortlist breakdown: useful to spot, before running a single viewshed,
    # whether one kind of support or one owner dominates enough to skew the
    # reading (e.g. a flood of urban buildings, or a single operator locking
    # up every usable structure).
    par_source = Counter(s["source"] for s in shortlist)
    par_nature = Counter(s["nature"] for s in shortlist)
    par_proprio = Counter(s["proprietaire"] for s in shortlist)
    print("\n   breakdown by source (anfr+bdtopo: the same structure in both):")
    for source, n in par_source.most_common():
        print(f"     {n:3d}  {source}")
    print(f"\n   breakdown by kind ({len(par_nature)} kinds):")
    for nature, n in par_nature.most_common():
        print(f"     {n:3d}  {nature}")
    print(f"\n   breakdown by owner ({len(par_proprio)} distinct):")
    for proprio, n in par_proprio.most_common():
        print(f"     {n:3d}  {proprio}")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--dept", default=None,
                        help="département code, e.g. 77 (default: \"dept\" in "
                             "data/<region>/scenarios.json)")
    parser.add_argument("--sources", default=",".join(SOURCES),
                        help=f"comma-separated, among {', '.join(SOURCES)} "
                             f"(default: both)")
    parser.add_argument("--doublon", type=float, default=50.0,
                        help="an ANFR support this close to a BD TOPO water tower "
                             "is that tower (m)")
    parser.add_argument("--anfr", type=Path,
                        default=Path.home() / "Downloads" / "SUP_SUPPORT.geojson")
    parser.add_argument("--refs", type=Path,
                        default=Path.home() / "Downloads"
                        / "20250131-export-etalab-ref-1-")
    parser.add_argument("--zone", default="dept",
                        help="zone of interest used for the score (default: dept)")
    parser.add_argument("--around-zone", metavar="ZONE",
                        help="keep every support within --radius of this zone "
                             "(data/<region>/zones/<ZONE>.gpkg), any département, "
                             "no score; see the module docstring")
    parser.add_argument("--radius", type=float, default=VIEWSHED_RADIUS_M,
                        help="with --around-zone, distance to the zone outline (m, "
                             "default: VIEWSHED_RADIUS_M)")
    parser.add_argument("--hauteur-min", type=float, default=30.0)
    parser.add_argument("--ecart", type=float, default=None,
                        help="minimum distance between two kept candidates (m; "
                             "default 3000, none with --around-zone)")
    parser.add_argument("--proche-existant", type=float, default=500.0,
                        help="below this distance, a support counts as already listed")
    parser.add_argument("--top", type=int, default=None,
                        help="number of candidates written to the CSV (default "
                             "25, all with --around-zone)")
    parser.add_argument("--publics-seulement", action="store_true")
    parser.add_argument("--max-operateurs", type=int, default=None,
                        help="caps operator supports in the list; the rest is "
                             "filled with public ones. Recurring access cost is a "
                             "structuring criterion, not a detail")
    args = parser.parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources or set(sources) - set(SOURCES):
        raise SystemExit(f"❌ --sources: pick among {', '.join(SOURCES)}")

    around = None
    if args.around_zone:
        # Distance to the polygons, not to the département: --dept, if given,
        # only narrows the pool further.
        around = zone_geometry(args.region, args.around_zone)
        args.ecart = args.ecart or 0.0
    else:
        # The ANFR register is filtered by département: no default makes sense.
        args.dept = region_dept(args.region, args.dept)
        if not args.dept:
            raise SystemExit(f"❌ no département: set \"dept\" in "
                             f"data/{args.region}/scenarios.json, or pass --dept")
        args.ecart = 3000.0 if args.ecart is None else args.ecart
        args.top = 25 if args.top is None else args.top

    natures, proprios = {NAT_CHATEAU_EAU: "château d'eau"}, {}
    if "anfr" in sources:
        if not args.anfr.exists():
            raise SystemExit(f"❌ ANFR export not found: {args.anfr}")
        natures = load_reference_table(args.refs / "SUP_NATURE.txt")
        proprios = load_reference_table(args.refs / "SUP_PROPRIETAIRE.txt")

    near = None
    if around is not None:
        print(f"▶ {' + '.join(sources)}, within {args.radius / 1000:.0f} km of zone "
              f"« {args.around_zone} »"
              + (f", département {args.dept}" if args.dept else ""))
        minx, miny, maxx, maxy = around.bounds
        r = args.radius
        tower_bounds = (minx - r, miny - r, maxx + r, maxy + r)

        def near(x, y):
            # The bounding box first: the exact distance is only worth it for
            # the few hundred supports of the whole register that pass it.
            if not (minx - r <= x <= maxx + r and miny - r <= y <= maxy + r):
                return False
            return around.distance(Point(x, y)) <= r

        tower_inside = near
    else:
        print(f"▶ {' + '.join(sources)}, département {args.dept}")
        # ANFR supports are sorted by INSEE code; towers have none, so the
        # département outline decides for them.
        outline = _dept_gdf(args.region, args.dept).to_crs("EPSG:2154").geometry.union_all()
        tower_bounds, inside_outline = outline.bounds, prep(outline)

        def tower_inside(x, y):
            return inside_outline.contains(Point(x, y))

    supports = []
    if "anfr" in sources:
        supports = load_supports(args.anfr, args.dept, near)
        print(f"  {len(supports)} distinct ANFR supports")
    if "chateaux-eau" in sources:
        if around is not None and args.dept:
            # --dept narrows the ANFR pool by INSEE code; do the same for towers.
            in_dept = prep(_dept_gdf(args.region, args.dept)
                           .to_crs("EPSG:2154").geometry.union_all())
            tower_inside = (lambda x, y, near=near:
                            near(x, y) and in_dept.contains(Point(x, y)))
        towers = load_water_towers(tower_bounds, tower_inside)
        supports = merge_water_towers(supports, towers, args.doublon)

    kept = [s for s in supports if s["nat_id"] in NATURES_UTILES]
    print(f"  {len(kept)} of a usable kind")
    kept = [s for s in kept if (s["hauteur"] or 0) >= args.hauteur_min]
    print(f"  {len(kept)} at least {args.hauteur_min:.0f} m tall")

    for support in kept:
        if support["source"] == "bdtopo":
            # No owner in BD TOPO; a water tower belongs to a commune or a
            # water syndicate far more often than not. See the docstring.
            support["public"] = True
            support["proprietaire"] = "château d'eau (BD TOPO)"
        else:
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

    if around is not None:
        for support in kept:
            support["distance_m"] = around.distance(Point(support["x"], support["y"]))
        kept.sort(key=lambda s: (s["distance_m"], -(s["hauteur"] or 0)))
        shortlist = select(thin(kept, args.ecart), args.top, args.max_operateurs)
        out = write_candidates(shortlist, args.region)
        print(f"\n{'dist':>7} {'height':>6}  {'access':<10} {'kind':<18} {'source':<11} owner")
        for support in shortlist:
            print(f"{support['distance_m'] / 1000:>5.1f}km {support['hauteur']:>5.0f}m  "
                  f"{'public' if support['public'] else 'OPERATOR':<10} "
                  f"{support['nature'][:18]:<18} {support['source']:<11} "
                  f"{support['proprietaire'][:28]}")
        report(shortlist, out,
               "   dist = to the zone outline, 0 inside it. Append these rows to\n"
               "   sites.csv: the DEM is framed on them, then compute_viewsheds.py.")
        return

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
    shortlist = select(thin(kept, args.ecart), args.top, args.max_operateurs)
    out = write_candidates(shortlist, args.region)

    print(f"\n{'score':>7} {'height':>6}  {'access':<10} {'kind':<18} {'source':<11} owner")
    for support in shortlist:
        print(f"{support['score_km2']:>7.0f} {support['hauteur']:>5.0f}m  "
              f"{'public' if support['public'] else 'OPERATOR':<10} "
              f"{support['nature'][:18]:<18} {support['source']:<11} "
              f"{support['proprietaire'][:28]}")

    report(shortlist, out,
           "   The score is an upper bound ignoring terrain: it sorts, it does not\n"
           "   conclude. Append these rows to sites.csv and rerun compute_viewsheds.py.")


if __name__ == "__main__":
    main()
