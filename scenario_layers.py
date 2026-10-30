"""Build the QGIS layers for a given scenario of camera sites.

Rather than one layer per question, this writes a single raster counting **how
many cameras see each cell**. Read directly, it answers all three:

    0  zone not seen at all
    1  seen by one camera — detected, but not locatable
    2  seen by two — triangulation possible
    3  seen by three or more

Two rasters are produced: one restricted to the zone of interest (the
operational question) and one over the whole footprint (visual context). A
colour table is embedded in each, so QGIS renders them correctly on
drag-and-drop, with no style to load.

Everything region-specific lives in `data/<region>/scenarios.json`, next to the
data it describes — which viewsheds to draw from, which zone of interest, and
the scenarios themselves. A scenario is defined either way round:

    {"sites": ["site-a", "site-b"]}           explicit, matched on fragments
    {"en_place": true, "meilleurs": 6}        the deployed cameras plus the 6
                                              best by marginal contribution
    {"tous": true}                            every available viewshed

The generated form matters more than it looks. Listing site names freezes a
choice made against one state of the data; « les 6 meilleurs » is recomputed
each run, so correcting a height or a position updates the scenario instead of
silently invalidating it.

Usage:
    uv run python scenario_layers.py --list
    uv run python scenario_layers.py --scenario 03-existants-plus-6
    uv run python scenario_layers.py --all
    uv run python scenario_layers.py --sites "site-a,site-b"
"""

import argparse
import glob
import json
import os

from proj_env import use_bundled_proj

use_bundled_proj()  # must precede pyproj/geopandas/rasterio imports

import geopandas as gpd  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402

from config import REGION  # noqa: E402
from analysis_shape.gestionnaires import categoriser, charger  # noqa: E402
from analysis_shape.names import site_name as nfc  # noqa: E402
from analysis_shape.selection import WindowedMask, greedy_pick  # noqa: E402
from analysis_shape.zones import load_zone  # noqa: E402

os.environ.setdefault("OGR_GEOJSON_MAX_OBJ_SIZE", "0")

# red = blind, orange = seen once, greens = triangulated.
COLORMAP = {
    0: (214, 40, 40, 255),
    1: (247, 156, 40, 255),
    2: (120, 190, 90, 255),
    3: (30, 120, 60, 255),
}

DEPLOYED_MARKER = "EN PLACE"


def load_config(region):
    path = os.path.join("data", region, "scenarios.json")
    if not os.path.exists(path):
        raise SystemExit(
            f"❌ {path} not found.\n"
            f"   Create it with at least: regions, zone, dept, scenarios.\n"
            f"   See data/example/scenarios.json for a worked example.")
    with open(path, encoding="utf-8") as handle:
        config = json.load(handle)
    for key in ("regions", "zone", "scenarios"):
        if key not in config:
            raise SystemExit(f"❌ {path}: missing « {key} »")
    return config


def viewshed_index(regions):
    paths = {}
    for region in regions:
        pattern = f"data/{region}/output/viewsheds_geotiff/*.tif"
        for path in sorted(glob.glob(pattern)):
            name = nfc(os.path.basename(path)[len("viewshed_"):-len(".tif")])
            paths[name] = path
    return paths


def scenario_paths(spec, paths):
    """Viewsheds a scenario may name: `paths`, plus those of its candidate regions.

    `regions_candidats` may name a folder that is not in `regions` (docs: ANFR
    candidates in their own region folder). Its sites are picked from that pool,
    so building or re-reading a frozen list must find them too.

    A name with a different viewshed in `paths` and in the pool is refused: the
    greedy scores the pool's, the deployed baseline reads `paths`', and no single
    lookup can give each step the raster it used. The same file reached through a
    symlinked folder or file is not a different viewshed.
    """
    if not spec.get("regions_candidats"):
        return paths
    lookup = dict(paths)
    for name, path in viewshed_index(spec["regions_candidats"]).items():
        known = lookup.setdefault(name, path)
        if known != path and not os.path.samefile(known, path):
            raise SystemExit(
                f"❌ « {name} » has a viewshed in « regions » and another one in "
                f"« regions_candidats »:\n   {lookup[name]}\n   {path}\n"
                f"   Rename one of the two sites.")
    return lookup


