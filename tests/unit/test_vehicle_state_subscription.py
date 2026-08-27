"""Vehicle state subscription collection tests."""

from pathlib import Path
from types import SimpleNamespace

from traffic_platform.sumo_adapter import TraciSumoAdapter


class _Constants:
    VAR_TYPE = 1
    VAR_POSITION = 2
    VAR_NEXT_TLS = 3
    VAR_COLOR = 4
    VAR_ROAD_ID = 5
    VAR_LANE_ID = 6
    VAR_LANEPOSITION = 7
    VAR_SPEED = 8
    VAR_ACCELERATION = 9
    VAR_ANGLE = 10
    VAR_ROUTE_ID = 11
    VAR_WAITING_TIME = 12
    VAR_CO2EMISSION = 13
    VAR_NOXEMISSION = 14
    VAR_FUELCONSUMPTION = 15
    VAR_SIGNALS = 16
    VAR_LENGTH = 17


class _VehicleDomain:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, tuple[int, ...]]] = []
        self.values = {
            _Constants.VAR_TYPE: "connected_vehicle",
            _Constants.VAR_POSITION: (12.5, 24.0),
            _Constants.VAR_NEXT_TLS: (("tls-1", 0, 31.5, "G"),),
            _Constants.VAR_COLOR: (1, 2, 3, 255),
            _Constants.VAR_ROAD_ID: "edge-1",
            _Constants.VAR_LANE_ID: "edge-1_0",
            _Constants.VAR_LANEPOSITION: 18.0,
            _Constants.VAR_SPEED: 9.5,
            _Constants.VAR_ACCELERATION: 0.25,
            _Constants.VAR_ANGLE: 90.0,
            _Constants.VAR_ROUTE_ID: "route-1",
            _Constants.VAR_WAITING_TIME: 2.0,
            _Constants.VAR_CO2EMISSION: 3.0,
            _Constants.VAR_NOXEMISSION: 4.0,
            _Constants.VAR_FUELCONSUMPTION: 5.0,
            _Constants.VAR_SIGNALS: 6,
            _Constants.VAR_LENGTH: 4.5,
        }

    def getIDList(self) -> tuple[str, ...]:
        return ("vehicle-1",)

    def subscribe(self, vehicle_id: str, variables: tuple[int, ...]) -> None:
        self.subscriptions.append((vehicle_id, variables))

    def getAllSubscriptionResults(self) -> dict[str, dict[int, object]]:
        return {"vehicle-1": self.values}


class _VehicleTypeDomain:
    def __init__(self) -> None:
        self.calls = 0

    def getVehicleClass(self, vehicle_type: str) -> str:
        self.calls += 1
        assert vehicle_type == "connected_vehicle"
        return "passenger"


class _SimulationDomain:
    def getTime(self) -> float:
        return 601.0

    def getArrivedNumber(self) -> int:
        return 2

    def getLoadedNumber(self) -> int:
        return 10


class _PersonDomain:
    def getIDCount(self) -> int:
        return 3


class _SubscribedPersonDomain:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, tuple[int, ...]]] = []
        self.values = {
            _Constants.VAR_TYPE: "pedestrian",
            _Constants.VAR_POSITION: (3.0, 4.0),
            _Constants.VAR_ROAD_ID: ":crossing_c0",
            _Constants.VAR_LANE_ID: ":crossing_c0_0",
            _Constants.VAR_SPEED: 1.2,
            _Constants.VAR_WAITING_TIME: 0.5,
            _Constants.VAR_ANGLE: 180.0,
        }

    def getIDList(self) -> tuple[str, ...]:
        return ("person-1",)

    def subscribe(self, person_id: str, variables: tuple[int, ...]) -> None:
        self.subscriptions.append((person_id, variables))

    def getAllSubscriptionResults(self) -> dict[str, dict[int, object]]:
        return {"person-1": self.values}

    def getStageIndex(self, person_id: str) -> int:
        assert person_id == "person-1"
        return 2


def test_vehicle_states_use_one_persistent_subscription(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    vehicle = _VehicleDomain()
    vehicle_type = _VehicleTypeDomain()
    adapter._api = SimpleNamespace(
        vehicle=vehicle,
        vehicletype=vehicle_type,
        simulation=_SimulationDomain(),
        person=_PersonDomain(),
    )
    adapter._root_module = SimpleNamespace(constants=_Constants)
    adapter._running = True

    first = adapter.get_vehicle_states()
    second = adapter.get_vehicle_states()

    assert len(vehicle.subscriptions) == 1
    assert vehicle_type.calls == 1
    assert first == second
    assert first[0].vehicle_id == "vehicle-1"
    assert first[0].next_intersection_id == "tls-1"
    assert first[0].distance_to_stop_line_m == 31.5
    assert first[0].color_rgba == (1, 2, 3, 255)

    network = adapter.get_network_state()
    assert network.simulation_time_s == 601.0
    assert network.vehicle_count == 1
    assert network.mean_speed_m_s == 9.5


def test_pedestrian_states_use_one_persistent_subscription(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    person = _SubscribedPersonDomain()
    adapter._api = SimpleNamespace(person=person)
    adapter._root_module = SimpleNamespace(constants=_Constants)
    adapter._running = True

    first = adapter.get_pedestrian_states()
    second = adapter.get_pedestrian_states()

    assert len(person.subscriptions) == 1
    assert first == second
    assert first[0].pedestrian_id == "person-1"
    assert first[0].walking_stage_index == 2
    assert first[0].crossing_id == ":crossing_c0"
