import argparse
import os
import csv
import time
import zipfile
import random

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas/rasterio imports

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import geopandas as gpd  # noqa: E402
import rasterio  # noqa: E402
from rasterio.features import shapes  # noqa: E402
from rasterio.warp import calculate_default_transform, reproject, Resampling  # noqa: E402
from shapely.geometry import shape, MultiPolygon  # noqa: E402
from PIL import Image  # noqa: E402

from analysis_shape.names import site_name  # noqa: E402

# === CONFIGURATION ===
from config import REGION  # set the region in config.py
folder = REGION

# A ground overlay does not need 5 m pixels. Capping the PNG keeps the RGBA
# buffer small: at 5 m an uncapped overlay is ~11400 x 8900, i.e. ~400 MB for
# the RGBA array alone, plus as much again while PIL encodes it.
MAX_PNG_PX = 4000

# Geometry cleanup for the GeoPackage. Measured on a test region at 5 m over a 225 km²
# window: dropping polygons under 500 m² keeps 3.6 % of them for -0.52 % of
# area; simplifying at 10 m costs +0.08 %. `area_km2` is counted on the raster,
# so the published figures are unaffected either way.
MIN_POLYGON_AREA = 500.0  # m², 0 disables
SIMPLIFY_TOLERANCE = 10.0  # m, 0 disables

HERE = os.path.dirname(os.path.abspath(__file__))
stations_csv_path = os.path.join(HERE, "data", folder, "sites.csv")
viewshed_folder = os.path.join(HERE, "data", folder, "output", "viewsheds_geotiff")
output_root = os.path.join(HERE, f"kmz_output_{folder}")
gpkg_path = os.path.join(output_root, f"viewsheds_{folder}.gpkg")
os.makedirs(output_root, exist_ok=True)


# === HELPER FUNCTIONS ===

def get_station_info(station_name):
    """The sites.csv row behind a `viewshed_<Name>` file stem, or None."""
    wanted = site_name(station_name.removeprefix("viewshed_"))
    with open(stations_csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile, delimiter=";")
        for row in reader:
            if site_name(row["Name"]) == wanted:
                return {
                    "lat": float(row["Latitude"]),
                    "lon": float(row["Longitude"]),
                    "name": row["Name"],
                }
    return None


def generate_random_color():
    return [random.randint(50, 255), random.randint(50, 255), random.randint(50, 255), 180]


