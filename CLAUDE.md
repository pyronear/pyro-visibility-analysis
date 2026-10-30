# CLAUDE.md — PyroNear visibility analysis

Coverage analysis for smoke-detection cameras: viewsheds are computed in QGIS
on an elevation model, then crossed with zones of interest to rank candidate
sites.

Several traps in this project cost one to several hours when discovered the
hard way. **Read « Pitfalls » before running anything.** The step-by-step
reference, with a check after each step and a worked example, is
**README.md § « Quick start »**; every script's options, the output files and
the user-facing pitfalls are in **docs/reference.md**. When they disagree with
this file, those two win.

Personal or region-specific notes go in `CLAUDE.local.md`, which is ignored by
git.

---

## Repository rules

- **Comments, docstrings and runtime messages are in English.** What stays in
  French is what the code reads or compares (CSV columns such as `Surface`,
  `% du total`, `alertes`; `scenarios.json` keys; the `couverture` /
  `triangulation` criteria; `gestionnaires` match patterns; the column labels
  expected in a partner spreadsheet) and what the end client sees (QGIS group
  names, the generated scenarios markdown).
- **Never commit real data.** `data/` is ignored except `data/example/`, a
  fictitious region whose inputs only (`sites.csv`, `scenarios.json`,
  `README.md`) are versioned. No real site names, communes, coordinates,
  partner files or results in code, versioned docs or commit messages.
- Add files one by one — never `git add -A` / `git add .`.
- `config.py` is committed with `REGION = "example"`; a local working value
  must not end up in a commit.

---

## Where each script runs

Only `main.py` and `build_qgis_project.py` run in the **QGIS Python console**.
Everything else runs in a **terminal** from the repository root, with
`uv run python …`. Never paste a terminal script into QGIS: standalone scripts
reset PROJ/GDAL paths that QGIS depends on (see Pitfalls).

| script | where | role |
|---|---|---|
| `resolve_points_hauts.py` | terminal | partner spreadsheet (communes/addresses) → `sites.csv` |
| `find_anfr_candidates.py` | terminal | new high points from the ANFR register, ranked by blind spot |
| `audit_sites.py` | terminal | check declared heights against Lidar HD MNT/MNS |
| `experiments/generate_dem_fr.py` | terminal | Lidar HD surface model over WMS |
| `experiments/fill_dem_gaps.py` | terminal | fill Lidar HD holes in a surface model |
| `experiments/downsample_dem.py` | terminal | aggregate a DEM (`max` for a surface model) |
| `experiments/flatten_mast.py` | terminal | remove the camera's own mast from the surface model |
| `main.py` | **QGIS console** | compute the viewsheds |
| `summary.py` | terminal | areas, ranking, union, share per zone |
| `prioritise_sites.py` | terminal | zones of interest, marginal gain, greedy ranking |
| `scenario_layers.py` | terminal | per-scenario camera-count rasters |
| `build_qgis_project.py` | **QGIS console** | assemble the full QGIS project |
| `make_scenarios_md.py` | terminal | `docs/scenarios-<region>.md` |
| `package_project.py` | terminal | deliverable zip with relative paths |
| `analysis_shape/config_loader.py` | imported | load `config.py` by path, not via `sys.path` |
| `analysis_shape/zones.py` | imported | mask of a zone of interest (OLD, département, gpkg) |
| `analysis_shape/selection.py` | imported | the one greedy selection, shared |
| `analysis_shape/terrain.py` | imported | observer height corrected for the surface model |

---

## The chain for a new region (mirrors README « Quick start »)

```bash
# 1. [Terminal] cp -R data/example data/<region>; config.py → REGION,
#    VIEWSHED_RADIUS_M, TARGET_HEIGHT_M (decide the target height now)
# 2. [Terminal] sites.csv: Name;Latitude;Longitude;Owner;Height;Status
#    (Height = camera height ABOVE GROUND, never NGF); scenarios.json:
#    "regions", "zone", "dept". From a partner spreadsheet instead:
#    resolve_points_hauts.py, then READ resolution.csv (statut, alertes);
#    unknown communes → optional data/<region>/commune_alias.json
uv run python audit_sites.py --region <region>                    # 3
uv run python experiments/generate_dem_fr.py --region <region>    # 4, buffer = radius + 1 km
#    only if nodata > 0 → fill_dem_gaps.py; only if too slow at 5 m →
#    downsample_dem.py --method max + the two mv; only if a mast blocks its
#    own camera → flatten_mast.py
# 5. [QGIS Python console] new project saved in the repo → main.py
#    (check « ▶ REGION = … », then [i/N] per site)
uv run python summary.py --region <region> --zones dept           # 6
uv run python prioritise_sites.py --region <region> --zones dept --picks <n>
uv run python scenario_layers.py --region <region> --all          # 7 (--figer before delivery)
# 8. [QGIS Python console] exec(open('…/build_qgis_project.py').read())
uv run python make_scenarios_md.py --region <region>              # 9, before packaging
uv run python package_project.py <project>.qgz --light-dem 50
```

