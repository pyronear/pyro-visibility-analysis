import csv
import os
from qgis.core import QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem
from qgis import processing

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

    # Vérification si le fichier de sortie existe déjà
    if os.path.exists(output):
        print(f"⚠ Le fichier {output} existe déjà. Pass.")
        return
    
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

    # Vérification si le fichier de sortie existe déjà
    if os.path.exists(output):
        print(f"⚠ Le fichier {output} existe déjà. Pass.")
        return

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

    print(f"Fusion AND des rasters terminée. Résultat enregistré sous {output}.")

def read_csv(csv_path):    # return a list of all lines of the csv at csv_path as dictionaries with the same keys (the columns)
    try:
        with open(csv_path, mode="r", newline="", encoding="utf-8") as csv_file:
            reader = list(csv.DictReader(csv_file, delimiter=';')) # watchout for the delimiter
        return reader

    except Exception as e:
        print(f"❌ Error while reading the csv at {csv_path} : {e}")

def write_data(csv_path, list_dic):    # open the csv at csv_path and fill it with data in the list of dictionaries list_dic
    try:
        data = transform_dic(list_dic)
        columns = data[0].keys()
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns, delimiter=";")
            writer.writeheader()
            writer.writerows(data)
            
    except Exception as e:
        print(f"❌ Error while writing data from list_dic {list_dic} into csv at {csv_path} : {e}")

def transform_dic(dic):    # transform a dictionary dic with keys which are names, into a list of dictionaries with a added "name" key
    try:
        if isInstance(dic, dict):
            return [{"Nom": name, **info} for name, info in dic.items()]
        else:
            return dic

    except Exception as e:
        print(f"❌ Error while transforming the dic {dic} : {e}")

def filter_list_dic(list_dic, list_columns):    # filter a list of dictionaries list_dic to only have certain columns contained in the list of columns list_columns
    try:
        list_columns_clean = [col.lower() for col in list_columns]
        return [{col: row[col] for col in row if any(column in col.lower() for column in list_columns_clean)} for row in list_dic]

    except Exception as e:
        print(f"❌ Error while filtering the list of dic {list_dic} with columns {list_columns} : {e}")

def create_template(csv_path, output_path, list_columns):
    try: 
        reader = read_csv(csv_path)
        filter_dic = filter_list_dic(reader,list_columns)
        write_data(output_path, filter_dic)
    
    except Exception as e:
        print(f"❌ Error while creating a template from input csv at {input_path} in output csv at {output_path} while looking only at columns {list_columns} : {e}")