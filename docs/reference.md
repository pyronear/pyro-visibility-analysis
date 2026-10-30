# Reference

Every script of the chain, what it is for, when to use it, its useful options
and what it produces — then every output file, and the pitfalls worth knowing.
The step-by-step path is the [Quick start](../README.md#-quick-start-produce-an-analysis)
in the README.

Every terminal script accepts `--region <region>` to override `config.py`, and
`--help` for the full list of options. The main steps also have a `make`
target (`make help`), which prints the command it runs.

## Scripts

### `resolve_points_hauts.py` — clean a partner's list

**When:** a fire service, a water syndicate or a département shares a list of
high points that needs cleaning before it can be used — communes or addresses,
no coordinates, no reliable heights. The script rebuilds both by
cross-checking BAN geocoding, BD TOPO structures, the ANFR register and the
Lidar HD height model.

**Input:** the first sheet of an `.xlsx`. The header row is found by its
labels (within the first 30 rows), so title rows above it do not matter.

| column label | meaning | |
|---|---|---|
| `où` | commune | required |
| `quoi` | kind of structure (château d'eau, pylône, mât…) | recommended |
| `adresse` | street address | improves matching |
| `gestionnaire` | who manages it → `Owner` | optional |
| `n°` | site number, prefixed to the name | optional |
| `zones géographiques`, `avancement`, `coût` | carried into `resolution.csv` | optional |

Rows can be colour-coded with a highlight: green = in service, orange =
temporary, yellow = agreement to sign. Only those go into `sites.csv` by
default (`--etapes`); uncoloured rows are resolved but left out.

```bash
uv run python resolve_points_hauts.py --region <region> \
    --xlsx data/<region>/<list>.xlsx
```

**Produces:** `data/<region>/sites.csv`, and `data/<region>/resolution.csv`
with every decision (matched structure, distance to the geocoded point, the
three candidate heights and the one kept). **Read it before going on:**

- column `statut` — anything other than `ok…` was not resolved;
- column `alertes` — structure far from the geocoded point, a second candidate
  just as close, no address, a ground-level reservoir instead of a tower,
  heights that disagree, height not confirmed by the lidar.

The height kept is the **structure's**; lower it in `sites.csv` if the camera
sits below the top.

**Useful options and files:**

- `data/<region>/commune_alias.json` — `{"OLD NAME": "MERGED NAME"}` for
  communes the geo API does not recognise (merged communes, short forms): add
  one per « commune not found » and rerun.
- `data/<region>/sites_installes.json` — cameras already installed, a list of
  `{"name", "lat", "lon"}` (optionally `"hauteur_sol_m"`). Their position
  wins and they are marked `EN PLACE`.
- `--hauteur ouvrage|anfr|lidar` — preferred height source. The default,
  `ouvrage`, takes BD TOPO, then lidar, then ANFR — ANFR heights include
  antenna masts and overstate water towers.
- `--anfr` — path to `SUP_SUPPORT.geojson` (optional, used to cross-check).

### `find_anfr_candidates.py` — find new high points

**When:** a first analysis exists and you want structures that could cover
what is still blind. Needs existing viewsheds for the region.

It keeps ANFR supports of a usable kind (water towers, pylons, masts…) at
least `--hauteur-min` m tall (default 30), drops those near a site already in
`sites.csv`, and ranks the rest by the uncovered zone area within detection
range. The score ignores terrain: it sorts, real viewsheds decide.

```bash
uv run python find_anfr_candidates.py --region <region> --top 25 --max-operateurs 10
```

**Produces:** `data/<region>/candidats_anfr.csv`, in the `sites.csv` format.
Append its rows to `sites.csv` — or, to compare « the partner's list » with
« the list plus ANFR », put them in their own region folder and name it in a
scenario's `regions_candidats`. Then audit them and rerun
`compute_viewsheds.py`: only the new viewsheds are computed — unless a new
site's detection disc leaves the DEM, which was framed on the sites known when
it was downloaded. `compute_viewsheds.py` then warns and computes it clipped;
for a full disc, regenerate the DEM (`generate_dem_fr.py`) and delete
`output/`, since every viewshed must share the new grid.

**Useful options:** `--anfr`, `--refs` (ANFR files), `--top`, `--ecart`
(minimum spacing between candidates, m), `--max-operateurs` (cap on paid
operator supports), `--publics-seulement`.

### `audit_sites.py` — check the heights

Compares each declared height with the Lidar HD MNT and MNS around the point.

- `SUSPECT — close to the ground altitude` — an NGF altitude typed as a height.
- `IMPLAUSIBLE` / `MISSING HEIGHT` — fix the row.
- `ok — structure not captured by the lidar` — expected for lattice pylons.
- `OUTSIDE LIDAR COVERAGE` — the audit could not conclude. Cross-check with
  BD TOPO (`BDTOPO_V3:construction_ponctuelle`, `pylone`, `reservoir`) and the
  correlation MNS.

### `experiments/generate_dem_fr.py` — elevation model

Downloads the IGN surface model (MNS) over WMS at 5 m, already in Lambert-93,
around the sites. Writes `data/<region>/dem_l93.tif`.

- `--buffer-km` — margin around the sites; defaults to `VIEWSHED_RADIUS_M` +
  1 km. Wider lets you try a longer radius later without downloading again.
- `--product MNS_CORREL` — where Lidar HD does not exist yet (whole regions):
  the national photogrammetric surface model, which carries the canopy and
  matches the lidar to +0.4 m median.
- The download **does not resume**: unwritten blocks read back as 0 m, not
  nodata. If you stop it, delete the partial file.

Why a surface model: it carries the canopy, the main obstacle in flat wooded
terrain, which SRTM largely misses.

### `experiments/fill_dem_gaps.py` — fill Lidar HD holes

**Only if** `generate_dem_fr.py` reports nodata on land. A hole reads as a
pit, so every viewshed crossing one is wrong.

```bash
uv run python experiments/fill_dem_gaps.py --region <region>
uv run python experiments/fill_dem_gaps.py --region <region> --layer ELEVATION.ELEVATIONGRIDCOVERAGE
```

The first pass fills from the correlation MNS, the second from RGE ALTI
(masked sensitive sites, last pixels). Edits the DEM in place and writes
`dem_l93_source.tif` (1 = lidar, 2 = correlation, 3 = RGE ALTI, 0 = missing).
Nodata over the sea is expected and harmless.

### `experiments/downsample_dem.py` — aggregate to 10 m

**Only if** the viewsheds are too slow at 5 m (a large pool, a long radius).
10 m is enough to rank sites (±3 % per site against 5 m) and about four times
faster. Use `max`, never ask the WMS
for 10 m directly: it averages server-side and shaves the canopy.

```bash
uv run python experiments/downsample_dem.py --region <region> --factor 2 --method max
mv data/<region>/dem_l93.tif     data/<region>/dem_l93_5m.tif
mv data/<region>/dem_l93_10m.tif data/<region>/dem_l93.tif
```

`compute_viewsheds.py` reads `dem_l93.tif`; run it only once the `mv` commands
have run.

### `experiments/flatten_mast.py` — remove the mast from the relief

**Only if** a camera sits on a structure the surface model captures (a pylon
or mast next to the observer). That structure is part of the relief, so it can
blank out a whole sector of the camera's own horizon. `terrain.py` already
corrects the observer *height*; this removes the spike from the *relief*.

```bash
uv run python experiments/flatten_mast.py --region <region> --dry-run
uv run python experiments/flatten_mast.py --region <region>
```

Within `--radius` m of each site (default 20), cells more than `--seuil` m
(default 5) above the surrounding surface are brought down to it. Edits the
DEM in place: delete existing viewsheds afterwards.

### `generate_dem.py` — SRTM, outside France (legacy)

**When:** the region has no IGN coverage. It takes no option: it reads
`config.REGION` and `data/<region>/sites.csv`.

```bash
uv run python generate_dem.py
```

Downloads SRTM tiles (about 30 m) with a fixed 30 km margin around the sites,
using `eio` and the GDAL command-line tools (`brew install gdal`,
`apt-get install gdal-bin`, or OSGeo4W on Windows), then reprojects them to
EPSG:2154 as `data/<region>/dem_l93.tif`. SRTM is a 2000-era radar model: it
misses most of the canopy, so coverage comes out higher than reality. The
whole chain works in Lambert-93 (EPSG:2154), which suits France and the areas
just across its borders.

### `compute_viewsheds.py` — viewsheds

```bash
make viewsheds REGION=<region>
uv run python compute_viewsheds.py --region <region> [--workers N]
```

For each site of `sites.csv`, not yet on disk:

1. the observer height, corrected for the surface model
   (`OBS_HEIGHT = (ground + mast) − surface`, ground from the Lidar HD MNT,
   cached per site in `ground_elevation.json`);
2. `gdal_viewshed` within `VIEWSHED_RADIUS_M`, target `TARGET_HEIGHT_M`
   above the surface, Earth curvature with refraction 0.13 unless
   `EARTH_CURVATURE = False` — several sites in parallel (`--workers`,
   default all cores);
3. a 0/1 mask on the full DEM grid, uint8 DEFLATE, in
   `output/viewsheds_geotiff/`.

Then `output/output.csv` (area per site, share of the union) and the union,
`output/fusion/fusion_or_all_sites.tif`.

Before anything runs it names the sites whose detection disc leaves the DEM
(computed anyway, clipped), and refuses a site standing on a nodata cell and
two rows with the same name.

It records radius, target height, curvature and engine in `output/run.json`
and **refuses to start** if they differ from `config.py` while viewsheds are on
disk — including folders computed with the former QGIS plugin, which records
no engine: delete their `output/` and recompute. To compare settings, use one
folder per variant: `data/<region>-<variant>/`, same `sites.csv`, a link to
the DEM.

**GDAL ≥ 3.13 is required.** By default it runs from the official image
`ghcr.io/osgeo/gdal:ubuntu-small-3.13.3`, in one container kept for the whole
batch; the repository is mounted at the same path inside it, so the DEM and
`data/` must sit inside the repository (a symlink from one region folder to
another is fine). Docker on macOS costs about 20 % against a native binary.

#### Native GDAL, without Docker

Point `GDAL_VIEWSHED` at a native `gdal_viewshed` ≥ 3.13; `make gdal-check`
confirms which one runs and refuses an older version (before 3.13, the
observer's own cell could block the view — 50 to 80 % lost on sites whose
camera sits just below the top of its structure in the surface model).

| system | install | then |
|---|---|---|
| macOS | `brew install gdal` | `export GDAL_VIEWSHED=$(brew --prefix)/bin/gdal_viewshed` |
| any, with conda | `conda create -n gdal -c conda-forge "gdal>=3.13"` | `export GDAL_VIEWSHED=<env>/bin/gdal_viewshed` |
| Ubuntu | `apt` ships an older GDAL (3.8 on 24.04): use conda, or Docker | |
| Windows | OSGeo4W or conda | `set GDAL_VIEWSHED=…\gdal_viewshed.exe` |

Keep a conda GDAL out of the `uv` environment: conda exports `PROJ_DATA`,
which the standalone scripts deliberately drop (see `proj_env.py`); only the
`gdal_viewshed` binary is used.

### `summary.py` — areas and share per zone

```bash
uv run python summary.py --region <region> --zones dept
```

`--zones`: `dept` (département outline; the code is read from `"dept"` in
`scenarios.json`, or `--dept`), `old` (brush-clearing
obligation zones), or any `data/<region>/zones/<name>.gpkg`; several with
commas. Writes `summary.csv` and `sites_with_coverage.gpkg` (sites as points,
to label with `area_km2` in QGIS).

### `prioritise_sites.py` — marginal contribution

```bash
uv run python prioritise_sites.py --region <region> --zones dept --picks <n>
```

Sites with `Status = EN PLACE` are the baseline. At each step the greedy
selection takes the site adding the most new zone; it runs for all sites and
for public sites only, to show what operator sites buy. Use `--picks` = number
of sites to see the whole curve and its plateau. `--zones` defaults to `old`;
pass `--zones dept` where there is no OLD layer. Writes
`output/priorisation.csv`.

**The département, in every script**, comes from `"dept"` in
`data/<region>/scenarios.json`; `--dept` overrides it. It is only needed for
the `dept` zone and the ANFR scripts — outside France, or with a zone of your
own (`data/<region>/zones/<name>.gpkg`), leave it out.

### `scenario_layers.py` and `scenarios.json` — scenarios

`data/<region>/scenarios.json` names the regions whose viewsheds are read
(`regions`), the zone of interest (`zone`, `dept`), the owner categories
(`gestionnaires`) and the scenarios. Each scenario is a list or a rule:

| key | meaning |
|---|---|
| `"sites": ["A", "B"]` | explicit list (name fragments); wins over any rule |
| `"tous": true` | every site |
| `"en_place": true` | the `EN PLACE` sites, as a baseline |
| `"meilleurs": 6` | the 6 best by marginal contribution |
| `"cible_pct": 90` | as many sites as needed to reach 90 % of the zone |
| `"critere": "triangulation"` | optimise triangulation instead of coverage |
| `"max_operateurs": 2` | at most 2 paid operator sites, the rest public |
| `"regions_candidats": [...]` | restrict the pool to some regions |

```bash
uv run python scenario_layers.py --region <region> --list         # what is available
uv run python scenario_layers.py --region <region> --scenario 00-tous
uv run python scenario_layers.py --region <region> --all
uv run python scenario_layers.py --region <region> --figer        # freeze rules into lists
```

Writes `output/scenario_<name>/`: camera-count rasters (0 / 1 / 2 / 3+) on the
zone and overall, `bilan.csv`, `meta.json`. `--figer` writes each resolved list
next to its rule, so a delivered scenario stops changing when the data does.
After editing `scenarios.json` by hand, check it with
`python -m json.tool data/<region>/scenarios.json > /dev/null`.

### `make_scenarios_md.py` — scenario notes

```bash
uv run python make_scenarios_md.py --region <region>
```

Writes `docs/scenarios-<region>.md`: the sites of each scenario, with their
status, height and owner.

### `build_qgis_project.py` — QGIS project (QGIS Python console)

Assembles the project from `scenarios.json` and the `output/scenario_*`
folders. Rerun it after any `scenario_layers.py` run. To build another region
without editing `config.py`, define `PYRO_REGION = '<region>'` in the console
before the `exec`; `PYRO_SCENARIOS = ['00', '01']` keeps only the scenarios
whose name starts with those prefixes.

### `package_project.py` — deliverable zip

```bash
uv run python package_project.py <project>.qgz --light-dem 50
```

Copies exactly the files the project references, with relative paths.
`--light-dem M` ships the DEM coarsened to M metres (it only serves as a
hillshade); `--skip-viewsheds` leaves the individual viewsheds out.

### `export.py` and `visualize.py` — quick look outside QGIS

```bash
uv run python export.py           # GeoPackage of the viewsheds (--kmz: also Google Earth)
uv run streamlit run visualize.py # web app to browse it
```

`export.py` writes `kmz_output_<region>/viewsheds_<region>.gpkg`, one polygon
per site with `area_km2` counted on the raster (`--min-polygon-area`,
`--simplify` only clean the outlines). `visualize.py` maps the selected sites,
lists their areas and computes the union on demand.

---

## 📤 Outputs

Under `data/<region>/`:

| file | written by | content |
|---|---|---|
| `resolution.csv` | `resolve_points_hauts.py` | every resolution decision, to review |
| `candidats_anfr.csv` | `find_anfr_candidates.py` | ANFR shortlist, `sites.csv` format |
| `dem_l93.tif` | `generate_dem_fr.py` | the DEM `compute_viewsheds.py` reads |
| `dem_l93_source.tif` | `fill_dem_gaps.py` | origin of each pixel |
| `ground_elevation.json` | `compute_viewsheds.py` | ground elevation cache per site (`{ground, x, y}`) |
| `output/run.json` | `compute_viewsheds.py` | radius, target height, curvature, engine and GDAL version used |
| `output/viewsheds_geotiff/` | `compute_viewsheds.py` | one 0/1 mask per site on the DEM grid (uint8, DEFLATE) |
| `output/fusion/` | `compute_viewsheds.py` | the union of the viewsheds |
| `output/output.csv` | `compute_viewsheds.py` | `Site`, `Surface` (m²), `% du total` (share of the union) |
| `output/summary.csv`, `output/sites_with_coverage.gpkg` | `summary.py` | km² per site and per zone |
| `output/priorisation.csv` | `prioritise_sites.py` | total and marginal area per site and zone |
| `output/scenario_<name>/` | `scenario_layers.py` | count rasters, `bilan.csv`, `meta.json` |

---

## 💡 Tips & pitfalls

**Spotting a broken run.** Two sites with exactly the same visible area, or a
viewshed equal to a full disc (π × radius²), mean the DEM was read as empty —
usually because the viewsheds were computed while it was still downloading.
Delete `data/<region>/output/` and rerun once the download is over.

**Changed the DEM or a height?** `compute_viewsheds.py` skips viewsheds
already on disk and cannot see such a change: delete the affected viewsheds
(or `output/`) first.
A site moved by more than 5 m has its ground elevation measured again.

**« the DEM covers only X % of dept »** — part of the zone lies outside the
DEM. Fine if it is beyond every site's radius; otherwise regenerate the DEM
with a larger `--buffer-km`.

**Report two numbers, not one.** Coverage (≥ 1 camera) and triangulation
(≥ 2, needed to locate a fire) do not grow at the same rate, and the greedy
picks different sites for each.

**One site, several hypotheses.** When the lidar or BD TOPO disagree with the
announced height, or show a second structure nearby, put each hypothesis on
its own row of `sites.csv` and compare: when they differ by a factor of two,
the useful answer is « settle which structure you mean ».

More pitfalls and the reasoning behind the method: [`CLAUDE.md`](../CLAUDE.md), sections
« Pitfalls » and « Method decisions ».
