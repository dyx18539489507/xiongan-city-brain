PYTHON ?= python
PIP := $(PYTHON) -m pip
CLI := $(PYTHON) -m traffic_platform.cli
WEB := apps/web-dashboard

.PHONY: bootstrap validate generate-demo-scenario generate-3d-scene generate-official-sample generate-official-all up down demo demo-gui \
	benchmark benchmark-smoke fault-demo report test lint e2e

bootstrap:
	$(PIP) install -e ".[dev]"
	cd $(WEB) && npm ci

validate:
	$(CLI) validate
	$(CLI) generate-demo-scenario --verify-only
	cd $(WEB) && npm run build

generate-demo-scenario:
	$(CLI) official-inventory
	$(CLI) transfer-parameters
	$(CLI) generate-demo-scenario

generate-3d-scene:
	$(CLI) generate-3d-scene

generate-official-sample:
	$(CLI) generate-official-intersections --demo-ids 13 14

generate-official-all:
	$(CLI) generate-official-intersections --demo-ids 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 --jobs 4
	$(CLI) audit-official-intersections --output outputs/official_20_audit

up:
	COMPOSE_BAKE=false DOCKER_BUILDKIT=0 docker compose --env-file $${ENV_FILE:-.env.example} up -d --build

down:
	docker compose --env-file $${ENV_FILE:-.env.example} down

demo:
	$(CLI) demo --algorithm coordinated-max-pressure --duration 30 --output results/demo

demo-gui:
	$(CLI) demo --algorithm coordinated-max-pressure --duration 120 --gui --output results/demo-gui

benchmark:
	$(CLI) benchmark --duration 1800 --seeds 11 23 37 41 59 --output results/benchmark

benchmark-smoke:
	$(CLI) benchmark --duration 20 --seeds 11 --output results/benchmark-smoke

fault-demo:
	$(CLI) demo --algorithm coordinated-max-pressure --duration 70 --cloud-outage --accelerate-disturbances --output results/fault-demo

report:
	$(CLI) latest-report --output results/report-latest

test:
	$(PYTHON) -m pytest
	cd $(WEB) && npm test

lint:
	$(PYTHON) -m ruff check src tests deployment
	$(PYTHON) -m mypy src
	cd $(WEB) && npm run build

e2e:
	$(PYTHON) -m pytest tests/e2e tests/chaos -m "e2e or chaos"
	cd $(WEB) && npm run e2e
