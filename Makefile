#
# Kotoba — JLPT Flash Cards
#
# `make help` lists every target. Python commands run through the local
# virtualenv if one exists, and fall back to `python3` otherwise, so a
# contributor with either setup gets the same behaviour.
#

SHELL := /bin/bash
.DEFAULT_GOAL := help

VENV       ?= .venv
PYTHON     ?= $(if $(wildcard $(VENV)/bin/python),$(VENV)/bin/python,python3)
KOTOBA     ?= $(PYTHON) -m kotoba.cli
TRMNLP     ?= ./bin/trmnlp
SITE       ?= site
DIST       ?= dist
TRMNLP_IMAGE ?= kotoba/trmnlp:latest

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-18s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------

.PHONY: setup
setup: ## Install locked development dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip
	$(VENV)/bin/python -m pip install -e '.[dev,import]'
	@echo "Done. Next: make fetch-sources && make import"

.PHONY: trmnlp-image
trmnlp-image: ## Build the trmnlp image with Japanese fonts (needed for PNGs)
	docker build -f Dockerfile.trmnlp -t $(TRMNLP_IMAGE) .

# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------

.PHONY: fetch-sources
fetch-sources: ## Download third-party corpora into data/raw (the only network step)
	$(PYTHON) scripts/fetch_sources.py

.PHONY: import
import: ## Rebuild the canonical corpus from data/raw
	$(KOTOBA) import --config config/sources.yml

.PHONY: import-demo
import-demo: ## Build the small demo corpus into data/demo/vocabulary
	$(KOTOBA) import --config config/sources.demo.yml \
		--vocabulary-dir data/demo/vocabulary --review-dir data/demo/review

.PHONY: validate
validate: ## Validate corpus, provenance and schemas
	$(KOTOBA) validate

.PHONY: notice
notice: ## Regenerate NOTICE.md from data/sources.yml
	$(KOTOBA) validate --write-notice

# --------------------------------------------------------------------------
# Lint and tests
# --------------------------------------------------------------------------

# Lint only. The repository is not `ruff format`-clean and is not meant to be:
# comments and long strings are wrapped by hand for readability.
.PHONY: lint
lint: ## Lint the Python with ruff
	$(PYTHON) -m ruff check kotoba scripts tests

.PHONY: test
test: ## Run the Python test suite
	$(PYTHON) -m pytest

# --------------------------------------------------------------------------
# Site
# --------------------------------------------------------------------------

.PHONY: build-site
build-site: ## Generate the full static Pages site into site/
	$(KOTOBA) build-site --output $(SITE)

.PHONY: validate-site
validate-site: ## Validate the generated static API
	$(KOTOBA) validate-site --site $(SITE)

.PHONY: manifest
manifest: ## Summarise the generated build manifest
	$(KOTOBA) manifest --site $(SITE)

# Builds the full slot space, not a truncated one: the polling URL resolves
# `slot mod 4096` from the wall clock, so a short build 404s on almost every
# poll. All 20,480 files take about two seconds.
.PHONY: preview
preview: ## Build the site and start trmnlp against it
	$(KOTOBA) build-site --output $(SITE)
	@echo "Preview on http://localhost:4567 — Ctrl-C to stop"
	docker compose up --build

.PHONY: preview-down
preview-down: ## Stop the preview stack
	docker compose down

# --------------------------------------------------------------------------
# Plugin
# --------------------------------------------------------------------------

.PHONY: lint-plugin
lint-plugin: ## Run trmnlp lint
	$(TRMNLP) lint

.PHONY: render
render: ## Render the reference fixture to HTML and PNG
	$(PYTHON) scripts/render_fixtures.py --png --only full_reference

.PHONY: render-fixtures
render-fixtures: ## Render every visual fixture to HTML and PNG
	$(PYTHON) scripts/render_fixtures.py --png

.PHONY: render-html
render-html: ## Render every visual fixture to HTML only (no browser needed)
	$(PYTHON) scripts/render_fixtures.py

.PHONY: render-devices
render-devices: ## Render the reference fixture on TRMNL's own panel sizes
	$(PYTHON) scripts/render_devices.py --png

.PHONY: render-devices-all
render-devices-all: ## Render on every viewport in the device table
	$(PYTHON) scripts/render_devices.py --png --all

.PHONY: package
package: ## Produce a flat private-plugin ZIP in dist/
	$(PYTHON) scripts/package_plugin.py

.PHONY: configure
configure: ## Point settings.yml at your GitHub Pages deployment
	$(PYTHON) scripts/configure_repo.py

# --------------------------------------------------------------------------
# Housekeeping
# --------------------------------------------------------------------------

.PHONY: check
check: lint validate test build-site validate-site render-html ## Everything CI runs, locally
	@echo "All checks passed."

.PHONY: clean
clean: ## Remove generated output
	rm -rf $(SITE) $(DIST) _build .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

.PHONY: clean-raw
clean-raw: ## Also remove downloaded third-party sources
	find data/raw -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +
