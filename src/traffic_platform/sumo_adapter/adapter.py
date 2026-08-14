"""TraCI/libsumo lifecycle, state collection and safe actuation adapter."""

import os
import socket
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from traffic_platform.common.errors import ErrorCode, PlatformError


@dataclass(frozen=True, slots=True)
class VehicleSnapshot:
    """Raw SI-unit vehicle state collected from SUMO."""

    vehicle_id: str
    vehicle_type: str
    vehicle_class: str
    road_id: str
    lane_id: str
    x_m: float
    y_m: float
    lane_position_m: float
    speed_m_s: float
    acceleration_m_s2: float
    heading_deg: float
    route_id: str
    next_intersection_id: str | None
    distance_to_stop_line_m: float
    waiting_time_s: float
    co2_mg_s: float
    nox_mg_s: float
    fuel_mg_s: float
    signals: int = 0
    color_rgba: tuple[int, int, int, int] = (255, 255, 0, 255)


@dataclass(frozen=True, slots=True)
class BicycleSnapshot:
    """Observed bicycle or electric-bicycle state from the vehicle domain."""

    bicycle_id: str
    bicycle_type: str
    electric: bool
    road_id: str
    lane_id: str
    x_m: float
    y_m: float
    lane_position_m: float
    speed_m_s: float
    acceleration_m_s2: float
    waiting_time_s: float
    next_intersection_id: str | None
    in_bicycle_lane: bool


@dataclass(frozen=True, slots=True)
class PedestrianSnapshot:
    """Observed person state from a real SUMO walking stage."""

    pedestrian_id: str
    pedestrian_type: str
    road_id: str
    lane_id: str
    x_m: float
    y_m: float
    speed_m_s: float
    waiting_time_s: float
    walking_stage_index: int
    crossing_id: str | None
    waiting_area_id: str | None
    heading_deg: float = 0.0


@dataclass(frozen=True, slots=True)
class LaneSnapshot:
    """One lane aggregate from the latest simulation step."""

    lane_id: str
    vehicle_count: int
    queue_vehicle_count: int
    queue_length_m: float
    mean_speed_m_s: float
    occupancy_ratio: float
    max_speed_m_s: float
    bicycle_count: int = 0
    electric_bicycle_count: int = 0
    bicycle_queue_count: int = 0
    pedestrian_count: int = 0
    pedestrian_waiting_count: int = 0


@dataclass(frozen=True, slots=True)
class IntersectionSnapshot:
    """Signal and controlled-lane state for one SUMO traffic light."""

    intersection_id: str
    phase_index: int
    phase_state: str
    phase_duration_s: float
    next_switch_s: float
    controlled_lane_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NetworkSnapshot:
    """Network-wide state used by experiments and dashboards."""

    simulation_time_s: float
    vehicle_count: int
    mean_speed_m_s: float
    total_queue_vehicles: int
    completed_vehicles: int
    loaded_vehicles: int
    bicycle_count: int = 0
    pedestrian_count: int = 0


