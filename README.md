# PyroNear Visibility Analysis

Automated analysis of coverage and visibility zones using QGIS and Python.

---

## 🚀 How to analyze sites

1. Create a folder `data/sdis-xx/`
2. Add the site info in `data/sdis-xx/sites.csv` (semicolon-delimited):

   ```csv
   Name;Latitude;Longitude;Height
   Site A;48.8566;2.3522;30
   Site B;48.9000;2.4000;30
   ```

3. Generate the DEM: `uv run python generate_dem.py`
4. Open QGIS, then in the Python Console run `main.py`
5. Export the results: `uv run python export.py`
6. Visualize: `uv run streamlit run visualize.py`

> Set the region by editing the `CSV_PATH` / `folder` constant at the top of
> `generate_dem.py`, `main.py`, `export.py` and `visualize.py`.

See the sections below for details.

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
│   ├── sdis-77/
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
├── visualize.py            # Streamlit app to explore viewsheds + per-site/total area stats
├── viewshed_style.qml      # QGIS raster style applied to viewsheds
└── README.md
```

## 📦 Installation

Dependencies are managed with [uv](https://docs.astral.sh/uv/) — no manual
environment setup needed. `uv run` resolves and installs everything declared
in `pyproject.toml` into an isolated environment on first run.

---

## 🌍 Step 1: Automatic DEM Generation

You can automatically download and project a DEM (Digital Elevation Model):

- In `generate_dem.py`, update `CSV_PATH` to the CSV containing the stations you want to analyse.
- Then run:

```bash
uv run python generate_dem.py
```

This script:
- Parses station coordinates from `sites.csv`
- Computes a bounding box with buffer
- Downloads SRTM tiles using the `eio` CLI
- Reprojects to `EPSG:2154`
- Saves `dem_l93.tif` in the folder where the provided CSV is stored

---

## 🛰️ Step 2: Running the Analysis in QGIS

1. In `main.py`, update `CSV_PATH` to the CSV containing the stations you want to analyse.
2. Open **QGIS**.
3. Install the QGIS plugin **"Visibility Analysis"** (by Zoran Čučković) if you don't have it.
4. Create a **new project** and save it in the `pyro-visibility-analysis` working directory (this avoids path issues later).
5. Open the **Python Console** → *Show Editor*.
6. If `analysis_shape` can't be imported, register the repo path first:
   ```python
   import sys
   sys.path.append("/PATH_TO_THE_REPOSITORY/pyro-visibility-analysis")
   ```
7. Load and run `main.py`.
8. Go to **Project → Properties → CRS** and set it to `EPSG:2154` (Lambert-93).

> ℹ️ Note: Due to QGIS limitations, the project CRS might not fully apply during script execution. Manually setting it ensures all layers are correctly reprojected.

This will:
- Load your DEM and OpenStreetMap as background
- Generate and normalize viewsheds
- Compute overlaps and total coverage
- Save results to `output.csv`

To share the project, share the QGIS project file (`.qgz`) together with all data in the directory of the CSV you provided.

---

## 📤 Outputs

After running `main.py`, you'll find (in the `output/` folder next to your `CSV_PATH`, e.g. for `sdis-77`):

- Individual viewsheds: `data/sdis-77/output/viewsheds_geotiff/`
- Normalized viewsheds: `data/sdis-77/output/normalized/`
- Combined viewsheds: `data/sdis-77/output/fusion/`
- Coverage metrics: `data/sdis-77/output/output.csv`

---

## 📦 Export & Visualization

Once `main.py` has produced the raw viewsheds, two helper scripts package them
for delivery and quick inspection. Both read the same `folder = "<region>"`
constant at the top of the file — change it to switch region.

### `export.py`

```bash
uv run python export.py
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

### `visualize.py` (Streamlit app)

```bash
uv run streamlit run visualize.py
```

Interactive web app to inspect the GeoPackage produced by `export.py`.

**Sidebar**

- *Sites* — All / None bulk toggles, then a checkbox per site.
- *Basemap* — switch between OpenStreetMap and Satellite (Esri imagery).

**Main panel**

- Top-of-page metrics: number of sites selected, **total covered area
  (geometric union — overlap deduplicated)**, and the overlap surface
  (sum of per-site areas minus the union).
- A folium map of the selected viewsheds (colored by site, hover tooltip
  with site name + area) next to a sortable per-site area table (km²).

Areas are computed by reprojecting to a local UTM zone via
`gdf.estimate_utm_crs()` so they are accurate regardless of region.

Requires `streamlit`, `streamlit-folium`, `folium`, `matplotlib`,
`mapclassify` (all declared in `pyproject.toml`).

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

## 📝 Notes

- This project uses the **QGIS Visibility Analysis** processing tool under the hood.
- Basemaps are OpenStreetMap or Esri satellite imagery (via XYZ tiles).
- All coordinates are reprojected from `EPSG:4326` (lat/lon) to `EPSG:2154`.
- Output rasters use LZW compression for performance.
