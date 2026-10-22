# PyroNear Visibility Analysis

Coverage analysis for smoke-detection cameras. For each candidate high point,
QGIS computes what a camera there would see on a high-resolution elevation
model; the scripts then measure how much of the zone that matters is covered
(≥ 1 camera) and triangulated (≥ 2), rank the sites by what each one adds, and
build deployment scenarios ready to open in QGIS.

Two places run code, and each step below says which one:

- **[Terminal]** — a shell at the repository root, commands start with `uv run`.
- **[QGIS Python console]** — inside QGIS: *Plugins → Python Console*, then
  *Show Editor* → *Open Script…* → pick the file → *Run Script*.

Never run a terminal script inside QGIS, or the other way round: the terminal
scripts reset PROJ/GDAL paths that QGIS depends on.

---

## 🧰 Before you start

1. **uv** — install [uv](https://docs.astral.sh/uv/). `uv run` installs every
   Python dependency from `pyproject.toml` on first use; nothing else to set up.
2. **QGIS + the Visibility Analysis plugin** — install QGIS, then *Plugins →
   Manage and Install Plugins…* → **Visibility Analysis** (by Zoran Čučković).
   The viewsheds are computed by this plugin.
3. **Only to build or extend a site list from public data** — the ANFR
   register, from data.gouv.fr, dataset « Données sur les installations
   radioélectriques de plus de 5 watts »: `SUP_SUPPORT.geojson` and the
   reference tables (`SUP_NATURE.txt`, `SUP_PROPRIETAIRE.txt`). The scripts
   look for them in `~/Downloads/` by default.

---

## 🧭 Where do my sites come from?

| I have… | I use… | then |
|---|---|---|
| sites with coordinates and heights | nothing — write `sites.csv` by hand (step 2 below) | Quick start, step 3 |
| a partner's list of high points: communes or addresses, no coordinates, unreliable heights | [`resolve_points_hauts.py`](docs/reference.md#resolve_points_hautspy--clean-a-partners-list) | Quick start, step 3 |
| a first analysis done, and I want new high points to fill its gaps | [`find_anfr_candidates.py`](docs/reference.md#find_anfr_candidatespy--find-new-high-points) | append them, back to step 3 |

---

## 🚀 Quick start: produce an analysis

The common case: a region in France, a site list ready. Steps run in this
order — each one reads what the previous one wrote.

### 1. [Terminal] Create the region

```bash
cp -R data/example data/<region>
```

`data/example/` is a fictitious template: `sites.csv`, `scenarios.json` (zone
of interest, owner categories, scenarios) and a short README. Then, in
`config.py`:

```python
REGION = "<region>"          # the folder name under data/
VIEWSHED_RADIUS_M = 20000    # detection radius
TARGET_HEIGHT_M = 25         # smoke plume height considered detectable
```

`TARGET_HEIGHT_M` is the most decisive parameter of the whole chain: decide it
now, changing it later invalidates every viewshed.

### 2. [Terminal] Fill in `sites.csv` and `scenarios.json`

`data/<region>/sites.csv`, semicolon-delimited:

```csv
Name;Latitude;Longitude;Owner;Height;Status
CHATEAU D EAU NORD;48.6200;2.7500;Syndicat des eaux;32;
VIGIE SUD;48.5400;3.0500;SDIS;12;EN PLACE
```

- `Height` — camera height in metres **above the ground**, never an NGF altitude.
- `Owner` — who manages the structure; it sets the access-cost category
  through the `gestionnaires` table of `scenarios.json`.
- `Status` — `EN PLACE` for a camera already installed, empty otherwise.

In `data/<region>/scenarios.json`, set `"regions": ["<region>"]` and the zone
of interest — usually `"zone": "dept", "dept": "<NN>"`.

### 3. [Terminal] Check the heights

```bash
uv run python audit_sites.py --region <region>
```

Fix anything flagged before going further: `SUSPECT — close to the ground
altitude` is an NGF altitude typed instead of a height.

### 4. [Terminal] Download the elevation model

```bash
uv run python experiments/generate_dem_fr.py --region <region>
```

It downloads the IGN Lidar HD surface model at 5 m around the sites, with a
margin of `VIEWSHED_RADIUS_M` + 1 km. **Wait until it has finished** before
opening QGIS — a half-written DEM is read as empty.

- Only if it reports **nodata > 0** → fill the holes:
  [`fill_dem_gaps.py`](docs/reference.md#experimentsfill_dem_gapspy--fill-lidar-hd-holes).
- Only if QGIS is **too slow** at 5 m → aggregate to 10 m:
  [`downsample_dem.py`](docs/reference.md#experimentsdownsample_dempy--aggregate-to-10-m).
- Only if a camera sits on a **pylon or mast visible in the surface model** →
  [`flatten_mast.py`](docs/reference.md#experimentsflatten_mastpy--remove-the-mast-from-the-relief).

Outside France: `uv run python generate_dem.py` instead — SRTM at about 30 m,
worldwide but blind to most of the canopy, so less precise; it needs the GDAL
command-line tools ([details](docs/reference.md#generate_dempy--srtm-outside-france-legacy)).
The rest of the chain is unchanged, except `audit_sites.py`, which relies on
the French lidar and cannot check heights there.

### 5. [QGIS Python console] Compute the viewsheds — `main.py`

> **This step runs inside QGIS, not in a terminal.**
>
> 1. Open QGIS, create a **new project** and **save it inside the
>    `pyro-visibility-analysis` folder** — outputs are located from there.
> 2. *Plugins → Python Console* → *Show Editor* → *Open Script…* →
>    `main.py` → *Run Script*.
> 3. Check the first line it prints: `▶ REGION = <region>`.

It prints `[i/N] <site>` for each site — count a minute or more per site.
Viewsheds already on disk are skipped, so an interrupted run can simply be
restarted. Results land in `data/<region>/output/`.

### 6. [Terminal] Measure and rank

```bash
uv run python summary.py --region <region> --zones dept
uv run python prioritise_sites.py --region <region> --zones dept --picks <n>
```

The département comes from `"dept"` in `scenarios.json` (`--dept` overrides
it). `summary.py` gives each site's area and the share of the zone it sees.
`prioritise_sites.py` ranks the sites by what they add on top of the cameras
already installed, for all sites and for public sites only.

### 7. [Terminal] Build the scenarios

```bash
uv run python scenario_layers.py --region <region> --all
```

One folder per scenario of `scenarios.json`, with rasters counting how many
cameras see each cell, coverage and triangulation figures. Before delivery,
freeze the rules into explicit lists with `--figer`.

### 8. [QGIS Python console] Assemble the QGIS project — `build_qgis_project.py`

> **Inside QGIS again.** New project, saved inside the repository, then in the
> Python console:
>
> ```python
> exec(open('/PATH/TO/pyro-visibility-analysis/build_qgis_project.py').read())
> ```
>
> Save the project when it is done.

Sites coloured by access cost, one layer per scenario (named
`<n> sites · <x> % couv · <y> % tri`), the zone of interest, the individual
viewsheds and a background map.

### 9. [Terminal] Package the deliverable

```bash
uv run python make_scenarios_md.py --region <region>    # list of sites per scenario
uv run python package_project.py <project>.qgz --light-dem 50
```

`docs/scenarios-<region>.md`, then a zip that opens anywhere: relative paths,
the DEM coarsened to 50 m for the hillshade, and the scenario notes.

---

## 📚 Reference

Every script's options, every output file, and the pitfalls worth knowing:
see [docs/reference.md](docs/reference.md).

---

## 📁 Project structure

```
.
├── config.py              # REGION, VIEWSHED_RADIUS_M, TARGET_HEIGHT_M
├── data/                  # ignored by git, except data/example/ (fictitious template)
├── main.py                # [QGIS] viewsheds
├── build_qgis_project.py  # [QGIS] project assembly
├── *.py                   # [Terminal] the other scripts, see Reference
├── experiments/           # [Terminal] DEM download, gap filling, downsampling, mast flattening
├── analysis_shape/        # modules imported by the scripts
│   ├── viewshed.py        #   viewsheds, run.json guard
│   ├── terrain.py         #   observer height on a surface model
│   ├── area_analysis.py   #   union, per-site areas, compact rasters
│   ├── zones.py           #   zones of interest as masks
│   ├── selection.py       #   the shared greedy selection
│   ├── gestionnaires.py   #   owner → access-cost category
│   ├── config_loader.py   #   fresh config.py in the QGIS console
│   └── utils.py
├── viewshed_style.qml     # QGIS style for viewsheds
└── CLAUDE.md              # pitfalls and method decisions, for contributors
```

All coordinates are reprojected from `EPSG:4326` to `EPSG:2154`
(Lambert-93). Basemaps are OpenStreetMap or Esri imagery.