def find_free_port() -> int:
    """Reserve and return a currently free local TCP port for TraCI startup."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


class TraciSumoAdapter:
    """Own the SUMO process and expose stable domain-oriented operations."""

    def __init__(
        self,
        *,
        backend: Literal["traci", "libsumo"] = "traci",
        sumo_home: Path | None = None,
        binary: Path | None = None,
        label: str = "default",
        startup_timeout_s: float = 15.0,
    ) -> None:
        if startup_timeout_s <= 0:
            raise ValueError("startup_timeout_s must be positive")
        self.backend = backend
        configured_home = sumo_home or (
            Path(os.environ["SUMO_HOME"]) if "SUMO_HOME" in os.environ else None
        )
        if configured_home is None:
            raise PlatformError(
                ErrorCode.SUMO_UNAVAILABLE,
                "SUMO_HOME is required for the SUMO adapter",
            )
        self.sumo_home = configured_home
        tools = str(configured_home / "tools")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        executable = "sumo.exe" if os.name == "nt" else "sumo"
        self.binary = binary or configured_home / "bin" / executable
        self.label = label
        self.startup_timeout_s = startup_timeout_s
        self._api: Any | None = None
        self._root_module: Any | None = None
        self._running = False
        self._paused = False
        self._closed_lane_permissions: dict[str, tuple[str, ...]] = {}
        self._metric_callbacks: list[Callable[[NetworkSnapshot], None]] = []

    @property
    def running(self) -> bool:
        """Whether this adapter currently owns a running simulation."""

        return self._running

    def start_simulation(
        self,
        config_file: Path,
        *,
        gui: bool = False,
        seed: int | None = None,
        port: int | None = None,
        extra_args: list[str] | None = None,
    ) -> int | None:
        """Start SUMO with one unique TraCI connection or in-process libsumo."""

        if self._running:
            raise RuntimeError("simulation is already running")
        config = config_file.resolve()
        if not config.is_file():
            raise FileNotFoundError(config)
        gui_name = "sumo-gui.exe" if os.name == "nt" else "sumo-gui"
        binary = self.sumo_home / "bin" / (gui_name if gui else self.binary.name)
        if not binary.is_file():
            raise PlatformError(
                ErrorCode.SUMO_UNAVAILABLE,
                f"SUMO binary does not exist: {binary}",
            )
        command = [str(binary), "-c", str(config), "--no-step-log", "true"]
        if seed is not None:
            command.extend(["--seed", str(seed)])
        if extra_args:
            command.extend(extra_args)
        if self.backend == "libsumo":
            try:
                import libsumo
            except ImportError as exc:
                raise PlatformError(
                    ErrorCode.SUMO_UNAVAILABLE,
                    "libsumo is not available; select the traci backend",
                ) from exc
            try:
                libsumo.start(command)
                self._root_module = libsumo
                self._api = libsumo
                used_port = None
            except Exception as exc:
                self._api = None
                self._root_module = None
                raise PlatformError(
                    ErrorCode.SUMO_UNAVAILABLE,
                    f"libsumo failed to start: {exc}",
                ) from exc
        else:
            import traci

            used_port = port or find_free_port()
            try:
                traci.start(
                    command,
                    port=used_port,
                    numRetries=max(1, int(self.startup_timeout_s) + 1),
                    label=self.label,
                )
                self._root_module = traci
                self._api = traci.getConnection(self.label)
            except Exception as exc:
                self._api = None
                self._root_module = None
                raise PlatformError(
                    ErrorCode.SUMO_UNAVAILABLE,
                    (
                        f"SUMO TraCI startup failed within "
                        f"{self.startup_timeout_s:.1f}s on port {used_port}: {exc}"
                    ),
                ) from exc
        self._running = True
        self._paused = False
        return used_port

    def pause_simulation(self) -> None:
        """Pause adapter stepping while keeping SUMO and TraCI alive."""

        self._require_running()
        self._paused = True

    def resume_simulation(self) -> None:
        """Resume stepping after a local pause."""

        self._require_running()
        self._paused = False

    def step(self, target_time_s: float | None = None) -> NetworkSnapshot:
        """Advance one configured step or to a requested simulation timestamp."""

        api = self._require_running()
        if self._paused:
            return self.get_network_state()
        try:
            api.simulationStep(0 if target_time_s is None else target_time_s)
        except Exception as exc:
            self._raise_if_process_exited(exc)
            raise
        snapshot = self.get_network_state()
        for callback in self._metric_callbacks:
            callback(snapshot)
        return snapshot

    def stop_simulation(self) -> None:
        """Close the connection and terminate the owned SUMO process."""

        if not self._running:
            return
        try:
            if self.backend == "libsumo":
                assert self._api is not None
                self._api.close()
            else:
                assert self._api is not None
                self._api.close(True)
        finally:
            self._api = None
            self._root_module = None
            self._running = False
            self._paused = False

    def reset(self, config_file: Path, *, seed: int | None = None) -> None:
        """Stop and restart the same adapter with a new deterministic seed."""

        self.stop_simulation()
        self.start_simulation(config_file, seed=seed)

    def get_vehicle_states(self) -> list[VehicleSnapshot]:
        """Collect all active vehicle states in SI units."""

        api = self._require_running()
        snapshots: list[VehicleSnapshot] = []
        for vehicle_id in api.vehicle.getIDList():
            vehicle_type = str(api.vehicle.getTypeID(vehicle_id))
            x_m, y_m = api.vehicle.getPosition(vehicle_id)
            next_signals = api.vehicle.getNextTLS(vehicle_id)
            next_intersection_id = str(next_signals[0][0]) if next_signals else None
            distance_to_stop_line_m = max(0.0, float(next_signals[0][2])) if next_signals else 0.0
            color = api.vehicle.getColor(vehicle_id)
            snapshots.append(
                VehicleSnapshot(
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type,
                    vehicle_class=str(api.vehicletype.getVehicleClass(vehicle_type)),
                    road_id=api.vehicle.getRoadID(vehicle_id),
                    lane_id=api.vehicle.getLaneID(vehicle_id),
                    x_m=float(x_m),
                    y_m=float(y_m),
                    lane_position_m=float(api.vehicle.getLanePosition(vehicle_id)),
                    speed_m_s=float(api.vehicle.getSpeed(vehicle_id)),
                    acceleration_m_s2=float(api.vehicle.getAcceleration(vehicle_id)),
                    heading_deg=float(api.vehicle.getAngle(vehicle_id)),
                    route_id=api.vehicle.getRouteID(vehicle_id),
                    next_intersection_id=next_intersection_id,
                    distance_to_stop_line_m=distance_to_stop_line_m,
                    waiting_time_s=float(api.vehicle.getWaitingTime(vehicle_id)),
                    co2_mg_s=float(api.vehicle.getCO2Emission(vehicle_id)),
                    nox_mg_s=float(api.vehicle.getNOxEmission(vehicle_id)),
                    fuel_mg_s=float(api.vehicle.getFuelConsumption(vehicle_id)),
                    signals=int(api.vehicle.getSignals(vehicle_id)),
                    color_rgba=(
                        int(color[0]),
                        int(color[1]),
                        int(color[2]),
                        int(color[3]),
                    ),
                )
            )
        return snapshots

    def get_bicycle_states(self) -> list[BicycleSnapshot]:
        """Collect bicycles and electric bicycles without counting motor traffic."""

        api = self._require_running()
        bicycles: list[BicycleSnapshot] = []
        for vehicle in self.get_vehicle_states():
            if vehicle.vehicle_class != "bicycle":
                continue
            allowed = set(str(item) for item in api.lane.getAllowed(vehicle.lane_id))
            bicycles.append(
                BicycleSnapshot(
                    bicycle_id=vehicle.vehicle_id,
                    bicycle_type=vehicle.vehicle_type,
                    electric=("electric" in vehicle.vehicle_type.lower()),
                    road_id=vehicle.road_id,
                    lane_id=vehicle.lane_id,
                    x_m=vehicle.x_m,
                    y_m=vehicle.y_m,
                    lane_position_m=vehicle.lane_position_m,
                    speed_m_s=vehicle.speed_m_s,
                    acceleration_m_s2=vehicle.acceleration_m_s2,
                    waiting_time_s=vehicle.waiting_time_s,
                    next_intersection_id=vehicle.next_intersection_id,
                    in_bicycle_lane=(
                        "bicycle" in allowed and not ({"passenger", "bus", "truck"} & allowed)
                    ),
                )
            )
        return bicycles

    def get_pedestrian_states(self) -> list[PedestrianSnapshot]:
        """Collect active SUMO persons, including crossing and waiting-area state."""

        api = self._require_running()
        pedestrians: list[PedestrianSnapshot] = []
        for pedestrian_id in api.person.getIDList():
            x_m, y_m = api.person.getPosition(pedestrian_id)
            road_id = str(api.person.getRoadID(pedestrian_id))
            lane_id = str(api.person.getLaneID(pedestrian_id))
            internal_id = road_id or lane_id
            stage_index_getter = getattr(api.person, "getStageIndex", None)
            pedestrians.append(
                PedestrianSnapshot(
                    pedestrian_id=str(pedestrian_id),
                    pedestrian_type=str(api.person.getTypeID(pedestrian_id)),
                    road_id=road_id,
                    lane_id=lane_id,
                    x_m=float(x_m),
                    y_m=float(y_m),
                    speed_m_s=max(0.0, float(api.person.getSpeed(pedestrian_id))),
                    waiting_time_s=max(
                        0.0,
                        float(api.person.getWaitingTime(pedestrian_id)),
                    ),
                    walking_stage_index=max(
                        0,
                        int(stage_index_getter(pedestrian_id))
                        if stage_index_getter is not None
                        else 0,
                    ),
                    crossing_id=(
                        internal_id if internal_id.startswith(":") and "_c" in internal_id else None
                    ),
                    waiting_area_id=(
                        internal_id if internal_id.startswith(":") and "_w" in internal_id else None
                    ),
                    heading_deg=float(api.person.getAngle(pedestrian_id)),
                )
            )
        return pedestrians

    def get_vehicle_ids(
        self,
        preferred_edge_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        """Return active vehicle IDs, optionally restricted to visible/core edges."""

        api = self._require_running()
        identifiers = sorted(str(item) for item in api.vehicle.getIDList())
        if not preferred_edge_ids:
            return tuple(identifiers)
        selected: list[str] = []
        for vehicle_id in identifiers:
            road_id = str(api.vehicle.getRoadID(vehicle_id))
            # Do not infer visibility from the next route edge while the
            # vehicle is traversing an internal connection. Its lane position
            # belongs to the internal lane and cannot safely parameterize a
            # setStop call on the route edge.
            if road_id in preferred_edge_ids:
                selected.append(vehicle_id)
        return tuple(selected)

    def get_arrived_vehicle_ids(self) -> tuple[str, ...]:
        """Return vehicle-domain arrivals from the latest simulation step."""

        return tuple(str(item) for item in self._require_running().simulation.getArrivedIDList())

    def get_arrived_pedestrian_ids(self) -> tuple[str, ...]:
        """Return person-domain arrivals from the latest simulation step."""

        simulation = self._require_running().simulation
        getter = getattr(simulation, "getArrivedPersonIDList", None)
        return tuple(str(item) for item in getter()) if getter is not None else ()

    def get_representative_route(
        self,
        preferred_edge_ids: set[str] | None = None,
        *,
        vehicle_type: str | None = None,
    ) -> tuple[str, ...] | None:
        """Return a type-compatible route, preferring a controlled incoming edge."""

        api = self._require_running()
        vehicle_class = (
            str(api.vehicletype.getVehicleClass(vehicle_type)) if vehicle_type is not None else None
        )

        def edge_allows(edge_id: str) -> bool:
            if vehicle_class is None:
                return True
            return any(
                (
                    (not (allowed := set(api.lane.getAllowed(f"{edge_id}_{index}"))))
                    and vehicle_class not in set(api.lane.getDisallowed(f"{edge_id}_{index}"))
                )
                or vehicle_class in allowed
                for index in range(int(api.edge.getLaneNumber(edge_id)))
            )

        fallback: tuple[str, ...] | None = None
        for vehicle_id in self.get_vehicle_ids():
            route = tuple(str(edge_id) for edge_id in api.vehicle.getRoute(vehicle_id))
            if not route:
                continue
            starts = [
                index
                for index, edge_id in enumerate(route[:-1])
                if preferred_edge_ids and edge_id in preferred_edge_ids
            ]
            starts.append(0)
            for index in dict.fromkeys(starts):
                if not edge_allows(route[index]):
                    continue
                endpoint = next(
                    (
                        edge_index
                        for edge_index in range(len(route) - 1, index, -1)
                        if edge_allows(route[edge_index])
                    ),
                    None,
                )
                if endpoint is None:
                    continue
                candidate = route[index : endpoint + 1]
                if vehicle_type is None:
                    fallback = fallback or candidate
                    if preferred_edge_ids and candidate[0] in preferred_edge_ids:
                        return candidate
                    continue
                routed = api.simulation.findRoute(
                    candidate[0],
                    candidate[-1],
                    vType=vehicle_type,
                )
                compatible = tuple(str(edge_id) for edge_id in routed.edges)
                if not compatible:
                    continue
                fallback = fallback or compatible
                if preferred_edge_ids and candidate[0] in preferred_edge_ids:
                    return compatible
        return fallback

    def add_vehicle(
        self,
        vehicle_id: str,
        vehicle_type: str,
        route_edges: Sequence[str],
    ) -> None:
        """Add a runtime vehicle on a validated route already seen in SUMO."""

        if not route_edges:
            raise ValueError("route_edges must not be empty")
        api = self._require_running()
        routed = api.simulation.findRoute(
            str(route_edges[0]),
            str(route_edges[-1]),
            vType=vehicle_type,
        )
        validated_edges = tuple(str(edge_id) for edge_id in routed.edges)
        if not validated_edges:
            raise ValueError(f"SUMO found no {vehicle_type} route between disturbance endpoints")
        route_id = f"route-{vehicle_id}"
        api.route.add(route_id, list(validated_edges))
        api.vehicle.add(
            vehicle_id,
            route_id,
            typeID=vehicle_type,
            depart="now",
            departSpeed="max",
        )

    def get_lane_states(self, lane_ids: list[str] | None = None) -> list[LaneSnapshot]:
        """Collect selected or all non-internal lane aggregates."""

        api = self._require_running()
        identifiers = lane_ids or [
            lane_id for lane_id in api.lane.getIDList() if not lane_id.startswith(":")
        ]
        persons_by_lane: dict[str, list[str]] = defaultdict(list)
        for person_id in api.person.getIDList():
            persons_by_lane[str(api.person.getLaneID(person_id))].append(str(person_id))
        snapshots: list[LaneSnapshot] = []
        for lane_id in identifiers:
            vehicle_ids = tuple(api.lane.getLastStepVehicleIDs(lane_id))
            bicycle_ids: list[str] = []
            motor_ids: list[str] = []
            electric_bicycle_count = 0
            for vehicle_id in vehicle_ids:
                type_id = str(api.vehicle.getTypeID(vehicle_id))
                if str(api.vehicletype.getVehicleClass(type_id)) == "bicycle":
                    bicycle_ids.append(str(vehicle_id))
                    electric_bicycle_count += int("electric" in type_id.lower())
                else:
                    motor_ids.append(str(vehicle_id))
            motor_speeds = [float(api.vehicle.getSpeed(item)) for item in motor_ids]
            bicycle_speeds = [float(api.vehicle.getSpeed(item)) for item in bicycle_ids]
            person_ids = tuple(persons_by_lane.get(lane_id, ()))
            person_waiting = sum(
                float(api.person.getWaitingTime(item)) > 0.0 for item in person_ids
            )
            vehicle_count = len(motor_ids)
            queue_count = sum(speed < 0.1 for speed in motor_speeds)
            mean_length = (
                sum(float(api.vehicle.getLength(item)) for item in motor_ids) / vehicle_count
                if vehicle_count
                else 5.0
            )
            snapshots.append(
                LaneSnapshot(
                    lane_id=lane_id,
                    vehicle_count=vehicle_count,
                    queue_vehicle_count=queue_count,
                    queue_length_m=queue_count * (mean_length + 2.5),
                    mean_speed_m_s=(
                        max(0.0, sum(motor_speeds) / vehicle_count) if vehicle_count else 0.0
                    ),
                    occupancy_ratio=min(
                        1.0,
                        max(0.0, float(api.lane.getLastStepOccupancy(lane_id)) / 100),
                    ),
                    max_speed_m_s=float(api.lane.getMaxSpeed(lane_id)),
                    bicycle_count=len(bicycle_ids),
                    electric_bicycle_count=electric_bicycle_count,
                    bicycle_queue_count=sum(speed < 0.1 for speed in bicycle_speeds),
                    pedestrian_count=len(person_ids),
                    pedestrian_waiting_count=person_waiting,
                )
            )
        return snapshots

    def get_intersection_state(self, intersection_id: str) -> IntersectionSnapshot:
        """Collect the active phase and controlled lane IDs of one signal."""

        api = self._require_running()
        return IntersectionSnapshot(
            intersection_id=intersection_id,
            phase_index=int(api.trafficlight.getPhase(intersection_id)),
            phase_state=api.trafficlight.getRedYellowGreenState(intersection_id),
            phase_duration_s=float(api.trafficlight.getPhaseDuration(intersection_id)),
            next_switch_s=float(api.trafficlight.getNextSwitch(intersection_id)),
            controlled_lane_ids=tuple(
                dict.fromkeys(api.trafficlight.getControlledLanes(intersection_id))
            ),
        )

    def get_network_state(self) -> NetworkSnapshot:
        """Aggregate live vehicle speed, queue and lifecycle counts."""

        api = self._require_running()
        motor_speeds: list[float] = []
        bicycle_count = 0
        for identifier in api.vehicle.getIDList():
            type_id = str(api.vehicle.getTypeID(identifier))
            if str(api.vehicletype.getVehicleClass(type_id)) == "bicycle":
                bicycle_count += 1
            else:
                motor_speeds.append(float(api.vehicle.getSpeed(identifier)))
        return NetworkSnapshot(
            simulation_time_s=float(api.simulation.getTime()),
            vehicle_count=len(motor_speeds),
            mean_speed_m_s=(sum(motor_speeds) / len(motor_speeds) if motor_speeds else 0.0),
            total_queue_vehicles=sum(1 for speed in motor_speeds if speed < 0.1),
            completed_vehicles=int(api.simulation.getArrivedNumber()),
            loaded_vehicles=int(api.simulation.getLoadedNumber()),
            bicycle_count=bicycle_count,
            pedestrian_count=int(api.person.getIDCount()),
        )

    def get_traffic_light_program(self, intersection_id: str) -> Any:
        """Return TraCI program logic for mapping and diagnostics only."""

        return self._require_running().trafficlight.getAllProgramLogics(intersection_id)

    def get_traffic_light_ids(self) -> tuple[str, ...]:
        """Return all signal controller IDs from the loaded SUMO network."""

        return tuple(self._require_running().trafficlight.getIDList())

    def get_controlled_links(
        self,
        intersection_id: str,
    ) -> tuple[tuple[tuple[str, str, str], ...], ...]:
        """Return lane-to-lane signal link groups for topology construction."""

        links = self._require_running().trafficlight.getControlledLinks(intersection_id)
        return tuple(
            tuple((str(link[0]), str(link[1]), str(link[2])) for link in group) for group in links
        )

    def set_traffic_light_phase(self, intersection_id: str, phase_index: int) -> None:
        """Apply a safety-approved signal phase index."""

        self._require_running().trafficlight.setPhase(intersection_id, phase_index)

    def set_phase_duration(self, intersection_id: str, duration_s: float) -> None:
        """Apply a positive safety-approved remaining phase duration."""

        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._require_running().trafficlight.setPhaseDuration(
            intersection_id,
            duration_s,
        )

    def apply_speed_guidance(self, vehicle_id: str, speed_m_s: float) -> float:
        """Clamp speed advice to the current lane limit and apply it."""

        api = self._require_running()
        if speed_m_s < 0:
            raise ValueError("speed_m_s must be non-negative")
        lane_id = api.vehicle.getLaneID(vehicle_id)
        applied = min(float(speed_m_s), float(api.lane.getMaxSpeed(lane_id)))
        api.vehicle.setSpeed(vehicle_id, applied)
        return applied

    def close_lane(self, lane_id: str) -> None:
        """Close one lane while retaining its previous permission list."""

        api = self._require_running()
        if lane_id not in self._closed_lane_permissions:
            self._closed_lane_permissions[lane_id] = tuple(api.lane.getAllowed(lane_id))
        api.lane.setDisallowed(lane_id, ["all"])

    def reopen_lane(self, lane_id: str) -> None:
        """Restore the exact permission list saved during lane closure."""

        api = self._require_running()
        previous = self._closed_lane_permissions.pop(lane_id, ())
        api.lane.setAllowed(lane_id, list(previous))

    def inject_incident(self, vehicle_id: str, duration_s: float) -> bool:
        """Schedule a stop far enough ahead for the vehicle to brake safely."""

        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        api = self._require_running()
        if vehicle_id not in api.vehicle.getIDList():
            return False
        # SUMO exposes bicycles through the vehicle domain as well. Incidents
        # in this platform represent a stopped motor vehicle, so active-mode
        # participants must not be selected merely because they departed first.
        if str(api.vehicle.getVehicleClass(vehicle_id)).lower() in {
            "bicycle",
            "moped",
            "pedestrian",
        }:
            return False
        speed = max(0.0, float(api.vehicle.getSpeed(vehicle_id)))
        deceleration = max(0.1, float(api.vehicle.getDecel(vehicle_id)))
        required_distance = speed * speed / (2.0 * deceleration) + 5.0
        route = list(api.vehicle.getRoute(vehicle_id))
        route_index = max(0, int(api.vehicle.getRouteIndex(vehicle_id)))
        current_lane_index = int(api.vehicle.getLaneIndex(vehicle_id))
        current_position = float(api.vehicle.getLanePosition(vehicle_id))
        distance_before_edge = 0.0
        for index, edge_id in enumerate(route[route_index:], start=route_index):
            lane_count = int(api.edge.getLaneNumber(edge_id))
            if lane_count <= 0:
                continue
            lane_index = min(current_lane_index, lane_count - 1)
            lane_id = f"{edge_id}_{lane_index}"
            edge_start = current_position if index == route_index else 0.0
            lane_length = float(api.lane.getLength(lane_id))
            available = max(0.0, lane_length - edge_start - 1.0)
            if distance_before_edge + available >= required_distance:
                position = edge_start + (required_distance - distance_before_edge)
                api.vehicle.setStop(
                    vehicle_id,
                    edge_id,
                    pos=min(lane_length - 1.0, position),
                    laneIndex=lane_index,
                    # Explicit clearing owns the event end; the margin is a
                    # fail-safe if a run terminates before the clear action.
                    duration=duration_s + 60.0,
                )
                return True
            distance_before_edge += available
        return False

    def incident_is_stopped(self, vehicle_id: str) -> bool:
        """Report SUMO's actual stop state for truthful event publication."""

        api = self._require_running()
        return vehicle_id in api.vehicle.getIDList() and bool(api.vehicle.isStopped(vehicle_id))

    def clear_incident(self, vehicle_id: str) -> bool:
        """Resume an incident vehicle only while SUMO still marks it stopped."""

        api = self._require_running()
        if vehicle_id not in api.vehicle.getIDList():
            return False
        if bool(api.vehicle.isStopped(vehicle_id)):
            api.vehicle.resume(vehicle_id)
            return True
        if api.vehicle.getStops(vehicle_id, limit=1):
            api.vehicle.replaceStop(vehicle_id, 0, "")
            return True
        return False

    def subscribe_metrics(self, callback: Callable[[NetworkSnapshot], None]) -> None:
        """Register a callback invoked after each real simulation step."""

        self._metric_callbacks.append(callback)

    def _require_running(self) -> Any:
        if not self._running or self._api is None:
            raise RuntimeError("simulation is not running")
        self._raise_if_process_exited()
        return self._api

    def _raise_if_process_exited(self, cause: Exception | None = None) -> None:
        """Translate an owned SUMO process exit into a stable platform error."""

        process = getattr(self._api, "_process", None)
        return_code = process.poll() if process is not None else None
        if return_code is None:
            return
        self._running = False
        error = PlatformError(
            ErrorCode.SUMO_UNAVAILABLE,
            f"owned SUMO process exited unexpectedly with code {return_code}",
            details={"return_code": return_code, "label": self.label},
        )
        if cause is not None:
            raise error from cause
        raise error

    def __enter__(self) -> "TraciSumoAdapter":
        """Return this adapter for context-managed ownership."""

        return self

    def __exit__(self, *_: object) -> None:
        """Always release SUMO and its TraCI port."""

        self.stop_simulation()