def deployed_sites(regions, paths):
    """Sites flagged EN PLACE in any of the regions' sites.csv."""
    deployed = []
    for region in regions:
        csv_path = os.path.join("data", region, "sites.csv")
        if not os.path.exists(csv_path):
            continue
        sites = pd.read_csv(csv_path, delimiter=";")
        # Status when it exists, Owner otherwise — sites.csv files from before
        # the manager / status split marked EN PLACE in Owner.
        column = "Status" if "Status" in sites.columns else "Owner"
        for _, row in sites.iterrows():
            if str(row.get(column, "")).strip() == DEPLOYED_MARKER:
                name = nfc(row["Name"])
                if name in paths and name not in deployed:
                    deployed.append(name)
    return deployed


def owner_categories(regions):
    """Name → access-cost category ("public"/"operateur"/…), across regions.

    One `gestionnaires` table per region (`charger` falls back to the
    project-wide defaults), so a scenario restricted to one `regions_candidats`
    still classifies its sites with that region's own table.
    """
    categories = {}
    for region in regions:
        csv_path = os.path.join("data", region, "sites.csv")
        if not os.path.exists(csv_path):
            continue
        table = charger(region)
        sites = pd.read_csv(csv_path, delimiter=";")
        for _, row in sites.iterrows():
            categories[nfc(row["Name"])] = categoriser(row.get("Owner", ""), table)
    return categories


def write_site_points(sites, regions, path):
    """The scenario's sites as points, coloured like the project's Sites layer.

    Viewshed names are the sites.csv names read through site_name(), so the
    join is made on that same form.
    """
    wanted = set(sites)
    rows = []
    for region in regions:
        csv_path = os.path.join("data", region, "sites.csv")
        if not os.path.exists(csv_path):
            continue
        table = charger(region)
        frame = pd.read_csv(csv_path, delimiter=";")
        column = "Status" if "Status" in frame.columns else "Owner"
        for _, row in frame.iterrows():
            name = nfc(row["Name"])
            if name not in wanted:
                continue
            wanted.discard(name)
            deployed = str(row.get(column, "")).strip() == DEPLOYED_MARKER
            rows.append({
                "Name": name, "Height": row.get("Height"),
                "categorie": ("en place" if deployed
                              else categoriser(row.get("Owner", ""), table)),
                "lon": float(row["Longitude"]), "lat": float(row["Latitude"]),
            })
    if wanted:
        print(f"⚠️  not in any sites.csv, left out of sites.gpkg: "
              f"{', '.join(sorted(wanted))}")
    if not rows:
        return
    frame = pd.DataFrame(rows)
    points = gpd.GeoDataFrame(
        frame.drop(columns=["lon", "lat"]),
        geometry=gpd.points_from_xy(frame["lon"], frame["lat"]),
        crs="EPSG:4326").to_crs("EPSG:2154")
    points.to_file(path, driver="GPKG", layer="sites")


_CELL_CACHE = {}


def _cell(paths):
    """Cell area in km², from any viewshed — they all share the DEM grid."""
    key = next(iter(paths.values()))
    if key not in _CELL_CACHE:
        with rasterio.open(key) as src:
            _CELL_CACHE[key] = abs(src.transform.a * src.transform.e) / 1e6
    return _CELL_CACHE[key]


def read_mask(path):
    with rasterio.open(path) as src:
        band = src.read(1)
        if src.nodata is not None:
            band = np.where(band == src.nodata, 0, band)
    return band > 0


def resolve(fragments, paths):
    """Map loose name fragments to actual viewshed names."""
    chosen, missing = [], []
    for fragment in fragments:
        hits = [n for n in paths if nfc(fragment).lower() in n.lower()]
        if not hits:
            missing.append(fragment)
        else:
            chosen.append(sorted(hits, key=len)[0])
    return chosen, missing


