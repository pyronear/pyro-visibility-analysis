"""One spelling of a site name, shared by every script.

A name from `sites.csv` becomes a file name (`viewshed_<Name>.tif`), then is
read back from that file name by every downstream script and joined to
`sites.csv` again. Two things break that round trip:

  * macOS stores file names in NFD while CSVs are NFC;
  * a '/' or '>' in an ANFR address (« A6 >Paris/Aire de Service ») is illegal
    in a path, so the viewshed must be written under a cleaned name.

Cleaning in one script and joining on the raw name elsewhere lost such sites
silently: no area in summary.py, « no viewshed » in prioritise_sites.py, and an
installed camera dropped from the scenarios' baseline. Every read of `Name`
goes through `site_name()` instead, so the file name and the CSV name agree.
"""

import re
import unicodedata

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')


def site_name(value):
    """NFC, stripped, path-safe. Idempotent, so file names may pass through it too."""
    return _ILLEGAL.sub("-", unicodedata.normalize("NFC", str(value)).strip())
