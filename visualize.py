import os
import webbrowser
import geopandas as gpd

# === CONFIGURATION ===
folder = "noord-limburg"

HERE = os.path.dirname(os.path.abspath(__file__))
gpkg_path = os.path.join(HERE, f"kmz_output_{folder}", f"viewsheds_{folder}.gpkg")
output_html = os.path.join(HERE, f"kmz_output_{folder}", f"viewsheds_{folder}.html")
layer = "viewsheds"


def main():
    gdf = gpd.read_file(gpkg_path, layer=layer)

    print(f"Loaded {len(gdf)} features from {gpkg_path}")
    print(f"CRS: {gdf.crs}")
    print(f"Bounds: {gdf.total_bounds}")
    print(gdf[["site_name", "geometry"]].head(len(gdf)))

    # Reproject to WGS84 for web map (folium expects lat/lon)
    gdf_wgs = gdf.to_crs("EPSG:4326") if gdf.crs and gdf.crs.to_epsg() != 4326 else gdf

    m = gdf_wgs.explore(
        column="site_name",
        tooltip="site_name",
        popup=True,
        cmap="tab20",
        style_kwds={"fillOpacity": 0.4, "weight": 1},
        legend=True,
        tiles="CartoDB positron",
    )
    m.save(output_html)
    print(f"Interactive map saved to: {output_html}")

    # Auto-open in default browser
    webbrowser.open(f"file://{os.path.abspath(output_html)}")


if __name__ == "__main__":
    main()
