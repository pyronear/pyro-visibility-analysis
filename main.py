# === Paths Setup ===
# Must come before importing anything from analysis_shape: the repo is not an
# installed package, so its directory has to be on sys.path first.
#
# `__file__` is undefined when the script is pasted into the QGIS Python Console
# or run with exec(Path(...).read_text()) — only the console's "open script"
# button defines it. Fall back to the saved project's directory, which is why the
# project must live inside the repo.
import importlib
import os
import sys
from pathlib import Path

from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem
)

try:
    VISILITY_ANALYSIS_PATH = Path(__file__).resolve().parent
except NameError:
    project_file = QgsProject.instance().fileName()
    if not project_file:
        raise RuntimeError(
            "Save the QGIS project inside the pyro-visibility-analysis "
            "directory before running this script."
        )
    VISILITY_ANALYSIS_PATH = Path(project_file).resolve().parent

if str(VISILITY_ANALYSIS_PATH) not in sys.path:
    sys.path.insert(0, str(VISILITY_ANALYSIS_PATH))

import csv  # noqa: E402

# The QGIS Python console keeps modules cached between runs, so editing anything
# under analysis_shape/ and re-running would silently execute the old version.
# Reload before binding the names: reloading a module does not rebind names
# already imported from it, so the order here is what makes the refresh real.
# Dependencies first — viewshed holds references into terrain and utils.
import analysis_shape.terrain  # noqa: E402
import analysis_shape.area_analysis  # noqa: E402
import analysis_shape.utils  # noqa: E402
import analysis_shape.viewshed  # noqa: E402

for _module in (analysis_shape.terrain, analysis_shape.area_analysis,
                analysis_shape.utils, analysis_shape.viewshed):
    importlib.reload(_module)

from analysis_shape.area_analysis import covered_surface  # noqa: E402
from analysis_shape.utils import (  # noqa: E402
    display_tif, normalize_create, create_template, write_data,
    add_osm_background,
)
from analysis_shape.viewshed import viewsheds_create  # noqa: E402

# The QGIS Python console keeps modules cached between runs, so editing
# config.py and re-running this script would silently reuse the previous
# REGION — and write the results into the wrong folder. Force a fresh read.
# `importlib.reload(config)` is not enough: it needs sys.path, which the
# console may have lost, and then raises « spec not found for the module
# 'config' » even though `import config` succeeds from the cache — on the old
# region. See analysis_shape/config_loader.py.
import analysis_shape.config_loader  # noqa: E402
importlib.reload(analysis_shape.config_loader)
config = analysis_shape.config_loader.load_config()
REGION = config.REGION
print(f"▶ REGION = {REGION}")

CSV_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data", REGION, "sites.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(CSV_PATH), "output")

VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "viewsheds_geotiff")
NORM_VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "normalized")
OBSERVATION_POINTS_PATH = os.path.join(OUTPUT_DIR, "observation_points")
FUSION_PATH = os.path.join(OUTPUT_DIR, "fusion")
VIEWSHED_STYLE_FILE_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "viewshed_style.qml")
DEM_PROJECTED_PATH = os.path.join(os.path.dirname(CSV_PATH), "dem_l93.tif")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "output.csv")

# Create output folders
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)
os.makedirs(NORM_VIEWSHEDS_PATH, exist_ok=True)
os.makedirs(OBSERVATION_POINTS_PATH, exist_ok=True)
os.makedirs(FUSION_PATH, exist_ok=True)

# === Set up QGIS Project ===
project_crs = QgsCoordinateReferenceSystem("EPSG:2154")
QgsProject.instance().setCrs(project_crs)

# === Add OpenStreetMap background layer ===
add_osm_background()

# === Run visibility analysis pipeline ===

# 1. Create viewpoints & viewsheds
viewsheds_create(
    csv_path=CSV_PATH,
    dem_path=DEM_PROJECTED_PATH,
    elevation_style_file=VIEWSHED_STYLE_FILE_PATH,
    output=VIEWSHEDS_PATH,
    layer_tree_root=QgsProject.instance().layerTreeRoot()
)

# 2. Normalize the viewsheds
normalize_create(VIEWSHEDS_PATH, NORM_VIEWSHEDS_PATH)

# 3. Create a trimmed CSV from selected input columns
columns = ["Name", "Latitude", "Longitude", "Height"]
create_template(CSV_PATH, OUTPUT_PATH, columns)

# 4. Perform area analysis
dic = covered_surface(NORM_VIEWSHEDS_PATH, FUSION_PATH, CSV_PATH)

# 5. Write output CSV
write_data(OUTPUT_PATH, dic)

print("✅ Analysis completed.")

# 6. Display final fused viewshed
CSV_name = os.path.splitext(os.path.basename(CSV_PATH))[0]
display_tif(os.path.join(
    FUSION_PATH, f"fusion_or_all_{CSV_name}.tif"), group_name="Viewsheds_merged", style_file_path=VIEWSHED_STYLE_FILE_PATH)
