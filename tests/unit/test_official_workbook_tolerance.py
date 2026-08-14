"""Displayed-precision checks for organizer ratio cells."""

from traffic_platform.scenario_engine.official_workbook import (
    _display_tolerance,
    _ratios_differ,
)


def test_two_decimal_ratio_accepts_display_equivalent_rounding() -> None:
    tolerance = _display_tolerance("0.00_ ")

    assert tolerance > 0.005
    assert not _ratios_differ(0.56, 0.5621500559910414, tolerance=tolerance)
    assert _ratios_differ(0.37, 0.37512537612838515, tolerance=tolerance)


def test_exact_format_remains_strict_when_decimals_are_not_declared() -> None:
    tolerance = _display_tolerance("General")

    assert tolerance == 1e-9
    assert _ratios_differ(0.5, 0.500001, tolerance=tolerance)
