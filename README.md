# PyroNear Visibility Analysis

Automated analysis of coverage and visibility zones using QGIS and Python.

---

## Overview

This repository provides a script-based solution for evaluating viewsheds (areas visible from high points), calculating coverage, and analyzing overlaps between them. It integrates with QGIS and uses raster-based elevation data.

---

## Contents

- `./data`: Input and output data (DEM files, input CSV, output CSV).
- `./src`: All Python scripts.
  - `viewshed.py`: Creates viewsheds from high points.
  - `area_analysis.py`: Computes coverage metrics and overlaps.
  - `utils.py`: General-purpose functions (I/O, normalization, display).
- `./viewsheds_geotiff`: Raw viewsheds generated by the tool.
- `./normalized`: Viewsheds after NaN removal.
- `./fusion`: Viewshed files resulting from fusion operations (OR/AND).
- `main.py`: The main script to run the analysis.

---

## Requirements

- QGIS (https://www.qgis.org/en/site/forusers/alldownloads.html)
- Plugins:
  - SRTM Downloader (for DEM files)
  - HCMGIS (for base maps)
- EarthData account for DEM data: https://urs.earthdata.nasa.gov/users/new

---

## DEM Preparation (QGIS)

1. Install plugins: SRTM Downloader and HCMGIS.
2. Set map to Google Maps: `HCMGIS > BaseMaps > Google Maps`.
3. Use SRTM Downloader:
   - Either set canvas extent or input coordinates manually.
   - Login to EarthData when prompted.
4. Merge DEM tiles: Use "Merge" tool.
   - Output format: `Int16`
   - Save as: `./data/dem_file.tif`
5. Reproject the DEM:
   - Use "Warp (Reproject)" tool.
   - Target CRS: UTM zone for your area (e.g., EPSG:32631)
   - Save as: `./data/dem_file_projected.tif`

---

## Running the Code (QGIS)

1. Open QGIS > Python Console > Show Editor
2. Load `main.py`
3. Run the script using the "Play" button

---

## Functionality

### Viewshed Generation (`viewshed.py`)
- Reads a CSV of observation points (lat/lon, height, name).
- Generates a viewshed (visibility map) for each point.
- Reprojects to appropriate CRS.
- Applies a visual style (`.qml`).
- Saves results as individual `.tif` files.

### Normalization (`utils.py`)
- Removes NaN values from `.tif` files (required for further analysis).
- Output files are saved to `./normalized`.

### Fusion (`utils.py`)
- Logical fusion of viewsheds using OR or AND.
- Results saved to `./fusion`.

### Coverage Analysis (`area_analysis.py`)
- Calculates:
  - Area covered by a single viewshed
  - Coverage ratio relative to the network
  - Overlap between two viewsheds

### Output
- Final metrics are stored in `./data/output.csv`.

---

## Configuration

Paths are defined in `main.py`:
- `VISILITY_ANALYSIS_PATH`: Root folder (`./analysis_shape`)
- `DATA_PATH`: `./data`
- `CSV_PATH`: Input file (`pts_hauts_x.csv`)
- `DEM_PROJECTED_PATH`: `dem_file_projected.tif`
- `VIEWSHEDS_PATH`, `NORM_VIEWSHEDS_PATH`, `FUSION_PATH`: Subdirectories for outputs
- `OUTPUT_PATH`: `./data/output.csv`

(You can externalize paths into a `config.py` file if needed.)

---

## Dependencies

Python Standard Library:
- `os`, `csv`, `numpy`

Image Processing:
- `PIL.Image`, `PIL.TiffTags`

---

## Usage Summary

1. Prepare DEM using QGIS.
2. Normalize all viewsheds using `normalize_create()`.
3. Generate KPIs using `covered_surface()`.
4. Output will be saved in `output.csv`.

---

## Notes

- Viewshed generation uses QGIS native plugin `Visibility Analysis`.
- Normalization is required because the default plugin outputs use NaN for no-data values.
- QGIS may misinterpret the scale of `.tif` files unless color ramps are explicitly set to binary.

---
