"""Observed trajectory-based surrogate-safety monitoring for mixed traffic."""

from __future__ import annotations

import math
from dataclasses import dataclass

from traffic_platform.sumo_adapter import PedestrianSnapshot, VehicleSnapshot


@dataclass(frozen=True, slots=True)
class ObservedConflict:
    """One TTC/PET observation derived from simulated participant trajectories."""

    participant_a_id: str
    participant_b_id: str
    conflict_type: str
    minimum_distance_m: float
    relative_speed_m_s: float
    ttc_s: float | None
    pet_s: float | None
    x_m: float
    y_m: float
    severity: str


@dataclass(frozen=True, slots=True)
class _Participant:
    identifier: str
    category: str
    x_m: float
    y_m: float
    vx_m_s: float
    vy_m_s: float


class SurrogateSafetyMonitor:
    """Calculate TTC and cell-occupancy PET without synthetic observations."""

    def __init__(
        self,
        *,
        ttc_threshold_s: float = 5.0,
        pet_threshold_s: float = 5.0,
        conflict_distance_m: float = 2.5,
        search_radius_m: float = 8.0,
    ) -> None:
        if (
            min(
                ttc_threshold_s,
                pet_threshold_s,
                conflict_distance_m,
                search_radius_m,
            )
            <= 0
        ):
            raise ValueError("surrogate-safety thresholds must be positive")
        self.ttc_threshold_s = ttc_threshold_s
        self.pet_threshold_s = pet_threshold_s
        self.conflict_distance_m = conflict_distance_m
        self.search_radius_m = search_radius_m
        self._previous: dict[str, tuple[float, float, float]] = {}
        self._cell_occupants: dict[tuple[int, int], dict[str, str]] = {}
        self._last_cell_exit: dict[tuple[int, int], tuple[float, str, str]] = {}
        self._last_pair_event: dict[tuple[str, str, str], float] = {}

    def reset(self) -> None:
        """Discard trajectory history between reproducible experiments."""

        self._previous.clear()
        self._cell_occupants.clear()
        self._last_cell_exit.clear()
        self._last_pair_event.clear()

    def observe(
        self,
        simulation_time_s: float,
        vehicles: list[VehicleSnapshot],
        pedestrians: list[PedestrianSnapshot],
    ) -> list[ObservedConflict]:
        """Return only conflicts supported by this simulation step's trajectories."""

        participants = self._participants(simulation_time_s, vehicles, pedestrians)
        ttc_conflicts = self._ttc_conflicts(simulation_time_s, participants)
        pet_conflicts = self._pet_conflicts(simulation_time_s, participants)
        self._previous = {
            item.identifier: (simulation_time_s, item.x_m, item.y_m) for item in participants
        }
        return ttc_conflicts + pet_conflicts

    def _participants(
        self,
        simulation_time_s: float,
        vehicles: list[VehicleSnapshot],
        pedestrians: list[PedestrianSnapshot],
    ) -> list[_Participant]:
        participants: list[_Participant] = []
        for vehicle in vehicles:
            category = "bicycle" if vehicle.vehicle_class == "bicycle" else "motor"
            vx_m_s, vy_m_s = self._velocity(
                vehicle.vehicle_id,
                simulation_time_s,
                vehicle.x_m,
                vehicle.y_m,
                fallback_speed_m_s=vehicle.speed_m_s,
                heading_deg=vehicle.heading_deg,
            )
            participants.append(
                _Participant(
                    vehicle.vehicle_id,
                    category,
                    vehicle.x_m,
                    vehicle.y_m,
                    vx_m_s,
                    vy_m_s,
                )
            )
        for pedestrian in pedestrians:
            vx_m_s, vy_m_s = self._velocity(
                pedestrian.pedestrian_id,
                simulation_time_s,
                pedestrian.x_m,
                pedestrian.y_m,
                fallback_speed_m_s=pedestrian.speed_m_s,
                heading_deg=0.0,
            )
            participants.append(
                _Participant(
                    pedestrian.pedestrian_id,
                    "pedestrian",
                    pedestrian.x_m,
                    pedestrian.y_m,
                    vx_m_s,
                    vy_m_s,
                )
            )
        return participants

    def _velocity(
        self,
        identifier: str,
        simulation_time_s: float,
        x_m: float,
        y_m: float,
        *,
        fallback_speed_m_s: float,
        heading_deg: float,
    ) -> tuple[float, float]:
        previous = self._previous.get(identifier)
        if previous is not None and simulation_time_s > previous[0]:
            elapsed = simulation_time_s - previous[0]
            return (x_m - previous[1]) / elapsed, (y_m - previous[2]) / elapsed
        angle = math.radians(90.0 - heading_deg)
        return fallback_speed_m_s * math.cos(angle), fallback_speed_m_s * math.sin(angle)

    def _ttc_conflicts(
        self,
        simulation_time_s: float,
        participants: list[_Participant],
    ) -> list[ObservedConflict]:
        bins: dict[tuple[int, int], list[_Participant]] = {}
        for participant in participants:
            bins.setdefault(self._cell(participant.x_m, participant.y_m), []).append(participant)
        observed: list[ObservedConflict] = []
        for left in participants:
            cell = self._cell(left.x_m, left.y_m)
            candidates = [
                item
                for x_offset in (-1, 0, 1)
                for y_offset in (-1, 0, 1)
                for item in bins.get((cell[0] + x_offset, cell[1] + y_offset), [])
            ]
            for right in candidates:
                if left.identifier >= right.identifier:
                    continue
                conflict_type = self._conflict_type(left.category, right.category)
                if conflict_type is None:
                    continue
                dx = right.x_m - left.x_m
                dy = right.y_m - left.y_m
                distance = math.hypot(dx, dy)
                if distance > self.search_radius_m:
                    continue
                dvx = right.vx_m_s - left.vx_m_s
                dvy = right.vy_m_s - left.vy_m_s
                relative_speed = math.hypot(dvx, dvy)
                velocity_squared = dvx * dvx + dvy * dvy
                if velocity_squared <= 1e-9:
                    continue
                ttc_s = -(dx * dvx + dy * dvy) / velocity_squared
                if ttc_s <= 0 or ttc_s > self.ttc_threshold_s:
                    continue
                closest_dx = dx + dvx * ttc_s
                closest_dy = dy + dvy * ttc_s
                closest_distance = math.hypot(closest_dx, closest_dy)
                if closest_distance > self.conflict_distance_m:
                    continue
                pair_key = (left.identifier, right.identifier, conflict_type)
                if simulation_time_s - self._last_pair_event.get(pair_key, -math.inf) < 1.0:
                    continue
                self._last_pair_event[pair_key] = simulation_time_s
                observed.append(
                    ObservedConflict(
                        participant_a_id=left.identifier,
                        participant_b_id=right.identifier,
                        conflict_type=conflict_type,
                        minimum_distance_m=closest_distance,
                        relative_speed_m_s=relative_speed,
                        ttc_s=ttc_s,
                        pet_s=None,
                        x_m=(left.x_m + right.x_m) / 2.0,
                        y_m=(left.y_m + right.y_m) / 2.0,
                        severity=self._severity(ttc_s),
                    )
                )
        return observed

    def _pet_conflicts(
        self,
        simulation_time_s: float,
        participants: list[_Participant],
    ) -> list[ObservedConflict]:
        current: dict[tuple[int, int], dict[str, str]] = {}
        by_id = {item.identifier: item for item in participants}
        for participant in participants:
            current.setdefault(
                self._pet_cell(participant.x_m, participant.y_m),
                {},
            )[participant.identifier] = participant.category
        for cell, prior in self._cell_occupants.items():
            for identifier, category in prior.items():
                if identifier not in current.get(cell, {}):
                    self._last_cell_exit[cell] = (simulation_time_s, identifier, category)
        observed: list[ObservedConflict] = []
        for cell, occupants in current.items():
            last_exit = self._last_cell_exit.get(cell)
            if last_exit is None:
                continue
            exit_time, previous_id, previous_category = last_exit
            pet_s = simulation_time_s - exit_time
            if pet_s < 0 or pet_s > self.pet_threshold_s:
                continue
            for identifier, category in occupants.items():
                if identifier == previous_id:
                    continue
                conflict_type = self._conflict_type(previous_category, category)
                if conflict_type is None:
                    continue
                participant = by_id[identifier]
                pair = tuple(sorted((previous_id, identifier)))
                pair_key = (pair[0], pair[1], f"pet:{conflict_type}")
                if simulation_time_s - self._last_pair_event.get(pair_key, -math.inf) < 1.0:
                    continue
                self._last_pair_event[pair_key] = simulation_time_s
                observed.append(
                    ObservedConflict(
                        participant_a_id=previous_id,
                        participant_b_id=identifier,
                        conflict_type=conflict_type,
                        minimum_distance_m=0.0,
                        relative_speed_m_s=math.hypot(
                            participant.vx_m_s,
                            participant.vy_m_s,
                        ),
                        ttc_s=None,
                        pet_s=pet_s,
                        x_m=participant.x_m,
                        y_m=participant.y_m,
                        severity=self._severity(pet_s),
                    )
                )
        self._cell_occupants = current
        return observed

    def _cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        return int(x_m // self.search_radius_m), int(y_m // self.search_radius_m)

    def _pet_cell(self, x_m: float, y_m: float) -> tuple[int, int]:
        return int(x_m // self.conflict_distance_m), int(y_m // self.conflict_distance_m)

    @staticmethod
    def _conflict_type(left: str, right: str) -> str | None:
        categories = frozenset((left, right))
        if categories == {"motor"}:
            return "motor_motor"
        if categories == {"motor", "bicycle"}:
            return "motor_bicycle"
        if categories == {"motor", "pedestrian"}:
            return "motor_pedestrian"
        if categories == {"bicycle", "pedestrian"}:
            return "bicycle_pedestrian"
        return None

    @staticmethod
    def _severity(time_gap_s: float) -> str:
        if time_gap_s < 1.0:
            return "critical"
        if time_gap_s < 2.0:
            return "serious"
        return "potential"
