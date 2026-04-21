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
├── export.py               # Export viewsheds as KMZ overlays + GeoPackage polygons
├── visualize.py            # Render the GeoPackage as an interactive HTML map
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

## 📦 Export & Visualization

Once `main.py` has produced the raw viewsheds, two helper scripts package them
for delivery and quick inspection. Both read the same `folder = "<region>"`
constant at the top of the file — change it to switch region.

### `export.py`

```bash
python export.py
```

For each `viewshed_<site>.tif` in `data/<region>/output/viewsheds_geotiff/`:

- **KMZ** — reprojects to WGS84, renders the visible pixels as a colored
  semi-transparent PNG ground overlay, and writes one `<site>.kmz` per site
  (Google Earth ready). Output: `kmz_output_<region>/`.
- **GeoPackage** — polygonizes each binary raster into a single dissolved
  `(Multi)Polygon` per site (vectorization in source CRS for accuracy, then
  reprojected to WGS84), and writes them all to a single
  `kmz_output_<region>/viewsheds_<region>.gpkg` file with one layer
  (`viewsheds`) and a `site_name` attribute.

### `visualize.py`

```bash
python visualize.py
```

Loads the GeoPackage and produces an interactive Leaflet map (via
`geopandas.explore` + folium), colored by `site_name` over a CartoDB Positron
basemap. Saves as `kmz_output_<region>/viewsheds_<region>.html` and opens it
in the default browser. Requires `folium`, `matplotlib` and `mapclassify`.

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
6. Back in a regular shell, run `python export.py` to produce KMZ + GeoPackage
   deliverables, and `python visualize.py` for an interactive HTML preview.

> ℹ️ Note: Due to QGIS limitations, the project CRS might not fully apply during script execution. Manually setting it ensures all layers are correctly reprojected.

---


## 📝 Notes

- This project uses the **QGIS Visibility Analysis** processing tool under the hood.
- Basemap is OpenStreetMap (via XYZ tiles), aligned with EPSG:2154.
- All coordinates are reprojected from `EPSG:4326` (lat/lon) to `EPSG:2154`.
- Output rasters use LZW compression for performance.

