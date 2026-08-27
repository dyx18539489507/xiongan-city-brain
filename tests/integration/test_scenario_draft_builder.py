import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from traffic_platform.scenario_engine.draft_builder import build_draft_scenario
from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.source_factory import (
    create_draft_record,
    prepare_planning_draft,
    save_draft,
    store_upload,
    update_draft,
)


@pytest.mark.integration
def test_reviewed_planning_draft_publishes_and_starts_real_sumo(tmp_path: Path) -> None:
    repository = Path.cwd()
    sumo_home = repository / ".tools" / "sumo"
    if not (sumo_home / "bin" / "sumo.exe").is_file():
        pytest.skip("workspace SUMO runtime is unavailable")
    configs = tmp_path / "scenarios" / "configs"
    configs.mkdir(parents=True)
    shutil.copy2(
        repository / "scenarios" / "configs" / "xiongan_rongdong_20.yaml",
        configs / "xiongan_rongdong_20.yaml",
    )
    draft_id = "draft-112233445566"
    record = create_draft_record(
        tmp_path,
        draft_id,
        "planning_file",
        {"original_name": "cross.geojson"},
    )
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[115.91, 39.05], [115.916, 39.05]],
                },
            },
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[115.913, 39.047], [115.913, 39.053]],
                },
            },
        ],
    }
    source = store_upload(
        tmp_path,
        draft_id,
        "cross.geojson",
        json.dumps(payload).encode(),
    )
    record["artifacts"] = {"source": source.name}
    save_draft(tmp_path, record)
    parsed = prepare_planning_draft(tmp_path, draft_id)
    reviewed = update_draft(
        tmp_path,
        draft_id,
        selected_intersection_ids=[parsed["preview"]["intersections"][0]["intersection_id"]],
        review_confirmed=True,
    )
    assert reviewed["validation"]["valid"] is True

    result = build_draft_scenario(
        tmp_path,
        sumo_home,
        draft_id=draft_id,
        scenario_id="planning-cross",
        display_name="规划十字路口",
        seed=42,
        traffic_demand={
            "source": "synthetic",
            "target_flow_veh_h": 600.0,
            "duration_s": 900.0,
            "od_pattern": "network_wide",
            "min_trip_distance_m": 0.0,
        },
    )

    assert result["status"] == "completed"
    assert result["selected_intersection_count"] == 1
    report = json.loads(Path(result["validation_report"]).read_text(encoding="utf-8"))
    assert report["sumo_smoke"]["passed"] is True
    assert report["checks"]["twenty_intersection_requirement"] == (
        "not_applied_user_selection_is_authoritative"
    )
    registry = json.loads(
        (tmp_path / "scenarios/generated/planning-cross/controlled_intersections.json").read_text(
            encoding="utf-8"
        )
    )
    selected = registry["intersections"][0]
    assert abs(selected["x"] - parsed["preview"]["intersections"][0]["x"]) > 1
    assert selected["parameter_provenance"] == "user_reviewed_source_draft"
    scene_path = Path(result["scene"]["output"])
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    assert scene["metadata"]["sceneId"] == "planning-cross"
    assert scene["metadata"]["counts"]["trafficLights"] == 1
    assert scene["coordinateSystem"]["sourceCrs"] == "SUMO local Cartesian"
    assert Path(result["scene"]["manifest"]).is_file()
    demand = result["traffic_demand"]
    assert demand["is_field_measured"] is False
    assert demand["requested"]["target_flow_veh_h"] == 600.0
    assert demand["requested"]["duration_s"] == 900.0
    assert demand["requested"]["od_pattern"] == "network_wide"
    assert demand["actual"]["routed_vehicle_count"] > 0
    demand_manifest = json.loads(
        (tmp_path / "scenarios/generated/planning-cross/traffic_demand_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert demand_manifest == demand
    sumocfg = Path(result["sumo_config"]).read_text(encoding="utf-8")
    assert '<end value="900.000"' in sumocfg
    assert '<gui-settings-file value="common.settings.xml"' in sumocfg
    assert '<tripinfo-output value="tripinfo.xml"' in sumocfg
    assert '<fcd-output value="traj.xml"' in sumocfg
    assert '<summary-output value="stats.xml"' in sumocfg
    gui_settings = ET.parse(
        tmp_path / "scenarios/generated/planning-cross/common.settings.xml"
    ).getroot()
    viewport = gui_settings.find("./viewport")
    assert viewport is not None
    assert viewport.get("zoom") == "100.00"
    assert viewport.get("angle") == "0.00"
    edges = gui_settings.find("./scheme/edges")
    assert edges is not None
    assert edges.get("showLinkDecals") == "0"
    assert edges.get("showLinkRules") == "1"
    assert edges.get("showDirection") == "0"
    background = gui_settings.find("./scheme/background")
    assert background is not None
    assert background.get("backgroundColor") == "white"
    assert gui_settings.find("./scheme").get("name") == "custom_1"
    vehicles = gui_settings.find("./scheme/vehicles")
    assert vehicles is not None
    assert vehicles.get("vehicleQuality") == "2"
    assert vehicles.get("vehicle_minSize") == "1.50"
    assert vehicles.get("vehicle_exaggeration") == "1.25"
    assert vehicles.get("vehicle_constantSize") == "0"
    generated_dir = tmp_path / "scenarios/generated/planning-cross"
    assert [path.name for path in generated_dir.glob("*.sumocfg")] == ["planning-cross.sumocfg"]
    assert not (generated_dir / "xiongan-presentation.view.xml").exists()
    assert not (generated_dir / "xiongan-diagnostic.view.xml").exists()
    assert not (generated_dir / "simple-shapes.view.xml").exists()
    assert not (generated_dir / "launch-sumo-diagnostics.cmd").exists()
    assert not (generated_dir / "launch-sumo-gui.cmd").exists()
    launcher = generated_dir / "launch-sumo-gui.vbs"
    assert launcher.is_file()
    launcher_text = launcher.read_text(encoding="ascii")
    assert "WScript.Shell" in launcher_text
    assert "shell.Run command, 1, False" in launcher_text
    generated_network = ET.parse(
        tmp_path / "scenarios/generated/planning-cross/rongdong.multimodal.net.xml"
    ).getroot()
    selected_id = parsed["preview"]["intersections"][0]["intersection_id"]
    selected_junction = next(
        item for item in generated_network.findall("junction") if item.get("id") == selected_id
    )
    assert selected_junction.get("type") == "traffic_light"
    assert any(item.get("id") == selected_id for item in generated_network.findall("tlLogic"))
    generated_config = (tmp_path / "scenarios/configs/planning-cross.yaml").read_text(
        encoding="utf-8"
    )
    assert "flow_veh_h: 600.0" in generated_config
    assert "connected_vehicle_penetration: 0.0" in generated_config
    loaded_config = ScenarioConfig.from_yaml(tmp_path / "scenarios/configs/planning-cross.yaml")
    assert loaded_config.simulation.duration_s == 900.0
    assert loaded_config.demand[0].flow_veh_h == 600.0
