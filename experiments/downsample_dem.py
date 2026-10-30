"""Coarsen an existing DEM by an integer factor, without re-downloading.

A 5 m DEM over a 15 km viewshed radius means ~28 M cells per site. If that turns
out to be too slow or too heavy in QGIS, dropping to 10 m divides the cell count
by 4 — and this script does it locally, from the file already on disk.

The aggregation method matters more than it looks:

    max     Keeps the highest point of each block. The right choice for a MNS:
            canopy and roof tops survive, which is the whole reason we moved off
            SRTM. Slightly over-blocking, since one isolated tall object claims
            the whole output cell.
    second  Second highest value of the block. A compromise for 2x2 blocks:
            keeps continuous canopy, drops isolated spikes (pylons, a single
            tree) that would otherwise block a whole ray.
    mean    Averages the block. Correct for a MNT (bare earth), wrong for a MNS
            — it pulls canopy tops down toward the ground.

Usage:
    uv run python experiments/downsample_dem.py --factor 2
    uv run python experiments/downsample_dem.py --factor 2 --method second
"""

import argparse
import importlib.util
import os
import sys


def _use_bundled_proj():
    """See generate_dem_fr.py — conda's PROJ shadows the one rasterio ships."""
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

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import Window  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REGION  # noqa: E402

NODATA = -9999.0
CHUNK_BLOCKS = 256  # output rows processed at a time


def aggregate_strip(strip, factor, method):
    """Aggregate a (rows*factor, cols*factor) strip into (rows, cols)."""
    rows = strip.shape[0] // factor
    cols = strip.shape[1] // factor
    blocks = strip[:rows * factor, :cols * factor].reshape(
        rows, factor, cols, factor)
    # Nodata must not win a max() nor drag a mean() down.
    blocks = np.where(blocks <= -100, np.nan, blocks)

    with np.errstate(invalid="ignore"):
        if method == "max":
            out = np.nanmax(blocks, axis=(1, 3))
        elif method == "mean":
            out = np.nanmean(blocks, axis=(1, 3))
        elif method == "second":
            flat = blocks.transpose(0, 2, 1, 3).reshape(rows, cols, factor * factor)
            ordered = np.sort(flat, axis=2)  # NaNs sort to the end
            valid = np.sum(~np.isnan(flat), axis=2)
            # Index of the second highest valid value, clamped for blocks that
            # only hold one valid cell.
            idx = np.clip(valid - 2, 0, None)
            out = np.take_along_axis(ordered, idx[..., None], axis=2)[..., 0]
            out = np.where(valid == 0, np.nan, out)
        else:
            raise ValueError(f"unknown method: {method}")

    return np.where(np.isnan(out), NODATA, out).astype(np.float32)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=None,
                        help="input DEM (default: data/<region>/dem_l93.tif)")
    parser.add_argument("--output", default=None,
                        help="output DEM (default: <input>_<res>m.tif)")
    parser.add_argument("--factor", type=int, default=2,
                        help="integer coarsening factor (default: 2, i.e. 5 m -> 10 m)")
    parser.add_argument("--method", default="max",
                        choices=("max", "second", "mean"),
                        help="block aggregation; 'max' for a MNS (default)")
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args()

    input_path = args.input or os.path.join("data", args.region, "dem_l93.tif")
    if not os.path.exists(input_path):
        raise SystemExit(f"❌ {input_path} not found")
    if args.factor < 2:
        raise SystemExit("❌ --factor must be >= 2")

    with rasterio.open(input_path) as src:
        in_res = src.res[0]
        out_res = in_res * args.factor
        out_width = src.width // args.factor
        out_height = src.height // args.factor

        output_path = args.output or input_path.replace(
            ".tif", f"_{out_res:g}m.tif")

        print(f"Input   : {input_path} ({src.width} x {src.height} @ {in_res:g} m)")
        print(f"Output  : {output_path} ({out_width} x {out_height} @ {out_res:g} m)")
        print(f"Method  : {args.method}")
        print(f"Cells   : {src.width * src.height / 1e6:.1f} Mpx -> "
              f"{out_width * out_height / 1e6:.1f} Mpx "
              f"({args.factor ** 2}x fewer)")

        profile = src.profile.copy()
        profile.update(
            width=out_width,
            height=out_height,
            dtype="float32",
            nodata=NODATA,
            transform=src.transform * src.transform.scale(args.factor, args.factor),
            compress="LZW",
            tiled=True,
            blockxsize=512,
            blockysize=512,
        )

        nodata_cells = 0
        with rasterio.open(output_path, "w", **profile) as dst:
            for row_off in range(0, out_height, CHUNK_BLOCKS):
                rows = min(CHUNK_BLOCKS, out_height - row_off)
                strip = src.read(1, window=Window(
                    0, row_off * args.factor,
                    out_width * args.factor, rows * args.factor)).astype(np.float32)
                out = aggregate_strip(strip, args.factor, args.method)
                nodata_cells += int((out == NODATA).sum())
                dst.write(out, 1, window=Window(0, row_off, out_width, rows))
                print(f"   rows {row_off}-{row_off + rows} written")

    size_mb = os.path.getsize(output_path) / 1e6
    pct = 100 * nodata_cells / (out_width * out_height)
    print(f"\n✅ {output_path} ({size_mb:.0f} MB, {pct:.2f} % nodata)")
    print("   To use it, rename it to dem_l93.tif.")


if __name__ == "__main__":
    main()
