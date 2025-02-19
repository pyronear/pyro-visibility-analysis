from qgis.core import QgsRasterLayer, QgsProject, QgsCoordinateReferenceSystem
import os

# Définition des chemins
ANALYSIS_PATH = os.path.dirname(__file__)
VIEWSHEDS_PATH = os.path.join(ANALYSIS_PATH, "Viewsheds_geotiff")
NORM_VIEWSHEDS_PATH = os.path.join(ANALYSIS_PATH, "normalized")  # Dossier pour stocker les rasters normalisés
output_fusion = os.path.join(ANALYSIS_PATH, "fusion.tif")

# Vérifier et créer le dossier normalized s'il n'existe pas
if not os.path.exists(NORM_VIEWSHEDS_PATH):
    os.makedirs(NORM_VIEWSHEDS_PATH)

# Récupérer tous les fichiers .tif dans le dossier Viewsheds_geotiff
tif_files = [os.path.splitext(f)[0] for f in os.listdir(VIEWSHEDS_PATH) if f.endswith(".tif")]

def normalisation(tif_files):
# Étape 1 : Normalisation (remplacement de NaN par 0)
    for filename in tif_files:
        input_file = os.path.join(VIEWSHEDS_PATH, f"{filename}.tif")
        processing.run("gdal:rastercalculator", {'INPUT_A':input_file,'BAND_A':1,'INPUT_B':None,'BAND_B':None,'INPUT_C':None,'BAND_C':None,'INPUT_D':None,'BAND_D':None,'INPUT_E':None,'BAND_E':None,'INPUT_F':None,'BAND_F':None,'FORMULA':'nan_to_num(A)','NO_DATA':None,'EXTENT_OPT':0,'PROJWIN':None,'RTYPE':5,'OPTIONS':'','EXTRA':'','OUTPUT': os.path.join(NORM_VIEWSHEDS_PATH, f"norm_{filename}.tif")})

# Récupérer tous les fichiers .tif normalisés dans le dossier normalized
norm_tif_files = [os.path.splitext(f)[0] for f in os.listdir(NORM_VIEWSHEDS_PATH) if f.endswith(".tif")]

# Étape 2 : Fusion avec l'opérateur OR
def fusion(norm_tif_files):
    input_files = [os.path.join(NORM_VIEWSHEDS_PATH, f"{filename}.tif") for filename in norm_tif_files]
    
    # Correction de l'expression pour inclure les guillemets et "@1"
    expression = " OR ".join([f'"{filename}@1"' for filename in norm_tif_files])
    expression = f"'{expression}'"  # Encapsuler l'expression entre apostrophes

    # Exécution du calcul raster
    processing.run("native:rastercalc", {
        'LAYERS': input_files,
        'EXPRESSION': expression,
        'EXTENT': None,
        'CELL_SIZE': None,
        'CRS': QgsCoordinateReferenceSystem('IGNF:ED50UTM31.IGN69'),
        'OUTPUT': output_fusion
    })

    print(f"Fusion des rasters terminée. Résultat enregistré sous {output_fusion}.")

normalisation(tif_files)
fusion(norm_tif_files)