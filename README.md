# PyroNear Visibility Analysis

Automated analysis of coverage and visibility zones using QGIS and Python.

---

## 🚀 The whole chain

Every command below runs from the repository root. `<region>` is a folder name
under `data/` — replace it everywhere, including in `config.py`. Each step
reads what the previous one wrote, so the order is not negotiable, and each
one ends with **what to check before moving on**: in this project you rarely
run the wrong command, you run the right one too early or on a stale cache.

```bash
# ── 1. Inputs ───────────────────────────────────────────────────────────────
mkdir -p data/<region>
```

Write `data/<region>/sites.csv`, semicolon-delimited. `Height` is metres
**above the ground**, never an NGF altitude:

```csv
Name;Latitude;Longitude;Owner;Height;Status
CHATEAU D EAU NORD;48.8566;2.3522;Syndicat des eaux;32;
VIGIE SUD;48.9000;2.4000;SDIS;12;EN PLACE
```

`Owner` carries the operator, which drives the access-cost colour; `Status` is
only `EN PLACE` for a camera already installed. Both columns are optional —
older files without them still work.

Starting from a list of communes or addresses instead:

```bash
uv run python resolve_points_hauts.py --region <region> \
    --xlsx data/<region>/<list>.xlsx --dept <NN>
```
> **check** — read `data/<region>/resolution.csv`, column `alertes`, before
> trusting the coordinates it produced.

Looking for new high points rather than validating given ones:

```bash
uv run python find_anfr_candidates.py --region <region> --dept <NN>
```

```bash
# ── 2. Region and detection envelope ───────────────────────────────────────
#    config.py:  REGION = "<region>"
#                VIEWSHED_RADIUS_M, TARGET_HEIGHT_M
```
> **check** — `TARGET_HEIGHT_M` is the single most decisive parameter of the
> whole chain (≈ 1.5 points of coverage per metre around 20 m). Decide it now:
> changing it later invalidates every viewshed. A variant means a new
> `data/<region>-<variant>/` folder, not an edit in place.

```bash
# ── 3. Validate the heights, before downloading anything ───────────────────
uv run python audit_sites.py --region <region>
```
> **check** — any `SUSPECT — proche de l'altitude sol` is an NGF altitude
> entered instead of a height. `HORS COUVERTURE LIDAR` means the audit could
> not conclude, not that the site is fine: cross-check against BD TOPO
> (`BDTOPO_V3:construction_ponctuelle`, `pylone`, `reservoir`) and the
> correlation MNS instead.

```bash
# ── 4. DEM ─────────────────────────────────────────────────────────────────
#    Full chain and the non-France case: see Step 1 below.
uv run python experiments/generate_dem_fr.py --region <region> --buffer-km <radius+1>
```
> **check** — the nodata percentage printed at the end. Above 0, `fill_dem_gaps.py`
> is mandatory: the plugin reads holes as hollows and every viewshed crossing
> one is wrong. And never open the `.tif` in QGIS while it is being written.

```bash
# ── 5. Remove the mast from the surface model ──────────────────────────────
uv run python experiments/flatten_mast.py --region <region> --dry-run
uv run python experiments/flatten_mast.py --region <region>
```
> **check** — a mast on a surface model blocks its own camera. `terrain.py`
> corrects the observer *height* but not the *relief*, so the spike stays in
> the way. Skip this only if the dry run reports nothing to shave.

```bash
# ── 6. Viewsheds — QGIS Python console, not a terminal ─────────────────────
#    New project, SAVED INSIDE THE REPOSITORY, CRS EPSG:2154.
#    Python console → "open script" button → main.py
```
> **check** — the `▶ REGION = <region>` line it prints first. And afterwards,
> two sites with exactly the same visible area, or a viewshed equal to a full
> disc (π × radius²), mean the DEM was read as empty.

```bash
# ── 7. Numbers, ranking, scenarios ─────────────────────────────────────────
uv run python summary.py --region <region> --zones dept --dept <NN>
uv run python prioritise_sites.py --region <region> --zones dept --dept <NN> --objectif dept --picks <n>
uv run python scenario_layers.py --region <region> --all
uv run python scenario_layers.py --region <region> --figer
uv run python make_scenarios_md.py --region <region>
```
> **check** — a `⚠️ the DEM covers only X %` warning means the zone sticks out
> of the DEM. Harmless if that part is beyond every site's radius, a bug if a
> site's disc reaches the DEM edge.

