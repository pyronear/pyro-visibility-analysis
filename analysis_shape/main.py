import os 
import csv

# Imports des autres fichiers
from src.viewshed import process_csv_points as viewsheds_create
from src.area_analysis import coverage, coverage_out_of_total_coverage, reccurent_coverage
from src.utils import display_tif, normalize, fusion_or, fusion_and, update_single

from qgis.core import QgsProject

# Chemin de base
VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
# Chemins relatifs 
DATA_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data")
ELEVATION_MODEL_PATH = os.path.join(DATA_PATH, "Digital_Elevation_Model_basRhin.qml")
CSV_PATH = os.path.join(DATA_PATH, "pts_hauts_2.csv")
DEM_PROJECTED_PATH = os.path.join(DATA_PATH, "dem_file_projected.tif")
VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "viewsheds_geotiff")
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)
NORM_VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "normalized")  # Dossier pour stocker les rasters normalisés
os.makedirs(NORM_VIEWSHEDS_PATH, exist_ok=True)
FUSION_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "fusion")
os.makedirs(FUSION_PATH, exist_ok=True)
layer_root = QgsProject.instance().layerTreeRoot()


# Créer les viewpoints et les viewsheds
viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut


# # Calculer la surface couverte
# update_single(CSV_PATH, VIEWSHEDS_PATH, "Surface couverte", coverage)
# print(f"CSV mis à jour")


# Créer une version normalisée des viewsheds pour pouvoir faire le calcul total 
for file_name in os.listdir(VIEWSHEDS_PATH):
    if file_name.endswith(".tif"):
        file_path = os.path.join(VIEWSHEDS_PATH, f"{file_name}").replace("\\", "/")
        normalize(file_path, output_path = NORM_VIEWSHEDS_PATH)

# Créer un fichier fusion pour calculer la surface totale couverte
norm_tif_files = [os.path.join(NORM_VIEWSHEDS_PATH, f).replace("\\", "/") for f in os.listdir(NORM_VIEWSHEDS_PATH) if f.endswith(".tif")]
fusion_or(norm_tif_files, os.path.join(FUSION_PATH, "fusion_or_all.tif"))

# Afficher la surface totale couverte par l'ensemble des viewsheds sur une couche QGIS
display_tif(os.path.join(FUSION_PATH, "fusion_or_all.tif"))

# Calculer la surface totale couverte
surface = coverage(os.path.join(FUSION_PATH, "fusion_or_all.tif"))
print(f"Surface totale couverte : {surface} m²\n")


# Tester la fonction coverage_out_of_total_coverage
p_surface = coverage_out_of_total_coverage(norm_tif_files[0], os.path.join(FUSION_PATH, "fusion_or_all.tif"))
print(f"pourcentage de surface couverte par {norm_tif_files[0].split("/")[-1]}: {p_surface*100} % \n")

# Tester la fonction reccurent_coverage 
fusion_and([norm_tif_files[0], os.path.join(FUSION_PATH, "fusion_or_all.tif")],os.path.join(FUSION_PATH, "fusion_and_test.tif"))
r_surface = reccurent_coverage(norm_tif_files[0],os.path.join(FUSION_PATH, "fusion_and_test.tif"))
print(f"pourcentage couvert par {norm_tif_files[0].split("/")[-1]} déjà couverte: {r_surface*100} % \n")