**The département has one source**: `"dept"` in `data/<region>/scenarios.json`,
read by `zones.region_dept()`; `--dept` only overrides it. It is required only
by the `dept` zone and the ANFR scripts (`resolve_points_hauts.py`,
`find_anfr_candidates.py`), which fail with a message saying where to set it.
Outside France or with a custom zone (`data/<region>/zones/<name>.gpkg`),
leave it out. Do not reintroduce a hardcoded default.

---

## Pitfalls — all hit, all costly

**PROJ broken by conda.** miniforge exports `PROJ_DATA` / `GDAL_DATA`
globally; its database is older than the wheels' and EPSG lookups fail
(`CRSError: The EPSG code is unknown`). Every standalone script starts with
`from proj_env import use_bundled_proj; use_bundled_proj()` **before**
importing pyproj / geopandas / rasterio. ⚠️ Never call it inside QGIS, which
relies on those variables.

**QGIS module cache.** The console keeps imported modules. `main.py` reloads
`config` by path (`analysis_shape/config_loader.py`) and prints
`▶ REGION = …` at start — check that line. It also reloads the
`analysis_shape/` modules **before** binding names from them: a reload placed
after `from X import y` rebinds nothing. `viewshed.py` reads the detection
envelope from `config` at call time, not at import, for the same reason.

**`main.py` must locate itself.** The repository is not an installed package,
so its root must be on `sys.path` before the first `analysis_shape` import.
Only the console's « open script » button defines `__file__`; with `exec()`
the script falls back on the saved project's folder.

**Unsaved QGIS project.** `main.py` derives its paths from the saved project.
Unsaved, it raises; saved elsewhere, outputs silently go to another folder.
Always save the project inside the repository **before** running.

**Never run `main.py` while the DEM is downloading.** QGIS can open
`dem_l93.tif` mid-write, read it as empty and keep that reading cached: every
viewshed then comes out as a full disc (π × radius²), identical from one site
to the next. Signature: two sites with exactly the same visible area. Stop,
remove the layer, delete `output/` **and** `dem_l93.tif.aux.xml` (which
remembers « 0 % valid »).

**The DEM download does not resume.** Unwritten blocks read back as 0 m, not
nodata, so `fill_dem_gaps.py` will not see them. Delete a partial file.

**Truncated INSEE codes in the ANFR export.** etalab drops the leading zero
(`02xxx` arrives as `2xxx`), so `startswith("21")` claims supports from
another département. Compare on `code.zfill(5)` and keep a distance check
against the département outline.

**NFD / NFC.** macOS stores file names in NFD, CSVs are NFC: any join between
names derived from files and `sites.csv` fails silently. Read every `Name`
through `analysis_shape/names.py::site_name()`, which also cleans path
characters (next pitfall).

**`nodata` on a binary mask.** Declaring `nodata=0` on a viewshed made
`gdal:rastercalculator` rewrite non-visible cells as 255, read back as
visible. A visibility mask has **no nodata**: 0 is a real value. Transparency
comes from `viewshed_style.qml`.

**Dots in site names.** `split(".")` on « 1.1 SITE A » cut at the first dot
and overwrote another site's normalized viewshed. Use `os.path.splitext`.

**Illegal path characters in names.** A motorway address may carry `/` or `>`.
The name becomes `viewshed_<Name>.tif`; a `/` reads as a missing subfolder,
`gdal.Create()` returns `None`, and the QGIS plugin crashes with
`'NoneType' object has no attribute 'SetProjection'` — no hint of the cause.
Every read of `Name` goes through `analysis_shape/names.py::site_name()`
(NFC, stripped, path-safe), so the file name and the CSV name agree in every
join. A script that reads `Name` any other way loses such sites silently.

