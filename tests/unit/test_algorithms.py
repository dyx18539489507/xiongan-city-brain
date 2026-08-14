"""B0-B4 baseline decisions and registry behavior."""

from tests.factories import cloud_strategy, edge_factory, intersection, topology

from traffic_platform.algorithm_sdk.types import AlgorithmConfig, ControlObservation
from traffic_platform.algorithms import builtin_registry
from traffic_platform.algorithms.coordinated import CoordinatedMaxPressureController
from traffic_platform.algorithms.max_pressure import MaxPressureController
from traffic_platform.algorithms.predictive import PredictiveAIControllerPlaceholder


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


def test_coordinated_controller_uses_valid_cloud_target() -> None:
    factory = edge_factory()
    state = intersection(factory, phase="P1", north_queue=3, south_queue=3)
    strategy = cloud_strategy(
        factory,
        green_ratios={"P1": 0.1, "P2": 0.8},
    )
    controller = CoordinatedMaxPressureController()
    controller.initialize(AlgorithmConfig(cloud_weight=2.0), topology())
    decision = controller.decide(ControlObservation(intersection=state, cloud_strategy=strategy))
    assert decision.requested_phase_id == "P2"
    assert decision.reason_codes == [
        "CLOUD_TARGET_APPLIED",
        "GREEN_WAVE_PHASE_ALIGNMENT",
    ]


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


def test_predictive_placeholder_never_fabricates_output() -> None:
    factory = edge_factory()
    controller = PredictiveAIControllerPlaceholder()
    controller.initialize(AlgorithmConfig(), topology())
    decision = controller.decide(ControlObservation(intersection=intersection(factory)))
    assert decision.status == "MODEL_NOT_AVAILABLE"
    assert decision.scores == {}
    assert decision.action_type == "fallback_fixed_time"


def test_registry_discovers_all_phase_one_algorithms() -> None:
    names = {item["name"] for item in builtin_registry().discover()}
    assert names == {
        "fixed-time",
        "actuated-control",
        "max-pressure",
        "coordinated-max-pressure",
        "predictive-controller-placeholder",
    }
