# PyroNear Visibility Analysis

Automated analysis of coverage and visibility zones using QGIS and Python.

---

## 🔍 Overview

This repository provides a script-based solution to:

- Generate viewsheds (visibility zones) from high points
- Normalize and combine them
- Analyze coverage and overlaps
- Visualize everything within QGIS using real DEM data and basemaps

---

## 📁 Project Structure

```
.
├── data/                    # Input & output data (CSV, DEM, results)
│   ├── sdis-67/
│   │   ├── sites.csv        # Input coordinates
│   │   ├── dem_l93.tif      # Projected DEM (EPSG:2154)
│   │   └── output/          # Generated outputs (viewsheds, metrics)
├── analysis_shape/         # Core Python modules
│   ├── viewshed.py          # Viewshed creation
│   ├── area_analysis.py     # Coverage & overlap analysis
│   └── utils.py             # Helper functions
├── generate_dem.py         # Script to download and reproject DEM
├── main.py                 # Main QGIS execution script
└── README.md
```

## 📦 Installation

```bash
pip install -r requirements.txt
```

Or use the provided `.venv`.

---

## 🌍 DEM Generation (automatic)

You can now automatically download and project a DEM using:

```bash
python generate_dem.py
```

This script:
- Parses station coordinates from `sites.csv`
- Computes a bounding box with buffer
- Downloads SRTM tiles using the `eio` CLI
- Reprojects to `EPSG:2154`
- Saves the result to `data/sdis-67/dem_l93.tif`

---

## 🛰️ Running the Analysis in QGIS

1. Open **QGIS**
2. Create a **new project**
3. Open the **Python Console** → *Show Editor*
4. Load and run `main.py`

This will:
- Load your DEM and OpenStreetMap as background
- Generate and normalize viewsheds
- Compute overlaps and total coverage
- Save results to `output.csv`

---

## 🧠 Functionality

### `viewshed.py`
- Reads `sites.csv` with `Name`, `Latitude`, `Longitude`, `Height`
- Reprojects points to `EPSG:2154`
- Generates one `.tif` viewshed per point

### `utils.py`
- `normalize_create()` replaces no-data with zeros
- `display_tif()` adds raster layer with style
- `fusion_or()` and `fusion_and()` combine rasters

### `area_analysis.py`
- Uses `rasterio` to compute:
  - Area covered per viewshed
  - % of total coverage
  - Pairwise overlaps between viewsheds

---

## 📤 Output

After running `main.py`, you’ll find:

- Individual viewsheds: `data/sdis-67/output/viewsheds_geotiff/`
- Normalized viewsheds: `data/sdis-67/output/normalized/`
- Combined viewsheds: `data/sdis-67/output/fusion/`
- Coverage metrics: `data/sdis-67/output/output.csv`

---

## ✅ Quick Start

```bash
# Step 1: Generate DEM
python generate_dem.py
```

Then:

1. **Open QGIS**
2. Create a **new project**
3. Open the **Python Console** → *Show Editor*
4. Load and **run `main.py`**
5. After the script finishes, go to  
   **Menu: Project → Properties → CRS** and set it to `EPSG:2154` (Lambert-93)

> ℹ️ Note: Due to QGIS limitations, the project CRS might not fully apply during script execution. Manually setting it ensures all layers are correctly reprojected.

---


## 📝 Notes

- This project uses the **QGIS Visibility Analysis** processing tool under the hood.
- Basemap is OpenStreetMap (via XYZ tiles), aligned with EPSG:2154.
- All coordinates are reprojected from `EPSG:4326` (lat/lon) to `EPSG:2154`.
- Output rasters use LZW compression for performance.