def convert_viewshed_to_kmz(input_tif):
    basename = os.path.splitext(os.path.basename(input_tif))[0]
    station_info = get_station_info(basename)
    if not station_info:
        print(f"Station info not found for: {basename}")
        return

    output_dir = os.path.join(output_root, basename)
    os.makedirs(output_dir, exist_ok=True)

    output_png = os.path.join(output_dir, f"{basename}.png")
    output_kml = os.path.join(output_dir, "doc.kml")
    output_kmz = os.path.join(output_root, f"{basename}.kmz")

    # === STEP 1: Reproject to WGS84, downsampled to MAX_PNG_PX ===
    # Done with rasterio rather than osgeo.gdal: the GDAL Python bindings are
    # not installable from pyproject.toml, and rasterio is already a dependency.
    with rasterio.open(input_tif) as src:
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds)
        scale = max(1.0, max(width, height) / MAX_PNG_PX)
        transform, width, height = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds,
            dst_width=int(width / scale), dst_height=int(height / scale))

        arr = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(src, 1),
            destination=arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.nearest,
        )

    # === STEP 2: Convert to color PNG with transparency ===
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    color = generate_random_color()
    rgba[arr == 1] = color  # Apply color only where viewshed is visible
    Image.fromarray(rgba, mode="RGBA").save(output_png)

    # === STEP 3: Get bounds for KML ===
    xmin = transform.c
    ymax = transform.f
    xmax = xmin + transform.a * width
    ymin = ymax + transform.e * height

    # === STEP 4: Write KML with camera point + overlay ===
    kml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>{basename}</name>
    <Placemark>
      <name>{station_info['name']}</name>
      <Point>
        <coordinates>{station_info['lon']},{station_info['lat']},0</coordinates>
      </Point>
    </Placemark>
    <GroundOverlay>
      <name>{basename}</name>
      <Icon>
        <href>{os.path.basename(output_png)}</href>
      </Icon>
      <LatLonBox>
        <north>{ymax}</north>
        <south>{ymin}</south>
        <east>{xmax}</east>
        <west>{xmin}</west>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>"""

    with open(output_kml, "w") as f:
        f.write(kml_content)

    # === STEP 5: Zip PNG + KML into KMZ ===
    with zipfile.ZipFile(output_kmz, "w", zipfile.ZIP_DEFLATED) as kmz:
        kmz.write(output_kml, "doc.kml")
        kmz.write(output_png, os.path.basename(output_png))

    print(f"KMZ exported: {output_kmz}")


def polygonize_viewshed(input_tif, site_name, min_polygon_area=MIN_POLYGON_AREA,
                        simplify_tolerance=SIMPLIFY_TOLERANCE):
    """Vectorize a binary viewshed raster into a single (Multi)Polygon.

    `area_km2` is counted on the raster, so it stays exact whatever the
    geometry cleanup does.
    """
    with rasterio.open(input_tif) as src:
        arr = src.read(1)
        mask = (arr == 1).astype("uint8")
        visible_pixels = int(mask.sum())
        if visible_pixels == 0:
            return None
        pixel_area = abs(src.transform.a * src.transform.e)
        area_km2 = visible_pixels * pixel_area / 1e6
        polys = [
            shape(geom)
            for geom, val in shapes(mask, mask=mask > 0, transform=src.transform)
            if val == 1
        ]
        crs = src.crs

    # A 5 m MNS viewshed is riddled with single-tree holes: ~90 000 polygons per
    # site, most of them a handful of pixels. Keeping them makes the GeoPackage
    # unusable — folium cannot render it and even reading it back is slow —
    # while contributing almost nothing: dropping everything under 500 m² (a
    # 22 x 22 m patch) removes 96 % of the polygons for 0.5 % of the area.
    if min_polygon_area:
        polys = [p for p in polys if p.area >= min_polygon_area]
        if not polys:
            return None
    if simplify_tolerance:
        polys = [p.simplify(simplify_tolerance) for p in polys]
        polys = [p for p in polys if not p.is_empty]

    if not polys:
        return None

    # `shapes()` returns disjoint connected components, so there is nothing to
    # merge: a MultiPolygon of the parts is the same geometry. unary_union was
    # doing the full merge anyway, which is cheap on the ~5 000 polygons a
    # 23.8 m SRTM viewshed produces and pathological on the ~140 000 that a 5 m
    # MNS viewshed produces — every isolated tree punches its own hole.
    geom = MultiPolygon(polys)

    return gpd.GeoDataFrame(
        {"site_name": [site_name], "area_km2": [area_km2]},
        geometry=[geom], crs=crs,
    )


def export_geopackage(viewshed_files, min_polygon_area=MIN_POLYGON_AREA,
                      simplify_tolerance=SIMPLIFY_TOLERANCE):
    frames = []
    total = len(viewshed_files)
    for index, tif_file in enumerate(viewshed_files, start=1):
        basename = os.path.splitext(os.path.basename(tif_file))[0]
        info = get_station_info(basename)
        site_name = info["name"] if info else basename

        print(f"[{index}/{total}] vectorizing {site_name}…", flush=True)
        started = time.time()
        gdf = polygonize_viewshed(tif_file, site_name,
                                  min_polygon_area, simplify_tolerance)
        if gdf is None:
            print(f"Empty viewshed, skipping polygon for: {basename}")
            continue

        parts = len(gdf.geometry.iloc[0].geoms)
        print(f"          {parts} polygons in {time.time() - started:.1f}s",
              flush=True)
        frames.append(gdf)

    if not frames:
        print("No polygons to write.")
        return

    merged = gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), crs=frames[0].crs
    ).to_crs("EPSG:4326")
    merged.to_file(gpkg_path, driver="GPKG", layer="viewsheds")
    print(f"GeoPackage exported: {gpkg_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export viewsheds as a GeoPackage, and optionally as KMZ.")
    parser.add_argument(
        "--kmz", action="store_true",
        help="also write one Google Earth KMZ ground overlay per site. Off by "
             "default: it is the expensive part and is not needed by "
             "visualize.py, which reads the GeoPackage.")
    parser.add_argument(
        "--min-polygon-area", type=float, default=MIN_POLYGON_AREA,
        help=f"drop polygons smaller than this, in m² (default "
             f"{MIN_POLYGON_AREA:g}; 0 keeps everything). Reported areas are "
             f"counted on the raster and are not affected.")
    parser.add_argument(
        "--simplify", type=float, default=SIMPLIFY_TOLERANCE,
        help=f"boundary simplification tolerance in m (default "
             f"{SIMPLIFY_TOLERANCE:g}; 0 disables)")
    args = parser.parse_args()

    viewshed_files = [
        os.path.join(viewshed_folder, f)
        for f in os.listdir(viewshed_folder)
        if f.endswith(".tif")
    ]

    if args.kmz:
        for tif_file in viewshed_files:
            convert_viewshed_to_kmz(tif_file)

    export_geopackage(viewshed_files, args.min_polygon_area, args.simplify)


if __name__ == "__main__":
    main()
