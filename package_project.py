"""Package a QGIS project and its data into a zip anyone can open.

Reads the .qgz, extracts every layer path it references, and copies exactly
those files — no guesswork about what the project needs. The layer paths in
the project are already relative, so the archive opens as-is once unzipped.

The DEM is the one heavy file (556 MB) and only serves as a hillshade
backdrop, so `--light-dem` ships a coarsened copy instead.

Usage:
    uv run python package_project.py example.qgz
    uv run python package_project.py example.qgz --light-dem 50
"""

import argparse
import os
import re
import shutil
import zipfile

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede rasterio import

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402

SIDECARS = ('.aux.xml', '.qml')


def referenced_files(qgz_path):
    """Every local file the project points at, project-relative."""
    with zipfile.ZipFile(qgz_path) as archive:
        name = next(n for n in archive.namelist() if n.endswith('.qgs'))
        xml = archive.read(name).decode('utf-8', errors='replace')

    files = []
    for source in re.findall(r'<datasource>([^<]*)</datasource>', xml):
        source = source.strip()
        if not source or source.startswith(('type=', 'http', 'crs=')):
            continue  # XYZ tiles, remote services, memory layers
        path = source.split('|', 1)[0]
        if path.startswith('./'):
            path = path[2:]
        if os.path.exists(path):
            files.append(path)
    return sorted(set(files))


def coarsen(src_path, dst_path, target_res):
    """Write a coarser copy of a raster, for context layers only."""
    with rasterio.open(src_path) as src:
        factor = max(1, int(round(target_res / src.res[0])))
        width, height = src.width // factor, src.height // factor
        data = src.read(1, out_shape=(height, width),
                        resampling=Resampling.average)
        profile = src.profile.copy()
        profile.update(width=width, height=height,
                       transform=src.transform * src.transform.scale(factor, factor),
                       compress='DEFLATE', tiled=True,
                       blockxsize=512, blockysize=512)
    with rasterio.open(dst_path, 'w', **profile) as dst:
        dst.write(data.astype(profile['dtype']), 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', help='the .qgz to package')
    parser.add_argument('--light-dem', type=float, metavar='M',
                        help='ship the DEM coarsened to M metres (e.g. 50) '
                             'instead of the full-resolution file')
    parser.add_argument('--skip-viewsheds', action='store_true',
                        help='leave the 57 individual viewsheds out')
    parser.add_argument('--out', default=None, help='output zip path')
    args = parser.parse_args()

    if not os.path.exists(args.project):
        raise SystemExit(f'❌ {args.project} introuvable')

    files = referenced_files(args.project)
    stem = os.path.splitext(os.path.basename(args.project))[0]
    staging = f'livraison_{stem}'
    if os.path.exists(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)

    shutil.copy2(args.project, os.path.join(staging, os.path.basename(args.project)))
    total, skipped = 0, 0

    for path in files:
        if args.skip_viewsheds and 'viewsheds_geotiff' in path:
            skipped += 1
            continue
        destination = os.path.join(staging, path)
        os.makedirs(os.path.dirname(destination), exist_ok=True)

        if args.light_dem and os.path.basename(path).startswith('dem_l93'):
            print(f'   allègement du DEM → {args.light_dem:g} m …')
            coarsen(path, destination, args.light_dem)
        else:
            shutil.copy2(path, destination)

        for suffix in SIDECARS:
            sidecar = path + suffix
            if os.path.exists(sidecar):
                shutil.copy2(sidecar, destination + suffix)
        total += os.path.getsize(destination)

    # `viewshed_style.qml` is generic, shared by every viewshed of every
    # project. Scenario notes, however, are specific to a region
    # (`make_scenarios_md.py` writes one per region): derive them from the
    # paths referenced by THIS project rather than a fixed list — a leftover
    # from when this script shipped a single region copied that region's
    # analysis note into every region's export.
    regions = {m.group(1) for path in files
              if (m := re.match(r'data/([^/]+)/', path))}
    extras = ['viewshed_style.qml'] + [f'docs/scenarios-{r}.md' for r in regions]
    for extra in extras:
        if os.path.exists(extra):
            destination = os.path.join(staging, extra)
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            shutil.copy2(extra, destination)

    archive = args.out or f'{staging}.zip'
    print(f'   compression → {archive} …')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for root, _, names in os.walk(staging):
            for name in names:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, staging))
    shutil.rmtree(staging)

    print(f'\n✅ {archive} — {os.path.getsize(archive) / 1e6:.0f} Mo')
    print(f'   {len(files) - skipped} couches empaquetées'
          + (f', {skipped} viewsheds ignorés' if skipped else ''))
    print('   Le destinataire dézippe et ouvre le .qgz : les chemins sont relatifs.')


if __name__ == '__main__':
    main()
