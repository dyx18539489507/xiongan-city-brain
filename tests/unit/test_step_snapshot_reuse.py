"""Per-step SUMO state is collected once and reused by all consumers."""

from pathlib import Path
from types import SimpleNamespace

from traffic_platform.contracts.factory import MessageFactory
from traffic_platform.contracts.models import SourceType
from traffic_platform.edge_service.aggregation import EdgeStateAggregator
from traffic_platform.sumo_adapter import (
    IntersectionSnapshot,
    LaneSnapshot,
    NetworkSnapshot,
    TraciSumoAdapter,
    VehicleSnapshot,
)


def _vehicle(vehicle_id: str) -> VehicleSnapshot:
    return VehicleSnapshot(
        vehicle_id=vehicle_id,
        vehicle_type="passenger",
        vehicle_class="passenger",
        road_id="edge-1",
        lane_id="lane-1",
        x_m=0.0,
        y_m=0.0,
        lane_position_m=0.0,
        speed_m_s=10.0,
        acceleration_m_s2=0.0,
        heading_deg=0.0,
        route_id="route-1",
        next_intersection_id="tls-1",
        distance_to_stop_line_m=10.0,
        waiting_time_s=0.0,
        co2_mg_s=0.0,
        nox_mg_s=0.0,
        fuel_mg_s=0.0,
    )


class _SimulationDomain:
    def __init__(self) -> None:
        self.time_s = 0.0

    def getTime(self) -> float:
        return self.time_s

    def getArrivedNumber(self) -> int:
        return 0

    def getLoadedNumber(self) -> int:
        return 1


class _StepApi:
    def __init__(self) -> None:
        self.simulation = _SimulationDomain()
        self.person = SimpleNamespace(getIDCount=lambda: 0)

    def simulationStep(self, _target_time_s: float) -> None:
        self.simulation.time_s += 1.0


def test_step_vehicle_cache_is_reused_then_invalidated(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    adapter._api = _StepApi()
    adapter._running = True
    collection_count = 0

    def collect() -> list[VehicleSnapshot]:
        nonlocal collection_count
        collection_count += 1
        return [_vehicle(f"vehicle-{collection_count}")]

    monkeypatch.setattr(adapter, "get_vehicle_states", collect)  # type: ignore[attr-defined]

    first_network = adapter.step()
    first_states = adapter.get_step_vehicle_states()
    assert collection_count == 1
    assert first_network.simulation_time_s == 1.0
    assert first_states[0].vehicle_id == "vehicle-1"

    second_network = adapter.step()
    second_states = adapter.get_step_vehicle_states()
    assert collection_count == 2
    assert second_network.simulation_time_s == 2.0
    assert second_states[0].vehicle_id == "vehicle-2"


class _LaneDomain:
    def getLastStepOccupancy(self, _lane_id: str) -> float:
        return 0.0

    def getMaxSpeed(self, _lane_id: str) -> float:
        return 13.9


class _SubscriptionConstants:
    LAST_STEP_OCCUPANCY = 1
    VAR_MAXSPEED = 2
    TL_CURRENT_PHASE = 3
    TL_RED_YELLOW_GREEN_STATE = 4
    TL_PHASE_DURATION = 5
    TL_NEXT_SWITCH = 6
    TL_CONTROLLED_LANES = 7


class _SubscribedLaneDomain:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, tuple[int, ...]]] = []

    def subscribe(self, lane_id: str, variables: tuple[int, ...]) -> None:
        self.subscriptions.append((lane_id, variables))

    def getAllSubscriptionResults(self) -> dict[str, dict[int, object]]:
        return {
            "lane-1": {
                _SubscriptionConstants.LAST_STEP_OCCUPANCY: 25.0,
                _SubscriptionConstants.VAR_MAXSPEED: 13.9,
            }
        }

    def getLastStepOccupancy(self, _lane_id: str) -> float:
        raise AssertionError("lane occupancy getter must not be called")

    def getMaxSpeed(self, _lane_id: str) -> float:
        raise AssertionError("lane max-speed getter must not be called")


