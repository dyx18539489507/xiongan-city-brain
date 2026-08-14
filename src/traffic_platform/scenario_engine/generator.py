"""Reproducible build and validation for the Rongdong 20-intersection scenario."""

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from traffic_platform.scenario_engine.demand_generation import (
    demand_summary,
    generate_routes,
    prepare_demand_network,
)
from traffic_platform.scenario_engine.functional_zones import build_functional_zones
from traffic_platform.scenario_engine.intersection_inventory import (
    build_intersection_inventory,
    write_intersection_inventory,
)
from traffic_platform.scenario_engine.manifest import build_manifest
from traffic_platform.scenario_engine.models import ScenarioConfig
from traffic_platform.scenario_engine.multimodal import (
    add_active_mode_types,
    build_multimodal_network,
    generate_multimodal_demand,
    route_and_validate_multimodal_demand,
    write_multimodal_demand_manifest,
)
from traffic_platform.scenario_engine.osm_selection import (
    select_controlled_intersections,
    selection_geojson,
)
from traffic_platform.scenario_engine.parameter_transfer import transfer_parameters
from traffic_platform.scenario_engine.signal_application import (
    apply_parameter_transfer,
    write_application_manifest,
)

REQUIRED_GENERATED = (
    "rongdong.control.net.xml",
    "rongdong.parameterized.net.xml",
    "rongdong.multimodal.base.net.xml",
    "rongdong.multimodal.signaled.net.xml",
    "rongdong.multimodal.net.xml",
    "routes.rou.xml",
    "multimodal.trips.xml",
    "multimodal.rou.xml",
    "vtypes.add.xml",
    "simple-shapes.view.xml",
    "pedestrian_adult.png",
    "pedestrian_elderly.png",
    "functional_zones.add.xml",
    "xiongan_rongdong_20.sumocfg",
    "controlled_intersections.json",
    "parameter_transfer.json",
    "organizer_parameter_application.json",
    "intersection_inventory.json",
    "intersection_inventory.csv",
    "profiles_manifest.json",
    "multimodal_network_manifest.json",
    "multimodal_demand_manifest.json",
    "functional_zones.json",
)


