import csv
import os
import re

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature,
    QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem,
    QgsCoordinateTransform, QgsRasterLayer, QgsVectorFileWriter
)
from PyQt5.QtCore import QVariant
from qgis import processing

from analysis_shape.area_analysis import compact_binary_raster
from analysis_shape.terrain import load_cache, observer_height
from analysis_shape.utils import display_tif
# Constant
DEFAULT_HEIGHT = 30  # in meters, above bare ground (not an NGF altitude)
# The envelope hardcoded before run.json existed: viewsheds found without a
# run.json are assumed to have been computed with it.
LEGACY_ENVELOPE = {"viewshed_radius_m": 15000, "target_height_m": 20}


def _detection_envelope():
    """RADIUS and TARGET_HEIGHT, read at call time rather than at import.

    The QGIS Python console caches imported modules, so a module-level
    `from config import ...` would freeze the values of the first run and
    silently ignore any later edit — the same trap that made main.py write into
    the previous REGION's folder.
    """
    from analysis_shape.config_loader import load_config
    config = load_config()
    return (getattr(config, "VIEWSHED_RADIUS_M", 15000),
            getattr(config, "TARGET_HEIGHT_M", 20))


def _write_run_metadata(output, radius_m, target_height_m):
    """Record the detection envelope, and refuse to mix two of them.

    Viewsheds already on disk are skipped — that is what makes a re-run cheap.
    It also means changing RADIUS or TARGET_HEIGHT and re-running produces
    nothing at all: the old rasters are reused, the new setting is silently
    ignored, and the resulting figures belong to neither envelope.

    So a mismatch stops the run rather than warning. A sensitivity study needs
    one region folder per envelope, not one folder holding both.
    """
    import glob
    import json

    path = os.path.join(os.path.dirname(output), "run.json")
    current = {"viewshed_radius_m": radius_m, "target_height_m": target_height_m}

    existing = glob.glob(os.path.join(output, "*.tif"))
    previous = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                previous = json.load(handle)
        except (ValueError, OSError):
            previous = None
    elif existing:
        # Viewsheds without a run.json predate it: they were computed with the
        # envelope then hardcoded, so compare against that.
        previous = LEGACY_ENVELOPE
    if previous:
        differences = [
            (key, previous.get(key), current[key])
            for key in current
            if previous.get(key) is not None and previous[key] != current[key]
        ]
        if differences and existing:
            detail = "\n".join(
                f"     {key} : {was} → {now}" for key, was, now in differences)
            raise RuntimeError(
                f"Les {len(existing)} viewsheds de ce dossier ont été "
                f"calculés avec d'autres paramètres :\n{detail}\n"
                f"   Ils seraient réutilisés tels quels et le nouveau "
                f"réglage ignoré.\n"
                f"   Deux options :\n"
                f"     · comparer deux réglages → créer data/<region>-<variante>/ "
                f"avec le même sites.csv et un lien vers le DEM\n"
                f"     · remplacer → supprimer {output}/ et "
                f"{os.path.dirname(output)}/normalized/")

    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(current, handle, indent=2)
    except OSError as exc:
        print(f"   ⚠️  could not write {path} ({exc})")


