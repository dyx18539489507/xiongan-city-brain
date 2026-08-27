import json
import sqlite3
from io import BytesIO
from pathlib import Path

from PIL import Image

from traffic_platform.scenario_engine import source_factory
from traffic_platform.scenario_engine.source_factory import (
    HEBEI_OSM_INDEX,
    create_draft_record,
    load_draft,
    local_osm_map,
    prepare_planning_draft,
    save_draft,
    store_upload,
    update_draft,
)


def _planning_draft(tmp_path: Path, payload: dict[str, object]) -> str:
    draft_id = "draft-0123456789ab"
    record = create_draft_record(
        tmp_path,
        draft_id,
        "planning_file",
        {"original_name": "roads.geojson"},
    )
    source = store_upload(
        tmp_path,
        draft_id,
        "roads.geojson",
        json.dumps(payload).encode(),
    )
    record["artifacts"] = {"source": source.name}
    save_draft(tmp_path, record)
    return draft_id


def test_planning_geojson_is_ready_without_manual_review_or_twenty_rule(
    tmp_path: Path,
) -> None:
    draft_id = _planning_draft(
        tmp_path,
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[0, 50], [100, 50]],
                    },
                },
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[50, 0], [50, 100]],
                    },
                },
            ],
        },
    )

    draft = prepare_planning_draft(tmp_path, draft_id)

    assert draft["status"] == "ready"
    assert draft["confidence"] == "high"
    assert len(draft["preview"]["roads"]) == 2
    assert len(draft["preview"]["intersections"]) == 1
    assert draft["requires_manual_review"] is False
    assert draft["review_confirmed"] is True
    assert draft["validation"]["valid"] is True

    updated = update_draft(
        tmp_path,
        draft_id,
        selected_intersection_ids=[
            draft["preview"]["intersections"][0]["intersection_id"]
        ],
    )
    assert updated["validation"]["valid"] is True
    assert updated["validation"]["selected_intersection_count"] == 1
    assert updated["validation"]["rule"] == "selected_count_is_authoritative"


def test_scan_generates_runnable_fallback_without_coordinates_or_manual_drawing(
    tmp_path: Path,
) -> None:
    draft_id = "draft-fedcba987654"
    record = create_draft_record(
        tmp_path,
        draft_id,
        "planning_file",
        {"original_name": "scan.png"},
    )
    buffer = BytesIO()
    Image.new("RGB", (1, 1), "white").save(buffer, format="PNG")
    content = buffer.getvalue()
    source = store_upload(tmp_path, draft_id, "scan.png", content)
    record["artifacts"] = {"source": source.name}
    save_draft(tmp_path, record)

    draft = prepare_planning_draft(tmp_path, draft_id)

    assert draft["status"] == "ready"
    assert draft["confidence"] == "low"
    assert draft["requires_manual_review"] is False
    assert draft["review_confirmed"] is True
    assert draft["extraction_method"] == "fallback_grid"
    assert len(draft["preview"]["roads"]) == 8
    assert len(draft["preview"]["intersections"]) == 16
    assert draft["validation"]["valid"] is True
    assert load_draft(tmp_path, draft_id)["artifacts"]["preview"] == source.name


def test_local_osm_map_reads_the_packaged_sqlite_index(tmp_path: Path) -> None:
    index = tmp_path / HEBEI_OSM_INDEX
    index.parent.mkdir(parents=True)
    with sqlite3.connect(index) as connection:
        connection.execute(
            """CREATE TABLE roads (
                osm_id INTEGER,
                highway TEXT,
                name TEXT,
                coordinates TEXT,
                min_lon REAL,
                min_lat REAL,
                max_lon REAL,
                max_lat REAL
            )"""
        )
        connection.execute(
            "INSERT INTO roads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "primary",
                "测试路",
                json.dumps([[115.91, 39.05], [115.92, 39.06]]),
                115.91,
                39.05,
                115.92,
                39.06,
            ),
        )

    payload = local_osm_map(
        tmp_path,
        {"west": 115.90, "south": 39.04, "east": 115.93, "north": 39.07},
    )

    assert payload["snapshot_date"] == "2026-08-21"
    assert payload["features"][0]["properties"] == {
        "highway": "primary",
        "name": "测试路",
    }


