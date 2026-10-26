# Viewsheds: GDAL `gdal_viewshed` against the QGIS plugin

Validation behind the switch from the QGIS *Visibility Analysis* plugin to
GDAL's `gdal_viewshed` (`compute_viewsheds.py`), and behind turning Earth
curvature on. Measured on four départements recently analysed with the former
chain (190 sites), named A to D below.

## Verdict

- **Same results.** 179 sites out of 190 within ±3 % of the plugin's visible
  area; coverage and triangulation of each département within 0.5 point; the
  greedy selection picks the same or equally good sites.
- **50 to 100 times faster**, from a terminal: a pool of 137 sites in 24 s
  (about two hours in the QGIS console), no QGIS, no saved project.
- **One condition: GDAL ≥ 3.13.** Older versions let the observer's own cell
  block the view (see below). The chain runs the official GDAL 3.13.3 image in
  Docker by default.
- **Separate finding: Earth curvature was off.** The plugin ran without it.
  Turning it on lowers coverage by 0.3 to 1 point at 15 km and 3.4 points at
  30 km, triangulation more. It is now on by default.

## How the two methods work

**QGIS plugin** (Čučković, *Visibility Analysis* 1.9.2, numpy). For each
observer it traces explicit lines of sight to every cell at the edge of the
radius, for one octant mirrored eight times. Along each line, terrain height
is interpolated between the two pixels the line passes between, turned into a
slope (height difference / distance), and a running maximum of that slope is
the horizon. A cell is visible if its slope, target height included, reaches
the horizon. Lines start at the neighbouring cell, so the observer's cell is
never an obstacle. Single-threaded; curvature optional and off in our runs.

**GDAL `gdal_viewshed`** (C++, Wang et al. 2000, "reference planes"). No
explicit rays: it sweeps the grid outward from the observer in one pass and
derives each cell's horizon from the one or two already-processed cells on the
observer's side, by projecting the plane through them, then compares it with
the cell's own height. One pass over the cells, hence the speed. The horizon
is inferred rather than traced, which makes it slightly more conservative next
to a large obstacle.

Both place the observer and the target *above the DEM cell* and return a 0/1
mask: same inputs, same meaning. The observer-height correction for surface
models (`terrain.py`) and the target-height convention carry over unchanged.

## Setup

- Same DEM as the reference runs (Lidar HD surface model, 10 m), same radius
  and target height, same observer heights (`terrain.py`, cached ground).
- Curvature off on the GDAL side for the comparison, as in the plugin runs.
- GDAL 3.13.3, through `compute_viewsheds.py` as merged.

| | terrain | sites | radius / target |
|---|---|---|---|
| A | flat, wooded, water towers | 14 | 15 km / 20 m |
| B | steep relief, lookout towers | 32 | 15 km / 20 m |
| C | mountains and plain | 7 | 30 km / 20 m |
| D | rolling, large candidate pool | 137 | 20 km / 25 m |

## Results

| | area gap, median | mean \|gap\| | within ±3 % | IoU, median | rank corr. | coverage plugin → GDAL | triangulation plugin → GDAL |
|---|---|---|---|---|---|---|---|
| A | +0.7 % | 1.8 % | 12 / 14 | 0.94 | 1.00 | 82.5 → 82.5 % | 53.4 → 53.6 % |
| B | +0.2 % | 1.4 % | 29 / 32 | 0.97 | 0.94 | 68.4 → 68.3 % | 46.2 → 45.8 % |
| C | −0.9 % | 1.9 % | 6 / 7 | 0.88 | 1.00 | 31.4 → 30.9 % | 7.3 → 7.6 % |
| D | +0.1 % | 0.6 % | 132 / 137 | 0.95 | 1.00 | 95.1 → 95.0 % | 87.5 → 87.3 % |

*Area gap = (GDAL − plugin) / plugin, per site. IoU = intersection over union
of the two masks. Rank corr. = Spearman correlation of the site areas.
Coverage (≥ 1 camera) and triangulation (≥ 2) are shares of the département.*

