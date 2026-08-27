"""B0-B3 baseline decisions, predictive fusion and registry behavior."""

import pytest
from tests.factories import cloud_strategy, edge_factory, intersection, topology

from traffic_platform.algorithm_sdk.types import (
    AlgorithmConfig,
    ControlObservation,
    PhaseDefinition,
    PhaseMovement,
)
from traffic_platform.algorithms import builtin_registry
from traffic_platform.algorithms.coordinated import CoordinatedMaxPressureController
from traffic_platform.algorithms.max_pressure import MaxPressureController
from traffic_platform.contracts.models import TrafficForecast


def test_max_pressure_prefers_larger_usable_queue() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P2", north_queue=12, south_queue=2)
    controller = MaxPressureController()
    controller.initialize(AlgorithmConfig(), topology())
    decision = controller.decide(ControlObservation(intersection=state))
    assert decision.requested_phase_id == "P1"
    assert decision.scores["P1"] > decision.scores["P2"]


def test_max_pressure_does_not_release_to_saturated_downstream() -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P2",
        north_queue=20,
        south_queue=3,
        north_downstream_occupancy=0.95,
    )
    controller = MaxPressureController()
    controller.initialize(AlgorithmConfig(), topology())
    decision = controller.decide(ControlObservation(intersection=state))
    assert decision.scores["P1"] <= 0
    assert decision.requested_phase_id == "P2"


@pytest.mark.parametrize(
    "algorithm_name",
    ["actuated-control", "max-pressure", "coordinated-max-pressure"],
)
def test_adaptive_algorithms_hold_current_phase_before_min_green(
    algorithm_name: str,
) -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P2",
        phase_elapsed=5.0,
        north_queue=12,
        south_queue=0,
    )
    algorithm = builtin_registry().create(algorithm_name)
    algorithm.initialize(AlgorithmConfig(), topology())
    decision = algorithm.decide(
        ControlObservation(
            intersection=state,
            cloud_strategy=cloud_strategy(
                factory,
                green_ratios={"P1": 0.9, "P2": 0.1},
            ),
        )
    )
    assert decision.requested_phase_id == "P2"


def test_coordinated_controller_falls_back_until_prediction_is_ready() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=3, south_queue=3)
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.1, "P2": 0.8},
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(cloud_weight=2.0), topology())
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    assert decision.requested_phase_id == "P1"
    assert decision.selected_policy == "B1"
    assert decision.action_type == "extend_green"
    assert "PREDICTIVE_GAIN_BELOW_GATE" in decision.reason_codes
    assert "PREDICTION_FALLBACK_CURRENT_STATE" in decision.reason_codes


def test_coordinated_controller_uses_dynamic_offset_window() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=1, south_queue=1)
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.1, "P2": 0.7},
    ).model_copy(
        update={
            "target_cycle_length": 100.0,
            "target_offsets": {"J1": 5.0},
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(cloud_weight=3.0), topology())
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    assert "GREEN_WAVE_PHASE_ALIGNMENT" in decision.reason_codes
    assert decision.scores["P1"] > 0.0


def test_coordinated_controller_fuses_confident_prediction() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=5, south_queue=5)
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.4, "P2": 0.4},
    ).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 1.0, "P2": 18.0},
                    phase_queues={"P1": 1.0, "P2": 16.0},
                    spillback_risk=0.2,
                    confidence=0.9,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(
            prediction_weight=2.0,
            predicted_queue_weight=2.0,
            predicted_spillback_weight=0.0,
            predictive_pressure_retention_ratio=0.0,
        ),
        topology(),
    )
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    assert decision.action_type == "extend_green"
    assert decision.requested_phase_id == "P1"
    assert decision.selected_policy == "B3"
    assert "SWITCH_AWAITING_CONFIRMATION" in decision.reason_codes
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    assert decision.requested_phase_id == "P2"
    assert decision.selected_policy == "B3"
    assert set(decision.candidate_policy_scores) == {"B0", "B1", "B2", "B3"}
    assert decision.expected_gain_ratio is not None
    assert decision.expected_gain_ratio > 0
    assert "PREDICTION_ENHANCED" in decision.reason_codes
    assert "PREDICTION_MODEL:test-forecast-v1" in decision.reason_codes


def test_coordinated_controller_preserves_b1_signal_action_by_default() -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P2",
        phase_elapsed=15.0,
        north_queue=5,
        south_queue=2,
    )
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.05, "P2": 0.95},
    ).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 30.0},
                    phase_queues={"P1": 0.0, "P2": 25.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="conflicting-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    config = AlgorithmConfig(
        cloud_weight=3.0,
        prediction_weight=5.0,
        predicted_queue_weight=5.0,
        predicted_spillback_weight=0.0,
    )
    baseline = builtin_registry().create("actuated-control")
    baseline.initialize(config, topology())
    coordinated = CoordinatedMaxPressureController()
    coordinated.initialize(config, topology())
    observation = ControlObservation(intersection=state, cloud_strategy=strategy)

    baseline_decision = baseline.decide(observation)
    coordinated_decision = coordinated.decide(observation)

    assert baseline_decision.requested_phase_id == "P2"
    assert coordinated_decision.action_type == baseline_decision.action_type
    assert coordinated_decision.requested_phase_id == baseline_decision.requested_phase_id
    assert coordinated_decision.requested_duration_s == baseline_decision.requested_duration_s


def test_coordinated_controller_gaps_out_for_confirmed_queue_imbalance() -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P2",
        phase_elapsed=15.0,
        north_queue=12,
        south_queue=2,
    )
    strategy = cloud_strategy(factory).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 20.0, "P2": 0.0},
                    phase_queues={"P1": 20.0, "P2": 0.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="queue-imbalance-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(coordinated_gap_out_minimum_queue_vehicles=8.0),
        topology(),
    )

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B3"
    assert decision.action_type == "request_next_phase"
    assert decision.requested_phase_id == "P1"
    assert "PREDICTED_QUEUE_IMBALANCE_GAP_OUT" in decision.reason_codes


def test_coordinated_gap_out_counts_each_incoming_lane_once() -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P1",
        phase_elapsed=15.0,
        north_queue=3,
        south_queue=5,
    )
    duplicate_movement_topology = topology().model_copy(
        update={
            "phases": {
                "J1": [
                    topology().phases["J1"][0],
                    PhaseDefinition(
                        phase_id="P2",
                        movements=[
                            PhaseMovement(
                                incoming_lane_id="S.in",
                                outgoing_lane_id="S.out",
                            ),
                            PhaseMovement(
                                incoming_lane_id="S.in",
                                outgoing_lane_id="N.out",
                            ),
                        ],
                    ),
                ]
            }
        }
    )
    strategy = cloud_strategy(factory).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 20.0},
                    phase_queues={"P1": 0.0, "P2": 20.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="duplicate-lane-guard-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(), duplicate_movement_topology)

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B1"
    assert decision.requested_phase_id == "P1"
    assert "PREDICTED_QUEUE_IMBALANCE_GAP_OUT" not in decision.reason_codes


def test_coordinated_gap_out_requires_usable_downstream_capacity() -> None:
    factory = edge_factory()
    state = intersection(
        factory,
        phase="P2",
        phase_elapsed=15.0,
        north_queue=40,
        south_queue=2,
        north_downstream_occupancy=0.86,
    )
    strategy = cloud_strategy(factory).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 40.0, "P2": 0.0},
                    phase_queues={"P1": 40.0, "P2": 0.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="downstream-capacity-guard-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(), topology())

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B1"
    assert decision.requested_phase_id == "P2"
    assert "PREDICTED_QUEUE_IMBALANCE_GAP_OUT" not in decision.reason_codes


def test_coordinated_controller_uses_mobility_only_as_score_tiebreak() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=5, south_queue=4)
    lane_states = list(state.lane_states)
    lane_states[0] = lane_states[0].model_copy(
        update={"vehicle_count": 20, "mean_speed": 10.0},
    )
    state = state.model_copy(update={"lane_states": lane_states})
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.1, "P2": 0.9},
    ).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 30.0},
                    phase_queues={"P1": 0.0, "P2": 30.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(
            cloud_weight=3.0,
            prediction_weight=5.0,
            predicted_queue_weight=5.0,
            predictive_pressure_retention_ratio=0.0,
        ),
        topology(),
    )

    first = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert first.selected_policy == "B3"
    assert "SWITCH_AWAITING_CONFIRMATION" in first.reason_codes
    assert decision.selected_policy == "B3"
    assert decision.requested_phase_id == "P2"
    assert decision.scores["P2"] > decision.scores["P1"]


