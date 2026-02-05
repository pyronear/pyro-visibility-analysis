from analysis_shape import utils
from analysis_shape.area_analysis import covered_surface
from analysis_shape.utils import display_tif, normalize_create, create_template, write_data, add_osm_background
from analysis_shape.viewshed import viewsheds_create
from qgis.core import (
    QgsProject,
    QgsCoordinateReferenceSystem
)
from analysis_shape.utils import display_tif
from pathlib import Path
import os
import csv
import importlib

# # === Force reload of local modules for debugging ===
# import analysis_shape.area_analysis
# import analysis_shape.utils
# import analysis_shape.viewshed
# importlib.reload(analysis_shape.area_analysis)
# importlib.reload(analysis_shape.utils)
# importlib.reload(analysis_shape.viewshed)


# === Paths Setup ===
try:
    BASE_PATH = Path(__file__).resolve().parent
except NameError:
    BASE_PATH = Path(QgsProject.instance().fileName()).parent

# VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
VISILITY_ANALYSIS_PATH = BASE_PATH

CSV_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data/sdis-67/sites.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(CSV_PATH), "output")

VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "viewsheds_geotiff")
NORM_VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "normalized")
OBSERVATION_POINTS_PATH = os.path.join(OUTPUT_DIR, "observation_points")
FUSION_PATH = os.path.join(OUTPUT_DIR, "fusion")
VIEWSHED_STYLE_FILE_PATH = os.path.join(OUTPUT_DIR, "viewshed_style.qml")
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
