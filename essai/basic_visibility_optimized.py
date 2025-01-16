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
ANALYSIS_PATH = r"C:\Users\merli\Desktop\@\Cours\3A\PyroNear\essai"
VIEWSHED_STYLE_FILE_PATH = os.path.join(ANALYSIS_PATH, "Digital_Elevation_Model_basRhin.qml")
CSV_PATH = os.path.join(ANALYSIS_PATH, "pts_hauts.csv")
DEM_PATH = os.path.join(ANALYSIS_PATH, "dem_file_projected.tif")
OUTPUT_VIEWSHEDS_PATH = os.path.join(ANALYSIS_PATH, "Viewsheds_geotiff")
os.makedirs(OUTPUT_VIEWSHEDS_PATH, exist_ok=True)

## Initialize groups
layer_tree_root = QgsProject.instance().layerTreeRoot()
groupe_points = layer_tree_root.addGroup("Points_Hauts_Potentiels")
viewshed_group = layer_tree_root.addGroup("Viewsheds")

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
                # Configure Single Band Gray Renderer
                min_value = 0
                max_value = 1
                gray_renderer = QgsSingleBandGrayRenderer(viewshed_layer.dataProvider(), 1)
                
                # Create a contrast enhancement object and set its algorithm
                contrast_enhancement = QgsContrastEnhancement()
                contrast_enhancement.setAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
                contrast_enhancement.setMinimumValue(min_value)
                contrast_enhancement.setMaximumValue(max_value)
                
                # Apply the contrast enhancement to the renderer
                gray_renderer.setContrastEnhancement(contrast_enhancement)
                gray_renderer.setGrayMinimumMaximum(min_value, max_value)
                viewshed_layer.setRenderer(gray_renderer)
                viewshed_layer.triggerRepaint()

                # Configurer le mode de fusion "Addition"
                viewshed_layer_renderer = viewshed_layer.renderer()
                layer_node = QgsProject.instance().layerTreeRoot().findLayer(viewshed_layer.id())
                if layer_node:
                    layer_node.setCustomProperty("blendMode", "5")  # "5" correspond à l'addition

                # Save viewshed as GeoTIFF
                output_file = os.path.join(OUTPUT_VIEWSHEDS_PATH, f"viewshed_{nom_point}.tif")
                processing.run("gdal:translate", {'INPUT': viewshed_layer, 'OUTPUT': output_file})

                # Ajouter la couche au projet
                QgsProject.instance().addMapLayer(viewshed_layer, False)
                viewshed_group.addLayer(viewshed_layer)
                print(f"Viewshed analysis done for {nom_point}")
            else:
                print(f"Viewshed analysis failed for {nom_point}")
    
    # Reorganize layers: Points_Hauts_Potentiels at top, Viewsheds second
    root = QgsProject.instance().layerTreeRoot()
    root.insertChildNode(0, groupe_points.clone())
    root.insertChildNode(1, viewshed_group.clone())

# Run the processing
process_csv_points()