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
    print(f"{file_name} normalisé et enregistré sous {os.path.join(output_path, f'norm_{file_name}.tif')}")

def normalize_create(viewsheds_path, output_path): # Normlise tout les GeoTIFFs dans le dossier viewsheds_path et les enregistre dans le dossier output_path
    for file_name in os.listdir(viewsheds_path):
      if file_name.endswith(".tif"):
          file_path = os.path.join(viewsheds_path, f"{file_name}").replace("\\", "/")
          name =file_path.split("/")[-1].split(".")[0]
          output = os.path.join(output_path, f"norm_{name}.tif")
          if os.path.exists(output):
            print(f"{file_name} déjà normalisé. Voir {os.path.join(output_path, f'norm_{file_name}')}")
            continue
          normalize(file_path, output_path)

def fusion_or(norm_files, output): # Fusionne les GeoTIFF normalisés en une seule couche 
    
    ## Si le fichier de sortie existe déjà, on ne fait rien
    if os.path.exists(output):
        print(f"Fusion OR des rasters déjà existante. Voir {output}.")  
        return
    
    # On genère l'expression pour la fusion OR : "ville@1" OR "village@1" OR ...
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
    
    ## Si le fichier de sortie existe déjà, on ne fait rien
    if os.path.exists(output):
        print(f"Fusion AND des rasters déjà existante. Voir {output}.")  
        return
   
    # On genère l'expression pour la fusion AND : "ville@1" AND "village@1" AND ...
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
        data = transform_dic(csv_path, list_dic)

        columns = data[0].keys()
        with open(csv_path, mode="w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns, delimiter=";")
            writer.writeheader()
            writer.writerows(data)
            
    except Exception as e:
        print(f"❌ Error while writing data from list_dic into csv at {csv_path} : {e}")

def fusion_dic(list_dic1, list_dic2, key):
    try:
        merged_dict = {}

        for entry in list_dic1:
            merged_dict[entry[key]] = entry

        for entry in list_dic2:
            if entry[key] in merged_dict:
                merged_dict[entry[key]].update(entry)
            else:
                merged_dict[entry[key]] = entry
        return list(merged_dict.values())
    
    except Exception as e:
        print(f"❌ Error while adding columns : {e}")

def transform_dic(csv_path, dic):    # transform a dictionary dic with keys which are names, into a list of dictionaries with a added "name" key
    try:
        origin = read_csv(csv_path)
        if isinstance(dic, dict):
            return fusion_dic(origin, [{"Nom": name, **info} for name, info in dic.items()], "Nom")
        else:
            return fusion_dic(origin, dic, "Nom")

    except Exception as e:
        print(f"❌ Error while transforming the dic : {e}")

def filter_list_dic(list_dic, list_columns):    # filter a list of dictionaries list_dic to only have certain columns contained in the list of columns list_columns
    try:
        list_columns_clean = [col.lower() for col in list_columns]
        return [{col: row[col] for col in row if any(col.lower().startswith(column) for column in list_columns_clean)} for row in list_dic]

    except Exception as e:
        print(f"❌ Error while filtering the list of dic with columns {list_columns} : {e}")

def create_template(csv_path, output_path, list_columns):
    try: 
        with open(output_path, mode="w", newline="", encoding="utf-8") as file:
            reader = read_csv(csv_path)
            filter_dic = filter_list_dic(reader, list_columns)
            write_data(output_path, filter_dic)
    
    except Exception as e:
        print(f"❌ Error while creating a template from input csv at {input_path} in output csv at {output_path} while looking only at columns {list_columns} : {e}")