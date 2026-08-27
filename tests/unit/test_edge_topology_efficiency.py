"""Topology startup should not repeat live lane scans for every junction."""

from types import SimpleNamespace

from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import SourceType
from traffic_platform.edge_service.aggregation import EdgeStateAggregator
from traffic_platform.sumo_adapter import LaneSnapshot


class TopologyAdapter:
    def __init__(self) -> None:
        self.lane_queries: list[list[str]] = []

    def get_controlled_links(self, intersection_id: str) -> list[list[tuple[str, str, str]]]:
        return [[(f"{intersection_id}.in", f"{intersection_id}.out", "")]]

    def get_traffic_light_program(self, _intersection_id: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                phases=[
                    SimpleNamespace(
                        state="G",
                        duration=30.0,
                        minDur=30.0,
                        maxDur=40.0,
                    ),
                    SimpleNamespace(
                        state="r",
                        duration=4.0,
                        minDur=4.0,
                        maxDur=4.0,
                    ),
                ]
            )
        ]

    def get_lane_states(self, lane_ids: list[str]) -> list[LaneSnapshot]:
        self.lane_queries.append(lane_ids)
        return [
            LaneSnapshot(
                lane_id=lane_id,
                vehicle_count=0,
                queue_vehicle_count=0,
                queue_length_m=0.0,
                mean_speed_m_s=0.0,
                occupancy_ratio=0.0,
                max_speed_m_s=13.9,
                bicycle_count=0,
                electric_bicycle_count=0,
                bicycle_queue_count=0,
                pedestrian_count=0,
                pedestrian_waiting_count=0,
            )
            for lane_id in lane_ids
        ]


def test_build_topology_queries_all_controlled_lanes_once() -> None:
    adapter = TopologyAdapter()
    factory = MessageFactory(
        source_id="test-edge",
        source_type=SourceType.EDGE,
        scenario_id="xiongan_rongdong_20",
        experiment_id="test-topology",
    )
    topology = EdgeStateAggregator(
        adapter,  # type: ignore[arg-type]
        factory,
        ["tls-b", "tls-a"],
    ).build_topology()

    assert adapter.lane_queries == [["tls-a.in", "tls-b.in"]]
    assert topology.speed_limits_m_s == {"tls-a.in": 13.9, "tls-b.in": 13.9}
    assert topology.phases["tls-a"][0].min_green_s == 10.0
    assert topology.phases["tls-b"][0].min_green_s == 10.0
