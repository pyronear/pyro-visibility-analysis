"""Write `output.csv` without the pairwise overlap matrix.

At the end `main.py` normally computes three things: the fusion/union, each
site's area, and an N×N overlap matrix between every pair of sites —
137×136/2 = 9 316 pairs on a test département, each re-reading two ~212 Mpx
rasters in full with no geometric pre-filter (yet two sites 80 km apart can
never overlap at a 20 km radius). That matrix, not the fusion nor the areas,
makes the final step of `main.py` disproportionately long on such a spread-out
pool — and nothing downstream reads it: `summary.py` only takes
`Site`/`Surface`, and `prioritise_sites.py` and `scenario_layers.py` do not
even read `output.csv`.

This script recomputes only `Surface` and `% du total` — one pass per site,
O(n) and fast — and writes `output.csv` in the format `summary.py` expects,
without ever computing the matrix.

    uv run python experiments/finish_output_csv.py --region example
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proj_env import use_bundled_proj  # noqa: E402

use_bundled_proj()  # must come before pyproj/rasterio

import pandas as pd  # noqa: E402

from analysis_shape.area_analysis import coverage, coverage_out_of_total_coverage  # noqa: E402
from config import REGION  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args()

    output_dir = os.path.join("data", args.region, "output")
    norm_dir = os.path.join(output_dir, "normalized")
    fusion_file = os.path.join(output_dir, "fusion", "fusion_or_all_sites.tif")
    out_path = os.path.join(output_dir, "output.csv")

    if not os.path.exists(fusion_file):
        raise SystemExit(f"❌ {fusion_file} introuvable — la fusion n'a pas été écrite")

    rows = []
    files = sorted(f for f in os.listdir(norm_dir) if f.endswith(".tif"))
    print(f"{len(files)} viewsheds normalisés trouvés")
    for i, fname in enumerate(files, 1):
        path = os.path.join(norm_dir, fname)
        name = fname.replace("norm_viewshed_", "").rsplit(".", 1)[0]
        surface = coverage(path)
        pct = coverage_out_of_total_coverage(path, fusion_file)
        rows.append({"Site": name, "Surface": surface, "% du total": pct})
        print(f"  [{i}/{len(files)}] {name} — {surface/1e6:.1f} km²")

    pd.DataFrame(rows).to_csv(out_path, sep=";", index=False)
    print(f"\n✅ {out_path} écrit ({len(rows)} sites, sans la matrice par paires)")


if __name__ == "__main__":
    main()
