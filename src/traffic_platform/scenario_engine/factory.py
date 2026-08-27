"""Versioned user-selected scenario builds derived from the verified OSM network."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
import yaml

from traffic_platform.scene.generator import generate_scene_document

ProgressCallback = Callable[[int, str], None]
SCENARIO_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_registry(workspace: Path) -> dict[str, Any]:
    path = (
        workspace
        / "scenarios"
        / "generated"
        / "xiongan_rongdong_20"
        / "controlled_intersections.json"
    )
    if not path.is_file():
        raise FileNotFoundError(f"source intersection registry is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload.get("intersections"), list):
        raise ValueError("source intersection registry is invalid")
    return payload


def validate_selection(
    workspace: Path,
    selected_intersection_ids: list[str],
) -> dict[str, Any]:
    """Validate exactly what the user selected; never impose a 20-junction minimum."""

    registry = _source_registry(workspace)
    known = {str(item["intersection_id"]): item for item in registry["intersections"]}
    selected = list(dict.fromkeys(selected_intersection_ids))
    errors: list[str] = []
    warnings: list[str] = []
    if not selected:
        errors.append("至少选择一个路口")
    missing = [identifier for identifier in selected if identifier not in known]
    if missing:
        errors.append(f"未知路口: {', '.join(missing)}")

    graph = nx.Graph()
    graph.add_nodes_from(known)
    for edge in registry.get("topology_edges", []):
        graph.add_edge(str(edge["source"]), str(edge["target"]))
    selected_graph = graph.subgraph([identifier for identifier in selected if identifier in known])
    connected = len(selected) <= 1 or (
        selected_graph.number_of_nodes() == len(selected)
        and nx.is_connected(selected_graph)
    )
    if selected and not connected:
        warnings.append("所选受控路口在控制拓扑中不连续; 仍允许生成, 并保留完整路网背景")

    return {
        "valid": not errors,
        "selected_intersection_count": len(selected),
        "selected_intersection_ids": selected,
        "connected_control_subgraph": connected,
        "errors": errors,
        "warnings": warnings,
        "rule": "selected_count_is_authoritative",
    }


def _copy_required(source: Path, target: Path, names: list[str]) -> list[Path]:
    copied: list[Path] = []
    for name in names:
        source_path = source / name
        if not source_path.is_file():
            raise FileNotFoundError(f"scenario source artifact is missing: {source_path}")
        target_path = target / name
        shutil.copy2(source_path, target_path)
        copied.append(target_path)
    return copied


def _write_sumocfg(output: Path, scenario_id: str, seed: int) -> Path:
    path = output / f"{scenario_id}.sumocfg"
    path.write_text(
        f'''<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <input>
    <net-file value="rongdong.multimodal.net.xml"/>
    <route-files value="routes.rou.xml,multimodal.rou.xml"/>
    <additional-files value="vtypes.add.xml,functional_zones.add.xml"/>
  </input>
  <time><begin value="0"/><end value="1800"/><step-length value="1"/></time>
  <processing><time-to-teleport value="300"/><collision.action value="warn"/></processing>
  <report><verbose value="false"/><no-step-log value="true"/><duration-log.statistics value="true"/></report>
  <output>
    <summary-output value="summary.xml"/>
    <tripinfo-output value="tripinfo.xml"/>
    <statistic-output value="statistics.xml"/>
  </output>
  <random_number><seed value="{seed}"/></random_number>
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
) -> Path:
    source = workspace / "scenarios" / "configs" / "xiongan_rongdong_20.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload.update(
        {
            "scenario_id": scenario_id,
            "display_name": display_name,
            "provenance": "openstreetmap_plus_modeled_parameters",
            "is_real_measured_network": False,
            "network_file": (
                f"scenarios/generated/{scenario_id}/rongdong.multimodal.net.xml"
            ),
            "signal_plan": "user_selected_control_registry_v1",
        }
    )
    payload["simulation"]["seed"] = seed
    payload["disturbances"] = []
    path = workspace / "scenarios" / "configs" / f"{scenario_id}.yaml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _sumo_smoke_validate(output: Path, scenario_id: str, sumo_home: Path) -> dict[str, Any]:
    binary = sumo_home / "bin" / "sumo.exe"
    if not binary.is_file():
        binary = sumo_home / "bin" / "sumo"
    if not binary.is_file():
        raise FileNotFoundError(f"SUMO binary was not found under {sumo_home}")
    environment = os.environ.copy()
    environment.pop("SUMO_HOME", None)
    process = subprocess.run(
        [
            str(binary),
            "-c",
            str(output / f"{scenario_id}.sumocfg"),
            "--end",
            "2",
            "--no-step-log",
            "true",
        ],
        cwd=output,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    return {
        "passed": process.returncode == 0,
        "exit_code": process.returncode,
        "stdout_tail": process.stdout[-2000:],
        "stderr_tail": process.stderr[-2000:],
    }


def build_selected_scenario(
    workspace: Path,
    sumo_home: Path,
    *,
    scenario_id: str,
    display_name: str,
    selected_intersection_ids: list[str],
    seed: int = 42,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Build one published, versioned SUMO package for an arbitrary selection."""

    notify = progress or (lambda _value, _message: None)
    if not SCENARIO_ID_PATTERN.fullmatch(scenario_id):
        raise ValueError("scenario_id must contain 3-64 lowercase letters, digits, '-' or '_'")
    validation = validate_selection(workspace, selected_intersection_ids)
    if not validation["valid"]:
        raise ValueError("; ".join(validation["errors"]))

    notify(8, "已验证用户选择")
    registry = _source_registry(workspace)
    selected_ids = validation["selected_intersection_ids"]
    selected_set = set(selected_ids)
    selected_items = [
        item for item in registry["intersections"] if item["intersection_id"] in selected_set
    ]
    selected_items.sort(key=lambda item: selected_ids.index(item["intersection_id"]))
    selected_edges = [
        edge
        for edge in registry.get("topology_edges", [])
        if edge["source"] in selected_set and edge["target"] in selected_set
    ]
    output = workspace / "scenarios" / "generated" / scenario_id
    output.mkdir(parents=True, exist_ok=True)
    source = workspace / "scenarios" / "generated" / "xiongan_rongdong_20"
    copied = _copy_required(
        source,
        output,
        [
            "rongdong.multimodal.net.xml",
            "routes.rou.xml",
            "multimodal.rou.xml",
            "vtypes.add.xml",
            "functional_zones.add.xml",
            "functional_zones.json",
            "simple-shapes.view.xml",
        ],
    )
    notify(32, "已复制可运行SUMO路网与交通需求")

    selected_registry = {
        "schema_version": "1.0",
        "network_provenance": "OpenStreetMap",
        "geography_claim": "real_geography_engineering_model_not_field_calibrated",
        "selection_method": "user_selected_from_verified_rongdong_osm_registry",
        "controlled_intersection_count": len(selected_items),
        "controlled_meta_graph_connected": validation["connected_control_subgraph"],
        "controlled_direct_adjacency_graph_connected": validation[
            "connected_control_subgraph"
        ],
        "requires_signalization": [],
        "core_corridor": [
            item["intersection_id"]
            for item in selected_items
            if item.get("role") == "core_corridor"
        ],
        "core_corridor_intersection_count": sum(
            item.get("role") == "core_corridor" for item in selected_items
        ),
        "topology_edge_count": len(selected_edges),
        "topology_edges": selected_edges,
        "intersections": selected_items,
        "source_scenario_id": "xiongan_rongdong_20",
        "full_osm_network_context_retained": True,
    }
    registry_path = output / "controlled_intersections.json"
    registry_path.write_text(
        json.dumps(selected_registry, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    copied.append(registry_path)
    notify(48, f"已登记{len(selected_items)}个用户选择路口")

    sumocfg = _write_sumocfg(output, scenario_id, seed)
    config_path = _write_config(workspace, scenario_id, display_name, seed)
    osm_context = output / "source.osm.xml"
    shutil.copy2(
        workspace
        / "scenarios"
        / "source"
        / "xiongan_rongdong_20"
        / "rongdong_bbox.osm.xml",
        osm_context,
    )
    scene_result = generate_scene_document(
        workspace,
        scenario_id=scenario_id,
        padding_m=120.0,
    )
    scene_artifacts = [
        Path(str(scene_result[key]))
        for key in ("output", "schema", "manifest", "traffic_light_mapping")
    ]
    copied.extend([sumocfg, config_path, osm_context, *scene_artifacts])
    notify(68, "已生成场景配置及同源2D/3D静态场景")

    smoke = _sumo_smoke_validate(output, scenario_id, sumo_home)
    if not smoke["passed"]:
        raise RuntimeError(f"SUMO smoke validation failed: {smoke['stderr_tail']}")
    notify(78, "SUMO短时启动验证通过")

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    versions = output / "versions"
    versions.mkdir(exist_ok=True)
    existing_versions = sorted(path for path in versions.glob("v????") if path.is_dir())
    version = f"v{len(existing_versions) + 1:04d}"
    version_dir = versions / version
    version_dir.mkdir()
    for path in copied:
        target = version_dir / path.name
        shutil.copy2(path, target)

    validation_report = {
        **validation,
        "scenario_id": scenario_id,
        "version": version,
        "generated_at": timestamp,
        "sumo_smoke": smoke,
        "checks": {
            "selected_count_matches_registry": len(selected_items) == len(selected_ids),
            "sumo_configuration_exists": sumocfg.is_file(),
            "twenty_intersection_requirement": "not_applied_user_selection_is_authoritative",
        },
    }
    validation_path = output / "validation-report.json"
    validation_path.write_text(
        json.dumps(validation_report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy2(validation_path, version_dir / validation_path.name)

    manifest_files = [*copied, validation_path]
    manifest = {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "version": version,
        "generated_at": timestamp,
        "source_scenario_id": "xiongan_rongdong_20",
        "selected_intersection_count": len(selected_items),
        "files": [
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in manifest_files
        ],
    }
    manifest_path = output / "scenario_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    shutil.copy2(manifest_path, version_dir / manifest_path.name)
    notify(100, f"场景{version}已发布")
    return {
        "status": "completed",
        "scenario_id": scenario_id,
        "display_name": display_name,
        "version": version,
        "selected_intersection_count": len(selected_items),
        "connected_control_subgraph": validation["connected_control_subgraph"],
        "warnings": validation["warnings"],
        "output_dir": str(output),
        "manifest": str(manifest_path),
        "validation_report": str(validation_path),
        "sumo_config": str(sumocfg),
        "scene": scene_result,
    }
