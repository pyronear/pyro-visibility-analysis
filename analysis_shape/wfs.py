"""GetFeature on the IGN WFS (`data.geopf.fr`), as a Lambert-93 GeoDataFrame.

Shared by fetch_zone.py (zones of interest) and find_candidates.py (BD TOPO
water towers). The caller imports pyproj / geopandas only after
`use_bundled_proj()`; this module does too, by being imported after it.
"""

import json
import urllib.parse
import urllib.request

import geopandas as gpd
import pandas as pd

WFS = "https://data.geopf.fr/wfs/ows"

# The server's cap on one GetFeature response; larger results come in pages.
PAGE = 5000

# WFS paging is only stable on a sorted request: without SORTBY the server
# may return pages in any order, duplicating or dropping features silently.
# One unique identifier per known layer.
SORT_FIELDS = {
    "BDTOPO_V3:foret_publique": "cleabs",
    "BDTOPO_V3:reservoir": "cleabs",
    "DEBROUSSAILLEMENT:debroussaillement": "id",
}


def get_features(layer, **params):
    frames = []
    start = 0
    sort_field = SORT_FIELDS.get(layer)
    while True:
        query = {
            "SERVICE": "WFS", "REQUEST": "GetFeature", "VERSION": "2.0.0",
            "TYPENAMES": layer, "OUTPUTFORMAT": "application/json",
            "SRSNAME": "EPSG:2154", "COUNT": PAGE, "STARTINDEX": start, **params,
        }
        if sort_field:
            query["SORTBY"] = sort_field
        elif start == PAGE:
            print(f"⚠️  {layer}: more than {PAGE} features and no known sort "
                  f"field, page order is not guaranteed — add one to SORT_FIELDS")
        url = f"{WFS}?{urllib.parse.urlencode(query)}"
        with urllib.request.urlopen(url, timeout=120) as response:
            data = json.load(response)
        features = data.get("features") or []
        if features:
            frames.append(gpd.GeoDataFrame.from_features(features, crs="EPSG:2154"))
        if len(features) < PAGE:
            break
        start += PAGE
    if not frames:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:2154")
    return gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:2154")


def bbox_l93(xmin, ymin, xmax, ymax):
    """The BBOX parameter for a Lambert-93 rectangle."""
    return f"{xmin},{ymin},{xmax},{ymax},urn:ogc:def:crs:EPSG::2154"
