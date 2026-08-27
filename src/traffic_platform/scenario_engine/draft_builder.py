"""Publish an reviewed source draft as a versioned runnable SUMO scenario."""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import sumolib
import yaml
from pyproj import CRS, Transformer
from shapely.geometry import LineString
from shapely.ops import unary_union

from traffic_platform.scenario_engine.source_factory import (
    draft_dir,
    load_draft,
    validate_draft,
)
from traffic_platform.scene.generator import generate_scene_document

ProgressCallback = Callable[[int, str], None]
SCENARIO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
OD_PATTERN_FRINGE_FACTORS = {
    "network_wide": 1.0,
    "boundary_exchange": 4.0,
    "boundary_dominant": 10.0,
}
OSM_SIMULATION_DURATION_S = 180.0
AUTOMATIC_TARGET_FLOW_MIN_VEH_H = 1800
AUTOMATIC_TARGET_FLOW_MAX_VEH_H = 3000
AUTOMATIC_TARGET_FLOW_STEP_VEH_H = 60
AUTOMATIC_TARGET_FLOW_FLOOR_VEH_H = 1200
AUTOMATIC_MIN_TRIP_DISTANCES_M = (50.0, 75.0, 100.0, 125.0, 150.0)
AUTOMATIC_ROUTE_MINIMUM_RATIO = 0.8
AUTOMATIC_RUNTIME_MIN_INSERTION_RATIO = 0.9
AUTOMATIC_RUNTIME_MAX_HALTING_RATIO = 0.8
AUTOMATIC_RUNTIME_MIN_MEAN_SPEED_M_S = 1.0
TLS_JOIN_DISTANCE_M = 20.0
GUI_SELECTION_MARGIN_M = 20.0
VIEW_SETTINGS_FILE = "common.settings.xml"
STALE_GUI_ARTIFACTS = (
    "simple-shapes.view.xml",
    "xiongan-presentation.view.xml",
    "xiongan-diagnostic.view.xml",
    "launch-sumo-diagnostics.cmd",
    "launch-sumo-gui.cmd",
)
DEFAULT_TRAFFIC_DEMAND: dict[str, Any] = {
    "source": "synthetic",
    "target_flow_veh_h": float(AUTOMATIC_TARGET_FLOW_MIN_VEH_H),
    "duration_s": OSM_SIMULATION_DURATION_S,
    "od_pattern": "boundary_exchange",
    "min_trip_distance_m": AUTOMATIC_MIN_TRIP_DISTANCES_M[0],
}


def automatic_traffic_demand(seed: int) -> dict[str, Any]:
    """Create a reproducible, sufficiently populated synthetic demand profile."""

    generator = random.Random(seed ^ 0x5C_10_A2_6D)
    return {
        "source": "synthetic",
        "target_flow_veh_h": float(
            generator.randrange(
                AUTOMATIC_TARGET_FLOW_MIN_VEH_H,
                AUTOMATIC_TARGET_FLOW_MAX_VEH_H + AUTOMATIC_TARGET_FLOW_STEP_VEH_H,
                AUTOMATIC_TARGET_FLOW_STEP_VEH_H,
            )
        ),
        "duration_s": OSM_SIMULATION_DURATION_S,
        "od_pattern": generator.choice(tuple(OD_PATTERN_FRINGE_FACTORS)),
        "min_trip_distance_m": generator.choice(AUTOMATIC_MIN_TRIP_DISTANCES_M),
    }


def normalize_traffic_demand(
    value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one validated, explicit synthetic demand definition.

    Source drafts do not contain measured traffic counts.  Keeping this
    normalization beside the generator ensures that direct Python callers and
    API callers receive the same defaults and validation boundaries.
    """

    demand = {**DEFAULT_TRAFFIC_DEMAND, **dict(value or {})}
    if demand["source"] != "synthetic":
        raise ValueError("source draft demand must be explicitly synthetic")
    flow = float(demand["target_flow_veh_h"])
    duration = float(demand["duration_s"])
    minimum_distance = float(demand["min_trip_distance_m"])
    od_pattern = str(demand["od_pattern"])
    if not 60.0 <= flow <= 7200.0:
        raise ValueError("target_flow_veh_h must be between 60 and 7200")
    if not OSM_SIMULATION_DURATION_S <= duration <= 7200.0:
        raise ValueError("duration_s must be between 180 and 7200")
    if not 0.0 <= minimum_distance <= 5000.0:
        raise ValueError("min_trip_distance_m must be between 0 and 5000")
    if od_pattern not in OD_PATTERN_FRINGE_FACTORS:
        raise ValueError(f"unsupported OD pattern: {od_pattern}")
    return {
        "source": "synthetic",
        "target_flow_veh_h": flow,
        "duration_s": duration,
        "od_pattern": od_pattern,
        "min_trip_distance_m": minimum_distance,
    }


def resolve_traffic_demand(
    source_type: str,
    seed: int,
    value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve hidden automatic demand and enforce the OSM three-minute runtime."""

    demand = normalize_traffic_demand(automatic_traffic_demand(seed) if value is None else value)
    if source_type == "osm_bbox":
        demand["duration_s"] = OSM_SIMULATION_DURATION_S
    return demand


def _sumo_binary(sumo_home: Path, name: str) -> Path:
    candidate = sumo_home / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
    if not candidate.is_file():
        raise FileNotFoundError(f"{name} was not found under {sumo_home}")
    return candidate


def _run(command: list[str], cwd: Path, timeout: int = 300) -> None:
    environment = os.environ.copy()
    is_random_trips = len(command) > 1 and Path(command[1]).name.lower() == "randomtrips.py"
    if Path(command[0]).stem.lower() == "netconvert":
        environment.pop("SUMO_HOME", None)
    elif is_random_trips:
        sumo_bin = Path(command[1]).resolve().parent.parent / "bin"
        environment.pop("SUMO_HOME", None)
        environment["PATH"] = str(sumo_bin) + os.pathsep + environment.get("PATH", "")
    process = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout)[-4000:])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _key(x: float, y: float, geographic: bool) -> tuple[float, float]:
    return round(x, 7 if geographic else 3), round(y, 7 if geographic else 3)


