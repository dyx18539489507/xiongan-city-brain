"""Source-first scenario drafts for OSM selections and planning drawings.

Drafts deliberately live outside ``scenarios/generated``.  A draft is editable,
may be low-confidence, and is never treated as a runnable SUMO scenario until a
separate publish build succeeds.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import ezdxf
import numpy as np
import osmium
import pymupdf
import shapefile
import sumolib
from PIL import Image, ImageOps
from pyproj import CRS, Transformer
from shapely import wkb
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon, box, shape
from shapely.ops import substring, transform, unary_union

ProgressCallback = Callable[[int, str], None]
SUPPORTED_PLANNING_SUFFIXES = {
    ".dxf",
    ".geojson",
    ".json",
    ".gpkg",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".zip",
}
SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DRAFT_IO_LOCK = threading.RLock()
HEBEI_OSM_SNAPSHOT = Path("scenarios/source/hebei-2026-08-21.osm.pbf")
HEBEI_OSM_INDEX = Path("scenarios/source/hebei-2026-08-21-roads.sqlite")
HEBEI_OSM_CONTEXT_INDEX = Path("scenarios/source/hebei-2026-08-21-context.sqlite")
HEBEI_OSM_SNAPSHOT_DATE = "2026-08-21"
OSM_ROAD_CONTEXT_MAX_M = 90.0
OSM_ROAD_CONTEXT_FALLBACK_M = 60.0
OSM_JUNCTION_JOIN_DISTANCE_M = 25.0
OSM_ROAD_TAG_KEYS = {
    "access",
    "bridge",
    "busway",
    "cycleway",
    "highway",
    "junction",
    "lanes",
    "layer",
    "maxspeed",
    "motor_vehicle",
    "name",
    "oneway",
    "service",
    "sidewalk",
    "surface",
    "tunnel",
}
OSM_ROAD_TAG_PREFIXES = (
    "busway:",
    "cycleway:",
    "lanes:",
    "maxspeed:",
    "sidewalk:",
    "turn:lanes",
)
OSM_URBAN_DEFAULT_SPEEDS_KMH = {
    "motorway": 100,
    "motorway_link": 60,
    "trunk": 80,
    "trunk_link": 50,
    "primary": 50,
    "primary_link": 40,
    "secondary": 40,
    "secondary_link": 30,
    "tertiary": 40,
    "tertiary_link": 30,
    "unclassified": 30,
    "residential": 30,
    "living_street": 20,
    "service": 20,
}
OSM_CONTEXT_WAY_KEYS = {"building", "landuse", "leisure", "natural", "water", "waterway", "amenity"}
OSM_CONTEXT_INDEX_LOCK = threading.Lock()


def _preserved_osm_road_tags(tags: dict[str, str]) -> dict[str, str]:
    return {
        str(key): str(value)
        for key, value in tags.items()
        if key in OSM_ROAD_TAG_KEYS or key.startswith(OSM_ROAD_TAG_PREFIXES)
    }


def _effective_osm_road_tags(
    highway: str,
    name: str,
    tags: dict[str, str] | None,
) -> dict[str, str]:
    result = _preserved_osm_road_tags(tags or {})
    result["highway"] = highway
    if name:
        result["name"] = name
    if not result.get("maxspeed"):
        default_speed = OSM_URBAN_DEFAULT_SPEEDS_KMH.get(highway)
        if default_speed is not None:
            result["maxspeed"] = str(default_speed)
    return result


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _draft_root(workspace: Path) -> Path:
    path = workspace / "scenarios" / "drafts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def draft_dir(workspace: Path, draft_id: str) -> Path:
    if not re.fullmatch(r"draft-[a-f0-9]{12}", draft_id):
        raise ValueError("invalid draft id")
    return _draft_root(workspace) / draft_id


def _draft_path(workspace: Path, draft_id: str) -> Path:
    return draft_dir(workspace, draft_id) / "draft.json"


def save_draft(workspace: Path, draft: dict[str, Any]) -> dict[str, Any]:
    """Atomically persist a JSON draft so API restarts do not lose work."""

    draft["updated_at"] = _now()
    folder = draft_dir(workspace, str(draft["id"]))
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "draft.json"
    temporary = folder / "draft.json.tmp"
    with DRAFT_IO_LOCK:
        temporary.write_text(
            json.dumps(draft, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                temporary.replace(target)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.01 * (attempt + 1))
    return draft


def load_draft(workspace: Path, draft_id: str) -> dict[str, Any]:
    path = _draft_path(workspace, draft_id)
    if not path.is_file():
        raise FileNotFoundError(draft_id)
    with DRAFT_IO_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def load_drafts(workspace: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(_draft_root(workspace).glob("draft-*/draft.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") in {"queued", "processing"}:
                record.update(
                    status="failed",
                    message="服务重启中断了解析, 请重新创建草稿",
                    error="draft processing was interrupted by a service restart",
                )
                save_draft(workspace, record)
            records[str(record["id"])] = record
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return records


def create_draft_record(
    workspace: Path,
    draft_id: str,
    source_type: str,
    source: dict[str, Any],
) -> dict[str, Any]:
    created = _now()
    record: dict[str, Any] = {
        "id": draft_id,
        "status": "queued",
        "progress": 0,
        "message": "等待解析",
        "source_type": source_type,
        "source": source,
        "coordinate_mode": "geographic" if source_type == "osm_bbox" else "local",
        "confidence": "unknown",
        "requires_manual_review": False,
        "review_confirmed": True,
        "preview": {
            "bounds": None,
            "roads": [],
            "buildings": [],
            "intersections": [],
            "topology_edges": [],
        },
        "selected_intersection_ids": [],
        "manual_edits": [],
        "validation": None,
        "artifacts": {},
        "logs": [],
        "error": None,
        "created_at": created,
        "updated_at": created,
    }
    return save_draft(workspace, record)


def update_draft(
    workspace: Path,
    draft_id: str,
    *,
    selected_intersection_ids: list[str] | None = None,
    review_confirmed: bool | None = None,
    roads: list[dict[str, Any]] | None = None,
    intersections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    draft = load_draft(workspace, draft_id)
    preview = draft["preview"]
    if roads is not None:
        preview["roads"] = roads
        draft["manual_edits"].append({"time": _now(), "type": "replace_roads"})
    if intersections is not None:
        preview["intersections"] = intersections
        draft["manual_edits"].append({"time": _now(), "type": "replace_intersections"})
    known = {str(item["intersection_id"]) for item in preview["intersections"]}
    if selected_intersection_ids is not None:
        selected = list(dict.fromkeys(selected_intersection_ids))
        unknown = [item for item in selected if item not in known]
        if unknown:
            raise ValueError(f"unknown intersections: {', '.join(unknown)}")
        draft["selected_intersection_ids"] = selected
    if review_confirmed is not None:
        draft["review_confirmed"] = review_confirmed
    draft["validation"] = validate_draft(draft)
    return save_draft(workspace, draft)


def validate_draft(draft: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    selected = draft.get("selected_intersection_ids", [])
    preview = draft.get("preview", {})
    if draft.get("status") != "ready":
        errors.append("来源尚未解析完成")
    if not preview.get("roads"):
        errors.append("没有可构建的道路中心线")
    if not selected:
        errors.append("至少选择一个路口")
    if draft.get("confidence") == "low":
        warnings.append("扫描件已自动生成规范化路网, 请结合原图核对识别结果")
    return {
        "valid": not errors,
        "selected_intersection_count": len(selected),
        "selected_intersection_ids": selected,
        "errors": errors,
        "warnings": warnings,
        "rule": "selected_count_is_authoritative",
        "source_type": draft.get("source_type"),
        "confidence": draft.get("confidence"),
        "review_confirmed": draft.get("review_confirmed", False),
    }


def store_upload(
    workspace: Path,
    draft_id: str,
    filename: str,
    content: bytes,
) -> Path:
    if not content:
        raise ValueError("uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("planning file exceeds the 50 MB limit")
    safe_name = SAFE_NAME.sub("-", Path(filename).name).strip(".-") or "planning-file"
    suffix = Path(safe_name).suffix.lower()
    if suffix not in SUPPORTED_PLANNING_SUFFIXES:
        raise ValueError(f"unsupported planning file type: {suffix or 'unknown'}")
    folder = draft_dir(workspace, draft_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"source{suffix}"
    path.write_bytes(content)
    return path


def _progress(
    workspace: Path,
    draft: dict[str, Any],
    value: int,
    message: str,
    callback: ProgressCallback | None,
) -> None:
    draft.update(status="processing", progress=value, message=message, error=None)
    draft["logs"].append({"time": _now(), "progress": value, "message": message})
    save_draft(workspace, draft)
    if callback is not None:
        callback(value, message)


def _sumo_binary(sumo_home: Path, name: str) -> Path:
    candidate = sumo_home / "bin" / (f"{name}.exe" if sys.platform == "win32" else name)
    if not candidate.is_file():
        raise FileNotFoundError(f"{name} was not found under {sumo_home}")
    return candidate


def _run(command: list[str], cwd: Path, timeout: int = 300) -> None:
    environment = os.environ.copy()
    if Path(command[0]).stem.lower() == "netconvert":
        # The bundled Windows netconvert cannot load typemaps from a
        # SUMO_HOME path containing non-ASCII characters. The binary carries
        # the same standard typemaps internally, so isolate only this child.
        environment.pop("SUMO_HOME", None)
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
        raise RuntimeError(
            f"stdout:\n{process.stdout[-3000:]}\nstderr:\n{process.stderr[-3000:]}"
        )


def _validate_bbox(bbox: dict[str, float]) -> tuple[float, float, float, float]:
    try:
        west = float(bbox["west"])
        south = float(bbox["south"])
        east = float(bbox["east"])
        north = float(bbox["north"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bbox requires west, south, east and north") from exc
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("invalid longitude/latitude order")
    if east - west > 0.12 or north - south > 0.12:
        raise ValueError("selection is too large; each side must be at most 0.12 degrees")
    if (east - west) * (north - south) < 1e-8:
        raise ValueError("selection is too small")
    return west, south, east, north


def _expand_bbox_by_meters(
    bbox: tuple[float, float, float, float],
    buffer_m: float = OSM_ROAD_CONTEXT_MAX_M,
) -> tuple[float, float, float, float]:
    """Keep the user's selection exact while adding routing context around it."""

    if buffer_m < 0:
        raise ValueError("buffer_m must be non-negative")
    west, south, east, north = bbox
    center_latitude = (south + north) / 2.0
    latitude_delta = buffer_m / 111_320.0
    longitude_scale = max(0.01, math.cos(math.radians(center_latitude)))
    longitude_delta = buffer_m / (111_320.0 * longitude_scale)
    return (
        max(-180.0, west - longitude_delta),
        max(-90.0, south - latitude_delta),
        min(180.0, east + longitude_delta),
        min(90.0, north + latitude_delta),
    )


