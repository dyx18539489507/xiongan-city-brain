import json
from pathlib import Path

from traffic_platform.scenario_engine.factory import validate_selection


def _workspace(tmp_path: Path) -> Path:
    generated = tmp_path / "scenarios" / "generated" / "xiongan_rongdong_20"
    generated.mkdir(parents=True)
    (generated / "controlled_intersections.json").write_text(
        json.dumps(
            {
                "intersections": [
                    {"intersection_id": "J1"},
                    {"intersection_id": "J2"},
                    {"intersection_id": "J3"},
                ],
                "topology_edges": [{"source": "J1", "target": "J2"}],
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_factory_accepts_exactly_one_selected_intersection(tmp_path: Path) -> None:
    result = validate_selection(_workspace(tmp_path), ["J2"])

    assert result["valid"] is True
    assert result["selected_intersection_count"] == 1
    assert result["selected_intersection_ids"] == ["J2"]
    assert result["rule"] == "selected_count_is_authoritative"


def test_factory_warns_but_does_not_reject_disconnected_selection(tmp_path: Path) -> None:
    result = validate_selection(_workspace(tmp_path), ["J1", "J3"])

    assert result["valid"] is True
    assert result["selected_intersection_count"] == 2
    assert result["connected_control_subgraph"] is False
    assert result["warnings"]


def test_factory_rejects_unknown_intersection_without_twenty_node_rule(
    tmp_path: Path,
) -> None:
    result = validate_selection(_workspace(tmp_path), ["J1", "UNKNOWN"])

    assert result["valid"] is False
    assert result["selected_intersection_count"] == 2
    assert "UNKNOWN" in result["errors"][0]
