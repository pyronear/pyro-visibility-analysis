import numpy as np
from PIL import Image
from PIL.TiffTags import TAGS


def area_tif(tif_path, tif_name):
    if tif_name.endswith(".tif"):
        image = Image.open(tif_path)
        meta_data = {TAGS[key]: image.tag[key] for key in image.tag_v2}
        raster_array = np.array(image)
        white_pixels = np.sum(raster_array == 1)
        pixel_size = meta_data['ModelPixelScaleTag']
        surface = pixel_size[0] * pixel_size[1] * white_pixels
        print(f"Surface couverte par {tif_name}: {surface} m²\n")
    else:
        print("Erreur : Le fichier n'est pas un .tif")