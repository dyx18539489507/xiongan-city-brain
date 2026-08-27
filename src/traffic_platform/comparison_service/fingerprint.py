"""Reproducible manifests for a same-condition paired SUMO run."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _referenced_sumo_files(config_path: Path) -> list[tuple[str, Path]]:
    """Return direct SUMO input files named by a ``.sumocfg`` document."""

    root = ElementTree.parse(config_path).getroot()
    inputs = root.find("input")
    if inputs is None:
        return []

    references: list[tuple[str, Path]] = []
    for element in inputs:
        raw_value = element.attrib.get("value", "")
        for raw_path in raw_value.split(","):
            value = raw_path.strip()
            if not value:
                continue
            resolved = (config_path.parent / value).resolve()
            references.append((element.tag, resolved))
    return references


def _display_path(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def build_fairness_manifest(
    *,
    sumo_config: str | Path,
    scenario_id: str,
    scenario_profile: str,
    seed: int,
    duration_s: float,
    scheduled_faults: Sequence[Mapping[str, Any]] = (),
    communication_profile: Mapping[str, Any] | None = None,
    runtime_files: Mapping[str, str | Path] | None = None,
) -> dict[str, Any]:
    """Build the immutable common-input manifest shared by both algorithms.

    Algorithm identifiers are intentionally excluded: a pair is fair only when
    every item in this manifest is identical while the algorithms differ.
    """

    config_path = Path(sumo_config).resolve()
    if not config_path.is_file():
        raise FileNotFoundError(f"SUMO configuration does not exist: {config_path}")

    base = config_path.parent
    files: list[dict[str, Any]] = [
        {
            "role": "sumo-config",
            "path": config_path.name,
            "bytes": config_path.stat().st_size,
            "sha256": _sha256(config_path),
        }
    ]
    seen = {config_path}
    for role, path in _referenced_sumo_files(config_path):
        if path in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(
                f"SUMO input referenced by {config_path.name} does not exist: {path}"
            )
        seen.add(path)
        files.append(
            {
                "role": role,
                "path": _display_path(path, base),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    for role, raw_path in sorted((runtime_files or {}).items()):
        path = Path(raw_path).resolve()
        if path in seen:
            continue
        if not path.is_file():
            raise FileNotFoundError(f"paired runtime input does not exist: {path}")
        seen.add(path)
        files.append(
            {
                "role": role,
                "path": _display_path(path, base),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )

    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "scenario_profile": scenario_profile,
        "seed": int(seed),
        "duration_s": float(duration_s),
        "scheduled_faults": [dict(item) for item in scheduled_faults],
        "communication_profile": dict(communication_profile or {}),
        "files": files,
    }


def fairness_fingerprint(manifest: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 fingerprint for a fairness manifest."""

    canonical = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
