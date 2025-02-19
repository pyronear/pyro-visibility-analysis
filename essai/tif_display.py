from qgis.core import QgsRasterLayer, QgsProject
import os

ANALYSIS_PATH = os.path.dirname(__file__)
output_file = os.path.join(ANALYSIS_PATH, "fusion.tif")

# Charger le raster dans QGIS
def tif_display(file):
    print(file)
    layer_name = os.path.splitext(os.path.basename(file))[0]
    raster_layer = QgsRasterLayer(file, layer_name)
    root = QgsProject.instance().layerTreeRoot()
    
    # Vérifier si le raster est valide et l'ajouter à QGIS
    if raster_layer.isValid():
        # Trouver la couche existante 'dem_file_projected' dans le projet
        dem_layer = QgsProject.instance().mapLayersByName("dem_file_projected")
        
        if dem_layer:
            # Récupérer le CRS de la couche 'dem_file_projected'
            crs = dem_layer[0].crs()
            print(f"Le CRS de la couche 'dem_file_projected' est {crs.authid()}.")
            
            # Appliquer le CRS de la couche 'dem_file_projected' à la nouvelle couche
            raster_layer.setCrs(crs)
        
        QgsProject.instance().addMapLayer(raster_layer, False)
        group = root.insertGroup(0, "Viewsheds_merged")
        group.addLayer(raster_layer)
        print(f"Le raster {layer_name} a été ajouté à QGIS.")
        
    else:
        print("Erreur : Impossible d'ajouter le raster à QGIS.")
        

tif_display(output_file)

# NORM_VIEWSHEDS_PATH = os.path.join(ANALYSIS_PATH, "normalized") 
# tif_files = [os.path.join(NORM_VIEWSHEDS_PATH, f) for f in os.listdir(NORM_VIEWSHEDS_PATH) if f.endswith(".tif")]
# print(tif_files)
# for file in tif_files:
#     tif_display(file)
