from traffic_platform.metrics_engine.surrogate_safety import SurrogateSafetyMonitor
from traffic_platform.sumo_adapter import PedestrianSnapshot, VehicleSnapshot


def _vehicle(identifier: str, x_m: float, heading_deg: float) -> VehicleSnapshot:
    return VehicleSnapshot(
        vehicle_id=identifier,
        vehicle_type="passenger",
        vehicle_class="passenger",
        road_id="edge",
        lane_id="edge_0",
        x_m=x_m,
        y_m=0.0,
        lane_position_m=x_m,
        speed_m_s=5.0,
        acceleration_m_s2=0.0,
        heading_deg=heading_deg,
        route_id="route",
        next_intersection_id="tls",
        distance_to_stop_line_m=10.0,
        waiting_time_s=0.0,
        co2_mg_s=0.0,
        nox_mg_s=0.0,
        fuel_mg_s=0.0,
    )


def _pedestrian(identifier: str, x_m: float) -> PedestrianSnapshot:
    return PedestrianSnapshot(
        pedestrian_id=identifier,
        pedestrian_type="pedestrian_adult",
        road_id=":tls_c0",
        lane_id=":tls_c0_0",
        x_m=x_m,
        y_m=0.0,
        speed_m_s=1.3,
        waiting_time_s=0.0,
        walking_stage_index=0,
        crossing_id=":tls_c0",
        waiting_area_id=None,
    )


def test_observed_ttc_conflict_is_trajectory_derived() -> None:
    monitor = SurrogateSafetyMonitor(search_radius_m=12.0)
    conflicts = monitor.observe(
        0.0,
        [_vehicle("east", -5.0, 90.0), _vehicle("west", 5.0, 270.0)],
        [],
    )
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "motor_motor"
    assert conflicts[0].ttc_s == 1.0
    assert conflicts[0].minimum_distance_m < 0.01


def test_pet_requires_observed_cell_exit_and_different_mode_entry() -> None:
    monitor = SurrogateSafetyMonitor(conflict_distance_m=2.5)
    monitor.observe(0.0, [], [_pedestrian("person", 0.5)])
    monitor.observe(1.0, [], [_pedestrian("person", 3.0)])
    conflicts = monitor.observe(2.0, [_vehicle("car", 0.5, 90.0)], [])
    assert any(item.conflict_type == "motor_pedestrian" and item.pet_s == 1.0 for item in conflicts)
