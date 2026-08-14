"""Strict model, expiry and idempotency behavior."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.contracts.idempotency import IdempotencyGuard
from traffic_platform.contracts.models import (
    BicycleState,
    EmissionEstimate,
    PedestrianState,
    PositionXY,
    VehicleState,
)


def vehicle(envelope: Callable[..., dict[str, Any]], **overrides: Any) -> VehicleState:
    """Build one valid strict vehicle message."""

    payload = {
        **envelope(),
        "vehicle_id": "veh-1",
        "vehicle_type": "connected_vehicle",
        "connected": True,
        "road_id": "edge-1",
        "lane_id": "lane-1",
        "position_xy": PositionXY(x=1.0, y=2.0),
        "lane_position": 10.0,
        "speed": 8.0,
        "acceleration": 0.1,
        "heading": 90.0,
        "route_id": "route-1",
        "next_intersection_id": "J1",
        "distance_to_stop_line": 30.0,
        "turn_direction": "straight",
        "waiting_time": 0.0,
        "stop_count": 0,
        "emission_estimate": EmissionEstimate(co2_mg_s=1.0, nox_mg_s=0.1),
        "fuel_consumption_estimate": 0.5,
    }
    payload.update(overrides)
    return VehicleState(**payload)


def test_vehicle_state_serializes_and_rejects_coercion(
    envelope: Callable[..., dict[str, Any]],
) -> None:
    message = vehicle(envelope)
    assert message.model_dump(mode="json")["speed"] == 8.0
    with pytest.raises(ValidationError):
        vehicle(envelope, speed="8.0")


def test_expired_message_is_rejected(
    envelope: Callable[..., dict[str, Any]],
) -> None:
    now = datetime.now(UTC)
    message = vehicle(
        envelope,
        created_at=now - timedelta(seconds=2),
        expires_at=now - timedelta(seconds=1),
    )
    with pytest.raises(PlatformError) as caught:
        message.ensure_not_expired()
    assert caught.value.code == ErrorCode.MESSAGE_EXPIRED


def test_idempotency_and_sequence_guards(
    envelope: Callable[..., dict[str, Any]],
) -> None:
    guard = IdempotencyGuard()
    first = vehicle(envelope)
    guard.accept(first)
    with pytest.raises(PlatformError) as duplicate:
        guard.accept(first)
    assert duplicate.value.code == ErrorCode.DUPLICATE_MESSAGE
    second = vehicle(envelope, sequence_number=1)
    with pytest.raises(PlatformError) as unordered:
        guard.accept(second)
    assert unordered.value.code == ErrorCode.OUT_OF_ORDER_MESSAGE


def test_sequence_numbers_restart_for_a_new_experiment(
    envelope: Callable[..., dict[str, Any]],
) -> None:
    guard = IdempotencyGuard()
    first = vehicle(envelope)
    guard.accept(first)
    next_experiment = first.model_copy(
        update={
            "message_id": uuid4(),
            "experiment_id": "experiment-next",
            "sequence_number": 0,
        }
    )
    guard.accept(next_experiment)


def test_active_mode_states_are_strict_si_unit_messages(
    envelope: Callable[..., dict[str, Any]],
) -> None:
    bicycle = BicycleState(
        **envelope(),
        bicycle_id="bike-1",
        bicycle_type="electric_bicycle",
        electric=True,
        road_id="edge-1",
        lane_id="edge-1_0",
        position_xy=PositionXY(x=1.0, y=2.0),
        lane_position_m=3.0,
        speed_m_s=5.0,
        acceleration_m_s2=0.2,
        waiting_time_s=0.0,
        next_intersection_id="K01",
        turn_direction="straight",
        in_bicycle_lane=True,
        conflict_risk=0.1,
    )
    pedestrian = PedestrianState(
        **envelope(sequence_number=1),
        pedestrian_id="person-1",
        pedestrian_type="pedestrian_adult",
        position_xy=PositionXY(x=2.0, y=3.0),
        road_id="walk-edge",
        lane_id="walk-edge_0",
        speed_m_s=1.3,
        waiting_time_s=2.0,
        walking_stage_index=0,
        crossing_id="crossing-1",
        waiting_area_id="walking-area-1",
        signal_state="G",
        conflict_risk=0.0,
    )
    assert bicycle.electric is True
    assert pedestrian.speed_m_s == 1.3
    with pytest.raises(ValidationError):
        BicycleState(**{**bicycle.model_dump(), "conflict_risk": 1.1})
