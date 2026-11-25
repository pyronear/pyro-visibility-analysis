"""The ANFR register of radio supports: where it lives, how to read it.

data.gouv.fr publishes it monthly, « Données sur les installations
radioélectriques de plus de 5 watts »: a data zip (`SUP_SUPPORT.txt`, one row
per station on a support) and a reference zip (`SUP_NATURE.txt`,
`SUP_PROPRIETAIRE.txt`…). `fetch_anfr.py` downloads the latest pair into
`data/anfr/<date>/`, and the scripts read the newest folder there by default.

Freshness matters. The owner type `TPO_ID` is updated as tower companies buy
operators' pylons: an export two years old had no support at all under
HIVORY or TOTEM, where the current one lists thousands — the same pylons,
then still filed under SFR, Orange, or the landowner (« DDE » for a pylon on
a motorway junction). Read stale, such a pylon passes for public.

The former `SUP_SUPPORT.geojson` export is still read when passed with
`--anfr`, for regions built from it.
"""

import csv
import datetime
import json
import os
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ANFR_DIR = REPO / "data" / "anfr"
DATASET_API = ("https://www.data.gouv.fr/api/1/datasets/"
               "donnees-sur-les-installations-radioelectriques-de-plus-de-5-watts-1/")
SUPPORTS = "SUP_SUPPORT.txt"
# The reference tables the scripts read; the zip holds others.
REFERENCES = ("SUP_NATURE.txt", "SUP_PROPRIETAIRE.txt")

# Older than this, a warning: owners have moved since.
STALE_DAYS = 180


def has_references(folder):
    return all((Path(folder) / name).exists() for name in REFERENCES)


def latest_export():
    """The newest complete `data/anfr/<date>/`, or None.

    Complete means the supports and the reference tables: a folder left
    half-filled by an interrupted download is not an export.
    """
    if not ANFR_DIR.is_dir():
        return None
    folders = sorted(p for p in ANFR_DIR.iterdir()
                     if not p.name.startswith(".")
                     and (p / SUPPORTS).exists() and has_references(p))
    return folders[-1] if folders else None


def default_supports(anfr=None):
    """The supports file: the argument, else the newest export's.

    Exits with the command to run when there is no export at all, and warns
    when the newest one is old.
    """
    if anfr is not None:
        return Path(anfr)
    folder = latest_export()
    if folder is None:
        raise SystemExit(
            "❌ no ANFR export in data/anfr/ — fetch the latest one with: "
            "make anfr  (or uv run python fetch_anfr.py)")
    age = (datetime.date.today()
           - datetime.date.fromisoformat(folder.name[:10])).days
    if age > STALE_DAYS:
        print(f"⚠️  ANFR export of {folder.name}, {age} days old: owners may "
              f"have changed since — make anfr fetches the latest")
    return folder / SUPPORTS


def default_paths(anfr=None, refs=None):
    """(supports file, reference folder).

    The reference tables default to the folder of the supports file, so both
    come from the same export. A supports file standing alone (a former
    .geojson) falls back on the newest export's tables, and says so.
    """
    anfr = default_supports(anfr)
    if refs is not None:
        return anfr, Path(refs)
    if has_references(anfr.parent):
        return anfr, anfr.parent
    folder = latest_export()
    if folder is None:
        raise SystemExit(
            f"❌ no {' / '.join(REFERENCES)} next to {anfr}: pass --refs, or "
            f"fetch an export with: make anfr")
    print(f"⚠️  no reference tables next to {anfr.name}: read from the "
          f"{folder.name} export — pass --refs to choose another")
    return anfr, folder


def fetch_latest():
    """Download the latest export into data/anfr/<date>/ and return the folder.

    Nothing is downloaded when that folder is already complete. The archives
    are downloaded and unpacked in a temporary folder, and the files moved in
    only once all are there: an interrupted run leaves no half-filled export.
    """
    with urllib.request.urlopen(DATASET_API, timeout=60) as response:
        resources = json.load(response)["resources"]
    data = max((r for r in resources if r["url"].endswith("export-etalab-data.zip")),
               key=lambda r: r["last_modified"])
    ref = max((r for r in resources if r["url"].endswith("export-etalab-ref.zip")),
              key=lambda r: r["last_modified"])
    folder = ANFR_DIR / data["last_modified"][:10]
    if (folder / SUPPORTS).exists() and has_references(folder):
        print(f"✅ {folder.relative_to(REPO)} is already the latest export")
        return folder
    ANFR_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=ANFR_DIR, prefix=".partial-") as tmp:
        tmp = Path(tmp)
        for resource, wanted in ((data, (SUPPORTS,)), (ref, REFERENCES)):
            archive = tmp / os.path.basename(resource["url"])
            print(f"   downloading {resource['title']} ({resource['url']})")
            urllib.request.urlretrieve(resource["url"], archive)
            with zipfile.ZipFile(archive) as zf:
                for name in wanted:
                    zf.extract(name, tmp)
        folder.mkdir(exist_ok=True)
        # The supports last: their presence is what the tables are checked with.
        for name in (*REFERENCES, SUPPORTS):
            os.replace(tmp / name, folder / name)
    print(f"✅ {folder.relative_to(REPO)}")
    return folder


def load_reference_table(path):
    table = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
        if ";" in line:
            key, label = line.split(";", 1)
            table[key.strip()] = label.strip()
    return table


def _dms(degrees, minutes, seconds, hemisphere):
    value = int(degrees) + int(minutes) / 60 + int(seconds) / 3600
    return -value if hemisphere in ("S", "W") else value


def _number(value):
    value = str(value or "").strip().replace(",", ".")
    return float(value) if value else None


def read_supports(path):
    """One dict per row (per station: a support appears once per station).

    Keys: SUP_ID, lat, lon, NAT_ID, TPO_ID, SUP_NM_HAUT (float or None),
    COM_CD_INSEE and the ADR_LB_* address fields, all as strings otherwise.
    """
    path = Path(path)
    if path.suffix == ".geojson":
        # One feature per line: streamed, not loaded whole.
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip().rstrip(",")
                if not line.startswith('{ "type": "Feature"'):
                    continue
                feature = json.loads(line)
                row = {k: ("" if v is None else str(v))
                       for k, v in feature["properties"].items()}
                row["lon"], row["lat"] = feature["geometry"]["coordinates"]
                row["SUP_NM_HAUT"] = _number(row.get("SUP_NM_HAUT"))
                yield row
        return
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            row["lat"] = _dms(row["COR_NB_DG_LAT"], row["COR_NB_MN_LAT"],
                              row["COR_NB_SC_LAT"], row["COR_CD_NS_LAT"])
            row["lon"] = _dms(row["COR_NB_DG_LON"], row["COR_NB_MN_LON"],
                              row["COR_NB_SC_LON"], row["COR_CD_EW_LON"])
            row["SUP_NM_HAUT"] = _number(row.get("SUP_NM_HAUT"))
            yield row
