"""Compute the viewshed of every site of a region, from a terminal.

For each site of `data/<region>/sites.csv`:

  1. the observer height, corrected for the surface model (terrain.py), with
     the ground elevation fetched once and cached;
  2. `gdal_viewshed` (GDAL ≥ 3.13, in Docker unless GDAL_VIEWSHED says
     otherwise), several sites in parallel;
  3. one 0/1 mask on the full DEM grid → `output/viewsheds_geotiff/`;

then, for the region as a whole:

  4. `output/output.csv` (area per site and share of the union) and the union
     itself, `output/fusion/fusion_or_all_sites.tif`.

The detection envelope (radius, target height, Earth curvature) comes from
config.py and is recorded in `output/run.json`. Viewsheds already on disk are
skipped, which makes adding sites cheap — and is why a folder computed with
other settings is refused rather than completed.

Usage:
    make viewsheds REGION=<region>
    uv run python compute_viewsheds.py --region <region> [--workers N]
"""

import argparse
import csv
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/rasterio imports

import pandas as pd  # noqa: E402
from pyproj import Transformer  # noqa: E402

from analysis_shape.area_analysis import covered_surface  # noqa: E402
from analysis_shape.config_loader import load_config  # noqa: E402
from analysis_shape.gdal_viewshed import (  # noqa: E402
    ENGINE, check_run_metadata, compute_viewshed, curvature_coefficient,
    gdal_viewshed_command,
)
from analysis_shape.terrain import load_cache, observer_height  # noqa: E402

DEFAULT_HEIGHT = 30  # in meters, above bare ground (not an NGF altitude)


def clean_name(name):
    """The site name as a file name.

    ANFR/BD TOPO addresses sometimes carry a character illegal in a path ('/'
    in a motorway address such as « A6 >Paris/Aire de Service », a direction
    of travel with '>'…). A '/' turns the name into a missing subfolder.
    """
    return re.sub(r'[/\\:*?"<>|]', '-', name)


def write_output_csv(path, surfaces):
    rows = [{"Site": site, **values} for site, values in surfaces.items()]
    pd.DataFrame(rows, columns=["Site", "Surface", "% du total"]).to_csv(
        path, sep=";", index=False, encoding="utf-8")


def main():
    config = load_config()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default=config.REGION)
    parser.add_argument("--workers", type=int, default=os.cpu_count(),
                        help="sites computed in parallel (default: all cores)")
    args = parser.parse_args()

    region_dir = os.path.join("data", args.region)
    csv_path = os.path.join(region_dir, "sites.csv")
    dem_path = os.path.join(region_dir, "dem_l93.tif")
    output_dir = os.path.join(region_dir, "output")
    viewsheds_dir = os.path.join(output_dir, "viewsheds_geotiff")
    fusion_dir = os.path.join(output_dir, "fusion")
    for path in (csv_path, dem_path):
        if not os.path.exists(path):
            raise SystemExit(f"❌ {path} not found")
    os.makedirs(viewsheds_dir, exist_ok=True)
    os.makedirs(fusion_dir, exist_ok=True)

    radius = config.VIEWSHED_RADIUS_M
    target_height = config.TARGET_HEIGHT_M
    earth_curvature = getattr(config, "EARTH_CURVATURE", True)
    refraction = getattr(config, "REFRACTION", 0.13)
    curvature_coeff = curvature_coefficient(earth_curvature, refraction)
    print(f"▶ REGION = {args.region}, RADIUS = {radius} m, "
          f"TARGET_HEIGHT = {target_height} m, "
          f"curvature {'on (refraction ' + str(refraction) + ')' if earth_curvature else 'off'}")

    # Checked before anything else, even with nothing left to compute: a
    # folder from another setting must not be completed, nor summarised as if
    # it matched the current one.
    envelope = {
        "viewshed_radius_m": radius,
        "target_height_m": target_height,
        "earth_curvature": earth_curvature,
        "refraction": refraction if earth_curvature else None,
        "engine": ENGINE,
    }
    check_run_metadata(output_dir, viewsheds_dir, envelope)

    with open(csv_path, newline="", encoding="utf-8") as handle:
        sites = list(csv.DictReader(handle, delimiter=";"))

    # Observer heights first, one site at a time: they may query the IGN MNT
    # and they share one cache file.
    to_l93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    ground_cache = load_cache(csv_path)
    jobs = []
    for row in sites:
        name = clean_name(row["Name"])
        output_file = os.path.join(viewsheds_dir, f"viewshed_{name}.tif")
        if os.path.exists(output_file):
            continue
        x, y = to_l93.transform(float(row["Longitude"]), float(row["Latitude"]))
        height = float(row["Height"]) if row["Height"] else DEFAULT_HEIGHT
        obs = observer_height(row["Name"], x, y, height, dem_path, csv_path,
                              ground_cache)
        jobs.append((name, output_file, x, y, obs))

    skipped = len(sites) - len(jobs)
    if skipped:
        print(f"   {skipped} viewsheds already computed, skipped")

    if jobs:
        with gdal_viewshed_command() as (prefix, version):
            check_run_metadata(output_dir, viewsheds_dir,
                               {**envelope, "gdal_version": version})
            print(f"   GDAL {version}, {len(jobs)} sites, {args.workers} in parallel")

            def work(job):
                name, output_file, x, y, obs = job
                compute_viewshed(prefix, dem_path, output_file, x, y, obs,
                                 target_height, radius, curvature_coeff)
                return name

            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for i, name in enumerate(pool.map(work, jobs), skipped + 1):
                    print(f"[{i}/{len(sites)}] {name}")
            print(f"   {len(jobs)} viewsheds in {time.perf_counter() - start:.0f} s")

    surfaces = covered_surface(viewsheds_dir, fusion_dir, csv_path)
    write_output_csv(os.path.join(output_dir, "output.csv"), surfaces)
    print(f"✅ {len(surfaces)} viewsheds → {viewsheds_dir}")


if __name__ == "__main__":
    main()
