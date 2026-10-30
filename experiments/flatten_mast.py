"""Remove from the MNS the structure carrying the camera.

`analysis_shape/terrain.py` already corrects the observer *height* so the mast
is not counted twice: the MNS contains the structure, hence
`OBS_HEIGHT = (MNT + mast) − MNS(pixel)`. But it does not remove the structure
from the *relief*, and that is a gap: the plugin then casts its rays over a DEM
where the mast still stands, right in the way.

On a test site the correlation MNS carried a 230.5 m photogrammetric spike —
the pylon itself — in the cell next to the observer, 7 m away. A camera mounted
at 44 m sits at 197 m, so 33.5 m *below* that spike; a 10 m cell seen from 7 m
subtends a huge angle, and it erased **50° of horizon**, from azimuth 240 to
290, at every distance — including the first 500 m, the signature of an
obstacle glued to the observer. The same camera at 105 m clears the spike and
the sector comes back to 100 %.

Physically none of this exists: a lattice pylon is mostly air, and a camera
mounted on it is not masked by its own support. The bias therefore hits
exactly the low variants, i.e. what one is trying to compare.

The fix is local and conservative: within `--radius` metres of each site, any
cell rising more than `--seuil` metres above the surrounding surface is brought
back down to it. The reference is the median of the ring around that radius,
i.e. the real canopy of the place.

Two properties make the operation safe:

  * the observer's absolute elevation does not move. `terrain.py` rebuilds it
    as `MNT + mast`; lowering the pixel lowers the surface and raises
    `OBS_HEIGHT` by as much. Only the blocking disappears.
  * it is idempotent. After a pass no cell exceeds the threshold any more, so
    rerunning does nothing.

The radius matches the structure's footprint, never more: beyond it, real
canopy would be deleted. On that test site the spike fitted within 15 m and the
ground was found again from 15-25 m, hence the 20 m default.

⚠️ Edits the DEM in place, like `fill_dem_gaps.py`. Viewsheds already computed
must be deleted afterwards, as `compute_viewsheds.py` skips those that exist.

Usage:
    uv run python experiments/flatten_mast.py --dry-run
    uv run python experiments/flatten_mast.py --region example
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proj_env import use_bundled_proj  # noqa: E402

use_bundled_proj()  # must come before pyproj/rasterio

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

from config import REGION  # noqa: E402

NODATA_FLOOR = -1000.0
# Width of the reference ring, beyond the processed radius.
RING_WIDTH_M = 100.0


def flatten(dem_path, sites, radius_m, seuil_m, dry_run):
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    mode = "r" if dry_run else "r+"
    journal = []

    with rasterio.open(dem_path, mode) as src:
        pad = radius_m + RING_WIDTH_M
        for _, site in sites.iterrows():
            name = str(site["Name"]).strip()
            x, y = transformer.transform(site["Longitude"], site["Latitude"])
            window = from_bounds(x - pad, y - pad, x + pad, y + pad,
                                 src.transform)
            block = src.read(1, window=window).astype(float)
            transform = src.window_transform(window)

            rows, cols = np.indices(block.shape)
            xs = transform.c + (cols + 0.5) * transform.a
            ys = transform.f + (rows + 0.5) * transform.e
            distance = np.hypot(xs - x, ys - y)

            ring = (distance >= radius_m) & (distance < radius_m + RING_WIDTH_M)
            ring &= block > NODATA_FLOOR
            if not ring.any():
                print(f"   ⚠️  {name}: no reference around the point, skipped")
                continue
            reference = float(np.median(block[ring]))

            core = (distance < radius_m) & (block > NODATA_FLOOR)
            hit = core & (block > reference + seuil_m)
            if not hit.any():
                print(f"   ✓  {name}: nothing to flatten (surface ≤ "
                      f"{reference + seuil_m:.1f} m within {radius_m:.0f} m)")
                continue

            before = float(block[hit].max())
            print(f"   ▸  {name}: {int(hit.sum())} cell(s) brought down from "
                  f"{before:.1f} m to {reference:.1f} m "
                  f"(i.e. −{before - reference:.1f} m)")
            journal.append({"site": name, "cellules": int(hit.sum()),
                            "avant_max_m": round(before, 1),
                            "reference_m": round(reference, 1),
                            "rayon_m": radius_m, "seuil_m": seuil_m})

            if not dry_run:
                block[hit] = reference
                src.write(block.astype(src.dtypes[0]), 1, window=window)

    return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--dem", default=None,
                        help="default: data/<region>/dem_l93.tif")
    parser.add_argument("--radius", type=float, default=20.0,
                        help="radius processed around each site, in metres (default 20)")
    parser.add_argument("--seuil", type=float, default=5.0,
                        help="tolerated excess above the surrounding "
                             "surface, in metres (default 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without writing")
    args = parser.parse_args()

    dem_path = args.dem or os.path.join("data", args.region, "dem_l93.tif")
    csv_path = os.path.join("data", args.region, "sites.csv")
    for path in (dem_path, csv_path):
        if not os.path.exists(path):
            raise SystemExit(f"❌ {path} not found")

    sites = pd.read_csv(csv_path, delimiter=";")
    print(f"Region   : {args.region}")
    print(f"DEM      : {dem_path}")
    print(f"Sites    : {len(sites)}")
    print(f"Settings : radius {args.radius:.0f} m, threshold +{args.seuil:.0f} m"
          f"{' — DRY RUN' if args.dry_run else ''}\n")

    journal = flatten(dem_path, sites, args.radius, args.seuil, args.dry_run)

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return
    if not journal:
        print("\nNo change.")
        return

    log_path = os.path.join("data", args.region, "mast_flatten.json")
    with open(log_path, "w", encoding="utf-8") as handle:
        json.dump(journal, handle, ensure_ascii=False, indent=2)
    print(f"\n✅ DEM edited in place. Log: {log_path}")
    print("   Purge the viewsheds before rerunning compute_viewsheds.py:")
    print(f"     rm -rf data/{args.region}/output/viewsheds_geotiff "
          f"data/{args.region}/output/fusion "
          f"data/{args.region}/output/output.csv")
    print(f"     rm -f {dem_path}.aux.xml")


if __name__ == "__main__":
    main()
