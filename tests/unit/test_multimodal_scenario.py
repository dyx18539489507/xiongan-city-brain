"""Evidence checks for the derived full-network multimodal scenario."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from traffic_platform.scenario_engine.multimodal import (
    audit_multimodal_network,
)

OUTPUT = Path("scenarios/generated/xiongan_rongdong_20")


def test_multimodal_network_has_real_active_mode_facilities() -> None:
    audit = audit_multimodal_network(
        OUTPUT / "rongdong.multimodal.net.xml",
        OUTPUT / "controlled_intersections.json",
    )
    assert audit["pedestrian_lane_count"] > 0
    assert audit["bicycle_lane_count"] > 0
    assert audit["crossing_edge_count"] > 0
    assert audit["walking_area_edge_count"] > 0
    assert audit["selected_with_conditional_parallel_pedestrian_signal"] >= 10
    assert audit["all_crossing_enabled_selected_use_conditional_parallel"] is True
    assert audit["all_crossing_enabled_selected_meet_minimum_green"] is True


def test_multimodal_demand_is_simultaneous_and_not_field_claimed() -> None:
    manifest = json.loads((OUTPUT / "multimodal_demand_manifest.json").read_text(encoding="utf-8"))
    assert all(
        manifest["participant_counts"][name] > 0
        for name in ("bicycle", "electric_bicycle", "pedestrian")
    )
    assert manifest["network_scope"] == "complete_rongdong_osm_network_not_cropped"
    assert manifest["field_calibrated"] is False


def test_active_modes_use_recognizable_gui_shapes() -> None:
    """The demo must render vulnerable road users as people and bicycles."""

    additional = ET.parse(OUTPUT / "vtypes.add.xml").getroot()
    types = {item.get("id"): item for item in additional.findall("vType")}
    assert types["bicycle"].get("guiShape") == "bicycle"
    assert types["electric_bicycle"].get("guiShape") == "bicycle"
    assert types["pedestrian_adult"].get("guiShape") == "pedestrian"
    assert types["pedestrian_elderly"].get("guiShape") == "pedestrian"
    assert types["pedestrian_adult"].get("imgFile") == "pedestrian_adult.png"
    assert types["pedestrian_elderly"].get("imgFile") == "pedestrian_elderly.png"
    assert (OUTPUT / "pedestrian_adult.png").is_file()
    assert (OUTPUT / "pedestrian_elderly.png").is_file()

    view = ET.parse(OUTPUT / "simple-shapes.view.xml").getroot()
    vehicles = view.find("./scheme/vehicles")
    persons = view.find("./scheme/persons")
    assert vehicles is not None
    assert persons is not None
    assert vehicles.get("vehicleQuality") == "2"
    assert float(vehicles.get("vehicle_minSize", "0")) >= 1.0
    assert persons.get("personQuality") == "3"
    assert float(persons.get("person_exaggeration", "0")) <= 1.5
    assert persons.get("person_constantSize") == "0"
