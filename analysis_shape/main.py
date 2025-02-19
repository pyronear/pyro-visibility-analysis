import os 

# Imports des autres fichiers
from src.viewshed import process_csv_points as viewsheds_create
from src.utils import display_tif 
from src.area_analysis import area_tif
from src.utils import normalize
from src.utils import fusion

from qgis.core import QgsProject

# Chemin de base
VISILITY_ANALYSIS_PATH = os.path.dirname(__file__)
# Chemins relatifs 
DATA_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "data")
ELEVATION_MODEL_PATH = os.path.join(DATA_PATH, "Digital_Elevation_Model_basRhin.qml")
CSV_PATH = os.path.join(DATA_PATH, "pts_hauts.csv")
DEM_PROJECTED_PATH = os.path.join(DATA_PATH, "dem_file_projected.tif")
VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "viewsheds_geotiff")
os.makedirs(VIEWSHEDS_PATH, exist_ok=True)
NORM_VIEWSHEDS_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "normalized")  # Dossier pour stocker les rasters normalisés
FUSION_PATH = os.path.join(VISILITY_ANALYSIS_PATH, "fusion.tif")

layer_root = QgsProject.instance().layerTreeRoot()

if __name__ == "__main__":
    viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut
    for file_name in os.listdir(VIEWSHEDS_PATH):
        area_tif(VIEWSHEDS_PATH, file_name)   # Calculer la surface couverte par chaque viewshed
        normalize(os.path.join(VIEWSHEDS_PATH, f"{file_name}.tif"), NORM_VIEWSHEDS_PATH) # Normaliser les viewsheds
    fusion(NORM_VIEWSHEDS_PATH, FUSION_PATH) # Fusionner les surfaces en une seule couche 
    display_tif(FUSION_PATH) # Afficher la surface totale couverte par l'ensemble des viewsheds sur une couche QGIS
    area_tif(FUSION_PATH) # Calculer la surface totale couverte par l'ensemble des viewsheds

viewsheds_create(cvs_path = CSV_PATH, dem_path = DEM_PROJECTED_PATH,elevation_style_file = ELEVATION_MODEL_PATH,output = VIEWSHEDS_PATH, layer_tree_root = layer_root) # Afficher les surfaces pour chaque point haut
for file_name in os.listdir(VIEWSHEDS_PATH):
    area_tif(VIEWSHEDS_PATH, file_name)   # Calculer la surface couverte par chaque viewshed
    normalize(os.path.join(VIEWSHEDS_PATH, f"{file_name}.tif"), NORM_VIEWSHEDS_PATH) # Normaliser les viewsheds
fusion(NORM_VIEWSHEDS_PATH, FUSION_PATH) # Fusionner les surfaces en une seule couche 
display_tif(FUSION_PATH) # Afficher la surface totale couverte par l'ensemble des viewsheds sur une couche QGIS
area_tif(FUSION_PATH) # Calculer la surface totale couverte par l'ensemble des viewsheds