"""OSM-grounded functional-zone evidence without field-calibration claims."""

from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from pyproj import Transformer

_FUNCTION_KEYS = {
    "amenity",
    "landuse",
    "leisure",
    "office",
    "public_transport",
    "shop",
    "tourism",
}

_FUNCTION_COLORS = {
    "commercial": "245,158,11,105",
    "construction": "249,115,22,75",
    "education": "59,130,246,115",
    "healthcare": "239,68,68,120",
    "industrial": "107,114,128,95",
    "office": "99,102,241,95",
    "other_osm_function": "148,163,184,70",
    "public_service": "6,182,212,105",
    "recreation": "34,197,94,80",
    "residential": "168,85,247,55",
    "tourism": "236,72,153,90",
    "transport": "20,184,166,90",
}


def build_functional_zones(
    osm_file: Path,
    selection_file: Path,
    output_file: Path,
    *,
    net_file: Path | None = None,
    sumo_shape_file: Path | None = None,
    association_radius_m: float = 1200.0,
) -> dict[str, Any]:
    """Associate selected junctions with nearby, explicitly tagged OSM features."""

    if association_radius_m <= 0:
        raise ValueError("association_radius_m must be positive")
    if (net_file is None) != (sumo_shape_file is None):
        raise ValueError("net_file and sumo_shape_file must be supplied together")
    root = ET.parse(osm_file).getroot()
    nodes: dict[str, tuple[float, float]] = {
        str(node.attrib["id"]): (
            float(node.attrib["lon"]),
            float(node.attrib["lat"]),
        )
        for node in root.findall("node")
        if "lon" in node.attrib and "lat" in node.attrib
    }
    features: list[dict[str, Any]] = []
    geometries: dict[str, list[tuple[float, float]]] = {}
    for node in root.findall("node"):
        tags = _tags(node)
        if not _is_functional(tags):
            continue
        lon_lat = nodes.get(str(node.attrib["id"]))
        if lon_lat is not None:
            feature = _feature("node", node.attrib["id"], lon_lat, tags)
            features.append(feature)
            geometries[feature["feature_id"]] = [lon_lat]
    for way in root.findall("way"):
        tags = _tags(way)
        if not _is_functional(tags):
            continue
        coordinates = [
            nodes[reference.attrib["ref"]]
            for reference in way.findall("nd")
            if reference.attrib.get("ref") in nodes
        ]
        if coordinates:
            centroid = (
                sum(point[0] for point in coordinates) / len(coordinates),
                sum(point[1] for point in coordinates) / len(coordinates),
            )
            feature = _feature("way", way.attrib["id"], centroid, tags)
            features.append(feature)
            geometries[feature["feature_id"]] = coordinates
    selection = json.loads(selection_file.read_text(encoding="utf-8"))
    associations: list[dict[str, Any]] = []
    for intersection in selection["intersections"]:
        distances = sorted(
            (
                _distance_m(
                    float(intersection["lon"]),
                    float(intersection["lat"]),
                    float(feature["lon"]),
                    float(feature["lat"]),
                ),
                feature,
            )
            for feature in features
        )
        nearby = [
            {
                "feature_id": item["feature_id"],
                "name": item["name"],
                "functional_class": item["functional_class"],
                "distance_m": round(distance, 2),
                "osm_tags": item["osm_tags"],
            }
            for distance, item in distances
            if distance <= association_radius_m
        ]
        counts = Counter(item["functional_class"] for item in nearby)
        associations.append(
            {
                "intersection_id": intersection["intersection_id"],
                "display_id": intersection["display_id"],
                "dominant_osm_function": (
                    counts.most_common(1)[0][0]
                    if counts
                    else "osm_function_not_observed_within_radius"
                ),
                "nearby_feature_count": len(nearby),
                "nearby_features": nearby[:10],
                "classification_status": (
                    "osm_tag_evidence_available" if nearby else "not_observed_no_assumption_added"
                ),
            }
        )
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "scenario_id": selection.get("scenario_id", "xiongan_rongdong_20"),
        "source": "OpenStreetMap tags from the complete Rongdong extract",
        "source_sha256": hashlib.sha256(osm_file.read_bytes()).hexdigest(),
        "field_calibrated": False,
        "claim_boundary": (
            "OSM tag evidence and deterministic engineering classification only; "
            "no inferred feature is claimed as a field-survey result"
        ),
        "association_radius_m": association_radius_m,
        "functional_feature_count": len(features),
        "class_counts": dict(
            sorted(Counter(item["functional_class"] for item in features).items())
        ),
        "features": features,
        "intersection_associations": associations,
    }
    if net_file is not None and sumo_shape_file is not None:
        payload["sumo_visualization"] = _write_sumo_shapes(
            features,
            geometries,
            net_file,
            sumo_shape_file,
        )
    output_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _write_sumo_shapes(
    features: list[dict[str, Any]],
    geometries: dict[str, list[tuple[float, float]]],
    net_file: Path,
    output_file: Path,
) -> dict[str, Any]:
    """Write a subdued, clickable SUMO polygon layer from OSM evidence."""

    location = ET.parse(net_file).getroot().find("location")
    if location is None:
        raise ValueError("SUMO network is missing location metadata")
    projection = location.attrib.get("projParameter")
    offset = location.attrib.get("netOffset")
    if not projection or not offset:
        raise ValueError("SUMO network is missing projection or offset metadata")
    offset_x, offset_y = (float(value) for value in offset.split(","))
    transformer = Transformer.from_crs("EPSG:4326", projection, always_xy=True)

    def project(lon_lat: tuple[float, float]) -> tuple[float, float]:
        x, y = transformer.transform(lon_lat[0], lon_lat[1])
        return (float(x) + offset_x, float(y) + offset_y)

    additional = ET.Element("additional")
    area_count = 0
    point_marker_count = 0
    for feature in features:
        coordinates = geometries[feature["feature_id"]]
        closed_area = (
            feature["osm_element_type"] == "way"
            and len(coordinates) >= 4
            and coordinates[0] == coordinates[-1]
        )
        if closed_area:
            shape = [project(point) for point in coordinates]
            area_count += 1
        else:
            center_x, center_y = project((float(feature["lon"]), float(feature["lat"])))
            radius = 5.0
            shape = [
                (center_x, center_y + radius),
                (center_x + radius, center_y),
                (center_x, center_y - radius),
                (center_x - radius, center_y),
                (center_x, center_y + radius),
            ]
            point_marker_count += 1
        functional_class = str(feature["functional_class"])
        polygon = ET.SubElement(
            additional,
            "poly",
            {
                "id": f"functional_{feature['osm_element_type']}_{feature['osm_id']}",
                "type": f"osm_function.{functional_class}",
                "name": str(feature["name"]),
                "color": _FUNCTION_COLORS.get(
                    functional_class,
                    _FUNCTION_COLORS["other_osm_function"],
                ),
                "fill": "true",
                "layer": "-20",
                "lineWidth": "0.60",
                "shape": " ".join(f"{x:.2f},{y:.2f}" for x, y in shape),
            },
        )
        for key, value in (
            ("source", "OpenStreetMap"),
            ("functional_class", functional_class),
            ("osm_element_type", feature["osm_element_type"]),
            ("osm_id", feature["osm_id"]),
            ("field_calibrated", "false"),
        ):
            ET.SubElement(polygon, "param", {"key": key, "value": str(value)})
    ET.indent(additional, space="    ")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(additional).write(output_file, encoding="utf-8", xml_declaration=True)
    return {
        "sumo_shape_file": output_file.name,
        "shape_count": len(features),
        "area_polygon_count": area_count,
        "point_marker_count": point_marker_count,
        "layer": -20,
        "claim_boundary": "OSM tag visualization only; not field calibrated",
    }


