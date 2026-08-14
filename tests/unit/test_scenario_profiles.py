"""S01-S07 profile completeness and disturbance validation."""

from pathlib import Path

from traffic_platform.scenario_engine.profiles import ScenarioProfileSet


def test_all_phase1_profiles_are_machine_readable() -> None:
    profiles = ScenarioProfileSet.from_yaml(
        Path("scenarios/configs/presets/S01-S07.yaml")
    )
    assert {profile.code for profile in profiles.profiles} == {
        "S01",
        "S02",
        "S03",
        "S04",
        "S05",
        "S06",
        "S07",
    }
    assert profiles.get("S04").disturbances[0].type == "roadwork"
    assert profiles.get("S07").communication_profile == "N8"


def test_profiles_convert_to_runtime_events_without_faking_cloud_as_sumo() -> None:
    profiles = ScenarioProfileSet.from_yaml(
        Path("scenarios/configs/presets/S01-S07.yaml")
    )

    roadwork = profiles.get("S04").physical_disturbances()
    assert len(roadwork) == 1
    assert roadwork[0].event_id == "s04_roadwork_600_0"
    assert roadwork[0].type == "roadwork"
    assert roadwork[0].simulation_time_s == 600.0
    assert profiles.get("S07").physical_disturbances() == []
    assert profiles.get("S07").cloud_outage_window() == (600.0, 60.0)


def test_event_profile_preserves_validated_demand_multiplier() -> None:
    profiles = ScenarioProfileSet.from_yaml(
        Path("scenarios/configs/presets/S01-S07.yaml")
    )

    dispersal = profiles.get("S03").physical_disturbances()[0]
    assert dispersal.type == "event_dispersal"
    assert dispersal.parameters["flow_multiplier"] == 2.5
