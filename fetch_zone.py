"""Fetch a zone of interest from the IGN WFS, ready for --zones / "zone".

Zones of interest other than the département are read from
`data/<region>/zones/<name>.gpkg` (analysis_shape/zones.py). This writes that
file from a public polygon layer, so a coverage question about one forest,
every forest of a kind, or the OLD needs no hand-drawn outline.

A source is a named WFS layer plus, optionally, a filter on its attributes:

    forets-publiques   BD TOPO public forests (`BDTOPO_V3:foret_publique`):
                       every ONF-managed forest — domaniale, communale,
                       départementale — with its name and ONF identifier.
                       Private forests are not in it. The default.
    forets-domaniales  the same layer, `nature = Forêt domaniale` only
    old                brush-clearing obligation zones
                       (`DEBROUSSAILLEMENT:debroussaillement`)

Three ways to pick the polygons:

    --point LAT,LON   the polygon(s) of the source containing this point; the
                      simplest when all one has is a spot on the map
    --onf ID          the forest with this ONF identifier (`F12345X`), as found
                      in `identifiants_sources`; stable across BD TOPO editions
    --dept [NN]       every polygon of the source in the département, clipped
                      to its outline; without NN, "dept" in scenarios.json

Start with `--point`: the script prints each polygon's toponym, area and ONF
identifier, which is both the check that the zone is the right one and the
identifier to put in a reproducible `--onf` command. To read it by hand
instead, in QGIS: Layer → Add Layer → WFS, connection
`https://data.geopf.fr/wfs/ows`, layer `BDTOPO_V3:foret_publique`, then the
Identify tool on the forest (`identifiants_sources`, `ONF:F12345X`).

    uv run python fetch_zone.py --region <region> --name <zone> --point 44.65,5.12
    uv run python fetch_zone.py --region <region> --name <zone> --onf F12345X
    uv run python fetch_zone.py --region <region> --name forets-domaniales \\
        --source forets-domaniales --dept 78
    uv run python fetch_zone.py --region <region> --name old --source old --dept 13

`--dept` clips to the outline, so a forest across the border counts for its
part in the département only, like the `dept` zone. The WFS returns whole
polygons that touch the request: clipping, not summing, is what keeps the
area right. Any other polygon layer of the same WFS works with `--point` or
`--dept` and `--layer` (its GetCapabilities lists them; `--onf` is specific
to forests). The zone is written in Lambert-93, layer `zone` (the one
build_qgis_project.py reads), and keeps the source attributes, so the toponym
and the ONF identifier travel with it. Then, in `data/<region>/scenarios.json`:

    "zone": "<zone>", "zone_libelle": "<label shown in QGIS>"

and `summary.py` / `prioritise_sites.py` take `--zones <zone>`. A zone named
`old` replaces the former `data/<region>/old_debroussaillement.gpkg`, still
read when there is none. A zone fetched again replaces the previous file.
"""

import argparse
import os

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas imports

import geopandas as gpd  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from analysis_shape.wfs import bbox_l93, get_features  # noqa: E402
from analysis_shape.zones import _dept_gdf, _normalise_dept, region_dept  # noqa: E402
from config import REGION  # noqa: E402

FORESTS = "BDTOPO_V3:foret_publique"

# `where` filters on attributes, after the request; `dept_field` lets the
# server select a département's polygons instead of a bounding box, which
# also brings in the neighbours'.
SOURCES = {
    "forets-publiques": {"layer": FORESTS},
    "forets-domaniales": {"layer": FORESTS, "where": {"nature": "Forêt domaniale"}},
    "old": {"layer": "DEBROUSSAILLEMENT:debroussaillement", "dept_field": "dept"},
}
DEFAULT_SOURCE = "forets-publiques"


def by_point(layer, lat, lon):
    # A BBOX a few metres wide returns every polygon touching it, whatever the
    # layer calls its geometry column; containment is then checked here.
    d = 0.0001
    gdf = get_features(layer, BBOX=f"{lat - d},{lon - d},{lat + d},{lon + d},"
                                   f"urn:ogc:def:crs:EPSG::4326")
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:2154",
                                always_xy=True).transform(lon, lat)
    return gdf[gdf.contains(Point(x, y))]


def by_onf(onf_id):
    return get_features(FORESTS, CQL_FILTER=(
        f"identifiants_sources LIKE '%{onf_id.strip().upper()}%'"))


