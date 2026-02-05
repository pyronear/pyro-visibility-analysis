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

## 🌍 Step 1: Automatic DEM Generation 

You can now automatically download and project a DEM (Digital Elevation Model):

- In `generate_dem.py`, update `CSV_PATH` to the csv containing stations you want to analyse 
- then run : 

```bash
python generate_dem.py
```

This script:
- Parses station coordinates from `sites.csv`
- Computes a bounding box with buffer
- Downloads SRTM tiles using the `eio` CLI
- Reprojects to `EPSG:2154`
- Saves the result to the folder where the provided csv is stored, named as follow `dem_l93.tif`

---

## 🛰️ Step 2: Running the Analysis in QGIS

1. In `main.py`, update `CSV_PATH` to the csv containing stations you want to analyse 
2. Open **QGIS**
3. You might need to install QGIS plugin "Visibility Analysis" (from Zoran Čučković)
4. Create a **new project**
5. In case of fail later, you might need to save the project in the working directory of the repo pyro-visibility-analysis
6. Open the **Python Console** → *Show Editor*
7. Load and run `main.py`
8. you might need to speficy first in the python console
```python
import sys
sys.path.append("/PATH_TO_THE_REPOSITORY/pyro-visibility-analysis")
```
7. **Menu: Project → Properties → CRS** and set it to `EPSG:2154` (Lambert-93)
> ℹ️ Note: Due to QGIS limitations, the project CRS might not fully apply during script execution. Manually setting it ensures all layers are correctly reprojected.

This will:
- Load your DEM and OpenStreetMap as background
- Generate and normalize viewsheds
- Compute overlaps and total coverage
- Save results to `output.csv`


## 📤 Outputs

After running `main.py`, you’ll find (in the directory of your `CSV_PATH`):
As an example :

- Individual viewsheds: `data/sdis-67/output/viewsheds_geotiff/`
- Normalized viewsheds: `data/sdis-67/output/normalized/`
- Combined viewsheds: `data/sdis-67/output/fusion/`
- Coverage metrics: `data/sdis-67/output/output.csv`




## 📝 Notes

- This project uses the **QGIS Visibility Analysis** processing tool under the hood.
- Basemap is OpenStreetMap (via XYZ tiles), aligned with EPSG:2154.
- All coordinates are reprojected from `EPSG:4326` (lat/lon) to `EPSG:2154`.
- Output rasters use LZW compression for performance.




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

