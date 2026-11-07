"""One self-contained HTML page to browse a region without QGIS.

Writes `data/<region>/output/viewer.html`: a Leaflet map of what was computed —
the sites of the scenarios, their viewsheds, the zone of interest and the
département outline. Tick or untick any of those sites and the page recounts,
in the browser, how many cameras see each cell and the coverage /
triangulation of the zone. A `tous` scenario is not a selection: it is left
out, and so are the candidates no other scenario picked. The data is inside the file, so it can be
sent as is and opened with a double click (the basemaps need internet).

Each viewshed is resampled onto one shared Web Mercator grid (`--res`, 100 m
by default, ~70 m on the ground in France) and only the window around its site
is kept, as a 1-bit PNG. Figures in the page are therefore approximate: on 418
sites at 10 m, every scenario came within 0.3 point of the exact figures, at
50 m as at 100 m. The exact ones of each scenario come from its meta.json and
are shown next to them. 100 m gave a 7 MB page there, 50 m 16 MB.

Usage:
    make viewer REGION=<region>
    uv run python viewer.py --region <region> [--res 50]
"""

import argparse
import base64
import glob
import io
import json
import math
import os

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas/rasterio imports

import geopandas as gpd  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from PIL import Image  # noqa: E402
from rasterio.crs import CRS  # noqa: E402
from rasterio.enums import Resampling  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402
from rasterio.vrt import WarpedVRT  # noqa: E402
from rasterio.warp import transform, transform_bounds  # noqa: E402
from rasterio.windows import Window  # noqa: E402

from config import REGION  # noqa: E402
from analysis_shape.gestionnaires import categoriser, charger  # noqa: E402
from analysis_shape.names import site_name  # noqa: E402
from analysis_shape.zones import zone_geometry  # noqa: E402
from scenario_layers import DEPLOYED_MARKER, load_config, viewshed_index  # noqa: E402
from summary import detection_radius  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "viewer_template.html")
LOGO = os.path.join(HERE, "viewer_logo.png")
L93 = CRS.from_epsg(2154)
WEB = CRS.from_epsg(3857)
# Never a value of a viewshed mask (0/1, or 255 in some old ones).
VOTING_NODATA = 200


def png_b64(mask):
    """A boolean array as a base64 1-bit PNG."""
    buffer = io.BytesIO()
    Image.fromarray(mask).save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def source_crs(src):
    # Same fallback as zones.py: QGIS-era rasters carry a LOCAL_CS WKT that
    # is Lambert-93 stripped of its datum.
    if src.crs is None or src.crs.to_epsg() is None:
        return L93
    return src.crs


def shared_grid(paths, res):
    """Origin and size of one Web Mercator grid covering every viewshed."""
    boxes = []
    for path in paths:
        with rasterio.open(path) as src:
            boxes.append(transform_bounds(source_crs(src), WEB, *src.bounds))
    left = math.floor(min(b[0] for b in boxes) / res) * res
    bottom = math.floor(min(b[1] for b in boxes) / res) * res
    right = math.ceil(max(b[2] for b in boxes) / res) * res
    top = math.ceil(max(b[3] for b in boxes) / res) * res
    return left, top, round((right - left) / res), round((top - bottom) / res)


def read_sites(regions):
    """Every site of the regions' sites.csv, first region wins on a duplicate."""
    sites = {}
    for region in regions:
        path = os.path.join("data", region, "sites.csv")
        if not os.path.exists(path):
            continue
        table = charger(region)
        frame = pd.read_csv(path, delimiter=";")
        column = "Status" if "Status" in frame.columns else "Owner"
        for _, row in frame.iterrows():
            name = site_name(row["Name"])
            if name in sites:
                continue
            deployed = str(row.get(column, "")).strip() == DEPLOYED_MARKER
            owner = "" if pd.isna(row.get("Owner")) else str(row["Owner"])
            sites[name] = {
                "name": name, "region": region, "owner": owner,
                "height": None if pd.isna(row.get("Height")) else float(row["Height"]),
                "deployed": deployed,
                "category": "en place" if deployed else categoriser(owner, table),
                "lat": float(row["Latitude"]), "lon": float(row["Longitude"]),
            }
    return sites


def site_window(site, radius, grid, res):
    """Grid window around a site, its radius taken on the ground (Lambert-93)."""
    left, top, width, height = grid
    (x,), (y,) = transform("EPSG:4326", L93, [site["lon"]], [site["lat"]])
    west, south, east, north = transform_bounds(
        L93, WEB, x - radius, y - radius, x + radius, y + radius)
    col0 = max(0, math.floor((west - left) / res))
    row0 = max(0, math.floor((top - north) / res))
    col1 = min(width, math.ceil((east - left) / res))
    row1 = min(height, math.ceil((top - south) / res))
    return col0, row0, col1 - col0, row1 - row0


def read_window(path, window, grid, res):
    """The viewshed resampled onto the shared grid, inside `window` only."""
    left, top, width, height = grid
    col, row, w, h = window
    with rasterio.open(path) as src:
        # Mode keeps a coarse cell visible when most of it is. It skips
        # nodata, so an old raster declaring nodata=0 would turn every cell
        # with one visible pixel visible: its nodata is swapped for a value no
        # mask holds, so every pixel votes. The source's nodata then reads as
        # « not visible », as in summary.read_mask.
        with WarpedVRT(src, src_crs=source_crs(src), crs=WEB,
                       transform=from_origin(left, top, res, res),
                       width=width, height=height,
                       src_nodata=VOTING_NODATA, nodata=VOTING_NODATA,
                       resampling=Resampling.mode) as vrt:
            band = vrt.read(1, window=Window(col, row, w, h))
        visible = (band > 0) & (band != VOTING_NODATA)
        if src.nodata is not None:
            visible &= band != src.nodata
        return visible


