"""Readable coverage summary, plus a QGIS-ready points layer.

`output.csv` holds the numbers but in square metres, which makes it awkward to
read while working in QGIS.
This writes two things in the region's output folder:

    summary.csv               site, area in km², share of the viewshed disc
    sites_with_coverage.gpkg  the sites as points, carrying `area_km2`

Load the GeoPackage in QGIS and label the points with `area_km2` to see each
site's coverage on the map.

With `--zones`, each site also gets the share of its coverage that falls inside
a zone of interest. That distinction is not cosmetic: in a test département half
of what the cameras saw lay in the neighbouring départements, so the raw union
overstates the operational result twofold.

Usage:
    uv run python summary.py
    uv run python summary.py --zones dept --dept 77
"""

import argparse
import glob
import json
import math
import os

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas imports

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402

import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from config import REGION, VIEWSHED_RADIUS_M  # noqa: E402
from analysis_shape.area_analysis import coverage  # noqa: E402
from analysis_shape.gestionnaires import categoriser, charger  # noqa: E402
from analysis_shape.zones import load_zones  # noqa: E402

def normalise(name):
    """macOS stores filenames in NFD, sites.csv is NFC — join on NFC."""
    import unicodedata
    return unicodedata.normalize("NFC", str(name))


def detection_radius(output_dir):
    """Radius the viewsheds in `output_dir` were actually computed with.

    `main.py` records it in run.json. Falling back to config.py would relabel a
    region computed at 15 km as soon as the default changes, so say plainly when
    the file is missing rather than quietly trusting the current setting.
    """
    path = os.path.join(output_dir, "run.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return int(json.load(handle)["viewshed_radius_m"]), "run.json"
    return VIEWSHED_RADIUS_M, f"config.py — {path} missing, to check"


def read_mask(path):
    """Binary visibility mask, nodata treated as not visible."""
    with rasterio.open(path) as src:
        band = src.read(1)
        if src.nodata is not None:
            band = np.where(band == src.nodata, 0, band)
    return band > 0


def zone_columns(region, output_dir, summary, zone_names, dept):
    """Per-site area inside each zone, plus the deduplicated union inside it.

    Returns the union figures separately: summing per-site areas double-counts
    every overlap, which is exactly what the union is there to avoid.
    """
    viewsheds = {
        normalise(os.path.basename(p))[len("viewshed_"):-len(".tif")]: p
        for p in sorted(glob.glob(os.path.join(output_dir, "viewsheds_geotiff",
                                               "*.tif")))
    }
    if not viewsheds:
        raise SystemExit(f"❌ no viewshed in {output_dir}/viewsheds_geotiff")

    reference = next(iter(viewsheds.values()))
    zones = load_zones(region, zone_names, reference, dept)

    union = None
    for path in viewsheds.values():
        mask = read_mask(path)
        union = mask if union is None else (union | mask)

    for zone in zones:
        column = f"km2_{zone.name}"
        summary[column] = [
            round(zone.covered_km2(read_mask(viewsheds[site])), 1)
            if site in viewsheds else None
            for site in summary["site"]
        ]
    return zones, union


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--zones", default=None,
                        help="comma-separated zones of interest, e.g. dept,old")
    parser.add_argument("--dept", default=None,
                        help="département code for the « dept » zone "
                             "(default: \"dept\" in data/<region>/scenarios.json)")
    parser.add_argument("--radius-km", type=float, default=None,
                        help="override the radius read from output/run.json")
    args = parser.parse_args()

    region = args.region
    output_dir = os.path.join("data", region, "output")
    metrics_path = os.path.join(output_dir, "output.csv")
    if not os.path.exists(metrics_path):
        raise SystemExit(f"❌ {metrics_path} not found — run main.py first")

    metrics = pd.read_csv(metrics_path, delimiter=";")
    metrics["Site"] = metrics["Site"].map(normalise)

    # Reference disc for `pct_of_disc`: the same radius the plugin was given.
    if args.radius_km is not None:
        radius_m, radius_source = int(args.radius_km * 1000), "--radius-km"
    else:
        radius_m, radius_source = detection_radius(output_dir)
    disc_km2 = math.pi * radius_m ** 2 / 1e6
    summary = pd.DataFrame({
        "site": metrics["Site"],
        "area_km2": (metrics["Surface"].astype(float) / 1e6).round(1),
    })
    summary["pct_of_disc"] = (100 * summary["area_km2"] / disc_km2).round(1)
    summary = summary.sort_values("area_km2", ascending=False).reset_index(drop=True)

    zones, union_mask = (None, None)
    if args.zones:
        names = [n.strip() for n in args.zones.split(",") if n.strip()]
        zones, union_mask = zone_columns(region, output_dir, summary, names,
                                         args.dept)

    summary_path = os.path.join(output_dir, "summary.csv")
    summary.to_csv(summary_path, sep=";", index=False)

    sites = pd.read_csv(os.path.join("data", region, "sites.csv"), delimiter=";")
    sites["Name"] = sites["Name"].map(normalise)
    merged = sites.merge(summary, left_on="Name", right_on="site", how="left")

    # `categorie` carries the access cost and colours the points in the QGIS
    # project; « en place » wins, as that is what one wants to see first.
    table = charger(region)
    deployed = (merged["Status"].astype(str).str.strip() == "EN PLACE"
                if "Status" in merged.columns
                else merged["Owner"].astype(str).str.strip() == "EN PLACE")
    merged["categorie"] = [
        "en place" if flag else categoriser(owner, table)
        for flag, owner in zip(deployed, merged["Owner"])
    ]

    colonnes = ["Name", "Height", "categorie", "area_km2", "pct_of_disc"]
    colonnes += [c for c in merged.columns if c.startswith("km2_")]
    points = gpd.GeoDataFrame(
        merged[colonnes],
        geometry=gpd.points_from_xy(merged["Longitude"], merged["Latitude"]),
        crs="EPSG:4326",
    ).to_crs("EPSG:2154")
    points_path = os.path.join(output_dir, "sites_with_coverage.gpkg")
    points.to_file(points_path, driver="GPKG", layer="sites")

    print(f"\nCoverage — {region}   ({radius_m / 1000:.0f} km disc "
          f"= {disc_km2:.0f} km², from {radius_source})\n")
    width = max(len(s) for s in summary["site"])
    for _, row in summary.iterrows():
        line = (f"  {row['site']:<{width}}  {row['area_km2']:>7.1f} km²  "
                f"{row['pct_of_disc']:>5.1f}% of disc")
        for zone in (zones or []):
            value = row.get(f"km2_{zone.name}")
            line += f"  | {zone.name} {value if value is not None else 0:>7.1f} km²"
        print(line)

    fusion = os.path.join(output_dir, "fusion", "fusion_or_all_sites.tif")
    if os.path.exists(fusion):
        union_km2 = coverage(fusion) / 1e6
        total = summary["area_km2"].sum()
        print(f"\n  {'UNION (deduplicated)':<{width}}  {union_km2:>7.1f} km²")
        print(f"  {'overlap (counted twice)':<{width}}  {total - union_km2:>7.1f} km²")

    if zones and union_mask is not None:
        print()
        for zone in zones:
            seen = zone.covered_km2(union_mask)
            print(f"  {'UNION inside « ' + zone.name + ' »':<{width}}  "
                  f"{seen:>7.1f} km²  "
                  f"{100 * seen / zone.reference_km2:>5.1f}% of the zone "
                  f"({zone.reference_km2:,.0f} km²)")

    print(f"\n✅ {summary_path}")
    print(f"✅ {points_path}  — load in QGIS and label with `area_km2`")


if __name__ == "__main__":
    main()