def _planning_inputs(
    draft: dict[str, Any],
    output: Path,
) -> tuple[Path, Path]:
    """Convert corrected planning centerlines to explicit SUMO nodes and edges."""

    preview = draft["preview"]
    raw_lines = [
        LineString([(float(point[0]), float(point[1])) for point in road["coordinates"]])
        for road in preview["roads"]
        if len(road.get("coordinates", [])) >= 2
    ]
    if not raw_lines:
        raise ValueError("planning draft has no road centerlines")
    geographic = draft.get("coordinate_mode") == "geographic"
    transformer: Transformer | None = None
    if geographic:
        centroid = unary_union(raw_lines).centroid
        zone = max(1, min(60, int((centroid.x + 180) / 6) + 1))
        epsg = 32600 + zone if centroid.y >= 0 else 32700 + zone
        transformer = Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)

    split_geometry = unary_union(raw_lines)
    split_lines = (
        [split_geometry]
        if isinstance(split_geometry, LineString)
        else list(getattr(split_geometry, "geoms", []))
    )
    intersection_ids = {
        _key(float(item["x"]), float(item["y"]), geographic): str(item["intersection_id"])
        for item in preview["intersections"]
    }
    selected = set(draft["selected_intersection_ids"])
    node_ids: dict[tuple[float, float], str] = {}
    node_coordinates: dict[str, tuple[float, float]] = {}

    def register(point: tuple[float, float]) -> str:
        point_key = _key(point[0], point[1], geographic)
        node_id = node_ids.get(point_key)
        if node_id is None:
            node_id = intersection_ids.get(point_key, f"N{len(node_ids) + 1:05d}")
            node_ids[point_key] = node_id
            projected = transformer.transform(*point) if transformer is not None else point
            node_coordinates[node_id] = (float(projected[0]), float(projected[1]))
        return node_id

    edges: list[tuple[str, str, str]] = []
    edge_index = 0
    for line in split_lines:
        coordinates = list(line.coords)
        for start, end in pairwise(coordinates):
            source = register((float(start[0]), float(start[1])))
            target = register((float(end[0]), float(end[1])))
            if source == target:
                continue
            edge_index += 1
            edges.append((f"E{edge_index:05d}", source, target))
            edge_index += 1
            edges.append((f"E{edge_index:05d}", target, source))
    if not edges:
        raise ValueError("planning centerlines did not produce any SUMO edges")

    nodes_root = ET.Element("nodes")
    for node_id, (x, y) in node_coordinates.items():
        attributes = {"id": node_id, "x": f"{x:.3f}", "y": f"{y:.3f}"}
        if node_id in selected:
            attributes["type"] = "traffic_light"
        ET.SubElement(nodes_root, "node", attributes)
    edges_root = ET.Element("edges")
    for edge_id, source, target in edges:
        ET.SubElement(
            edges_root,
            "edge",
            {
                "id": edge_id,
                "from": source,
                "to": target,
                "numLanes": "2",
                "speed": "13.89",
                "priority": "3",
            },
        )
    nodes_path = output / "planning.nod.xml"
    edges_path = output / "planning.edg.xml"
    _write_xml(nodes_path, nodes_root)
    _write_xml(edges_path, edges_root)
    return nodes_path, edges_path


def _build_network(
    workspace: Path,
    sumo_home: Path,
    draft: dict[str, Any],
    output: Path,
) -> Path:
    final = output / "rongdong.multimodal.net.xml"
    if draft["source_type"] == "osm_bbox":
        source = draft_dir(workspace, draft["id"]) / str(draft["artifacts"]["network"])
        command = [
            str(_sumo_binary(sumo_home, "netconvert")),
            "--sumo-net-file",
            str(source),
            "--output-file",
            str(final),
            "--tls.default-type",
            "actuated",
            "--tls.join",
            "false",
            "--junctions.join",
            "false",
            "--no-turnarounds",
            "true",
        ]
        selected_set = set(draft["selected_intersection_ids"])
        needs_signal = [
            str(item["intersection_id"])
            for item in draft["preview"]["intersections"]
            if item["intersection_id"] in selected_set and not item.get("signalized", False)
        ]
        if needs_signal:
            command.extend(["--tls.set", ",".join(needs_signal)])
    elif draft["source_type"] == "planning_file":
        nodes, edges = _planning_inputs(draft, output)
        command = [
            str(_sumo_binary(sumo_home, "netconvert")),
            "--node-files",
            str(nodes),
            "--edge-files",
            str(edges),
            "--output-file",
            str(final),
            "--junctions.join",
            "false",
            "--crossings.guess",
            "true",
            "--walkingareas",
            "true",
            "--no-turnarounds",
            "true",
        ]
    else:
        raise ValueError(f"unsupported draft source: {draft['source_type']}")
    _run(command, output)
    selected_ids = [str(item) for item in draft["selected_intersection_ids"]]
    root = ET.parse(final).getroot()
    junction_types = {
        str(element.get("id")): str(element.get("type", "")) for element in root.findall("junction")
    }
    signal_layout = _selected_signal_layout(final, selected_ids)
    missing_signalization = [
        identifier
        for identifier in selected_ids
        if not junction_types.get(identifier, "").startswith("traffic_light")
        or identifier not in signal_layout["selected_to_controller"]
    ]
    if missing_signalization:
        raise ValueError(
            "selected intersections were not generated as SUMO traffic lights: "
            + ", ".join(missing_signalization)
        )
    if signal_layout["controlled_internal_connections"]:
        raise ValueError(
            "joined physical intersections still control internal connector exits: "
            + ", ".join(signal_layout["controlled_internal_connections"])
        )
    return final


