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
# gives a file one to two orders of magnitude smaller than an uncompressed
# float32 one (what the QGIS plugin used to write), without losing anything.
# `nodata` is deliberately left unset. A viewshed mask has no missing data: 0
# means "not visible", which is a real answer. Declaring 0 as nodata once made
# a raster calculator treat every non-visible pixel as missing and rewrite it
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


def coverage(file):
    """Surface (in CRS units squared) covered by a viewshed."""
    with rasterio.open(file) as src:
        pixel_size_x, pixel_size_y = src.res
        visible = 0
        for window in _row_windows(src):
            visible += int((src.read(1, window=window) == 1).sum())
    return pixel_size_x * pixel_size_y * visible


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


def covered_surface(viewsheds_path, fusion_path, csv_path):
    """Per-site surface and share of the union, plus the union raster itself.

    This used to add an N×N matrix of pairwise overlaps. Nothing downstream
    read it (summary.py only takes `Site` and `Surface`), and it dominated the
    end of the run: 137 sites meant 9 316 pairs, each re-reading two full
    rasters. Overlap questions are answered by the union and by the scenario
    count rasters instead.
    """
    tif_files = sorted(os.path.join(viewsheds_path, f)
                       for f in os.listdir(viewsheds_path) if f.endswith(".tif"))
    fusion_file = os.path.join(
        fusion_path,
        f"fusion_or_all_{os.path.splitext(os.path.basename(csv_path))[0]}.tif")
    fusion_or(tif_files, fusion_file)
    total = coverage(fusion_file)

    output = {}
    for index, path in enumerate(tif_files, 1):
        name = os.path.splitext(os.path.basename(path))[0]
        name = name[len("viewshed_"):] if name.startswith("viewshed_") else name
        surface = coverage(path)
        output[name] = {"Surface": surface,
                        "% du total": surface / total if total else 0}
        print(f"[{index}/{len(tif_files)}] {name} — {surface / 1e6:.1f} km²")

    return output