def sites_for(spec, paths, config, zone):
    """Turn a scenario definition into a list of viewshed names.

    An explicit `sites` list wins over everything else, including a `tous` or
    `meilleurs` rule sitting next to it. That is what makes `--figer` work: it
    writes the resolved list back beside the rule that produced it, and from
    then on the list is what runs.
    """
    if "sites" in spec:
        # A list frozen from a candidate pool names sites of those regions too.
        return resolve(spec["sites"], scenario_paths(spec, paths))

    # A scenario may restrict its pool to some regions: « what the partner's
    # list gives alone » and « the list completed from ANFR » differ only in
    # that, once both sets of viewsheds sit side by side.
    pool = paths
    if spec.get("regions_candidats"):
        pool = viewshed_index(spec["regions_candidats"])
        if not pool:
            print(f"   ⚠️  no viewshed in "
                  f"{', '.join(spec['regions_candidats'])}")

    if spec.get("tous"):
        return sorted(pool), []

    base = deployed_sites(config["regions"], paths) if spec.get("en_place") else []
    n = spec.get("meilleurs")
    cible = spec.get("cible_pct")
    if n is None and cible is None:
        return base, []

    criterion = spec.get("critere", config.get("critere", "couverture"))
    max_operateurs = spec.get("max_operateurs")
    categories = (owner_categories(spec.get("regions_candidats") or config["regions"])
                  if max_operateurs is not None else None)
    # Windowed as they are read: 32 full masks on a test grid were ~3.7 GB.
    candidates = {name: WindowedMask(read_mask(path)) for name, path in pool.items()
                  if name not in base}
    baseline = [read_mask(paths[name]) for name in base]

    target_cells = None
    if cible is not None:
        # The target is expressed against the zone's true area, the same
        # denominator the reported percentages use.
        with rasterio.open(next(iter(paths.values()))) as src:
            cell_km2 = abs(src.transform.a * src.transform.e) / 1e6
        target_cells = int(round(cible / 100 * zone.reference_km2 / cell_km2))
        print(f"   target: {cible} % of « {zone.name} » by {criterion}")

    picked = greedy_pick(
        candidates, zone.mask, baseline_masks=baseline,
        picks=int(n) if n is not None else None,
        criterion=criterion, target_cells=target_cells,
        categories=categories, max_operateurs=max_operateurs,
        on_pick=lambda i, name, gain, reached: print(
            f"      {i}. {name:26s} +{gain * _cell(paths):6.0f} km² "
            f"→ {100 * reached * _cell(paths) / zone.reference_km2:5.1f} %"),
    )

    if cible is not None:
        if not picked:
            print(f"   ℹ️  {cible} % target already reached by the installed sites, "
                  f"or no candidate contributes to it")
        elif picked[-1][2] < target_cells:
            plafond = 100 * picked[-1][2] * _cell(paths) / zone.reference_km2
            print(f"   ⚠️  {cible} % target OUT OF REACH: the "
                  f"{len(candidates)} available candidates plateau at "
                  f"{plafond:.1f} %")
        else:
            print(f"   ✓ target reached with {len(picked)} added site(s), "
                  f"{len(base) + len(picked)} in total")
    elif n is not None and len(picked) < int(n):
        print(f"   ⚠️  only {len(picked)} of the {n} requested sites still add "
              f"anything to « {zone.name} »")
    return base + [name for name, _, _ in picked], []


def figer(config, region, paths, zone):
    """Expand generated scenarios into explicit site lists, in scenarios.json.

    « les 6 meilleurs » is convenient but invisible: you cannot read the config
    and know what a scenario contains, nor diff it, nor hand-correct one site.
    Freezing writes the resolved list next to the rule that produced it, so the
    scenario becomes reviewable and stops moving under a client's feet — while
    the rule stays there, documenting where the list came from. Delete the
    `sites` key to hand it back to the greedy.
    """
    from datetime import date

    path = os.path.join("data", region, "scenarios.json")
    changed = []
    for label, spec in config["scenarios"].items():
        if "sites" in spec:
            print(f"   = {label:32s} already explicit, left as is")
            continue
        sites, _ = sites_for(spec, paths, config, zone)
        spec["sites"] = sites
        spec["_fige_le"] = date.today().isoformat()
        # The scenario's own criterion wins, as in sites_for().
        spec["_fige_critere"] = spec.get("critere", config.get("critere", "couverture"))
        spec["_fige_zone"] = zone.name
        changed.append(label)
        print(f"   → {label:32s} {len(sites)} sites")
        for name in sites:
            print(f"        {name}")

    if not changed:
        print("\nNothing to freeze — every scenario is already explicit.")
        return

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"\n✅ {path} — {len(changed)} scenario(s) frozen")
    print("   Rerunning --figer will no longer recompute them; deleting their")
    print("   « sites » key hands them back to the marginal-gain computation.")


