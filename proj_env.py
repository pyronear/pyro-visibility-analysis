"""Keep a conda/miniforge PROJ from shadowing the one the wheels ship with.

A miniforge install exports `PROJ_DATA`, `PROJ_LIB` and `GDAL_DATA` globally, in
the shell profile. Those point at conda's own database, which can be older than
what the pyproj and rasterio wheels expect, and EPSG lookups then fail with:

    CRSError: The EPSG code is unknown. PROJ: ... proj.db contains
    DATABASE.LAYOUT.VERSION.MINOR = 2 whereas a number >= 6 is expected.

    ProjError: Error creating Transformer from CRS.

Clearing the variables lets each wheel fall back to its own bundled data, which
is the version it was built against.

Call `use_bundled_proj()` **before importing** pyproj, geopandas or rasterio —
they read the environment at import time.

Only for scripts run standalone (`uv run python ...`). Do **not** call it from
code running inside QGIS: QGIS provides its own consistent GDAL/PROJ stack and
relies on those variables.
"""

import os

_VARIABLES = ("PROJ_DATA", "PROJ_LIB", "GDAL_DATA")


def use_bundled_proj():
    """Drop conda's PROJ/GDAL data paths from the environment."""
    for variable in _VARIABLES:
        os.environ.pop(variable, None)