def _tags(element: ET.Element) -> dict[str, str]:
    return {
        str(tag.attrib["k"]): str(tag.attrib["v"])
        for tag in element.findall("tag")
        if "k" in tag.attrib and "v" in tag.attrib
    }


def _is_functional(tags: dict[str, str]) -> bool:
    return bool(_FUNCTION_KEYS & tags.keys())


def _feature(
    element_type: str,
    osm_id: str,
    lon_lat: tuple[float, float],
    tags: dict[str, str],
) -> dict[str, Any]:
    return {
        "feature_id": f"osm:{element_type}:{osm_id}",
        "osm_element_type": element_type,
        "osm_id": str(osm_id),
        "name": tags.get("name:zh") or tags.get("name") or "unnamed_osm_feature",
        "lon": lon_lat[0],
        "lat": lon_lat[1],
        "functional_class": _classify(tags),
        "classification_method": "deterministic_mapping_from_osm_tag",
        "osm_tags": tags,
    }


def _classify(tags: dict[str, str]) -> str:
    amenity = tags.get("amenity", "")
    landuse = tags.get("landuse", "")
    if amenity in {"school", "kindergarten", "college", "university"}:
        return "education"
    if amenity in {"hospital", "clinic", "social_facility"}:
        return "healthcare"
    if amenity in {
        "community_centre",
        "exhibition_centre",
        "government",
        "library",
        "police",
        "post_office",
        "townhall",
    }:
        return "public_service"
    if "shop" in tags or landuse in {"commercial", "retail"}:
        return "commercial"
    if amenity in {"restaurant", "fast_food", "cafe", "marketplace"}:
        return "commercial"
    if landuse in {"residential", "construction", "industrial"}:
        return landuse
    if "leisure" in tags:
        return "recreation"
    if "public_transport" in tags:
        return "transport"
    if "office" in tags:
        return "office"
    if "tourism" in tags:
        return "tourism"
    return "other_osm_function"


def _distance_m(
    left_lon: float,
    left_lat: float,
    right_lon: float,
    right_lat: float,
) -> float:
    radius_m = 6_371_000.0
    left_phi = math.radians(left_lat)
    right_phi = math.radians(right_lat)
    delta_phi = math.radians(right_lat - left_lat)
    delta_lambda = math.radians(right_lon - left_lon)
    value = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(left_phi) * math.cos(right_phi) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(value))
