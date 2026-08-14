"""Read-only inventory of organizer intersection and SUMO assets."""

import hashlib
import json
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_official_inventory(source_root: Path) -> dict[str, Any]:
    """Hash and classify organizer files without copying or modifying them."""

    if not source_root.is_dir():
        raise FileNotFoundError(source_root)
    workbooks = sorted(source_root.rglob("*.xlsx"))
    map_images = sorted(source_root.rglob("*.png"))
    sumo_configs = sorted(source_root.rglob("*.sumocfg"))
    sumo_files = sorted(
        path
        for path in source_root.rglob("*.xml")
        if "路口仿真案例" in str(path)
    )
    if len(workbooks) != 20 or len(map_images) != 20:
        raise ValueError(
            "organizer intersection collection must contain 20 workbooks and 20 maps"
        )
    assets = [
        {
            "relative_path": path.relative_to(source_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in [*workbooks, *map_images, *sumo_configs, *sumo_files]
    ]
    return {
        "schema_version": "1.0",
        "scenario_id": "official_20_independent",
        "source_policy": "read_only_external",
        "network_relationship": "independent_intersections_not_one_connected_network",
        "claims": {
            "organizer_intersection_count": 20,
            "supplied_sumo_case_count": len(sumo_configs),
            "is_connected_regional_network": False,
        },
        "counts": {
            "xlsx": len(workbooks),
            "map_png": len(map_images),
            "sumocfg": len(sumo_configs),
            "sumo_xml": len(sumo_files),
        },
        "assets": assets,
    }


def write_official_inventory(source_root: Path, output: Path) -> dict[str, Any]:
    """Write a derived inventory manifest outside the organizer source tree."""

    manifest = build_official_inventory(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest
