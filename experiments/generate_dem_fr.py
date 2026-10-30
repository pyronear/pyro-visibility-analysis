"""Generate a DEM for a French region from the IGN Lidar HD products.

Drop-in alternative to ``generate_dem.py`` (which uses SRTM1, ~30 m radar data
from 2000 that captures only part of the canopy height). Here we pull the
Lidar HD MNS/MNT/MNH from the IGN WMS, which serves the data *already* in
Lambert-93 (EPSG:2154) and resamples server-side to whatever resolution we ask
for. That means no 50 cm tile downloads (~99 GB for a typical footprint) and no
mosaicking: we request the area in chunks and write them straight into the
output raster.

Products (see --product):
    MNS  Modèle Numérique de Surface  — canopy and buildings included (DSM)
    MNT  Modèle Numérique de Terrain  — bare earth (DTM)
    MNH  Modèle Numérique de Hauteur  — height above ground, = MNS - MNT

For visibility analysis of smoke plumes, MNS is the relevant one: a camera on a
30 m mast in flat forest is barely above the canopy, and the canopy is exactly
what SRTM gets wrong.

Coverage is national but progressive (see macarte.ign.fr/carte/mThSup/
diffusionMNxLiDARHD). Areas outside coverage come back as nodata; the script
reports the percentage so you know what you got.

Usage:
    uv run python experiments/generate_dem_fr.py
    uv run python experiments/generate_dem_fr.py --product MNT --resolution 2.5
"""

import argparse
import importlib.util
import os
import sys
import time
import urllib.parse
import urllib.request


def _use_bundled_proj():
    """Point PROJ/GDAL at the data rasterio ships with.

    A conda/miniforge install exports PROJ_DATA and GDAL_DATA globally, and its
    proj.db can be older than the one rasterio expects — EPSG lookups then fail
    with "DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is expected".
    This must run before rasterio is imported, so the package is located without
    importing it.
    """
    spec = importlib.util.find_spec("rasterio")
    if spec is None or not spec.submodule_search_locations:
        return
    package_dir = spec.submodule_search_locations[0]
    for var, subdir in (("PROJ_DATA", "proj_data"), ("GDAL_DATA", "gdal_data")):
        bundled = os.path.join(package_dir, subdir)
        if os.path.isdir(bundled) and os.environ.get(var) != bundled:
            os.environ[var] = bundled
    os.environ.pop("PROJ_LIB", None)


_use_bundled_proj()

import numpy as np  # noqa: E402  (must follow _use_bundled_proj)
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.windows import Window  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis_shape.config_loader import load_config  # noqa: E402  (needs the path fix above)

_config = load_config()
REGION = _config.REGION

# === CONFIG ===
WMS_URL = "https://data.geopf.fr/wms-r"
LAYERS = {
    "MNS": "IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    "MNT": "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    "MNH": "IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    # Lidar HD is a rolling programme: whole regions still have none (no
    # data in any of 8 directions within 5 km of a test site). The
    # photogrammetric correlation MNS is national and carries the canopy —
    # measured elsewhere against the lidar MNS: median +0.4 m, sd 2.6 m.
    # It is the primary source where lidar is missing, rather than
    # downloading an extent of nodata to refill it later with
    # fill_dem_gaps.py.
    "MNS_CORREL": "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES.MNS",
}
TARGET_CRS = "EPSG:2154"
NODATA = -9999.0

# The viewshed radius compute_viewsheds.py will use. Anything beyond it can never be
# visible, so the DEM buffer is derived from it. It used to be hardcoded at
# 15 km here while config.py moved to 20 km: the default DEM then clipped the
# horizon of every viewshed, silently.
VIEWSHED_RADIUS_M = getattr(_config, "VIEWSHED_RADIUS_M", 15000)
BUFFER_MARGIN_M = 1000  # small margin so the horizon isn't clipped exactly

CHUNK_PX = 2000  # request size; 2000x2000 float32 ≈ 16 MB per request
MAX_RETRIES = 4


