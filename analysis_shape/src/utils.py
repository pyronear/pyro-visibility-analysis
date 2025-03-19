import csv
import os
from qgis.core import QgsProject, QgsRasterLayer, QgsCoordinateReferenceSystem
from qgis import processing
import subprocess

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
        
def create_csv(path, filename):
    """Lit un fichier CSV, extrait certaines colonnes et les écrit dans un nouveau fichier CSV avec des valeurs pour chaque ligne."""
    try:
        # Lire le fichier CSV source en utilisant ; comme délimiteur
        with open(path, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file, delimiter=";")  # Spécifier le délimiteur ici
            # Colonnes recherchées
            colonnes_voulues = ["Nom", "Latitude", "Longitude", "Hauteur (m)"]  # Mettre le nom exact de la colonne

            # Créer un fichier CSV de destination avec ; comme délimiteur
            with open(filename, mode="w", newline="", encoding="utf-8") as new_file:
                writer = csv.writer(new_file, delimiter=";")  # Utiliser un point-virgule aussi pour le fichier destination
                # Écrire l'en-tête
                writer.writerow(colonnes_voulues)
                # Pour chaque ligne, filtrer et écrire les données des colonnes voulues
                for row in list(reader):
                    # Extraire uniquement les colonnes présentes dans le fichier source
                    ligne = [row[col] for col in row if col in colonnes_voulues]
                    writer.writerow(ligne)

        print(f"✅ Fichier créé avec les colonnes filtrées et les valeurs : {filename}")
    except Exception as e:
        print(f"❌ Erreur lors de la lecture ou de l'écriture du fichier : {e}")

import csv

def wright_csv(filename, colonne_name, values):
    """Ajoute des colonnes spécifiées dans le fichier CSV, sans perdre les lignes existantes."""
    try:
        # Lire le fichier CSV source pour récupérer les données existantes
        with open(filename, mode="r", newline="", encoding="utf-8") as file:
            reader = csv.reader(file, delimiter=";")
            rows = list(reader)  # Lire toutes les lignes du fichier
            header = rows[0]  # L'en-tête (première ligne)

            # Ajouter les nouvelles colonnes spécifiées à l'en-tête
            header.extend(colonne_name)

            # Ajouter les nouvelles colonnes à chaque ligne existante
            for row in rows[1:]:  # Ignorer la première ligne (en-tête)
                nom = row[0]  # On suppose que le 'Nom' est dans la première colonne
                # Vérifier si le 'nom' est présent dans le dictionnaire de valeurs
                if nom in values:
                    row.extend(values[nom])  # Ajouter la valeur correspondante pour ce nom
                else:
                    # Ajouter une valeur vide si le nom n'est pas trouvé dans le dictionnaire
                    row.extend([''] * len(colonne_name))

        # Ouvrir le fichier en mode écriture pour ajouter les colonnes
        with open(filename, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file, delimiter=";")
            writer.writerow(header)  # Réécrire l'en-tête avec les nouvelles colonnes
            writer.writerows(rows[1:])  # Réécrire les lignes de données existantes avec les nouvelles colonnes

        print(f"✅ Colonnes {colonne_name} ajoutées au fichier : {filename}")

    except Exception as e:
        print(f"❌ Erreur lors de l'ajout des colonnes : {e}")


def open_excel_and_process(filename):
    """Ouvre le fichier CSV directement avec excel.exe et attend sa fermeture."""
    filepath = os.path.abspath(filename)
    try:
        print(f"📂 Tentative d'ouverture avec Excel : {filepath}")

        # Vérifier si Excel est bien installé
        excel_path = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"  # Modifier si nécessaire
        if not os.path.exists(excel_path):
            excel_path = r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"  # Version 32 bits
        if not os.path.exists(excel_path):
            print("⚠️ Excel introuvable, vérifiez son installation.")
            return

        # Lancer Excel en lui passant le fichier CSV
        process = subprocess.Popen([excel_path, filepath])
        process.wait()  # Attend la fermeture de l'application

        print(f"✅ Le fichier {filename} a été fermé.")
        check()
    except Exception as e:
        print(f"❌ Erreur lors de l'ouverture du fichier : {e}")

def check():
    """Fonction exécutée après la fermeture d'Excel."""
    print("🔍 Vérification : Tout est OK !")

def open_excel(filename):
    """Ouvre le fichier CSV directement avec Excel sans attendre sa fermeture."""
    filepath = os.path.abspath(filename)
    try:
        print(f"📂 Tentative d'ouverture avec Excel : {filepath}")

        # Vérifier si Excel est bien installé
        excel_path = r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE"  # Modifier si nécessaire
        if not os.path.exists(excel_path):
            excel_path = r"C:\Program Files (x86)\Microsoft Office\root\Office16\EXCEL.EXE"  # Version 32 bits
        if not os.path.exists(excel_path):
            print("⚠️ Excel introuvable, vérifiez son installation.")
            return

        # Lancer Excel en lui passant le fichier CSV sans attendre la fermeture
        subprocess.Popen([excel_path, filepath])

        print(f"✅ Le fichier {filename} a été ouvert dans Excel.")
    except Exception as e:
        print(f"❌ Erreur lors de l'ouverture du fichier : {e}")
