# Example region (fictitious)

This folder is a template: the sites are made up (the first one sits on the
Eiffel Tower, the others at random points in Seine-et-Marne) and describe no
real deployment.

To start a new region:

```bash
cp -R data/example data/<my-region>
```

then set `REGION = "<my-region>"` in `config.py`, and adapt:

- `sites.csv` — `;`-separated, columns `Name;Latitude;Longitude;Owner;Height;Status`.
  `Height` is the camera height **above the ground** (never an NGF altitude);
  `Status` is `EN PLACE` for a camera already installed, empty otherwise.
- `scenarios.json` — regions whose viewsheds are read, zone of interest (`dept`,
  `old` or a `zones/<name>.gpkg`), `gestionnaires` table (access cost per owner)
  and scenarios. See the main README, § « Scenarios ».

Optional, only when building `sites.csv` from a partner spreadsheet with
`resolve_points_hauts.py`:

- `commune_alias.json` — `{"OLD NAME": "MERGED NAME"}`. Partner lists often keep
  the name a commune had before a merger (commune nouvelle), or a short form,
  while the geo API only knows the current name. Unmatched rows show up as
  « commune not found » in `resolution.csv`; add them here and rerun.
- `sites_installes.json` — cameras already installed, whose position overrides
  the automatic resolution.

Everything the chain generates here (DEM, `output/`, `zones/`, JSON caches)
stays out of the repository.
