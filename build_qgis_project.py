"""Assemble the full QGIS project, one group per family of layers.

Run this **from the QGIS Python console**, not from a terminal: it uses the
QGIS API, and unlike the standalone scripts it must NOT touch PROJ_DATA /
GDAL_DATA — QGIS relies on them.

    exec(open('/PATH/TO/pyro-visibility-analysis/build_qgis_project.py').read())

Layer tree, top to bottom (top = drawn over the others):

    Sites                 every candidate, coloured by access cost
    Scénarios             one coverage raster each, named with its metrics
    Zone d'enjeu          the stake, in magenta under the coverage rasters
    Viewsheds individuels split by owner category, hidden and collapsed
    Contexte              relief, then OpenStreetMap at the very bottom

Which region it builds comes from `PYRO_REGION` if defined in the console,
otherwise from `config.py`; everything else from
`data/<region>/scenarios.json` — the viewshed regions, the zone of interest and
its label. Set REGION, save the project inside the repo, run.

Scenario layers are named `<n> sites · <x> % couv · <y> % tri`, and their
site list sits in the layer metadata (Propriétés → Information).
"""

import glob
import importlib
import json
import os
import sys

from qgis.core import (
    QgsProject, QgsRasterLayer, QgsVectorLayer, QgsCoordinateReferenceSystem,
    QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol,
    QgsSimpleFillSymbolLayer, QgsHillshadeRenderer, QgsLayerMetadata,
    QgsReferencedRectangle,
)
from PyQt5.QtGui import QColor


def _repo_root():
    """Locate the repository, whichever way the script was started."""
    if '__file__' in globals():
        return os.path.dirname(os.path.abspath(__file__))
    home = QgsProject.instance().homePath()
    if not home:
        raise RuntimeError(
            "Save the QGIS project inside the pyro-visibility-analysis "
            "directory first, then rerun the script.")
    if not os.path.isdir(os.path.join(home, 'data')):
        raise RuntimeError(
            f"Project saved in {home}, which has no data/ folder.")
    return home


ROOT = _repo_root()
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Loaded by path, not via sys.path: the QGIS console may have lost it, and
# `importlib.reload` would raise « spec not found for the module 'config' ».
import analysis_shape.config_loader  # noqa: E402
importlib.reload(analysis_shape.config_loader)
_config = analysis_shape.config_loader.load_config()

# Comparing variants means switching region often. Defining PYRO_REGION in the
# console before the exec() avoids editing config.py — and avoids leaving it on
# a variant, which would then silently drive the next main.py run.
#     PYRO_REGION = 'example-th20-r20'
#     exec(open('.../build_qgis_project.py').read())
REGION = globals().get('PYRO_REGION') or _config.REGION

CONFIG_PATH = os.path.join(ROOT, 'data', REGION, 'scenarios.json')
if not os.path.exists(CONFIG_PATH):
    raise RuntimeError(
        f"{CONFIG_PATH} not found. This file describes the region: regions, "
        f"zone, dept, scenarios. See data/example/scenarios.json.")
with open(CONFIG_PATH, encoding='utf-8') as _handle:
    CONFIG = json.load(_handle)

OUT = os.path.join(ROOT, 'data', REGION, 'output')
REGIONS = tuple(CONFIG['regions'])
ZONE = CONFIG.get('zone', 'old')
DEPT = CONFIG.get('dept')
ZONE_LIBELLE = CONFIG.get('zone_libelle', ZONE)

_source = 'PYRO_REGION' if globals().get('PYRO_REGION') else 'config.py'
print(f'▶ REGION = {REGION} ({_source}) | zone = {ZONE} | '
      f'viewsheds : {", ".join(REGIONS)}')
_run = os.path.join(OUT, 'run.json')
if os.path.exists(_run):
    with open(_run, encoding='utf-8') as _h:
        _p = json.load(_h)
    print(f"   radius {_p.get('viewshed_radius_m', 0) / 1000:.0f} km, "
          f"target {_p.get('target_height_m')} m")

