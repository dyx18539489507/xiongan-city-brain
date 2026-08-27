"""Behavioral coverage for requested green phases and mandatory clearance."""

from pytest import MonkeyPatch
from tests.factories import edge_factory, intersection

from traffic_platform.algorithm_sdk.types import (
    NetworkTopology,
    PhaseDefinition,
    PhaseMovement,
)
from traffic_platform.contracts.models import ExecutionStatus
from traffic_platform.edge_service.controller import EdgeController


class TransitionAdapter:
    def __init__(self) -> None:
        self.phase_calls: list[tuple[str, int]] = []
        self.duration_calls: list[tuple[str, float]] = []

    def set_traffic_light_phase(self, intersection_id: str, phase_index: int) -> None:
        self.phase_calls.append((intersection_id, phase_index))

    def set_phase_duration(self, intersection_id: str, duration_s: float) -> None:
        self.duration_calls.append((intersection_id, duration_s))


def transition_topology() -> NetworkTopology:
    return NetworkTopology(
        intersection_ids=["J1"],
        phases={
            "J1": [
                PhaseDefinition(
                    phase_id="0",
                    movements=[PhaseMovement(incoming_lane_id="N.in", outgoing_lane_id="N.out")],
                ),
                PhaseDefinition(
                    phase_id="3",
                    movements=[PhaseMovement(incoming_lane_id="S.in", outgoing_lane_id="S.out")],
                ),
            ]
        },
        downstream_intersections={"J1": []},
        phase_order={"J1": ["0", "1", "2", "3", "4", "5"]},
        phase_durations_s={"J1": {"0": 30.0, "1": 3.0, "2": 1.0, "3": 30.0}},
        clearance_phase_ids={"J1": {"1", "2", "4", "5"}},
        clearance_paths={"J1": {"0": {"3": ["1", "2"]}, "3": {"0": ["4", "5"]}}},
    )


def state_for_phase(phase_id: str, elapsed_s: float):
    state = intersection(
        edge_factory(),
        phase=phase_id,
        phase_elapsed=elapsed_s,
        north_queue=0,
        south_queue=10,
    )
    lanes = [
        lane.model_copy(
            update={
                "movement": (
                    "0" if lane.lane_id == "N.in" else "3" if lane.lane_id == "S.in" else "out"
                )
            }
        )
        for lane in state.lane_states
    ]
    return state.model_copy(update={"lane_states": lanes})


def test_requested_green_is_reached_after_yellow_and_all_red() -> None:
    adapter = TransitionAdapter()
    controller = EdgeController(
        adapter,  # type: ignore[arg-type]
        edge_factory(),
        transition_topology(),
        control_algorithm="actuated-control",
        isolate_algorithms=False,
    )
    try:
        started = controller.control(state_for_phase("0", 15.0))
        assert started is not None
        assert started.execution_status == ExecutionStatus.EXECUTED
        assert adapter.phase_calls == [("J1", 1)]
        assert adapter.duration_calls == [("J1", 4.0)]

        holding_yellow = controller.control(state_for_phase("1", 2.0))
        assert holding_yellow is not None
        assert holding_yellow.executed_action["action_type"] == "hold_clearance"

        controller.control(state_for_phase("1", 3.0))
        assert adapter.phase_calls[-1] == ("J1", 2)
        assert adapter.duration_calls[-1] == ("J1", 2.0)

        controller.control(state_for_phase("2", 1.0))
        assert adapter.phase_calls[-1] == ("J1", 3)

        completed = controller.control(state_for_phase("3", 0.0))
        assert completed is not None
        assert completed.observed_effect["target_phase_observed"] == "true"
        assert "J1" not in controller.pending_transitions
    finally:
        controller.close()


def test_adjacent_compatible_green_is_activated_directly() -> None:
    adapter = TransitionAdapter()
    topology = transition_topology().model_copy(
        update={"clearance_paths": {"J1": {"0": {"3": []}}}}
    )
    controller = EdgeController(
        adapter,  # type: ignore[arg-type]
        edge_factory(),
        topology,
        control_algorithm="actuated-control",
        isolate_algorithms=False,
    )
    try:
        feedback = controller.control(state_for_phase("0", 15.0))

        assert feedback is not None
        assert feedback.execution_status == ExecutionStatus.EXECUTED
        assert feedback.executed_action["action_type"] == "activate_requested_green"
        assert adapter.phase_calls == [("J1", 3)]
        assert controller.pending_transitions == {}
    finally:
        controller.close()


def test_algorithm_failure_uses_in_process_fixed_time_fallback(
    monkeypatch: MonkeyPatch,
) -> None:
    adapter = TransitionAdapter()
    controller = EdgeController(
        adapter,  # type: ignore[arg-type]
        edge_factory(),
        transition_topology(),
        control_algorithm="actuated-control",
        isolate_algorithms=False,
    )
    try:
        def fail_decision(_: object) -> None:
            raise RuntimeError("simulated isolated worker failure")

        monkeypatch.setattr(
            controller.algorithms["actuated-control"],
            "decide",
            fail_decision,
        )

        feedback = controller.control(state_for_phase("0", 15.0))

        assert feedback is not None
        assert feedback.requested_action["selected_policy"] == "B0"
        assert controller.algorithm_failure_count == 1
        assert adapter.phase_calls == []
    finally:
        controller.close()


def test_controller_only_initializes_algorithms_reachable_in_its_mode() -> None:
    fixed = EdgeController(
        TransitionAdapter(),  # type: ignore[arg-type]
        edge_factory(),
        transition_topology(),
        control_algorithm="fixed-time",
        isolate_algorithms=False,
    )
    coordinated = EdgeController(
        TransitionAdapter(),  # type: ignore[arg-type]
        edge_factory(),
        transition_topology(),
        control_algorithm="coordinated-max-pressure",
        isolate_algorithms=False,
    )
    try:
        assert fixed.algorithms == {}
        assert fixed.algorithm_version("fixed-time") == fixed.safe_fallback.version
        assert set(coordinated.algorithms) == {
            "max-pressure",
            "coordinated-max-pressure",
        }
    finally:
        fixed.close()
        coordinated.close()
