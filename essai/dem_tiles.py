# import elevation
import csv
import os 
import math
from srtm_downloader import SrtmDownloader

## pip install make 
## pip install elevation

# PATH
PATH = os.path.dirname(__file__)
csv_file = os.path.join(PATH, "pts_hauts.csv")

# Initialiser les variables
min_lat = float('inf')
max_lat = float('-inf')
min_lon = float('inf')
max_lon = float('-inf')

# Ouvrir et lire le fichier CSV
with open(csv_file, newline='', encoding='utf-8') as file:
    dialect = csv.Sniffer().sniff(file.read(1024))  # Détection automatique du délimiteur
    file.seek(0)  # Revenir au début du fichier
    reader = csv.reader(file, delimiter=dialect.delimiter)
    
    header = next(reader)  # Lire la première ligne (en-tête)
    header_lower = [col.lower().strip() for col in header]  # Normaliser les noms de colonnes

    # Trouver les index des colonnes (insensible à la casse)
    lat_index = header_lower.index("latitude")
    lon_index = header_lower.index("longitude")
    
    # Initialiser les min/max
    min_lat, max_lat = float("inf"), float("-inf")
    min_lon, max_lon = float("inf"), float("-inf")

    # Lire les valeurs des points
    for row in reader:
        try:
            lat, lon = float(row[lat_index]), float(row[lon_index])
            min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
            min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)
        except ValueError:
            pass  # Ignorer les lignes non valides

min_lat, max_lat = math.floor(min_lat), math.ceil(max_lat)
min_lon, max_lon = math.floor(min_lon), math.ceil(max_lon)
# Affichage des résultats
print(f"Zone englobante :\nMin Latitude: {min_lat}, Max Latitude: {max_lat}")
print(f"Min Longitude: {min_lon}, Max Longitude: {max_lon}")

# Set the bounds (min_lon, min_lat, max_lon, max_lat) for the DEM
bounds = (min_lat, min_lon, max_lat, max_lon)

## Set ouput file
output_file = os.path.join(PATH, f"elevation_{min_lat}_{min_lon}_{max_lat}_{max_lon}.tif")

# Configure the output file
elevation.clip(bounds=bounds, output=output_file)

# Clean up temporary files
elevation.cleanup()