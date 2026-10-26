"""Viewsheds with GDAL's `gdal_viewshed`, in Docker by default.

GDAL ≥ 3.13 is required and rarely the one a system ships: Ubuntu 24.04 has
3.8, conda environments often older. Earlier versions also let the observer's
own cell block the view: on a surface model the camera often sits just below
the top of its own structure (negative OBS_HEIGHT, see terrain.py), and GDAL
3.6 then lost 50 to 80 % of the area of such sites. 3.13 does not.

So by default `gdal_viewshed` runs from the official GDAL image, pinned below,
in one container kept alive for the whole batch. The repository is mounted at
the same path inside it, so every path is valid on both sides. Setting
`GDAL_VIEWSHED` overrides this with a native binary or any command prefix;
its version is checked either way.

Each site is computed on the DEM within the detection radius only, then placed
on the full DEM grid, which every downstream script expects (one grid for all
masks). The file stays small: tiles outside the window are never written.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
from contextlib import contextmanager

import numpy as np
import rasterio
from rasterio.windows import Window

from analysis_shape.area_analysis import BINARY_PROFILE

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GDAL_IMAGE = "ghcr.io/osgeo/gdal:ubuntu-small-3.13.3"
MIN_GDAL_VERSION = (3, 13)
ENGINE = "gdal_viewshed"

# Viewsheds found without a run.json, or with one that names no engine, were
# computed by the QGIS plugin before this module existed.
LEGACY_ENVELOPE = {"viewshed_radius_m": 15000, "target_height_m": 20,
                   "engine": "qgis-visibility-plugin"}


def _gdal_version(prefix):
    try:
        result = subprocess.run([*prefix, "--version"], capture_output=True, text=True)
    except FileNotFoundError:
        raise SystemExit(f"❌ {prefix[0]} not found (GDAL_VIEWSHED). Unset it to "
                         f"use Docker, or see docs/reference.md « Native GDAL ».")
    # Not the return code: some versions print theirs, then fail on the
    # missing arguments.
    match = re.search(r"GDAL (\d+)\.(\d+)\.(\d+)", result.stdout + result.stderr)
    if not match:
        raise SystemExit(f"❌ « {' '.join(prefix)} --version » failed:\n"
                         f"{(result.stderr or result.stdout).strip()}")
    version = tuple(int(part) for part in match.groups())
    if version[:2] < MIN_GDAL_VERSION:
        raise SystemExit(
            f"❌ {' '.join(prefix)} is GDAL {'.'.join(map(str, version))}; "
            f"{'.'.join(map(str, MIN_GDAL_VERSION))} or later is required "
            f"(older versions let the observer's own cell block the view).\n"
            f"   Unset GDAL_VIEWSHED to use Docker, or see docs/reference.md "
            f"« Native GDAL ».")
    return ".".join(map(str, version))


def _require_docker():
    if shutil.which("docker") is None:
        raise SystemExit(
            "❌ Docker not found. Install Docker, or point GDAL_VIEWSHED at a "
            "native gdal_viewshed ≥ 3.13 (docs/reference.md « Native GDAL »).")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("❌ Docker is installed but not running: start Docker "
                         "Desktop (or the docker service) and retry.")
    if subprocess.run(["docker", "image", "inspect", GDAL_IMAGE],
                      capture_output=True).returncode != 0:
        print(f"   pulling {GDAL_IMAGE} (once, ~150 MB)…")
        subprocess.run(["docker", "pull", "-q", GDAL_IMAGE], check=True)


@contextmanager
def gdal_viewshed_command():
    """Yield the command prefix that runs `gdal_viewshed`, and its version.

    In Docker, the container lives as long as the `with` block: one start for
    the whole batch, each site then being a `docker exec`.
    """
    custom = os.environ.get("GDAL_VIEWSHED")
    if custom:
        prefix = shlex.split(custom)
        yield prefix, _gdal_version(prefix)
        return

    _require_docker()
    name = f"pyro-gdal-{os.getpid()}"
    # Files written in the container belong to the user, not to root.
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, *user,
                    "-v", f"{ROOT}:{ROOT}", GDAL_IMAGE, "sleep", "infinity"],
                   check=True, capture_output=True)
    try:
        prefix = ["docker", "exec", name, "gdal_viewshed"]
        yield prefix, _gdal_version(prefix)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def curvature_coefficient(earth_curvature, refraction):
    """GDAL's `-cc`: 0 ignores curvature, 1 − k applies it with refraction k."""
    return 1.0 - refraction if earth_curvature else 0.0


