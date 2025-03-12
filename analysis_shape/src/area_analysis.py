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



    