def sites_bbox_l93(csv_path, buffer_m):
    """Bounding box of the sites in Lambert-93, expanded by buffer_m.

    Note: unlike generate_dem.py, the buffer is applied directly in a metric
    CRS. Buffering in EPSG:3857 (as generate_dem.py does) inflates distances by
    1/cos(latitude) — at latitude 46.7 a "30 km" buffer is really ~20.5 km.
    """
    df = pd.read_csv(csv_path, delimiter=";")
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    xs, ys = transformer.transform(df["Longitude"].values, df["Latitude"].values)
    return (
        min(xs) - buffer_m,
        min(ys) - buffer_m,
        max(xs) + buffer_m,
        max(ys) + buffer_m,
    )


def fetch_chunk(layer, minx, miny, maxx, maxy, width, height):
    """One WMS GetMap request, returned as a float32 array."""
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "EXCEPTIONS": "text/xml",
        "LAYERS": layer,
        "STYLES": "",
        "FORMAT": "image/geotiff",
        "CRS": TARGET_CRS,
        "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": str(width),
        "HEIGHT": str(height),
    }
    url = f"{WMS_URL}?{urllib.parse.urlencode(params)}"

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=180) as response:
                payload = response.read()
            if payload[:4] not in (b"II*\x00", b"MM\x00*"):
                # The server answers errors as XML with a 200 status.
                raise RuntimeError(f"not a GeoTIFF: {payload[:300]!r}")
            with rasterio.io.MemoryFile(payload) as memfile:
                with memfile.open() as src:
                    return src.read(1).astype(np.float32)
        except Exception as exc:  # noqa: BLE001 - retry on anything transient
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"   ⚠️  attempt {attempt} failed ({exc}); retrying in {wait}s")
            time.sleep(wait)


def clean_nodata(array):
    """Mask nodata and the interpolation bleed around it.

    The WMS resamples server-side, so pixels next to a nodata area come back as
    a blend of -9999 and real elevations (e.g. -67 m in the middle of a test département).
    Thresholding alone doesn't catch those, so the nodata mask is dilated by two
    pixels.
    """
    invalid = (array < -100) | ~np.isfinite(array)
    if not invalid.any():
        return array

    dilated = invalid.copy()
    for _ in range(2):
        padded = np.pad(dilated, 1, mode="constant", constant_values=False)
        dilated = (
            padded[1:-1, 1:-1]
            | padded[:-2, 1:-1]
            | padded[2:, 1:-1]
            | padded[1:-1, :-2]
            | padded[1:-1, 2:]
        )
    array[dilated] = NODATA
    return array