def _selected_signal_layout(
    network: Path,
    selected_ids: list[str],
) -> dict[str, Any]:
    """Map selected SUMO junction members onto their physical TLS controllers."""

    root = ET.parse(network).getroot()
    selected = set(selected_ids)
    edge_endpoints = {
        str(element.get("id")): (
            str(element.get("from", "")),
            str(element.get("to", "")),
        )
        for element in root.findall("edge")
        if element.get("function") != "internal"
    }
    controller_ids = {str(element.get("id")) for element in root.findall("tlLogic")}
    controllers_by_member: dict[str, set[str]] = {identifier: set() for identifier in selected}
    for connection in root.findall("connection"):
        controller = connection.get("tl")
        endpoints = edge_endpoints.get(str(connection.get("from", "")))
        if not controller or endpoints is None:
            continue
        junction_id = endpoints[1]
        if junction_id in selected and controller in controller_ids:
            controllers_by_member[junction_id].add(str(controller))

    ambiguous = {
        identifier: sorted(controller_ids_for_member)
        for identifier, controller_ids_for_member in controllers_by_member.items()
        if len(controller_ids_for_member) > 1
    }
    if ambiguous:
        raise ValueError(f"selected SUMO junctions map to multiple TLS controllers: {ambiguous}")
    selected_to_controller = {
        identifier: next(iter(controller_ids_for_member))
        for identifier, controller_ids_for_member in controllers_by_member.items()
        if controller_ids_for_member
    }
    selected_order = {identifier: index for index, identifier in enumerate(selected_ids)}
    controllers: dict[str, list[str]] = {}
    for identifier, controller in selected_to_controller.items():
        controllers.setdefault(controller, []).append(identifier)
    for members in controllers.values():
        members.sort(key=selected_order.__getitem__)

    internal_connector_edges: dict[str, set[str]] = {}
    for controller, members in controllers.items():
        member_set = set(members)
        internal_connector_edges[controller] = {
            edge_id
            for edge_id, (source, target) in edge_endpoints.items()
            if source in member_set and target in member_set
        }
    controlled_internal_connections = sorted(
        f"{connection.get('from')}->{connection.get('to')}@{connection.get('tl')}"
        for connection in root.findall("connection")
        if connection.get("tl") in internal_connector_edges
        and connection.get("from") in internal_connector_edges[str(connection.get("tl"))]
    )
    return {
        "selected_to_controller": selected_to_controller,
        "controllers": controllers,
        "internal_connector_edges": {
            controller: sorted(edge_ids)
            for controller, edge_ids in internal_connector_edges.items()
        },
        "controlled_internal_connections": controlled_internal_connections,
    }


def _gui_viewport(draft: Mapping[str, Any], network: Path) -> dict[str, float] | None:
    loaded = sumolib.net.readNet(str(network), withInternal=False)
    min_x, min_y, max_x, max_y = (float(value) for value in loaded.getBoundary())
    if max_x <= min_x or max_y <= min_y:
        return None
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    zoom = 100.0
    selection = draft.get("preview", {}).get("selection_bounds")
    if draft.get("source_type") == "osm_bbox" and isinstance(selection, Mapping):
        try:
            west = float(selection["west"])
            south = float(selection["south"])
            east = float(selection["east"])
            north = float(selection["north"])
            selection_min_x, selection_min_y = loaded.convertLonLat2XY(west, south)
            selection_max_x, selection_max_y = loaded.convertLonLat2XY(east, north)
            center_x = (selection_min_x + selection_max_x) / 2.0
            center_y = (selection_min_y + selection_max_y) / 2.0
            visible_width = abs(selection_max_x - selection_min_x) + 2 * GUI_SELECTION_MARGIN_M
            visible_height = abs(selection_max_y - selection_min_y) + 2 * GUI_SELECTION_MARGIN_M
            zoom = 100.0 * min(
                (max_x - min_x) / max(visible_width, 1.0),
                (max_y - min_y) / max(visible_height, 1.0),
            )
            zoom = min(800.0, max(100.0, zoom))
        except (KeyError, TypeError, ValueError):
            pass
    return {
        "x": center_x,
        "y": center_y,
        "zoom": zoom,
    }


