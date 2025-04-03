import csv
import os

# Imports of used functions
from src.viewshed import viewsheds_create
from src.utils import display_tif, normalize_create, create_template, write_data
from src.area_analysis import covered_surface
from qgis.core import QgsProject

# Paths Setup

VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
DATA_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data")

ELEVATION_MODEL_PATH = os.path.join(DATA_PATH, "Digital_Elevation_Model_basRhin.qml")   # To modify if needed

CSV_PATH = os.path.join(DATA_PATH, "pts_hauts_1.csv") # To modify if needed

DEM_PROJECTED_PATH = os.path.join(DATA_PATH, "dem_file_projected.tif")

VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "viewsheds_geotiff")
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)

NORM_VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "normalized")
os.makedirs(NORM_VIEWSHEDS_PATH, exist_ok=True)

FUSION_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "fusion")
os.makedirs(FUSION_PATH, exist_ok=True)

layer_root = QgsProject.instance().layerTreeRoot()

OUTPUT_PATH = os.path.join(DATA_PATH, "output.csv")


# Create viewpoints & viewsheds
viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut

# Create normalized files
normalize_create(VIEWSHEDS_PATH, NORM_VIEWSHEDS_PATH)

columns = ["Nom", "Latitude", "Longitude", "Hauteur"]

create_template(CSV_PATH, OUTPUT_PATH, columns)
dic = covered_surface(NORM_VIEWSHEDS_PATH, FUSION_PATH, CSV_PATH)
write_data(OUTPUT_PATH, dic)
print("over")

# Display total covered surface by all viewsheds on a QGIS layer
display_tif(os.path.join(FUSION_PATH, f"fusion_or_all_{CSV_PATH}.tif"))