def build_dem(layer, bbox, resolution, output_path):
    minx, miny, maxx, maxy = bbox
    width = int(np.ceil((maxx - minx) / resolution))
    height = int(np.ceil((maxy - miny) / resolution))
    # Snap the extent to the pixel grid we just computed.
    maxx = minx + width * resolution
    miny = maxy - height * resolution

    print(f"   grid: {width} x {height} px at {resolution} m "
          f"({width * height / 1e6:.1f} Mpx, {width * height * 4 / 1e9:.2f} GB float32)")

    profile = {
        "driver": "GTiff",
        "dtype": "float32",
        "count": 1,
        "width": width,
        "height": height,
        "crs": TARGET_CRS,
        "transform": from_origin(minx, maxy, resolution, resolution),
        "nodata": NODATA,
        "compress": "LZW",
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
    }

    n_cols = int(np.ceil(width / CHUNK_PX))
    n_rows = int(np.ceil(height / CHUNK_PX))
    total = n_cols * n_rows
    nodata_count = 0

    with rasterio.open(output_path, "w", **profile) as dst:
        done = 0
        for row in range(n_rows):
            for col in range(n_cols):
                off_x = col * CHUNK_PX
                off_y = row * CHUNK_PX
                w = min(CHUNK_PX, width - off_x)
                h = min(CHUNK_PX, height - off_y)

                chunk_minx = minx + off_x * resolution
                chunk_maxy = maxy - off_y * resolution
                chunk_maxx = chunk_minx + w * resolution
                chunk_miny = chunk_maxy - h * resolution

                array = fetch_chunk(
                    layer, chunk_minx, chunk_miny, chunk_maxx, chunk_maxy, w, h
                )
                array = clean_nodata(array)
                nodata_count += int((array == NODATA).sum())

                dst.write(array, 1, window=Window(off_x, off_y, w, h))
                done += 1
                print(f"   [{done}/{total}] chunk written ({w}x{h})")

    pct = 100 * nodata_count / (width * height)
    return pct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=REGION,
                        help="region folder under data/ (default: config.REGION)")
    parser.add_argument("--product", default="MNS", choices=sorted(LAYERS),
                        help="MNS (surface, default), MNT (terrain) or MNH (height)")
    parser.add_argument("--resolution", type=float, default=5.0,
                        help="output pixel size in metres (default: 5)")
    parser.add_argument("--buffer-km", type=float, default=None,
                        help="buffer around the sites; defaults to the viewshed "
                             f"radius from config.py ({VIEWSHED_RADIUS_M / 1000:g} km) "
                             "plus a 1 km margin")
    parser.add_argument("--output", default=None,
                        help="output path (default: data/<region>/dem_l93.tif)")
    args = parser.parse_args()

    csv_path = os.path.join("data", args.region, "sites.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"❌ {csv_path} not found")

    output_path = args.output or os.path.join("data", args.region, "dem_l93.tif")
    buffer_m = (args.buffer_km * 1000 if args.buffer_km is not None
                else VIEWSHED_RADIUS_M + BUFFER_MARGIN_M)

    bbox = sites_bbox_l93(csv_path, buffer_m)
    print(f"Region       : {args.region}")
    print(f"Product      : Lidar HD {args.product} ({LAYERS[args.product]})")
    print(f"Buffer       : {buffer_m / 1000:.1f} km")
    print(f"BBox (L93)   : {bbox[0]:.0f}, {bbox[1]:.0f}, {bbox[2]:.0f}, {bbox[3]:.0f}")
    print(f"Extent       : {(bbox[2]-bbox[0])/1000:.1f} x {(bbox[3]-bbox[1])/1000:.1f} km")

    # Downloaded next to the target and swapped in only once complete: the
    # current DEM (hours of download, often patched by fill_dem_gaps.py or
    # flatten_mast.py since) must survive a WMS failure halfway through.
    partial_path = f"{output_path}.part"
    try:
        pct_nodata = build_dem(LAYERS[args.product], bbox, args.resolution,
                               partial_path)
    except BaseException:
        if os.path.exists(partial_path):
            os.remove(partial_path)
        raise

    # Never silently destroy the SRTM DEM: compute_viewsheds.py reads
    # dem_l93.tif, so we take its name, but the previous file is kept alongside
    # as the epic's baseline.
    # An existing backup is never overwritten: on a second run that would
    # replace the original SRTM DEM with a Lidar HD one.
    if os.path.exists(output_path):
        backup = output_path.replace(".tif", "_previous.tif")
        if os.path.exists(backup):
            print(f"ℹ️  {backup} already exists; replacing the previous "
                  f"{os.path.basename(output_path)}")
        else:
            os.rename(output_path, backup)
            print(f"ℹ️  existing DEM moved to {backup}")
    os.replace(partial_path, output_path)

    size_mb = os.path.getsize(output_path) / 1e6
    print(f"\n✅ DEM saved to {output_path} ({size_mb:.0f} MB on disk)")
    print(f"   nodata: {pct_nodata:.2f} % of pixels")
    if pct_nodata > 5:
        print("   ⚠️  Significant nodata — part of the footprint is outside Lidar HD "
              "coverage. Check macarte.ign.fr/carte/mThSup/diffusionMNxLiDARHD ; "
              "the viewshed will treat those cells as holes.")


if __name__ == "__main__":
    main()