def _viewsettings_xml(viewport: Mapping[str, float] | None) -> str:
    viewport_xml = (
        f'  <viewport zoom="{viewport["zoom"]:.2f}" '
        f'x="{viewport["x"]:.2f}" y="{viewport["y"]:.2f}" angle="0.00"/>\n'
        if viewport is not None
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<viewsettings>
  <scheme name="custom_1">
    <opengl dither="0" fps="0" trueZ="0" drawBoundaries="0" disableDottedContours="0" forceDrawRectangleSelection="0"/>
    <background backgroundColor="white" showGrid="0" gridXSize="100.00" gridYSize="100.00"/>
    <edges laneEdgeMode="0" scaleMode="0" laneShowBorders="1" showBikeMarkings="1"
           showLinkDecals="0" realisticLinkRules="0" showLinkRules="1" showRails="1"
           secondaryShape="0" hideConnectors="0" widthExaggeration="1.00" minSize="0.00"
           showDirection="0" showSublanes="1" spreadSuperposed="0" disableHideByZoom="1">
      <colorScheme name="uniform">
        <entry color="black" name="road"/>
        <entry color="grey" name="sidewalk"/>
        <entry color="192,66,44" name="bike lane"/>
        <entry color="invisible" name="green verge"/>
        <entry color="150,200,200" name="waterway"/>
        <entry color="black" name="railway"/>
        <entry color="64,0,64" name="rails on road"/>
        <entry color="92,92,92" name="no passenger"/>
        <entry color="red" name="closed"/>
        <entry color="green" name="connector"/>
        <entry color="orange" name="forbidden"/>
        <entry color="200,240,240" name="airway"/>
      </colorScheme>
    </edges>
    <vehicles vehicleMode="0" vehicleScaleMode="0" vehicleQuality="2"
              vehicle_minSize="1.50" vehicle_exaggeration="1.25" vehicle_constantSize="0"
              vehicle_constantSizeSelected="0" showBlinker="1" drawMinGap="0" drawBrakeGap="0"
              showRouteIndex="0" scaleLength="1" drawReversed="0">
      <colorScheme name="given vehicle/type/route color"><entry color="yellow"/></colorScheme>
      <colorScheme name="uniform"><entry color="yellow"/></colorScheme>
      <colorScheme name="given/assigned vehicle color"><entry color="yellow"/></colorScheme>
      <colorScheme name="given/assigned type color"><entry color="yellow"/></colorScheme>
      <colorScheme name="given/assigned route color"><entry color="yellow"/></colorScheme>
      <scalingScheme name="uniform"><entry color="1.00"/></scalingScheme>
    </vehicles>
    <persons personMode="0" personQuality="0" showPedestrianNetwork="1"
             pedestrianNetworkColor="179,217,255" person_minSize="1.00"
             person_exaggeration="1.00" person_constantSize="0">
      <colorScheme name="given person/type color"><entry color="blue"/></colorScheme>
      <colorScheme name="uniform"><entry color="blue"/></colorScheme>
    </persons>
    <junctions junctionMode="0" drawLinkTLIndex_show="0" drawLinkJunctionIndex_show="0"
               junctionID_show="0" junctionName_show="0" internalJunctionName_show="0"
               tlsPhaseIndex_show="0" tlsPhaseName_show="0" showLane2Lane="0" drawShape="1"
               drawCrossingsAndWalkingareas="0" junction_minSize="1.00"
               junction_exaggeration="1.00" junction_constantSize="0">
      <colorScheme name="uniform">
        <entry color="black"/>
        <entry color="150,200,200" name="waterway"/>
        <entry color="invisible" name="railway"/>
        <entry color="200,240,240" name="airway"/>
      </colorScheme>
    </junctions>
    <additionals addMode="0" add_minSize="1.00" add_exaggeration="1.00" add_constantSize="0"/>
    <polys polyMode="0" poly_minSize="0.00" poly_exaggeration="1.00" poly_constantSize="0">
      <colorScheme name="given polygon color"><entry color="orange"/></colorScheme>
      <colorScheme name="uniform"><entry color="orange"/></colorScheme>
    </polys>
    <legend showSizeLegend="1" showColorLegend="0" showVehicleColorLegend="0"/>
  </scheme>
{viewport_xml}  <delay value="300.00"/>
</viewsettings>
"""


def _write_launchers(output: Path, scenario_id: str) -> list[Path]:
    launcher = output / "launch-sumo-gui.vbs"
    launcher.write_text(
        rf"""Option Explicit

Dim shell, files, sceneDir, projectGui, portableGui, sumoGui, configFile, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

sceneDir = files.GetParentFolderName(WScript.ScriptFullName)
projectGui = files.GetAbsolutePathName(files.BuildPath(sceneDir, "..\..\..\.tools\sumo\bin\sumo-gui.exe"))
portableGui = files.GetAbsolutePathName(files.BuildPath(sceneDir, "..\..\..\runtime\sumo\bin\sumo-gui.exe"))
configFile = files.BuildPath(sceneDir, "{scenario_id}.sumocfg")

If files.FileExists(projectGui) Then
  sumoGui = projectGui
ElseIf files.FileExists(portableGui) Then
  sumoGui = portableGui
Else
  sumoGui = "sumo-gui.exe"
End If

shell.CurrentDirectory = sceneDir
command = Chr(34) & sumoGui & Chr(34) & " -c " & Chr(34) & configFile & Chr(34) & " --start --window-size 1600,1000"

On Error Resume Next
shell.Run command, 1, False
If Err.Number <> 0 Then
  MsgBox "SUMO GUI was not found. Keep this scene inside the project workspace or install SUMO.", 16, "Unable to open SUMO"
End If
""",
        encoding="ascii",
    )
    readme = output / "SCENE-README.txt"
    readme.write_text(
        f"""Xiongan SUMO generated scene: {scenario_id}

Open
  Double-click launch-sumo-gui.vbs. It opens SUMO without a command window and loads
  the sumo工程_路口3 custom_1 view.

Files
  {scenario_id}.sumocfg                 single simulation entry
  {VIEW_SETTINGS_FILE}                  sumo工程_路口3-compatible custom_1 settings
  controlled_intersections.json         physical TLS controller/member mapping

Traffic truth, vehicles, routes and signals remain in SUMO.
""",
        encoding="utf-8",
    )
    return [launcher, readme]


def _write_support_files(
    output: Path,
    draft: Mapping[str, Any],
    network: Path,
    scenario_id: str,
) -> list[Path]:
    # Historical versions retain the richer diagnostic files, while the active
    # generated directory exposes one configuration and one standard light view.
    for stale_name in (*STALE_GUI_ARTIFACTS, f"{scenario_id}.diagnostic.sumocfg"):
        (output / stale_name).unlink(missing_ok=True)
    multimodal = output / "multimodal.rou.xml"
    multimodal.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<routes/>\n',
        encoding="utf-8",
    )
    vtypes = output / "vtypes.add.xml"
    vtypes.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<additional>
  <vType id="platform_passenger" vClass="passenger" accel="2.6" decel="4.5" sigma="0.5" length="5" minGap="2.5" maxSpeed="33.3"/>
</additional>
""",
        encoding="utf-8",
    )
    zones_add = output / "functional_zones.add.xml"
    zones_add.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<additional/>\n',
        encoding="utf-8",
    )
    zones_json = output / "functional_zones.json"
    zones_json.write_text(
        json.dumps({"schema_version": "1.0", "zones": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    viewport = _gui_viewport(draft, network)
    view_settings = output / VIEW_SETTINGS_FILE
    view_settings.write_text(_viewsettings_xml(viewport), encoding="utf-8")
    return [
        multimodal,
        vtypes,
        zones_add,
        zones_json,
        view_settings,
        *_write_launchers(output, scenario_id),
    ]


def _xml_element_count(path: Path, tag: str) -> int:
    count = 0
    for _event, element in ET.iterparse(path, events=("end",)):
        if element.tag == tag:
            count += 1
        element.clear()
    return count


def _network_diagonal_m(network: Path) -> float:
    loaded = sumolib.net.readNet(str(network), withInternal=False)
    min_x, min_y, max_x, max_y = loaded.getBoundary()
    return math.hypot(max_x - min_x, max_y - min_y)


def _route_attempt_parameters(
    demand: Mapping[str, Any],
    network_diagonal_m: float,
    adaptive: bool,
) -> list[tuple[str, float]]:
    requested_pattern = str(demand["od_pattern"])
    requested_distance = float(demand["min_trip_distance_m"])
    if not adaptive:
        return [(requested_pattern, requested_distance)]
    feasible_distance = min(requested_distance, max(0.0, network_diagonal_m * 0.45))
    candidates = [
        (requested_pattern, feasible_distance),
        (requested_pattern, feasible_distance * 0.5),
        ("network_wide", feasible_distance * 0.25),
        ("network_wide", 0.0),
    ]
    attempts: list[tuple[str, float]] = []
    for pattern, distance in candidates:
        value = (pattern, round(distance, 3))
        if value not in attempts:
            attempts.append(value)
    return attempts


def _generate_routes(
    workspace: Path,
    sumo_home: Path,
    output: Path,
    network: Path,
    seed: int,
    traffic_demand: Mapping[str, Any] | None,
    minimum_route_ratio: float | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    demand = normalize_traffic_demand(traffic_demand)
    random_trips = sumo_home / "tools" / "randomTrips.py"
    if not random_trips.is_file():
        random_trips = workspace / ".tools" / "sumo" / "tools" / "randomTrips.py"
    if not random_trips.is_file():
        raise FileNotFoundError("SUMO randomTrips.py was not found")
    route_file = output / "routes.rou.xml"
    trips_file = output / "trips.trips.xml"
    period_s = 3600.0 / float(demand["target_flow_veh_h"])
    expected_departures = float(demand["target_flow_veh_h"]) * float(demand["duration_s"]) / 3600.0
    adaptive = minimum_route_ratio is not None
    required_vehicle_count = (
        math.ceil(expected_departures * float(minimum_route_ratio)) if adaptive else 0
    )
    network_diagonal_m = _network_diagonal_m(network)
    attempts: list[dict[str, Any]] = []
    routed_vehicle_count = 0
    candidate_trip_count = 0
    applied_pattern = str(demand["od_pattern"])
    applied_distance = float(demand["min_trip_distance_m"])
    fringe_factor = OD_PATTERN_FRINGE_FACTORS[applied_pattern]
    for attempt_number, (pattern, minimum_distance) in enumerate(
        _route_attempt_parameters(demand, network_diagonal_m, adaptive),
        start=1,
    ):
        for stale_name in (route_file.name, "trips.trips.xml", "tmp.routes.rou.xml"):
            (output / stale_name).unlink(missing_ok=True)
        fringe_factor = OD_PATTERN_FRINGE_FACTORS[pattern]
        _run(
            [
                sys.executable,
                str(random_trips),
                "-n",
                network.name,
                "-r",
                route_file.name,
                "-b",
                "0",
                "-e",
                f"{float(demand['duration_s']):.3f}",
                "-p",
                f"{period_s:.9f}",
                "--seed",
                str(seed),
                "--validate",
                "--vehicle-class",
                "passenger",
                "--fringe-factor",
                f"{fringe_factor:.3f}",
                "--min-distance",
                f"{minimum_distance:.3f}",
                "--prefix",
                "veh_",
            ],
            output,
            timeout=600,
        )
        routed_vehicle_count = _xml_element_count(route_file, "vehicle")
        candidate_trip_count = _xml_element_count(trips_file, "trip")
        applied_pattern = pattern
        applied_distance = minimum_distance
        attempts.append(
            {
                "attempt": attempt_number,
                "od_pattern": pattern,
                "min_trip_distance_m": minimum_distance,
                "candidate_trip_count": candidate_trip_count,
                "routed_vehicle_count": routed_vehicle_count,
            }
        )
        if not adaptive or routed_vehicle_count >= required_vehicle_count:
            break
    accepted = not adaptive or routed_vehicle_count >= required_vehicle_count
    demand_summary = {
        "schema_version": "1.0",
        "source": "synthetic_engineering_demand",
        "is_field_measured": False,
        "generator": "SUMO randomTrips.py",
        "seed": seed,
        "requested": demand,
        "derived": {
            "period_s": round(period_s, 9),
            "fringe_factor": fringe_factor,
            "network_diagonal_m": round(network_diagonal_m, 3),
            "expected_departures_before_routing": round(expected_departures, 3),
            "minimum_routed_vehicle_ratio": minimum_route_ratio,
            "minimum_routed_vehicle_count": required_vehicle_count,
            "applied_od_pattern": applied_pattern,
            "applied_min_trip_distance_m": applied_distance,
        },
        "actual": {
            "candidate_trip_count": candidate_trip_count,
            "routed_vehicle_count": routed_vehicle_count,
            "achieved_flow_veh_h": round(
                routed_vehicle_count * 3600.0 / float(demand["duration_s"]),
                3,
            ),
        },
        "od_definition": {
            "method": "weighted_random_edge_pairs",
            "requested_pattern": demand["od_pattern"],
            "applied_pattern": applied_pattern,
            "route_feasibility_filter": True,
            "note": (
                "Origin and destination edges are sampled from the generated network; "
                "the fringe factor controls boundary preference. This is not a measured OD matrix."
            ),
        },
        "generation_attempts": attempts,
        "acceptance": {
            "accepted": accepted,
            "minimum_ratio": minimum_route_ratio,
            "required_vehicle_count": required_vehicle_count,
            "actual_vehicle_count": routed_vehicle_count,
        },
    }
    demand_manifest = output / "traffic_demand_manifest.json"
    demand_manifest.write_text(
        json.dumps(demand_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not accepted:
        raise RuntimeError(
            "OSM traffic demand could not reach the publication threshold: "
            f"routed {routed_vehicle_count}, required {required_vehicle_count}"
        )
    return route_file, demand_manifest, demand_summary


def _automatic_flow_candidates(initial_flow_veh_h: float) -> list[float]:
    """Keep the random target, then use populated fallbacks for tiny networks."""

    rounded = int(
        round(initial_flow_veh_h / AUTOMATIC_TARGET_FLOW_STEP_VEH_H)
        * AUTOMATIC_TARGET_FLOW_STEP_VEH_H
    )
    candidates = [max(AUTOMATIC_TARGET_FLOW_FLOOR_VEH_H, rounded)]
    for fallback in (2400, 1800, 1500, AUTOMATIC_TARGET_FLOW_FLOOR_VEH_H):
        if fallback < candidates[0] and fallback not in candidates:
            candidates.append(fallback)
    return [float(value) for value in candidates]


def _runtime_acceptance_from_summary(summary_file: Path) -> dict[str, Any]:
    root = ET.parse(summary_file).getroot()
    steps = root.findall("step")
    if not steps:
        raise ValueError("SUMO demand runtime summary contains no simulation steps")
    final = steps[-1]
    tail = steps[-30:]
    loaded = int(final.get("loaded", "0"))
    inserted = int(final.get("inserted", "0"))
    running = int(final.get("running", "0"))
    waiting = int(final.get("waiting", "0"))
    arrived = int(final.get("arrived", final.get("ended", "0")))
    mean_speed = sum(float(step.get("meanSpeed", "0")) for step in tail) / len(tail)
    running_samples = sum(int(step.get("running", "0")) for step in tail)
    halting_samples = sum(int(step.get("halting", "0")) for step in tail)
    insertion_ratio = inserted / loaded if loaded else 0.0
    halting_ratio = halting_samples / running_samples if running_samples else 0.0
    traffic_cleared = running == 0 and waiting == 0
    accepted = loaded > 0 and insertion_ratio >= AUTOMATIC_RUNTIME_MIN_INSERTION_RATIO
    if not traffic_cleared:
        accepted = (
            accepted
            and mean_speed >= AUTOMATIC_RUNTIME_MIN_MEAN_SPEED_M_S
            and halting_ratio <= AUTOMATIC_RUNTIME_MAX_HALTING_RATIO
        )
    return {
        "accepted": accepted,
        "loaded_vehicle_count": loaded,
        "inserted_vehicle_count": inserted,
        "arrived_vehicle_count": arrived,
        "running_vehicle_count": running,
        "waiting_vehicle_count": waiting,
        "insertion_ratio": round(insertion_ratio, 4),
        "last_30s_mean_speed_m_s": round(mean_speed, 4),
        "last_30s_halting_ratio": round(halting_ratio, 4),
    }


def _audit_automatic_demand_runtime(
    sumo_home: Path,
    output: Path,
    network: Path,
    route_file: Path,
    seed: int,
    duration_s: float,
) -> dict[str, Any]:
    summary_file = output / ".automatic-demand-runtime-summary.xml"
    summary_file.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.pop("SUMO_HOME", None)
    process = subprocess.run(
        [
            str(_sumo_binary(sumo_home, "sumo")),
            "-n",
            network.name,
            "-r",
            route_file.name,
            "-b",
            "0",
            "-e",
            f"{duration_s:.3f}",
            "--seed",
            str(seed),
            "--summary-output",
            summary_file.name,
            "--no-step-log",
            "true",
        ],
        cwd=output,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=environment,
        check=False,
    )
    if process.returncode != 0 or not summary_file.is_file():
        summary_file.unlink(missing_ok=True)
        return {
            "accepted": False,
            "exit_code": process.returncode,
            "error": (process.stderr or process.stdout)[-1000:],
        }
    try:
        return {
            **_runtime_acceptance_from_summary(summary_file),
            "exit_code": process.returncode,
        }
    finally:
        summary_file.unlink(missing_ok=True)


def _write_sumocfg(
    output: Path,
    scenario_id: str,
    seed: int,
    duration_s: float,
) -> Path:
    path = output / f"{scenario_id}.sumocfg"
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
  <input>
    <net-file value="rongdong.multimodal.net.xml"/>
    <route-files value="routes.rou.xml,multimodal.rou.xml"/>
    <additional-files value="vtypes.add.xml,functional_zones.add.xml"/>
    <gui-settings-file value="{VIEW_SETTINGS_FILE}"/>
  </input>
  <output>
    <tripinfo-output value="tripinfo.xml"/>
    <fcd-output value="traj.xml"/>
    <summary-output value="stats.xml"/>
  </output>
  <time>
    <begin value="0"/>
    <end value="{duration_s:.3f}"/>
    <step-length value="1"/>
  </time>
  <processing>
    <time-to-teleport value="300"/>
    <collision.action value="warn"/>
  </processing>
  <report>
    <verbose value="false"/>
    <no-step-log value="true"/>
    <duration-log.statistics value="true"/>
  </report>
  <random_number>
    <seed value="{seed}"/>
  </random_number>
</configuration>
''',
        encoding="utf-8",
    )
    return path


def _write_config(
    workspace: Path,
    scenario_id: str,
    display_name: str,
    seed: int,
    source_type: str,
    traffic_demand: Mapping[str, Any],
) -> Path:
    baseline = workspace / "scenarios" / "configs" / "xiongan_rongdong_20.yaml"
    payload = yaml.safe_load(baseline.read_text(encoding="utf-8"))
    payload.update(
        scenario_id=scenario_id,
        display_name=display_name,
        provenance=(
            "openstreetmap_plus_modeled_parameters"
            if source_type == "osm_bbox"
            else "engineering_demo_placeholder"
        ),
        is_real_measured_network=False,
        network_file=f"scenarios/generated/{scenario_id}/rongdong.multimodal.net.xml",
        signal_plan="user_reviewed_source_draft_v1",
        disturbances=[],
    )
    payload["simulation"]["seed"] = seed
    payload["simulation"]["duration_s"] = float(traffic_demand["duration_s"])
    payload["demand"] = [
        {
            "origin_zone": f"synthetic_{traffic_demand['od_pattern']}_origins",
            "destination_zone": f"synthetic_{traffic_demand['od_pattern']}_destinations",
            "flow_veh_h": float(traffic_demand["target_flow_veh_h"]),
            "begin_s": 0.0,
            "end_s": float(traffic_demand["duration_s"]),
            "route_alternatives": True,
            "route_scope": "complete_network",
        }
    ]
    payload["vehicle_type_ratios"] = {"passenger": 1.0}
    payload["connected_vehicle_penetration"] = 0.0
    payload["flow_multiplier"] = 1.0
    payload["multimodal"]["demands"] = []
    path = workspace / "scenarios" / "configs" / f"{scenario_id}.yaml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _write_registry(output: Path, draft: dict[str, Any], network: Path) -> Path:
    selected = [str(item) for item in draft["selected_intersection_ids"]]
    selected_set = set(selected)
    signal_layout = _selected_signal_layout(network, selected)
    selected_to_controller: dict[str, str] = signal_layout["selected_to_controller"]
    controllers: dict[str, list[str]] = signal_layout["controllers"]
    network_junctions: dict[str, dict[str, str]] = {}
    for _event, element in ET.iterparse(network, events=("end",)):
        if element.tag == "junction":
            junction_id = element.get("id", "")
            if junction_id in selected_set:
                network_junctions[junction_id] = dict(element.attrib)
        element.clear()
    preview_by_id = {
        str(item["intersection_id"]): item for item in draft["preview"]["intersections"]
    }
    controller_order = sorted(
        controllers,
        key=lambda controller: min(selected.index(item) for item in controllers[controller]),
    )
    items: list[dict[str, Any]] = []
    geographic = draft.get("coordinate_mode") == "geographic"
    for display_index, controller in enumerate(controller_order, start=1):
        members = controllers[controller]
        junctions = [network_junctions.get(member) for member in members]
        missing_members = [
            member for member, junction in zip(members, junctions, strict=True) if junction is None
        ]
        if missing_members:
            raise ValueError(
                "selected junction members are absent from generated SUMO net: "
                + ", ".join(missing_members)
            )
        member_junctions = [junction for junction in junctions if junction is not None]
        previews = [preview_by_id[member] for member in members]
        source_display_ids = [
            str(item.get("display_id", member))
            for item, member in zip(previews, members, strict=True)
        ]
        x = sum(float(junction["x"]) for junction in member_junctions) / len(member_junctions)
        y = sum(float(junction["y"]) for junction in member_junctions) / len(member_junctions)
        lon = sum(float(item["x"]) for item in previews) / len(previews) if geographic else 0.0
        lat = sum(float(item["y"]) for item in previews) / len(previews) if geographic else 0.0
        items.append(
            {
                "intersection_id": controller,
                "display_id": f"J{display_index:02d}",
                "display_name": f"路口 {display_index}",
                "x": x,
                "y": y,
                "lon": lon,
                "lat": lat,
                "degree": max(int(item.get("degree", 0)) for item in previews),
                "signalized": True,
                "source_signalized": any(bool(item.get("signalized", False)) for item in previews),
                "role": "user_selected",
                "sumo_tls_id": controller,
                "sumo_node_id": members[0],
                "member_sumo_junction_ids": members,
                "source_intersection_ids": members,
                "source_display_ids": source_display_ids,
                "physical_intersection_member_count": len(members),
                "physical_intersection_aggregation": "single_sumo_junction",
                "original_sumo_junction_type": member_junctions[0].get("type", "unknown"),
                "original_sumo_junction_types": {
                    member: junction.get("type", "unknown")
                    for member, junction in zip(members, member_junctions, strict=True)
                },
                "parameter_provenance": "user_reviewed_source_draft",
            }
        )

    physical_edges: dict[tuple[str, str], dict[str, Any]] = {}
    controller_rank = {controller: index for index, controller in enumerate(controller_order)}
    for edge in draft["preview"].get("topology_edges", []):
        source_member = str(edge["source"])
        target_member = str(edge["target"])
        if source_member not in selected_set or target_member not in selected_set:
            continue
        source = selected_to_controller[source_member]
        target = selected_to_controller[target_member]
        if source == target:
            continue
        if controller_rank[source] > controller_rank[target]:
            source, target = target, source
        key = (source, target)
        candidate = {
            "source": source,
            "target": target,
            "road_distance_m": float(edge["road_distance_m"]),
        }
        if (
            key not in physical_edges
            or candidate["road_distance_m"] < physical_edges[key]["road_distance_m"]
        ):
            physical_edges[key] = candidate
    edges = list(physical_edges.values())
    payload = {
        "schema_version": "1.1",
        "network_provenance": draft["source_type"],
        "geography_claim": (
            "openstreetmap_geography_not_field_calibrated"
            if draft["source_type"] == "osm_bbox"
            else "user_reviewed_planning_draft_not_as_built_measurement"
        ),
        "selection_method": "user_selected_physical_sumo_junctions",
        "controlled_intersection_count": len(items),
        "selected_source_intersection_count": len(selected),
        "selected_source_intersection_ids": selected,
        "controlled_meta_graph_connected": None,
        "controlled_direct_adjacency_graph_connected": None,
        "requires_signalization": controller_order,
        "source_requires_signalization": selected,
        "tls_join": {
            "enabled": False,
            "distance_m": TLS_JOIN_DISTANCE_M,
            "uncontrolled_within": False,
            "controllers": controllers,
            "internal_connector_edges": signal_layout["internal_connector_edges"],
            "controlled_internal_connection_count": len(
                signal_layout["controlled_internal_connections"]
            ),
        },
        "core_corridor": [],
        "core_corridor_intersection_count": 0,
        "topology_edge_count": len(edges),
        "topology_edges": edges,
        "intersections": items,
        "source_draft_id": draft["id"],
        "full_network_context_retained": draft["source_type"] != "osm_bbox",
        "network_context_strategy": (
            draft.get("source", {}).get("network_context", {}).get("strategy")
        ),
    }
    path = output / "controlled_intersections.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _smoke(output: Path, scenario_id: str, sumo_home: Path) -> dict[str, Any]:
    environment = os.environ.copy()
    environment.pop("SUMO_HOME", None)
    process = subprocess.run(
        [
            str(_sumo_binary(sumo_home, "sumo")),
            "-c",
            str(output / f"{scenario_id}.sumocfg"),
            "--end",
            "10",
            "--no-step-log",
            "true",
        ],
        cwd=output,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    return {
        "passed": process.returncode == 0,
        "exit_code": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }


def build_draft_scenario(
    workspace: Path,
    sumo_home: Path,
    *,
    draft_id: str,
    scenario_id: str,
    display_name: str,
    seed: int,
    traffic_demand: Mapping[str, Any] | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Publish one reviewed source draft and prove it starts in real SUMO."""

    notify = progress or (lambda _value, _message: None)
    if not SCENARIO_ID_PATTERN.fullmatch(scenario_id):
        raise ValueError("scenario_id must contain 3-64 lowercase letters, digits, '-' or '_'")
    draft = load_draft(workspace, draft_id)
    validation = validate_draft(draft)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))
    normalized_demand = resolve_traffic_demand(
        str(draft["source_type"]),
        seed,
        traffic_demand,
    )
    output = workspace / "scenarios" / "generated" / scenario_id
    output.mkdir(parents=True, exist_ok=True)
    notify(8, "草稿校核状态与用户路口选择已验证")
    network = _build_network(workspace, sumo_home, draft, output)
    notify(35, "SUMO 路网与用户选择信号控制已生成")
    if draft["source_type"] == "osm_bbox" and traffic_demand is None:
        initial_random_flow = float(normalized_demand["target_flow_veh_h"])
        runtime_attempts: list[dict[str, Any]] = []
        for candidate_flow in _automatic_flow_candidates(initial_random_flow):
            candidate_demand = {
                **normalized_demand,
                "target_flow_veh_h": candidate_flow,
            }
            route_file, demand_manifest, demand_summary = _generate_routes(
                workspace,
                sumo_home,
                output,
                network,
                seed,
                candidate_demand,
                minimum_route_ratio=AUTOMATIC_ROUTE_MINIMUM_RATIO,
            )
            runtime_check = _audit_automatic_demand_runtime(
                sumo_home,
                output,
                network,
                route_file,
                seed,
                float(candidate_demand["duration_s"]),
            )
            runtime_attempts.append({"target_flow_veh_h": candidate_flow, **runtime_check})
            if runtime_check["accepted"]:
                normalized_demand = candidate_demand
                break
        else:
            raise RuntimeError(
                "automatic traffic demand caused persistent gridlock at the minimum populated flow"
            )
        demand_summary["automatic_flow_control"] = {
            "enabled": True,
            "initial_random_target_flow_veh_h": initial_random_flow,
            "accepted_target_flow_veh_h": normalized_demand["target_flow_veh_h"],
            "minimum_populated_flow_veh_h": AUTOMATIC_TARGET_FLOW_FLOOR_VEH_H,
            "acceptance_rule": {
                "minimum_insertion_ratio": AUTOMATIC_RUNTIME_MIN_INSERTION_RATIO,
                "maximum_last_30s_halting_ratio": AUTOMATIC_RUNTIME_MAX_HALTING_RATIO,
                "minimum_last_30s_mean_speed_m_s": AUTOMATIC_RUNTIME_MIN_MEAN_SPEED_M_S,
            },
            "attempts": runtime_attempts,
        }
        demand_manifest.write_text(
            json.dumps(demand_summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    else:
        route_file, demand_manifest, demand_summary = _generate_routes(
            workspace,
            sumo_home,
            output,
            network,
            seed,
            normalized_demand,
            minimum_route_ratio=(
                AUTOMATIC_ROUTE_MINIMUM_RATIO if draft["source_type"] == "osm_bbox" else None
            ),
        )
    support_files = _write_support_files(output, draft, network, scenario_id)
    notify(58, "确定性交通需求与运行支持文件已生成")
    registry = _write_registry(output, draft, network)
    sumocfg = _write_sumocfg(
        output,
        scenario_id,
        seed,
        float(normalized_demand["duration_s"]),
    )
    config = _write_config(
        workspace,
        scenario_id,
        display_name,
        seed,
        draft["source_type"],
        normalized_demand,
    )
    preview_path = output / "source-preview.json"
    preview_path.write_text(
        json.dumps(draft["preview"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    source_context = output / "source.osm.xml"
    if draft["source_type"] == "osm_bbox":
        source_artifact = draft_dir(workspace, draft_id) / str(draft["artifacts"]["source"])
        shutil.copy2(source_artifact, source_context)
    elif source_context.is_file():
        source_context.unlink()
    scene_result = generate_scene_document(
        workspace,
        scenario_id=scenario_id,
        padding_m=120.0,
    )
    scene_artifacts = [
        Path(str(scene_result[key]))
        for key in ("output", "schema", "manifest", "traffic_light_mapping")
    ]
    notify(74, "同一 SUMO 路网的 2D/3D 静态场景与 ID 映射已生成")
    smoke = _smoke(output, scenario_id, sumo_home)
    if not smoke["passed"]:
        raise RuntimeError(f"SUMO smoke validation failed: {smoke['stderr_tail']}")
    notify(86, "真实 SUMO 短时运行验证通过")
    registry_payload = json.loads(registry.read_text(encoding="utf-8"))

    versions = output / "versions"
    versions.mkdir(exist_ok=True)
    version = f"v{len([path for path in versions.glob('v????') if path.is_dir()]) + 1:04d}"
    version_dir = versions / version
    version_dir.mkdir()
    artifacts = [
        network,
        route_file,
        demand_manifest,
        *support_files,
        registry,
        sumocfg,
        config,
        preview_path,
        *([source_context] if source_context.is_file() else []),
        *scene_artifacts,
    ]
    for artifact in artifacts:
        shutil.copy2(artifact, version_dir / artifact.name)
    report = {
        **validation,
        "scenario_id": scenario_id,
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(),
        "sumo_smoke": smoke,
        "checks": {
            "selected_source_nodes_accounted_for": set(draft["selected_intersection_ids"])
            == {
                member
                for item in registry_payload["intersections"]
                for member in item["member_sumo_junction_ids"]
            },
            "physical_controller_count_matches_registry": registry_payload[
                "controlled_intersection_count"
            ]
            == len(registry_payload["intersections"]),
            "joined_internal_connections_uncontrolled": registry_payload["tls_join"][
                "controlled_internal_connection_count"
            ]
            == 0,
            "twenty_intersection_requirement": "not_applied_user_selection_is_authoritative",
            "source_review_required": draft["requires_manual_review"],
            "source_review_confirmed": draft["review_confirmed"],
            "traffic_demand_minimum_ratio": demand_summary["acceptance"],
            "automatic_demand_runtime": demand_summary.get("automatic_flow_control"),
        },
    }
    validation_path = output / "validation-report.json"
    validation_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(validation_path, version_dir / validation_path.name)
    manifest = {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "version": version,
        "source_draft_id": draft_id,
        "source_type": draft["source_type"],
        "source_metadata": draft["source"],
        "traffic_demand": demand_summary,
        "manual_edits": draft["manual_edits"],
        "generated_at": report["generated_at"],
        "files": [
            {"name": path.name, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path in [*artifacts, validation_path]
        ],
    }
    manifest_path = output / "scenario_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.copy2(manifest_path, version_dir / manifest_path.name)
    notify(100, f"场景 {version} 已发布")
    return {
        "status": "completed",
        "scenario_id": scenario_id,
        "display_name": display_name,
        "version": version,
        "source_draft_id": draft_id,
        "source_type": draft["source_type"],
        "selected_intersection_count": registry_payload["controlled_intersection_count"],
        "selected_source_node_count": len(draft["selected_intersection_ids"]),
        "warnings": validation["warnings"],
        "output_dir": str(output),
        "manifest": str(manifest_path),
        "validation_report": str(validation_path),
        "sumo_config": str(sumocfg),
        "scene": scene_result,
        "traffic_demand": demand_summary,
    }
