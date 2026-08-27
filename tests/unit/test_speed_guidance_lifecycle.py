"""Vehicle guidance must expire back to native SUMO car following."""

from types import SimpleNamespace
from typing import Any

import pytest

from traffic_platform.algorithm_sdk.types import AlgorithmConfig
from traffic_platform.experiment_service.engine import ExperimentRunner
from traffic_platform.safety_kernel import SafetyKernel
from traffic_platform.vehicle_agent.agent import (
    GlosaEffectivenessGate,
    GlosaMobilityRegimeClassifier,
    VehicleGuidanceAgent,
)


class _Adapter:
    def __init__(self) -> None:
        self.released: list[str] = []
        self.applied: list[tuple[str, float]] = []

    def release_speed_guidance(self, vehicle_id: str) -> None:
        self.released.append(vehicle_id)

    def apply_speed_guidance(self, vehicle_id: str, speed_m_s: float) -> None:
        self.applied.append((vehicle_id, speed_m_s))


def test_glosa_gate_stays_inactive_while_collecting_evidence() -> None:
    gate = GlosaEffectivenessGate(window_s=10.0)

    active = gate.observe(
        simulation_time_s=0.0,
        mean_speed_m_s=10.0,
        queue_vehicles=100,
    )

    assert active is False
    assert gate.active is False
    assert gate.reason == "WARMING_UP"
    assert gate.speed_change_ratio is None
    assert gate.queue_reduction_ratio is None


def test_glosa_gate_stays_active_when_queue_is_falling() -> None:
    gate = GlosaEffectivenessGate(
        window_s=10.0,
        cooldown_s=5.0,
        minimum_speed_loss_ratio=0.01,
        minimum_queue_reduction_ratio=0.02,
    )

    active = True
    for second in range(11):
        active = gate.observe(
            simulation_time_s=float(second),
            mean_speed_m_s=10.0 - 0.1 * second,
            queue_vehicles=100 - 4 * second,
        )

    assert active is True
    assert gate.reason == "QUEUE_REDUCTION_JUSTIFIES_GUIDANCE"
    assert gate.queue_reduction_ratio is not None
    assert gate.queue_reduction_ratio >= 0.02


def test_glosa_gate_stays_inactive_without_proven_queue_reduction() -> None:
    gate = GlosaEffectivenessGate(
        window_s=10.0,
        minimum_speed_loss_ratio=0.01,
        minimum_queue_reduction_ratio=0.02,
    )

    active = False
    for second in range(11):
        active = gate.observe(
            simulation_time_s=float(second),
            mean_speed_m_s=10.0 + 0.1 * second,
            queue_vehicles=100,
        )

    assert active is False
    assert gate.active is False
    assert gate.reason == "QUEUE_REDUCTION_NOT_PROVEN"
    assert gate.speed_change_ratio is not None
    assert gate.speed_change_ratio > 0.0
    assert gate.queue_reduction_ratio == pytest.approx(0.0)


def test_glosa_gate_pauses_when_speed_loss_has_no_queue_payoff() -> None:
    gate = GlosaEffectivenessGate(
        window_s=10.0,
        cooldown_s=5.0,
        minimum_speed_loss_ratio=0.01,
        minimum_queue_reduction_ratio=0.02,
    )

    active = True
    for second in range(11):
        active = gate.observe(
            simulation_time_s=float(second),
            mean_speed_m_s=10.0 - 0.2 * second,
            queue_vehicles=100 + second,
        )

    assert active is False
    assert gate.reason in {
        "SPEED_LOSS_WITHOUT_QUEUE_PAYOFF",
        "COOLDOWN_AFTER_NO_QUEUE_PAYOFF",
    }
    assert gate.speed_change_ratio is not None
    assert gate.speed_change_ratio <= -0.01
    assert gate.cooldown_until_s > 10.0