**Selection.** `selection.greedy_pick` on each set, then GDAL's picks scored
on the plugin's viewsheds:

| | criterion, picks | same sites | plugin's pick | GDAL's pick |
|---|---|---|---|---|
| A | coverage, 14 | 14 / 14 | 82.52 % | 82.52 % |
| A | triangulation, 14 | 14 / 14 | 53.38 % | 53.38 % |
| B | coverage, 16 | 14 / 16 | 59.40 % | 59.21 % |
| B | triangulation, 16 | 16 / 16 | 31.17 % | 31.17 % |
| C | both, 7 | 7 / 7 | identical | identical |
| D | coverage, 20 | 19 / 20 | 82.16 % | 82.42 % |
| D | triangulation, 20 | 20 / 20 | 48.32 % | 48.32 % |

Where the sites differ they are near-ties: the result moves by 0.2 point at
most, in either direction.

**By distance**, the engines agree within 1–2 % beyond 5 km in every region;
what differences remain sit close to the camera.

## Where they disagree: an obstacle at the camera's height

3 sites out of 190 differ by more than 5 % (−28 %, −10 %, +6 %). In such cases
a cell within 20 m of the camera stands at or above the camera's own height —
a water tower's roof just above the camera, canopy around a low mast. The view
then hinges on one or two pixels, which the two methods treat differently
(interpolated slope against projected plane). Neither figure is reliable for
such a site: it is an input problem, which `flatten_mast.py` or a corrected
height addresses.

## GDAL before 3.13: the observer's own cell

On a surface model the camera often sits just below the top of its own
structure, giving a negative observer height. GDAL 3.6 let the observer's own
cell block the view: one water tower saw 247 km² at −0.9 m but 501 km² at
+0.5 m, and five sites of region A lost 50 to 80 % (coverage 82.5 → 74.9 %).
GDAL 3.13 does not: with or without a workaround (lowering that cell below the
camera), its results are identical within 0.2 % on every site. Hence the
requirement, checked at run time.

## Earth curvature

The horizon drops by d² / 2R × (1 − k), with refraction k = 0.13:

| distance | 5 km | 10 km | 15 km | 20 km | 25 km | 30 km |
|---|---|---|---|---|---|---|
| drop | 1.7 m | 6.8 m | 15 m | 27 m | 43 m | 61 m |

This is a drop below the observer's horizontal, not a visibility limit: on
flat ground a 10 m target stays visible from 40 m up to ~36 km, a 20 m target
up to ~41 km. What curvature removes is the visibility gained by a narrow
margin, behind a crest or a forest edge, at long range. Measured, curvature
off → on:

| | radius | coverage | triangulation | site area, median |
|---|---|---|---|---|
| A | 15 km | 82.5 → 81.4 % | 53.6 → 51.4 % | −4.0 % |
| B | 15 km | 68.3 → 68.1 % | 45.8 → 45.2 % | −1.1 % |
| D | 20 km | 95.0 → 94.5 % | 87.3 → 86.0 % | −7.3 % |
| C | 30 km | 30.9 → 27.5 % | 7.6 → 5.2 % | −24.5 % |

Rankings barely move (rank correlation ≥ 0.96). Figures produced before this
change are optimistic in proportion to their radius.

## Docker against a native GDAL

| | sites | native 3.13.3 | Docker 3.13.3 | outputs |
|---|---|---|---|---|
| B | 32 | 3 s | 4 s | identical, pixel for pixel |
| D | 137 | 18 s | 22 s | identical, pixel for pixel |

About 20 % slower on macOS (bind-mounted files), negligible next to the
former minute per site. Docker is the default because it pins the GDAL
version and needs no install beyond Docker; a native GDAL ≥ 3.13 remains
possible (`GDAL_VIEWSHED`, see `docs/reference.md`).