def zone_layer(region, config, grid, res):
    """Zone mask on the grid, outline for display, area on the polygons."""
    left, top, width, height = grid
    name = config["zone"]
    geometry = zone_geometry(region, name, config.get("dept"))
    series = gpd.GeoSeries([geometry], crs=L93)
    mask = rasterize([(series.to_crs(WEB).iloc[0], 1)], out_shape=(height, width),
                     transform=from_origin(left, top, res, res),
                     dtype="uint8").astype(bool)
    outline = series.simplify(20).to_crs("EPSG:4326").iloc[0]
    return {
        "name": config.get("zone_libelle", name),
        # The denominator is the polygons, never the mask: the mask stops at
        # the grid, which would inflate every percentage (zones.py).
        # Unrounded: a forest zone may be well under 1 km².
        "km2": geometry.area / 1e6,
        "mask": png_b64(mask),
        "outline": outline.__geo_interface__,
    }


def dept_outline(region, config):
    """Département outline for display, or None outside France / without one."""
    if not config.get("dept"):
        return None
    geometry = zone_geometry(region, "dept", config["dept"])
    return gpd.GeoSeries([geometry], crs=L93).simplify(50).to_crs("EPSG:4326").iloc[0].__geo_interface__


def read_scenarios(region, config):
    """Scenarios computed by scenario_layers.py, except « every site » ones."""
    scenarios = []
    pattern = os.path.join("data", region, "output", "scenario_*", "meta.json")
    for path in sorted(glob.glob(pattern)):
        key = os.path.basename(os.path.dirname(path))[len("scenario_"):]
        spec = config["scenarios"].get(key)
        # Even frozen (--figer), « tous » lists the whole pool, not a choice.
        if spec is None or spec.get("tous"):
            continue
        with open(path, encoding="utf-8") as handle:
            meta = json.load(handle)
        scenarios.append({
            "label": meta["label"],
            "sites": [site_name(s) for s in meta["sites"]],
            "pct_couvert": meta.get("pct_couvert"),
            "pct_triangule": meta.get("pct_triangule"),
        })
    return scenarios


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--region", default=REGION)
    parser.add_argument("--res", type=float, default=100,
                        help="grid cell in Web Mercator metres (default: 100)")
    args = parser.parse_args()

    config = load_config(args.region)
    # Candidate pools may live in their own region folder: show them too.
    regions = list(dict.fromkeys(
        config["regions"]
        + [r for spec in config["scenarios"].values() if isinstance(spec, dict)
           for r in spec.get("regions_candidats", [])]))
    # First region wins, as in read_sites(), so a site's raster and its
    # position come from the same folder. Two different rasters under one name
    # are refused, as scenario_layers.scenario_paths() does.
    paths = {}
    for region in regions:
        for name, path in viewshed_index([region]).items():
            known = paths.setdefault(name, path)
            if known != path and not os.path.samefile(known, path):
                raise SystemExit(f"❌ « {name} » has two different viewsheds:\n"
                                 f"   {known}\n   {path}")
    if not paths:
        raise SystemExit(f"❌ no viewshed in data/{{{','.join(regions)}}}/output/"
                         f"viewsheds_geotiff/ — run compute_viewsheds.py first")
    # Only what was computed: the sites some scenario picked, not the whole
    # candidate pool. Without scenarios yet, every site.
    scenarios = read_scenarios(args.region, config)
    picked = {name for s in scenarios for name in s["sites"]}
    if picked:
        paths = {name: path for name, path in paths.items() if name in picked}
    else:
        print("   ⚠️  no scenario computed yet: every site is shown")
    sites = read_sites(regions)
    # Without scenarios, sites with no viewshed yet stay listed, unticked.
    shown = picked or set(sites)

    grid = shared_grid(paths.values(), args.res)
    left, top, width, height = grid
    print(f"▶ {len(paths)} viewsheds on a {width} × {height} grid "
          f"at {args.res:g} m")

    radii = {r: detection_radius(os.path.join("data", r, "output"))[0]
             for r in regions}
    for name, path in paths.items():
        site = sites.get(name)
        if site is None:
            print(f"   ⚠️  « {name} » has a viewshed but is in no sites.csv: skipped")
            continue
        window = site_window(site, radii[site["region"]], grid, args.res)
        site["window"] = list(window)
        site["mask"] = png_b64(read_window(path, window, grid, args.res))

    west, south, east, north = transform_bounds(
        WEB, "EPSG:4326", left, top - height * args.res,
        left + width * args.res, top)
    data = {
        "region": args.region,
        "grid": {"left": left, "top": top, "res": args.res,
                 "width": width, "height": height,
                 "bounds": [[south, west], [north, east]]},
        "zone": zone_layer(args.region, config, grid, args.res),
        "dept": dept_outline(args.region, config),
        "sites": [site for name, site in sites.items() if name in shown],
        "scenarios": scenarios,
    }

    with open(TEMPLATE, encoding="utf-8") as handle:
        page = handle.read()
    # « </ » would close the <script> block early if a name carried one.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("__DATA__", payload)
    # Inlined, like the data, so the page stays one file.
    with open(LOGO, "rb") as handle:
        logo = base64.b64encode(handle.read()).decode("ascii")
    page = page.replace("__LOGO__", f"data:image/png;base64,{logo}")
    out = os.path.join("data", args.region, "output", "viewer.html")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(page)
    print(f"✅ {out} ({os.path.getsize(out) / 1e6:.1f} MB) — open it in a browser")


if __name__ == "__main__":
    main()