```bash
# ── 8. Deliverable ─────────────────────────────────────────────────────────
#    QGIS, new project saved inside the repository, Python console:
#    exec(open('/PATH/TO/pyro-visibility-analysis/build_qgis_project.py').read())
uv run python package_project.py <region>.qgz --light-dem 50
```

A fully worked example, with real values, is at the end of this file:
[Worked example](#-worked-example-a-single-high-point).

See the sections below for the detail of each step.

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
│   ├── example/
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

### Which script runs where

Only `main.py` and `build_qgis_project.py` run in the QGIS Python console.
Everything else runs in a terminal, because every standalone script calls
`proj_env.use_bundled_proj()` — which repairs a PROJ database that conda
breaks, and which would break QGIS, since QGIS relies on those very variables.

| script | where | role |
|---|---|---|
| `resolve_points_hauts.py` | terminal | xlsx of communes/addresses → `sites.csv` |
| `find_anfr_candidates.py` | terminal | new high points from the ANFR export, ranked by blind spot |
| `audit_sites.py` | terminal | check the heights against the Lidar HD MNT/MNS |
| `experiments/generate_dem_fr.py` | terminal | download the MNS (Lidar HD, or correlation) |
| `experiments/fill_dem_gaps.py` | terminal | refill the Lidar HD holes of a MNS |
| `experiments/flatten_mast.py` | terminal | remove the camera's own mast from the relief |
| `experiments/downsample_dem.py` | terminal | aggregate a DEM (`max` for a surface model) |
| `main.py` | **QGIS console** | compute the viewsheds |
| `summary.py` | terminal | areas, ranking, union, share per zone |
| `prioritise_sites.py` | terminal | zone crossing, marginal contribution, greedy pick |
| `scenario_layers.py` | terminal | per-scenario counting rasters |
| `make_scenarios_md.py` | terminal | `docs/scenarios-<region>.md` |
| `build_qgis_project.py` | **QGIS console** | assemble the full project |
| `package_project.py` | terminal | deliverable zip, relative paths |

---

## 📦 Installation

### System dependency: GDAL

`generate_dem.py` requires the GDAL command-line tools (`gdal_translate`,
`gdalbuildvrt`) to be available on your system PATH.

| Platform | Command |
|----------|---------|
| macOS | `brew install gdal` |
| Ubuntu / Debian | `sudo apt-get install gdal-bin` |
| Windows | Install [OSGeo4W](https://trac.osgeo.org/osgeo4w/) and add its `bin/` to PATH |
| conda (any OS) | `conda install -c conda-forge gdal` |

Verify with: `gdal_translate --version`

### Python dependencies

Managed with [uv](https://docs.astral.sh/uv/) — no manual environment setup
needed. `uv run` resolves and installs everything declared in `pyproject.toml`
into an isolated environment on first run.

---

## 🌍 Step 1: DEM Generation

Set `REGION` in `config.py` first. All commands run from the repository root,
in a terminal — not in QGIS.

### France: Lidar HD surface model (recommended)

```bash
# 1. Download the Lidar HD MNS at 5 m (IGN WMS, already in Lambert-93).
#    Buffer = detection radius + 1 km (e.g. 16 for 15 km); a larger buffer
#    lets you try a longer radius later without downloading again.
uv run python experiments/generate_dem_fr.py --buffer-km 16

# 2. Fill the Lidar HD gaps: correlation MNS first, then RGE ALTI for what
#    is left (masked sites such as CEA, last few pixels). Needed if step 1
#    reports nodata on land. Writes dem_l93_source.tif
#    (1 = lidar, 2 = correlation, 3 = RGE ALTI, 0 = still missing).
uv run python experiments/fill_dem_gaps.py
uv run python experiments/fill_dem_gaps.py --layer ELEVATION.ELEVATIONGRIDCOVERAGE

# 3. Aggregate to 10 m keeping the tops (max), then swap the files so that
#    main.py reads the 10 m DEM.
uv run python experiments/downsample_dem.py --factor 2 --method max
mv data/<region>/dem_l93.tif data/<region>/dem_l93_5m.tif
mv data/<region>/dem_l93_10m.tif data/<region>/dem_l93.tif
```

Every command accepts `--region <region>` to override `config.py`.

**Where Lidar HD does not exist at all.** The programme is progressive: whole
regions have no lidar yet. Step 1 would then
download an extent of nodata for step 2 to refill. Take the correlation MNS as
the primary source instead — it is national, carries the canopy, and matches
the lidar MNS to +0.4 m median:

```bash
uv run python experiments/generate_dem_fr.py --region <region> \
    --product MNS_CORREL --buffer-km <radius+1>
uv run python experiments/fill_dem_gaps.py --region <region> \
    --layer ELEVATION.ELEVATIONGRIDCOVERAGE
```

To tell a rollout gap from a masked military site, probe the WMS in several
directions: a masked site is a hole of a few km² surrounded by data, a rollout
gap has nothing for tens of kilometres.

**The DEM download does not resume.** `generate_dem_fr.py` opens the raster in
`"w"` and walks its chunk grid from the start; interrupting it and relaunching
restarts at chunk 1. Worse, unwritten blocks read back as **0 m**, not nodata,
so `fill_dem_gaps.py` will not see them. If you must stop, delete the partial
`dem_l93.tif` rather than keep it.

Why each step matters:
- **MNS, not SRTM**: the surface model carries the canopy, which is the main
  obstacle in flat wooded terrain; SRTM misses about half of it.
- **5 m then `max`**: asking the WMS for 10 m directly averages server-side
  and shaves about a metre off the canopy.
- **10 m** is enough to rank sites (±3 % per site against 5 m) and is about
  four times faster in QGIS.
- Nodata over the sea is expected and harmless.

⚠️ **The DEM is ready only when the `mv` commands have run.** A `dem_l93.tif`
appears as soon as step 1 starts writing it. If QGIS opens it before it is
complete, it reads it as empty and keeps that reading: every viewshed then
comes out as a full disc of the detection radius, identical from one site to
the next. If that happened, quit QGIS and delete `data/<region>/output/` and
`dem_l93.tif.aux.xml` before rerunning.

### Removing the mast from the surface model

On a surface model the structure carrying the camera is part of the relief, so
the plugin lets it block its own camera. `analysis_shape/terrain.py` corrects
the observer *height* (`OBS_HEIGHT = MNT + mast − MNS`) but not the relief, and
a photogrammetric spike in the cell next to the observer subtends a huge angle:
on one test pylon it erased **50° of horizon at every distance**, including
the first 500 m — the signature of an obstacle glued to the observer.

```bash
uv run python experiments/flatten_mast.py --region <region> --dry-run
uv run python experiments/flatten_mast.py --region <region>
```

Within `--radius` metres of each site, any cell more than `--seuil` above the
surrounding surface is brought back down to it. The observer's absolute
elevation does not move — `terrain.py` rebuilds it as `MNT + mast` — only the
blocking disappears. Keep the radius on the footprint of the structure: wider
would delete real canopy.

### Elsewhere: SRTM (legacy)

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

1. Set `REGION` in `config.py` to the region you want to analyse.
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
- Generate and normalize viewsheds, printing `[i/N] <site>` as it goes
- Compute each site's area and the union of all viewsheds
- Save results to `output.csv`

To share the project, share the QGIS project file (`.qgz`) together with all data in the directory of the CSV you provided.

---

## 📤 Outputs

After running `main.py`, you'll find (in the `output/` folder under your region, e.g. for `example`):

- Individual viewsheds: `data/example/output/viewsheds_geotiff/`
- Normalized viewsheds: `data/example/output/normalized/`
- Combined viewsheds: `data/example/output/fusion/`
- Coverage metrics: `data/example/output/output.csv`

---

## 📊 Step 3: Scoring & scenarios

Run in a terminal, once `main.py` has finished. Raw coverage in km² is not the
answer: what matters is the share of the **zone of interest** that is seen by
at least one camera (**coverage**) and by at least two (**triangulation**, the
condition to locate a fire). Always report both.

The zone is chosen with `--zones`: `dept` (the département outline, fetched and
cached; needs `--dept`), `old` (OLD brush-clearing zones) or any
`data/<region>/zones/<name>.gpkg`. Several can be combined: `--zones dept,old`.

```bash
# 1. Per-site areas and the share of each zone they see
uv run python summary.py --zones dept --dept <NN>

# 2. Marginal contribution: rank the sites, then pick them greedily — each
#    step takes the site that adds the most new zone. --picks = how many
#    steps; use the total number of sites to get the full curve and spot
#    the plateau where extra sites add almost nothing.
uv run python prioritise_sites.py --zones dept --dept <NN> --picks <n>
```

`prioritise_sites.py` treats sites with `Status` = `EN PLACE` in `sites.csv`
as the baseline, and only ranks what the others add on top.

### Scenarios

Scenarios are declared in `data/<region>/scenarios.json` (see
`data/example/scenarios.json`). Each one is
either an explicit list or a rule:

| key | meaning |
|---|---|
| `"sites": ["A", "B"]` | explicit list (name fragments); wins over any rule |
| `"tous": true` | every site |
| `"en_place": true` | the `EN PLACE` sites, as a baseline |
| `"meilleurs": 6` | the 6 best by marginal contribution |
| `"cible_pct": 90` | as many sites as needed to reach 90 % of the zone |
| `"critere": "triangulation"` | optimise triangulation instead of coverage |
| `"regions_candidats": [...]` | restrict the pool to some regions |

```bash
# See the available viewsheds and scenarios
uv run python scenario_layers.py --list

# Build one scenario, or all of them: a raster counting how many cameras see
# each cell (0 / 1 / 2 / 3+), plus bilan.csv and meta.json, in
# data/<region>/output/scenario_<name>/
uv run python scenario_layers.py --scenario 00-toutes-les-vigies
uv run python scenario_layers.py --all

# Before delivery: freeze the rules into explicit site lists, written back
# into scenarios.json, so a scenario no longer changes when the data does
uv run python scenario_layers.py --figer

# Write docs/scenarios-<region>.md, the list of sites per scenario
uv run python make_scenarios_md.py --region example
```

### Visualize the scenarios in QGIS

Once `scenario_layers.py --all` has written the `output/scenario_*` folders,
build the full project **from the QGIS Python console** (not a terminal):

1. Open a **new** QGIS project and **save it inside the repository** first.
2. In the Python console:
   ```python
   exec(open('/PATH/TO/pyro-visibility-analysis/build_qgis_project.py').read())
   ```

It builds groups for sites (coloured by access cost), scenarios (one coverage
raster each, named `<n> sites · <x> % couv · <y> % tri`, site list in the layer
metadata), the zone of interest, individual viewsheds and background. It
reads `config.REGION`; to build another region without editing `config.py`,
define `PYRO_REGION = 'example'` in the console before the `exec`. Rerun it
after any `scenario_layers.py` run — it does not pick up new scenarios on its
own.

`summary.py`, `prioritise_sites.py` and `scenario_layers.py` default to
`config.REGION`; pass `--region <region>` to override. `scenario_layers.py`
reads its zone from `scenarios.json`, so it needs no `--zones`.

---

## 💡 Tips & pitfalls

**Where each step runs.** Only `main.py` and `build_qgis_project.py` run in the
QGIS Python console; everything else runs in a terminal from the repository
root. Never paste a terminal script into QGIS: they reset PROJ/GDAL paths that
QGIS depends on.

**Order matters.** DEM (all commands finished) → `main.py` in QGIS →
`summary.py` / `prioritise_sites.py` → `scenario_layers.py --all` →
`build_qgis_project.py` in QGIS. Each step reads what the previous one wrote.

**Always pass `--zones` and `--dept` to `prioritise_sites.py`.** Its defaults
(`--zones old --dept 036`) are those of the first region it was written for: without them, another
region is scored against the wrong zone. `summary.py` takes the same options.

**Validate `scenarios.json` after editing it by hand.** A missing brace or a
trailing comma makes every script stop with `JSONDecodeError: Expecting ','
delimiter` — the error is in the file, not in the script. To find the line:

```bash
python -m json.tool data/<region>/scenarios.json > /dev/null
```

**Rerunning is safe.** Each command overwrites its own outputs
(`priorisation.csv`, `output/scenario_*`…). The exception is `main.py`: it
**skips** viewsheds that already exist. After changing the DEM, heights,
radius or target height, delete `data/<region>/output/` first — `viewshed.py`
refuses to start if `run.json` disagrees with `config.py`, but it cannot
detect a changed DEM or height.

**« the DEM covers only X % of dept »** means part of the zone lies outside
the DEM. That part counts as never covered, which is correct if it is beyond
the detection radius of every site. It is a problem only if a site's disc
reaches the DEM edge: regenerate the DEM with a larger `--buffer-km`.

**Spotting a broken run.** Two sites with exactly the same visible area, or
viewsheds equal to a full disc (π × radius², 706.9 km² at 15 km), mean the DEM
was read as empty — see the warning in [Step 1](#-step-1-dem-generation).

**Report two numbers, not one.** Coverage (≥ 1 camera) and triangulation
(≥ 2) do not grow at the same rate, and the greedy picks different sites for
each: add `"critere": "triangulation"` to a scenario to optimise the second.

More project-specific pitfalls (heights, Lidar HD gaps, NFD/NFC names…) are
in `CLAUDE.md`, section « Pièges ».

---

## 📦 Export & Visualization

Once `main.py` has produced the raw viewsheds, two helper scripts package them
for delivery and quick inspection. Both read the `REGION` set in `config.py`.

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
  - % of total coverage (share of the union)

---

## 🧭 Worked example: a single high point

A fictitious case — one candidate high point — that exercises the awkward
branches: checking the declared height, a structure visible in the surface
model, and a zone of interest. The coordinates are those of the Eiffel Tower,
used purely as an illustration; `data/example/` ships a ready-made version.

**The brief.** One high point at 48.858370;2.294481, height announced as
60 m, owner unknown. Question: what would a camera there see?

```bash
mkdir -p data/example
cat > data/example/sites.csv <<'EOF'
Name;Latitude;Longitude;Owner;Height;Status
tour-exemple;48.858370;2.294481;Gestionnaire public;60;
EOF
# config.py → REGION = "example", VIEWSHED_RADIUS_M = 20000

uv run python audit_sites.py --region example
```

Read the audit before anything else. `HORS COUVERTURE LIDAR` means the Lidar
HD MNS is missing there: probe the WMS in several directions to tell a rollout
gap (nothing for tens of kilometres) from a masked sensitive site (a hole of a
few km² surrounded by data), and switch to the correlation MNS if needed.

If the lidar or BD TOPO (`BDTOPO_V3:construction_ponctuelle`) shows a
structure whose height disagrees with the announced one, or a second structure
nearby, do not pick one: compute each hypothesis as its own row of the same
`sites.csv`, sharing one DEM.

```bash
uv run python experiments/generate_dem_fr.py --region example \
    --product MNS_CORREL --buffer-km 21
uv run python experiments/fill_dem_gaps.py --region example \
    --layer ELEVATION.ELEVATIONGRIDCOVERAGE
uv run python experiments/downsample_dem.py --region example --factor 2 --method max
mv data/example/dem_l93.tif     data/example/dem_l93_5m.tif
mv data/example/dem_l93_10m.tif data/example/dem_l93.tif

uv run python experiments/flatten_mast.py --region example
```

That last command matters more than it looks: when the structure carrying the
camera is itself in the surface model, a spike in the neighbouring DEM cell can
blank out a whole sector of horizon at every distance. The bias falls exactly
on the low-height hypotheses, i.e. on what is being compared.

QGIS → new project saved in the repository, CRS EPSG:2154, Python console →
`main.py`. Then:

```bash
uv run python summary.py --region example --zones dept --dept 75
uv run python scenario_layers.py --region example --all
uv run python scenario_layers.py --region example --figer
```

Report one row per hypothesis — observer elevation and coverage — rather than
a single number: when the hypotheses disagree by a factor of two, the answer to
give back is not "the site covers X", but "settle which structure you mean,
because it decides everything".

---

## 📝 Notes

- This project uses the **QGIS Visibility Analysis** processing tool under the hood.
- Basemaps are OpenStreetMap or Esri satellite imagery (via XYZ tiles).
- All coordinates are reprojected from `EPSG:4326` (lat/lon) to `EPSG:2154`.
- Output rasters use LZW compression for performance.