**Sites appended after the DEM.** The DEM is framed on `sites.csv` at
download time. A site added later (ANFR candidates) can sit near its edge and
get a clipped viewshed. `terrain.check_dem_extent()` refuses it before the
first viewshed; the answer is a new DEM and an empty `output/`.

**`unary_union` on vectorised viewsheds.** `shapes()` returns disjoint parts;
the union was useless and took hours on ~90 000 polygons. `MultiPolygon` is
enough (`export.py`).

**Memory.** A full boolean mask per candidate exhausts RAM on a large pool.
`selection.WindowedMask` keeps only the bounding window of each viewshed
(~13× less) with an identical gain.

**Triangulation greedy with no installed camera.** No single camera
triangulates, so every gain was 0 and the greedy stopped before its first
pick. Coverage now breaks ties.

**Volumes.** At 5 m an uncompressed float32 viewshed is ~400 MB; they are
written as **uint8 + DEFLATE** (~1 MB). Merges work **by strips**.

**No pairwise overlap matrix.** `main.py` used to end with an N×N overlap
matrix nobody read, re-reading two full rasters per pair. It is gone;
`output.csv` keeps `Site`, `Surface`, `% du total`.

---

## Method decisions

**Lidar HD surface model, not SRTM.** SRTM (30 m) recovers only ~40-60 % of
canopy height, which dominates in flat wooded terrain. `generate_dem_fr.py`
fetches the MNS over **WMS** (`data.geopf.fr`), already in Lambert-93 — no
tiles to download or mosaic.

**Lidar HD is incomplete — plan the fallback.** The programme is rolling and
the plugin reads missing cells as pits. `fill_dem_gaps.py` fills them in
place from the photogrammetric correlation MNS
(`ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES.MNS`, national, carries the canopy;
against the lidar MNS: median +0.4 m, sd 2.6 m, so coverage stays a lower
bound), then a second pass with RGE ALTI finishes the rest. Where there is no
lidar at all, use `--product MNS_CORREL` directly. `dem_l93_source.tif`
records each pixel's origin (1 lidar, 2 correlation, 3 RGE ALTI). Sensitive
sites are masked in every IGN product except RGE ALTI, and RGE ALTI gives 0 m
over the sea — both correct to fill as bare ground.

**Always 5 m, then a local `max`.** Asking the WMS for 10 m averages
server-side and shaves canopy. `downsample_dem.py --method max` keeps the
tops. 10 m is enough to rank sites (±3 % per site against 5 m); 20 m starts to
*over*-estimate, as thin obstacles stop being resolved.

**Observer height on a surface model.** The plugin adds `OBS_HEIGHT` to the
DEM surface, where the supporting structure may already be: double counting.
`terrain.py` computes `OBS_HEIGHT = (MNT + mast) − MNS(pixel)` from the Lidar
HD MNT, falling back on RGE ALTI. It may be negative. Ground elevations are
cached in `data/<region>/ground_elevation.json` as `{"ground", "x", "y"}` per
site name: a site moved by more than 5 m is measured again, a network failure
is never cached, and older bare-number entries are still accepted.
`flatten_mast.py` additionally removes the mast from the *relief*, where it
could block its own camera.

**`TARGET_HEIGHT` counts above the MNS — on purpose.** A target at « ground +
20 m » under 25 m of canopy would sit inside the trees. The asymmetry with the
observer is a detection *delay* between forest and open ground, not a
geometric bias. Do not « fix » it to `MNT + height`.

**The detection envelope is a property of the run.** `VIEWSHED_RADIUS_M` and
`TARGET_HEIGHT_M` live in `config.py`; `main.py` records them in
`output/run.json`, which `summary.py` reads back. Because `main.py` skips
viewsheds already on disk, `viewshed.py` **refuses** to run when `run.json`
disagrees with the current setting. A folder of viewsheds without `run.json`
predates it and is compared against the old hardcoded 15000 m / 20 m. One
variant = one folder `data/<region>-<variant>/` sharing `sites.csv` and a
symlink to the DEM. A viewshed computed at radius R and clipped to r < R *is*
the viewshed at r, so computing wide once gives every smaller radius.
⚠️ The DEM buffer must be ≥ the radius; `generate_dem_fr.py` defaults to
`VIEWSHED_RADIUS_M` + 1 km from `config.py`.

