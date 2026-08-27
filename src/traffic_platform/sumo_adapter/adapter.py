"""TraCI/libsumo lifecycle, state collection and safe actuation adapter."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import xml.etree.ElementTree as ET
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from traffic_platform.common.errors import ErrorCode, PlatformError

_OUTPUT_FILE_OPTIONS = frozenset(
    {
        "--summary-output",
        "--tripinfo-output",
        "--statistic-output",
        "--fcd-output",
        "--queue-output",
        "--emission-output",
        "--full-output",
        "--vehroute-output",
    }
)
_INPUT_FILE_OPTIONS = frozenset({"--load-state"})
_TRACI_START_LOCK = threading.Lock()


def _is_ascii_path(path: Path | str) -> bool:
    """Return whether a path can be passed safely to the Windows SUMO build."""

    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _stage_sumo_config(config: Path, destination: Path) -> Path:
    """Copy a SUMO config and its declared inputs into an ASCII runtime folder."""

    source_root = config.parent.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(config)
    external_index = 0
    for element in tree.getroot().findall("./input/*"):
        raw_value = element.get("value")
        if not raw_value:
            continue
        staged_values: list[str] = []
        for raw_item in raw_value.split(","):
            item = raw_item.strip()
            if not item:
                continue
            candidate = Path(item)
            source = candidate if candidate.is_absolute() else source_root / candidate
            source = source.resolve()
            if not source.is_file():
                staged_values.append(item)
                continue
            try:
                relative = source.relative_to(source_root)
            except ValueError:
                external_index += 1
                relative = Path(f"external-{external_index:03d}-{source.name}")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            staged_values.append(relative.as_posix())
        element.set("value", ",".join(staged_values))
    config_output_root = destination / "config-outputs"
    for element in tree.getroot().findall("./output/*"):
        raw_value = element.get("value")
        if not raw_value:
            continue
        output_name = Path(raw_value).name or f"{element.tag}.xml"
        config_output_root.mkdir(parents=True, exist_ok=True)
        element.set("value", str((config_output_root / output_name).resolve()))
    staged_config = destination / config.name
    tree.write(staged_config, encoding="utf-8", xml_declaration=True)
    return staged_config


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
        self._subscribed_vehicle_ids: set[str] = set()
        self._subscribed_person_ids: set[str] = set()
        self._subscribed_lane_ids: set[str] = set()
        self._subscribed_traffic_light_ids: set[str] = set()
        self._vehicle_class_by_type: dict[str, str] = {}
        self._vehicle_length_by_id: dict[str, float] = {}
        self._step_vehicle_states: list[VehicleSnapshot] | None = None
        self._step_pedestrian_states: list[PedestrianSnapshot] | None = None
        self._runtime_stage: tempfile.TemporaryDirectory[str] | None = None
        self._staged_output_files: list[tuple[Path, Path]] = []

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
        requested_extra_args = list(extra_args or [])
        config, requested_extra_args = self._prepare_runtime_paths(
            config,
            requested_extra_args,
        )
        command = [str(binary), "-c", str(config), "--no-step-log", "true"]
        if seed is not None:
            command.extend(["--seed", str(seed)])
        command.extend(requested_extra_args)
        if not gui:
            # SUMO 1.27.1 on Windows may abort without diagnostics when the
            # headless binary loads a GUI view-settings file from sumocfg.
            command.extend(["--gui-settings-file", ""])
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
                self._finalize_runtime_stage(copy_outputs=False)
                raise PlatformError(
                    ErrorCode.SUMO_UNAVAILABLE,
                    f"libsumo failed to start: {exc}",
                ) from exc
        else:
            import traci

            used_port = port
            try:
                # Port discovery releases its probe socket before SUMO binds.
                # Serialize discovery through connection establishment so two
                # paired runners cannot select the same ephemeral port.
                with _TRACI_START_LOCK:
                    used_port = port or find_free_port()
                    retry_count = max(1, int(self.startup_timeout_s) + 1)
                    if self._runtime_stage is None:
                        traci.start(
                            command,
                            port=used_port,
                            numRetries=retry_count,
                            label=self.label,
                        )
                    else:
                        process_environment = os.environ.copy()
                        if not _is_ascii_path(self.sumo_home):
                            process_environment.pop("SUMO_HOME", None)
                        process = subprocess.Popen(
                            [*command, "--remote-port", str(used_port)],
                            cwd=self._runtime_stage.name,
                            env=process_environment,
                        )
                        try:
                            traci.init(
                                used_port,
                                numRetries=retry_count,
                                host="localhost",
                                label=self.label,
                                proc=process,
                            )
                        except Exception:
                            if process.poll() is None:
                                process.terminate()
                                process.wait(timeout=5)
                            raise
                    self._root_module = traci
                    self._api = traci.getConnection(self.label)
            except Exception as exc:
                self._api = None
                self._root_module = None
                self._finalize_runtime_stage(copy_outputs=False)
                raise PlatformError(
                    ErrorCode.SUMO_UNAVAILABLE,
                    (
                        f"SUMO TraCI startup failed within "
                        f"{self.startup_timeout_s:.1f}s on port {used_port}: {exc}"
                    ),
                ) from exc
        self._running = True
        self._paused = False
        self._subscribed_vehicle_ids.clear()
        self._subscribed_person_ids.clear()
        self._subscribed_lane_ids.clear()
        self._subscribed_traffic_light_ids.clear()
        self._vehicle_class_by_type.clear()
        self._vehicle_length_by_id.clear()
        self._clear_step_state_cache()
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
            return self.get_network_state(vehicle_states=self.get_step_vehicle_states())
        self._clear_step_state_cache()
        try:
            api.simulationStep(0 if target_time_s is None else target_time_s)
        except Exception as exc:
            self._raise_if_process_exited(exc)
            raise
        vehicle_states = self.get_step_vehicle_states()
        snapshot = self.get_network_state(vehicle_states=vehicle_states)
        for callback in self._metric_callbacks:
            callback(snapshot)
        return snapshot

    def save_state(self, destination: Path) -> Path:
        """Persist the complete deterministic SUMO state for paired evaluation."""

        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._require_running().simulation.saveState(str(destination))
        if not destination.is_file():
            raise RuntimeError(f"SUMO did not create state file: {destination}")
        return destination

    def stop_simulation(self) -> None:
        """Close the connection and terminate the owned SUMO process."""

        if not self._running:
            self._finalize_runtime_stage(copy_outputs=False)
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
            self._subscribed_vehicle_ids.clear()
            self._subscribed_person_ids.clear()
            self._subscribed_lane_ids.clear()
            self._subscribed_traffic_light_ids.clear()
            self._vehicle_class_by_type.clear()
            self._vehicle_length_by_id.clear()
            self._clear_step_state_cache()
            self._finalize_runtime_stage(copy_outputs=True)

    def _clear_step_state_cache(self) -> None:
        """Invalidate state shared by consumers of one simulation step."""

        self._step_vehicle_states = None
        self._step_pedestrian_states = None

    def _prepare_runtime_paths(
        self,
        config: Path,
        extra_args: list[str],
    ) -> tuple[Path, list[str]]:
        """Stage non-ASCII Windows paths so SUMO can load and write reliably."""

        if os.name != "nt":
            return config, extra_args
        output_indexes = [
            index + 1
            for index, value in enumerate(extra_args[:-1])
            if value in _OUTPUT_FILE_OPTIONS
        ]
        input_indexes = [
            index + 1 for index, value in enumerate(extra_args[:-1]) if value in _INPUT_FILE_OPTIONS
        ]
        path_values: list[Path | str] = [config, self.sumo_home]
        path_values.extend(extra_args[index] for index in output_indexes)
        path_values.extend(extra_args[index] for index in input_indexes)
        if all(_is_ascii_path(value) for value in path_values):
            return config, extra_args

        runtime_root = os.environ.get("SUMO_RUNTIME_DIR")
        self._runtime_stage = tempfile.TemporaryDirectory(
            prefix="xiongan-sumo-",
            dir=runtime_root or None,
        )
        stage_root = Path(self._runtime_stage.name)
        if not _is_ascii_path(stage_root):
            self._finalize_runtime_stage(copy_outputs=False)
            raise PlatformError(
                ErrorCode.SUMO_UNAVAILABLE,
                (
                    "SUMO requires an ASCII runtime path on Windows; set "
                    "SUMO_RUNTIME_DIR to a writable ASCII-only directory"
                ),
            )
        staged_config = _stage_sumo_config(config, stage_root / "scenario")
        rewritten_args = list(extra_args)
        input_root = stage_root / "inputs"
        for sequence, index in enumerate(input_indexes, start=1):
            source = Path(extra_args[index]).resolve()
            if not source.is_file():
                raise FileNotFoundError(source)
            input_root.mkdir(parents=True, exist_ok=True)
            staged_input = input_root / f"{sequence:02d}-{source.name}"
            shutil.copy2(source, staged_input)
            rewritten_args[index] = str(staged_input)
        output_root = stage_root / "outputs"
        for sequence, index in enumerate(output_indexes, start=1):
            destination = Path(extra_args[index])
            if _is_ascii_path(destination):
                continue
            output_root.mkdir(parents=True, exist_ok=True)
            staged_output = output_root / f"{sequence:02d}-{destination.name}"
            rewritten_args[index] = str(staged_output)
            self._staged_output_files.append((staged_output, destination))
        return staged_config, rewritten_args

    def _finalize_runtime_stage(self, *, copy_outputs: bool) -> None:
        """Copy completed SUMO outputs back and release the temporary mirror."""

        if copy_outputs:
            for staged, destination in self._staged_output_files:
                if not staged.is_file():
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staged, destination)
        self._staged_output_files.clear()
        if self._runtime_stage is not None:
            self._runtime_stage.cleanup()
            self._runtime_stage = None

    def reset(self, config_file: Path, *, seed: int | None = None) -> None:
        """Stop and restart the same adapter with a new deterministic seed."""

        self.stop_simulation()
        self.start_simulation(config_file, seed=seed)

    def get_vehicle_states(self) -> list[VehicleSnapshot]:
        """Collect all active vehicle states in SI units."""

        api = self._require_running()
        subscribed = self._get_subscribed_vehicle_states(api)
        if subscribed is not None:
            return subscribed
        return self._get_vehicle_states_with_getters(api)

    def get_step_vehicle_states(self) -> list[VehicleSnapshot]:
        """Return the vehicle collection shared by the current simulation step."""

        if self._step_vehicle_states is None:
            self._step_vehicle_states = self.get_vehicle_states()
        return self._step_vehicle_states

    def _get_subscribed_vehicle_states(self, api: Any) -> list[VehicleSnapshot] | None:
        """Use TraCI subscriptions to avoid per-field socket round trips."""

        constants = getattr(self._root_module, "constants", None)
        vehicle_domain = api.vehicle
        if (
            constants is None
            or not hasattr(vehicle_domain, "subscribe")
            or not hasattr(vehicle_domain, "getAllSubscriptionResults")
        ):
            return None
        variable_names = (
            "VAR_TYPE",
            "VAR_POSITION",
            "VAR_NEXT_TLS",
            "VAR_COLOR",
            "VAR_ROAD_ID",
            "VAR_LANE_ID",
            "VAR_LANEPOSITION",
            "VAR_SPEED",
            "VAR_ACCELERATION",
            "VAR_ANGLE",
            "VAR_ROUTE_ID",
            "VAR_WAITING_TIME",
            "VAR_CO2EMISSION",
            "VAR_NOXEMISSION",
            "VAR_FUELCONSUMPTION",
            "VAR_SIGNALS",
            "VAR_LENGTH",
        )
        if any(not hasattr(constants, name) for name in variable_names):
            return None
        variables = tuple(int(getattr(constants, name)) for name in variable_names)
        try:
            vehicle_ids = tuple(str(item) for item in vehicle_domain.getIDList())
            active_ids = set(vehicle_ids)
            departed_ids = self._subscribed_vehicle_ids - active_ids
            self._subscribed_vehicle_ids.intersection_update(active_ids)
            for vehicle_id in departed_ids:
                self._vehicle_length_by_id.pop(vehicle_id, None)
            for vehicle_id in vehicle_ids:
                if vehicle_id in self._subscribed_vehicle_ids:
                    continue
                vehicle_domain.subscribe(vehicle_id, variables)
                self._subscribed_vehicle_ids.add(vehicle_id)
            results = vehicle_domain.getAllSubscriptionResults()
            if not isinstance(results, dict):
                return None
            snapshots: list[VehicleSnapshot] = []
            for vehicle_id in vehicle_ids:
                values = results.get(vehicle_id)
                if not isinstance(values, dict) or any(
                    variable not in values for variable in variables
                ):
                    return None
                vehicle_type = str(values[constants.VAR_TYPE])
                self._vehicle_length_by_id[vehicle_id] = float(values[constants.VAR_LENGTH])
                vehicle_class = self._vehicle_class_by_type.get(vehicle_type)
                if vehicle_class is None:
                    vehicle_class = str(api.vehicletype.getVehicleClass(vehicle_type))
                    self._vehicle_class_by_type[vehicle_type] = vehicle_class
                x_m, y_m = values[constants.VAR_POSITION]
                next_signals = values[constants.VAR_NEXT_TLS]
                color = values[constants.VAR_COLOR]
                snapshots.append(
                    VehicleSnapshot(
                        vehicle_id=vehicle_id,
                        vehicle_type=vehicle_type,
                        vehicle_class=vehicle_class,
                        road_id=str(values[constants.VAR_ROAD_ID]),
                        lane_id=str(values[constants.VAR_LANE_ID]),
                        x_m=float(x_m),
                        y_m=float(y_m),
                        lane_position_m=float(values[constants.VAR_LANEPOSITION]),
                        speed_m_s=float(values[constants.VAR_SPEED]),
                        acceleration_m_s2=float(values[constants.VAR_ACCELERATION]),
                        heading_deg=float(values[constants.VAR_ANGLE]),
                        route_id=str(values[constants.VAR_ROUTE_ID]),
                        next_intersection_id=(str(next_signals[0][0]) if next_signals else None),
                        distance_to_stop_line_m=(
                            max(0.0, float(next_signals[0][2])) if next_signals else 0.0
                        ),
                        waiting_time_s=float(values[constants.VAR_WAITING_TIME]),
                        co2_mg_s=float(values[constants.VAR_CO2EMISSION]),
                        nox_mg_s=float(values[constants.VAR_NOXEMISSION]),
                        fuel_mg_s=float(values[constants.VAR_FUELCONSUMPTION]),
                        signals=int(values[constants.VAR_SIGNALS]),
                        color_rgba=(
                            int(color[0]),
                            int(color[1]),
                            int(color[2]),
                            int(color[3]),
                        ),
                    )
                )
            return snapshots
        except Exception as exc:
            self._raise_if_process_exited(exc)
            return None

    def _get_vehicle_states_with_getters(self, api: Any) -> list[VehicleSnapshot]:
        """Collect vehicle states through individual getters as a compatibility path."""

        snapshots: list[VehicleSnapshot] = []
        for vehicle_id in api.vehicle.getIDList():
            vehicle_type = str(api.vehicle.getTypeID(vehicle_id))
            vehicle_class = self._vehicle_class_by_type.get(vehicle_type)
            if vehicle_class is None:
                vehicle_class = str(api.vehicletype.getVehicleClass(vehicle_type))
                self._vehicle_class_by_type[vehicle_type] = vehicle_class
            x_m, y_m = api.vehicle.getPosition(vehicle_id)
            next_signals = api.vehicle.getNextTLS(vehicle_id)
            next_intersection_id = str(next_signals[0][0]) if next_signals else None
            distance_to_stop_line_m = max(0.0, float(next_signals[0][2])) if next_signals else 0.0
            color = api.vehicle.getColor(vehicle_id)
            snapshots.append(
                VehicleSnapshot(
                    vehicle_id=vehicle_id,
                    vehicle_type=vehicle_type,
                    vehicle_class=vehicle_class,
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
        subscribed = self._get_subscribed_pedestrian_states(api)
        if subscribed is not None:
            return subscribed
        return self._get_pedestrian_states_with_getters(api)

    def get_step_pedestrian_states(self) -> list[PedestrianSnapshot]:
        """Return the pedestrian collection shared by the current simulation step."""

        if self._step_pedestrian_states is None:
            self._step_pedestrian_states = self.get_pedestrian_states()
        return self._step_pedestrian_states

    def _get_subscribed_pedestrian_states(
        self,
        api: Any,
    ) -> list[PedestrianSnapshot] | None:
        constants = getattr(self._root_module, "constants", None)
        person_domain = api.person
        variable_names = (
            "VAR_TYPE",
            "VAR_POSITION",
            "VAR_ROAD_ID",
            "VAR_LANE_ID",
            "VAR_SPEED",
            "VAR_WAITING_TIME",
            "VAR_ANGLE",
        )
        if (
            constants is None
            or not hasattr(person_domain, "subscribe")
            or not hasattr(person_domain, "getAllSubscriptionResults")
            or any(not hasattr(constants, name) for name in variable_names)
        ):
            return None
        variables = tuple(int(getattr(constants, name)) for name in variable_names)
        try:
            pedestrian_ids = tuple(str(item) for item in person_domain.getIDList())
            active_ids = set(pedestrian_ids)
            self._subscribed_person_ids.intersection_update(active_ids)
            for pedestrian_id in pedestrian_ids:
                if pedestrian_id in self._subscribed_person_ids:
                    continue
                person_domain.subscribe(pedestrian_id, variables)
                self._subscribed_person_ids.add(pedestrian_id)
            results = person_domain.getAllSubscriptionResults()
            if not isinstance(results, dict):
                return None
            stage_index_getter = getattr(person_domain, "getStageIndex", None)
            pedestrians: list[PedestrianSnapshot] = []
            for pedestrian_id in pedestrian_ids:
                values = results.get(pedestrian_id)
                if not isinstance(values, dict) or any(
                    variable not in values for variable in variables
                ):
                    return None
                x_m, y_m = values[constants.VAR_POSITION]
                road_id = str(values[constants.VAR_ROAD_ID])
                lane_id = str(values[constants.VAR_LANE_ID])
                internal_id = road_id or lane_id
                pedestrians.append(
                    PedestrianSnapshot(
                        pedestrian_id=pedestrian_id,
                        pedestrian_type=str(values[constants.VAR_TYPE]),
                        road_id=road_id,
                        lane_id=lane_id,
                        x_m=float(x_m),
                        y_m=float(y_m),
                        speed_m_s=max(0.0, float(values[constants.VAR_SPEED])),
                        waiting_time_s=max(
                            0.0,
                            float(values[constants.VAR_WAITING_TIME]),
                        ),
                        walking_stage_index=max(
                            0,
                            int(stage_index_getter(pedestrian_id))
                            if stage_index_getter is not None
                            else 0,
                        ),
                        crossing_id=(
                            internal_id
                            if internal_id.startswith(":") and "_c" in internal_id
                            else None
                        ),
                        waiting_area_id=(
                            internal_id
                            if internal_id.startswith(":") and "_w" in internal_id
                            else None
                        ),
                        heading_deg=float(values[constants.VAR_ANGLE]),
                    )
                )
            return pedestrians
        except Exception as exc:
            self._raise_if_process_exited(exc)
            return None

    def _get_pedestrian_states_with_getters(self, api: Any) -> list[PedestrianSnapshot]:
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

    def get_lane_states(
        self,
        lane_ids: list[str] | None = None,
        *,
        vehicle_states: Sequence[VehicleSnapshot] | None = None,
        pedestrian_states: Sequence[PedestrianSnapshot] | None = None,
    ) -> list[LaneSnapshot]:
        """Collect selected or all non-internal lane aggregates."""

        api = self._require_running()
        identifiers = lane_ids or [
            lane_id for lane_id in api.lane.getIDList() if not lane_id.startswith(":")
        ]
        vehicles_by_lane: dict[str, list[VehicleSnapshot]] = defaultdict(list)
        vehicles = self.get_vehicle_states() if vehicle_states is None else vehicle_states
        for vehicle in vehicles:
            vehicles_by_lane[vehicle.lane_id].append(vehicle)
        pedestrians_by_lane: dict[str, list[PedestrianSnapshot]] = defaultdict(list)
        pedestrians = (
            self.get_pedestrian_states() if pedestrian_states is None else pedestrian_states
        )
        for pedestrian in pedestrians:
            pedestrians_by_lane[pedestrian.lane_id].append(pedestrian)
        subscribed_lane_metrics = self._get_subscribed_lane_metrics(api, identifiers)
        snapshots: list[LaneSnapshot] = []
        for lane_id in identifiers:
            lane_vehicles = vehicles_by_lane.get(lane_id, [])
            bicycle_vehicles = [
                vehicle for vehicle in lane_vehicles if vehicle.vehicle_class == "bicycle"
            ]
            motor_vehicles = [
                vehicle for vehicle in lane_vehicles if vehicle.vehicle_class != "bicycle"
            ]
            motor_speeds = [vehicle.speed_m_s for vehicle in motor_vehicles]
            bicycle_speeds = [vehicle.speed_m_s for vehicle in bicycle_vehicles]
            lane_pedestrians = pedestrians_by_lane.get(lane_id, [])
            person_waiting = sum(pedestrian.waiting_time_s > 0.0 for pedestrian in lane_pedestrians)
            vehicle_count = len(motor_vehicles)
            queue_count = sum(speed < 0.1 for speed in motor_speeds)
            mean_length = (
                sum(
                    self._vehicle_length_by_id[vehicle.vehicle_id]
                    if vehicle.vehicle_id in self._vehicle_length_by_id
                    else float(api.vehicle.getLength(vehicle.vehicle_id))
                    for vehicle in motor_vehicles
                )
                / vehicle_count
                if vehicle_count
                else 5.0
            )
            lane_metrics = (
                subscribed_lane_metrics.get(lane_id)
                if subscribed_lane_metrics is not None
                else None
            )
            occupancy_percent, max_speed_m_s = (
                lane_metrics
                if lane_metrics is not None
                else (
                    float(api.lane.getLastStepOccupancy(lane_id)),
                    float(api.lane.getMaxSpeed(lane_id)),
                )
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
                        max(0.0, occupancy_percent / 100),
                    ),
                    max_speed_m_s=max_speed_m_s,
                    bicycle_count=len(bicycle_vehicles),
                    electric_bicycle_count=sum(
                        "electric" in vehicle.vehicle_type.lower() for vehicle in bicycle_vehicles
                    ),
                    bicycle_queue_count=sum(speed < 0.1 for speed in bicycle_speeds),
                    pedestrian_count=len(lane_pedestrians),
                    pedestrian_waiting_count=person_waiting,
                )
            )
        return snapshots

    def _get_subscribed_lane_metrics(
        self,
        api: Any,
        lane_ids: Sequence[str],
    ) -> dict[str, tuple[float, float]] | None:
        """Fetch dynamic lane metrics in one TraCI subscription response."""

        constants = getattr(self._root_module, "constants", None)
        lane_domain = api.lane
        variable_names = ("LAST_STEP_OCCUPANCY", "VAR_MAXSPEED")
        if (
            constants is None
            or not hasattr(lane_domain, "subscribe")
            or not hasattr(lane_domain, "getAllSubscriptionResults")
            or any(not hasattr(constants, name) for name in variable_names)
        ):
            return None
        variables = tuple(int(getattr(constants, name)) for name in variable_names)
        try:
            for lane_id in lane_ids:
                if lane_id in self._subscribed_lane_ids:
                    continue
                lane_domain.subscribe(lane_id, variables)
                self._subscribed_lane_ids.add(lane_id)
            results = lane_domain.getAllSubscriptionResults()
            if not isinstance(results, dict):
                return None
            metrics: dict[str, tuple[float, float]] = {}
            for lane_id in lane_ids:
                values = results.get(lane_id)
                if not isinstance(values, dict) or any(
                    variable not in values for variable in variables
                ):
                    return None
                metrics[lane_id] = (
                    float(values[constants.LAST_STEP_OCCUPANCY]),
                    float(values[constants.VAR_MAXSPEED]),
                )
            return metrics
        except Exception:
            return None

    def get_intersection_state(self, intersection_id: str) -> IntersectionSnapshot:
        """Collect the active phase and controlled lane IDs of one signal."""

        return self.get_intersection_states([intersection_id])[0]

    def get_intersection_states(
        self,
        intersection_ids: Sequence[str],
    ) -> list[IntersectionSnapshot]:
        """Collect multiple signal states through one subscription response."""

        api = self._require_running()
        subscribed = self._get_subscribed_intersection_states(api, intersection_ids)
        if subscribed is not None:
            return subscribed
        return [
            self._get_intersection_state_with_getters(api, intersection_id)
            for intersection_id in intersection_ids
        ]

    def _get_subscribed_intersection_states(
        self,
        api: Any,
        intersection_ids: Sequence[str],
    ) -> list[IntersectionSnapshot] | None:
        constants = getattr(self._root_module, "constants", None)
        signal_domain = api.trafficlight
        variable_names = (
            "TL_CURRENT_PHASE",
            "TL_RED_YELLOW_GREEN_STATE",
            "TL_PHASE_DURATION",
            "TL_NEXT_SWITCH",
            "TL_CONTROLLED_LANES",
        )
        if (
            constants is None
            or not hasattr(signal_domain, "subscribe")
            or not hasattr(signal_domain, "getAllSubscriptionResults")
            or any(not hasattr(constants, name) for name in variable_names)
        ):
            return None
        variables = tuple(int(getattr(constants, name)) for name in variable_names)
        try:
            for intersection_id in intersection_ids:
                if intersection_id in self._subscribed_traffic_light_ids:
                    continue
                signal_domain.subscribe(intersection_id, variables)
                self._subscribed_traffic_light_ids.add(intersection_id)
            results = signal_domain.getAllSubscriptionResults()
            if not isinstance(results, dict):
                return None
            snapshots: list[IntersectionSnapshot] = []
            for intersection_id in intersection_ids:
                values = results.get(intersection_id)
                if not isinstance(values, dict) or any(
                    variable not in values for variable in variables
                ):
                    return None
                snapshots.append(
                    IntersectionSnapshot(
                        intersection_id=intersection_id,
                        phase_index=int(values[constants.TL_CURRENT_PHASE]),
                        phase_state=str(values[constants.TL_RED_YELLOW_GREEN_STATE]),
                        phase_duration_s=float(values[constants.TL_PHASE_DURATION]),
                        next_switch_s=float(values[constants.TL_NEXT_SWITCH]),
                        controlled_lane_ids=tuple(
                            dict.fromkeys(
                                str(lane_id)
                                for lane_id in values[constants.TL_CONTROLLED_LANES]
                            )
                        ),
                    )
                )
            return snapshots
        except Exception:
            return None

    @staticmethod
    def _get_intersection_state_with_getters(
        api: Any,
        intersection_id: str,
    ) -> IntersectionSnapshot:
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

    def get_network_state(
        self,
        *,
        vehicle_states: Sequence[VehicleSnapshot] | None = None,
    ) -> NetworkSnapshot:
        """Aggregate live vehicle speed, queue and lifecycle counts."""

        api = self._require_running()
        vehicles = self.get_vehicle_states() if vehicle_states is None else vehicle_states
        motor_speeds = [
            vehicle.speed_m_s for vehicle in vehicles if vehicle.vehicle_class != "bicycle"
        ]
        bicycle_count = sum(vehicle.vehicle_class == "bicycle" for vehicle in vehicles)
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

    def release_speed_guidance(self, vehicle_id: str) -> None:
        """Return a vehicle from an expired advisory to native SUMO following."""

        self._require_running().vehicle.setSpeed(vehicle_id, -1.0)

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