def viewsheds_create(csv_path, dem_path, elevation_style_file, output, layer_tree_root):
    """
    Process CSV points to create viewsheds in order to perform reprojection, and area calculation.
    """
    # Initialize groups (the "Viewsheds" group is created by display_tif)
    group_points = layer_tree_root.insertGroup(0, "Points_Hauts_Potentiels")

    # Ground elevations are fetched once per site and cached next to sites.csv.
    ground_cache = load_cache(csv_path)

    radius_m, target_height_m = _detection_envelope()
    print(f"▶ RADIUS = {radius_m} m, TARGET_HEIGHT = {target_height_m} m")

    # Record the envelope next to the rasters. The radius is a property of this
    # run, not a global constant: reading it back from config.py later would
    # relabel an old 15 km region as 25 km the day the default changes.
    _write_run_metadata(output, radius_m, target_height_m)

    with open(csv_path, newline='', encoding='utf-8') as csvfile:
        lecteur_csv = csv.DictReader(csvfile, delimiter=';')

        for i, ligne in enumerate(lecteur_csv):

            # ANFR/BD TOPO addresses sometimes carry a character illegal in
            # a path ('/' in a motorway address such as « A6 >Paris/Aire de
            # Service », a direction of travel with '>'…). A '/' turns the
            # name into a missing subfolder; the QGIS plugin does not check
            # that gdal.Create() succeeded before calling SetProjection() on
            # it, and crashes with an error that says nothing of the real
            # cause (`'NoneType' object has no attribute 'SetProjection'`).
            # Cleaned once here, for every name downstream.
            Name_point = re.sub(r'[/\\:*?"<>|]', '-', ligne['Name'])

            output_file = os.path.join(output, f"viewshed_{Name_point}.tif")

            latitude = float(ligne['Latitude'])
            longitude = float(ligne['Longitude'])
            Height = float(
                ligne["Height"]) if ligne["Height"] else DEFAULT_HEIGHT

            # Reproject point
            source_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            target_crs = QgsCoordinateReferenceSystem("EPSG:2154")
            transform = QgsCoordinateTransform(
                source_crs, target_crs, QgsProject.instance())
            point_reprojected = transform.transform(
                QgsPointXY(longitude, latitude))

            # Create point layer
            uri_reprojected = "Point?crs=EPSG:2154"
            reprojected_layer = QgsVectorLayer(
                uri_reprojected, f"Point_{Name_point}_Lambert93", "memory")
            provider = reprojected_layer.dataProvider()
            provider.addAttributes([QgsField("Name", QVariant.String), QgsField(
                "Latitude", QVariant.Double), QgsField("Longitude", QVariant.Double)])
            reprojected_layer.updateFields()

            feature = QgsFeature()
            geom = QgsGeometry.fromPointXY(point_reprojected)
            feature.setGeometry(geom)

            feature.setAttributes([Name_point, latitude, longitude])
            provider.addFeature(feature)

            gpkg_observation_point_path = os.path.join(
                os.path.dirname(output), "observation_points", f"{Name_point}.gpkg")

            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "point"
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

            QgsVectorFileWriter.writeAsVectorFormatV2(
                reprojected_layer,
                gpkg_observation_point_path,
                QgsProject.instance().transformContext(),
                options
            )

            saved_layer = QgsVectorLayer(
                f"{gpkg_observation_point_path}|layername=point",
                f"Point_{Name_point}",
                "ogr"
            )

            QgsProject.instance().addMapLayer(saved_layer, False)
            group_points.addLayer(saved_layer)

            if os.path.exists(output_file):
                continue

            # Viewshed analysis
            viewpoint_result = processing.run("visibility:createviewpoints", {
                'OBSERVER_POINTS': reprojected_layer,
                'DEM': dem_path,
                'RADIUS': radius_m,
                'OBS_HEIGHT': observer_height(
                    Name_point,
                    point_reprojected.x(),
                    point_reprojected.y(),
                    Height,
                    dem_path,
                    csv_path,
                    ground_cache,
                ),
                'TARGET_HEIGHT': target_height_m,
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
            result_viewshed = processing.run(
                "visibility:viewshed", params_viewshed)

            # The plugin writes uncompressed Float32 for a 0/1 mask (~400 MB
            # per site at 5 m). Rewrite it as compressed uint8 before anything
            # else touches it; the values are unchanged.
            compact_binary_raster(result_viewshed['OUTPUT'])

            viewshed_layer = QgsRasterLayer(
                result_viewshed['OUTPUT'], f"Viewshed_{Name_point}")

            if viewshed_layer.isValid():

                display_tif(
                    result_viewshed['OUTPUT'],
                    group_name="Viewsheds",
                    style_file_path=elevation_style_file)

            else:
                print(f"Viewshed analysis failed for {Name_point}")
