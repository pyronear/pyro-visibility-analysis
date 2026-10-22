import os

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas imports

import streamlit as st  # noqa: E402
import geopandas as gpd  # noqa: E402
from shapely.ops import unary_union  # noqa: E402
from streamlit_folium import st_folium  # noqa: E402

# === CONFIGURATION ===
from config import REGION  # set the region in config.py
folder = REGION

HERE = os.path.dirname(os.path.abspath(__file__))
gpkg_path = os.path.join(HERE, f"kmz_output_{folder}", f"viewsheds_{folder}.gpkg")
layer = "viewsheds"

# Outline simplification applied for display only, in metres. Areas come from
# the raster, so this trades nothing but pixel-level detail no one can see at
# map zoom.
DISPLAY_SIMPLIFY_M = 50.0


@st.cache_data(show_spinner=False)
def load_data(path, layer):
    """Load the GeoPackage and its per-site area in km².

    export.py stores `area_km2` counted on the raster, which is exact and
    unaffected by the geometry simplification applied for display. Older
    GeoPackages without the column fall back to measuring the geometry.
    """
    gdf = gpd.read_file(path, layer=layer)
    proj_crs = gdf.estimate_utm_crs()
    if "area_km2" not in gdf.columns:
        gdf["area_km2"] = gdf.to_crs(proj_crs).geometry.area / 1e6
    return gdf, proj_crs


def main():
    st.set_page_config(page_title=f"Viewsheds — {folder}", layout="wide")
    st.title(f"Viewshed coverage — {folder}")

    if not os.path.exists(gpkg_path):
        st.error(
            f"GeoPackage not found at `{gpkg_path}`.\n\n"
            "Run `python export.py` first to generate it."
        )
        return

    gdf, proj_crs = load_data(gpkg_path, layer)
    sites = sorted(gdf["site_name"].tolist())

    for s in sites:
        st.session_state.setdefault(f"site_{s}", True)

    st.sidebar.header("Sites")

    ctrl_all, ctrl_none = st.sidebar.columns(2)
    if ctrl_all.button("All", width="stretch"):
        for s in sites:
            st.session_state[f"site_{s}"] = True
    if ctrl_none.button("None", width="stretch"):
        for s in sites:
            st.session_state[f"site_{s}"] = False

    st.sidebar.subheader("Basemap")
    basemap = st.sidebar.selectbox(
        "Background map",
        ["OpenStreetMap", "Satellite"],
        index=0,
    )

    selected = [
        s for s in sites
        if st.sidebar.checkbox(s, key=f"site_{s}")
    ]

    if not selected:
        st.info("Select at least one site from the sidebar.")
        return

    sub = gdf[gdf["site_name"].isin(selected)].copy()
    sum_area_km2 = float(sub["area_km2"].sum())

    # The union is the one genuinely expensive metric: dissolving the selected
    # viewsheds takes minutes at 5 m, so it is computed on demand rather than on
    # every checkbox click. The cached value is dropped as soon as the selection
    # changes, so a stale number can never be shown against the wrong sites.
    selection_key = tuple(sorted(selected))
    has_union = st.session_state.get("union_selection") == selection_key

    c1, c2, c3 = st.columns(3)
    c1.metric("Sites selected", len(selected))

    if has_union:
        union_area_km2 = st.session_state["union_area_km2"]
        c2.metric("Total covered area (union)", f"{union_area_km2:,.1f} km²")
        c3.metric("Overlap (double-counted)",
                  f"{sum_area_km2 - union_area_km2:,.1f} km²")
    else:
        c2.metric("Total covered area (union)", "—")
        c3.metric("Overlap (double-counted)", "—")
        if c2.button("Compute union", width="stretch"):
            with st.spinner("Dissolving viewsheds — this takes a few minutes…"):
                geoms = sub.to_crs(proj_crs).geometry.values
                st.session_state["union_area_km2"] = (
                    unary_union(geoms).area / 1e6)
                st.session_state["union_selection"] = selection_key
            st.rerun()
        c3.caption(f"Sum of per-site areas: {sum_area_km2:,.1f} km² "
                   "(overlaps counted twice)")

    # Coarsen the outlines for the browser. Leaflet draws every polygon
    # individually, so the fine 5 m contours that QGIS renders effortlessly are
    # what makes this map slow. Nothing is lost: the areas shown come from
    # `area_km2`, counted on the raster, and QGIS remains the tool for looking
    # at the exact geometry.
    sub_display = sub.to_crs(proj_crs)
    sub_display["geometry"] = sub_display.geometry.simplify(DISPLAY_SIMPLIFY_M)
    sub_wgs = sub_display.to_crs("EPSG:4326")
    if basemap == "Satellite":
        tiles = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
        attr = "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community"
    else:
        tiles = basemap
        attr = None
    fmap = sub_wgs.explore(
        column="site_name",
        tooltip=["site_name", "area_km2"],
        popup=True,
        cmap="tab20",
        style_kwds={"fillOpacity": 0.4, "weight": 1},
        legend=True,
        tiles=tiles,
        attr=attr,
    )

    map_col, table_col = st.columns([3, 1])
    with map_col:
        st_folium(fmap, height=600, returned_objects=[], width=None)
        st.caption(
            f"Outlines simplified to {DISPLAY_SIMPLIFY_M:g} m for display. "
            "Areas are counted on the raster and are exact — open the "
            "viewsheds in QGIS to inspect the precise geometry."
        )
    with table_col:
        st.subheader("Per-site area")
        table = (
            sub[["site_name", "area_km2"]]
            .rename(columns={"site_name": "Site", "area_km2": "Area (km²)"})
            .sort_values("Area (km²)", ascending=False)
            .reset_index(drop=True)
        )
        table["Area (km²)"] = table["Area (km²)"].round(1)
        st.dataframe(table, width="stretch", height=600)


if __name__ == "__main__":
    main()
