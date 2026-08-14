"""Stateful full-snapshot to spawn/update/remove delta encoder."""

from __future__ import annotations

from traffic_platform.realtime.models import (
    DigitalTwinDelta,
    DigitalTwinInit,
    DigitalTwinSourceFrame,
    EntityRemovalSet,
    EntityStateSet,
    PedestrianEntity,
    RealtimeEvent,
    SafetyConflictEntity,
    SceneReference,
    TrafficLightEntity,
    VehicleEntity,
)


def _round(value: float) -> float:
    return round(float(value), 3)


def _color(value: tuple[int, int, int, int]) -> str:
    return "#" + "".join(f"{max(0, min(255, int(channel))):02X}" for channel in value[:3])


def _vehicle(source: object) -> VehicleEntity:
    from traffic_platform.sumo_adapter import VehicleSnapshot

    if not isinstance(source, VehicleSnapshot):
        raise TypeError("vehicle source must be VehicleSnapshot")
    return VehicleEntity(
        id=source.vehicle_id,
        type=source.vehicle_type,
        vehicle_class=source.vehicle_class,
        x=_round(source.x_m),
        y=_round(source.y_m),
        angle=_round(source.heading_deg % 360.0),
        speed=_round(source.speed_m_s),
        acceleration=_round(source.acceleration_m_s2),
        lane_id=source.lane_id,
        edge_id=source.road_id,
        route_id=source.route_id,
        signals=source.signals,
        color=_color(source.color_rgba),
        brake=source.acceleration_m_s2 < -0.5,
        status="waiting" if source.speed_m_s < 0.1 else "moving",
    )


def _pedestrian(source: object) -> PedestrianEntity:
    from traffic_platform.sumo_adapter import PedestrianSnapshot

    if not isinstance(source, PedestrianSnapshot):
        raise TypeError("pedestrian source must be PedestrianSnapshot")
    return PedestrianEntity(
        id=source.pedestrian_id,
        type=source.pedestrian_type,
        x=_round(source.x_m),
        y=_round(source.y_m),
        angle=_round(source.heading_deg % 360.0),
        speed=_round(source.speed_m_s),
        lane_id=source.lane_id,
        edge_id=source.road_id,
        crossing_id=source.crossing_id,
        waiting_area_id=source.waiting_area_id,
        status="waiting" if source.speed_m_s < 0.1 else "walking",
    )


def _optional_float(value: object) -> float | None:
    return _round(value) if isinstance(value, int | float) else None


def _conflict(
    source: object,
    *,
    experiment_id: str,
    simulation_time_s: float,
    index: int,
) -> SafetyConflictEntity:
    from collections.abc import Mapping

    if not isinstance(source, Mapping):
        raise TypeError("conflict source must be a mapping")
    participant_a_id = str(source.get("participant_a_id", "unknown-a"))
    participant_b_id = str(source.get("participant_b_id", "unknown-b"))
    conflict_type = str(source.get("conflict_type", "unknown"))
    conflict_id = str(
        source.get("conflict_id")
        or (
            f"{experiment_id}:{_round(simulation_time_s)}:{index}:"
            f"{participant_a_id}:{participant_b_id}:{conflict_type}"
        )
    )
    return SafetyConflictEntity(
        id=conflict_id,
        participant_a_id=participant_a_id,
        participant_b_id=participant_b_id,
        conflict_type=conflict_type,
        x=_round(float(source.get("x_m", 0.0))),
        y=_round(float(source.get("y_m", 0.0))),
        minimum_distance_m=_round(float(source.get("minimum_distance_m", 0.0))),
        relative_speed_m_s=_round(float(source.get("relative_speed_m_s", 0.0))),
        ttc_s=_optional_float(source.get("ttc_s")),
        pet_s=_optional_float(source.get("pet_s")),
        severity=str(source.get("severity", "warning")),
    )


def _changes[Entity: (VehicleEntity, PedestrianEntity)](
    previous: dict[str, Entity],
    current: dict[str, Entity],
) -> tuple[list[Entity], list[Entity], list[str]]:
    spawned = [current[item] for item in sorted(current.keys() - previous.keys())]
    updated = [
        current[item]
        for item in sorted(current.keys() & previous.keys())
        if current[item] != previous[item]
    ]
    removed = sorted(previous.keys() - current.keys())
    return spawned, updated, removed


