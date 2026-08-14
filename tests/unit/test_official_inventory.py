"""Organizer inventory stays explicit about the independent-intersection boundary."""

from pathlib import Path

from traffic_platform.scenario_engine.official_inventory import build_official_inventory


def test_inventory_rejects_incomplete_collection(tmp_path: Path) -> None:
    (tmp_path / "demo_1.xlsx").write_bytes(b"x")
    try:
        build_official_inventory(tmp_path)
    except ValueError as exc:
        assert "20 workbooks" in str(exc)
    else:
        raise AssertionError("incomplete organizer collection was accepted")
