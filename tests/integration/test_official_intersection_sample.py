"""Artifact-level integration checks for the two organizer sample projects."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


@pytest.mark.integration
@pytest.mark.parametrize(
    ("demo_id", "expected_totals", "expected_cycles", "expected_arm_lengths"),
    [
        (
            13,
            {"am_peak": 3087, "offpeak": 2750, "pm_peak": 3786},
            {152, 147},
            {"E": 2996.25, "W": 537.09, "N": 472.18},
        ),
        (
            14,
            {"am_peak": 3406, "offpeak": 2792, "pm_peak": 3644},
            {75},
            {"E": 156.92, "N": 191.56, "S": 45.06},
        ),
    ],
)
def test_generated_official_project_is_complete_and_traceable(
    demo_id: int,
    expected_totals: dict[str, int],
    expected_cycles: set[int],
    expected_arm_lengths: dict[str, float],
) -> None:
    root = (
        Path(__file__).resolve().parents[2]
        / "scenarios"
        / "generated"
        / "official_20_independent"
        / f"demo_{demo_id}"
    )
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((root / "validation.json").read_text(encoding="utf-8"))

    assert manifest["provenance_class"] == "organizer_excel_png_plus_osm_modeled_sumo"
    assert validation["actual_sumo_run"] is True
    assert validation["structurally_valid"] is True
    assert len(manifest["source_files"]) >= 3
    assert {
        arm: evidence["measured_length_m"]
        for arm, evidence in manifest["arm_geometry"].items()
    } == expected_arm_lengths
    assert {
        evidence["modeled_length_m"] for evidence in manifest["arm_geometry"].values()
    } == {250.0}
    assert {
        evidence["modeling_adjustment"]["type"]
        for evidence in manifest["arm_geometry"].values()
    } == {"standardized_isolated_intersection_boundary"}
    view_settings_path = root / "simple-shapes.view.xml"
    assert view_settings_path.is_file()
    view_settings = ET.parse(view_settings_path).getroot()
    assert view_settings.find("./scheme").get("name") == "competition simple shapes"  # type: ignore[union-attr]
    assert view_settings.find("./scheme/vehicles").get("vehicleQuality") == "2"  # type: ignore[union-attr]

    cycle_values: set[int] = set()
    for profile, expected in expected_totals.items():
        route_path = root / f"demo_{demo_id}_{profile}.rou.xml"
        config_path = root / f"demo_{demo_id}_{profile}.sumocfg"
        net_path = root / f"demo_{demo_id}_{profile}.net.xml"
        assert route_path.is_file() and config_path.is_file() and net_path.is_file()
        route_root = ET.parse(route_path).getroot()
        assert sum(int(flow.get("number", "0")) for flow in route_root.findall("flow")) == expected
        assert route_root.find("vType").get("color") == "1,1,0"  # type: ignore[union-attr]
        config_root = ET.parse(config_path).getroot()
        assert config_root.find("./gui_only/delay").get("value") == "300"  # type: ignore[union-attr]
        assert config_root.find("./input/gui-settings-file").get("value") == (  # type: ignore[union-attr]
            "simple-shapes.view.xml"
        )
        net_root = ET.parse(net_path).getroot()
        logic = next(element for element in net_root.findall("tlLogic") if element.get("id") == "J")
        cycle_values.add(sum(int(phase.get("duration", "0")) for phase in logic.findall("phase")))
        assert validation["profiles"][profile]["demand_conservation"] is True
        assert validation["profiles"][profile]["collisions"] == 0
        assert validation["profiles"][profile]["teleports"] == 0
    assert cycle_values == expected_cycles


@pytest.mark.integration
def test_all_platform_passenger_classes_use_the_theme_color() -> None:
    root = Path(__file__).resolve().parents[2]
    scenario_source = root / "scenarios" / "source" / "xiongan_rongdong_20"
    vtypes = ET.parse(scenario_source / "vtypes.add.xml")
    passenger_types = [
        vehicle_type
        for vehicle_type in vtypes.getroot().findall("vType")
        if vehicle_type.get("vClass") == "passenger"
    ]
    assert passenger_types
    assert {vehicle_type.get("color") for vehicle_type in passenger_types} == {"1,1,0"}
    scenario_config = ET.parse(scenario_source / "xiongan_rongdong_20.sumocfg").getroot()
    delay = scenario_config.find("./gui_only/delay")
    assert delay is not None
    assert delay.get("value") == "300"
    gui_settings_name = scenario_config.find("./input/gui-settings-file")
    assert gui_settings_name is not None
    assert gui_settings_name.get("value") == "simple-shapes.view.xml"
    gui_settings = ET.parse(scenario_source / "simple-shapes.view.xml").getroot()
    assert gui_settings.find("./scheme/vehicles").get("vehicleQuality") == "2"  # type: ignore[union-attr]

    generated_scenario = root / "scenarios" / "generated" / "xiongan_rongdong_20"
    generated_configs = sorted(generated_scenario.glob("*.sumocfg"))
    assert len(generated_configs) == 8
    for generated_config in generated_configs:
        generated_root = ET.parse(generated_config).getroot()
        gui_settings_ref = generated_root.find("./input/gui-settings-file")
        assert gui_settings_ref is not None
        assert gui_settings_ref.get("value") == "simple-shapes.view.xml"
    generated_gui_settings = ET.parse(
        generated_scenario / "simple-shapes.view.xml"
    ).getroot()
    assert generated_gui_settings.find("./scheme/vehicles").get(  # type: ignore[union-attr]
        "vehicleQuality"
    ) == "2"


@pytest.mark.integration
def test_all_20_official_projects_cover_sumo_links_and_preserve_gui_theme() -> None:
    """Every generated signal state must cover even unused netconvert links."""

    root = (
        Path(__file__).resolve().parents[2]
        / "scenarios"
        / "generated"
        / "official_20_independent"
    )
    for demo_id in range(1, 21):
        project = root / f"demo_{demo_id}"
        manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
        validation = json.loads((project / "validation.json").read_text(encoding="utf-8"))
        assert validation["actual_sumo_run"] is True
        assert validation["structurally_valid"] is True
        modeled_lengths = {
            geometry.get("modeled_length_m", geometry["measured_length_m"])
            for geometry in manifest["arm_geometry"].values()
        }
        if demo_id <= 4:
            assert modeled_lengths != {250.0}
            assert {
                geometry.get("modeling_adjustment")
                for geometry in manifest["arm_geometry"].values()
            } == {None}
        else:
            assert modeled_lengths == {250.0}
            assert {
                geometry["modeling_adjustment"]["type"]
                for geometry in manifest["arm_geometry"].values()
            } == {"standardized_isolated_intersection_boundary"}
        view = ET.parse(project / "simple-shapes.view.xml").getroot()
        assert view.find("./scheme/vehicles").get("vehicleQuality") == "2"  # type: ignore[union-attr]

        for profile in ("am_peak", "offpeak", "pm_peak"):
            expected = manifest["workbook_interpretation"][profile]["demand_total"]
            route_root = ET.parse(project / f"demo_{demo_id}_{profile}.rou.xml").getroot()
            assert route_root.find("vType").get("color") == "1,1,0"  # type: ignore[union-attr]
            assert sum(
                int(flow.get("number", "0")) for flow in route_root.findall("flow")
            ) == expected

            config_root = ET.parse(
                project / f"demo_{demo_id}_{profile}.sumocfg"
            ).getroot()
            assert config_root.find("./gui_only/delay").get("value") == "300"  # type: ignore[union-attr]
            assert config_root.find("./input/gui-settings-file").get("value") == (  # type: ignore[union-attr]
                "simple-shapes.view.xml"
            )

            net_root = ET.parse(project / f"demo_{demo_id}_{profile}.net.xml").getroot()
            indices = [
                int(connection.get("linkIndex", "-1"))
                for connection in net_root.findall("connection")
                if connection.get("tl") == "J"
            ]
            assert indices
            logic = next(
                element
                for element in net_root.findall("tlLogic")
                if element.get("id") == "J"
            )
            assert {
                len(phase.get("state", "")) for phase in logic.findall("phase")
            } == {max(indices) + 1}
            profile_validation = validation["profiles"][profile]
            assert profile_validation["demand_conservation"] is True
            assert profile_validation["collisions"] == 0
            assert profile_validation["teleports"] == 0
