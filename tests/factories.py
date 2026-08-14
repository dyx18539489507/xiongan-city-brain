"""Reusable valid contract and topology factories."""

from traffic_platform.algorithm_sdk.types import (
    NetworkTopology,
    PhaseDefinition,
    PhaseMovement,
)
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import (
    CloudStrategy,
    IntersectionState,
    LaneState,
    RegionalState,
    SourceType,
)


def edge_factory() -> MessageFactory:
    """Return an isolated edge message factory."""

    return MessageFactory(
        source_id="edge-1",
        source_type=SourceType.EDGE,
        scenario_id="scenario-test",
        experiment_id="experiment-test",
        environment="test",
    )


def lane(
    factory: MessageFactory,
    lane_id: str,
    *,
    movement: str,
    queue: int,
    occupancy: float = 0.2,
    downstream_occupancy: float = 0.2,
    downstream_capacity: float = 10.0,
) -> LaneState:
    """Create one consistent lane aggregate."""

    return factory.build(
        LaneState,
        simulation_time=10.0,
        lane_id=lane_id,
        intersection_id="J1",
        direction="inbound",
        movement=movement,
        vehicle_count=max(queue, 1),
        connected_vehicle_count=0,
        queue_vehicle_count=queue,
        queue_length_m=float(queue) * 7.5,
        mean_speed=5.0,
        occupancy=occupancy,
        arrival_rate=600.0,
        discharge_rate=300.0,
        downstream_lane_id=f"{lane_id}.out",
        downstream_occupancy=downstream_occupancy,
        downstream_available_capacity=downstream_capacity,
    )


def intersection(
    factory: MessageFactory,
    *,
    phase: str = "P1",
    phase_elapsed: float = 15.0,
    north_queue: int = 10,
    south_queue: int = 2,
    north_downstream_occupancy: float = 0.2,
) -> IntersectionState:
    """Create a two-phase intersection observation."""

    lanes = [
        lane(
            factory,
            "N.in",
            movement="P1",
            queue=north_queue,
            downstream_occupancy=north_downstream_occupancy,
        ),
        lane(factory, "N.out", movement="out", queue=1),
        lane(factory, "S.in", movement="P2", queue=south_queue),
        lane(factory, "S.out", movement="out", queue=1),
    ]
    return factory.build(
        IntersectionState,
        simulation_time=10.0,
        intersection_id="J1",
        edge_id="edge-1",
        current_phase_id=phase,
        phase_state="GGrr",
        phase_elapsed=phase_elapsed,
        phase_remaining=10.0,
        cycle_elapsed=phase_elapsed,
        lane_states=lanes,
        total_queue=sum(item.queue_vehicle_count for item in lanes),
        mean_speed=5.0,
        throughput=300.0,
        congestion_level=0.7,
        spillback_risk=0.6,
        incident_state="none",
        communication_state="online",
        local_control_mode="CLOUD_COORDINATED",
    )


def regional(
    factory: MessageFactory,
    state: IntersectionState,
) -> RegionalState:
    """Create a one-intersection regional aggregation."""

    return factory.build(
        RegionalState,
        simulation_time=10.0,
        intersection_states=[state],
        network_mean_speed=state.mean_speed,
        total_queue=state.total_queue,
        congested_intersections=["J1"],
        spillback_edges=[],
        risk_levels={"J1": state.spillback_risk},
        active_disturbances=[],
    )


def topology() -> NetworkTopology:
    """Create the two-phase lane-movement topology used by unit tests."""

    return NetworkTopology(
        intersection_ids=["J1"],
        phases={
            "J1": [
                PhaseDefinition(
                    phase_id="P1",
                    movements=[
                        PhaseMovement(
                            incoming_lane_id="N.in",
                            outgoing_lane_id="N.out",
                        )
                    ],
                ),
                PhaseDefinition(
                    phase_id="P2",
                    movements=[
                        PhaseMovement(
                            incoming_lane_id="S.in",
                            outgoing_lane_id="S.out",
                        )
                    ],
                ),
            ]
        },
        downstream_intersections={"J1": []},
        speed_limits_m_s={"N.in": 13.9, "S.in": 13.9},
    )


def cloud_strategy(
    factory: MessageFactory,
    *,
    version: int = 1,
    release_limit: float = 1.0,
    green_ratios: dict[str, float] | None = None,
) -> CloudStrategy:
    """Create one valid cloud strategy for J1."""

    return factory.build(
        CloudStrategy,
        simulation_time=10.0,
        strategy_version=version,
        generated_at_sim_time=10.0,
        valid_from=0.0,
        valid_until=100.0,
        target_intersection_id="J1",
        target_cycle_length=90.0,
        target_green_ratios=green_ratios or {"P1": 0.5, "P2": 0.3},
        target_offsets={"J1": 0.0},
        upstream_release_limit=release_limit,
        downstream_priority={},
        recommended_phase_plan=["P1", "P2"],
        speed_guidance_parameters={"target_speed_factor": 0.8},
        confidence=0.8,
        reason_codes=["TEST"],
        fallback_policy="edge_max_pressure",
    )

