"""Convert raw TraCI snapshots into versioned intersection/regional contracts."""

from collections import defaultdict

from traffic_platform.algorithm_sdk.types import (
    NetworkTopology,
    PhaseDefinition,
    PhaseMovement,
)
from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import IntersectionState, LaneState, RegionalState
from traffic_platform.sumo_adapter import (
    IntersectionSnapshot,
    LaneSnapshot,
    NetworkSnapshot,
    PedestrianSnapshot,
    TraciSumoAdapter,
    VehicleSnapshot,
)


class EdgeStateAggregator:
    """Aggregate one-second local state without exposing TraCI to algorithms."""

    def __init__(
        self,
        adapter: TraciSumoAdapter,
        factory: MessageFactory,
        intersection_ids: list[str],
        *,
        edge_id: str = "edge-rongdong",
    ) -> None:
        self.adapter = adapter
        self.factory = factory
        self.intersection_ids = intersection_ids
        self.edge_id = edge_id
        self._previous_counts: dict[str, int] = {}
        self._previous_vehicle_ids: dict[str, set[str]] = {}
        self._phase_started_at: dict[str, tuple[int, float]] = {}
        self._lane_movements: dict[str, dict[str, str]] = {}
        self._downstream_lanes: dict[str, dict[str, str]] = {}
        self._cycle_network: NetworkSnapshot | None = None
        self._cycle_signals: dict[str, IntersectionSnapshot] = {}
        self._cycle_lanes: dict[str, LaneSnapshot] = {}
        self._cycle_vehicles: list[VehicleSnapshot] | None = None
        self.last_vehicle_states: list[VehicleSnapshot] = []
        self.last_pedestrian_states: list[PedestrianSnapshot] = []
        self.last_intersection_snapshots: dict[str, IntersectionSnapshot] = {}

    def build_topology(self) -> NetworkTopology:
        """Parse signal programs and controlled links into the algorithm SDK."""

        phases_by_intersection: dict[str, list[PhaseDefinition]] = {}
        downstream: dict[str, list[str]] = {identifier: [] for identifier in self.intersection_ids}
        speed_limits: dict[str, float] = {}
        conflicting_phases: dict[str, set[tuple[str, str]]] = {}
        pedestrian_phases: dict[str, set[str]] = {}
        clearance_phases: dict[str, set[str]] = {}
        phase_order: dict[str, list[str]] = {}
        phase_durations: dict[str, dict[str, float]] = {}
        clearance_paths: dict[str, dict[str, dict[str, list[str]]]] = {}
        topology_lane_ids: set[str] = set()
        for intersection_id in self.intersection_ids:
            links = self.adapter.get_controlled_links(intersection_id)
            programs = self.adapter.get_traffic_light_program(intersection_id)
            if not programs:
                raise RuntimeError(f"no signal program for {intersection_id}")
            program = programs[0]
            is_static_program = int(getattr(program, "type", 0)) == 0
            ordered_phase_ids = [str(index) for index, _phase in enumerate(program.phases)]
            green_phase_ids = {
                str(index)
                for index, phase in enumerate(program.phases)
                if any(signal in {"G", "g"} for signal in phase.state)
            }
            phase_order[intersection_id] = ordered_phase_ids
            phase_durations[intersection_id] = {
                str(index): float(phase.duration)
                for index, phase in enumerate(program.phases)
            }
            definitions: list[PhaseDefinition] = []
            movement_by_lane: dict[str, str] = {}
            downstream_by_lane: dict[str, str] = {}
            for phase_index, phase in enumerate(program.phases):
                movements: list[PhaseMovement] = []
                for link_index, state in enumerate(phase.state):
                    if state not in {"G", "g"} or link_index >= len(links):
                        continue
                    for incoming, outgoing, _via in links[link_index]:
                        movement = PhaseMovement(
                            incoming_lane_id=incoming,
                            outgoing_lane_id=outgoing,
                        )
                        if movement not in movements:
                            movements.append(movement)
                        movement_by_lane.setdefault(incoming, str(phase_index))
                        downstream_by_lane.setdefault(incoming, outgoing)
                if movements:
                    phase_duration_s = float(phase.duration)
                    min_green_s = (
                        min(10.0, phase_duration_s)
                        if is_static_program
                        else max(5.0, float(getattr(phase, "minDur", 10.0)))
                    )
                    definitions.append(
                        PhaseDefinition(
                            phase_id=str(phase_index),
                            movements=movements,
                            min_green_s=min_green_s,
                            max_green_s=max(
                                float(phase.duration),
                                float(getattr(phase, "maxDur", phase.duration)),
                            ),
                            yellow_s=3.0,
                            all_red_s=1.0,
                        )
                    )
            if not definitions:
                raise RuntimeError(f"no green phases parsed for {intersection_id}")
            phases_by_intersection[intersection_id] = definitions
            phase_ids = {definition.phase_id for definition in definitions}
            conflicting_phases[intersection_id] = {
                (left, right) for left in phase_ids for right in phase_ids if left != right
            }
            pedestrian_phases[intersection_id] = {
                str(phase_index)
                for phase_index, phase in enumerate(program.phases)
                if any(
                    signal in {"G", "g"}
                    and link_index < len(links)
                    and any(
                        "_c" in incoming
                        or "walkingarea" in incoming.lower()
                        or "_c" in outgoing
                        or "walkingarea" in outgoing.lower()
                        for incoming, outgoing, _via in links[link_index]
                    )
                    for link_index, signal in enumerate(phase.state)
                )
            }
            clearance_phases[intersection_id] = {
                str(index)
                for index, phase in enumerate(program.phases)
                if not any(signal in {"G", "g"} for signal in phase.state)
            }
            paths: dict[str, dict[str, list[str]]] = {}
            for source in green_phase_ids:
                source_index = int(source)
                paths[source] = {}
                for target in green_phase_ids - {source}:
                    path: list[str] = []
                    for offset in range(1, len(program.phases) + 1):
                        candidate = str((source_index + offset) % len(program.phases))
                        if candidate == target:
                            break
                        path.append(candidate)
                    paths[source][target] = path
            clearance_paths[intersection_id] = paths
            self._lane_movements[intersection_id] = movement_by_lane
            self._downstream_lanes[intersection_id] = downstream_by_lane
            topology_lane_ids.update(movement_by_lane)
        # Lane state collection also classifies live pedestrians and bicycles.
        # Query all controlled lanes once instead of repeating that work for
        # every junction during startup.
        for snapshot in self.adapter.get_lane_states(sorted(topology_lane_ids)):
            speed_limits[snapshot.lane_id] = snapshot.max_speed_m_s
        return NetworkTopology(
            intersection_ids=self.intersection_ids,
            phases=phases_by_intersection,
            downstream_intersections=downstream,
            speed_limits_m_s=speed_limits,
            conflicting_phase_pairs=conflicting_phases,
            pedestrian_phase_ids=pedestrian_phases,
            clearance_phase_ids=clearance_phases,
            phase_order=phase_order,
            phase_durations_s=phase_durations,
            clearance_paths=clearance_paths,
        )

    def collect_intersection(
        self,
        intersection_id: str,
        *,
        control_mode: str,
    ) -> IntersectionState:
        """Collect lane, queue, signal and local-mode state for one junction."""

        network = self._cycle_network or self.adapter.get_network_state()
        simulation_time = network.simulation_time_s
        signal = self._cycle_signals.get(
            intersection_id,
        ) or self.adapter.get_intersection_state(intersection_id)
        phase_record = self._phase_started_at.get(intersection_id)
        if phase_record is None or phase_record[0] != signal.phase_index:
            self._phase_started_at[intersection_id] = (
                signal.phase_index,
                simulation_time,
            )
            phase_elapsed = 0.0
        else:
            phase_elapsed = simulation_time - phase_record[1]
        lane_snapshots = (
            {
                lane_id: self._cycle_lanes[lane_id]
                for lane_id in signal.controlled_lane_ids
                if lane_id in self._cycle_lanes
            }
            if self._cycle_lanes
            else {
                item.lane_id: item
                for item in self.adapter.get_lane_states(list(signal.controlled_lane_ids))
            }
        )
        downstream_ids = {
            lane_id: downstream_id
            for lane_id, downstream_id in self._downstream_lanes.get(
                intersection_id,
                {},
            ).items()
            if downstream_id
        }
        downstream_snapshots = (
            {
                lane_id: self._cycle_lanes[lane_id]
                for lane_id in set(downstream_ids.values())
                if lane_id in self._cycle_lanes
            }
            if self._cycle_lanes
            else {
                item.lane_id: item
                for item in self.adapter.get_lane_states(sorted(set(downstream_ids.values())))
            }
        )
        vehicles_by_lane: dict[str, list[str]] = defaultdict(list)
        connected_by_lane: dict[str, int] = defaultdict(int)
        emergency_lanes: set[str] = set()
        vehicles = self._cycle_vehicles
        if vehicles is None:
            vehicles = self.adapter.get_vehicle_states()
        for vehicle in vehicles:
            vehicles_by_lane[vehicle.lane_id].append(vehicle.vehicle_id)
            if "connected_vehicle" in vehicle.vehicle_type:
                connected_by_lane[vehicle.lane_id] += 1
            if "emergency" in vehicle.vehicle_type:
                emergency_lanes.add(vehicle.lane_id)
        lane_messages: list[LaneState] = []
        for lane_id, snapshot in lane_snapshots.items():
            previous = self._previous_counts.get(lane_id, snapshot.vehicle_count)
            current_vehicle_ids = set(vehicles_by_lane.get(lane_id, []))
            previous_vehicle_ids = self._previous_vehicle_ids.get(lane_id)
            if previous_vehicle_ids is None:
                arrival_count = max(0, snapshot.vehicle_count - previous)
                discharge_count = max(0, previous - snapshot.vehicle_count)
            else:
                arrival_count = len(current_vehicle_ids - previous_vehicle_ids)
                discharge_count = len(previous_vehicle_ids - current_vehicle_ids)
            arrival_rate = arrival_count * 3600.0
            discharge_rate = discharge_count * 3600.0
            self._previous_counts[lane_id] = snapshot.vehicle_count
            self._previous_vehicle_ids[lane_id] = current_vehicle_ids
            downstream_id = downstream_ids.get(lane_id)
            downstream_snapshot = (
                downstream_snapshots.get(downstream_id) if downstream_id is not None else None
            )
            downstream_occupancy = (
                downstream_snapshot.occupancy_ratio if downstream_snapshot is not None else 0.0
            )
            downstream_capacity = (
                max(
                    0.0,
                    20.0 * (1.0 - downstream_occupancy) - downstream_snapshot.vehicle_count,
                )
                if downstream_snapshot is not None
                else 10.0
            )
            lane_messages.append(
                self.factory.build(
                    LaneState,
                    simulation_time=simulation_time,
                    ttl_s=3.0,
                    lane_id=lane_id,
                    intersection_id=intersection_id,
                    direction="inbound",
                    movement=self._lane_movements.get(intersection_id, {}).get(
                        lane_id,
                        str(signal.phase_index),
                    ),
                    vehicle_count=snapshot.vehicle_count,
                    connected_vehicle_count=connected_by_lane[lane_id],
                    queue_vehicle_count=snapshot.queue_vehicle_count,
                    queue_length_m=snapshot.queue_length_m,
                    mean_speed=snapshot.mean_speed_m_s,
                    occupancy=snapshot.occupancy_ratio,
                    arrival_rate=arrival_rate,
                    discharge_rate=discharge_rate,
                    downstream_lane_id=downstream_id,
                    downstream_occupancy=downstream_occupancy,
                    downstream_available_capacity=downstream_capacity,
                    bicycle_count=snapshot.bicycle_count,
                    electric_bicycle_count=snapshot.electric_bicycle_count,
                    bicycle_queue_count=snapshot.bicycle_queue_count,
                    bicycle_queue_length_m=snapshot.bicycle_queue_count * 2.5,
                    pedestrian_count=snapshot.pedestrian_count,
                    pedestrian_waiting_count=snapshot.pedestrian_waiting_count,
                )
            )
        total_queue = sum(item.queue_vehicle_count for item in lane_messages)
        mean_speed = (
            sum(item.mean_speed for item in lane_messages) / len(lane_messages)
            if lane_messages
            else 0.0
        )
        mean_occupancy = (
            sum(item.occupancy for item in lane_messages) / len(lane_messages)
            if lane_messages
            else 0.0
        )
        spillback = max(
            (item.downstream_occupancy for item in lane_messages),
            default=0.0,
        )
        bicycle_queue_count = sum(item.bicycle_queue_count for item in lane_messages)
        pedestrian_waiting_count = sum(item.pedestrian_waiting_count for item in lane_messages)
        crossing_pedestrian_count = sum(
            item.pedestrian_count
            for item in lane_messages
            if item.lane_id.startswith(":") and "_c" in item.lane_id
        )
        emergency_priority_phase_id = next(
            (
                self._lane_movements[intersection_id][lane_id]
                for lane_id in sorted(emergency_lanes)
                if lane_id in self._lane_movements.get(intersection_id, {})
            ),
            None,
        )
        return self.factory.build(
            IntersectionState,
            simulation_time=simulation_time,
            ttl_s=3.0,
            intersection_id=intersection_id,
            edge_id=self.edge_id,
            current_phase_id=str(signal.phase_index),
            phase_state=signal.phase_state,
            phase_elapsed=phase_elapsed,
            phase_remaining=max(0.0, signal.next_switch_s - simulation_time),
            cycle_elapsed=simulation_time,
            lane_states=lane_messages,
            total_queue=total_queue,
            mean_speed=mean_speed,
            throughput=0.0,
            congestion_level=min(1.0, max(mean_occupancy, total_queue / 40.0)),
            spillback_risk=spillback,
            incident_state=(
                "emergency_priority" if emergency_priority_phase_id is not None else "none"
            ),
            emergency_priority_phase_id=emergency_priority_phase_id,
            communication_state="online",
            local_control_mode=control_mode,
            bicycle_queue_count=bicycle_queue_count,
            pedestrian_waiting_count=pedestrian_waiting_count,
            crossing_pedestrian_count=crossing_pedestrian_count,
        )

    def collect_regional(
        self,
        *,
        control_mode: str,
        active_disturbances: list[str] | None = None,
        network: NetworkSnapshot | None = None,
    ) -> RegionalState:
        """Collect a regional aggregation for the cloud service."""

        network = network if network is not None else self.adapter.get_network_state()
        signals = {
            signal.intersection_id: signal
            for signal in self.adapter.get_intersection_states(self.intersection_ids)
        }
        self.last_intersection_snapshots = signals
        lane_ids = {
            lane_id for signal in signals.values() for lane_id in signal.controlled_lane_ids
        }
        lane_ids.update(
            downstream_lane
            for mapping in self._downstream_lanes.values()
            for downstream_lane in mapping.values()
        )
        self._cycle_network = network
        self._cycle_signals = signals
        self._cycle_vehicles = self.adapter.get_step_vehicle_states()
        pedestrians = self.adapter.get_step_pedestrian_states()
        self._cycle_lanes = {
            lane.lane_id: lane
            for lane in self.adapter.get_lane_states(
                sorted(lane_ids),
                vehicle_states=self._cycle_vehicles,
                pedestrian_states=pedestrians,
            )
        }
        self.last_vehicle_states = self._cycle_vehicles
        self.last_pedestrian_states = pedestrians
        try:
            states = [
                self.collect_intersection(
                    intersection_id,
                    control_mode=control_mode,
                )
                for intersection_id in self.intersection_ids
            ]
        finally:
            self._cycle_network = None
            self._cycle_signals = {}
            self._cycle_lanes = {}
            self._cycle_vehicles = None
        return self.factory.build(
            RegionalState,
            simulation_time=network.simulation_time_s,
            ttl_s=3.0,
            intersection_states=states,
            network_mean_speed=network.mean_speed_m_s,
            total_queue=sum(state.total_queue for state in states),
            congested_intersections=[
                state.intersection_id for state in states if state.congestion_level >= 0.7
            ],
            spillback_edges=[state.edge_id for state in states if state.spillback_risk >= 0.9],
            risk_levels={
                state.intersection_id: max(
                    state.congestion_level,
                    state.spillback_risk,
                )
                for state in states
            },
            active_disturbances=active_disturbances or [],
        )