**`TARGET_HEIGHT` is the most sensitive parameter.** It moves coverage far
more than the radius does; a longer radius mostly buys triangulation (more
cameras on the same ground) once the zone is already in range.

**Zones of interest, not raw area.** Raw km² ranks candidates very
differently from km² of what matters. `zones.py` rasterises a named zone onto
a viewshed grid: `old` (brush-clearing obligation zones, WFS
`DEBROUSSAILLEMENT:debroussaillement`), `dept` (département outline, cached),
or any `data/<region>/zones/<name>.gpkg`. Without OLD, the zone is the
département: much of what cameras see can fall in neighbouring ones.
⚠️ A zone percentage's denominator is measured on the **polygons**, never on
the mask (which only covers the DEM extent). The OLD WFS returns whole
polygons that touch the bbox: rasterise, never sum their areas.

**Two criteria, always both.** Coverage (≥ 1 camera) and triangulation
(≥ 2, needed to locate a fire) do not grow at the same rate and do not rank
sites the same way. Report both against the same total.

**One greedy selection.** `selection.greedy_pick` picks, at each step, the
site adding the most under the chosen criterion, optionally capped on
operator sites (`max_operateurs`) or stopped at a target percentage. Both
`prioritise_sites.py` and `scenario_layers.py` call it, so they cannot
disagree; « public only » is `max_operateurs=0`.

**Access cost is declared, not guessed.** Owner categories (public /
delegataire / operateur) are declared under `gestionnaires` in
`scenarios.json`, matched on accent- and case-insensitive substrings. An
unknown owner defaults to `operateur` (paid), so the affordable set is
understated rather than overstated. `Owner` carries the manager; `Status`
(`EN PLACE`) whether a camera is installed — mixing them erased the manager.

**Scenarios live in `data/<region>/scenarios.json`**, not in code: an explicit
list, or a rule (`en_place`, `meilleurs`, `cible_pct`, `tous`) optionally
restricted to a pool with `regions_candidats`. `scenario_layers.py --figer`
writes the resolved list next to its rule, so a delivered scenario stops
moving; an explicit list wins over any rule.

**Search for high points, don't just validate them.**
`find_anfr_candidates.py` narrows a département's ANFR supports in one pass:
usable kind, minimum height, distance to known sites, owner, then a
« blind spot » score — uncovered zone area within a detection-radius disc,
via an integral image, terrain ignored (an upper bound). Sorted and spaced
(`--ecart`), it is a shortlist; real viewsheds and the greedy decide.

**Heights from different sources disagree.** For water towers, ANFR
`SUP_NM_HAUT` describes the radio support *including* its antenna mast and
sits well above BD TOPO and the lidar MNH, which agree with each other: for a
camera, use BD TOPO corroborated by the lidar (`resolve_points_hauts.py
--hauteur ouvrage`, the default). Not true for lookout towers, where ANFR
describes the tower itself. BD TOPO building `hauteur` is inflated on slopes
(it comes from max roof − min ground); on relief only the pixel-wise lidar MNH
measures the structure. The lidar MNS does not see lattice towers. ANFR
coordinates are whole DMS seconds (~30 m): use them to match, never to place
an observer; its address field matches more reliably than BAN geocoding.

---

## Data sources

| what | where |
|---|---|
| Lidar HD MNS / MNT / MNH | WMS `data.geopf.fr/wms-r`, layers `IGNF_LIDAR-HD_MN{S,T,H}_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93` |
| Lidar HD coverage | `macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD` |
| OLD zones | WFS `data.geopf.fr/wfs/ows`, `DEBROUSSAILLEMENT:debroussaillement` |
| Radio supports | data.gouv.fr, « Données sur les installations radioélectriques de plus de 5 watts » → `SUP_SUPPORT`, with `SUP_NATURE`, `SUP_PROPRIETAIRE` |
| Structures with height | WFS `data.geopf.fr/wfs/ows`, `BDTOPO_V3:reservoir`, `BDTOPO_V3:pylone` |
| Address geocoding | `api-adresse.data.gouv.fr` (BAN) |
| Communes, outlines | `geo.api.gouv.fr/departements/<NN>/communes?fields=contour` |

---

## Known open points

**CRS lost on derived rasters.** Raw viewsheds are EPSG:2154, but
`normalized/` and `fusion/` come out with a `LOCAL_CS` WKT that pyproj cannot
transform. `zones.py` falls back on EPSG:2154; the cause in `export.py` is not
fixed.
