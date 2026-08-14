"""Phase 1 scene-model and coordinate integrity tests."""

import hashlib
import json
from itertools import pairwise
from pathlib import Path

import pytest

from traffic_platform.scene.coordinates import CoordinateDefinition, CoordinateService
from traffic_platform.scene.generator import generate_scene_document
from traffic_platform.scene.models import SceneDocument


@pytest.fixture(scope="module")
def scene_payload(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    output = tmp_path_factory.mktemp("scene") / "xiongan.scene.json"
    result = generate_scene_document(Path.cwd(), output_path=output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    SceneDocument.model_validate(payload)
    manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    return {"result": result, "payload": payload, "manifest": manifest}


def test_coordinate_service_round_trips_registered_k06() -> None:
    service = CoordinateService(
        CoordinateDefinition(
            projection=(
                "+proj=utm +zone=50 +ellps=WGS84 +datum=WGS84 +units=m +no_defs"
            ),
            net_offset_x=-402358.92,
            net_offset_y=-4317416.65,
            world_origin_sumo_x=3691.65,
            world_origin_sumo_y=6515.815,
        )
    )
    lon, lat = service.sumo_to_lon_lat(4005.52, 5451.76)
    assert lon == pytest.approx(115.91790831041494, abs=1e-10)
    assert lat == pytest.approx(39.04987534804161, abs=1e-10)
    x_m, y_m = service.lon_lat_to_sumo(lon, lat)
    assert x_m == pytest.approx(4005.52, abs=1e-6)
    assert y_m == pytest.approx(5451.76, abs=1e-6)
    world = service.sumo_to_world(x_m, y_m, 1.2)
    assert service.world_to_sumo(world[0], world[2]) == pytest.approx((x_m, y_m))
    assert service.world_angle_to_sumo(service.sumo_angle_to_three(359.0)) == pytest.approx(
        359.0
    )


def test_scene_contains_all_twenty_controlled_tls_and_stable_ids(
    scene_payload: dict[str, object],
) -> None:
    payload = scene_payload["payload"]
    assert isinstance(payload, dict)
    controlled = {
        item["sumoJunctionId"]
        for item in payload["junctions"]
        if item["controlled"]
    }
    traffic_lights = {item["sumoTlsId"] for item in payload["trafficLights"]}
    assert len(controlled) == 20
    assert traffic_lights == controlled
    assert payload["controlCorridors"][0]["displayIds"] == [
        "K01",
        "K02",
        "K03",
        "K04",
        "K05",
        "K06",
        "K07",
        "K08",
    ]
    corridor = payload["controlCorridors"][0]
    assert len(corridor["segments"]) == 7
    assert [segment["fromJunctionId"] for segment in corridor["segments"]] == corridor[
        "junctionIds"
    ][:-1]
    assert [segment["toJunctionId"] for segment in corridor["segments"]] == corridor[
        "junctionIds"
    ][1:]
    assert all(
        segment["forwardEdgeIds"] or segment["reverseEdgeIds"]
        for segment in corridor["segments"]
    )
    directional_edges = {
        edge_id
        for segment in corridor["segments"]
        for direction in ("forwardEdgeIds", "reverseEdgeIds")
        for edge_id in segment[direction]
    }
    assert set(corridor["edgeIds"]) == directional_edges
    edge_by_id = {item["sumoEdgeId"]: item for item in payload["edges"]}
    for segment in corridor["segments"]:
        forward = [edge_by_id[item] for item in segment["forwardEdgeIds"]]
        reverse = [edge_by_id[item] for item in segment["reverseEdgeIds"]]
        if forward:
            assert forward[0]["fromJunctionId"] == segment["fromJunctionId"]
            assert forward[-1]["toJunctionId"] == segment["toJunctionId"]
            assert all(
                left["toJunctionId"] == right["fromJunctionId"]
                for left, right in pairwise(forward)
            )
        if reverse:
            assert reverse[0]["fromJunctionId"] == segment["toJunctionId"]
            assert reverse[-1]["toJunctionId"] == segment["fromJunctionId"]
            assert all(
                left["toJunctionId"] == right["fromJunctionId"]
                for left, right in pairwise(reverse)
            )
    assert payload["coordinateSystem"]["units"] == "m"
    assert payload["coordinateSystem"]["worldAxes"]["z"] == "south; north is -z"


def test_scene_lane_connection_and_source_references_are_closed(
    scene_payload: dict[str, object],
) -> None:
    payload = scene_payload["payload"]
    assert isinstance(payload, dict)
    edge_ids = {item["sumoEdgeId"] for item in payload["edges"]}
    lane_ids = {item["sumoLaneId"] for item in payload["lanes"]}
    assert len(edge_ids) > 0
    assert len(lane_ids) > 0
    assert all(item["sumoEdgeId"] in edge_ids for item in payload["lanes"])
    assert all(item["fromLaneId"] in lane_ids for item in payload["connections"])
    assert all(item["toLaneId"] in lane_ids for item in payload["connections"])
    assert payload["metadata"]["counts"]["crossings"] > 0
    assert payload["metadata"]["counts"]["buildings"] > 0
    assert payload["metadata"]["counts"]["roadsideDevices"] == 40
    devices = payload["roadsideDevices"]
    assert len({item["deviceId"] for item in devices}) == 40
    assert {item["deviceType"] for item in devices} == {"rsu", "camera"}
    assert all(item["managedJunctions"] for item in devices)
    assert all(
        item["provenance"]
        == "engineering_model_from_controlled_junction_and_sumo_lane"
        for item in devices
    )

    for source in payload["metadata"]["sourceFiles"]:
        path = Path(str(source["path"]))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == source["sha256"]

    manifest = scene_payload["manifest"]
    assert isinstance(manifest, dict)
    assert manifest["sceneSha256"] == scene_payload["result"]["sha256"]
    assert manifest["sceneBytes"] > 0
    assert manifest["counts"] == payload["metadata"]["counts"]
