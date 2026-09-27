"""Local time as models should read it.

Storage stays UTC. A model reasoning about "today" or "yesterday" must see the
user's wall clock, and the backend runs on the user's Mac, so the OS zone is the
user's zone (the same source Codex CLI and Hermes Agent use).
"""

from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pantaray_agents.utils.timestamps import parse_iso8601_utc

_ZONEINFO_MARKER = "zoneinfo/"
_LOCALTIME_LINK = "/etc/localtime"


def local_zone_name() -> str | None:
    """IANA name of the zone `datetime.astimezone()` uses, or None if unknown."""

    # TZ overrides /etc/localtime for the process, so when it is set it alone
    # names the zone in use; a POSIX rule or a file path has no IANA name.
    configured = os.environ.get("TZ")
    if configured is not None:
        key = configured.lstrip(":")
        return key if _is_iana_key(key) else None
    try:
        target = os.readlink(_LOCALTIME_LINK)
    except OSError:
        return None
    _, marker, name = target.partition(_ZONEINFO_MARKER)
    return name if marker and name else None


def _is_iana_key(key: str) -> bool:
    try:
        ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def describe_local_time(value: datetime, zone_name: str | None) -> str:
    """e.g. `2026-09-27T06:50+09:00 (Asia/Tokyo)`; offset only when unnamed."""

    text = value.astimezone().isoformat(timespec="minutes")
    return f"{text} ({zone_name})" if zone_name else text


def describe_utc_timestamp(value: str) -> str:
    """A stored UTC ISO-8601 string as local time with offset, unnamed.

    For timestamps repeated in one result; name the zone once beside them.
    """

    return describe_local_time(parse_iso8601_utc(value), None)


def local_period(start: str, end: str) -> str:
    return f"{describe_utc_timestamp(start)} - {describe_utc_timestamp(end)}"


def local_time_note(zone_name: str | None) -> str:
    """Names the zone once per prompt; every time also carries its offset."""

    return f"Times are local ({zone_name})." if zone_name else "Times are local."


def local_now_for_model() -> str:
    return describe_local_time(datetime.now().astimezone(), local_zone_name())


__all__ = [
    "describe_local_time",
    "describe_utc_timestamp",
    "local_now_for_model",
    "local_period",
    "local_time_note",
    "local_zone_name",
]
