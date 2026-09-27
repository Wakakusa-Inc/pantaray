from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pantaray_agents.local_runtime.runtime.utc_timestamps import parse_utc_iso
from pantaray_agents.local_runtime.storage.migrations import MigrationError


def test_parse_utc_iso_accepts_utc_z_suffix() -> None:
    assert parse_utc_iso("2026-03-24T00:10:00Z") == datetime(
        2026, 3, 24, 0, 10, 0, tzinfo=UTC
    )


def test_parse_utc_iso_normalizes_offset_to_utc() -> None:
    assert parse_utc_iso("2026-03-24T09:10:00+09:00") == datetime(
        2026, 3, 24, 0, 10, 0, tzinfo=UTC
    )


def test_parse_utc_iso_rejects_naive_timestamps() -> None:
    with pytest.raises(MigrationError, match="timezone information is required"):
        parse_utc_iso("2026-03-24T00:10:00")
