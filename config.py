# Single place to set the region/SDIS to analyse.
# All scripts (generate_dem.py, main.py, export.py, visualize.py) read this.
# It must match the folder name under data/, e.g. data/example/.
REGION = "example"

# Detection envelope handed to the visibility plugin.
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
