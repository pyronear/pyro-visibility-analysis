# One entry point for the terminal steps of the chain. Each target runs the
# script of the same step with `uv run python`; only the viewsheds need GDAL
# ≥ 3.13, which compute_viewsheds.py runs in Docker unless GDAL_VIEWSHED points
# at a native binary.
#
#   make viewsheds REGION=<region>
#   make analyse   REGION=<region> PICKS=20
#
# REGION defaults to config.py's. The two QGIS steps (build_qgis_project.py)
# are run from the QGIS Python console, not from here.

PY      := uv run python
REGION  ?=
ZONES   ?= dept
PICKS   ?= 10
FREEZE  ?=
PROJECT ?=
LIGHT_DEM ?= 50

R := $(if $(REGION),--region $(REGION))

.DEFAULT_GOAL := help
.PHONY: help gdal-check audit dem viewsheds summary prioritise scenarios \
        scenarios-md package analyse

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*## "} {printf "  make %-13s %s\n", $$1, $$2}'
	@echo "  Variables: REGION=<region> ZONES=$(ZONES) PICKS=$(PICKS) FREEZE=1 PROJECT=<x>.qgz"

gdal-check: ## Check gdal_viewshed (pulls the Docker image the first time)
	@$(PY) -m analysis_shape.gdal_viewshed

audit: ## Check declared site heights against Lidar HD
	$(PY) audit_sites.py $(R)

dem: ## Download the Lidar HD surface model (buffer = radius + 1 km)
	$(PY) experiments/generate_dem_fr.py $(R)

viewsheds: ## Compute the viewsheds, output.csv and the union
	$(PY) compute_viewsheds.py $(R)

summary: ## Areas, ranking, share per zone (ZONES)
	$(PY) summary.py $(R) --zones $(ZONES)

prioritise: ## Marginal gain and greedy ranking (ZONES, PICKS)
	$(PY) prioritise_sites.py $(R) --zones $(ZONES) --picks $(PICKS)

scenarios: ## Per-scenario camera-count rasters (FREEZE=1 before delivery)
	$(PY) scenario_layers.py $(R) --all $(if $(FREEZE),--figer)

scenarios-md: ## docs/scenarios-<region>.md
	$(PY) make_scenarios_md.py $(R)

package: ## Deliverable zip of PROJECT, with a light DEM (LIGHT_DEM metres)
	@test -n "$(PROJECT)" || { echo "❌ PROJECT=<project>.qgz is required"; exit 1; }
	$(PY) package_project.py $(PROJECT) --light-dem $(LIGHT_DEM)

analyse: viewsheds summary prioritise scenarios ## viewsheds → summary → prioritise → scenarios