# One colour per access-cost category. Blue reads as "already there", green as
# free, amber as a convention to negotiate, red as a recurring bill.
SITE_COLORS = {
    'en place': '#2b6cb0',
    'public': '#2a9d4a',
    'delegataire': '#e08a1e',
    'operateur': '#d64545',
    'prive': '#d64545',
}

GROUP_LABELS = {
    'en place': 'Caméras en place',
    'public': 'Sites publics',
    'delegataire': 'Sites délégataires',
    'operateur': 'Sites opérateurs',
    'prive': 'Sites privés',
}


def site_buckets():
    """Map every site name to its owner category, across all the regions."""
    import csv
    import unicodedata

    from analysis_shape.gestionnaires import categoriser, charger

    table = charger(REGION)
    buckets = {}
    for region in REGIONS:
        path = os.path.join(ROOT, 'data', region, 'sites.csv')
        if not os.path.exists(path):
            continue
        with open(path, newline='', encoding='utf-8') as handle:
            for row in csv.DictReader(handle, delimiter=';'):
                name = unicodedata.normalize('NFC', row['Name']).strip()
                if str(row.get('Status', '')).strip() == 'EN PLACE':
                    buckets[name] = 'en place'
                elif str(row.get('Owner', '')).strip() == 'EN PLACE':
                    buckets[name] = 'en place'  # older sites.csv without Status
                else:
                    buckets[name] = categoriser(row.get('Owner', ''), table)
    return buckets


def add_raster(path, name, grp, visible=False, opacity=None, abstract=None):
    if not os.path.exists(path):
        print(f'   ⚠️  missing: {os.path.basename(path)}')
        return None
    layer = QgsRasterLayer(path, name)
    if not layer.isValid():
        print(f'   ⚠️  invalide : {name}')
        return None
    if opacity is not None:
        layer.renderer().setOpacity(opacity)
    if abstract:
        # QGIS 3 reads QgsLayerMetadata in Propriétés → Métadonnées ;
        # setAbstract() alone targets the legacy field and stays invisible.
        metadata = QgsLayerMetadata()
        metadata.setTitle(name)
        metadata.setAbstract(abstract)
        layer.setMetadata(metadata)
        layer.setAbstract(abstract)
    QgsProject.instance().addMapLayer(layer, False)
    grp.addLayer(layer).setItemVisibilityChecked(visible)
    return layer


