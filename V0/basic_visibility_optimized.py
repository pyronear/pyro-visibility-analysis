import csv
import os
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsRasterLayer
)
from PyQt5.QtCore import QVariant
from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry

## Constants
DEFAULT_HEIGHT = 30  # in meters

## Paths
ANALYSIS_PATH = r"C:\Users\merli\Desktop\@\Cours\3A\PyroNear\tuto"
VIEWSHED_STYLE_FILE_PATH = os.path.join(ANALYSIS_PATH, "Digital_Elevation_Model_basRhin.qml")
CSV_PATH = os.path.join(ANALYSIS_PATH, "Liste points hauts Pyronear.csv")
DEM_PATH = os.path.join(ANALYSIS_PATH, "dem_file.tif")
OUTPUT_VIEWSHEDS_PATH = os.path.join(ANALYSIS_PATH, "Viewsheds_geotiff")
os.makedirs(OUTPUT_VIEWSHEDS_PATH, exist_ok=True)

## Initialize groups
layer_tree_root = QgsProject.instance().layerTreeRoot()
groupe_points = layer_tree_root.addGroup("Points_Hauts_Potentiels")
viewshed_group = layer_tree_root.addGroup("Viewsheds")

i = 0

def calculate_white_area_optimized(raster_layer):
    """
    Calculate the area corresponding to pixels > 0 in a raster using QgsRasterCalculator.
    """
    if not raster_layer.isValid():
        print("Invalid raster layer!")
        return None

    # Prepare raster calculator entry
    entry = QgsRasterCalculatorEntry()
    entry.ref = "raster@1"
    entry.raster = raster_layer
    entry.bandNumber = 1

    # Temporary output file
    temp_output = os.path.join(OUTPUT_VIEWSHEDS_PATH, "temp_white_area.tif")

    # Run raster calculation (mask values > 0)
    calc = QgsRasterCalculator(
        'raster@1 > 0',
        temp_output,
        "GTiff",
        raster_layer.extent(),
        raster_layer.width(),
        raster_layer.height(),
        [entry]
    )
    calc.processCalculation()

    # Open the result layer
    result_layer = QgsRasterLayer(temp_output, "Temp White Area", "gdal")
    if not result_layer.isValid():
        print("Failed to calculate white area")
        return None

    # Calculate the number of pixels with value > 0
    provider = result_layer.dataProvider()
    stats = provider.bandStatistics(1, QgsRasterBandStats.All)
    visible_area = stats.sum * raster_layer.rasterUnitsPerPixelX() * raster_layer.rasterUnitsPerPixelY()

    return visible_area


def process_csv_points():
    """
    Process CSV points to perform reprojection, viewshed, and area calculation.
    """
    with open(CSV_PATH, newline='', encoding='utf-8') as csvfile:
        lecteur_csv = csv.DictReader(csvfile, delimiter=';')

        for i, ligne in enumerate(lecteur_csv):
            nom_point = ligne['Nom']
            latitude = float(ligne['Latitude'])
            longitude = float(ligne['Longitude'])
            hauteur = float(ligne["Hauteur (m)"]) if ligne["Hauteur (m)"] else DEFAULT_HEIGHT

            # Reproject point
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            point_reprojected = transform.transform(QgsPointXY(longitude, latitude))

            # Create point layer
            uri_reprojected = "Point?crs=EPSG:2154"
            reprojected_layer = QgsVectorLayer(uri_reprojected, f"Point_{nom_point}_Lambert93", "memory")
            provider = reprojected_layer.dataProvider()
            provider.addAttributes([QgsField("Nom", QVariant.String), QgsField("Latitude", QVariant.Double), QgsField("Longitude", QVariant.Double)])
            reprojected_layer.updateFields()

            feature = QgsFeature()
            feature.setGeometry(QgsGeometry.fromPointXY(point_reprojected))
            feature.setAttributes([nom_point, latitude, longitude])
            provider.addFeature(feature)

            QgsProject.instance().addMapLayer(reprojected_layer, False)
            groupe_points.addLayer(reprojected_layer)

            # Viewshed analysis
            viewpoint_result = processing.run("visibility:createviewpoints", {
                'OBSERVER_POINTS': reprojected_layer,
                'DEM': DEM_PATH,
                'RADIUS': 15000,
                'OBS_HEIGHT': hauteur,
                'TARGET_HEIGHT': 20,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            viewpoint_layer = viewpoint_result['OUTPUT']

            # Run viewshed
            params_viewshed = {
                'DEM': DEM_PATH,
                'OBSERVER_POINTS': viewpoint_layer,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
            result_viewshed = processing.run("visibility:viewshed", params_viewshed)
            viewshed_layer = QgsRasterLayer(result_viewshed['OUTPUT'], f"Viewshed_{nom_point}")

            if viewshed_layer.isValid():
                viewshed_layer.loadNamedStyle(VIEWSHED_STYLE_FILE_PATH)
                viewshed_layer.triggerRepaint()

                # Calculate white area (optional)
                if i == 0:
                    pass
                    # i+=1
                    # white_area = calculate_white_area_optimized(viewshed_layer)
                    # print(f"White area (visible zones) for {nom_point}: {white_area:.2f} m²")

                # Save viewshed as GeoTIFF
                output_file = os.path.join(OUTPUT_VIEWSHEDS_PATH, f"viewshed_{nom_point}.tif")
                processing.run("gdal:translate", {'INPUT': viewshed_layer, 'OUTPUT': output_file})

                QgsProject.instance().addMapLayer(viewshed_layer, False)
                viewshed_group.addLayer(viewshed_layer)
            else:
                print(f"Viewshed analysis failed for {nom_point}")


# Run the processing
process_csv_points()
# calculate_white_area_optimized()