def test_osm_bbox_export_uses_the_road_index_without_scanning_the_pbf(
    tmp_path: Path,
) -> None:
    index = tmp_path / HEBEI_OSM_INDEX
    index.parent.mkdir(parents=True)
    with sqlite3.connect(index) as connection:
        connection.execute(
            """CREATE TABLE roads (
                osm_id INTEGER,
                highway TEXT,
                name TEXT,
                coordinates TEXT,
                min_lon REAL,
                min_lat REAL,
                max_lon REAL,
                max_lat REAL
            )"""
        )
        connection.execute(
            "INSERT INTO roads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                7,
                "primary",
                "测试路",
                json.dumps([[115.90, 39.05], [115.92, 39.05]]),
                115.90,
                39.05,
                115.92,
                39.05,
            ),
        )
        connection.execute(
            "INSERT INTO roads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                8,
                "secondary",
                "框外道路",
                json.dumps([[115.9045, 39.049], [115.9045, 39.051]]),
                115.9045,
                39.049,
                115.9045,
                39.051,
            ),
        )

    target = tmp_path / "source.osm.xml"
    context = source_factory._extract_local_osm(
        tmp_path,
        target,
        (115.905, 39.045, 115.915, 39.055),
    )

    root = source_factory.ET.parse(target).getroot()
    nodes = root.findall("node")
    ways = root.findall("way")
    assert len(nodes) == 2
    assert len(ways) == 1
    assert {tag.attrib["k"]: tag.attrib["v"] for tag in ways[0].findall("tag")} == {
        "highway": "primary",
        "maxspeed": "50",
        "name": "测试路",
        "source_way_id": "7",
    }
    longitudes = {float(node.attrib["lon"]) for node in nodes}
    assert min(longitudes) < 115.905
    assert max(longitudes) > 115.915
    assert context["selected_source_way_count"] == 1
    assert context["corridors"][0]["before_boundary"] == "nearest_intersection"
    assert context["corridors"][0]["after_boundary"] == "fallback_stub"
    assert min(longitudes) == 115.9045
    assert {tag.attrib["v"] for tag in ways[0].findall("tag")} - {
        "primary",
        "50",
        "测试路",
        "7",
    } == set()


def test_osm_network_bbox_adds_context_without_changing_selection() -> None:
    selection = (115.9172, 39.0596, 115.9178, 39.0600)

    expanded = source_factory._expand_bbox_by_meters(selection)

    assert expanded[0] < selection[0]
    assert expanded[1] < selection[1]
    assert expanded[2] > selection[2]
    assert expanded[3] > selection[3]
    assert expanded[0] == source_factory._expand_bbox_by_meters(selection)[0]
    assert 0.0025 < expanded[2] - expanded[0] < 0.003
    assert 0.0019 < expanded[3] - expanded[1] < 0.0021


