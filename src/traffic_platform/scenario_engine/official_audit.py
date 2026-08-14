"""Reproducible organizer-data versus generated-SUMO audit."""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import yaml

from traffic_platform.scenario_engine.official_models import PROFILE_KEYS
from traffic_platform.scenario_engine.official_workbook import parse_official_workbook


def _workbook(source_root: Path, demo_id: int) -> Path:
    candidates = sorted(
        path
        for path in (source_root / "路口数据" / str(demo_id)).rglob("*.xlsx")
        if not path.name.startswith("~$")
    )
    if len(candidates) != 1:
        raise ValueError(f"demo_{demo_id} workbook count is {len(candidates)}, expected 1")
    return candidates[0]


def _expected_flows(workbook: Any, profile_key: str) -> list[tuple[int, int, str, int]]:
    return sorted(
        (interval.begin_s, interval.end_s, movement, count)
        for interval in workbook.demand_profiles[profile_key].intervals
        for movement, count in interval.counts.items()
        if count > 0
    )


def _actual_flows(path: Path) -> list[tuple[int, int, str, int]]:
    root = ET.parse(path).getroot()
    return sorted(
        (
            int(float(flow.get("begin", "0"))),
            int(float(flow.get("end", "0"))),
            str(flow.get("route")),
            int(flow.get("number", "0")),
        )
        for flow in root.findall("flow")
    )


def _expected_signal_durations(workbook: Any, profile_key: str) -> list[int]:
    result: list[int] = []
    for phase in workbook.signal_profiles[profile_key].phases:
        result.extend(
            duration
            for duration in (phase.green_s, phase.yellow_s, phase.all_red_s)
            if duration > 0
        )
    return result


def _actual_signal_durations(path: Path) -> list[int]:
    root = ET.parse(path).getroot()
    logic = root.find("tlLogic")
    if logic is None:
        raise ValueError(f"{path} has no tlLogic")
    return [int(phase.get("duration", "0")) for phase in logic.findall("phase")]


