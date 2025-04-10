import os 
import csv

# Force reload
import importlib
import analysis_shape.area_analysis
import analysis_shape.utils
importlib.reload(analysis_shape.area_analysis)
importlib.reload(analysis_shape.utils)


## Imports of used functions
import analysis_shape.area_analysis
from analysis_shape.viewshed import viewsheds_create

from analysis_shape.utils import display_tif, normalize_create, create_template, write_data
from analysis_shape.area_analysis import covered_surface
from qgis.core import QgsProject

## Paths Setup
# Solution path (principal)
VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)

CSV_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data/sdis-67/sites.csv")

OUTPUT_DIR = os.path.join(os.path.dirname(CSV_PATH), "output")

# Paths based on the solution path
VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "viewsheds_geotiff")
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)
NORM_VIEWSHEDS_PATH = os.path.join(OUTPUT_DIR, "normalized")
os.makedirs(NORM_VIEWSHEDS_PATH, exist_ok=True)
FUSION_PATH = os.path.join(OUTPUT_DIR, "fusion")
os.makedirs(FUSION_PATH, exist_ok=True)

# Inputs / Ouptuts
ELEVATION_MODEL_PATH = os.path.join(OUTPUT_DIR, "Elevation_Model.qml")   # To modify if needed

DEM_PROJECTED_PATH = os.path.join(os.path.dirname(CSV_PATH), "dem_l93.tif")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "output.csv") # To modify if needed

# Project layers
layer_root = QgsProject.instance().layerTreeRoot()


## Main functions
# Create viewpoints & viewsheds
viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut

# Create normalized files
normalize_create(VIEWSHEDS_PATH, NORM_VIEWSHEDS_PATH)

# Choosing the columns to keep from the input CSV file to create the output CSV file
columns = ["Name", "Latitude", "Longitude", "Height"]
# Create the output CSV file with the chosen columns
create_template(CSV_PATH, OUTPUT_PATH, columns)
# Dictionary with the content of the main analysis functions
dic = covered_surface(NORM_VIEWSHEDS_PATH, FUSION_PATH, CSV_PATH)
# Writing in the output file
write_data(OUTPUT_PATH, dic)

print("Analysis completed.")

# Display total covered surface by all viewsheds on a QGIS layer
CSV_name = os.path.splitext(os.path.basename(CSV_PATH))[0]
display_tif(os.path.join(FUSION_PATH, f"fusion_or_all_{CSV_name}.tif"))