def test_osm_bbox_export_appends_indexed_buildings_and_water(tmp_path: Path) -> None:
    road_index = tmp_path / source_factory.HEBEI_OSM_INDEX
    road_index.parent.mkdir(parents=True)
    with sqlite3.connect(road_index) as connection:
        connection.execute(
            """CREATE TABLE roads (
                osm_id INTEGER, highway TEXT, name TEXT, coordinates TEXT,
                min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL
            )"""
        )
        connection.execute(
            "INSERT INTO roads VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                7,
                "primary",
                "测试路",
                json.dumps([[115.90, 39.05], [115.92, 39.05]]),
                115.90,
                39.05,
                115.92,
                39.05,
            ),
        )

    context_index = tmp_path / source_factory.HEBEI_OSM_CONTEXT_INDEX
    with sqlite3.connect(context_index) as connection:
        connection.execute(
            """CREATE TABLE features (
                osm_type TEXT, osm_id INTEGER, min_lon REAL, max_lon REAL,
                min_lat REAL, max_lat REAL, coordinates TEXT, tags_json TEXT
            )"""
        )
        coordinates = [
            [101, 115.907, 39.049],
            [102, 115.909, 39.049],
            [103, 115.909, 39.051],
            [101, 115.907, 39.049],
        ]
        connection.executemany(
            "INSERT INTO features VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "way",
                    501,
                    115.907,
                    115.909,
                    39.049,
                    39.051,
                    json.dumps(coordinates),
                    json.dumps({"building": "apartments", "building:levels": "6"}),
                ),
                (
                    "way",
                    502,
                    115.907,
                    115.909,
                    39.049,
                    39.051,
                    json.dumps([[201, 115.907, 39.049], [202, 115.909, 39.049], [203, 115.909, 39.051], [201, 115.907, 39.049]]),
                    json.dumps({"natural": "water"}),
                ),
            ],
        )

    target = tmp_path / "source.osm.xml"
    context = source_factory._extract_local_osm(
        tmp_path,
        target,
        (115.905, 39.045, 115.915, 39.055),
    )

    root = source_factory.ET.parse(target).getroot()
    tags_by_way = {
        way.attrib["id"]: {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        for way in root.findall("way")
    }
    assert tags_by_way["501"]["building"] == "apartments"
    assert tags_by_way["502"]["natural"] == "water"
    assert context["context_feature_counts"] == {"ways": 2, "nodes": 6}


def test_osm_bbox_export_preserves_oneway_tunnel_layer_and_urban_speed(
    tmp_path: Path,
) -> None:
    index = tmp_path / HEBEI_OSM_INDEX
    index.parent.mkdir(parents=True)
    tags = {
        "highway": "secondary",
        "layer": "-1",
        "name": "地下道路",
        "oneway": "yes",
        "tunnel": "yes",
    }
    with sqlite3.connect(index) as connection:
        connection.execute(
            """CREATE TABLE roads (
                osm_id INTEGER, highway TEXT, name TEXT, coordinates TEXT,
                min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL,
                tags_json TEXT
            )"""
        )
        connection.execute(
            "INSERT INTO roads VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                99,
                "secondary",
                "地下道路",
                json.dumps([[115.90, 39.05], [115.92, 39.05]]),
                115.90,
                39.05,
                115.92,
                39.05,
                json.dumps(tags),
            ),
        )

    target = tmp_path / "source.osm.xml"
    source_factory._extract_local_osm(
        tmp_path,
        target,
        (115.905, 39.045, 115.915, 39.055),
    )

    way = source_factory.ET.parse(target).getroot().find("way")
    assert way is not None
    exported = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
    assert exported["oneway"] == "yes"
    assert exported["tunnel"] == "yes"
    assert exported["layer"] == "-1"
    assert exported["maxspeed"] == "40"


def test_osm_netconvert_receives_absolute_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(source_factory, "_sumo_binary", lambda *_args: Path("netconvert.exe"))
    monkeypatch.setattr(
        source_factory,
        "_run",
        lambda command, cwd: calls.append((command, cwd)),
    )

    source_factory._build_osm_net(
        Path("relative/source.osm.xml"),
        Path("relative/network.net.xml"),
        Path("sumo"),
        (115.91, 39.05, 115.92, 39.06),
    )

    command, cwd = calls[0]
    assert Path(command[command.index("--osm-files") + 1]).is_absolute()
    assert Path(command[command.index("--output-file") + 1]).is_absolute()
    assert command[command.index("--no-turnarounds") + 1] == "true"
    assert command[command.index("--remove-edges.isolated") + 1] == "false"
    assert command[command.index("--walkingareas") + 1] == "false"
    assert command[command.index("--junctions.join") + 1] == "true"
    assert command[command.index("--junctions.join-dist") + 1] == "25.0"
    assert cwd.is_absolute()
