from traffic_platform.comparison_service import LiveComparisonAccumulator
from traffic_platform.realtime.models import DigitalTwinSourceFrame


def _frame(
    experiment_id: str,
    simulation_time_s: float,
    *,
    queue: int,
    speed: float,
    waiting: float,
    completed: int,
    intersection_queue: int,
    spillback: float = 0.1,
    extra_metrics: dict[str, float | int] | None = None,
) -> DigitalTwinSourceFrame:
    return DigitalTwinSourceFrame(
        experiment_id=experiment_id,
        scenario_id="scene",
        simulation_time_s=simulation_time_s,
        tick_hz=10.0,
        vehicles=(),
        pedestrians=(),
        traffic_lights=(),
        events=(),
        metrics={
            "total_queue_vehicles": queue,
            "mean_speed_m_s": speed,
            "waiting_time_s": waiting,
            "completed_trips": completed,
            **(extra_metrics or {}),
        },
        intersection_metrics=(
            {
                "intersection_id": "K01",
                "queue_vehicles": intersection_queue,
                "mean_speed_m_s": speed,
                "spillback_risk": spillback,
                "approaches": [
                    {
                        "lane_id": "edge-north_0",
                        "direction": "north",
                        "movement": "through",
                        "vehicle_count": intersection_queue + 2,
                        "queue_vehicles": intersection_queue,
                        "mean_speed_m_s": speed,
                        "occupancy": 0.5,
                        "downstream_occupancy": 0.2,
                    }
                ],
            },
        ),
    )


def test_live_comparison_waits_for_full_window_before_verdict() -> None:
    comparison = LiveComparisonAccumulator(window_s=60)
    comparison.add(
        _frame("baseline", 10, queue=20, speed=4, waiting=100, completed=2, intersection_queue=12),
        _frame("candidate", 10, queue=10, speed=6, waiting=70, completed=4, intersection_queue=7),
    )

    summary = comparison.summary()

    assert summary["valid"] is True
    assert summary["verdict"] == "warming_up"
    assert summary["warmup_remaining_s"] == 60
    assert summary["reason"] == "建立对照基线"


def test_live_comparison_reports_network_and_intersection_improvement() -> None:
    comparison = LiveComparisonAccumulator(window_s=60)
    for simulation_time_s in (0, 30, 60):
        comparison.add(
            _frame(
                "baseline",
                simulation_time_s,
                queue=20,
                speed=4,
                waiting=100,
                completed=int(simulation_time_s / 10),
                intersection_queue=12,
            ),
            _frame(
                "candidate",
                simulation_time_s,
                queue=10,
                speed=6,
                waiting=70,
                completed=int(simulation_time_s / 10) + 3,
                intersection_queue=7,
            ),
        )

    summary = comparison.summary()

    assert summary["verdict"] == "improved"
    assert summary["network"]["total_queue_vehicles"]["benefit"] == 10
    assert summary["network"]["mean_speed_m_s"]["benefit"] == 2
    assert summary["counts"] == {
        "improved_intersections": 1,
        "stable_intersections": 0,
        "worse_intersections": 0,
    }
    assert summary["intersections"][0]["label"] == "↓ 少排5辆"
    approach = summary["intersections"][0]["approaches"][0]
    assert approach["lane_id"] == "edge-north_0"
    assert approach["verdict"] == "improved"
    assert approach["delta"]["queue_vehicles"] == -5


def test_live_comparison_exposes_mixed_result_and_new_spillback() -> None:
    comparison = LiveComparisonAccumulator(window_s=1)
    comparison.add(
        _frame("baseline", 0, queue=20, speed=4, waiting=100, completed=2, intersection_queue=5),
        _frame("candidate", 0, queue=10, speed=6, waiting=70, completed=4, intersection_queue=8, spillback=0.8),
    )
    comparison.add(
        _frame("baseline", 1, queue=20, speed=4, waiting=100, completed=2, intersection_queue=5),
        _frame("candidate", 1, queue=10, speed=6, waiting=70, completed=4, intersection_queue=8, spillback=0.8),
    )

    summary = comparison.summary()

    assert summary["verdict"] == "mixed"
    assert summary["intersections"][0]["verdict"] == "worse"
    assert summary["intersections"][0]["label"] == "↑ 多排3辆"


def test_live_comparison_includes_max_queue_multimodal_and_safety_metrics() -> None:
    comparison = LiveComparisonAccumulator(window_s=1)
    baseline_extra = {
        "max_queue_vehicles": 18,
        "bicycle_waiting_time_s": 14,
        "bicycle_queue_count": 8,
        "pedestrian_waiting_time_s": 20,
        "pedestrian_crossing_count": 3,
        "motor_bicycle_conflict_count": 2,
        "motor_pedestrian_conflict_count": 2,
        "bicycle_pedestrian_conflict_count": 1,
    }
    candidate_extra = {
        "max_queue_vehicles": 10,
        "bicycle_waiting_time_s": 8,
        "bicycle_queue_count": 4,
        "pedestrian_waiting_time_s": 11,
        "pedestrian_crossing_count": 6,
        "motor_bicycle_conflict_count": 0,
        "motor_pedestrian_conflict_count": 1,
        "bicycle_pedestrian_conflict_count": 0,
    }
    for simulation_time_s in (0, 1):
        comparison.add(
            _frame("baseline", simulation_time_s, queue=20, speed=4, waiting=100,
                   completed=2, intersection_queue=12, extra_metrics=baseline_extra),
            _frame("candidate", simulation_time_s, queue=10, speed=6, waiting=70,
                   completed=4, intersection_queue=7, extra_metrics=candidate_extra),
        )

    network = comparison.summary()["network"]

    assert network["max_queue_vehicles"]["benefit"] == 8
    assert network["pedestrian_waiting_time_s"]["trend"] == "improved"
    assert network["pedestrian_crossing_count"]["benefit"] == 3
    assert network["bicycle_queue_count"]["benefit"] == 4
    assert network["motor_pedestrian_conflict_count"]["benefit"] == 1


def test_live_comparison_invalidates_different_simulation_times() -> None:
    comparison = LiveComparisonAccumulator()

    try:
        comparison.add(
            _frame("baseline", 10, queue=1, speed=4, waiting=1, completed=1, intersection_queue=1),
            _frame("candidate", 11, queue=1, speed=4, waiting=1, completed=1, intersection_queue=1),
        )
    except ValueError as error:
        assert "simulation time mismatch" in str(error)
    else:
        raise AssertionError("time mismatch must invalidate a paired comparison")

    assert comparison.summary()["verdict"] == "invalid"
