"""Fill the Lidar HD holes in a MNS with the IGN correlation MNS.

Lidar HD is a rolling programme. On a test département it left 25 % of the
footprint empty — a whole quarter of it, in one block — and the
visibility plugin reads those cells as holes, so every viewshed crossing them is
wrong. Waiting for coverage is not an option, and dropping the area would remove
a quarter of the département from the study.

`ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES.MNS` is the photogrammetric surface
model IGN derives from aerial imagery. It is national, and — unlike SRTM, which
recovers only 40-60 % of canopy height — it carries the canopy. Measured against
the Lidar HD MNS where both exist, over 1.9 M pixels of a test département:

    forest A             median +0.4 m   mean +0.9 m   sd 2.6 m
    forest B             median +0.1 m   mean +0.5 m   sd 2.5 m
    plateau agricole     median -0.0 m   mean +0.4 m   sd 2.3 m

It agrees to well under a metre and, where it differs, sits slightly *higher* —
so the filled cells obstruct marginally more than the lidar would, and coverage
stays a lower bound. The `source` band records which cells were filled, so a
result can always be re-read knowing where the lidar stopped.

Usage:
    uv run python experiments/fill_dem_gaps.py --region example
"""

import argparse
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proj_env import use_bundled_proj  # noqa: E402

use_bundled_proj()

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from config import REGION  # noqa: E402

WMS_URL = "https://data.geopf.fr/wms-r"
FILL_LAYER = "ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES.MNS"
# Provenance code stamped per fill layer; anything else gets 9.
FILL_CODES = {FILL_LAYER: 2, "ELEVATION.ELEVATIONGRIDCOVERAGE": 3}
NODATA_FLOOR = -100.0
CHUNK_PX = 2000


def fetch(layer, minx, miny, maxx, maxy, width, height, retries=3):
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": layer, "STYLES": "", "FORMAT": "image/geotiff",
        "CRS": "EPSG:2154", "BBOX": f"{minx},{miny},{maxx},{maxy}",
        "WIDTH": str(width), "HEIGHT": str(height),
    }
    url = f"{WMS_URL}?{urllib.parse.urlencode(params)}"
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=300) as response:
                payload = response.read()
            if payload[:4] not in (b"II*\x00", b"MM\x00*"):
                return None  # the WMS answers with an error image, not a raster
            with rasterio.io.MemoryFile(payload) as memfile, memfile.open() as src:
                return src.read(1).astype(np.float32)
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                print(f"   ⚠️  giving up on a chunk ({type(exc).__name__})")
                return None
            time.sleep(2 * (attempt + 1))


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--dem", default=None,
                        help="DEM to patch (default: data/<region>/dem_l93.tif)")
    parser.add_argument("--layer", default=FILL_LAYER)
    args = parser.parse_args()

    dem_path = args.dem or os.path.join("data", args.region, "dem_l93.tif")
    if not os.path.exists(dem_path):
        raise SystemExit(f"❌ {dem_path} not found")

    provenance_path = os.path.splitext(dem_path)[0] + "_source.tif"

    with rasterio.open(dem_path) as src:
        profile, transform = src.profile, src.transform
        width, height = src.width, src.height
        res_x, res_y = abs(transform.a), abs(transform.e)
        left, top = transform.c, transform.f

    # 1 = Lidar HD, 2 = correlation MNS, 3 = RGE ALTI, 0 = still missing.
    source_profile = dict(profile, dtype="uint8", nodata=0, compress="DEFLATE",
                          zlevel=9, tiled=True, blockxsize=512, blockysize=512)
    code = FILL_CODES.get(args.layer, 9)

    # A second pass (RGE ALTI after the correlation MNS) used to rewrite the
    # provenance from scratch, relabelling every cell the first pass had
    # filled as lidar. Reopen it instead, and only stamp the cells filled now.
    previous = os.path.exists(provenance_path)

    print(f"▶ {dem_path}  ({width} x {height} px at {res_x:.0f} m)")
    print(f"  bouchage depuis {args.layer} (code {code})"
          f"{' — provenance existante conservée' if previous else ''}\n")

    n_cols = int(np.ceil(width / CHUNK_PX))
    n_rows = int(np.ceil(height / CHUNK_PX))
    total = n_cols * n_rows
    holes = filled = 0
    done = 0

    prov_open = ((provenance_path, "r+") if previous
                 else (provenance_path, "w"))
    prov_kwargs = {} if previous else source_profile
    with rasterio.open(dem_path, "r+") as dst, \
            rasterio.open(*prov_open, **prov_kwargs) as prov:
        for row in range(n_rows):
            for col in range(n_cols):
                off_x, off_y = col * CHUNK_PX, row * CHUNK_PX
                w = min(CHUNK_PX, width - off_x)
                h = min(CHUNK_PX, height - off_y)
                window = Window(off_x, off_y, w, h)

                band = dst.read(1, window=window)
                missing = band <= NODATA_FLOOR
                if previous:
                    source = prov.read(1, window=window)
                else:
                    source = np.where(missing, 0, 1).astype(np.uint8)
                done += 1

                if not missing.any():
                    prov.write(source, 1, window=window)
                    print(f"   [{done}/{total}] complet")
                    continue

                holes += int(missing.sum())
                chunk_minx = left + off_x * res_x
                chunk_maxy = top - off_y * res_y
                patch = fetch(args.layer, chunk_minx, chunk_maxy - h * res_y,
                              chunk_minx + w * res_x, chunk_maxy, w, h)

                if patch is None:
                    prov.write(source, 1, window=window)
                    print(f"   [{done}/{total}] {missing.sum():>7} trous — "
                          f"échec du remplissage")
                    continue

                usable = missing & (patch > NODATA_FLOOR)
                band[usable] = patch[usable]
                source[usable] = code
                filled += int(usable.sum())

                dst.write(band, 1, window=window)
                prov.write(source, 1, window=window)
                print(f"   [{done}/{total}] {missing.sum():>7} trous, "
                      f"{usable.sum():>7} bouchés")

    pixels = width * height
    print(f"\n✅ {dem_path}")
    print(f"   trous initiaux : {holes:,} px ({100 * holes / pixels:.2f} %)")
    print(f"   bouchés        : {filled:,} px ({100 * filled / pixels:.2f} %)")
    residual = holes - filled
    print(f"   restants       : {residual:,} px ({100 * residual / pixels:.2f} %)")
    print(f"✅ {provenance_path}  — 1 = Lidar HD, 2 = corrélation, "
          f"3 = RGE ALTI, 0 = manquant")
    if residual:
        print("\n   ⚠️  Des trous subsistent : les viewsheds les traiteront comme "
              "des creux.")


if __name__ == "__main__":
    main()
