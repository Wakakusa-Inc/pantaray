from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pantaray_agents.utils import local_time
from pantaray_agents.utils.local_time import (
    describe_local_time,
    local_time_note,
    local_zone_name,
)

TOKYO = timezone(timedelta(hours=9))


@pytest.mark.usefixtures("tokyo_local_zone")
def test_describe_local_time_shows_the_wall_clock_date_not_the_utc_date() -> None:
    # 06:50 in Tokyo is still the previous day in UTC; the model must see the 27th.
    instant = datetime(2026, 9, 26, 21, 50, tzinfo=UTC)
    assert (
        describe_local_time(instant, "Asia/Tokyo")
        == "2026-09-27T06:50+09:00 (Asia/Tokyo)"
    )
    assert describe_local_time(instant.astimezone(TOKYO), None) == (
        "2026-09-27T06:50+09:00"
    )


def test_local_zone_name_prefers_tz_then_the_localtime_link(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    link = tmp_path / "localtime"
    link.symlink_to("/var/db/timezone/zoneinfo/Europe/Paris")
    monkeypatch.setattr(local_time, "_LOCALTIME_LINK", str(link))

    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert local_zone_name() == "Asia/Tokyo"
    # A set TZ is the zone in use even without a slash; the link must not name it.
    monkeypatch.setenv("TZ", "UTC")
    assert local_zone_name() == "UTC"
    # A POSIX rule or a zone file path has no IANA name: offset only.
    for unnamed in ("JST-9", "/usr/share/zoneinfo/Asia/Tokyo"):
        monkeypatch.setenv("TZ", unnamed)
        assert local_zone_name() is None

    monkeypatch.delenv("TZ")
    assert local_zone_name() == "Europe/Paris"

    monkeypatch.setattr(local_time, "_LOCALTIME_LINK", str(tmp_path / "missing"))
    assert local_zone_name() is None


def test_local_time_note_names_the_zone_only_when_known() -> None:
    assert local_time_note("Asia/Tokyo") == "Times are local (Asia/Tokyo)."
    assert local_time_note(None) == "Times are local."
