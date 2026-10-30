"""Zones of interest, rasterised onto a viewshed grid.

Coverage in square kilometres answers "how much does this site see". It does
not answer "how much of what matters does it see", and the two rank candidates
very differently — on a test département, 16 of 24 candidates saw 0 km² of OLD despite
respectable raw areas.

Until now that second question was hardwired to the OLD layer. A département
with no OLD at all takes the département itself as zone of interest: on a test
case half of what the cameras saw fell in neighbouring départements, and reporting the raw union
would overstate the result by a factor of two.

A zone is therefore just a named polygon layer plus the mask it projects onto a
raster grid:

    old     data/<region>/old_debroussaillement.gpkg, layer `old`
    dept    the département contour, fetched once and cached
    <name>  data/<region>/zones/<name>.gpkg

`reference_km2` is measured on the polygons, never on the mask. The mask only
covers the DEM extent, so counting its pixels silently shrinks the denominator
and inflates every percentage. `clipped_pct` says how much of the zone the
raster actually reaches, and the caller is expected to complain when it is not
close to 100.
"""

import json
import os
import urllib.request

import geopandas as gpd
import rasterio
from shapely.geometry import shape
from rasterio.features import rasterize

GEO_API = "https://geo.api.gouv.fr"

# Below this, the DEM does not cover the zone and percentages of it are wrong.
COVERAGE_WARN_PCT = 99.0


class Zone:
    """A zone of interest projected onto one raster grid."""

    def __init__(self, name, mask, reference_km2, cell_km2):
        self.name = name
        self.mask = mask
        self.reference_km2 = reference_km2
        self.cell_km2 = cell_km2

    @property
    def raster_km2(self):
        """Area of the zone that the raster grid actually reaches."""
        return float(self.mask.sum()) * self.cell_km2

    @property
    def clipped_pct(self):
        if not self.reference_km2:
            return 100.0
        return 100.0 * self.raster_km2 / self.reference_km2

    def covered_km2(self, visible_mask):
        return float((visible_mask & self.mask).sum()) * self.cell_km2

    def warning(self):
        """Message to print when the DEM does not cover the whole zone."""
        if self.clipped_pct >= COVERAGE_WARN_PCT:
            return None
        return (f"⚠️  the DEM covers only {self.clipped_pct:.1f} % of « {self.name} » "
                f"({self.raster_km2:,.0f} of {self.reference_km2:,.0f} km²). "
                f"Percentages of this zone are computed on the full zone, so the "
                f"missing part counts as never covered.")


def _normalise_dept(dept):
    """`077` in the OLD layer, `77` in the API — accept either spelling."""
    d = str(dept).strip()
    return d.zfill(3), d.lstrip("0") or d


def _dept_gdf(region, dept):
    """Département contour, cached so the API is hit once per region."""
    cache = os.path.join("data", region, "zones", f"dept_{dept}.gpkg")
    if os.path.exists(cache):
        return gpd.read_file(cache, layer="zone")

    _, short = _normalise_dept(dept)
    url = (f"{GEO_API}/departements/{short}/communes"
           f"?fields=contour&format=json")
    with urllib.request.urlopen(url, timeout=120) as response:
        communes = json.load(response)
    if not communes:
        raise SystemExit(f"❌ no commune returned for département {short}")

    gdf = gpd.GeoDataFrame(
        {"dept": [short] * len(communes)},
        geometry=[shape(c["contour"]) for c in communes],
        crs="EPSG:4326",
    )
    gdf = gdf.dissolve(by="dept", as_index=False).to_crs("EPSG:2154")

    os.makedirs(os.path.dirname(cache), exist_ok=True)
    gdf.to_file(cache, driver="GPKG", layer="zone")
    return gdf


def region_dept(region, dept=None):
    """The région's département: `dept` if given, else `"dept"` in scenarios.json.

    scenarios.json is the one place a region declares its département, so the
    scripts do not each carry a default. None when neither says anything —
    which is fine outside France, or with a zone of one's own
    (data/<region>/zones/<name>.gpkg); only the « dept » zone needs it.
    """
    if dept:
        return str(dept).strip()
    path = os.path.join("data", region, "scenarios.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle).get("dept")
        if value:
            return str(value).strip()
    return None


def _zone_gdf(region, name, dept):
    if name == "old":
        path = os.path.join("data", region, "old_debroussaillement.gpkg")
        if not os.path.exists(path):
            raise SystemExit(f"❌ {path} not found — the OLD zone is unavailable")
        gdf = gpd.read_file(path, layer="old")
        if dept and "dept" in gdf.columns:
            padded, short = _normalise_dept(dept)
            gdf = gdf[gdf["dept"].astype(str).isin({padded, short})]
        return gdf

    if name == "dept":
        if not dept:
            raise SystemExit(
                f"❌ zone « dept » needs a département: set \"dept\" in "
                f"data/{region}/scenarios.json, or pass --dept")
        return _dept_gdf(region, dept)

    path = os.path.join("data", region, "zones", f"{name}.gpkg")
    if not os.path.exists(path):
        raise SystemExit(f"❌ unknown zone « {name} » — expected {path}")
    return gpd.read_file(path)


def load_zone(region, name, reference_path, dept=None):
    """Rasterise zone `name` onto the grid of `reference_path`."""
    with rasterio.open(reference_path) as src:
        shape_out = (src.height, src.width)
        transform, crs = src.transform, src.crs
        cell_km2 = abs(src.transform.a * src.transform.e) / 1e6

    # Some intermediate rasters come back with a LOCAL_CS WKT — a Lambert-93
    # grid stripped of its datum, which pyproj refuses to build a transformer
    # from. The whole pipeline is Lambert-93, so say so rather than crash.
    if crs is None or crs.to_epsg() is None:
        crs = rasterio.crs.CRS.from_epsg(2154)

    dept = region_dept(region, dept)
    gdf = _zone_gdf(region, name, dept).to_crs(crs)
    if gdf.empty:
        raise SystemExit(f"❌ zone « {name} » is empty for département {dept}")

    # Overlapping polygons would be counted twice by a plain sum of areas; the
    # union is also what the mask represents, so measure the same object.
    reference_km2 = float(gdf.geometry.union_all().area) / 1e6

    mask = rasterize(((geom, 1) for geom in gdf.geometry), out_shape=shape_out,
                     transform=transform, dtype="uint8").astype(bool)
    return Zone(name, mask, reference_km2, cell_km2)


def load_zones(region, names, reference_path, dept=None):
    """Load several zones, warning about any the DEM does not fully cover."""
    zones = []
    for name in names:
        zone = load_zone(region, name, reference_path, dept)
        if (message := zone.warning()):
            print(message)
        zones.append(zone)
    return zones
