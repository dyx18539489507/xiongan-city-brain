import json
import xml.etree.ElementTree as ET
from pathlib import Path


def test_osm_functional_zones_preserve_evidence_boundary() -> None:
    payload = json.loads(
        Path("scenarios/generated/xiongan_rongdong_20/functional_zones.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["field_calibrated"] is False
    assert len(payload["intersection_associations"]) == 20
    assert payload["class_counts"]["education"] >= 1
    assert payload["class_counts"]["commercial"] >= 1
    assert all(
        item["classification_status"]
        in {"osm_tag_evidence_available", "not_observed_no_assumption_added"}
        for item in payload["intersection_associations"]
    )


def test_osm_functional_zones_are_available_as_sumo_shapes() -> None:
    output = Path("scenarios/generated/xiongan_rongdong_20")
    payload = json.loads((output / "functional_zones.json").read_text(encoding="utf-8"))
    visualization = payload["sumo_visualization"]
    shapes = ET.parse(output / "functional_zones.add.xml").getroot().findall("poly")

    assert visualization["shape_count"] == payload["functional_feature_count"]
    assert visualization["area_polygon_count"] > 0
    assert len(shapes) == payload["functional_feature_count"]
    assert {shape.get("type") for shape in shapes} >= {
        "osm_function.education",
        "osm_function.commercial",
    }
    assert all(shape.get("layer") == "-20" for shape in shapes)
