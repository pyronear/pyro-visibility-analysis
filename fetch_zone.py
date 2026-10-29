"""Fetch a zone of interest from the IGN WFS, ready for --zones / "zone".

Zones of interest other than the OLD and the département are read from
`data/<region>/zones/<name>.gpkg` (analysis_shape/zones.py). This writes that
file from a public polygon layer, so a coverage question about one forest, one
natural area or one massif needs no hand-drawn outline.

The default layer is BD TOPO's public forests (`BDTOPO_V3:foret_publique`):
every forest managed by the ONF — domaniale, communale, départementale — with
its name and its ONF identifier. Private forests are not in it. Two ways to
pick the polygon:

    --point LAT,LON   the polygon(s) of the layer containing this point; the
                      simplest when all one has is a spot on the map
    --onf ID          the forest with this ONF identifier (`F12345X`), as found
                      in `identifiants_sources`; stable across BD TOPO editions

Start with `--point`: the script prints each polygon's toponym, area and ONF
identifier, which is both the check that the zone is the right one and the
identifier to put in a reproducible `--onf` command. To read it by hand
instead, in QGIS: Layer → Add Layer → WFS, connection
`https://data.geopf.fr/wfs/ows`, layer `BDTOPO_V3:foret_publique`, then the
Identify tool on the forest (`identifiants_sources`, `ONF:F12345X`).

    uv run python fetch_zone.py --region <region> --name <zone> --point 44.65,5.12
    uv run python fetch_zone.py --region <region> --name <zone> --onf F12345X

Any other polygon layer of the same WFS works with `--point` and `--layer`
(its GetCapabilities lists them; `--onf` is specific to forests). The
zone is written in Lambert-93, layer `zone` (the one build_qgis_project.py
reads), and keeps the source attributes, so the toponym and the ONF identifier
travel with it. Then, in `data/<region>/scenarios.json`:

    "zone": "<zone>", "zone_libelle": "<label shown in QGIS>"

and `summary.py` / `prioritise_sites.py` take `--zones <zone>`. A zone fetched
again replaces the previous file.
"""

import argparse
import json
import os
import urllib.parse
import urllib.request

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas imports

import geopandas as gpd  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.geometry import Point  # noqa: E402

from config import REGION  # noqa: E402

WFS = "https://data.geopf.fr/wfs/ows"
DEFAULT_LAYER = "BDTOPO_V3:foret_publique"


def get_features(layer, **params):
    query = {
        "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
        "TYPENAMES": layer, "OUTPUTFORMAT": "application/json",
        "SRSNAME": "EPSG:2154", **params,
    }
    url = f"{WFS}?{urllib.parse.urlencode(query)}"
    with urllib.request.urlopen(url, timeout=120) as response:
        data = json.load(response)
    if not data.get("features"):
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")
    return gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:2154")


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
    return get_features(DEFAULT_LAYER, CQL_FILTER=(
        f"identifiants_sources LIKE '%{onf_id.strip().upper()}%'"))


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
    parser.add_argument("--layer", default=DEFAULT_LAYER,
                        help=f"WFS polygon layer for --point (default: {DEFAULT_LAYER})")
    args = parser.parse_args()

    if args.point:
        lat, lon = (float(v) for v in args.point.split(","))
        gdf = by_point(args.layer, lat, lon)
        where = f"containing {lat:.5f}, {lon:.5f} in {args.layer}"
    else:
        gdf = by_onf(args.onf)
        where = f"with ONF identifier {args.onf} in {DEFAULT_LAYER}"
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

    label = "toponyme" if "toponyme" in gdf.columns else None
    print(f"✅ {path} — {len(gdf)} polygon(s) {where}")
    for _, row in gdf.iterrows():
        name = row[label] if label else "(no toponym)"
        # `identifiants_sources` reads « ONF:F12345X »; --onf takes the part
        # after the colon.
        sources = str(row.get("identifiants_sources") or "")
        onf = next((s.split(":", 1)[1] for s in sources.split("/")
                    if s.strip().startswith("ONF:")), None)
        print(f"   {name} — {row.geometry.area / 1e6:,.1f} km²"
              + (f" — --onf {onf}" if onf else ""))
    if len(gdf) > 1:
        print("   ⚠️  several polygons: the zone is their union. Use --onf to "
              "keep a single forest.")
    print(f'   Next: "zone": "{args.name}" in data/{args.region}/scenarios.json, '
          f"--zones {args.name} for summary.py / prioritise_sites.py")


if __name__ == "__main__":
    main()
