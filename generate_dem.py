import subprocess
from pathlib import Path
import pandas as pd
import geopandas as gpd
from shapely.geometry import box
import rioxarray
import numpy as np
from rasterio.enums import Resampling
import os


# === CONFIG ===
CSV_PATH = "data/sdis-67/sites.csv"  # Update this path to your CSV
OUTPUT_DIR = os.path.join(os.path.dirname(CSV_PATH), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)
DEM_EIO_OUTPUT = os.path.join(OUTPUT_DIR, "srtm_dem.tif")
DEM_FINAL_OUTPUT = os.path.join(OUTPUT_DIR, "dem_l93.tif")
BUFFER_KM = 30
PRODUCT = "SRTM1"


def compute_dem_bbox_around_stations(df, buffer_km=30):
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["Longitude"], df["Latitude"]), crs="EPSG:4326")
    gdf_projected = gdf.to_crs(epsg=3857)
    bounds = gdf_projected.total_bounds
    minx, miny, maxx, maxy = bounds
    buffered_bounds = box(minx - buffer_km * 1000, miny - buffer_km * 1000,
                          maxx + buffer_km * 1000, maxy + buffer_km * 1000)
    buffered_bounds_geo = gpd.GeoSeries([buffered_bounds], crs="EPSG:3857").to_crs(epsg=4326).total_bounds
    return tuple(buffered_bounds_geo)


def download_dem_eio(bbox, out_path="srtm_dem.tif", product="SRTM1"):
    """
    Downloads a clipped SRTM DEM using eio CLI tool for the specified bbox.
    Requires `eio` installed and working (via `elevation` package).
    """
    cmd = [
        "eio", "--product", product, "clip",
        "--bounds", *map(str, bbox),
        "--output", out_path
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("🚨 Command failed:")
        print(result.stderr)
        raise RuntimeError("DEM download failed")
    elif not Path(out_path).exists():
        raise FileNotFoundError("DEM file not found after eio execution")
    else:
        print(f"✅ DEM downloaded: {out_path}")




def reproject_and_save_dem(input_path, output_path, target_crs="EPSG:2154", nodata_val=-9999):
    dem_data = rioxarray.open_rasterio(input_path, masked=True).squeeze()

    if dem_data.rio.crs is None:
        dem_data.rio.write_crs("EPSG:4326", inplace=True)

    dem_l93 = dem_data.rio.reproject(
        target_crs,
        resampling=Resampling.bilinear,
        nodata=np.nan
    )

    dem_l93_int16 = dem_l93.fillna(nodata_val).round().astype(np.int16)
    dem_l93_int16.rio.write_nodata(nodata_val, inplace=True)
    dem_l93_int16.rio.write_crs(target_crs, inplace=True)
    dem_l93_int16.rio.to_raster(output_path, compress="LZW")

    print(f"✅ Reprojected DEM saved to {output_path}")


def main():
    print("Loading station data")
    df_antennes = pd.read_csv(CSV_PATH, delimiter=";")

    print("Computing bounding box with buffer")
    dem_bbox = compute_dem_bbox_around_stations(df_antennes, buffer_km=BUFFER_KM)

    print("Downloading DEM using eio")
    download_dem_eio(dem_bbox, out_path=DEM_EIO_OUTPUT, product=PRODUCT)

    print("Reprojecting and saving DEM")
    reproject_and_save_dem(DEM_EIO_OUTPUT, DEM_FINAL_OUTPUT)

    print("🎉 Done!")


if __name__ == "__main__":
    main()
