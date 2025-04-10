import csv
import os

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsRasterLayer, QgsPainting
)
from PyQt5.QtCore import QVariant
from qgis import processing

## Constant
DEFAULT_HEIGHT = 30  # in meters

def viewsheds_create(cvs_path, dem_path, elevation_style_file, output, layer_tree_root):
    """
    Process CSV points to create viewsheds in order to perform reprojection, and area calculation.
    """
    ## Initialize groups
    group_points = layer_tree_root.insertGroup(0, "Points_Hauts_Potentiels")
    viewshed_group = layer_tree_root.insertGroup(1, "Viewsheds")

    with open(cvs_path, newline='', encoding='utf-8') as csvfile:
        lecteur_csv = csv.DictReader(csvfile, delimiter=';')

        for i, ligne in enumerate(lecteur_csv):
            Name_point = ligne['Name']

            output_file = os.path.join(output, f"viewshed_{Name_point}.tif")
            if os.path.exists(output_file):
                continue

            latitude = float(ligne['Latitude'])
            longitude = float(ligne['Longitude'])
            Height = float(ligne["Height"]) if ligne["Height"] else DEFAULT_HEIGHT

            # Reproject point
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
            transform = QgsCoordinateTransform(source_crs, target_crs, QgsProject.instance())
            point_reprojected = transform.transform(QgsPointXY(longitude, latitude))

            # Create point layer
            uri_reprojected = "Point?crs=EPSG:2154"
            reprojected_layer = QgsVectorLayer(uri_reprojected, f"Point_{Name_point}_Lambert93", "memory")
            provider = reprojected_layer.dataProvider()
            provider.addAttributes([QgsField("Name", QVariant.String), QgsField("Latitude", QVariant.Double), QgsField("Longitude", QVariant.Double)])
            reprojected_layer.updateFields()

            feature = QgsFeature()
            geom = QgsGeometry.fromPointXY(point_reprojected)
            feature.setGeometry(geom)

            feature.setAttributes([Name_point, latitude, longitude])
            provider.addFeature(feature)

            QgsProject.instance().addMapLayer(reprojected_layer, False)
            group_points.addLayer(reprojected_layer)

            # Viewshed analysis
            viewpoint_result = processing.run("visibility:createviewpoints", {
                'OBSERVER_POINTS': reprojected_layer,
                'DEM': dem_path,
                'RADIUS': 15000,
                'OBS_HEIGHT': Height,
                'TARGET_HEIGHT': 20,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            })
            viewpoint_layer = viewpoint_result['OUTPUT']

            # Run viewshed
            params_viewshed = {
                'ANALYSIS_TYPE': 0,
                'OPERATOR': 0,
                'DEM': dem_path,
                'OBSERVER_POINTS': viewpoint_layer,
                'OUTPUT': output_file
            }
            result_viewshed = processing.run("visibility:viewshed", params_viewshed)
            viewshed_layer = QgsRasterLayer(result_viewshed['OUTPUT'], f"Viewshed_{Name_point}")
            
            if viewshed_layer.isValid():
                viewshed_layer.loadNamedStyle(elevation_style_file)
                viewshed_layer.setBlendMode(QgsPainting.getCompositionMode(QgsPainting.BlendAddition))
                viewshed_layer.renderer().contrastEnhancement().setMaximumValue(1)

                QgsProject.instance().addMapLayer(viewshed_layer, False)
                viewshed_group.addLayer(viewshed_layer)
    
            else:
                print(f"Viewshed analysis failed for {Name_point}")
    