def build(label, sites, paths, config, zone, out_root):
    reference = paths[sites[0]]
    with rasterio.open(reference) as src:
        profile, shape = src.profile, src.shape
        cell_km2 = abs(src.transform.a * src.transform.e) / 1e6

    # How many cameras see each cell.
    count = np.zeros(shape, dtype=np.uint8)
    for name in sites:
        count += read_mask(paths[name]).astype(np.uint8)
    count = np.clip(count, 0, 3)

    out_dir = os.path.join(out_root, f"scenario_{label}")
    os.makedirs(out_dir, exist_ok=True)
    profile.update(dtype="uint8", count=1, compress="DEFLATE", zlevel=9,
                   tiled=True, blockxsize=512, blockysize=512)

    # Restricted to the zone: 255 (nodata) everywhere else, so the layer shows
    # only what matters operationally.
    zone_view = np.where(zone.mask, count, 255).astype(np.uint8)
    path_zone = os.path.join(out_dir, "couverture_zone_interet.tif")
    with rasterio.open(path_zone, "w", **dict(profile, nodata=255)) as dst:
        dst.write(zone_view, 1)
        dst.write_colormap(1, COLORMAP)

    # nodata = 0 : over the whole footprint, « seen by no camera » covers most
    # of the extent and is rarely the point. Declaring it nodata makes it
    # transparent in QGIS with no manual setting.
    path_all = os.path.join(out_dir, "couverture_zone.tif")
    with rasterio.open(path_all, "w", **dict(profile, nodata=0)) as dst:
        dst.write(count, 1)
        dst.write_colormap(1, COLORMAP)

    # Reference area comes from the polygons, not the mask: a mask only covers
    # the DEM extent, so counting its cells shrinks the denominator in silence.
    total = zone.reference_km2
    stats = pd.DataFrame({
        "classe": ["0 — non couvert", "1 — vue simple", "2 — triangulé",
                   "3+ — triangulé"],
        "km2": [(zone_view == v).sum() * cell_km2 for v in (0, 1, 2, 3)],
    })
    stats["% de la zone"] = (100 * stats["km2"] / total).round(1)
    stats["km2"] = stats["km2"].round(1)
    stats.to_csv(os.path.join(out_dir, "bilan.csv"), sep=";", index=False)

    # Counted on `count` masked by the zone — not on `zone_view`, whose 255
    # nodata values would satisfy any >= comparison.
    seen = ((count >= 1) & zone.mask).sum() * cell_km2
    tri = ((count >= 2) & zone.mask).sum() * cell_km2
    total_seen = (count >= 1).sum() * cell_km2
    total_tri = (count >= 2).sum() * cell_km2

    meta = {
        "label": label,
        "n_sites": len(sites),
        "zone": zone.name,
        "zone_libelle": config.get("zone_libelle", zone.name),
        "zone_km2": round(total, 1),
        "pct_couvert": round(100 * seen / total, 1),
        "pct_triangule": round(100 * tri / total, 1),
        "km2_zone_couvert": round(seen, 1),
        "km2_zone_triangule": round(tri, 1),
        "km2_total_couvert": round(total_seen, 1),
        "km2_total_triangule": round(total_tri, 1),
        "sites": sites,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)

    # One points layer per scenario, so the QGIS project can show which sites
    # a coverage raster is made of without reading its metadata.
    write_site_points(sites, config["regions"], os.path.join(out_dir, "sites.gpkg"))

    libelle = config.get("zone_libelle", zone.name)
    print(f"\n{libelle} : {total:,.0f} km²")
    print(stats.to_string(index=False))
    print(f"\n  covered       {seen:.0f} km²  ({100 * seen / total:.1f} %)")
    print(f"  triangulated  {tri:.0f} km²  ({100 * tri / total:.1f} %)")
    print(f"  including outside the zone: {total_seen:.0f} km² covered, "
          f"{total_tri:.0f} km² triangulated")
    print(f"\n✅ {out_dir}/")
    return meta


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--region", default=REGION,
                        help="region holding scenarios.json (default: config.REGION)")
    parser.add_argument("--scenario", help="scenario name from scenarios.json")
    parser.add_argument("--all", action="store_true",
                        help="build every scenario in scenarios.json")
    parser.add_argument("--sites", help="comma-separated site fragments, "
                                        "overrides --scenario")
    parser.add_argument("--list", action="store_true",
                        help="list viewsheds and scenarios, then exit")
    parser.add_argument("--figer", action="store_true",
                        help="resolve generated scenarios into explicit site "
                             "lists, written back into scenarios.json")
    parser.add_argument("--critere", choices=("couverture", "triangulation"),
                        help="override the criterion driving « meilleurs N »")
    args = parser.parse_args()

    config = load_config(args.region)
    if args.critere:
        config["critere"] = args.critere
    out_root = os.path.join("data", args.region, "output")
    paths = viewshed_index(config["regions"])
    if not paths:
        raise SystemExit(f"❌ no viewshed under data/{{{','.join(config['regions'])}}}"
                         f"/output/viewsheds_geotiff — run compute_viewsheds.py first")

    if args.list:
        deployed = deployed_sites(config["regions"], paths)
        print(f"{len(paths)} viewsheds :")
        for name in sorted(paths):
            print(f"   {'≡' if name in deployed else ' '} {name}")
        print(f"\nscenarios in data/{args.region}/scenarios.json:")
        for name, spec in config["scenarios"].items():
            if "sites" in spec:
                how = f"{len(spec['sites'])} sites listed"
            elif spec.get("tous"):
                how = "all sites"
                if spec.get("regions_candidats"):
                    how += f" [pool: {', '.join(spec['regions_candidats'])}]"
            else:
                how = ("installed" if spec.get("en_place") else "")
                if spec.get("regions_candidats"):
                    how += f" [pool: {', '.join(spec['regions_candidats'])}]"
                if spec.get("meilleurs"):
                    how += f" + {spec['meilleurs']} best"
                if spec.get("cible_pct"):
                    how += (f" + as many as needed for "
                            f"{spec['cible_pct']} % by "
                            f"{spec.get('critere', config.get('critere', 'couverture'))}")
            print(f"   {name:32s} {how.strip()}")
        return

    reference = next(iter(paths.values()))
    zone = load_zone(args.region, config["zone"], reference, config.get("dept"))
    if (message := zone.warning()):
        print(message)

    if args.figer:
        print(f"Freezing the scenarios of data/{args.region}/scenarios.json\n")
        figer(config, args.region, paths, zone)
        return

    if args.sites:
        jobs = [("sur-mesure", {"sites": [s.strip() for s in args.sites.split(",")]})]
    elif args.all:
        jobs = list(config["scenarios"].items())
    elif args.scenario:
        if args.scenario not in config["scenarios"]:
            raise SystemExit(f"❌ unknown scenario. Available: "
                             f"{', '.join(config['scenarios'])}")
        jobs = [(args.scenario, config["scenarios"][args.scenario])]
    else:
        raise SystemExit("❌ pass --scenario, --all, --sites or --list")

    for label, spec in jobs:
        print(f"\n{'=' * 70}\nScenario « {label} »")
        sites, missing = sites_for(spec, paths, config, zone)
        if missing:
            print(f"⚠️  no viewshed matched: {', '.join(missing)}")
        if not sites:
            print("⚠️  no site — scenario skipped")
            continue
        deployed = deployed_sites(config["regions"], paths)
        for name in sites:
            print(f"   {'≡' if name in deployed else '+'} {name}")
        build(label, sites, scenario_paths(spec, paths), config, zone, out_root)


if __name__ == "__main__":
    main()
