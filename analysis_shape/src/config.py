import os

DEFAULT_HEIGHT = 30  # Hauteur par défaut en mètres
PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA_PATH = os.path.join(PATH, "data")
VIEWSHED_STYLE_FILE_PATH = os.path.join(DATA_PATH, "Digital_Elevation_Model_basRhin.qml")
CSV_PATH = os.path.join(DATA_PATH, "pts_hauts.csv")
DEM_PATH = os.path.join(DATA_PATH, "dem_file_projected.tif")
OUTPUT_VIEWSHEDS_PATH = os.path.join(PATH, "viewsheds_geotiff")
os.makedirs(OUTPUT_VIEWSHEDS_PATH, exist_ok=True)