def compute_viewshed(prefix, dem_path, output_file, x, y, obs_height,
                     target_height, radius, curvature_coeff):
    """Viewshed of one site, written as a 0/1 mask on the full DEM grid.

    Written under a temporary name and renamed at the end, so that an
    interrupted run never leaves a file the next run would skip as done.
    """
    # Absolute paths: the container's working directory is not the repository.
    dem_path = os.path.realpath(dem_path)
    output_file = os.path.abspath(output_file)
    if not dem_path.startswith(ROOT + os.sep):
        raise SystemExit(f"❌ {dem_path} is outside the repository, which is "
                         f"all the GDAL container can see. Copy the DEM into "
                         f"data/ rather than linking to it from elsewhere.")
    # No .tif extension: a file left behind by a crash must not be picked up
    # by the scripts that glob viewsheds_geotiff/*.tif.
    window_file = f"{output_file}.window"
    result = subprocess.run(
        [*prefix, "-q",
         "-ox", f"{x:.2f}", "-oy", f"{y:.2f}",
         "-oz", f"{obs_height:.3f}", "-tz", f"{target_height}",
         "-md", f"{radius}", "-cc", f"{curvature_coeff}",
         "-vv", "1", "-iv", "0", "-ov", "0", "-of", "GTiff",
         dem_path, window_file],
        capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gdal_viewshed failed for {os.path.basename(output_file)}: "
                           f"{(result.stderr or result.stdout).strip()}")
    try:
        _place_on_grid(window_file, dem_path, f"{output_file}.part")
        os.replace(f"{output_file}.part", output_file)
    finally:
        for leftover in (window_file, f"{output_file}.part"):
            if os.path.exists(leftover):
                os.remove(leftover)


def _place_on_grid(window_file, dem_path, output_file):
    with rasterio.open(dem_path) as dem:
        meta = {"width": dem.width, "height": dem.height,
                "transform": dem.transform, "crs": dem.crs}
        dem_transform = dem.transform
    with rasterio.open(window_file) as src:
        data = (src.read(1) == 1).astype(np.uint8)
        col_off = int(round((src.transform.c - dem_transform.c) / dem_transform.a))
        row_off = int(round((src.transform.f - dem_transform.f) / dem_transform.e))

    # GDAL keeps its window inside the raster; clip anyway rather than trust it.
    top, left = max(row_off, 0), max(col_off, 0)
    bottom = min(row_off + data.shape[0], meta["height"])
    right = min(col_off + data.shape[1], meta["width"])
    data = data[top - row_off:bottom - row_off, left - col_off:right - col_off]

    # SPARSE_OK: tiles never written cost nothing on disk and read back as 0.
    # DEFLATE level 6, not 9: eight times faster for files ~20 % larger, and
    # level 9 made the write, not GDAL, the slowest part of a site.
    profile = {**BINARY_PROFILE, "zlevel": 6}
    with rasterio.open(output_file, "w", **profile, **meta,
                       sparse_ok=True) as dst:
        dst.write(data, 1, window=Window(left, top, right - left, bottom - top))


def check_run_metadata(output_dir, viewsheds_dir, envelope):
    """Record the run's envelope in run.json, and refuse to mix two of them.

    Viewsheds already on disk are skipped — that is what makes a re-run cheap.
    It also means changing the radius, the target height, curvature or the
    engine and re-running would reuse the old rasters and silently ignore the
    new setting. So a mismatch stops the run: one setting per folder.
    """
    path = os.path.join(output_dir, "run.json")
    existing = [f for f in os.listdir(viewsheds_dir) if f.endswith(".tif")] \
        if os.path.isdir(viewsheds_dir) else []

    previous = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                previous = json.load(handle)
        except (ValueError, OSError):
            previous = None
        if previous is not None and "engine" not in previous:
            previous = {**previous, "engine": LEGACY_ENVELOPE["engine"]}
    elif existing:
        previous = LEGACY_ENVELOPE

    if previous and existing:
        keys = ("viewshed_radius_m", "target_height_m", "engine",
                "earth_curvature", "refraction")
        differences = [(key, previous.get(key), envelope.get(key)) for key in keys
                       if previous.get(key) != envelope.get(key)]
        if differences:
            detail = "\n".join(f"     {key} : {was} → {now}"
                               for key, was, now in differences)
            raise SystemExit(
                f"❌ The {len(existing)} viewsheds in {viewsheds_dir} were "
                f"computed with other settings:\n{detail}\n"
                f"   They would be reused as they are. Either:\n"
                f"     · replace them → delete {output_dir}/ and rerun "
                f"(seconds to minutes with GDAL)\n"
                f"     · keep both → create data/<region>-<variant>/ with the "
                f"same sites.csv and a link to the DEM")

    if previous and previous.get("gdal_version") and "gdal_version" not in envelope:
        envelope = {**envelope, "gdal_version": previous["gdal_version"]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(envelope, handle, indent=2)


if __name__ == "__main__":
    # `make gdal-check`: which gdal_viewshed would run, and its version.
    with gdal_viewshed_command() as (prefix, version):
        print(f"gdal_viewshed: {' '.join(prefix)} → GDAL {version}")
