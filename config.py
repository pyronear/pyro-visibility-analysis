# Single place to set the region/SDIS to analyse.
# Every script reads it as its default --region.
# It must match the folder name under data/, e.g. data/example/.
REGION = "example"

# Detection envelope handed to gdal_viewshed (compute_viewsheds.py), recorded
# in data/<region>/output/run.json with the viewsheds.
#
# Both were long hardcoded at 15 000 / 20 and never challenged, so every figure
# the project has produced is a lower bound. Field feedback from one SDIS shows
# incidents detected well beyond 15 km, hence the larger default.
#
# A viewshed computed at radius R and clipped to r < R *is* the viewshed at r —
# visibility is radial, so truncation is exact. Computing wide once therefore
# gives every smaller radius for free, and lets a run answer "and at 15 km?"
# without recomputing.
#
# ⚠️ The DEM must be generated with a buffer of at least this radius:
#     uv run python experiments/generate_dem_fr.py --buffer-km <radius + 1>
VIEWSHED_RADIUS_M = 20000

# Height above ground at which a smoke plume is considered detectable.
TARGET_HEIGHT_M = 25

# Earth curvature, with atmospheric refraction. The horizon drops by
# d² / 2R × (1 − REFRACTION): ~7 m at 10 km, ~27 m at 20 km, ~61 m at 30 km —
# the order of TARGET_HEIGHT_M. Every run ignored it until the QGIS plugin was
# replaced; measured on four départements, that overstated coverage by 0.3 to
# 1 point at 15 km and 3.4 at 30 km, triangulation more. 0.13 is the usual
# coefficient for visible light (and was the plugin's).
EARTH_CURVATURE = True
REFRACTION = 0.13
