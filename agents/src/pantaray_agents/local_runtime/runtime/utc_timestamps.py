from __future__ import annotations

from datetime import UTC, datetime

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.utils.timestamps import format_iso8601_utc_z_milliseconds

UTC_ISO_SECONDS_TIMESPEC = "seconds"


def utc_now() -> datetime:
    return datetime.now(UTC)


def format_utc_iso(value: datetime) -> str:
    return format_iso8601_utc_z_milliseconds(value)


def format_utc_seconds_iso(value: datetime) -> str:
    return (
        value.astimezone(UTC)
        .isoformat(timespec=UTC_ISO_SECONDS_TIMESPEC)
        .replace("+00:00", "Z")
    )


def now_utc_iso() -> str:
    return format_utc_iso(utc_now())


def parse_utc_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MigrationError(f"invalid UTC timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise MigrationError(f"timezone information is required: {value}")
    return parsed.astimezone(UTC)


__all__ = [
    "format_utc_iso",
    "format_utc_seconds_iso",
    "now_utc_iso",
    "parse_utc_iso",
    "utc_now",
]
