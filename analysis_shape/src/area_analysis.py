import numpy as np
from PIL import Image
from PIL.TiffTags import TAGS

from src.utils import fusion

## Calcul de la surface couverte par un fichier .tif
def area_tif(tif_path, tif_name):
    if tif_name.endswith(".tif"):
        image = Image.open(tif_path)
        meta_data = {TAGS[key]: image.tag[key] for key in image.tag_v2}
        raster_array = np.array(image)
        white_pixels = np.sum(raster_array == 1)
        pixel_size = meta_data['ModelPixelScaleTag']
        surface = pixel_size[0] * pixel_size[1] * white_pixels
        return surface
    else:
        print("Erreur : Le fichier n'est pas un .tif")

## Calcul de la surface couverte par rapport à une zone totale
def coverage_out_of_total_coverage(tif_path, tif_name, fusion_path, fusion_name):
    total_coverage = area_tif(fusion_path, fusion_name)
    coverage = area_tif(tif_path, tif_name)
    return coverage/total_coverage



    