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