def test_lane_aggregation_accepts_explicit_empty_state_without_refetching(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    adapter._api = SimpleNamespace(lane=_LaneDomain())
    adapter._running = True

    def fail() -> None:
        raise AssertionError("explicit per-step state must not be fetched again")

    monkeypatch.setattr(adapter, "get_vehicle_states", fail)  # type: ignore[attr-defined]
    monkeypatch.setattr(adapter, "get_pedestrian_states", fail)  # type: ignore[attr-defined]

    lanes = adapter.get_lane_states(
        ["lane-1"],
        vehicle_states=[],
        pedestrian_states=[],
    )

    assert len(lanes) == 1
    assert lanes[0].vehicle_count == 0
    assert lanes[0].pedestrian_count == 0


def test_lane_metrics_use_one_persistent_subscription(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    lane = _SubscribedLaneDomain()
    adapter._api = SimpleNamespace(lane=lane)
    adapter._root_module = SimpleNamespace(constants=_SubscriptionConstants)
    adapter._running = True

    first = adapter.get_lane_states(
        ["lane-1"],
        vehicle_states=[],
        pedestrian_states=[],
    )
    second = adapter.get_lane_states(
        ["lane-1"],
        vehicle_states=[],
        pedestrian_states=[],
    )

    assert len(lane.subscriptions) == 1
    assert first == second
    assert first[0].occupancy_ratio == 0.25
    assert first[0].max_speed_m_s == 13.9


class _SubscribedSignalDomain:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, tuple[int, ...]]] = []

    def subscribe(self, signal_id: str, variables: tuple[int, ...]) -> None:
        self.subscriptions.append((signal_id, variables))

    def getAllSubscriptionResults(self) -> dict[str, dict[int, object]]:
        return {
            "tls-1": {
                _SubscriptionConstants.TL_CURRENT_PHASE: 2,
                _SubscriptionConstants.TL_RED_YELLOW_GREEN_STATE: "rrGG",
                _SubscriptionConstants.TL_PHASE_DURATION: 30.0,
                _SubscriptionConstants.TL_NEXT_SWITCH: 42.0,
                _SubscriptionConstants.TL_CONTROLLED_LANES: ["lane-1", "lane-1"],
            }
        }


def test_signal_states_use_one_persistent_batch_subscription(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    trafficlight = _SubscribedSignalDomain()
    adapter._api = SimpleNamespace(trafficlight=trafficlight)
    adapter._root_module = SimpleNamespace(constants=_SubscriptionConstants)
    adapter._running = True

    first = adapter.get_intersection_states(["tls-1"])
    second = adapter.get_intersection_states(["tls-1"])

    assert len(trafficlight.subscriptions) == 1
    assert first == second
    assert first[0].phase_index == 2
    assert first[0].phase_state == "rrGG"
    assert first[0].controlled_lane_ids == ("lane-1",)


class _RegionalAdapter:
    def __init__(self) -> None:
        self.vehicles = [_vehicle("vehicle-1")]
        self.pedestrians: list[object] = []
        self.lane_arguments: tuple[object, object] | None = None

    def get_network_state(self) -> NetworkSnapshot:
        raise AssertionError("the supplied network snapshot must be reused")

    def get_intersection_state(self, intersection_id: str) -> IntersectionSnapshot:
        return IntersectionSnapshot(
            intersection_id=intersection_id,
            phase_index=0,
            phase_state="G",
            phase_duration_s=30.0,
            next_switch_s=31.0,
            controlled_lane_ids=("lane-1",),
        )

    def get_intersection_states(
        self,
        intersection_ids: list[str],
    ) -> list[IntersectionSnapshot]:
        return [self.get_intersection_state(intersection_id) for intersection_id in intersection_ids]

    def get_step_vehicle_states(self) -> list[VehicleSnapshot]:
        return self.vehicles

    def get_step_pedestrian_states(self) -> list[object]:
        return self.pedestrians

    def get_lane_states(
        self,
        _lane_ids: list[str],
        *,
        vehicle_states: object,
        pedestrian_states: object,
    ) -> list[LaneSnapshot]:
        self.lane_arguments = (vehicle_states, pedestrian_states)
        return [
            LaneSnapshot(
                lane_id="lane-1",
                vehicle_count=1,
                queue_vehicle_count=0,
                queue_length_m=0.0,
                mean_speed_m_s=10.0,
                occupancy_ratio=0.1,
                max_speed_m_s=13.9,
            )
        ]


def test_regional_aggregation_reuses_step_snapshots() -> None:
    adapter = _RegionalAdapter()
    factory = MessageFactory(
        source_id="test-edge",
        source_type=SourceType.EDGE,
        scenario_id="xiongan_rongdong_20",
        experiment_id="test-snapshot-reuse",
    )
    aggregator = EdgeStateAggregator(
        adapter,  # type: ignore[arg-type]
        factory,
        ["tls-1"],
    )
    network = NetworkSnapshot(
        simulation_time_s=1.0,
        vehicle_count=1,
        mean_speed_m_s=10.0,
        total_queue_vehicles=0,
        completed_vehicles=0,
        loaded_vehicles=1,
    )

    regional = aggregator.collect_regional(control_mode="normal", network=network)

    assert regional.simulation_time == 1.0
    assert adapter.lane_arguments == (adapter.vehicles, adapter.pedestrians)
    assert aggregator.last_vehicle_states is adapter.vehicles
    assert aggregator.last_pedestrian_states is adapter.pedestrians
