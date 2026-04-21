import os
import streamlit as st
import geopandas as gpd
from shapely.ops import unary_union
from streamlit_folium import st_folium

# === CONFIGURATION ===
folder = "noord-limburg"

HERE = os.path.dirname(os.path.abspath(__file__))
gpkg_path = os.path.join(HERE, f"kmz_output_{folder}", f"viewsheds_{folder}.gpkg")
layer = "viewsheds"


@st.cache_data(show_spinner=False)
def load_data(path, layer):
    """Load the GeoPackage and pre-compute per-site area in km² using a local UTM CRS."""
    gdf = gpd.read_file(path, layer=layer)
    proj_crs = gdf.estimate_utm_crs()
    gdf_proj = gdf.to_crs(proj_crs)
    gdf["area_km2"] = gdf_proj.geometry.area / 1e6
    geoms_by_site = dict(zip(gdf["site_name"], gdf_proj.geometry))
    return gdf, proj_crs, geoms_by_site


def greedy_max_coverage(geoms_by_site, n):
    """Greedy approximation of max-coverage: pick n sites that maximize union area.

    Returns the list of selected site names, in pick order.
    """
    remaining = dict(geoms_by_site)
    selected = []
    current_union = None
    current_area = 0.0

    for _ in range(min(n, len(geoms_by_site))):
        best_name, best_gain, best_union, best_area = None, -1.0, None, 0.0
        for name, geom in remaining.items():
            new_union = geom if current_union is None else unary_union([current_union, geom])
            new_area = new_union.area
            gain = new_area - current_area
            if gain > best_gain:
                best_name, best_gain, best_union, best_area = name, gain, new_union, new_area
        if best_name is None:
            break
        selected.append(best_name)
        current_union, current_area = best_union, best_area
        del remaining[best_name]

    return selected


def main():
    st.set_page_config(page_title=f"Viewsheds — {folder}", layout="wide")
    st.title(f"Viewshed coverage — {folder}")

    if not os.path.exists(gpkg_path):
        st.error(
            f"GeoPackage not found at `{gpkg_path}`.\n\n"
            "Run `python export.py` first to generate it."
        )
        return

    gdf, proj_crs, geoms_by_site = load_data(gpkg_path, layer)
    sites = sorted(gdf["site_name"].tolist())

    st.sidebar.header("Sites")

    st.sidebar.subheader("Auto-select")
    n_auto = st.sidebar.number_input(
        "How many sites?",
        min_value=1,
        max_value=len(sites),
        value=min(3, len(sites)),
        step=1,
    )
    if st.sidebar.button(f"Pick best {n_auto} (max coverage)", width="stretch"):
        best = set(greedy_max_coverage(geoms_by_site, n_auto))
        for s in sites:
            st.session_state[f"site_{s}"] = s in best
        st.rerun()

    st.sidebar.subheader("Manual")
    ctrl_all, ctrl_none = st.sidebar.columns(2)
    if ctrl_all.button("All", width="stretch"):
        for s in sites:
            st.session_state[f"site_{s}"] = True
    if ctrl_none.button("None", width="stretch"):
        for s in sites:
            st.session_state[f"site_{s}"] = False

    selected = [
        s for s in sites
        if st.sidebar.checkbox(s, value=True, key=f"site_{s}")
    ]

    if not selected:
        st.info("Select at least one site from the sidebar.")
        return

    sub = gdf[gdf["site_name"].isin(selected)].copy()
    sub_proj = sub.to_crs(proj_crs)

    union_geom = unary_union(sub_proj.geometry.values)
    union_area_km2 = union_geom.area / 1e6
    sum_area_km2 = float(sub["area_km2"].sum())
    overlap_km2 = sum_area_km2 - union_area_km2

    c1, c2, c3 = st.columns(3)
    c1.metric("Sites selected", len(selected))
    c2.metric("Total covered area (union)", f"{union_area_km2:,.1f} km²")
    c3.metric("Overlap (double-counted)", f"{overlap_km2:,.1f} km²")

    sub_wgs = sub.to_crs("EPSG:4326")
    fmap = sub_wgs.explore(
        column="site_name",
        tooltip=["site_name", "area_km2"],
        popup=True,
        cmap="tab20",
        style_kwds={"fillOpacity": 0.4, "weight": 1},
        legend=True,
        tiles="CartoDB positron",
    )
    st_folium(fmap, height=600, returned_objects=[])

    st.subheader("Per-site area")
    table = (
        sub[["site_name", "area_km2"]]
        .rename(columns={"site_name": "Site", "area_km2": "Area (km²)"})
        .sort_values("Area (km²)", ascending=False)
        .reset_index(drop=True)
    )
    table["Area (km²)"] = table["Area (km²)"].round(1)
    st.dataframe(table, width="stretch")


if __name__ == "__main__":
    main()
