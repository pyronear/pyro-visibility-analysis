import os
import numpy as np
from PIL import Image
from PIL.TiffTags import TAGS

from src.utils import fusion_or, fusion_and

## Calcul de la surface couverte par un fichier .tif
def coverage(file):
    name = file.split("/")[-1]
    if name.endswith(".tif"):
        image = Image.open(file)
        meta_data = {TAGS[key]: image.tag[key] for key in image.tag_v2}
        raster_array = np.array(image)
        white_pixels = np.sum(raster_array == 1)
        pixel_size = meta_data['ModelPixelScaleTag']
        surface = pixel_size[0] * pixel_size[1] * white_pixels
        return surface
    else:
        print("Erreur : Le fichier n'est pas un .tif")

## Calcul de la surface couverte par rapport à une zone totale
def coverage_out_of_total_coverage(file, total_file):
    total_coverage = coverage(total_file)
    cov = coverage(file)
    return cov/total_coverage

## Calcul de la surface couverte déjà couverte par le reste des couches 
def reccurent_coverage(file, total_file):
    recc_coverage = coverage(total_file)
    cov = coverage(file)
    if cov == 0:
        Exception("La couverture de la couche est nulle (division par zéro)")
    return recc_coverage/cov

## Calcul du recouvrement entre deux fichiers .tif
def overlap_22(file1, file2, fusion_path):
    name1 = os.path.splitext(os.path.basename(file1))[0]
    name2 = os.path.splitext(os.path.basename(file2))[0]
    fusion_22_path = os.path.join(fusion_path, f"fusion_or_{name1}_{name2}.tif")
    fusion_and([file1, file2],fusion_22_path)
    return coverage(fusion_22_path)

## Appelle les fonctions précédentes et crée un dictionnaire de sortie
def covered_surface(norm_viewsheds_path, fusion_path, CSV_path):

    norm_tif_files = [os.path.join(norm_viewsheds_path, f).replace("\\", "/") for f in os.listdir(norm_viewsheds_path) if f.endswith(".tif")]

    CSV_name = os.path.splitext(os.path.basename(CSV_path))[0]
    fusion_or(norm_tif_files, os.path.join(fusion_path, f"fusion_or_all_{CSV_name}.tif"))
    output = {} 

    # Initialisation du dictionnaire de sortie
    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        output.setdefault(name, {})
        output[name].setdefault("Surface", None)
        output[name].setdefault("% du total", None)
        for path2 in norm_tif_files:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            output[name].setdefault(name2, None)

    # Analyse viewshed par viewshed
    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        
        output[name]["Surface"] = coverage(path)
        output[name]["% du total"] = coverage_out_of_total_coverage(path, os.path.join(fusion_path, "fusion_or_all.tif"))

        other_paths = [x for x in norm_tif_files if x != path]

        #Recouvrement 2 à 2
        output[name].setdefault(name, 1)
        for path2 in other_paths:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            if output[name][name2] == None:
                cov22 = overlap_22(path, path2, fusion_path)
                output[name][name2] = cov22
                output[name2][name] = cov22

            break
        break
        print(f"{name} ajouté au dictionnaire")

    return output
    