def by_dept(region, layer, dept, dept_field=None):
    outline = _dept_gdf(region, dept).to_crs("EPSG:2154")
    if dept_field:
        padded, short = _normalise_dept(dept)
        gdf = get_features(layer, CQL_FILTER=(
            f"{dept_field} IN ('{padded}', '{short}')"))
    else:
        xmin, ymin, xmax, ymax = outline.total_bounds
        gdf = get_features(layer, BBOX=bbox_l93(xmin, ymin, xmax, ymax))
    if gdf.empty:
        return gdf
    gdf = gpd.clip(gdf, outline)
    return gdf[~gdf.geometry.is_empty]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--name", required=True,
                        help="zone name: data/<region>/zones/<name>.gpkg")
    pick = parser.add_mutually_exclusive_group(required=True)
    pick.add_argument("--point", help="LAT,LON inside the wanted polygon")
    pick.add_argument("--onf", help="ONF forest identifier, e.g. F12345X")
    pick.add_argument("--dept", nargs="?", const="",
                      help="every polygon in this département, clipped to it "
                           "(alone: \"dept\" in data/<region>/scenarios.json)")
    parser.add_argument("--source", default=DEFAULT_SOURCE, choices=sorted(SOURCES),
                        help=f"named layer and filter (default: {DEFAULT_SOURCE})")
    parser.add_argument("--layer", default=None,
                        help="any other WFS polygon layer, for --point or --dept "
                             "(replaces --source)")
    args = parser.parse_args()

    source = {"layer": args.layer} if args.layer else SOURCES[args.source]
    layer = source["layer"]
    label = args.layer or f"{args.source} ({layer})"
    if args.onf and layer != FORESTS:
        raise SystemExit(f"❌ --onf only applies to {FORESTS}")

    if args.point:
        lat, lon = (float(v) for v in args.point.split(","))
        gdf = by_point(layer, lat, lon)
        where = f"containing {lat:.5f}, {lon:.5f} in {label}"
    elif args.onf:
        gdf = by_onf(args.onf)
        where = f"with ONF identifier {args.onf} in {label}"
    else:
        dept = region_dept(args.region, args.dept)
        if not dept:
            raise SystemExit(
                f"❌ --dept needs a département: pass --dept <NN>, or set "
                f"\"dept\" in data/{args.region}/scenarios.json")
        gdf = by_dept(args.region, layer, dept, source.get("dept_field"))
        where = f"in département {dept}, {label}"

    for column, value in source.get("where", {}).items():
        if not gdf.empty:
            gdf = gdf[gdf[column] == value]
    if gdf.empty:
        raise SystemExit(f"❌ no polygon {where}")

    # Nested JSON fields do not survive the GPKG driver.
    for column in gdf.columns:
        if column != "geometry" and gdf[column].map(
                lambda v: isinstance(v, (dict, list))).any():
            gdf = gdf.drop(columns=column)

    out_dir = os.path.join("data", args.region, "zones")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{args.name}.gpkg")
    if os.path.exists(path):
        os.remove(path)
    gdf.to_file(path, driver="GPKG", layer="zone")

    toponym = "toponyme" if "toponyme" in gdf.columns else None
    print(f"✅ {path} — {len(gdf)} polygon(s) {where}")
    if toponym:
        # One line per forest: BD TOPO may split one into several polygons.
        # `identifiants_sources` reads « ONF:F12345X »; --onf takes the part
        # after the colon.
        rows = {}
        for _, row in gdf.iterrows():
            sources = str(row.get("identifiants_sources") or "")
            onf = next((s.split(":", 1)[1] for s in sources.split("/")
                        if s.strip().startswith("ONF:")), None)
            key = (row[toponym] or "(no toponym)", onf)
            rows[key] = rows.get(key, 0.0) + row.geometry.area / 1e6
        for (name, onf), km2 in sorted(rows.items(), key=lambda kv: -kv[1]):
            print(f"   {name} — {km2:,.1f} km²" + (f" — --onf {onf}" if onf else ""))
    # Overlapping polygons count once, as they will in the mask.
    total = gdf.geometry.union_all().area / 1e6
    print(f"   total: {total:,.1f} km²")
    if len(gdf) > 1 and args.dept is None:
        print("   ⚠️  several polygons: the zone is their union. Use --onf to "
              "keep a single forest.")
    print(f'   Next: "zone": "{args.name}" in data/{args.region}/scenarios.json, '
          f"--zones {args.name} for summary.py / prioritise_sites.py")


if __name__ == "__main__":
    main()