def _flatten_source_issues(demo_id: int, audit: dict[str, Any]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for profile_key, profile in audit["profiles"].items():
        flow = profile["flow"]
        signal = profile["signal"]
        for direction, difference in flow["approach_total_differences"].items():
            issues.append(
                {
                    "demo_id": demo_id,
                    "profile": profile_key,
                    "category": "approach_total",
                    "field": direction,
                    **difference,
                }
            )
        for movement, difference in flow["turn_ratio_differences"].items():
            issues.append(
                {
                    "demo_id": demo_id,
                    "profile": profile_key,
                    "category": "turn_ratio",
                    "field": movement,
                    **difference,
                }
            )
        if not signal["cycle_matches"]:
            issues.append(
                {
                    "demo_id": demo_id,
                    "profile": profile_key,
                    "category": "cycle_total",
                    "field": "cycle_s",
                    "source": signal["declared_cycle_s"],
                    "calculated": signal["calculated_component_cycle_s"],
                }
            )
        for mismatch in signal["phase_component_total_mismatches"]:
            issues.append(
                {
                    "demo_id": demo_id,
                    "profile": profile_key,
                    "category": "phase_component_total",
                    "field": str(mismatch.get("phase_id", "unknown")),
                    "source": mismatch.get("source"),
                    "calculated": mismatch.get("calculated"),
                }
            )
    return issues


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_official_audit(
    workspace: Path,
    source_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Compare all 20 generated projects against organizer workbooks and evidence."""

    generated = workspace / "scenarios" / "generated" / "official_20_independent"
    evidence_path = (
        workspace
        / "scenarios"
        / "source"
        / "official_20_independent"
        / "derived_evidence"
        / "lane_evidence_assessment.json"
    )
    lane_evidence = json.loads(evidence_path.read_text(encoding="utf-8"))["intersections"]
    intersections: list[dict[str, Any]] = []
    profiles: list[dict[str, Any]] = []
    geometry_rows: list[dict[str, Any]] = []
    source_issues: list[dict[str, Any]] = []

    for demo_id in range(1, 21):
        project = generated / f"demo_{demo_id}"
        manifest = json.loads((project / "manifest.json").read_text(encoding="utf-8"))
        validation = json.loads((project / "validation.json").read_text(encoding="utf-8"))
        config = yaml.safe_load((project / "effective_config.yaml").read_text(encoding="utf-8"))
        workbook = parse_official_workbook(_workbook(source_root, demo_id))
        expected_lanes = lane_evidence[str(demo_id)]["arms"]
        actual_lanes = {
            arm: {
                "incoming": int(data["incoming_lanes"]),
                "outgoing": int(data["outgoing_lanes"]),
            }
            for arm, data in config["arms"].items()
        }
        lane_match = actual_lanes == expected_lanes
        reviewed_override = not lane_match and demo_id in {13, 14} and all(
            arm.get("lane_basis") and arm.get("lane_confidence")
            for arm in config["arms"].values()
        )
        lane_status = (
            "exact_registry_match"
            if lane_match
            else "explicit_reviewed_override"
            if reviewed_override
            else "unresolved_conflict"
        )
        adjustments = [
            {"arm": arm, **geometry["modeling_adjustment"]}
            for arm, geometry in manifest["arm_geometry"].items()
            if geometry.get("modeling_adjustment")
        ]
        for arm, geometry in manifest["arm_geometry"].items():
            adjustment = geometry.get("modeling_adjustment") or {}
            effective = geometry.get("sumo_effective_lane_length_m", {})
            evidence_length = geometry.get("measured_length_m")
            geometry_rows.append(
                {
                    "demo_id": demo_id,
                    "arm": arm,
                    "geometry_source": geometry.get("geometry_source", "explicit_osm_chain"),
                    "evidence_length_m": evidence_length,
                    "modeled_length_m": geometry.get("modeled_length_m", evidence_length),
                    "sumo_effective_in_m": effective.get("in"),
                    "sumo_effective_out_m": effective.get("out"),
                    "adjustment_type": adjustment.get("type", "none"),
                    "length_confidence": geometry.get("length_confidence"),
                    "cutoff_reason": geometry.get("cutoff_reason"),
                }
            )
        source_issues.extend(_flatten_source_issues(demo_id, workbook.source_audit))
        cleared_count = 0
        for profile_key in PROFILE_KEYS:
            route_path = project / f"demo_{demo_id}_{profile_key}.rou.xml"
            signal_path = project / f"demo_{demo_id}_{profile_key}.signal.add.xml"
            config_path = project / f"demo_{demo_id}_{profile_key}.sumocfg"
            route_root = ET.parse(route_path).getroot()
            config_root = ET.parse(config_path).getroot()
            view_root = ET.parse(project / "simple-shapes.view.xml").getroot()
            flow_match = _actual_flows(route_path) == _expected_flows(workbook, profile_key)
            signal_match = _actual_signal_durations(signal_path) == _expected_signal_durations(
                workbook, profile_key
            )
            theme_match = (
                route_root.find("vType") is not None
                and route_root.find("vType").get("color") == "1,1,0"  # type: ignore[union-attr]
                and config_root.find("./gui_only/delay") is not None
                and config_root.find("./gui_only/delay").get("value") == "300"  # type: ignore[union-attr]
                and config_root.find("./input/gui-settings-file") is not None
                and config_root.find("./input/gui-settings-file").get("value")  # type: ignore[union-attr]
                == "simple-shapes.view.xml"
                and view_root.find("./scheme/vehicles") is not None
                and view_root.find("./scheme/vehicles").get("vehicleQuality") == "2"  # type: ignore[union-attr]
            )
            run = validation["profiles"][profile_key]
            cleared_count += int(bool(run["all_vehicles_cleared"]))
            profiles.append(
                {
                    "demo_id": demo_id,
                    "profile": profile_key,
                    "expected_demand": workbook.demand_profiles[profile_key].total_vehicles,
                    "generated_demand": sum(
                        int(flow.get("number", "0")) for flow in route_root.findall("flow")
                    ),
                    "flow_intervals_exact": flow_match,
                    "signal_components_exact": signal_match,
                    "theme_gui_exact": theme_match,
                    "source_profile_consistent": workbook.source_audit["profiles"][profile_key][
                        "source_consistent"
                    ],
                    **run,
                }
            )
        intersections.append(
            {
                "demo_id": demo_id,
                "provenance_class": manifest["provenance_class"],
                "official_sumo_reference": demo_id <= 4,
                "lane_evidence_method": lane_evidence[str(demo_id)]["method"],
                "lane_confidence": lane_evidence[str(demo_id)]["confidence"],
                "lane_counts_match_evidence": lane_match,
                "lane_configuration_status": lane_status,
                "lane_configuration_traceable": lane_match or reviewed_override,
                "workbook_source_consistent": workbook.source_audit[
                    "workbook_source_consistent"
                ],
                "geometry_adjustment_count": len(adjustments),
                "geometry_adjustments": adjustments,
                "structurally_valid": validation["structurally_valid"],
                "profiles_cleared": cleared_count,
            }
        )

    summary = {
        "intersection_count": len(intersections),
        "profile_count": len(profiles),
        "official_sumo_reference_count": sum(
            int(row["official_sumo_reference"]) for row in intersections
        ),
        "osm_modeled_count": sum(
            int(not row["official_sumo_reference"]) for row in intersections
        ),
        "lane_evidence_match_count": sum(
            int(row["lane_counts_match_evidence"]) for row in intersections
        ),
        "lane_configuration_traceable_count": sum(
            int(row["lane_configuration_traceable"]) for row in intersections
        ),
        "workbook_source_consistent_count": sum(
            int(row["workbook_source_consistent"]) for row in intersections
        ),
        "flow_interval_exact_count": sum(int(row["flow_intervals_exact"]) for row in profiles),
        "signal_components_exact_count": sum(
            int(row["signal_components_exact"]) for row in profiles
        ),
        "theme_gui_exact_count": sum(int(row["theme_gui_exact"]) for row in profiles),
        "sumo_exit_ok_count": sum(int(row["sumo_exit_code"] == 0) for row in profiles),
        "demand_conservation_count": sum(
            int(row["demand_conservation"]) for row in profiles
        ),
        "cleared_profile_count": sum(int(row["all_vehicles_cleared"]) for row in profiles),
        "collision_count": sum(int(row["collisions"]) for row in profiles),
        "teleport_count": sum(int(row["teleports"]) for row in profiles),
        "organizer_source_issue_count": len(source_issues),
        "geometry_arm_count": len(geometry_rows),
        "geometry_adjustment_count": sum(
            int(row["adjustment_type"] != "none") for row in geometry_rows
        ),
        "evidence_boundary": (
            "1-4号参考主办方SUMO示例; 5-20号为主办方Excel/PNG加OSM工程模型, "
            "不是主办方提供的SUMO真值或测绘级车道数据"
        ),
    }
    payload = {
        "schema_version": "1.0",
        "summary": summary,
        "intersections": intersections,
        "profiles": profiles,
        "geometry": geometry_rows,
        "organizer_source_issues": source_issues,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "official_20_audit.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_csv(
        output_dir / "official_20_intersections.csv",
        intersections,
        [
            "demo_id",
            "provenance_class",
            "official_sumo_reference",
            "lane_evidence_method",
            "lane_confidence",
            "lane_counts_match_evidence",
            "lane_configuration_status",
            "lane_configuration_traceable",
            "workbook_source_consistent",
            "geometry_adjustment_count",
            "structurally_valid",
            "profiles_cleared",
        ],
    )
    _write_csv(
        output_dir / "official_20_profiles.csv",
        profiles,
        [
            "demo_id",
            "profile",
            "expected_demand",
            "generated_demand",
            "flow_intervals_exact",
            "signal_components_exact",
            "theme_gui_exact",
            "source_profile_consistent",
            "loaded",
            "tripinfo_count",
            "final_running",
            "final_waiting",
            "demand_conservation",
            "all_vehicles_cleared",
            "collisions",
            "teleports",
            "sumo_exit_code",
        ],
    )
    _write_csv(
        output_dir / "official_20_geometry.csv",
        geometry_rows,
        [
            "demo_id",
            "arm",
            "geometry_source",
            "evidence_length_m",
            "modeled_length_m",
            "sumo_effective_in_m",
            "sumo_effective_out_m",
            "adjustment_type",
            "length_confidence",
            "cutoff_reason",
        ],
    )
    _write_csv(
        output_dir / "official_20_source_issues.csv",
        source_issues,
        [
            "demo_id",
            "profile",
            "category",
            "field",
            "source",
            "calculated",
            "display_tolerance",
        ],
    )
    return {"status": "audited", "output": str(json_path), **summary}
