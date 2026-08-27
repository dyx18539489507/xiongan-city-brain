"""Deterministic runtime execution of scenario disturbance schedules."""

import random
from collections.abc import Sequence
from typing import Protocol

from traffic_platform.scenario_engine.models import Disturbance, ScenarioConfig


class DisturbanceAdapter(Protocol):
    """Narrow SUMO operations needed by scheduled scenario disturbances."""

    def close_lane(self, lane_id: str) -> None: ...

    def reopen_lane(self, lane_id: str) -> None: ...

    def inject_incident(self, vehicle_id: str, duration_s: float) -> bool: ...

    def clear_incident(self, vehicle_id: str) -> bool: ...

    def get_vehicle_ids(
        self,
        preferred_edge_ids: set[str] | None = None,
    ) -> tuple[str, ...]: ...

    def incident_is_stopped(self, vehicle_id: str) -> bool: ...

    def get_representative_route(
        self,
        preferred_edge_ids: set[str] | None = None,
        *,
        vehicle_type: str | None = None,
    ) -> tuple[str, ...] | None: ...

    def add_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: str,
        route_edges: Sequence[str],
    ) -> None: ...


RuntimeEvent = dict[str, str | float]


class DisturbanceRuntime:
    """Apply one validated scenario schedule exactly once at simulation time."""

    def __init__(
        self,
        scenario: ScenarioConfig,
        *,
        seed: int,
        fallback_roadwork_lane: str,
        preferred_route_edges: set[str] | None = None,
    ) -> None:
        self.scenario = scenario
        self.fallback_roadwork_lane = fallback_roadwork_lane
        self.preferred_route_edges = preferred_route_edges or set()
        self._random = random.Random(seed)
        self._started: set[str] = set()
        self._ended: set[str] = set()
        self._roadwork_lanes: dict[str, str] = {}
        self._incident_vehicles: dict[str, str] = {}
        self._incident_stopped_announced: set[str] = set()
        self._next_departure_s: dict[str, float] = {}
        self._injected_counts: dict[str, int] = {}
        self._dynamic: dict[str, Disturbance] = {}

    def schedule(self, disturbance: Disturbance) -> None:
        """Add one validated live disturbance without mutating scenario sources."""

        if disturbance.event_id in self._dynamic or any(
            item.event_id == disturbance.event_id for item in self.scenario.disturbances
        ):
            raise ValueError(f"duplicate disturbance event_id: {disturbance.event_id}")
        self._dynamic[disturbance.event_id] = disturbance

    def tick(
        self,
        simulation_time_s: float,
        adapter: DisturbanceAdapter,
    ) -> list[RuntimeEvent]:
        """Apply all actions due at this timestamp and return auditable events."""

        events: list[RuntimeEvent] = []
        for disturbance in sorted(
            [*self.scenario.disturbances, *self._dynamic.values()],
            key=lambda item: (item.simulation_time_s, item.event_id),
        ):
            start = disturbance.simulation_time_s
            end = start + disturbance.duration_s
            if simulation_time_s >= start and disturbance.event_id not in self._started:
                events.extend(self._start(disturbance, simulation_time_s, adapter))
            if (
                disturbance.type == "incident"
                and disturbance.event_id in self._started
                and disturbance.event_id not in self._ended
                and disturbance.event_id not in self._incident_stopped_announced
            ):
                vehicle_id = self._incident_vehicles[disturbance.event_id]
                if adapter.incident_is_stopped(vehicle_id):
                    self._incident_stopped_announced.add(disturbance.event_id)
                    events.append(
                        self._event(
                            disturbance,
                            simulation_time_s,
                            "INCIDENT_VEHICLE_STOPPED",
                            vehicle_id,
                        )
                    )
            if (
                disturbance.type == "event_dispersal"
                and disturbance.event_id in self._started
                and start <= simulation_time_s < end
            ):
                events.extend(
                    self._inject_dispersal(
                        disturbance,
                        simulation_time_s,
                        adapter,
                    )
                )
            if (
                simulation_time_s >= end
                and disturbance.event_id in self._started
                and disturbance.event_id not in self._ended
            ):
                events.extend(self._end(disturbance, simulation_time_s, adapter))
        return events

    def active_event_ids(self, simulation_time_s: float) -> list[str]:
        """Return event IDs whose scheduled window is currently active."""

        return [
            disturbance.event_id
            for disturbance in [*self.scenario.disturbances, *self._dynamic.values()]
            if (
                disturbance.event_id in self._started
                and disturbance.event_id not in self._ended
                and disturbance.simulation_time_s
                <= simulation_time_s
                < disturbance.simulation_time_s + disturbance.duration_s
            )
        ]

    def _start(
        self,
        disturbance: Disturbance,
        simulation_time_s: float,
        adapter: DisturbanceAdapter,
    ) -> list[RuntimeEvent]:
        if disturbance.type == "roadwork":
            configured_lane = disturbance.parameters.get("lane_id")
            lane_id = (
                configured_lane
                if isinstance(configured_lane, str) and configured_lane
                else self.fallback_roadwork_lane
            )
            adapter.close_lane(lane_id)
            self._roadwork_lanes[disturbance.event_id] = lane_id
            self._started.add(disturbance.event_id)
            return [
                self._event(
                    disturbance,
                    simulation_time_s,
                    "ROADWORK_LANE_CLOSED",
                    lane_id,
                )
            ]

        if disturbance.type == "incident":
            configured_vehicle_id = disturbance.parameters.get("vehicle_id")
            vehicle_ids = (
                (configured_vehicle_id,)
                if isinstance(configured_vehicle_id, str) and configured_vehicle_id
                else adapter.get_vehicle_ids(self.preferred_route_edges or None)
            )
            if not vehicle_ids:
                return []
            vehicle_id = next(
                (
                    candidate
                    for candidate in vehicle_ids
                    if adapter.inject_incident(
                        candidate,
                        disturbance.duration_s,
                    )
                ),
                None,
            )
            if vehicle_id is None:
                return []
            self._incident_vehicles[disturbance.event_id] = vehicle_id
            self._started.add(disturbance.event_id)
            return [
                self._event(
                    disturbance,
                    simulation_time_s,
                    "INCIDENT_STOP_SCHEDULED",
                    vehicle_id,
                )
            ]

        if disturbance.type == "emergency_vehicle":
            emergency_vehicle_id = self._inject_vehicle(
                disturbance,
                adapter,
                vehicle_type="emergency",
            )
            if emergency_vehicle_id is None:
                return []
            self._started.add(disturbance.event_id)
            return [
                self._event(
                    disturbance,
                    simulation_time_s,
                    "EMERGENCY_VEHICLE_INJECTED",
                    emergency_vehicle_id,
                )
            ]

        self._started.add(disturbance.event_id)
        self._next_departure_s[disturbance.event_id] = disturbance.simulation_time_s
        return [
            self._event(
                disturbance,
                simulation_time_s,
                "EVENT_DISPERSAL_STARTED",
                disturbance.target,
            )
        ]

    def _end(
        self,
        disturbance: Disturbance,
        simulation_time_s: float,
        adapter: DisturbanceAdapter,
    ) -> list[RuntimeEvent]:
        self._ended.add(disturbance.event_id)
        if disturbance.type == "roadwork":
            lane_id = self._roadwork_lanes[disturbance.event_id]
            adapter.reopen_lane(lane_id)
            return [
                self._event(
                    disturbance,
                    simulation_time_s,
                    "ROADWORK_LANE_REOPENED",
                    lane_id,
                )
            ]
        if disturbance.type == "incident":
            vehicle_id = self._incident_vehicles[disturbance.event_id]
            cleared = adapter.clear_incident(vehicle_id)
            actually_stopped = disturbance.event_id in self._incident_stopped_announced
            return [
                self._event(
                    disturbance,
                    simulation_time_s,
                    (
                        "INCIDENT_CLEARED"
                        if cleared and actually_stopped
                        else "INCIDENT_STOP_CANCELLED"
                        if cleared
                        else "INCIDENT_ALREADY_RELEASED"
                    ),
                    vehicle_id,
                )
            ]
        return [
            self._event(
                disturbance,
                simulation_time_s,
                (
                    "EVENT_DISPERSAL_ENDED"
                    if disturbance.type == "event_dispersal"
                    else "EMERGENCY_PRIORITY_WINDOW_ENDED"
                ),
                disturbance.target,
            )
        ]

    def _inject_dispersal(
        self,
        disturbance: Disturbance,
        simulation_time_s: float,
        adapter: DisturbanceAdapter,
    ) -> list[RuntimeEvent]:
        multiplier_value = disturbance.parameters.get("flow_multiplier", 1.0)
        multiplier = float(multiplier_value) if isinstance(multiplier_value, int | float) else 1.0
        baseline_flow = sum(item.flow_veh_h for item in self.scenario.demand)
        additional_flow = baseline_flow * max(0.0, multiplier - 1.0)
        if additional_flow <= 0:
            return []
        interval_s = 3600.0 / additional_flow
        next_departure = self._next_departure_s[disturbance.event_id]
        events: list[RuntimeEvent] = []
        # The cap prevents a long simulation jump from flooding TraCI at once.
        injection_budget = 50
        while simulation_time_s + 1e-9 >= next_departure and injection_budget > 0:
            vehicle_id = self._inject_vehicle(disturbance, adapter)
            if vehicle_id is None:
                break
            events.append(
                self._event(
                    disturbance,
                    simulation_time_s,
                    "EVENT_DISPERSAL_VEHICLE_INJECTED",
                    vehicle_id,
                )
            )
            next_departure += interval_s
            injection_budget -= 1
        self._next_departure_s[disturbance.event_id] = next_departure
        return events

    def _inject_vehicle(
        self,
        disturbance: Disturbance,
        adapter: DisturbanceAdapter,
        *,
        vehicle_type: str | None = None,
    ) -> str | None:
        selected_type = vehicle_type or self._weighted_vehicle_type()
        route = adapter.get_representative_route(
            self.preferred_route_edges,
            vehicle_type=selected_type,
        )
        if route is None:
            return None
        count = self._injected_counts.get(disturbance.event_id, 0) + 1
        self._injected_counts[disturbance.event_id] = count
        vehicle_id = f"runtime-{disturbance.event_id}-{count:05d}"
        adapter.add_vehicle(vehicle_id, selected_type, route)
        return vehicle_id

    def _weighted_vehicle_type(self) -> str:
        types = list(self.scenario.vehicle_type_ratios)
        weights = [self.scenario.vehicle_type_ratios[item] for item in types]
        return self._random.choices(types, weights=weights, k=1)[0]

    @staticmethod
    def _event(
        disturbance: Disturbance,
        simulation_time_s: float,
        event: str,
        detail: str,
    ) -> RuntimeEvent:
        return {
            "simulation_time": simulation_time_s,
            "event": event,
            "detail": detail,
            "disturbance_id": disturbance.event_id,
        }
