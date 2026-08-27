from __future__ import annotations

import os
import sys

import pytest

from traffic_platform.scenario_engine import draft_builder
from traffic_platform.scenario_engine.draft_builder import (
    AUTOMATIC_MIN_TRIP_DISTANCES_M,
    AUTOMATIC_TARGET_FLOW_MAX_VEH_H,
    AUTOMATIC_TARGET_FLOW_MIN_VEH_H,
    AUTOMATIC_TARGET_FLOW_STEP_VEH_H,
    OD_PATTERN_FRINGE_FACTORS,
    OSM_SIMULATION_DURATION_S,
    automatic_traffic_demand,
    normalize_traffic_demand,
    resolve_traffic_demand,
)


def test_automatic_demand_is_reproducible_and_sufficiently_populated() -> None:
    demand = automatic_traffic_demand(42)

    assert demand == automatic_traffic_demand(42)
    assert demand["duration_s"] == OSM_SIMULATION_DURATION_S
    assert (
        AUTOMATIC_TARGET_FLOW_MIN_VEH_H
        <= demand["target_flow_veh_h"]
        <= AUTOMATIC_TARGET_FLOW_MAX_VEH_H
    )
    assert (
        demand["target_flow_veh_h"] - AUTOMATIC_TARGET_FLOW_MIN_VEH_H
    ) % AUTOMATIC_TARGET_FLOW_STEP_VEH_H == 0
    assert demand["od_pattern"] in OD_PATTERN_FRINGE_FACTORS
    assert demand["min_trip_distance_m"] in AUTOMATIC_MIN_TRIP_DISTANCES_M


def test_osm_demand_always_uses_three_minutes() -> None:
    demand = resolve_traffic_demand(
        "osm_bbox",
        42,
        {
            "source": "synthetic",
            "target_flow_veh_h": 2400,
            "duration_s": 900,
            "od_pattern": "network_wide",
            "min_trip_distance_m": 100,
        },
    )

    assert demand["duration_s"] == 180.0


def test_three_minutes_is_the_shortest_supported_generated_duration() -> None:
    assert normalize_traffic_demand({"duration_s": 180})["duration_s"] == 180.0

    with pytest.raises(ValueError, match="between 180 and 7200"):
        normalize_traffic_demand({"duration_s": 179})


def test_osm_route_generation_retries_until_eighty_percent_threshold(
    tmp_path,
    monkeypatch,
) -> None:
    sumo_home = tmp_path / "sumo"
    random_trips = sumo_home / "tools" / "randomTrips.py"
    random_trips.parent.mkdir(parents=True)
    random_trips.write_text("# test placeholder\n", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    network = output / "network.net.xml"
    network.write_text("<net/>\n", encoding="utf-8")
    monkeypatch.setattr(draft_builder, "_network_diagonal_m", lambda _network: 100.0)

    def fake_run(command, cwd, timeout=300):
        del timeout
        minimum_distance = float(command[command.index("--min-distance") + 1])
        count = 90 if minimum_distance == 0 else 10
        vehicles = "".join(f'<vehicle id="v{index}"/>' for index in range(count))
        trips = "".join(f'<trip id="t{index}"/>' for index in range(count))
        (cwd / command[command.index("-r") + 1]).write_text(
            f"<routes>{vehicles}</routes>", encoding="utf-8"
        )
        (cwd / "trips.trips.xml").write_text(
            f"<routes>{trips}</routes>", encoding="utf-8"
        )

    monkeypatch.setattr(draft_builder, "_run", fake_run)

    _route_file, _manifest, summary = draft_builder._generate_routes(
        tmp_path,
        sumo_home,
        output,
        network,
        42,
        {
            "source": "synthetic",
            "target_flow_veh_h": 1800,
            "duration_s": 180,
            "od_pattern": "boundary_dominant",
            "min_trip_distance_m": 150,
        },
        minimum_route_ratio=0.8,
    )

    assert summary["derived"]["minimum_routed_vehicle_count"] == 72
    assert summary["derived"]["applied_min_trip_distance_m"] == 0.0
    assert len(summary["generation_attempts"]) == 4
    assert summary["actual"]["routed_vehicle_count"] == 90
    assert summary["acceptance"]["accepted"] is True


def test_random_trips_uses_the_packaged_sumo_bin_without_sumo_home(
    tmp_path,
    monkeypatch,
) -> None:
    random_trips = tmp_path / "portable-sumo" / "tools" / "randomTrips.py"
    random_trips.parent.mkdir(parents=True)
    random_trips.write_text("# test placeholder\n", encoding="utf-8")
    captured: dict[str, str] = {}

    def fake_subprocess_run(*_args, **kwargs):
        captured.update(kwargs["env"])
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setenv("SUMO_HOME", "C:/system-sumo-that-must-not-be-used")
    monkeypatch.setattr(draft_builder.subprocess, "run", fake_subprocess_run)

    draft_builder._run([sys.executable, str(random_trips)], tmp_path)

    assert "SUMO_HOME" not in captured
    assert captured["PATH"].split(os.pathsep)[0] == str(
        (tmp_path / "portable-sumo" / "bin").resolve()
    )


def test_automatic_flow_candidates_keep_random_target_and_populated_floor() -> None:
    assert draft_builder._automatic_flow_candidates(2940) == [
        2940.0,
        2400.0,
        1800.0,
        1500.0,
        1200.0,
    ]
    assert draft_builder._automatic_flow_candidates(1800) == [1800.0, 1500.0, 1200.0]


def test_runtime_acceptance_rejects_gridlock_and_accepts_moving_tail(tmp_path) -> None:
    gridlocked = tmp_path / "gridlocked.xml"
    gridlocked.write_text(
        """<summary>
  <step loaded="100" inserted="90" running="80" waiting="10" arrived="10" halting="78" meanSpeed="0.2"/>
  <step loaded="100" inserted="90" running="80" waiting="10" arrived="10" halting="79" meanSpeed="0.1"/>
</summary>
""",
        encoding="utf-8",
    )
    moving = tmp_path / "moving.xml"
    moving.write_text(
        """<summary>
  <step loaded="60" inserted="60" running="24" waiting="0" arrived="36" halting="14" meanSpeed="2.4"/>
  <step loaded="60" inserted="60" running="22" waiting="0" arrived="38" halting="13" meanSpeed="1.2"/>
</summary>
""",
        encoding="utf-8",
    )

    rejected = draft_builder._runtime_acceptance_from_summary(gridlocked)
    accepted = draft_builder._runtime_acceptance_from_summary(moving)

    assert rejected["accepted"] is False
    assert rejected["last_30s_halting_ratio"] > 0.9
    assert accepted["accepted"] is True
    assert accepted["inserted_vehicle_count"] == 60
