import os
import numpy as np
from PIL import Image
from PIL.TiffTags import TAGS
import pandas as pd

from analysis_shape.utils import fusion_or, fusion_and

## Returns the .tif covered area in m²
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
        print("Error : not a .tif file")

## Returns the .tif covered area % of the total area
def coverage_out_of_total_coverage(file, total_file):
    total_coverage = coverage(total_file)
    cov = coverage(file)
    return cov/total_coverage

## Returns the .tif covered area % of already covered by the rest of the viewsheds
def reccurent_coverage(file, total_file):
    recc_coverage = coverage(total_file)
    cov = coverage(file)
    if cov == 0:
        Exception("the covered area is null (cannot divide by 0)")
    return recc_coverage/cov

## Returns the overlaping area of two viewsheds in m²
def overlap_22(file1, file2, fusion_path):
    name1 = os.path.basename(file1).replace("norm_viewshed_", "").rsplit(".", 1)[0]
    name2 = os.path.basename(file1).replace("norm_viewshed_", "").rsplit(".", 1)[0]
    fusion_22_path = os.path.join(fusion_path, f"fusion_or_{name1}_{name2}.tif")
    fusion_and([file1, file2],fusion_22_path)
    return coverage(fusion_22_path)

## Uses the precedent fuctions to create a dictionary with the following structure:
## { "name1": { "Surface": x, "% du total": y, "name1": overlap1, "name2": overlap2, ...}, "name2": {... .
def covered_surface(norm_viewsheds_path, fusion_path, CSV_path):

    norm_tif_files = [os.path.join(norm_viewsheds_path, f).replace("\\", "/") for f in os.listdir(norm_viewsheds_path) if f.endswith(".tif")]

    # Reads CSV to create a list of viewpoints to analyse
    print(CSV_path)
    df = pd.read_csv(CSV_path, delimiter=';')
    df.columns = df.columns.str.strip()
    col_Name = [col for col in df.columns if col.lower() == "Name"]
    if not col_Name:
        raise ValueError("Column 'Name' not found in the CSV file, or delimiter is incorrect.")
    expected_names = set(df[col_Name[0]].astype(str))  # Column "Name" or "Name" expected in the CSV

    # Filters .tif files keeping only those that are in the CSV
    filtered_tif_files = []
    
    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        if name in expected_names:
            filtered_tif_files.append(path)

    norm_tif_files = filtered_tif_files 

    CSV_name = os.path.splitext(os.path.basename(CSV_path))[0]
    fusion_or(norm_tif_files, os.path.join(fusion_path, f"fusion_or_all_{CSV_name}.tif"))
    
    output = {} 

    # Output dictionary initialization
    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        output.setdefault(name, {})
        output[name].setdefault("Surface", None)
        output[name].setdefault("% du total", None)
        for path2 in norm_tif_files:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            output[name].setdefault(name2, None)

    # Analysis viewshed by viewshed
    for path in norm_tif_files:
        name = os.path.basename(path).replace("norm_viewshed_", "").rsplit(".", 1)[0]
        
        output[name]["Surface"] = coverage(path)
        output[name]["% du total"] = coverage_out_of_total_coverage(path, os.path.join(fusion_path, "fusion_or_all.tif"))

        other_paths = [x for x in norm_tif_files if x != path]

        #Overlapping 2 by 2
        output[name].setdefault(name, 1)
        for path2 in other_paths:
            name2 = os.path.basename(path2).replace("norm_viewshed_", "").rsplit(".", 1)[0]
            if output[name][name2] == None:
                cov22 = overlap_22(path, path2, fusion_path)
                output[name][name2] = cov22
                output[name2][name] = cov22

        print(f"{name} added to the output dictionary")

    return output
    