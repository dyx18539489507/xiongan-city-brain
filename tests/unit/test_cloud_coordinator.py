"""Explainable regional cloud weighting."""

from tests.factories import edge_factory, intersection, regional

from traffic_platform.cloud_service.coordinator import (
    CoordinatorConfig,
    RegionalCoordinator,
)
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import SourceType


def test_cloud_suppresses_release_when_downstream_is_high() -> None:
    edge_messages = edge_factory()
    state = intersection(
        edge_messages,
        north_downstream_occupancy=0.92,
    )
    cloud_messages = MessageFactory(
        source_id="cloud-1",
        source_type=SourceType.CLOUD,
        scenario_id="scenario-test",
        experiment_id="experiment-test",
        environment="test",
    )
    coordinator = RegionalCoordinator(cloud_messages)
    strategy = coordinator.strategies(regional(edge_messages, state))[0]
    assert strategy.upstream_release_limit < 1.0
    assert "UPSTREAM_RELEASE_SUPPRESSED" in strategy.reason_codes
    assert sum(strategy.target_green_ratios.values()) <= 1.0


def test_cloud_generates_dynamic_cycle_and_green_wave_offsets() -> None:
    edge_messages = edge_factory()
    first = intersection(edge_messages)
    second = first.model_copy(update={"intersection_id": "J2", "spillback_risk": 0.2})
    region = regional(edge_messages, first).model_copy(
        update={
            "intersection_states": [first, second],
            "risk_levels": {"J1": 0.6, "J2": 0.2},
        }
    )
    cloud_messages = MessageFactory(
        source_id="cloud-1",
        source_type=SourceType.CLOUD,
        scenario_id="scenario-test",
        experiment_id="experiment-test",
        environment="test",
    )
    coordinator = RegionalCoordinator(
        cloud_messages,
        CoordinatorConfig(
            corridor_intersection_ids=("J1", "J2"),
            corridor_segment_distances_m=(220.0,),
        ),
    )
    strategies = coordinator.strategies(region)
    assert all(strategy.target_cycle_length != 90.0 for strategy in strategies)
    offsets = {
        strategy.target_intersection_id: strategy.target_offsets[strategy.target_intersection_id]
        for strategy in strategies
    }
    assert offsets["J2"] > offsets["J1"]
    assert all("GREEN_WAVE_OFFSET_UPDATED" in strategy.reason_codes for strategy in strategies)