def test_glosa_gate_cooldown_releases_even_when_high_mobility_is_locked() -> None:
    adapter = _Adapter()
    gate = GlosaEffectivenessGate(window_s=10.0, cooldown_s=20.0)
    for second in range(11):
        gate.observe(
            simulation_time_s=float(second),
            mean_speed_m_s=10.0 - 0.2 * second,
            queue_vehicles=100 + second,
        )
    congested_classifier = GlosaMobilityRegimeClassifier(
        window_s=1.0,
        high_mobility_speed_threshold_m_s=11.0,
    )
    congested_classifier.observe(simulation_time_s=0.0, mean_speed_m_s=10.0)
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 1.0})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-red": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-green")],
                    ),
                    SimpleNamespace(
                        phase_id="1",
                        movements=[SimpleNamespace(incoming_lane_id="lane-red")],
                    ),
                ]
            },
            phase_order={"K01": ["0", "1"]},
            phase_durations_s={"K01": {"0": 20.0, "1": 20.0}},
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(
                intersection_id="K01",
                current_phase_id="0",
                phase_remaining=10.0,
            )
        },
        glosa_effectiveness_gate=gate,
        glosa_mobility_classifier=congested_classifier,
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-red",
            vehicle_type="connected_vehicle",
            lane_id="lane-red",
            speed_m_s=10.0,
            distance_to_stop_line_m=30.0,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=11.0,
    )

    assert result == (0, 0, 0)
    assert adapter.applied == []
    assert adapter.released == ["cv-red"]

    classifier = GlosaMobilityRegimeClassifier(
        window_s=60.0,
        high_mobility_speed_threshold_m_s=4.82,
    )
    classifier.observe(simulation_time_s=0.0, mean_speed_m_s=5.0)
    classifier.observe(simulation_time_s=60.0, mean_speed_m_s=5.0)
    controller.glosa_mobility_classifier = classifier
    high_mobility_result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=12.0,
    )

    assert high_mobility_result == (0, 0, 0)
    assert adapter.applied == []
    assert adapter.released == ["cv-red", "cv-red"]


def test_inactive_guidance_releases_connected_vehicle_speed_override() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 1.0})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-1": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-1")],
                    )
                ]
            },
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(intersection_id="K01", current_phase_id="0")
        },
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-1",
            vehicle_type="connected_vehicle",
            lane_id="lane-1",
            speed_m_s=9.8,
        ),
        SimpleNamespace(
            vehicle_id="car-1",
            vehicle_type="passenger",
            lane_id="lane-1",
            speed_m_s=9.8,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (0, 0, 0)
    assert adapter.released == ["cv-1"]


def test_small_speed_reduction_releases_connected_vehicle_speed_override() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(
            minimum_actionable_speed_reduction_ratio=0.05,
        ),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 0.99})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-1": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-1")],
                    )
                ]
            },
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(intersection_id="K01", current_phase_id="0")
        },
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-1",
            vehicle_type="connected_vehicle",
            lane_id="lane-1",
            speed_m_s=9.8,
        ),
        SimpleNamespace(
            vehicle_id="car-1",
            vehicle_type="passenger",
            lane_id="lane-1",
            speed_m_s=9.8,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (0, 0, 0)
    assert adapter.released == ["cv-1"]


def test_small_speed_target_accelerates_green_queue_connected_vehicle() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 0.99})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-1": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-1")],
                    )
                ]
            },
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(intersection_id="K01", current_phase_id="0")
        },
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-1",
            vehicle_type="connected_vehicle",
            lane_id="lane-1",
            speed_m_s=0.2,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (1, 0, 0)
    assert adapter.released == []
    assert adapter.applied == [("cv-1", pytest.approx(4.0))]

    controller.last_state_by_intersection["K01"] = SimpleNamespace(
        intersection_id="K01",
        current_phase_id="1",
    )
    released = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=11.0,
    )

    assert released == (0, 0, 0)
    assert adapter.released == ["cv-1"]

    controller.last_state_by_intersection["K01"] = SimpleNamespace(
        intersection_id="K01",
        current_phase_id="0",
    )
    vehicles[0].speed_m_s = 0.0
    queue_discharge = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=12.0,
    )

    assert queue_discharge == (1, 0, 0)
    assert adapter.applied[-1] == ("cv-1", pytest.approx(4.0))


def test_red_approach_guidance_aligns_connected_vehicle_to_next_green() -> None:
    adapter = _Adapter()
    gate = GlosaEffectivenessGate(window_s=10.0)
    for second in range(11):
        gate.observe(
            simulation_time_s=float(second),
            mean_speed_m_s=10.0,
            queue_vehicles=100 - 4 * second,
        )
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        glosa_effectiveness_gate=gate,
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 1.0})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-red": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-green")],
                    ),
                    SimpleNamespace(
                        phase_id="1",
                        movements=[SimpleNamespace(incoming_lane_id="lane-red")],
                    ),
                ]
            },
            phase_order={"K01": ["0", "1"]},
            phase_durations_s={"K01": {"0": 20.0, "1": 20.0}},
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(
                intersection_id="K01",
                current_phase_id="0",
                phase_remaining=10.0,
            )
        },
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-red",
            vehicle_type="connected_vehicle",
            lane_id="lane-red",
            speed_m_s=10.0,
            distance_to_stop_line_m=70.0,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result[0] == 1
    assert adapter.applied == [("cv-red", pytest.approx(7.0))]