class RealtimeDeltaEncoder:
    """Retain only the current entity state and produce deterministic deltas."""

    def __init__(self, scene: SceneReference) -> None:
        self.scene = scene
        self.experiment_id: str | None = None
        self.scenario_id = scene.scene_id
        self.simulation_time_s = 0.0
        self.tick_hz = 1.0
        self.vehicles: dict[str, VehicleEntity] = {}
        self.bicycles: dict[str, VehicleEntity] = {}
        self.pedestrians: dict[str, PedestrianEntity] = {}
        self.traffic_lights: dict[str, TrafficLightEntity] = {}
        self.conflicts: list[SafetyConflictEntity] = []
        self.active_events: dict[str, RealtimeEvent] = {}
        self.metrics: dict[str, object] = {}
        self.intersection_metrics: list[dict[str, object]] = []

    def encode(self, frame: DigitalTwinSourceFrame, sequence: int) -> DigitalTwinDelta:
        if frame.experiment_id != self.experiment_id:
            self.vehicles = {}
            self.bicycles = {}
            self.pedestrians = {}
            self.traffic_lights = {}
            self.active_events = {}
        current_vehicles: dict[str, VehicleEntity] = {}
        current_bicycles: dict[str, VehicleEntity] = {}
        for source in frame.vehicles:
            entity = _vehicle(source)
            target = current_bicycles if source.vehicle_class == "bicycle" else current_vehicles
            target[entity.id] = entity
        current_pedestrians = {
            source.pedestrian_id: _pedestrian(source) for source in frame.pedestrians
        }
        current_tls = {
            source.intersection_id: TrafficLightEntity(
                id=source.intersection_id,
                phase_index=source.phase_index,
                state=source.phase_state,
                phase_duration_s=_round(source.phase_duration_s),
                remaining_s=_round(max(0.0, source.next_switch_s - frame.simulation_time_s)),
            )
            for source in frame.traffic_lights
        }
        current_conflicts = [
            _conflict(
                source,
                experiment_id=frame.experiment_id,
                simulation_time_s=frame.simulation_time_s,
                index=index,
            )
            for index, source in enumerate(frame.conflicts)
        ]
        vehicle_spawn, vehicle_update, vehicle_remove = _changes(self.vehicles, current_vehicles)
        bicycle_spawn, bicycle_update, bicycle_remove = _changes(self.bicycles, current_bicycles)
        pedestrian_spawn, pedestrian_update, pedestrian_remove = _changes(
            self.pedestrians, current_pedestrians
        )
        changed_tls = [
            current_tls[item]
            for item in sorted(current_tls)
            if current_tls[item] != self.traffic_lights.get(item)
        ]
        events: list[RealtimeEvent] = []
        for index, event in enumerate(frame.events):
            raw_event_time = event.get("simulation_time", frame.simulation_time_s)
            event_time = (
                float(raw_event_time)
                if isinstance(raw_event_time, int | float)
                else frame.simulation_time_s
            )
            realtime_event = RealtimeEvent(
                event_id=(
                    f"{frame.experiment_id}:{_round(frame.simulation_time_s)}:"
                    f"{index}:{event.get('event', 'UNKNOWN')}"
                ),
                simulation_time=event_time,
                event=str(event.get("event", "UNKNOWN")),
                detail=(str(event["detail"]) if event.get("detail") is not None else None),
                payload=dict(event),
            )
            events.append(realtime_event)
            disturbance_id = event.get("disturbance_id")
            event_key = (
                str(disturbance_id)
                if isinstance(disturbance_id, str) and disturbance_id
                else realtime_event.event_id
            )
            if realtime_event.event in {
                "ROADWORK_LANE_CLOSED",
                "INCIDENT_VEHICLE_STOPPED",
                "EVENT_DISPERSAL_STARTED",
            }:
                self.active_events[event_key] = realtime_event
            elif realtime_event.event in {
                "ROADWORK_LANE_REOPENED",
                "INCIDENT_CLEARED",
                "INCIDENT_STOP_CANCELLED",
                "INCIDENT_ALREADY_RELEASED",
                "EVENT_DISPERSAL_ENDED",
            }:
                self.active_events.pop(event_key, None)
        self.experiment_id = frame.experiment_id
        self.scenario_id = frame.scenario_id
        self.simulation_time_s = frame.simulation_time_s
        self.tick_hz = frame.tick_hz
        self.vehicles = current_vehicles
        self.bicycles = current_bicycles
        self.pedestrians = current_pedestrians
        self.traffic_lights = current_tls
        self.conflicts = current_conflicts
        self.metrics = {
            key: value
            for key, value in frame.metrics.items()
            if value is None or isinstance(value, bool | int | float | str)
        }
        self.intersection_metrics = [dict(item) for item in frame.intersection_metrics]
        return DigitalTwinDelta(
            sequence=sequence,
            experiment_id=frame.experiment_id,
            simulation_time_s=_round(frame.simulation_time_s),
            spawn=EntityStateSet(
                vehicles=vehicle_spawn,
                bicycles=bicycle_spawn,
                pedestrians=pedestrian_spawn,
            ),
            update=EntityStateSet(
                vehicles=vehicle_update,
                bicycles=bicycle_update,
                pedestrians=pedestrian_update,
            ),
            remove=EntityRemovalSet(
                vehicles=vehicle_remove,
                bicycles=bicycle_remove,
                pedestrians=pedestrian_remove,
            ),
            traffic_lights=changed_tls,
            conflicts=current_conflicts,
            events=events,
            metrics=self.metrics,
            intersection_metrics=self.intersection_metrics,
        )

    def initial(self, sequence: int, status: str) -> DigitalTwinInit:
        return DigitalTwinInit(
            sequence=sequence,
            status=status,
            experiment_id=self.experiment_id,
            scenario_id=self.scenario_id,
            simulation_time_s=_round(self.simulation_time_s),
            tick_hz=self.tick_hz,
            scene=self.scene,
            vehicle_types=sorted(
                {item.type for item in [*self.vehicles.values(), *self.bicycles.values()]}
            ),
            entities=EntityStateSet(
                vehicles=[self.vehicles[item] for item in sorted(self.vehicles)],
                bicycles=[self.bicycles[item] for item in sorted(self.bicycles)],
                pedestrians=[self.pedestrians[item] for item in sorted(self.pedestrians)],
            ),
            traffic_lights=[self.traffic_lights[item] for item in sorted(self.traffic_lights)],
            conflicts=self.conflicts,
            active_events=[self.active_events[item] for item in sorted(self.active_events)],
            metrics=self.metrics,
            intersection_metrics=self.intersection_metrics,
        )