def generate_demo_scenario(
    workspace: Path,
    sumo_home: Path,
    *,
    rebuild: bool = True,
) -> dict[str, Any]:
    """Build or verify the real-geography engineering demonstration scenario."""

    source = workspace / "scenarios" / "source" / "xiongan_rongdong_20"
    output = workspace / "scenarios" / "generated" / "xiongan_rongdong_20"
    config_file = workspace / "scenarios" / "configs" / "xiongan_rongdong_20.yaml"
    profile_file = workspace / "scenarios" / "configs" / "presets" / "S01-S07.yaml"
    scenario = ScenarioConfig.from_yaml(config_file)
    output.mkdir(parents=True, exist_ok=True)
    if rebuild:
        base_networks_exist = (output / "rongdong.net.xml").is_file() and (
            output / "rongdong.control.net.xml"
        ).is_file()
        allow_base_rebuild = os.environ.get(
            "TRAFFIC_ALLOW_BASE_NETWORK_REBUILD", "false"
        ).lower() in {"1", "true", "yes"}
        if not base_networks_exist or allow_base_rebuild:
            _build_network(source, output, sumo_home)
        selection = select_controlled_intersections(
            output / "rongdong.net.xml",
            source / "organizer_demo13_20_registration_estimates.geojson",
        )
        (output / "controlled_intersections.json").write_text(
            json.dumps(selection, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (output / "controlled_intersections.geojson").write_text(
            json.dumps(selection_geojson(selection), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        build_functional_zones(
            source / "rongdong_bbox.osm.xml",
            output / "controlled_intersections.json",
            output / "functional_zones.json",
            net_file=output / "rongdong.net.xml",
            sumo_shape_file=output / "functional_zones.add.xml",
        )
        if not base_networks_exist or allow_base_rebuild:
            signal_ids = ",".join(selection["requires_signalization"])
            _run(
                [
                    str(_sumo_binary(sumo_home, "netconvert")),
                    "--sumo-net-file",
                    str(output / "rongdong.net.xml"),
                    "--output-file",
                    str(output / "rongdong.control.net.xml"),
                    "--tls.set",
                    signal_ids,
                    "--tls.default-type",
                    "static",
                ],
                workspace,
            )
        parameter_file = _ensure_parameter_transfer(
            output=output,
            selection_file=output / "controlled_intersections.json",
            sumo_home=sumo_home,
        )
        application = apply_parameter_transfer(
            net_file=output / "rongdong.control.net.xml",
            parameter_file=parameter_file,
            selection_file=output / "controlled_intersections.json",
            output_file=output / "rongdong.parameterized.net.xml",
        )
        write_application_manifest(
            application,
            output / "organizer_parameter_application.json",
        )
        _build_routes_and_profiles(
            output=output,
            source=source,
            scenario=scenario,
            profile_file=profile_file,
            sumo_home=sumo_home,
            parameter_file=parameter_file,
        )
        inventory = build_intersection_inventory(
            net_file=output / "rongdong.multimodal.net.xml",
            selection_file=output / "controlled_intersections.json",
            parameter_file=parameter_file,
        )
        write_intersection_inventory(
            inventory,
            json_file=output / "intersection_inventory.json",
            csv_file=output / "intersection_inventory.csv",
        )
    missing = [name for name in REQUIRED_GENERATED if not (output / name).is_file()]
    if missing:
        raise FileNotFoundError(f"missing generated scenario files: {missing}")
    selection = json.loads((output / "controlled_intersections.json").read_text(encoding="utf-8"))
    if selection["controlled_intersection_count"] != 20:
        raise ValueError("demo scenario must have exactly 20 controlled intersections")
    if not selection["controlled_meta_graph_connected"]:
        raise ValueError("demo scenario controlled topology is not connected")
    files = [
        *[output / name for name in REQUIRED_GENERATED],
        config_file,
        profile_file,
        *sorted(output.glob("routes.S??.rou.xml")),
        *sorted(output.glob("xiongan_rongdong_20.S??.sumocfg")),
    ]
    manifest = build_manifest(
        "xiongan_rongdong_20",
        files,
        workspace=workspace,
        provenance={
            "network": "OpenStreetMap extract",
            "parameter_status": "organizer plus modeled transfer",
            "claim": "engineering validation, not field-calibrated digital twin",
            "generator": "traffic_platform.scenario_engine.generator",
        },
    )
    manifest_path = output / "scenario_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "generated" if rebuild else "verified",
        "intersection_count": 20,
        "topology_edge_count": len(selection["topology_edges"]),
        "connected": True,
        "scenario_config": str(config_file),
        "profile_count": 7,
        "organizer_parameters_applied": True,
        "manifest": str(manifest_path),
    }


def _build_network(source: Path, output: Path, sumo_home: Path) -> None:
    osm_file = source / "rongdong_bbox.osm.xml"
    if not osm_file.is_file():
        raise FileNotFoundError(
            f"Rongdong OSM extract is absent; place a legitimate OSM extract at {osm_file}"
        )
    _run(
        [
            str(_sumo_binary(sumo_home, "netconvert")),
            "--osm-files",
            str(osm_file),
            "--output-file",
            str(output / "rongdong.net.xml"),
            "--geometry.remove",
            "true",
            "--roundabouts.guess",
            "true",
            "--tls.guess-signals",
            "true",
            "--tls.discard-simple",
            "false",
            "--remove-edges.by-vclass",
            "tram,rail_urban,subway,cable_car,rail_electric,bicycle,pedestrian",
            "--remove-edges.isolated",
            "true",
            "--junctions.join",
            "true",
        ],
        output,
    )


def _ensure_parameter_transfer(
    *,
    output: Path,
    selection_file: Path,
    sumo_home: Path,
) -> Path:
    parameter_file = output / "parameter_transfer.json"
    processed_value = os.environ.get("TRAFFIC_ORGANIZER_PROCESSED_ROOT")
    processed_root = Path(processed_value) if processed_value else None
    if processed_root is not None and processed_root.is_dir():
        os.environ.setdefault("SUMO_HOME", str(sumo_home))
        result = transfer_parameters(
            processed_root,
            output / "rongdong.control.net.xml",
            selection_file,
        )
        parameter_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if not parameter_file.is_file():
        raise FileNotFoundError(
            "organizer parameter transfer is absent. Run `traffic-platform "
            "transfer-parameters` or set TRAFFIC_ORGANIZER_PROCESSED_ROOT before "
            "generating the connected scenario."
        )
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    parameters = json.loads(parameter_file.read_text(encoding="utf-8"))
    expected_ids = {item["intersection_id"] for item in selection["intersections"]}
    actual_ids = set(parameters.get("intersections", {}))
    if actual_ids != expected_ids:
        raise ValueError(
            "parameter_transfer.json is stale for the selected control area; set "
            "TRAFFIC_ORGANIZER_PROCESSED_ROOT and rebuild the scenario"
        )
    return parameter_file


def _write_sumocfg(
    *,
    template: Path,
    output: Path,
    route_name: str,
    network_name: str,
    scenario: ScenarioConfig,
) -> None:
    tree = ET.parse(template)
    root = tree.getroot()
    route = root.find("./input/route-files")
    network = root.find("./input/net-file")
    additional = root.find("./input/additional-files")
    end = root.find("./time/end")
    step = root.find("./time/step-length")
    seed = root.find("./random_number/seed")
    teleport = root.find("./processing/time-to-teleport")
    if (
        route is None
        or network is None
        or additional is None
        or end is None
        or step is None
        or seed is None
        or teleport is None
    ):
        raise ValueError("SUMO configuration template is missing required elements")
    route.set("value", route_name)
    network.set("value", network_name)
    additional.set("value", "vtypes.add.xml,functional_zones.add.xml")
    end.set("value", f"{scenario.simulation.duration_s:g}")
    step.set("value", f"{scenario.simulation.step_length_s:g}")
    seed.set("value", str(scenario.simulation.seed))
    # Teleporting silently changes queue propagation and gridlock metrics.
    teleport.set("value", "-1")
    ET.indent(tree, space="    ")
    tree.write(output, encoding="utf-8", xml_declaration=True)


def _build_routes_and_profiles(
    *,
    output: Path,
    source: Path,
    scenario: ScenarioConfig,
    profile_file: Path,
    sumo_home: Path,
    parameter_file: Path,
) -> None:
    shutil.copyfile(source / "vtypes.add.xml", output / "vtypes.add.xml")
    shutil.copyfile(
        source / "simple-shapes.view.xml",
        output / "simple-shapes.view.xml",
    )
    for image_name in ("pedestrian_adult.png", "pedestrian_elderly.png"):
        shutil.copyfile(source / image_name, output / image_name)
    _configure_gui_assets(
        output=output,
        selection_file=output / "controlled_intersections.json",
    )
    add_active_mode_types(output / "vtypes.add.xml")
    build_multimodal_network(
        osm_file=source / "rongdong_bbox.osm.xml",
        output=output,
        sumo_home=sumo_home,
        selection_file=output / "controlled_intersections.json",
        parameter_file=parameter_file,
        scenario=scenario,
    )
    prepared_network = prepare_demand_network(
        net_file=output / "rongdong.multimodal.net.xml",
        scenario=scenario,
        sumo_home=sumo_home,
        selection_file=output / "controlled_intersections.json",
    )
    base = generate_routes(
        net_file=output / "rongdong.multimodal.net.xml",
        route_file=output / "routes.rou.xml",
        scenario=scenario,
        sumo_home=sumo_home,
        parameter_file=parameter_file,
        prepared_network=prepared_network,
    )
    raw_active_demand = generate_multimodal_demand(
        net_file=output / "rongdong.multimodal.net.xml",
        route_file=output / "multimodal.trips.xml",
        scenario=scenario,
        sumo_home=sumo_home,
    )
    active_demand = route_and_validate_multimodal_demand(
        raw_summary=raw_active_demand,
        net_file=output / "rongdong.multimodal.net.xml",
        additional_file=output / "vtypes.add.xml",
        output_file=output / "multimodal.rou.xml",
        sumo_home=sumo_home,
        seed=scenario.simulation.seed,
        scenario=scenario,
    )
    write_multimodal_demand_manifest(
        active_demand,
        output / "multimodal_demand_manifest.json",
    )
    _write_sumocfg(
        template=source / "xiongan_rongdong_20.sumocfg",
        output=output / "xiongan_rongdong_20.sumocfg",
        route_name="routes.rou.xml,multimodal.rou.xml",
        network_name="rongdong.multimodal.net.xml",
        scenario=scenario,
    )
    profile_payload = yaml.safe_load(profile_file.read_text(encoding="utf-8"))
    profiles: list[dict[str, Any]] = []
    for index, profile in enumerate(profile_payload["profiles"], start=1):
        code = str(profile["code"])
        route_name = f"routes.{code}.rou.xml"
        generated = generate_routes(
            net_file=output / "rongdong.multimodal.net.xml",
            route_file=output / route_name,
            scenario=scenario,
            sumo_home=sumo_home,
            flow_multiplier=float(profile["flow_multiplier"]),
            connected_vehicle_penetration=float(profile["connected_vehicle_penetration"]),
            seed_offset=index * 1000,
            parameter_file=parameter_file,
            prepared_network=prepared_network,
        )
        config_name = f"xiongan_rongdong_20.{code}.sumocfg"
        _write_sumocfg(
            template=source / "xiongan_rongdong_20.sumocfg",
            output=output / config_name,
            route_name=f"{route_name},multimodal.rou.xml",
            network_name="rongdong.multimodal.net.xml",
            scenario=scenario,
        )
        profiles.append(
            {
                **profile,
                "route_generation": demand_summary(generated),
                "sumo_config": config_name,
            }
        )
    manifest = {
        "schema_version": "1.0",
        "base_scenario_id": scenario.scenario_id,
        "base_route_generation": demand_summary(base),
        "profiles": profiles,
        "reproducibility": {
            "seed": scenario.simulation.seed,
            "same_config_and_seed_produce_same_routes": True,
        },
    }
    (output / "profiles_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _configure_gui_assets(*, output: Path, selection_file: Path) -> None:
    """Focus SUMO-GUI on the control area and label the twenty junctions."""

    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    intersections = selection["intersections"]
    view_file = output / "simple-shapes.view.xml"
    view_tree = ET.parse(view_file)
    view_root = view_tree.getroot()
    # Do not force the GUI viewport onto the twenty controlled intersections.
    # SUMO auto-fits the complete Rongdong OSM network; POIs remain searchable.
    viewport = view_root.find("viewport")
    if viewport is not None:
        view_root.remove(viewport)
    scheme = view_root.find("scheme")
    if scheme is not None and scheme.find("pois") is None:
        ET.SubElement(
            scheme,
            "pois",
            {
                "poi_minSize": "5.00",
                "poi_exaggeration": "1.50",
                "poi_constantSize": "1",
                "poiName_show": "1",
                "poiName_size": "40.00",
                "poiName_color": "255,255,255",
            },
        )
    ET.indent(view_tree, space="    ")
    view_tree.write(view_file, encoding="utf-8", xml_declaration=True)

    vtype_file = output / "vtypes.add.xml"
    vtype_tree = ET.parse(vtype_file)
    vtype_root = vtype_tree.getroot()
    corridor_ids = set(selection["core_corridor"])
    for item in intersections:
        anchor = item.get("location_anchor")
        color = (
            "255,153,0"
            if anchor
            else "0,210,255"
            if item["intersection_id"] in corridor_ids
            else "183,108,255"
        )
        display_id = str(item["display_id"])
        label = display_id + (f"/{anchor}" if anchor else "")
        ET.SubElement(
            vtype_root,
            "poi",
            {
                "id": label,
                "type": "controlled_intersection",
                "color": color,
                "x": f"{float(item['x']):.2f}",
                "y": f"{float(item['y']):.2f}",
                "layer": "10",
                "width": "5.0",
                "height": "5.0",
            },
        )
    ET.indent(vtype_tree, space="    ")
    vtype_tree.write(vtype_file, encoding="utf-8", xml_declaration=True)


def _sumo_binary(sumo_home: Path, name: str) -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    candidates = (
        sumo_home / "bin" / f"{name}{suffix}",
        sumo_home / f"{name}{suffix}",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{name} was not found under SUMO_HOME={sumo_home}")


def _run(command: list[str], cwd: Path) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"scenario command failed ({completed.returncode}): "
            f"{' '.join(command)}\n{completed.stderr}"
        )
