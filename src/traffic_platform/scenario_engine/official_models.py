"""Typed organizer-workbook records used by the independent SUMO builder."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROFILE_KEYS = ("am_peak", "offpeak", "pm_peak")
MOVEMENTS = (
    "E_L",
    "E_S",
    "E_R",
    "W_L",
    "W_S",
    "W_R",
    "S_L",
    "S_S",
    "S_R",
    "N_L",
    "N_S",
    "N_R",
)


@dataclass(frozen=True, slots=True)
class FlowInterval:
    """One exact 15-minute movement-count interval from the workbook."""

    begin_s: int
    end_s: int
    source_begin: str
    source_end: str
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class DemandProfile:
    """Two-hour organizer demand profile and its source totals."""

    key: str
    label: str
    clock_window: str
    intervals: tuple[FlowInterval, ...]
    movement_totals: dict[str, int]
    approach_totals: dict[str, int]
    source_approach_totals: dict[str, float]

    @property
    def total_vehicles(self) -> int:
        """Return the exact vehicle count represented by the profile."""

        return sum(self.movement_totals.values())


@dataclass(frozen=True, slots=True)
class SignalPhase:
    """One official fixed-time signal phase."""

    phase_id: str
    name: str
    green_s: int
    yellow_s: int
    all_red_s: int

    @property
    def total_s(self) -> int:
        """Return the complete phase time."""

        return self.green_s + self.yellow_s + self.all_red_s


@dataclass(frozen=True, slots=True)
class SignalProfile:
    """Official signal plan for one time-of-day profile."""

    key: str
    label: str
    clock_window: str
    cycle_s: int
    source_cycle_s: int
    phases: tuple[SignalPhase, ...]


@dataclass(frozen=True, slots=True)
class OfficialWorkbook:
    """Parsed, validated organizer workbook."""

    path: Path
    demand_profiles: dict[str, DemandProfile]
    signal_profiles: dict[str, SignalProfile]
    source_audit: dict[str, Any]
