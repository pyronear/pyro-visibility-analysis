"""Observer elevation helpers.

The visibility plugin places the observer at `OBS_HEIGHT` metres **above the DEM
surface**. That was fine with SRTM, where a 30 m pixel hides water towers and
masts so the surface was effectively the ground. It breaks on a Lidar HD MNS at
5 m: the surface is the top of whatever stands there — sometimes the tower the
camera is mounted on, which then gets counted twice.

The physically meaningful quantity is the camera's absolute elevation:

    camera_elevation = MNT(site) + mast_height

and since the viewshed must keep running on the MNS (the canopy is exactly the
obstacle we care about), the value handed to the plugin becomes:

    OBS_HEIGHT = camera_elevation - MNS(observer pixel)

which may legitimately be negative when the camera sits below the top of its own
structure as captured by the lidar.

Note this is self-correcting: run the pipeline on a MNT and MNS(pixel) equals
MNT(site), so OBS_HEIGHT falls back to the plain mast height.
"""

import json
import math
import os
import urllib.parse
import urllib.request

import numpy as np
import rasterio
import rasterio.warp

WMS_URL = "https://data.geopf.fr/wms-r"
MNT_LAYER = "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93"
# Lidar HD is a rolling programme: a quarter of a test département had no MNT
# yet, and three of its sites sat in the gap. Without a fallback those three lose the
# surface correction entirely and their observer is placed on top of the canopy —
# exactly the double-counting this module exists to prevent. RGE ALTI is
# national and, being bare earth like the lidar MNT, measures the same thing.
MNT_FALLBACK_LAYER = "ELEVATION.ELEVATIONGRIDCOVERAGE"
NODATA_FLOOR = -100.0
CACHE_NAME = "ground_elevation.json"


def check_dem_extent(dem_path, sites, radius_m):
    """Refuse any site whose detection disc leaves the DEM.

    `sites` is an iterable of (name, longitude, latitude) in WGS84. The DEM is
    framed on sites.csv at download time, so a site appended later (ANFR
    candidates, a partner's second list) can sit near the edge: its viewshed
    would then be clipped by the raster boundary, understating its area and
    its rank with no warning. The fix is a new DEM, which changes the grid —
    and every viewshed must share one grid — so output/ goes with it.
    """
    sites = list(sites)
    if not sites:
        return
    with rasterio.open(dem_path) as src:
        bounds, crs = src.bounds, src.crs
    if crs is None or crs.to_epsg() is None:
        crs = rasterio.crs.CRS.from_epsg(2154)  # the chain is Lambert-93
    names, lons, lats = zip(*sites)
    xs, ys = rasterio.warp.transform("EPSG:4326", crs, list(lons), list(lats))
    outside = [name for name, x, y in zip(names, xs, ys)
               if x - radius_m < bounds.left or x + radius_m > bounds.right
               or y - radius_m < bounds.bottom or y + radius_m > bounds.top]
    if outside:
        raise RuntimeError(
            f"The DEM does not cover the {radius_m / 1000:g} km disc of "
            f"{len(outside)} site(s): {', '.join(outside)}.\n"
            f"   Their viewsheds are clipped by the raster edge. For full "
            f"discs, regenerate the DEM (generate_dem_fr.py frames it on "
            f"sites.csv), then delete {os.path.dirname(dem_path)}/output/: "
            f"a new DEM is a new grid, and every viewshed must share it.")


def sample_raster(raster_path, x, y):
    """Value of `raster_path` at the (x, y) Lambert-93 point, or None if nodata."""
    with rasterio.open(raster_path) as src:
        value = float(next(src.sample([(x, y)]))[0])
    return value if value > NODATA_FLOOR else None


def fetch_ground_elevation(x, y, half_size=50.0, resolution=5.0):
    """Bare-ground elevation at (x, y), from the IGN Lidar HD MNT.

    Falls back to RGE ALTI outside Lidar HD coverage. Requests a small window
    rather than a single pixel so that a nodata cell can fall back to the median
    of its surroundings.
    """
    for layer in (MNT_LAYER, MNT_FALLBACK_LAYER):
        value = _fetch_from_layer(layer, x, y, half_size, resolution)
        if value is not None:
            if layer is MNT_FALLBACK_LAYER:
                print(f"   ℹ️  no Lidar HD MNT here — ground taken from RGE ALTI "
                      f"({value:.1f} m)")
            return value
    return None


def _fetch_from_layer(layer, x, y, half_size, resolution):
    size = max(3, int(2 * half_size / resolution))
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "",
        "FORMAT": "image/geotiff",
        "CRS": "EPSG:2154",
        "BBOX": f"{x - half_size},{y - half_size},{x + half_size},{y + half_size}",
        "WIDTH": str(size),
        "HEIGHT": str(size),
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
    except Exception as exc:  # noqa: BLE001 - the MNT is a best-effort refinement
        print(f"   ⚠️  MNT request failed ({exc})")
        return None

    centre = window[window.shape[0] // 2, window.shape[1] // 2]
    if centre > NODATA_FLOOR:
        return float(centre)

    valid = window[window > NODATA_FLOOR]
    return float(np.median(valid)) if valid.size else None


# A cached ground elevation is reused only while the site stays within this
# distance of the position it was measured at.
CACHE_MOVE_TOLERANCE_M = 5.0


def cached_ground(cache, site_name, x, y):
    """Ground elevation cached for this site, or None if it must be fetched.

    Entries are {"ground", "x", "y"}, so a site whose coordinates were
    corrected is measured again. Older caches stored a bare number: those
    entries are trusted as they are, which avoids re-downloading every site.
    """
    entry = cache.get(site_name)
    if isinstance(entry, dict):
        moved = math.hypot(entry.get("x", x) - x, entry.get("y", y) - y)
        return entry.get("ground") if moved <= CACHE_MOVE_TOLERANCE_M else None
    return entry


def _cache_path(csv_path):
    return os.path.join(os.path.dirname(csv_path), CACHE_NAME)


def load_cache(csv_path):
    path = _cache_path(csv_path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (ValueError, OSError):
        return {}


def save_cache(csv_path, cache):
    try:
        with open(_cache_path(csv_path), "w", encoding="utf-8") as handle:
            json.dump(cache, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        print(f"   ⚠️  could not write the ground elevation cache ({exc})")


def observer_height(site_name, x, y, mast_height, dem_path, csv_path, cache):
    """OBS_HEIGHT to hand to the plugin, corrected for the DEM surface.

    Falls back to `mast_height` — the previous behaviour — whenever the MNT is
    unavailable, and says so, so a silent wrong number never goes unnoticed.
    """
    ground = cached_ground(cache, site_name, x, y)
    if ground is None:
        ground = fetch_ground_elevation(x, y)
        # Only a value is worth keeping. Caching a failure (None) turned one
        # network timeout into a permanently disabled correction for the site.
        if ground is not None:
            cache[site_name] = {"ground": ground, "x": round(x, 1), "y": round(y, 1)}
            save_cache(csv_path, cache)

    surface = sample_raster(dem_path, x, y)

    if ground is None or surface is None:
        print(f"   ⚠️  {site_name}: no MNT available, using the raw mast height "
              f"({mast_height} m above the DEM surface). If the DEM is a "
              f"surface model, this over-estimates the observer elevation.")
        return mast_height

    corrected = (ground + mast_height) - surface
    structure = surface - ground
    if abs(structure) > 1:
        print(f"   ℹ️  {site_name}: DEM surface is {structure:+.1f} m above the "
              f"MNT ground → OBS_HEIGHT {mast_height:.1f} → {corrected:.1f} m")
    return corrected
