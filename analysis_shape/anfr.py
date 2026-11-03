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
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ANFR_DIR = REPO / "data" / "anfr"
DATASET_API = ("https://www.data.gouv.fr/api/1/datasets/"
               "donnees-sur-les-installations-radioelectriques-de-plus-de-5-watts-1/")
SUPPORTS = "SUP_SUPPORT.txt"
REFERENCES = ("SUP_NATURE.txt", "SUP_PROPRIETAIRE.txt", "SUP_EXPLOITANT.txt",
              "SUP_TYPE_ANTENNE.txt")

# Older than this, a warning: owners have moved since.
STALE_DAYS = 180


def latest_export():
    """The newest `data/anfr/<date>/` holding the supports, or None."""
    if not ANFR_DIR.is_dir():
        return None
    folders = sorted(p for p in ANFR_DIR.iterdir() if (p / SUPPORTS).exists())
    return folders[-1] if folders else None


def default_paths(anfr=None, refs=None):
    """(supports file, reference folder): the arguments, else the newest export.

    Exits with the command to run when there is no export at all, and warns
    when the newest one is old.
    """
    folder = latest_export()
    if anfr is None or refs is None:
        if folder is None:
            raise SystemExit(
                "❌ no ANFR export in data/anfr/ — fetch the latest one with: "
                "make anfr  (or uv run python fetch_anfr.py)")
        age = (datetime.date.today()
               - datetime.date.fromisoformat(folder.name[:10])).days
        if age > STALE_DAYS:
            print(f"⚠️  ANFR export of {folder.name}, {age} days old: owners may "
                  f"have changed since — make anfr fetches the latest")
    return (Path(anfr) if anfr else folder / SUPPORTS,
            Path(refs) if refs else folder)


def fetch_latest():
    """Download the latest export into data/anfr/<date>/ and return the folder.

    Nothing is downloaded when that folder is already complete.
    """
    with urllib.request.urlopen(DATASET_API, timeout=60) as response:
        resources = json.load(response)["resources"]
    data = max((r for r in resources if r["url"].endswith("export-etalab-data.zip")),
               key=lambda r: r["last_modified"])
    ref = max((r for r in resources if r["url"].endswith("export-etalab-ref.zip")),
              key=lambda r: r["last_modified"])
    folder = ANFR_DIR / data["last_modified"][:10]
    if all((folder / name).exists() for name in (SUPPORTS, *REFERENCES)):
        print(f"✅ {folder.relative_to(REPO)} is already the latest export")
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    for resource, wanted in ((data, (SUPPORTS,)), (ref, REFERENCES)):
        archive = folder / os.path.basename(resource["url"])
        print(f"   downloading {resource['title']} ({resource['url']})")
        urllib.request.urlretrieve(resource["url"], archive)
        with zipfile.ZipFile(archive) as zf:
            for name in wanted:
                zf.extract(name, folder)
        archive.unlink()
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
