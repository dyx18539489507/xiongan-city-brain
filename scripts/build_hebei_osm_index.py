"""Build the fixed local Hebei OSM road index once; no update task is installed."""

from __future__ import annotations

from pathlib import Path

from traffic_platform.scenario_engine.source_factory import (
    build_local_osm_index,
)

if __name__ == "__main__":
    workspace = Path(__file__).resolve().parents[1]
    output = build_local_osm_index(workspace)
    print(output)
