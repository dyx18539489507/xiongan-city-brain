"""Timezone and simulation-time utilities."""

from datetime import UTC, datetime, timedelta


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def expires_after(seconds: float) -> datetime:
    """Return an expiry timestamp relative to the current UTC time."""

    return utc_now() + timedelta(seconds=seconds)

