"""Sanity-check the heights in a sites.csv against IGN Lidar HD.

Added after two sites in a test region were supplied with their NGF summit altitude
(142 m and 135 m) in the `Height` column, which expects metres above ground.
The pipeline cannot detect that on its own: it runs, produces a viewshed and
reports a plausible-looking coverage. Those two sites came out ranked first and
second when they are in fact last.

Three checks per site:

  altitude mix-up   `Height` close to the local ground elevation is the
                    signature of an altitude entered instead of a height.
  lidar agreement   For solid structures (water towers, buildings) the lidar
                    measures the real height and confirms the declared value.
                    Lattice masts are mostly air, so the lidar sees little or
                    nothing of them — that is expected physics, not an error,
                    and is reported as such rather than as a problem.
  coverage          Lidar HD is a rolling programme. A site outside coverage
                    cannot be checked, and cannot use the MNS either.

Usage:
    uv run python audit_sites.py
    uv run python audit_sites.py --region example
"""

import argparse
import math
import os
import urllib.parse
import urllib.request

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/rasterio imports

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from pyproj import Transformer  # noqa: E402

from config import REGION  # noqa: E402

WMS_URL = "https://data.geopf.fr/wms-r"
MNT_LAYER = "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93"
MNS_LAYER = "IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93"

# A height within this of the local ground elevation looks like an altitude.
ALTITUDE_MARGIN_M = 25.0
# Above this, no mast is plausible.
IMPLAUSIBLE_HEIGHT_M = 60.0
# Structures shorter than this are treated as "not captured" rather than as a
# contradiction: lattice masts are largely transparent to lidar.
CAPTURED_THRESHOLD_M = 10.0
# Tolerance when comparing a declared height to a measured structure.
AGREEMENT_MARGIN_M = 8.0
# Half-width of the window the structure is measured in: wide enough for a
# water tower whose coordinates fall off-centre, narrow enough to leave out the
# neighbouring mast.
STRUCTURE_HALF_M = 10.0


def sample(layer, x, y, half_size=50.0, resolution=5.0):
    size = max(3, int(2 * half_size / resolution))
    params = {
        "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
        "LAYERS": layer, "STYLES": "", "FORMAT": "image/geotiff",
        "CRS": "EPSG:2154",
        "BBOX": f"{x - half_size},{y - half_size},{x + half_size},{y + half_size}",
        "WIDTH": str(size), "HEIGHT": str(size),
    }
    url = f"{WMS_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read()
        if payload[:4] not in (b"II*\x00", b"MM\x00*"):
            return None
        with rasterio.io.MemoryFile(payload) as memfile:
            with memfile.open() as src:
                window = src.read(1).astype(float)
    except Exception:  # noqa: BLE001 - the audit is best-effort
        return None
    window[window < -100] = np.nan
    return None if np.all(np.isnan(window)) else window


def classify(height, ground, structure):
    """Return (verdict, is_problem)."""
    if height is None or math.isnan(height):
        hint = (f", lidar mesure {structure:.0f} m"
                if structure is not None and structure >= CAPTURED_THRESHOLD_M
                else "")
        return f"HAUTEUR MANQUANTE{hint}", True
    if height > IMPLAUSIBLE_HEIGHT_M:
        return f"IMPLAUSIBLE ({height:.0f} m au-dessus du sol)", True
    if abs(height - ground) < ALTITUDE_MARGIN_M:
        return f"SUSPECT — proche de l'altitude sol ({ground:.0f} m)", True
    # Agreement first: a 9 m vigie measured at 9 m is confirmed, not « missed ».
    if structure is not None and abs(height - structure) < AGREEMENT_MARGIN_M:
        return "ok — confirme par le lidar", False
    if structure is None or structure < CAPTURED_THRESHOLD_M:
        return "ok — structure non captee par le lidar (pylone treillis ?)", False
    return (f"a verifier — lidar mesure {structure:.0f} m pour {height:.0f} m "
            f"declares"), False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args()

    csv_path = os.path.join("data", args.region, "sites.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"❌ {csv_path} not found")

    sites = pd.read_csv(csv_path, delimiter=";")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)

    rows = []
    for site in sites.itertuples():
        x, y = transformer.transform(site.Longitude, site.Latitude)
        # Structure = MNS − MNT pixel by pixel, close to the point. It used to be
        # max(MNS) − median(MNT) over 100 m, which on a summit measures the
        # relief, not the tower: the lookout towers of a test département came out at 11-27 m of
        # « structure » where the lidar sees a 3 m hut, and a mast 30 m away
        # was read as the site itself.
        mnt = sample(MNT_LAYER, x, y, STRUCTURE_HALF_M, 1.0)
        if mnt is None:
            rows.append((site.Name, site.Height, None, None,
                         "HORS COUVERTURE LIDAR", True))
            continue
        mns = sample(MNS_LAYER, x, y, STRUCTURE_HALF_M, 1.0)
        ground = float(np.nanmedian(mnt))
        structure = float(np.nanmax(mns - mnt)) if mns is not None else None
        height = None if pd.isna(site.Height) else float(site.Height)
        verdict, problem = classify(height, ground, structure)
        rows.append((site.Name, height, ground, structure, verdict, problem))

    width = max(len(str(r[0])) for r in rows)
    print(f"\nAudit — {args.region}\n")
    print(f"{'site':<{width}} {'H':>6} {'sol':>7} {'struct':>7}  verdict")
    for name, height, ground, structure, verdict, _ in rows:
        h = f"{height:.1f}" if height is not None and not math.isnan(height) else "--"
        g = f"{ground:.1f}" if ground is not None else "--"
        s = f"{structure:.1f}" if structure is not None else "--"
        print(f"{name:<{width}} {h:>6} {g:>7} {s:>7}  {verdict}")

    problems = [r for r in rows if r[5]]
    print(f"\n{len(problems)} point(s) d'attention sur {len(rows)} sites")
    for name, *_, verdict, _ in problems:
        print(f"  - {name} : {verdict}")

    report = pd.DataFrame(
        [(n, h, g, s, v) for n, h, g, s, v, _ in rows],
        columns=["site", "height_declared", "ground_mnt", "structure_lidar",
                 "verdict"])
    report_path = os.path.join("data", args.region, "audit_hauteurs.csv")
    report.to_csv(report_path, sep=";", index=False)
    print(f"\n✅ {report_path}")


if __name__ == "__main__":
    main()