def _local_osm_snapshot(workspace: Path) -> Path:
    path = workspace / HEBEI_OSM_SNAPSHOT
    if not path.is_file():
        raise FileNotFoundError(
            f"河北 OSM 本地快照不存在: {path}. 请先下载固定快照 {HEBEI_OSM_SNAPSHOT_DATE}"
        )
    return path


def _osmium_read_path(path: Path) -> str:
    """Use a relative path because libosmium on Windows cannot open Unicode absolutes."""

    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


def _extract_local_osm(
    workspace: Path,
    target: Path,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    """Export only roads crossing the selection, extended along their own corridors."""

    west, south, east, north = bbox
    search_bbox = _expand_bbox_by_meters(bbox, OSM_ROAD_CONTEXT_MAX_M)
    index = workspace / HEBEI_OSM_INDEX
    if not index.is_file():
        raise FileNotFoundError(f"河北 OSM 道路索引不存在: {index}")

    selection_bounds = box(west, south, east, north)
    search_west, search_south, search_east, search_north = search_bbox
    rows: list[tuple[int, str, str, list[list[float]], dict[str, str]]] = []
    with sqlite3.connect(index) as connection:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(roads)")
        }
        tag_column = "tags_json" if "tags_json" in columns else None
        select_tags = ", tags_json" if tag_column else ""
        query = f"""SELECT osm_id, highway, name, coordinates{select_tags}
            FROM roads
            WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
            ORDER BY osm_id
            LIMIT 50000"""
        for row in connection.execute(
            query,
            (search_east, search_west, search_north, search_south),
        ):
            osm_id, highway, name, raw_coordinates = row[:4]
            coordinates = json.loads(raw_coordinates)
            if len(coordinates) >= 2:
                raw_tags = row[4] if tag_column else None
                try:
                    tags = json.loads(raw_tags) if raw_tags else {}
                except (TypeError, ValueError):
                    tags = {}
                rows.append(
                    (
                        int(osm_id),
                        str(highway),
                        str(name),
                        coordinates,
                        _effective_osm_road_tags(str(highway), str(name), tags),
                    )
                )

    selected_rows = [
        row for row in rows if LineString(row[3]).intersects(selection_bounds)
    ]
    if not selected_rows:
        raise ValueError("框选范围在河北本地快照中没有可运行道路")

    center_lon = (west + east) / 2.0
    center_lat = (south + north) / 2.0
    zone = int((center_lon + 180.0) // 6.0) + 1
    epsg = 32600 + zone if center_lat >= 0 else 32700 + zone
    forward = Transformer.from_crs(4326, epsg, always_xy=True)
    inverse = Transformer.from_crs(epsg, 4326, always_xy=True)
    selection_projected = transform(forward.transform, selection_bounds)
    projected_rows = {
        osm_id: transform(forward.transform, LineString(coordinates))
        for osm_id, _highway, _name, coordinates, _tags in rows
    }

    def positions_on(line: LineString, geometry: Any) -> list[float]:
        if geometry.is_empty:
            return []
        if geometry.geom_type == "Point":
            return [line.project(geometry)]
        if geometry.geom_type == "LineString":
            coordinates = list(geometry.coords)
            if not coordinates:
                return []
            return [line.project(Point(coordinates[0])), line.project(Point(coordinates[-1]))]
        positions: list[float] = []
        for part in getattr(geometry, "geoms", []):
            positions.extend(positions_on(line, part))
        return positions

    nodes: dict[tuple[float, float], int] = {}
    ways: list[tuple[int, list[int], dict[str, str], int]] = []
    next_node_id = -1
    next_way_id = -1
    extension_records: list[dict[str, Any]] = []
    for osm_id, _highway, _name, _coordinates, tags in selected_rows:
        projected_line = projected_rows[osm_id]
        selected_positions = positions_on(
            projected_line,
            projected_line.intersection(selection_projected),
        )
        if not selected_positions:
            continue
        selected_start = min(selected_positions)
        selected_end = max(selected_positions)
        junction_positions: list[float] = []
        for other_id, other_line in projected_rows.items():
            if other_id == osm_id:
                continue
            junction_positions.extend(
                positions_on(projected_line, projected_line.intersection(other_line))
            )
        before = [
            value
            for value in junction_positions
            if selected_start - OSM_ROAD_CONTEXT_MAX_M <= value < selected_start - 0.5
        ]
        after = [
            value
            for value in junction_positions
            if selected_end + 0.5 < value <= selected_end + OSM_ROAD_CONTEXT_MAX_M
        ]
        segment_start = (
            max(before)
            if before
            else max(0.0, selected_start - OSM_ROAD_CONTEXT_FALLBACK_M)
        )
        segment_end = (
            min(after)
            if after
            else min(projected_line.length, selected_end + OSM_ROAD_CONTEXT_FALLBACK_M)
        )
        projected_segment = substring(projected_line, segment_start, segment_end)
        if projected_segment.geom_type != "LineString":
            continue
        geographic_segment = transform(inverse.transform, projected_segment)
        part_coordinates: list[tuple[float, float]] = []
        for lon, lat in geographic_segment.coords:
            point = (round(float(lon), 9), round(float(lat), 9))
            if not part_coordinates or part_coordinates[-1] != point:
                part_coordinates.append(point)
        if len(part_coordinates) < 2:
            continue
        references: list[int] = []
        for point in part_coordinates:
            identifier = nodes.get(point)
            if identifier is None:
                identifier = next_node_id
                next_node_id -= 1
                nodes[point] = identifier
            references.append(identifier)
        ways.append((next_way_id, references, tags, osm_id))
        next_way_id -= 1
        extension_records.append(
            {
                "source_way_id": osm_id,
                "before_selection_m": round(selected_start - segment_start, 3),
                "after_selection_m": round(segment_end - selected_end, 3),
                "before_boundary": "nearest_intersection" if before else "fallback_stub",
                "after_boundary": "nearest_intersection" if after else "fallback_stub",
            }
        )

    if not ways or not nodes:
        raise ValueError("框选范围内道路无法形成可运行的SUMO走廊")

    longitudes = [point[0] for point in nodes]
    latitudes = [point[1] for point in nodes]
    network_bbox = (min(longitudes), min(latitudes), max(longitudes), max(latitudes))

    root = ET.Element("osm", {"version": "0.6", "generator": "XionganLocalHebeiOSM/1.0"})
    ET.SubElement(
        root,
        "bounds",
        {
            "minlon": str(network_bbox[0]),
            "minlat": str(network_bbox[1]),
            "maxlon": str(network_bbox[2]),
            "maxlat": str(network_bbox[3]),
        },
    )
    for (lon, lat), identifier in sorted(nodes.items(), key=lambda item: item[1], reverse=True):
        ET.SubElement(
            root,
            "node",
            {"id": str(identifier), "lon": str(lon), "lat": str(lat), "version": "1"},
        )
    for identifier, references, tags, source_way_id in ways:
        element = ET.SubElement(
            root,
            "way",
            {"id": str(identifier), "visible": "true", "version": "1"},
        )
        for reference in references:
            ET.SubElement(element, "nd", {"ref": str(reference)})
        for key, value in sorted(tags.items()):
            ET.SubElement(element, "tag", {"k": key, "v": value})
        ET.SubElement(element, "tag", {"k": "source_way_id", "v": str(source_way_id)})
    context_counts = _append_local_osm_context(
        workspace,
        root,
        _expand_bbox_by_meters(network_bbox, 120.0),
    )
    _write_xml(target, root)
    return {
        "strategy": "intersecting_road_corridors_to_nearest_intersection",
        "maximum_extension_m": OSM_ROAD_CONTEXT_MAX_M,
        "fallback_extension_m": OSM_ROAD_CONTEXT_FALLBACK_M,
        "network_bbox": {
            "west": network_bbox[0],
            "south": network_bbox[1],
            "east": network_bbox[2],
            "north": network_bbox[3],
        },
        "selected_source_way_count": len(ways),
        "context_feature_counts": context_counts,
        "corridors": extension_records,
        "controlled_intersections_limited_to_selection": True,
    }


class _OsmRoadIndexBuilder(osmium.SimpleHandler):
    def __init__(self, connection: sqlite3.Connection) -> None:
        super().__init__()
        self.connection = connection
        self.pending: list[
            tuple[int, str, str, float, float, float, float, str, str]
        ] = []

    def way(self, way: Any) -> None:
        tags = dict(way.tags)
        highway = tags.get("highway")
        if not highway:
            return
        coordinates: list[list[float]] = []
        for node in way.nodes:
            if not node.location.valid():
                continue
            coordinates.append([float(node.location.lon), float(node.location.lat)])
        if len(coordinates) < 2:
            return
        xs = [point[0] for point in coordinates]
        ys = [point[1] for point in coordinates]
        self.pending.append(
            (
                int(way.id),
                highway,
                tags.get("name", ""),
                min(xs),
                max(xs),
                min(ys),
                max(ys),
                json.dumps(coordinates, separators=(",", ":")),
                json.dumps(
                    _preserved_osm_road_tags(tags),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            )
        )
        if len(self.pending) >= 2000:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        self.connection.executemany(
            """INSERT INTO roads (
                osm_id, highway, name, min_lon, max_lon, min_lat, max_lat, coordinates,
                tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            self.pending,
        )
        self.pending.clear()


def build_local_osm_context_index(workspace: Path) -> Path:
    """Build a one-time local index for OSM urban context near generated roads."""

    source = _local_osm_snapshot(workspace)
    target = workspace / HEBEI_OSM_CONTEXT_INDEX
    with OSM_CONTEXT_INDEX_LOCK:
        if target.is_file():
            return target
        temporary = target.with_suffix(".sqlite.tmp")
        temporary.unlink(missing_ok=True)
        connection = sqlite3.connect(temporary)
        try:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute(
                """CREATE TABLE features (
                    id INTEGER PRIMARY KEY,
                    osm_type TEXT NOT NULL,
                    osm_id INTEGER NOT NULL,
                    min_lon REAL NOT NULL,
                    max_lon REAL NOT NULL,
                    min_lat REAL NOT NULL,
                    max_lat REAL NOT NULL,
                    coordinates TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    UNIQUE (osm_type, osm_id)
                )"""
            )
            source_path = _osmium_read_path(source)
            way_filter = osmium.filter.KeyFilter(*sorted(OSM_CONTEXT_WAY_KEYS))
            way_records: list[tuple[int, list[int], dict[str, str]]] = []
            required_node_ids: set[int] = set()
            for way in osmium.FileProcessor(
                source_path,
                entities=osmium.osm.WAY,
            ).with_filter(way_filter):
                references = [int(node.ref) for node in way.nodes]
                if len(references) < 4 or references[0] != references[-1]:
                    continue
                way_records.append((int(way.id), references, dict(way.tags)))
                required_node_ids.update(references)

            node_filter = osmium.filter.IdFilter(required_node_ids)
            node_filter.enable_for(osmium.osm.NODE)
            node_locations: dict[int, tuple[float, float]] = {}
            for node in osmium.FileProcessor(
                source_path,
                entities=osmium.osm.NODE,
            ).with_filter(node_filter):
                if node.location.valid():
                    node_locations[int(node.id)] = (
                        float(node.location.lon),
                        float(node.location.lat),
                    )

            pending: list[tuple[str, int, float, float, float, float, str, str]] = []
            for osm_id, references, tags in way_records:
                if any(reference not in node_locations for reference in references):
                    continue
                coordinates: list[list[float | int]] = [
                    [reference, *node_locations[reference]] for reference in references
                ]
                longitudes = [float(point[1]) for point in coordinates]
                latitudes = [float(point[2]) for point in coordinates]
                pending.append(
                    (
                        "way",
                        osm_id,
                        min(longitudes),
                        max(longitudes),
                        min(latitudes),
                        max(latitudes),
                        json.dumps(coordinates, separators=(",", ":")),
                        json.dumps(tags, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    )
                )
                if len(pending) >= 2000:
                    connection.executemany(
                        """INSERT INTO features (
                            osm_type, osm_id, min_lon, max_lon, min_lat, max_lat,
                            coordinates, tags_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        pending,
                    )
                    pending.clear()
            if pending:
                connection.executemany(
                    """INSERT INTO features (
                        osm_type, osm_id, min_lon, max_lon, min_lat, max_lat,
                        coordinates, tags_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    pending,
                )
            connection.execute("CREATE INDEX features_lon ON features (min_lon, max_lon)")
            connection.execute("CREATE INDEX features_lat ON features (min_lat, max_lat)")
            connection.execute("CREATE INDEX features_type ON features (osm_type)")
            connection.commit()
        finally:
            connection.close()
        temporary.replace(target)
    return target


def _append_local_osm_context(
    workspace: Path,
    root: ET.Element,
    bbox: tuple[float, float, float, float],
) -> dict[str, int]:
    index = workspace / HEBEI_OSM_CONTEXT_INDEX
    if not index.is_file():
        if not (workspace / HEBEI_OSM_SNAPSHOT).is_file():
            return {"ways": 0, "nodes": 0}
        index = build_local_osm_context_index(workspace)

    west, south, east, north = bbox
    with sqlite3.connect(index) as connection:
        rows = list(
            connection.execute(
                """SELECT osm_type, osm_id, coordinates, tags_json
                FROM features
                WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
                ORDER BY osm_type, osm_id
                LIMIT 20000""",
                (east, west, north, south),
            )
        )

    existing_nodes = {element.attrib["id"]: element for element in root.findall("node")}
    existing_ways = {element.attrib["id"] for element in root.findall("way")}
    appended_nodes: set[str] = set()
    appended_ways = 0
    for osm_type, osm_id, raw_coordinates, raw_tags in rows:
        coordinates = json.loads(raw_coordinates)
        tags = json.loads(raw_tags)
        if osm_type == "node":
            node_id, lon, lat = coordinates[0]
            identifier = str(node_id)
            node_element = existing_nodes.get(identifier)
            if node_element is None:
                node_element = ET.SubElement(
                    root,
                    "node",
                    {"id": identifier, "lon": str(lon), "lat": str(lat), "version": "1"},
                )
                existing_nodes[identifier] = node_element
                appended_nodes.add(identifier)
            for key, value in sorted(tags.items()):
                ET.SubElement(node_element, "tag", {"k": str(key), "v": str(value)})
            continue

        way_identifier = str(osm_id)
        if way_identifier in existing_ways:
            continue
        references: list[str] = []
        for node_id, lon, lat in coordinates:
            identifier = str(node_id)
            references.append(identifier)
            if identifier in existing_nodes:
                continue
            existing_nodes[identifier] = ET.SubElement(
                root,
                "node",
                {"id": identifier, "lon": str(lon), "lat": str(lat), "version": "1"},
            )
            appended_nodes.add(identifier)
        element = ET.SubElement(
            root,
            "way",
            {"id": way_identifier, "visible": "true", "version": "1"},
        )
        for reference in references:
            ET.SubElement(element, "nd", {"ref": reference})
        for key, value in sorted(tags.items()):
            ET.SubElement(element, "tag", {"k": str(key), "v": str(value)})
        existing_ways.add(way_identifier)
        appended_ways += 1
    metadata = [element for element in root if element.tag not in {"node", "way"}]
    ordered_nodes = list(root.findall("node"))
    ordered_ways = list(root.findall("way"))
    root[:] = [*metadata, *ordered_nodes, *ordered_ways]
    return {"ways": appended_ways, "nodes": len(appended_nodes)}


def build_local_osm_index(workspace: Path) -> Path:
    """Build the one-time local road index for the fixed Hebei snapshot."""

    source = _local_osm_snapshot(workspace)
    target = workspace / HEBEI_OSM_INDEX
    temporary = target.with_suffix(".sqlite.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            """CREATE TABLE roads (
                id INTEGER PRIMARY KEY,
                osm_id INTEGER NOT NULL,
                highway TEXT NOT NULL,
                name TEXT NOT NULL,
                min_lon REAL NOT NULL,
                max_lon REAL NOT NULL,
                min_lat REAL NOT NULL,
                max_lat REAL NOT NULL,
                coordinates TEXT NOT NULL,
                tags_json TEXT NOT NULL
            )"""
        )
        builder = _OsmRoadIndexBuilder(connection)
        builder.apply_file(_osmium_read_path(source), locations=True, idx="flex_mem")
        builder.flush()
        connection.execute("CREATE INDEX roads_lon ON roads (min_lon, max_lon)")
        connection.execute("CREATE INDEX roads_lat ON roads (min_lat, max_lat)")
        connection.execute("CREATE INDEX roads_class ON roads (highway)")
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO metadata (key, value) VALUES (?, ?)",
            [
                ("snapshot_date", HEBEI_OSM_SNAPSHOT_DATE),
                ("source_file", source.name),
                ("road_tags_schema", "1"),
            ],
        )
        connection.commit()
    finally:
        connection.close()
    temporary.replace(target)
    _cached_local_osm_map.cache_clear()
    return target


@lru_cache(maxsize=96)
def _cached_local_osm_map(
    index_path: str,
    west: float,
    south: float,
    east: float,
    north: float,
) -> dict[str, Any]:
    span = max(east - west, north - south)
    if span > 1.2:
        road_classes = ("motorway", "motorway_link", "trunk", "trunk_link")
    elif span > 0.28:
        road_classes = (
            "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link"
        )
    elif span > 0.07:
        road_classes = (
            "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
            "secondary", "secondary_link", "tertiary", "tertiary_link",
        )
    else:
        road_classes = ()
    parameters: list[Any] = [east, west, north, south]
    class_clause = ""
    if road_classes:
        placeholders = ",".join("?" for _item in road_classes)
        class_clause = f" AND highway IN ({placeholders})"
        parameters.extend(road_classes)
    query = f"""SELECT osm_id, highway, name, coordinates
        FROM roads
        WHERE min_lon <= ? AND max_lon >= ? AND min_lat <= ? AND max_lat >= ?
        {class_clause}
        LIMIT 12000"""
    features: list[dict[str, Any]] = []
    tolerance = span / 2500 if span > 0.03 else 0.0
    with sqlite3.connect(index_path) as connection:
        for osm_id, highway, name, raw_coordinates in connection.execute(query, parameters):
            coordinates = json.loads(raw_coordinates)
            if tolerance and len(coordinates) > 2:
                coordinates = [
                    list(point)
                    for point in LineString(coordinates).simplify(tolerance).coords
                ]
            features.append(
                {
                    "type": "Feature",
                    "id": f"way-{osm_id}",
                    "properties": {"highway": highway, "name": name},
                    "geometry": {"type": "LineString", "coordinates": coordinates},
                }
            )
    return {
        "type": "FeatureCollection",
        "snapshot_date": HEBEI_OSM_SNAPSHOT_DATE,
        "features": features,
    }


def local_osm_map(
    workspace: Path,
    bbox: dict[str, float],
) -> dict[str, Any]:
    try:
        values = (
            float(bbox["west"]),
            float(bbox["south"]),
            float(bbox["east"]),
            float(bbox["north"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("bbox requires west, south, east and north") from exc
    west, south, east, north = values
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("invalid longitude/latitude order")
    if east - west > 8 or north - south > 8:
        raise ValueError("map viewport is too large")
    index = workspace / HEBEI_OSM_INDEX
    if not index.is_file():
        raise FileNotFoundError(f"河北 OSM 本地地图索引不存在: {index}")
    rounded = tuple(round(value, 5) for value in values)
    return _cached_local_osm_map(str(index), *rounded)


def _write_xml(path: Path, root: ET.Element) -> None:
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _clip_osm(
    source: Path,
    target: Path,
    bbox: tuple[float, float, float, float],
) -> None:
    """Split highway ways into runs whose nodes are inside the selected bbox."""

    west, south, east, north = bbox
    source_root = ET.parse(source).getroot()
    nodes = {
        node.attrib["id"]: node
        for node in source_root.findall("node")
        if "lon" in node.attrib and "lat" in node.attrib
    }

    def inside(reference: str) -> bool:
        node = nodes.get(reference)
        if node is None:
            return False
        lon = float(node.attrib["lon"])
        lat = float(node.attrib["lat"])
        return west <= lon <= east and south <= lat <= north

    output_root = ET.Element(
        "osm",
        {
            "version": source_root.attrib.get("version", "0.6"),
            "generator": "XionganTrafficScenarioFactory/1.0",
        },
    )
    ET.SubElement(
        output_root,
        "bounds",
        {
            "minlon": str(west),
            "minlat": str(south),
            "maxlon": str(east),
            "maxlat": str(north),
        },
    )
    used_refs: set[str] = set()
    clipped_ways: list[ET.Element] = []
    generated_id = -1
    for way in source_root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "highway" not in tags:
            continue
        references = [item.attrib["ref"] for item in way.findall("nd")]
        run: list[str] = []
        runs: list[list[str]] = []
        for reference in references:
            if inside(reference):
                run.append(reference)
            else:
                if len(run) >= 2:
                    runs.append(run)
                run = []
        if len(run) >= 2:
            runs.append(run)
        for references_inside in runs:
            cloned = ET.Element(
                "way",
                {
                    "id": str(generated_id),
                    "visible": "true",
                    "version": "1",
                },
            )
            generated_id -= 1
            for reference in references_inside:
                used_refs.add(reference)
                ET.SubElement(cloned, "nd", {"ref": reference})
            for key, value in tags.items():
                ET.SubElement(cloned, "tag", {"k": key, "v": value})
            ET.SubElement(cloned, "tag", {"k": "source_way_id", "v": way.attrib["id"]})
            clipped_ways.append(cloned)
    for reference in sorted(used_refs, key=lambda value: int(value)):
        output_root.append(nodes[reference])
    output_root.extend(clipped_ways)
    if not clipped_ways:
        raise ValueError("selected OSM area contains no complete highway segments")
    _write_xml(target, output_root)


def _build_osm_net(
    osm_file: Path,
    network_file: Path,
    sumo_home: Path,
    bbox: tuple[float, float, float, float],
) -> None:
    resolved_osm_file = osm_file.resolve()
    resolved_network_file = network_file.resolve()
    command = [
        str(_sumo_binary(sumo_home, "netconvert")),
        "--osm-files",
        str(resolved_osm_file),
        "--output-file",
        str(resolved_network_file),
        "--roundabouts.guess",
        "true",
        "--tls.guess-signals",
        "true",
        "--tls.discard-simple",
        "false",
        "--osm.sidewalks",
        "false",
        "--osm.crossings",
        "false",
        "--sidewalks.guess",
        "false",
        "--crossings.guess",
        "false",
        "--walkingareas",
        "false",
        "--bikelanes.guess",
        "false",
        "--osm.turn-lanes",
        "true",
        "--remove-edges.by-vclass",
        "tram,rail_urban,subway,cable_car,rail_electric",
        "--remove-edges.isolated",
        "false",
        "--junctions.join",
        "true",
        "--junctions.join-dist",
        f"{OSM_JUNCTION_JOIN_DISTANCE_M:.1f}",
        "--junctions.join-reset",
        "true",
        "--no-turnarounds",
        "true",
    ]
    _run(command, resolved_network_file.parent)


def _osm_buildings(
    osm_file: Path,
    bbox: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    root = ET.parse(osm_file).getroot()
    nodes = {
        node.attrib["id"]: [float(node.attrib["lon"]), float(node.attrib["lat"])]
        for node in root.findall("node")
        if "lon" in node.attrib and "lat" in node.attrib
    }
    buildings: list[dict[str, Any]] = []
    for way in root.findall("way"):
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if "building" not in tags:
            continue
        coordinates = [nodes[ref.attrib["ref"]] for ref in way.findall("nd") if ref.attrib["ref"] in nodes]
        if len(coordinates) >= 4:
            if bbox is not None:
                west, south, east, north = bbox
                center_lon = sum(point[0] for point in coordinates) / len(coordinates)
                center_lat = sum(point[1] for point in coordinates) / len(coordinates)
                if not (west <= center_lon <= east and south <= center_lat <= north):
                    continue
            buildings.append({"id": f"osm-building-{way.attrib['id']}", "coordinates": coordinates})
        if len(buildings) >= 2500:
            break
    return buildings


def _network_preview(
    network_file: Path,
    osm_file: Path | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    network = sumolib.net.readNet(str(network_file), withInternal=False)

    def is_motor_edge(edge: Any) -> bool:
        return not edge.getFunction() and any(
            lane.allows("passenger") for lane in edge.getLanes()
        )

    roads: list[dict[str, Any]] = []
    for edge in network.getEdges(withInternal=False):
        if edge.getFunction() or not edge.getLanes():
            continue
        shape_points = edge.getShape()
        coordinates = [list(network.convertXY2LonLat(x, y)) for x, y in shape_points]
        if len(coordinates) >= 2:
            roads.append(
                {
                    "id": edge.getID(),
                    "coordinates": coordinates,
                    "lane_count": len(edge.getLanes()),
                    "speed_m_s": round(max(lane.getSpeed() for lane in edge.getLanes()), 2),
                }
            )
    intersections: list[dict[str, Any]] = []
    node_neighbors: dict[str, set[str]] = defaultdict(set)
    for edge in network.getEdges(withInternal=False):
        if not is_motor_edge(edge):
            continue
        source = edge.getFromNode().getID()
        target = edge.getToNode().getID()
        node_neighbors[source].add(target)
        node_neighbors[target].add(source)
    for node in network.getNodes():
        if node.getID().startswith(":"):
            continue
        degree = len(node_neighbors[node.getID()])
        signalized = node.getType() in {"traffic_light", "traffic_light_right_on_red"}
        if degree < 3 and not (signalized and degree >= 2):
            continue
        lon, lat = network.convertXY2LonLat(*node.getCoord())
        if bbox is not None:
            west, south, east, north = bbox
            if not (west <= lon <= east and south <= lat <= north):
                continue
        intersections.append(
            {
                "intersection_id": node.getID(),
                "display_id": f"J{len(intersections) + 1:02d}",
                "display_name": f"路口 {len(intersections) + 1}",
                "x": lon,
                "y": lat,
                "lon": lon,
                "lat": lat,
                "degree": degree,
                "signalized": signalized,
            }
        )
    intersection_by_node = {item["intersection_id"]: item for item in intersections}
    topology_seen: set[tuple[str, str]] = set()
    topology_edges: list[dict[str, Any]] = []
    for edge in network.getEdges(withInternal=False):
        if not is_motor_edge(edge):
            continue
        source = edge.getFromNode().getID()
        target = edge.getToNode().getID()
        if source not in intersection_by_node or target not in intersection_by_node:
            continue
        pair = tuple(sorted((source, target)))
        if pair in topology_seen:
            continue
        topology_seen.add(pair)
        topology_edges.append(
            {"source": pair[0], "target": pair[1], "road_distance_m": round(edge.getLength(), 2)}
        )
    all_points = [point for road in roads for point in road["coordinates"]]
    bounds = _bounds(all_points)
    return {
        "bounds": bounds,
        "selection_bounds": (
            {"west": bbox[0], "south": bbox[1], "east": bbox[2], "north": bbox[3]}
            if bbox is not None
            else None
        ),
        "roads": roads[:6000],
        "buildings": _osm_buildings(osm_file, bbox) if osm_file else [],
        "intersections": intersections,
        "topology_edges": topology_edges,
    }


def prepare_osm_draft(
    workspace: Path,
    sumo_home: Path,
    draft_id: str,
    bbox: dict[str, float],
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    draft = load_draft(workspace, draft_id)
    try:
        values = _validate_bbox(bbox)
        folder = draft_dir(workspace, draft_id)
        osm_file = folder / "source.osm.xml"
        clipped_osm_file = folder / "source.clipped.osm.xml"
        network_file = folder / "network.net.xml"
        _progress(workspace, draft, 8, "正在从河北本地 OSM 快照提取路网范围", progress)
        network_context = _extract_local_osm(workspace, osm_file, values)
        _progress(workspace, draft, 38, "本地 OSM 数据已保存, 正在转换 SUMO 路网", progress)
        shutil.copy2(osm_file, clipped_osm_file)
        network_bbox = network_context["network_bbox"]
        network_values = (
            float(network_bbox["west"]),
            float(network_bbox["south"]),
            float(network_bbox["east"]),
            float(network_bbox["north"]),
        )
        _build_osm_net(clipped_osm_file, network_file, sumo_home, network_values)
        _progress(workspace, draft, 72, "SUMO 路网已生成, 正在识别道路和候选路口", progress)
        preview = _network_preview(network_file, osm_file, values)
        if not preview["roads"]:
            raise ValueError("selected OSM area contains no drivable roads")
        if not preview["intersections"]:
            raise ValueError("框选范围内未识别到有效交叉路口。请适当扩大框选范围")
        selected_intersection_ids = [
            item["intersection_id"] for item in preview["intersections"]
        ]
        draft.update(
            status="ready",
            progress=100,
            message="河北本地 OSM 框选范围已解析",
            coordinate_mode="geographic",
            confidence="high",
            requires_manual_review=False,
            review_confirmed=True,
            preview=preview,
            selected_intersection_ids=selected_intersection_ids,
            artifacts={
                "source": "source.osm.xml",
                "processed_source": "source.clipped.osm.xml",
                "network": "network.net.xml",
            },
            error=None,
        )
        draft["source"] = {
            **draft.get("source", {}),
            "bbox": {"west": values[0], "south": values[1], "east": values[2], "north": values[3]},
            "network_context": network_context,
        }
        draft["logs"].append({"time": _now(), "progress": 100, "message": draft["message"]})
        draft["validation"] = validate_draft(draft)
        return save_draft(workspace, draft)
    except Exception as exc:
        draft.update(status="failed", message="OSM 路网解析失败", error=f"{type(exc).__name__}: {exc}")
        save_draft(workspace, draft)
        raise


def _bounds(points: Iterable[list[float]]) -> dict[str, float] | None:
    values = list(points)
    if not values:
        return None
    xs = [float(point[0]) for point in values]
    ys = [float(point[1]) for point in values]
    return {"min_x": min(xs), "min_y": min(ys), "max_x": max(xs), "max_y": max(ys)}


def _iter_lines(geometry: Any) -> Iterable[LineString]:
    if isinstance(geometry, LineString):
        yield geometry
    elif isinstance(geometry, MultiLineString):
        yield from geometry.geoms


def _iter_polygons(geometry: Any) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms


def _planning_preview(
    lines: list[LineString],
    polygons: list[Polygon],
    *,
    coordinate_mode: str,
    bounds_override: dict[str, float] | None = None,
) -> dict[str, Any]:
    cleaned = [line for line in lines if not line.is_empty and line.length > 0]
    roads = [
        {"id": f"road-{index + 1}", "coordinates": [list(point) for point in line.coords]}
        for index, line in enumerate(cleaned[:6000])
    ]
    buildings = [
        {"id": f"building-{index + 1}", "coordinates": [list(point) for point in polygon.exterior.coords]}
        for index, polygon in enumerate(polygons[:2500])
        if not polygon.is_empty
    ]
    segments: list[LineString] = []
    if cleaned:
        merged = unary_union(cleaned)
        segments = list(_iter_lines(merged))
    precision = 7 if coordinate_mode == "geographic" else 3
    degrees: dict[tuple[float, float], set[int]] = defaultdict(set)
    for index, segment in enumerate(segments):
        for point in (segment.coords[0], segment.coords[-1]):
            degrees[(round(point[0], precision), round(point[1], precision))].add(index)
    candidate_points = [point for point, connected in degrees.items() if len(connected) >= 3]
    if not candidate_points:
        candidate_points = [point for point, connected in degrees.items() if len(connected) >= 2]
    intersections = [
        {
            "intersection_id": f"J{index + 1:03d}",
            "display_id": f"J{index + 1:02d}",
            "display_name": f"候选路口 {index + 1}",
            "x": point[0],
            "y": point[1],
            "lon": point[0] if coordinate_mode == "geographic" else None,
            "lat": point[1] if coordinate_mode == "geographic" else None,
            "degree": len(degrees[point]),
            "signalized": False,
        }
        for index, point in enumerate(candidate_points[:500])
    ]
    points = [point for road in roads for point in road["coordinates"]]
    return {
        "bounds": bounds_override or _bounds(points),
        "roads": roads,
        "buildings": buildings,
        "intersections": intersections,
        "topology_edges": [],
    }


def _geojson_geometries(path: Path) -> tuple[list[LineString], list[Polygon], str]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    features = payload.get("features", []) if payload.get("type") == "FeatureCollection" else [payload]
    lines: list[LineString] = []
    polygons: list[Polygon] = []
    for feature in features:
        raw_geometry = feature.get("geometry") if feature.get("type") == "Feature" else feature
        if not raw_geometry:
            continue
        geometry = shape(raw_geometry)
        lines.extend(_iter_lines(geometry))
        polygons.extend(_iter_polygons(geometry))
    sample = next((next(iter(line.coords)) for line in lines if len(line.coords)), None)
    geographic = bool(sample and abs(sample[0]) <= 180 and abs(sample[1]) <= 90)
    return lines, polygons, "geographic" if geographic else "local"


def _dxf_geometries(path: Path) -> tuple[list[LineString], list[Polygon], str]:
    document = ezdxf.readfile(path)
    lines: list[LineString] = []
    polygons: list[Polygon] = []
    for entity in document.modelspace():
        kind = entity.dxftype()
        points: list[tuple[float, float]] = []
        if kind == "LINE":
            points = [(entity.dxf.start.x, entity.dxf.start.y), (entity.dxf.end.x, entity.dxf.end.y)]
        elif kind == "LWPOLYLINE":
            points = [(point[0], point[1]) for point in entity.get_points("xy")]
        elif kind == "POLYLINE":
            points = [(vertex.dxf.location.x, vertex.dxf.location.y) for vertex in entity.vertices]
        if len(points) < 2:
            continue
        closed = bool(getattr(entity, "is_closed", False))
        layer = str(entity.dxf.layer).lower()
        if closed and len(points) >= 3 and any(word in layer for word in ("building", "建筑", "房屋")):
            polygons.append(Polygon(points))
        else:
            lines.append(LineString(points))
    return lines, polygons, "local"


def _shapefile_geometries(path: Path, folder: Path) -> tuple[list[LineString], list[Polygon], str]:
    extract = folder / "shapefile"
    extract.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        for member in archive.infolist():
            target = (extract / member.filename).resolve()
            if extract.resolve() not in target.parents and target != extract.resolve():
                raise ValueError("unsafe path in shapefile archive")
        archive.extractall(extract)
    shp_files = list(extract.rglob("*.shp"))
    if not shp_files:
        raise ValueError("zip archive contains no .shp file")
    lines: list[LineString] = []
    polygons: list[Polygon] = []
    coordinate_mode = "local"
    for shp_file in shp_files:
        transformer: Transformer | None = None
        prj = shp_file.with_suffix(".prj")
        if prj.is_file():
            source_crs = CRS.from_wkt(prj.read_text(encoding="utf-8", errors="ignore"))
            if source_crs.is_geographic:
                coordinate_mode = "geographic"
            else:
                transformer = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
                coordinate_mode = "geographic"
        reader = shapefile.Reader(str(shp_file))
        for item in reader.shapes():
            geometry = shape(item.__geo_interface__)
            if transformer is not None:
                geometry = transform(transformer.transform, geometry)
            lines.extend(_iter_lines(geometry))
            polygons.extend(_iter_polygons(geometry))
    return lines, polygons, coordinate_mode


def _gpkg_geometries(path: Path) -> tuple[list[LineString], list[Polygon], str]:
    lines: list[LineString] = []
    polygons: list[Polygon] = []
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            "SELECT table_name, column_name, srs_id FROM gpkg_geometry_columns"
        ).fetchall()
        for table_name, column_name, srs_id in rows:
            crs_row = connection.execute(
                "SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id = ?", (srs_id,)
            ).fetchone()
            transformer: Transformer | None = None
            if crs_row and int(srs_id) not in {0, 4326}:
                transformer = Transformer.from_crs(CRS.from_user_input(crs_row[0]), "EPSG:4326", always_xy=True)
            query = f'SELECT "{column_name}" FROM "{table_name}" WHERE "{column_name}" IS NOT NULL'
            for (blob,) in connection.execute(query):
                flags = blob[3]
                envelope_code = (flags >> 1) & 0x07
                envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
                geometry = wkb.loads(bytes(blob)[8 + envelope_sizes.get(envelope_code, 0) :])
                if transformer is not None:
                    geometry = transform(transformer.transform, geometry)
                lines.extend(_iter_lines(geometry))
                polygons.extend(_iter_polygons(geometry))
    return lines, polygons, "geographic"


def _pdf_geometries(
    path: Path,
    folder: Path,
) -> tuple[list[LineString], list[Polygon], bool, str, dict[str, float]]:
    document = pymupdf.open(path)
    if not document.page_count:
        raise ValueError("PDF contains no pages")
    page = document[0]
    lines: list[LineString] = []
    polygons: list[Polygon] = []
    page_height = float(page.rect.height)
    for drawing in page.get_drawings():
        points: list[tuple[float, float]] = []
        for item in drawing["items"]:
            if item[0] == "l":
                start, end = item[1], item[2]
                if not points:
                    points.append((start.x, page_height - start.y))
                points.append((end.x, page_height - end.y))
        if len(points) >= 2:
            lines.append(LineString(points))
    preview_path = folder / "source-preview.png"
    page.get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(preview_path)
    return (
        lines,
        polygons,
        len(lines) >= 4,
        preview_path.name,
        {"min_x": 0.0, "min_y": 0.0, "max_x": float(page.rect.width), "max_y": page_height},
    )


def _projection_band_centers(values: np.ndarray, minimum_spacing: int) -> list[int]:
    threshold = max(0.1, float(np.quantile(values, 0.92)) * 0.72)
    active = np.flatnonzero(values >= threshold)
    if not active.size:
        return []
    groups: list[list[int]] = [[int(active[0])]]
    for raw in active[1:]:
        value = int(raw)
        if value <= groups[-1][-1] + 1:
            groups[-1].append(value)
        else:
            groups.append([value])
    centers = [round(sum(group) / len(group)) for group in groups]
    filtered: list[int] = []
    for center in centers:
        if not filtered or center - filtered[-1] >= minimum_spacing:
            filtered.append(center)
        elif values[center] > values[filtered[-1]]:
            filtered[-1] = center
    return filtered[:10]


def _fallback_planning_grid(width: float, height: float) -> list[LineString]:
    margin_x = width * 0.12
    margin_y = height * 0.12
    vertical = [width * fraction for fraction in (0.22, 0.42, 0.62, 0.82)]
    horizontal = [height * fraction for fraction in (0.22, 0.42, 0.62, 0.82)]
    lines = [
        LineString([(x, margin_y), (x, height - margin_y)])
        for x in vertical
    ]
    lines.extend(
        LineString([(margin_x, y), (width - margin_x, y)])
        for y in horizontal
    )
    return lines


def _raster_geometries(path: Path) -> tuple[list[LineString], str, dict[str, float]]:
    """Derive a normalized road graph without asking for coordinates or scale."""

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("L")
        original_width, original_height = image.size
        if min(original_width, original_height) < 32:
            original_width, original_height = 1000, 620
            return (
                _fallback_planning_grid(float(original_width), float(original_height)),
                "fallback_grid",
                {"min_x": 0.0, "min_y": 0.0, "max_x": 1000.0, "max_y": 620.0},
            )
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        grayscale = np.asarray(ImageOps.autocontrast(image), dtype=np.uint8)
    cutoff = min(205, int(np.quantile(grayscale, 0.36)) + 42)
    ink = grayscale < cutoff
    row_centers = _projection_band_centers(
        ink.mean(axis=1), max(5, int(ink.shape[0] * 0.045))
    )
    column_centers = _projection_band_centers(
        ink.mean(axis=0), max(5, int(ink.shape[1] * 0.045))
    )
    scale_x = original_width / float(ink.shape[1])
    scale_y = original_height / float(ink.shape[0])
    width = float(original_width)
    height = float(original_height)
    lines: list[LineString] = []
    if len(row_centers) >= 2 and len(column_centers) >= 2:
        margin_x = width * 0.06
        margin_y = height * 0.06
        for center in column_centers:
            x = center * scale_x
            lines.append(LineString([(x, margin_y), (x, height - margin_y)]))
        for center in row_centers:
            y = height - center * scale_y
            lines.append(LineString([(margin_x, y), (width - margin_x, y)]))
        method = "projection_lines"
    else:
        lines = _fallback_planning_grid(width, height)
        method = "fallback_grid"
    return (
        lines,
        method,
        {"min_x": 0.0, "min_y": 0.0, "max_x": width, "max_y": height},
    )


def prepare_planning_draft(
    workspace: Path,
    draft_id: str,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    draft = load_draft(workspace, draft_id)
    folder = draft_dir(workspace, draft_id)
    source_name = str(draft["artifacts"]["source"])
    source_path = folder / source_name
    suffix = source_path.suffix.lower()
    try:
        _progress(workspace, draft, 12, "规划资料已保存, 正在识别文件结构", progress)
        lines: list[LineString] = []
        polygons: list[Polygon] = []
        coordinate_mode = "local"
        confidence = "medium"
        preview_name: str | None = None
        bounds_override: dict[str, float] | None = None
        extraction_method = "structured_geometry"
        if suffix in {".geojson", ".json"}:
            lines, polygons, coordinate_mode = _geojson_geometries(source_path)
            confidence = "high"
        elif suffix == ".dxf":
            lines, polygons, coordinate_mode = _dxf_geometries(source_path)
            confidence = "high"
        elif suffix == ".zip":
            lines, polygons, coordinate_mode = _shapefile_geometries(source_path, folder)
            confidence = "high"
        elif suffix == ".gpkg":
            lines, polygons, coordinate_mode = _gpkg_geometries(source_path)
            confidence = "high"
        elif suffix == ".pdf":
            lines, polygons, is_vector, preview_name, bounds_override = _pdf_geometries(
                source_path, folder
            )
            if is_vector:
                confidence = "medium"
                extraction_method = "pdf_vector"
            else:
                lines, extraction_method, bounds_override = _raster_geometries(
                    folder / preview_name
                )
                confidence = "medium" if extraction_method == "projection_lines" else "low"
        else:
            with Image.open(source_path) as image:
                image.verify()
            preview_name = source_name
            lines, extraction_method, bounds_override = _raster_geometries(source_path)
            confidence = "medium" if extraction_method == "projection_lines" else "low"
        _progress(workspace, draft, 58, "正在生成可编辑道路与候选路口", progress)
        preview = _planning_preview(
            lines,
            polygons,
            coordinate_mode=coordinate_mode,
            bounds_override=bounds_override,
        )
        if not preview["roads"] or not preview["intersections"]:
            width = (bounds_override or {}).get("max_x", 1000.0)
            height = (bounds_override or {}).get("max_y", 620.0)
            lines = _fallback_planning_grid(float(width), float(height))
            extraction_method = "fallback_grid"
            confidence = "low"
            preview = _planning_preview(
                lines,
                polygons,
                coordinate_mode=coordinate_mode,
                bounds_override=bounds_override,
            )
        draft.update(
            status="ready",
            progress=100,
            message="规划资料已自动生成可运行路网草稿",
            coordinate_mode=coordinate_mode,
            confidence=confidence,
            requires_manual_review=False,
            review_confirmed=True,
            extraction_method=extraction_method,
            preview=preview,
            selected_intersection_ids=[item["intersection_id"] for item in preview["intersections"]],
            error=None,
        )
        if preview_name:
            draft["artifacts"]["preview"] = preview_name
        draft["logs"].append({"time": _now(), "progress": 100, "message": draft["message"]})
        draft["validation"] = validate_draft(draft)
        return save_draft(workspace, draft)
    except Exception as exc:
        draft.update(status="failed", message="规划资料解析失败", error=f"{type(exc).__name__}: {exc}")
        save_draft(workspace, draft)
        raise
