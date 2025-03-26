import csv
import os

# Imports des autres fichiers
from src.viewshed import viewsheds_create
from src.area_analysis import coverage, coverage_out_of_total_coverage
from src.utils import display_tif, normalize, fusion_or, fusion_and, create_template, write_data
from qgis.core import QgsProject

# Setup

VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
DATA_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data")

ELEVATION_MODEL_PATH = os.path.join(DATA_PATH, "Digital_Elevation_Model_basRhin.qml")   # To modify if needed

CSV_PATH = os.path.join(DATA_PATH, "pts_hauts_2.csv") # To modify id needed

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
viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH, elevation_style_file = ELEVATION_MODEL_PATH, output = VIEWSHEDS_PATH, layer_tree_root = layer_root)


# Create a normalized version of the viewsheds to compute area covered
for file_name in os.listdir(VIEWSHEDS_PATH):
    if file_name.endswith(".tif"):
        file_path = os.path.join(VIEWSHEDS_PATH, f"{file_name}").replace("\\", "/")
        normalize(file_path, output_path = NORM_VIEWSHEDS_PATH)

# Create a fusion file to compute total area covered
norm_tif_files = [os.path.join(NORM_VIEWSHEDS_PATH, f).replace("\\", "/") for f in os.listdir(NORM_VIEWSHEDS_PATH) if f.endswith(".tif")]
fusion_or(norm_tif_files, os.path.join(FUSION_PATH, "fusion_or_all.tif"))

# Afficher la surface totale couverte par l'ensemble des viewsheds sur une couche QGIS
display_tif(os.path.join(FUSION_PATH, "fusion_or_all.tif"))

## Dictionnaire avec les valeurs de sortie
output = {} 

# Calculer la surface totale couverte
for path in norm_tif_files:
    name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
    
    output[name] = {"Surface" : coverage(path)}
    print(f"Surface couverte par {name} ajoutée au dictionnaire")

## Dictionnaire avec les valeurs de sortie
output = {} 

# Initialisation du dictionnaire (Surtout à ne pas enlever)
for path in norm_tif_files:
    name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
    output.setdefault(name, {})
    output[name].setdefault("Surface", None)
    output[name].setdefault("p_surface", None)
    output[name].setdefault("r_surface", None)
    for path2 in norm_tif_files:
        name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        output[name].setdefault(name2, None)

for path in norm_tif_files:
    name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
    
    output[name]["Surface"] = coverage(path)
    output[name]["p_surface"] = coverage_out_of_total_coverage(path, os.path.join(FUSION_PATH, "fusion_or_all.tif"))

    other_paths = [x for x in norm_tif_files if x != path]

    # Recouvrement 2 à 2
    output[name].setdefault(name, 1)
    for path2 in other_paths:
        name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        if output[name][name2] == None:
            fusion_22_path = os.path.join(FUSION_PATH, f"fusion_and_{name}_{name2}.tif")
            fusion_and([path, path2],fusion_22_path)
            cov = coverage(fusion_22_path)
            output[name][name2] = cov
            output[name2][name] = cov  
    print(f"{name} ajouté au dictionnaire")  

columns = ["Nom", "Latitude", "Longitude", "Hauteur"]
create_template(CSV_PATH, OUTPUT_PATH, columns)
write_data(OUTPUT_PATH, output)
