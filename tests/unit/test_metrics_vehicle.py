"""Actual-only metrics and vehicle guidance limits."""

from traffic_platform.metrics_engine.calculator import MetricsAccumulator, MetricSample
from traffic_platform.vehicle_agent.agent import VehicleDynamics, VehicleGuidanceAgent


def test_metrics_explicitly_report_unrun_then_aggregate_samples() -> None:
    accumulator = MetricsAccumulator()
    assert accumulator.summary() == {"status": "尚未运行"}
    accumulator.add(
        MetricSample(
            simulation_time_s=1.0,
            mean_speed_m_s=10.0,
            total_queue_vehicles=5,
            total_queue_m=37.5,
            throughput_vehicles=3,
            completed_trips=2,
            waiting_time_s=1.0,
            time_loss_s=2.0,
            stop_count=1,
            spillback_intersections=0,
            bicycle_completed_trips=2,
            bicycle_waiting_time_s=3.0,
            pedestrian_completed_trips=4,
            pedestrian_waiting_time_s=5.0,
            motor_pedestrian_conflict_count=1,
            minimum_ttc_s=1.8,
        )
    )
    summary = accumulator.summary()
    assert summary["mean_speed"] == 10.0
    assert summary["bicycle_completed_trips"] == 2
    assert summary["pedestrian_completed_trips"] == 4
    assert summary["motor_pedestrian_conflict_count"] == 1
    assert summary["minimum_ttc_s"] == 1.8


def test_guidance_respects_connectivity_speed_and_dynamics() -> None:
    agent = VehicleGuidanceAgent()
    non_connected = agent.apply(
        10.0,
        VehicleDynamics(
            connected=False,
            current_speed_m_s=8.0,
            speed_limit_m_s=13.0,
        ),
    )
    assert not non_connected.executed
    connected = agent.apply(
        20.0,
        VehicleDynamics(
            connected=True,
            current_speed_m_s=8.0,
            speed_limit_m_s=13.0,
        ),
        horizon_s=2.0,
    )
    assert connected.executed
    assert connected.applied_speed_m_s == 12.0
