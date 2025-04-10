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

# === Function Imports ===
from analysis_shape.viewshed import viewsheds_create
from analysis_shape.utils import display_tif, normalize_create, create_template, write_data
from analysis_shape.area_analysis import covered_surface

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsLayerTreeLayer,
    QgsCoordinateReferenceSystem
)

# === Add OpenStreetMap background layer ===
def add_osm_background():
    osm_url = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    layer = QgsRasterLayer(osm_url, "OpenStreetMap", "wms")

    if not layer.isValid():
        print("❌ Failed to load OpenStreetMap layer")
        return

    # Add to bottom of layer tree
    QgsProject.instance().addMapLayer(layer, False)
    layer_node = QgsLayerTreeLayer(layer)
    root = QgsProject.instance().layerTreeRoot()
    root.insertChildNode(0, layer_node)

    print("🗺️ OpenStreetMap added as background")

# === Paths Setup ===
VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
CSV_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data/sdis-67/sites.csv")
OUTPUT_DIR = os.path.join(os.path.dirname(CSV_PATH), "output")

VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "viewsheds_geotiff")
NORM_VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "normalized")
FUSION_PATH = os.path.join(OUTPUT_DIR, "fusion")
ELEVATION_MODEL_PATH = os.path.join(OUTPUT_DIR, "Elevation_Model.qml")
DEM_PROJECTED_PATH = os.path.join(os.path.dirname(CSV_PATH), "dem_l93.tif")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "output.csv")

# Create output folders
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)
os.makedirs(NORM_VIEWSHEDS_PATH, exist_ok=True)
os.makedirs(FUSION_PATH, exist_ok=True)

# === Set up QGIS Project ===
project_crs = QgsCoordinateReferenceSystem("EPSG:2154")
QgsProject.instance().setCrs(project_crs)

# === Add OSM background first ===
add_osm_background()

# === Run visibility analysis pipeline ===

# 1. Create viewpoints & viewsheds
viewsheds_create(
    cvs_path=CSV_PATH,
    dem_path=DEM_PROJECTED_PATH,
    elevation_style_file=ELEVATION_MODEL_PATH,
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
display_tif(os.path.join(FUSION_PATH, f"fusion_or_all_{CSV_name}.tif"))