def main():
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem('EPSG:2154'))
    root = project.layerTreeRoot()

    # Groups are appended, so the first one added ends up on top.
    g_sites = root.addGroup('Sites')
    g_scen = root.addGroup(f'Scénarios — {ZONE_LIBELLE}')
    g_tot = root.addGroup('Scénarios — couverture totale')
    g_old = root.addGroup(f'Zone d\'enjeu — {ZONE_LIBELLE}')
    g_vs = root.addGroup('Viewsheds individuels')
    g_ctx = root.addGroup('Contexte')

    buckets = site_buckets()

    # --- Sites -----------------------------------------------------------
    # One layer per region: ANFR candidates live in their own folder, and
    # keeping them apart lets them be switched off in one click.
    # `tous_sites.gpkg` used to be assembled by hand; summary.py now produces
    # the equivalent, with the `categorie` column.
    present = [v for v in SITE_COLORS if v in set(buckets.values())]

    def style_sites(layer):
        categories = []
        for value in present or list(SITE_COLORS):
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            symbol.setColor(QColor(SITE_COLORS[value]))
            symbol.setSize(3.4)
            categories.append(QgsRendererCategory(
                value, symbol, GROUP_LABELS.get(value, value)))
        layer.setRenderer(QgsCategorizedSymbolRenderer('categorie', categories))

    found = 0
    for region in REGIONS:
        region_out = os.path.join(ROOT, 'data', region, 'output')
        path = os.path.join(region_out, 'tous_sites.gpkg')
        if not os.path.exists(path):
            path = os.path.join(region_out, 'sites_with_coverage.gpkg')
        if not os.path.exists(path):
            print(f'   ⚠️  no sites layer for {region} — run '
                  f'summary.py --region {region}')
            continue
        sites = QgsVectorLayer(f'{path}|layername=sites', f'Sites — {region}',
                               'ogr')
        if not sites.isValid():
            print(f'   ⚠️  invalid Sites layer: {path}')
            continue
        style_sites(sites)
        project.addMapLayer(sites, False)
        g_sites.addLayer(sites)
        found += 1
    if not found:
        print(f'   ⚠️  no sites layer loaded')

    # --- Scénarios -------------------------------------------------------
    # A delivery does not always carry every computed scenario: defining
    # PYRO_SCENARIOS in the console before the exec() restricts the project
    # (and so what package_project.py ships, since it only copies what the
    # .qgz references) to those whose label starts with one of these
    # prefixes.
    #     PYRO_SCENARIOS = ['00', '01', '02', '03']
    folders = sorted(glob.glob(os.path.join(OUT, 'scenario_*')))
    _wanted = globals().get('PYRO_SCENARIOS')
    if _wanted:
        folders = [f for f in folders
                  if os.path.basename(f)[len('scenario_'):].startswith(tuple(_wanted))]
        print(f'   scenarios filtered on {_wanted}: '
              f'{", ".join(os.path.basename(f) for f in folders)}')
    for index, folder in enumerate(folders):
        label = os.path.basename(folder).replace('scenario_', '')
        meta_path = os.path.join(folder, 'meta.json')
        name, abstract = label, None
        if os.path.exists(meta_path):
            with open(meta_path, encoding='utf-8') as handle:
                meta = json.load(handle)
            name = (f"{label} · {meta['n_sites']} sites · "
                    f"{meta['pct_couvert']} % couv · {meta['pct_triangule']} % tri")
            abstract = ("Sites du scénario :\n  - "
                        + "\n  - ".join(meta['sites']))
        # The name changed when the zone of interest stopped being the OLD
        # by definition; the old one is still accepted for scenarios not
        # regenerated since.
        zone_raster = os.path.join(folder, 'couverture_zone_interet.tif')
        if not os.path.exists(zone_raster):
            zone_raster = os.path.join(folder, 'couverture_old.tif')
        add_raster(zone_raster, name, g_scen,
                   visible=(index == 0), opacity=0.75, abstract=abstract)

        # Same count, without restriction to the zone of interest. Class 0 is
        # declared nodata there, so only the areas seen show up.
        total_name = label
        if os.path.exists(meta_path):
            total_name = (f"{label} · {meta['n_sites']} sites · "
                          f"{meta['km2_total_couvert']:.0f} km² couverts · "
                          f"{meta['km2_total_triangule']:.0f} km² triangulés")
        add_raster(os.path.join(folder, 'couverture_zone.tif'), total_name,
                   g_tot, visible=False, opacity=0.75, abstract=abstract)

    # --- Zone d'enjeu ----------------------------------------------------
    # Magenta fill, under the coverage rasters: toggling a scenario off shows
    # the whole stake, toggling it on leaves only the uncovered parts visible
    # in red. Two readings of the same thing.
    if ZONE == 'old':
        zone_path = os.path.join(ROOT, 'data', REGION,
                                 'old_debroussaillement.gpkg')
        zone_layer_name, zone_filter = 'old', f"\"dept\" = '{DEPT}'"
    else:
        # Cached by analysis_shape/zones.py on the first computation.
        zone_path = os.path.join(ROOT, 'data', REGION, 'zones',
                                 f'dept_{DEPT}.gpkg' if ZONE == 'dept'
                                 else f'{ZONE}.gpkg')
        zone_layer_name, zone_filter = 'zone', None

    if os.path.exists(zone_path):
        old = QgsVectorLayer(f'{zone_path}|layername={zone_layer_name}',
                             f'Zone d\'enjeu — {ZONE_LIBELLE}', 'ogr')
        if old.isValid():
            if zone_filter:
                old.setSubsetString(zone_filter)
            symbol = QgsSymbol.defaultSymbol(old.geometryType())
            symbol.changeSymbolLayer(0, QgsSimpleFillSymbolLayer.create({
                'color': '186,60,190,140',
                'outline_color': '120,20,130,255',
                'outline_width': '0.3',
            }))
            old.renderer().setSymbol(symbol)
            project.addMapLayer(old, False)
            g_old.addLayer(old)

    # --- Viewsheds individuels -------------------------------------------
    # One subgroup per category actually present, in order of access cost:
    # what is already installed first, what must be paid for last.
    ordre = [c for c in SITE_COLORS if c in set(buckets.values())]
    if not ordre:
        ordre = ['public']
    subgroups = {c: g_vs.addGroup(GROUP_LABELS.get(c, c)) for c in ordre}
    style = os.path.join(ROOT, 'viewshed_style.qml')
    counts = {c: 0 for c in ordre}
    for region in REGIONS:
        pattern = os.path.join(ROOT, 'data', region, 'output',
                               'viewsheds_geotiff', '*.tif')
        for path in sorted(glob.glob(pattern)):
            name = os.path.basename(path)[len('viewshed_'):-len('.tif')]
            import unicodedata
            bucket = buckets.get(unicodedata.normalize('NFC', name).strip(),
                                 ordre[-1])
            if bucket not in subgroups:
                bucket = ordre[-1]
            layer = add_raster(path, name, subgroups[bucket])
            if layer and os.path.exists(style):
                layer.loadNamedStyle(style)
            counts[bucket] += 1
    for categorie, grp in subgroups.items():
        grp.setExpanded(False)
        grp.setName(f'{GROUP_LABELS.get(categorie, categorie)} '
                    f'({counts[categorie]})')
    g_vs.setExpanded(False)
    g_vs.setItemVisibilityChecked(False)

    # --- Contexte (OSM at the very bottom) -----------------------------------
    dem = add_raster(os.path.join(ROOT, 'data', REGION, 'dem_l93.tif'),
                     'Relief (MNS 10 m)', g_ctx)
    if dem:
        dem.setRenderer(QgsHillshadeRenderer(dem.dataProvider(), 1, 315.0, 45.0))

    osm = QgsRasterLayer(
        'type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png',
        'OpenStreetMap', 'wms')
    if osm.isValid():
        project.addMapLayer(osm, False)
        g_ctx.addLayer(osm)

    # Frame the project on the zone of interest, otherwise it opens on QGIS's
    # default extent — somewhere off the Gulf of Guinea.
    focus = None
    for layer in project.mapLayers().values():
        if layer.name().startswith('Zone d\'enjeu'):
            focus = layer.extent()
            break
    if focus is None:
        for layer in project.mapLayers().values():
            if layer.name().startswith('Sites ('):
                focus = layer.extent()
                break
    if focus is not None and not focus.isEmpty():
        focus.grow(max(focus.width(), focus.height()) * 0.05)
        try:
            project.viewSettings().setDefaultViewExtent(
                QgsReferencedRectangle(focus, project.crs()))
        except Exception:
            pass
        try:
            iface.mapCanvas().setExtent(focus)
            iface.mapCanvas().refresh()
        except Exception:
            pass
        print(f'   Framing: {focus.width() / 1000:.0f} x '
              f'{focus.height() / 1000:.0f} km on {ZONE_LIBELLE}')

    print(f'✅ Project built — {len(folders)} scenarios, '
          f'{sum(counts.values())} viewsheds')
    for categorie in ordre:
        print(f'     {GROUP_LABELS.get(categorie, categorie)} : '
              f'{counts[categorie]}')
    print(f'   Two scenario groups: {ZONE_LIBELLE}, and total coverage')
    print('   Only one layer ticked at a time in each group')
    print('   Red = not covered · Orange = 1 camera · Green = triangulated')
    print(f'   Site list: Properties → Metadata, or '
          f'docs/scenarios-{REGION}.md')
    print('   Remember to save the project again.')


main()
