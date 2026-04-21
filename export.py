import os
import csv
import zipfile
import random
from osgeo import gdal
import numpy as np
import pandas as pd
import geopandas as gpd
import rasterio
from rasterio.features import shapes
from shapely.geometry import shape, MultiPolygon
from shapely.ops import unary_union
from PIL import Image

# === CONFIGURATION ===
folder = "noord-limburg"

HERE = os.path.dirname(os.path.abspath(__file__))
stations_csv_path = os.path.join(HERE, "data", folder, "sites.csv")
viewshed_folder = os.path.join(HERE, "data", folder, "output", "viewsheds_geotiff")
output_root = os.path.join(HERE, f"kmz_output_{folder}")
gpkg_path = os.path.join(output_root, f"viewsheds_{folder}.gpkg")
os.makedirs(output_root, exist_ok=True)


# === HELPER FUNCTIONS ===

def get_station_info(station_name):
    with open(stations_csv_path, newline="", encoding="utf-8") as csvfile:
        reader = csv.DictReader(csvfile, delimiter=";")
        for row in reader:
            if row["Name"] in station_name:
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

    reprojected_tif = os.path.join(output_dir, f"{basename}_wgs84.tif")
    output_png = os.path.join(output_dir, f"{basename}.png")
    output_kml = os.path.join(output_dir, "doc.kml")
    output_kmz = os.path.join(output_root, f"{basename}.kmz")

    # === STEP 1: Reproject to WGS84 ===
    gdal.Warp(reprojected_tif, input_tif, dstSRS="EPSG:4326", resampleAlg="near")

    # === STEP 2: Convert to color PNG with transparency ===
    ds = gdal.Open(reprojected_tif)
    arr = ds.ReadAsArray()
    rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    color = generate_random_color()
    rgba[arr == 1] = color  # Apply color only where viewshed is visible
    Image.fromarray(rgba, mode="RGBA").save(output_png)

    # === STEP 3: Get bounds for KML ===
    gt = ds.GetGeoTransform()
    xmin = gt[0]
    ymax = gt[3]
    xmax = xmin + gt[1] * ds.RasterXSize
    ymin = ymax + gt[5] * ds.RasterYSize

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


def polygonize_viewshed(input_tif, site_name):
    """Vectorize a binary viewshed raster into a single dissolved (Multi)Polygon."""
    with rasterio.open(input_tif) as src:
        arr = src.read(1)
        mask = (arr == 1).astype("uint8")
        if mask.sum() == 0:
            return None
        polys = [
            shape(geom)
            for geom, val in shapes(mask, mask=mask > 0, transform=src.transform)
            if val == 1
        ]
        crs = src.crs

    if not polys:
        return None

    geom = unary_union(polys)
    if geom.geom_type == "Polygon":
        geom = MultiPolygon([geom])

    return gpd.GeoDataFrame({"site_name": [site_name]}, geometry=[geom], crs=crs)


def export_geopackage(viewshed_files):
    frames = []
    for tif_file in viewshed_files:
        basename = os.path.splitext(os.path.basename(tif_file))[0]
        info = get_station_info(basename)
        site_name = info["name"] if info else basename
        gdf = polygonize_viewshed(tif_file, site_name)
        if gdf is None:
            print(f"Empty viewshed, skipping polygon for: {basename}")
            continue
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
    viewshed_files = [
        os.path.join(viewshed_folder, f)
        for f in os.listdir(viewshed_folder)
        if f.endswith(".tif")
    ]

    for tif_file in viewshed_files:
        convert_viewshed_to_kmz(tif_file)

    export_geopackage(viewshed_files)


if __name__ == "__main__":
    main()