def test_coordinated_controller_executes_confirmed_target_at_min_green() -> None:
    factory = edge_factory()
    early_state = intersection(
        factory,
        phase="P1",
        phase_elapsed=5.0,
        north_queue=5,
        south_queue=5,
    )
    target_p2 = cloud_strategy(factory).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 30.0},
                    phase_queues={"P1": 0.0, "P2": 30.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    target_p1 = target_p2.model_copy(
        update={
            "forecasts": [
                target_p2.forecasts[0].model_copy(
                    update={
                        "phase_arrivals": {"P1": 30.0, "P2": 0.0},
                        "phase_queues": {"P1": 30.0, "P2": 0.0},
                    }
                )
            ]
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(
            prediction_weight=5.0,
            predicted_queue_weight=5.0,
            predictive_pressure_retention_ratio=0.0,
        ),
        topology(),
    )

    controller.decide(ControlObservation(intersection=early_state, cloud_strategy=target_p2))
    committed = controller.decide(
        ControlObservation(intersection=early_state, cloud_strategy=target_p2)
    )
    switch_state = early_state.model_copy(update={"phase_elapsed": 10.0})
    decision = controller.decide(
        ControlObservation(intersection=switch_state, cloud_strategy=target_p1)
    )

    assert committed.action_type == "extend_green"
    assert "SWITCH_TARGET_COMMITTED" in committed.reason_codes
    assert decision.action_type == "request_next_phase"
    assert decision.requested_phase_id == "P2"
    assert "SWITCH_TARGET_COMMITTED" in decision.reason_codes


def test_coordinated_controller_preserves_dominant_current_pressure() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=20, south_queue=0)
    strategy = cloud_strategy(factory, green_ratios={"P1": 0.1, "P2": 0.9}).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 30.0},
                    phase_queues={"P1": 0.0, "P2": 30.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(
            cloud_weight=3.0,
            prediction_weight=5.0,
            predicted_queue_weight=5.0,
        ),
        topology(),
    )

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B1"
    assert decision.requested_phase_id == "P1"
    assert "CURRENT_PRESSURE_DOMINANCE_GUARD" in decision.reason_codes


def test_coordinated_controller_does_not_extend_a_demandless_phase() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=0, south_queue=5)
    strategy = cloud_strategy(factory, green_ratios={"P1": 0.9, "P2": 0.1}).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 30.0, "P2": 0.0},
                    phase_queues={"P1": 30.0, "P2": 0.0},
                    spillback_risk=0.0,
                    confidence=0.95,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(
        AlgorithmConfig(
            cloud_weight=3.0,
            prediction_weight=5.0,
            predicted_queue_weight=5.0,
            predictive_pressure_retention_ratio=0.0,
        ),
        topology(),
    )

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B1"
    assert decision.requested_phase_id == "P2"
    assert decision.action_type == "request_next_phase"


def test_coordinated_controller_uses_baseline_candidate_for_low_demand() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=0, south_queue=0)
    strategy = cloud_strategy(factory).model_copy(
        update={
            "forecasts": [
                TrafficForecast(
                    horizon_s=60,
                    phase_arrivals={"P1": 0.0, "P2": 1.0},
                    phase_queues={"P1": 0.0, "P2": 1.0},
                    spillback_risk=0.0,
                    confidence=0.9,
                    model_id="test-forecast-v1",
                    sample_count=10,
                    generated_at_sim_time=10.0,
                )
            ],
            "prediction_status": "ready",
        }
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(low_demand_queue_threshold=3.0), topology())

    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))

    assert decision.selected_policy == "B1"
    assert decision.action_type == "hold_phase"
    assert "PREDICTIVE_GAIN_BELOW_GATE" in decision.reason_codes


def test_registry_discovers_all_phase_one_algorithms() -> None:
    names = {item["name"] for item in builtin_registry().discover()}
    assert names == {
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
    }
