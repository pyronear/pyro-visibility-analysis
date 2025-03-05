import os 

# Imports des autres fichiers
from src.viewshed import process_csv_points as viewsheds_create
from src.utils import display_tif 
from src.area_analysis import area_tif, coverage_out_of_total_coverage
from src.utils import normalize
from src.utils import fusion

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

## Créer les viewpoints et les viewsheds
# viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut

# ## Pour chaque viewshed
# for file_name in os.listdir(VIEWSHEDS_PATH):
#     if file_name.endswith(".tif"):
#         file_path = os.path.join(VIEWSHEDS_PATH, f"{file_name}").replace("\\", "/")
#         ## Calculer la surface couverte
#         surface = area_tif(file_path, file_name)
#         print(f"Surface couverte par {file_name}: {surface} m²\n")
#         ## Créer une version normalisée du fichier pour pouvoir faire le calcul total 
#         normalize(file_path, output_path = NORM_VIEWSHEDS_PATH)

# ## Créer un fichier fusion pour calculer la surface totale couverte
# fusion(NORM_VIEWSHEDS_PATH, FUSION_PATH, "fusion.tif")
# # Afficher la surface totale couverte par l'ensemble des viewsheds sur une couche QGIS
# display_tif(os.path.join(FUSION_PATH, "fusion.tif"))
# # Calculer la surface totale couverte
# surface = area_tif(os.path.join(FUSION_PATH, "fusion.tif"), "fusion.tif")
# print(f"Surface couverte par {"fusion.tif"}: {surface} m²\n")

## Pour chaque viewshed
for file_name in os.listdir(VIEWSHEDS_PATH):
    if file_name.endswith(".tif"):
        file_path = os.path.join(VIEWSHEDS_PATH, f"{file_name}").replace("\\", "/")
        ## Calculer du pourcentage de surface couverte par rapport au total couvert
        p_surface = coverage_out_of_total_coverage(file_path, file_name,os.path.join(FUSION_PATH, "fusion.tif"), "fusion.tif")
        print(f"pourcentage de surface couverte par {file_name}: {p_surface*100} % \n")
        break