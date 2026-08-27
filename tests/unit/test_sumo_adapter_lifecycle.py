"""SUMO adapter lifecycle and process-failure isolation tests."""

from pathlib import Path

import pytest

from traffic_platform.common.errors import ErrorCode, PlatformError
from traffic_platform.experiment_service.engine import _traci_label
from traffic_platform.sumo_adapter import TraciSumoAdapter


class _ExitedProcess:
    def poll(self) -> int:
        return 23


class _ExitedApi:
    _process = _ExitedProcess()


class _IncidentLaneDomain:
    def getAllowed(self, lane_id: str) -> tuple[str, ...]:
        if lane_id == "future_1":
            return ("bus",)
        return ()

    def getDisallowed(self, lane_id: str) -> tuple[str, ...]:
        return ()

    def getLength(self, lane_id: str) -> float:
        return 100.0


class _IncidentEdgeDomain:
    def getLaneNumber(self, edge_id: str) -> int:
        return 2 if edge_id == "future" else 1


class _IncidentVehicleDomain:
    def __init__(self, *, reject_stops: bool = False) -> None:
        self.reject_stops = reject_stops
        self.stop_calls: list[tuple[str, str, float, int, float]] = []

    def getIDList(self) -> tuple[str, ...]:
        return ("vehicle-a",)

    def getVehicleClass(self, vehicle_id: str) -> str:
        return "passenger"

    def getSpeed(self, vehicle_id: str) -> float:
        return 10.0

    def getDecel(self, vehicle_id: str) -> float:
        return 5.0

    def getRoute(self, vehicle_id: str) -> tuple[str, ...]:
        return ("current", "future")

    def getRouteIndex(self, vehicle_id: str) -> int:
        return 0

    def getLaneIndex(self, vehicle_id: str) -> int:
        return 1

    def getLanePosition(self, vehicle_id: str) -> float:
        return 95.0

    def setStop(
        self,
        vehicle_id: str,
        edge_id: str,
        *,
        pos: float,
        laneIndex: int,
        duration: float,
    ) -> None:
        self.stop_calls.append((vehicle_id, edge_id, pos, laneIndex, duration))
        if self.reject_stops:
            raise RuntimeError("SUMO rejected stop placement")


class _IncidentApi:
    def __init__(self, *, reject_stops: bool = False) -> None:
        self.vehicle = _IncidentVehicleDomain(reject_stops=reject_stops)
        self.edge = _IncidentEdgeDomain()
        self.lane = _IncidentLaneDomain()


def test_adapter_rejects_invalid_startup_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TraciSumoAdapter(sumo_home=tmp_path, startup_timeout_s=0)


def test_adapter_detects_owned_sumo_process_exit(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    adapter._running = True
    adapter._api = _ExitedApi()
    with pytest.raises(PlatformError) as caught:
        adapter.get_network_state()
    assert caught.value.code == ErrorCode.SUMO_UNAVAILABLE
    assert caught.value.details["return_code"] == 23
    assert adapter.running is False


def test_parallel_adapter_instances_have_independent_labels(tmp_path: Path) -> None:
    first = TraciSumoAdapter(sumo_home=tmp_path, label="first")
    second = TraciSumoAdapter(sumo_home=tmp_path, label="second")
    assert first.label != second.label
    assert first.startup_timeout_s == second.startup_timeout_s


def test_paired_child_identifiers_remain_distinguishable() -> None:
    baseline = "pair-123456789abc-baseline"
    candidate = "pair-123456789abc-candidate"

    assert _traci_label(baseline) != _traci_label(candidate)


def test_incident_selects_a_future_lane_that_allows_the_vehicle_class(
    tmp_path: Path,
) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    api = _IncidentApi()
    adapter._running = True
    adapter._api = api

    assert adapter.inject_incident("vehicle-a", 30.0) is True
    assert api.vehicle.stop_calls == [("vehicle-a", "future", 11.0, 0, 90.0)]


def test_rejected_incident_stop_does_not_terminate_the_runner(tmp_path: Path) -> None:
    adapter = TraciSumoAdapter(sumo_home=tmp_path)
    api = _IncidentApi(reject_stops=True)
    adapter._running = True
    adapter._api = api

    assert adapter.inject_incident("vehicle-a", 30.0) is False
    assert api.vehicle.stop_calls
