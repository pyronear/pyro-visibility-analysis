import os
import numpy as np
import rasterio
from rasterio.merge import merge

## Fusion OR
def fusion_or(input_paths, output_path):
    datasets = [rasterio.open(path) for path in input_paths]
    
    # Use metadata from the first raster
    reference = datasets[0]
    meta = reference.meta.copy()
    arrays = [ds.read(1) for ds in datasets]

    # Ensure binary masks (0 and 1)
    arrays_bin = [(arr > 0).astype(np.uint8) for arr in arrays]
    fused = np.any(arrays_bin, axis=0).astype(np.uint8)

    # Fix nodata for uint8
    meta.update(dtype=rasterio.uint8, count=1, nodata=0)

    with rasterio.open(output_path, 'w', **meta) as dst:
        dst.write(fused, 1)

    for ds in datasets:
        ds.close()

## Fusion AND
def fusion_and(input_paths, output_path):
    datasets = [rasterio.open(path) for path in input_paths]
    reference = datasets[0]
    meta = reference.meta.copy()
    arrays = [ds.read(1) for ds in datasets]

    arrays_bin = [(arr > 0).astype(np.uint8) for arr in arrays]
    fused = np.all(arrays_bin, axis=0).astype(np.uint8)

    # Fix nodata for uint8
    meta.update(dtype=rasterio.uint8, count=1, nodata=0)


    with rasterio.open(output_path, 'w', **meta) as dst:
        dst.write(fused, 1)

    for ds in datasets:
        ds.close()

## Surface couverte par un fichier .tif
def coverage(file):
    with rasterio.open(file) as src:
        array = src.read(1)
        pixel_size_x, pixel_size_y = src.res
        pixel_area = pixel_size_x * pixel_size_y
        white_pixels = np.sum(array == 1)
        surface = pixel_area * white_pixels
    return surface

## Surface couverte par rapport à la zone totale
def coverage_out_of_total_coverage(file, total_file):
    total_coverage = coverage(total_file)
    cov = coverage(file)
    return cov / total_coverage if total_coverage else 0

## Surface couverte déjà couverte par le reste
def reccurent_coverage(file, total_file):
    recc_coverage = coverage(total_file)
    cov = coverage(file)
    if cov == 0:
        raise Exception("La couverture de la couche est nulle (division par zéro)")
    return recc_coverage / cov

## Calcul de la surface totale et des recouvrements croisés
def covered_surface(norm_viewsheds_path, fusion_path, csv_path):
    norm_tif_files = [os.path.join(norm_viewsheds_path, f).replace("\\", "/") for f in os.listdir(norm_viewsheds_path) if f.endswith(".tif")]
    fusion_file = os.path.join(fusion_path, f"fusion_or_all_{os.path.splitext(os.path.basename(csv_path))[0]}.tif")
    fusion_or(norm_tif_files, fusion_file)
    
    output = {}

    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        output.setdefault(name, {})
        output[name].setdefault("Surface", None)
        output[name].setdefault("% du total", None)
        for path2 in norm_tif_files:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            output[name].setdefault(name2, None)

    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        output[name]["Surface"] = coverage(path)
        output[name]["% du total"] = coverage_out_of_total_coverage(path, fusion_file)

        other_paths = [x for x in norm_tif_files if x != path]
        output[name].setdefault(name, 1)
        for path2 in other_paths:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            if output[name][name2] is None:
                fusion_22_path = os.path.join(fusion_path, f"fusion_and_{name}_{name2}.tif")
                fusion_and([path, path2], fusion_22_path)
                cov = coverage(fusion_22_path)
                output[name][name2] = cov
                output[name2][name] = cov
        print(f"{name} ajouté au dictionnaire")

    return output
