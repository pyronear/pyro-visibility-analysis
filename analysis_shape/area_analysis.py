import os

import numpy as np
import rasterio
from rasterio.windows import Window

# Viewsheds are binary masks, so everything here is read and written one
# horizontal strip at a time. At 23.8 m (SRTM) reading whole rasters was
# harmless; at 5 m (Lidar HD) a single viewshed is ~400 MB as float32 and
# stacking all of them at once exhausts memory.
CHUNK_ROWS = 512

# Creation options for the binary outputs. DEFLATE on a 0/1 mask typically
# gives a file one to two orders of magnitude smaller than the uncompressed
# float32 the viewshed plugin produces, without losing anything.
# `nodata` is deliberately left unset. A viewshed mask has no missing data: 0
# means "not visible", which is a real answer. Declaring 0 as nodata made
# gdal:rastercalculator treat every non-visible pixel as missing and rewrite it
# as 255, which then read back as visible. Transparency is handled by
# viewshed_style.qml, whose palette only defines the value 1.
BINARY_PROFILE = {
    "driver": "GTiff",
    "dtype": rasterio.uint8,
    "count": 1,
    "nodata": None,
    "compress": "DEFLATE",
    "zlevel": 9,
    "tiled": True,
    "blockxsize": 512,
    "blockysize": 512,
}


def _visible(dataset, window):
    """Boolean visibility mask, with any declared nodata treated as not visible."""
    band = dataset.read(1, window=window)
    if dataset.nodata is not None:
        band = np.where(band == dataset.nodata, 0, band)
    return band > 0


def _row_windows(dataset):
    """Yield full-width horizontal strips covering the raster."""
    for row_off in range(0, dataset.height, CHUNK_ROWS):
        height = min(CHUNK_ROWS, dataset.height - row_off)
        yield Window(0, row_off, dataset.width, height)


def _check_same_grid(datasets):
    reference = datasets[0]
    for dataset in datasets[1:]:
        if (dataset.width, dataset.height) != (reference.width, reference.height):
            raise ValueError(
                f"{os.path.basename(dataset.name)} has shape "
                f"{dataset.width}x{dataset.height}, expected "
                f"{reference.width}x{reference.height}. All viewsheds must come "
                f"from the same DEM."
            )
    return reference


def _fusion(input_paths, output_path, combine):
    """Combine binary rasters strip by strip with `combine` (np.logical_or/and)."""
    if not input_paths:
        raise ValueError("No input raster provided for fusion.")

    datasets = [rasterio.open(path) for path in input_paths]
    try:
        reference = _check_same_grid(datasets)
        meta = reference.meta.copy()
        meta.update(BINARY_PROFILE)

        with rasterio.open(output_path, "w", **meta) as dst:
            for window in _row_windows(reference):
                fused = None
                for dataset in datasets:
                    band = _visible(dataset, window)
                    fused = band if fused is None else combine(fused, band)
                dst.write(fused.astype(np.uint8), 1, window=window)
    finally:
        for dataset in datasets:
            dataset.close()


def fusion_or(input_paths, output_path):
    """Union of the input viewsheds."""
    _fusion(input_paths, output_path, np.logical_or)


def fusion_and(input_paths, output_path):
    """Intersection of the input viewsheds."""
    _fusion(input_paths, output_path, np.logical_and)


def compact_binary_raster(path):
    """Rewrite a binary raster as compressed uint8, in place.

    The visibility plugin writes Float32 with no compression: 4 bytes per pixel
    for data that only ever holds 0 or 1. At 5 m that is ~400 MB per site.
    """
    with rasterio.open(path) as src:
        if (src.dtypes[0] == "uint8" and src.compression is not None
                and src.nodata is None):
            return path
        meta = src.meta.copy()
        meta.update(BINARY_PROFILE)
        temp_path = f"{path}.compact.tif"
        with rasterio.open(temp_path, "w", **meta) as dst:
            for window in _row_windows(src):
                band = np.nan_to_num(src.read(1, window=window)) > 0
                dst.write(band.astype(np.uint8), 1, window=window)

    os.replace(temp_path, path)
    return path


def coverage(file):
    """Surface (in CRS units squared) covered by a viewshed."""
    with rasterio.open(file) as src:
        pixel_size_x, pixel_size_y = src.res
        visible = 0
        for window in _row_windows(src):
            visible += int((src.read(1, window=window) == 1).sum())
    return pixel_size_x * pixel_size_y * visible


def intersection_coverage(file_a, file_b):
    """Surface visible from both viewsheds, without writing an intermediate raster.

    `covered_surface` used to materialise one `fusion_and_<a>_<b>.tif` per pair
    only to count its pixels — N*(N-1)/2 files for nothing.
    """
    with rasterio.open(file_a) as src_a, rasterio.open(file_b) as src_b:
        _check_same_grid([src_a, src_b])
        pixel_size_x, pixel_size_y = src_a.res
        shared = 0
        for window in _row_windows(src_a):
            shared += int(np.logical_and(_visible(src_a, window),
                                         _visible(src_b, window)).sum())
    return pixel_size_x * pixel_size_y * shared


def coverage_out_of_total_coverage(file, total_file):
    total_coverage = coverage(total_file)
    cov = coverage(file)
    return cov / total_coverage if total_coverage else 0


def reccurent_coverage(file, total_file):
    recc_coverage = coverage(total_file)
    cov = coverage(file)
    if cov == 0:
        raise Exception(
            "The layer's coverage is zero (division by zero)")
    return recc_coverage / cov


def covered_surface(norm_viewsheds_path, fusion_path, csv_path):
    norm_tif_files = [os.path.join(norm_viewsheds_path, f).replace("\\", "/")
                      for f in os.listdir(norm_viewsheds_path) if f.endswith(".tif")]
    fusion_file = os.path.join(
        fusion_path,
        f"fusion_or_all_{os.path.splitext(os.path.basename(csv_path))[0]}.tif")
    fusion_or(norm_tif_files, fusion_file)

    output = {}

    for path in norm_tif_files:
        name = os.path.basename(path).replace(
            "norm_viewshed_", "").rsplit(".", 1)[0]
        output.setdefault(name, {})
        output[name].setdefault("Surface", None)
        output[name].setdefault("% du total", None)
        for path2 in norm_tif_files:
            name2 = os.path.basename(path2).replace(
                "norm_viewshed_", "").rsplit(".", 1)[0]
            output[name].setdefault(name2, None)

    for path in norm_tif_files:
        name = os.path.basename(path).replace(
            "norm_viewshed_", "").rsplit(".", 1)[0]
        output[name]["Surface"] = coverage(path)
        output[name]["% du total"] = coverage_out_of_total_coverage(
            path, fusion_file)

        other_paths = [x for x in norm_tif_files if x != path]
        output[name].setdefault(name, 1)
        for path2 in other_paths:
            name2 = os.path.basename(path2).replace(
                "norm_viewshed_", "").rsplit(".", 1)[0]
            if output[name][name2] is None:
                cov = intersection_coverage(path, path2)
                output[name][name2] = cov
                output[name2][name] = cov
        print(f"{name} added to the dictionary")

    return output
