# Pyronear Visibility Analysis

Coverage analysis for smoke-detection cameras. For each candidate high point,
GDAL computes what a camera there would see on a high-resolution elevation
model; the scripts then measure how much of the zone that matters is covered
(≥ 1 camera) and triangulated (≥ 2), rank the sites by what each one adds, and
build deployment scenarios assembled into a QGIS project.

Two places run code, and each step below says which one:

- **[Terminal]** — a shell at the repository root. Every step is a `make`
  target (`make help` lists them); each one prints the `uv run python …`
  command it runs, which you can also type directly.
- **[QGIS Python console]** — only to assemble the final project: inside QGIS,
  *Plugins → Python Console*.

Never run a terminal script inside QGIS: the terminal scripts reset PROJ/GDAL
paths that QGIS depends on.

---

## 🧰 Before you start

1. **uv** — install [uv](https://docs.astral.sh/uv/). `uv run` installs every
   Python dependency from `pyproject.toml` on first use.
2. **Docker**, running — the viewsheds use GDAL ≥ 3.13, which the chain runs
   from the official GDAL image (pulled once, ~150 MB). Check with
   `make gdal-check`. Without Docker, install GDAL natively instead: see
   [Native GDAL](docs/reference.md#native-gdal-without-docker).
3. **QGIS** — to open and assemble the final project (step 8). No plugin
   needed.
4. **Only to build or extend a site list from public data** — the ANFR
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
| one small zone (a forest…), and the question « can the existing high points see it? » | [`fetch_zone.py`](docs/reference.md#fetch_zonepy--a-zone-of-interest-from-the-ign-wfs), then [`find_anfr_candidates.py --around-zone`](docs/reference.md#around-one-zone---around-zone) | [Variant: one small zone](#-variant-one-small-zone-a-forest-a-massif) |

---

## 🚀 Quick start: produce an analysis

The common case: a region in France, a site list ready. Steps run in this
order — each one reads what the previous one wrote. `REGION=<region>` can be
left out once `config.py` names the region.

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
EARTH_CURVATURE = True       # with refraction 0.13 — leave it on
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
make audit REGION=<region>
```

Fix anything flagged before going further: `SUSPECT — close to the ground
altitude` is an NGF altitude typed instead of a height.

### 4. [Terminal] Download the elevation model

```bash
make dem REGION=<region>
```

It downloads the IGN Lidar HD surface model at 5 m around the sites, with a
margin of `VIEWSHED_RADIUS_M` + 1 km. **Wait until it has finished** before
computing viewsheds — a half-written DEM reads as empty.

- Only if it reports **nodata > 0** → fill the holes:
  [`fill_dem_gaps.py`](docs/reference.md#experimentsfill_dem_gapspy--fill-lidar-hd-holes).
- Only if the viewsheds are **too slow** at 5 m (a large pool, a long radius)
  → aggregate to 10 m:
  [`downsample_dem.py`](docs/reference.md#experimentsdownsample_dempy--aggregate-to-10-m).
- Only if a camera sits on a **pylon or mast visible in the surface model** →
  [`flatten_mast.py`](docs/reference.md#experimentsflatten_mastpy--remove-the-mast-from-the-relief).

Outside France: `uv run python generate_dem.py` instead — SRTM at about 30 m,
worldwide but blind to most of the canopy, so less precise; it needs the GDAL
command-line tools ([details](docs/reference.md#generate_dempy--srtm-outside-france-legacy)).
The rest of the chain is unchanged, except `audit_sites.py`, which relies on
the French lidar and cannot check heights there.

### 5. [Terminal] Compute the viewsheds

```bash
make viewsheds REGION=<region>
```

One `[i/N] <site>` line per site, a few sites in parallel — about a second
each at 10 m, a few at 5 m. Viewsheds already on disk are skipped, so adding
sites or restarting an interrupted run only computes what is missing. Results
land in `data/<region>/output/`.

### 6. [Terminal] Measure and rank

```bash
make summary    REGION=<region>
make prioritise REGION=<region> PICKS=<n>
```

The zone defaults to the département (`ZONES=dept`), whose code comes from
`"dept"` in `scenarios.json`. `summary` gives each site's area and the share
of the zone it sees; `prioritise` ranks the sites by what they add on top of
the cameras already installed, for all sites and for public sites only.

### 7. [Terminal] Build the scenarios

```bash
make scenarios REGION=<region>
```

One folder per scenario of `scenarios.json`, with rasters counting how many
cameras see each cell, coverage and triangulation figures. Before delivery,
freeze the rules into explicit lists with `make scenarios FREEZE=1`.

Steps 5 to 7 in one go: `make analyse REGION=<region> PICKS=<n>`.

### 8. [QGIS Python console] Assemble the QGIS project — `build_qgis_project.py`

> **Inside QGIS.** New project, saved inside the repository, then in the
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
make scenarios-md REGION=<region>    # list of sites per scenario
make package PROJECT=<project>.qgz   # LIGHT_DEM=50 by default
```

`docs/scenarios-<region>.md`, then a zip that opens anywhere: relative paths,
the DEM coarsened to 50 m for the hillshade, and the scenario notes.

---

## 🎯 Variant: one small zone (a forest, a massif)

The question is no longer « how much of the département » but « can the
existing high points see **this** zone ». The zone is the denominator, the
sites are every ANFR support in range, whatever their département. Same chain
as the Quick start, with three differences: the zone comes first, the sites
come from the ANFR register, and every percentage is a share of the zone.

```bash
mkdir -p data/<region>                       # no sites.csv to write by hand

# 1. The zone — a point inside it, read on any map
make zone REGION=<region> NAME=<zone> POINT=<lat>,<lon>
#    check the printed name and area, then note the « --onf F… » it prints:
#    make zone REGION=<region> NAME=<zone> ONF=<id> fetches the same polygon

# 2. Every ANFR support within VIEWSHED_RADIUS_M of the zone outline
uv run python find_anfr_candidates.py --region <region> --around-zone <zone> \
    --hauteur-min 10
cp data/<region>/candidats_anfr.csv data/<region>/sites.csv

# 3. Then the usual chain, with the zone as ZONES
make audit      REGION=<region>
make dem        REGION=<region>
make viewsheds  REGION=<region>
make summary    REGION=<region> ZONES=<zone>
make prioritise REGION=<region> ZONES=<zone> PICKS=20
make scenarios  REGION=<region>
```

`data/<region>/scenarios.json` names the zone and sorts the ANFR owners, which
`find_anfr_candidates.py` writes as `PUBLIC …` or `OPERATEUR …`. No `"dept"`:

```json
{
  "regions": ["<region>"],
  "zone": "<zone>",
  "zone_libelle": "<label shown in QGIS>",
  "critere": "couverture",
  "gestionnaires": {"defaut": "operateur", "public": ["PUBLIC"], "operateur": ["OPERATEUR"]},
  "scenarios": {
    "00-tous":            {"tous": true},
    "01-publics":         {"cible_pct": 100, "max_operateurs": 0},
    "02-meilleurs-5":     {"meilleurs": 5},
    "03-meilleurs-5-tri": {"meilleurs": 5, "critere": "triangulation"}
  }
}
```

`00-tous` is the upper bound: what stays red there, no existing support sees.

**Options worth knowing**

| option | default | why change it |
|---|---|---|
| `--hauteur-min` | 30 m | 10 m keeps short masts on a ridge, often better placed than a tall pylon in the plain |
| `--radius` | `VIEWSHED_RADIUS_M` | to search wider or narrower than the detection radius |
| `--publics-seulement`, `--max-operateurs N` | off | to leave paid operator sites out of the list itself, rather than in a scenario |
| `--top N`, `--ecart M` | all, none | only if the list gets too long to compute |
| `--onf` / `--layer` (`fetch_zone.py`) | — | reproducible zone; a polygon layer other than public forests |

Two things to keep in mind:
- ANFR heights include the antenna mast: a camera would sit lower, so
  coverage comes out optimistic.
- The register only lists supports carrying radio equipment. A structure
  without one (a water tower, a lookout) is only in BD TOPO
  (`BDTOPO_V3:construction_ponctuelle`, `pylone`, `reservoir`): add it to
  `sites.csv` by hand, then `make viewsheds` computes only the new sites.

Details of each script:
[`fetch_zone.py`](docs/reference.md#fetch_zonepy--a-zone-of-interest-from-the-ign-wfs),
[`--around-zone`](docs/reference.md#around-one-zone---around-zone).

---

## 📚 Reference

Every script's options, every output file, and the pitfalls worth knowing:
see [docs/reference.md](docs/reference.md).

---

## 📁 Project structure

```
.
├── config.py              # REGION, VIEWSHED_RADIUS_M, TARGET_HEIGHT_M, EARTH_CURVATURE
├── Makefile               # one target per terminal step (make help)
├── data/                  # ignored by git, except data/example/ (fictitious template)
├── compute_viewsheds.py   # [Terminal] viewsheds, output.csv, union
├── build_qgis_project.py  # [QGIS] project assembly
├── *.py                   # [Terminal] the other scripts, see Reference
├── experiments/           # [Terminal] DEM download, gap filling, downsampling, mast flattening
├── analysis_shape/        # modules imported by the scripts
│   ├── gdal_viewshed.py   #   gdal_viewshed in Docker or native, run.json guard
│   ├── terrain.py         #   observer height on a surface model
│   ├── area_analysis.py   #   union, per-site areas
│   ├── zones.py           #   zones of interest as masks
│   ├── selection.py       #   the shared greedy selection
│   ├── gestionnaires.py   #   owner → access-cost category
│   └── config_loader.py   #   fresh config.py in the QGIS console
├── viewshed_style.qml     # QGIS style for viewsheds
└── CLAUDE.md              # pitfalls and method decisions, for contributors
```

All coordinates are reprojected from `EPSG:4326` to `EPSG:2154`
(Lambert-93). Basemaps are OpenStreetMap or Esri imagery.
