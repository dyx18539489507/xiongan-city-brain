"""Validate stable SUMO TLS/link/lane mappings emitted by the scene generator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validate(scene: dict[str, Any], mapping: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    lane_ids = {str(lane["sumoLaneId"]) for lane in scene.get("lanes", [])}
    scene_controllers = {
        str(controller["sumoTlsId"]): controller
        for controller in scene.get("trafficLights", [])
    }
    mapping_controllers = mapping.get("controllers", [])
    if mapping.get("sceneId") != scene.get("metadata", {}).get("sceneId"):
        errors.append("sceneId mismatch")
    if len(mapping_controllers) != len(scene_controllers):
        errors.append("controller count mismatch")

    for controller in mapping_controllers:
        tls_id = str(controller.get("sumoTlsId", ""))
        scene_controller = scene_controllers.get(tls_id)
        if scene_controller is None:
            errors.append(f"unknown TLS {tls_id}")
            continue
        links = controller.get("links", [])
        indexes = [int(link["linkIndex"]) for link in links]
        if len(indexes) != len(set(indexes)):
            errors.append(f"TLS {tls_id}: duplicate linkIndex")
        for link in links:
            lane_id = str(link["fromLaneId"])
            if lane_id not in lane_ids:
                errors.append(f"TLS {tls_id}: missing fromLane {lane_id}")
        required_state_length = max(indexes, default=-1) + 1
        for phase_index, length in enumerate(controller.get("phaseStateLengths", [])):
            if int(length) < required_state_length:
                errors.append(
                    f"TLS {tls_id}: phase {phase_index} state length {length} "
                    f"< required {required_state_length}"
                )
        scene_links = scene_controller.get("links", [])
        if links != scene_links:
            errors.append(f"TLS {tls_id}: mapping links differ from scene links")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scene", type=Path)
    parser.add_argument("mapping", type=Path)
    args = parser.parse_args()
    scene = json.loads(args.scene.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    errors = validate(scene, mapping)
    report = {
        "valid": not errors,
        "controllers": len(mapping.get("controllers", [])),
        "links": sum(len(item.get("links", [])) for item in mapping.get("controllers", [])),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