@pytest.mark.parametrize(
    ("high_mobility_threshold_m_s", "expected_minimum_m_s", "should_apply"),
    [(4.85, 3.0, False), (11.0, 1.0, False)],
)
def test_glosa_minimum_speed_adapts_to_network_mobility(
    high_mobility_threshold_m_s: float,
    expected_minimum_m_s: float,
    should_apply: bool,
) -> None:
    adapter = _Adapter()
    classifier = GlosaMobilityRegimeClassifier(
        window_s=1.0,
        high_mobility_speed_threshold_m_s=high_mobility_threshold_m_s,
    )
    classifier.observe(simulation_time_s=0.0, mean_speed_m_s=10.0)
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(
            high_mobility_speed_threshold_m_s=high_mobility_threshold_m_s,
        ),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 1.0})
        },
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-red": 10.0},
            phases={
                "K01": [
                    SimpleNamespace(
                        phase_id="0",
                        movements=[SimpleNamespace(incoming_lane_id="lane-green")],
                    ),
                    SimpleNamespace(
                        phase_id="1",
                        movements=[SimpleNamespace(incoming_lane_id="lane-red")],
                    ),
                ]
            },
            phase_order={"K01": ["0", "1"]},
            phase_durations_s={"K01": {"0": 20.0, "1": 20.0}},
        ),
        last_state_by_intersection={
            "K01": SimpleNamespace(
                intersection_id="K01",
                current_phase_id="0",
                phase_remaining=10.0,
            )
        },
        glosa_mobility_classifier=classifier,
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-red",
            vehicle_type="connected_vehicle",
            lane_id="lane-red",
            speed_m_s=10.0,
            distance_to_stop_line_m=20.0,
        )
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert controller.last_glosa_minimum_speed_m_s == expected_minimum_m_s
    assert controller.glosa_mobility_classifier.regime == (
        "high_mobility" if expected_minimum_m_s == 3.0 else "congested"
    )
    assert result == ((1, 0, 1) if should_apply else (0, 0, 0))
    assert adapter.applied == ([("cv-red", pytest.approx(4.0))] if should_apply else [])
    assert adapter.released == ([] if should_apply else ["cv-red"])


def test_missing_cloud_strategy_releases_connected_vehicle_override() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={},
    )
    vehicles: Any = [
        SimpleNamespace(vehicle_id="cv-1", vehicle_type="connected_vehicle"),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (0, 0, 0)
    assert adapter.released == ["cv-1"]


def test_non_b3_algorithm_does_not_change_vehicle_speed_lifecycle() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={},
    )
    vehicles: Any = [
        SimpleNamespace(vehicle_id="cv-1", vehicle_type="connected_vehicle"),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (0, 0, 0)
    assert adapter.released == []


def test_actionable_speed_reduction_is_applied() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(
            minimum_actionable_speed_reduction_ratio=0.05,
        ),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 0.94})
        },
        topology=SimpleNamespace(speed_limits_m_s={"lane-1": 10.0}),
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-1",
            vehicle_type="connected_vehicle",
            lane_id="lane-1",
            speed_m_s=10.0,
        ),
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (1, 0, 0)
    assert adapter.released == []
    assert adapter.applied == [("cv-1", pytest.approx(9.4))]


def test_default_rejects_small_network_wide_speed_cap() -> None:
    adapter = _Adapter()
    controller: Any = SimpleNamespace(
        control_algorithm="coordinated-max-pressure",
        algorithm_config=AlgorithmConfig(),
        last_strategy_by_intersection={
            "K01": SimpleNamespace(speed_guidance_parameters={"target_speed_factor": 0.94})
        },
        last_state_by_intersection={},
        topology=SimpleNamespace(
            speed_limits_m_s={"lane-1": 10.0},
            phases={},
            phase_order={},
            phase_durations_s={},
        ),
        safety=SafetyKernel(),
        factory=SimpleNamespace(experiment_id="guidance-test"),
    )
    vehicles: Any = [
        SimpleNamespace(
            vehicle_id="cv-1",
            vehicle_type="connected_vehicle",
            lane_id="lane-1",
            speed_m_s=10.0,
        )
    ]

    result = ExperimentRunner._apply_guidance(
        adapter,  # type: ignore[arg-type]
        controller,
        VehicleGuidanceAgent(),
        vehicles,
        simulation_time_s=10.0,
    )

    assert result == (0, 0, 0)
    assert adapter.applied == []
    assert adapter.released == ["cv-1"]
