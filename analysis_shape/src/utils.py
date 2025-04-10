import csv
import os

from qgis.core import QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem
from qgis import processing

# Displays a raster layer in QGIS from a .tif file
def display_tif(file):
    layer_name = os.path.splitext(os.path.basename(file))[0]
    raster_layer = QgsRasterLayer(file, layer_name)
    root = QgsProject.instance().layerTreeRoot()
    
    # Check if the raster is valid and add it to QGIS
    if raster_layer.isValid():
        # Find the existing layer 'dem_file_projected' in the QGIS project
        dem_layer = QgsProject.instance().mapLayersByName("dem_file_projected")
        
        if dem_layer:
            # Get the CRS from the 'dem_file_projected' layer
            crs = dem_layer[0].crs()
            print(f"The CRS of the layer 'dem_file_projected' is {crs.authid()}.")

            # Apply the same CRS to the new raster layer
            raster_layer.setCrs(crs)
        
        QgsProject.instance().addMapLayer(raster_layer, False)
        group = root.insertGroup(0, "Viewsheds_merged")
        group.addLayer(raster_layer)
        print(f"Raster {layer_name} successfully added to QGIS.")
        
    else:
        print("Error: Could not add raster to QGIS.")

# Replace NaN values in GeoTIFFs with 0
def normalize(file_path, output_path): 
    file_name =file_path.split("/")[-1].split(".")[0]
    processing.run("gdal:rastercalculator", {'INPUT_A':file_path,'BAND_A':1,'INPUT_B':None,'BAND_B':None,
                                            'INPUT_C':None,'BAND_C':None,'INPUT_D':None,'BAND_D':None,
                                            'INPUT_E':None,'BAND_E':None,'INPUT_F':None,'BAND_F':None,
                                            'FORMULA':'nan_to_num(A)','NO_DATA':None,'EXTENT_OPT':0,
                                            'PROJWIN':None,'RTYPE':5,'OPTIONS':'','EXTRA':'',
                                            'OUTPUT':os.path.join(output_path, f"norm_{file_name}.tif")})
    print(f"{file_name} normalized and saved to {os.path.join(output_path, f'norm_{file_name}.tif')}")

# Normalize all GeoTIFFs in input_dir and save them to output_dir
def normalize_create(viewsheds_path, output_path):
    for file_name in os.listdir(viewsheds_path):
      if file_name.endswith(".tif"):
          file_path = os.path.join(viewsheds_path, f"{file_name}").replace("\\", "/")
          name =file_path.split("/")[-1].split(".")[0]
          output = os.path.join(output_path, f"norm_{name}.tif")
          if os.path.exists(output):
            print(f"{file_name} already normalized. See {output}")
            continue
          normalize(file_path, output_path)

# Merge normalized GeoTIFFs using logical OR operation
def fusion_or(norm_files, output):
    
    if os.path.exists(output):
        print(f"OR fusion already exists. See {output}.")  
        return
    
    # Generate expression like "city@1 OR village@1 OR ..."
    expression = " OR ".join([f'"{os.path.splitext(os.path.basename(filename))[0]}@1"' for filename in norm_files])
    expression = f"'{expression}'"  # Wrap expression in quotes

    processing.run("native:rastercalc", {
        'LAYERS': norm_files,
        'EXPRESSION': expression,
        'EXTENT': None,
        'CELL_SIZE': None,
        'CRS': QgsCoordinateReferenceSystem('IGNF:ED50UTM31.IGN69'),
        'OUTPUT': output
    })

    print(f"OR fusion completed. Output saved to {output}.")

# Merge normalized GeoTIFFs using logical AND operation
def fusion_and(norm_files, output):
    
    if os.path.exists(output):
        print(f"AND fusion already exists. See {output}.")  
        return

    # Generate expression like "city@1 AND village@1 AND ..."
    expression = " AND ".join([f'"{os.path.splitext(os.path.basename(filename))[0]}@1"' for filename in norm_files])
    expression = f"'{expression}'"

    processing.run("native:rastercalc", {
        'LAYERS': norm_files,
        'EXPRESSION': expression,
        'EXTENT': None,
        'CELL_SIZE': None,
        'CRS': QgsCoordinateReferenceSystem('IGNF:ED50UTM31.IGN69'),
        'OUTPUT': output
    })

    print(f"AND fusion completed. Output saved to {output}.")
     
# Returns a list of all lines of the csv at csv_path as dictionaries with the same keys (the columns)
def read_csv(csv_path):    
    try:
        with open(csv_path, mode="r", newline="", encoding="utf-8") as csv_file:
            reader = list(csv.DictReader(csv_file, delimiter=';')) # watchout for the delimiter
        return reader

    except Exception as e:
        print(f"❌ Error while reading the csv at {csv_path} : {e}")

# Opens the csv at csv_path and fill it with data of the dictionnary dict
def write_data(csv_path, dict):    
    try:
        data = transform_dic(csv_path, dict)

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

# Transforms a dictionary dic with keys which are names, into a list of dictionaries with a added "name" key
def transform_dic(csv_path, dic):    
    try:
        origin = read_csv(csv_path)
        if isinstance(dic, dict):
            return fusion_dic(origin, [{"Name": name, **info} for name, info in dic.items()], "Name")
        else:
            return fusion_dic(origin, dic, "Name")

    except Exception as e:
        print(f"❌ Error while transforming the dic : {e}")

# Filters a list of dictionaries list_dic to only have certain columns contained in the list of columns list_columns
def filter_list_dic(list_dic, list_columns):    
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
        print(f"❌ Error while creating a template from input csv at {csv_path} in output csv at {output_path} while looking only at columns {list_columns} : {e}")