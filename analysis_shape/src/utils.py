import csv
import os
from qgis.core import QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem
from qgis import processing

def read_csv(file_path):
    with open(file_path, newline='', encoding='utf-8') as csvfile:
        return list(csv.DictReader(csvfile, delimiter=';'))

def display_tif(file):
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

def normalize(file_path, output_path): # Remplace la valeur NaN des GeoTIFF par 0
    file_name =file_path.split("/")[-1].split(".")[0]
    processing.run("gdal:rastercalculator", {'INPUT_A':file_path,'BAND_A':1,'INPUT_B':None,'BAND_B':None,
                                            'INPUT_C':None,'BAND_C':None,'INPUT_D':None,'BAND_D':None,
                                            'INPUT_E':None,'BAND_E':None,'INPUT_F':None,'BAND_F':None,
                                            'FORMULA':'nan_to_num(A)','NO_DATA':None,'EXTENT_OPT':0,
                                            'PROJWIN':None,'RTYPE':5,'OPTIONS':'','EXTRA':'',
                                            'OUTPUT':os.path.join(output_path, f"norm_{file_name}.tif")})


def fusion_or(norm_files, output): # Fusionne les GeoTIFF normalisés en une seule couche 

    # Correction de l'expression pour inclure les guillemets et "@1"
    expression = " OR ".join([f'"{os.path.splitext(os.path.basename(filename))[0]}@1"' for filename in norm_files])
    expression = f"'{expression}'"  # Encapsuler l'expression entre apostrophes
    
    # Exécution du calcul raster
    processing.run("native:rastercalc", {
        'LAYERS': norm_files,
        'EXPRESSION': expression,
        'EXTENT': None,
        'CELL_SIZE': None,
        'CRS': QgsCoordinateReferenceSystem('IGNF:ED50UTM31.IGN69'),
        'OUTPUT': output
    })

    print(f"Fusion OR des rasters terminée. Résultat enregistré sous {output}.")

def fusion_and(norm_files, output): # Fusionne les GeoTIFF normalisés en une seule couche 

    # Correction de l'expression pour inclure les guillemets et "@1"
    expression = " AND ".join([f'"{os.path.splitext(os.path.basename(filename))[0]}@1"' for filename in norm_files])
    expression = f"'{expression}'"  # Encapsuler l'expression entre apostrophes
    
    # Exécution du calcul raster
    processing.run("native:rastercalc", {
        'LAYERS': norm_files,
        'EXPRESSION': expression,
        'EXTENT': None,
        'CELL_SIZE': None,
        'CRS': QgsCoordinateReferenceSystem('IGNF:ED50UTM31.IGN69'),
        'OUTPUT': output
    })

    print(f"Fusion OR des rasters terminée. Résultat enregistré sous {output}.")

## Ajout de la colonne "name" qui effectue l'analyse "fct" au csv
def update_single(csv_path, viewsheds_path, name, fct):
    # Lire le CSV d'origine
    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        lecteur_csv = csv.DictReader(csvfile, delimiter=';')
        lignes = list(lecteur_csv)
        
        # Vérifier si la colonne existe déjà
        colonnes = lecteur_csv.fieldnames
        if name not in colonnes:
            colonnes.append(name)  # Ajouter la colonne uniquement si elle n'existe pas

    # Calculer les surfaces couvertes et mettre à jour les lignes
    for ligne in lignes:
        nom_point = ligne['Nom']
        viewshed_file = os.path.join(viewsheds_path, f"viewshed_{nom_point}.tif")
        if os.path.exists(viewshed_file):
            surface = fct(viewshed_file, f"viewshed_{nom_point}.tif")
            ligne[name] = surface
        else:
            ligne[name] = "N/A"

    with open(csv_path, mode='w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=colonnes, delimiter=';')
        writer.writeheader()
        writer.writerows(lignes)