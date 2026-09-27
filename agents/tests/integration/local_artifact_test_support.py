from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from tests.activity_log_seed import seed_activity_log

from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.local_owner import ensure_logged_out_owner
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    mark_configured,
)
from pantaray_agents.mock.mock_llm_client import MockLLMClient

WORKER_CLAIM_OWNER = "local-artifact-integration-tests"
SUMMARY_WINDOW_LENGTH = timedelta(hours=24)
# Far enough behind `now` to be a complete window, far short of the expiry lag.
SUMMARY_WINDOW_LAG = timedelta(minutes=5)
ACTIVITY_LOG_SLOT_LENGTH = timedelta(minutes=4)


@dataclass(frozen=True, slots=True)
class SummaryWindow:
    period_start: str
    period_end: str
    log_period_start: str


def _iso_z(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def live_summary_window() -> SummaryWindow:
    """A 24h window the runtime still summarizes, plus a log slot inside it.

    A window expires 24h after its period end
    (`runtime.activity_summary_execution.is_activity_summary_window_expired`),
    so a fixed calendar date silently turns a Summary test into a test of the
    canceled-on-expiry path once that date is a day old.
    """
    period_end = datetime.now(UTC) - SUMMARY_WINDOW_LAG
    return SummaryWindow(
        period_start=_iso_z(period_end - SUMMARY_WINDOW_LENGTH),
        period_end=_iso_z(period_end),
        log_period_start=_iso_z(period_end - ACTIVITY_LOG_SLOT_LENGTH),
    )


@pytest.fixture(autouse=True)
def reset_local_store_owner() -> Iterator[None]:
    """`register_logged_out_owner` is process-global; never carry it between tests."""
    reset_logged_out_owner()
    yield
    reset_logged_out_owner()


def insert_user(db_path: Path, *, user_id: str = "user-1") -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                ui_language,
                created_at,
                updated_at
            ) VALUES (?, 'ja', '2026-03-30T00:00:00Z', '2026-03-30T00:00:00Z')
            """,
            (user_id,),
        )
    # Startup owns the store before any job runs; route identity reads that owner
    # even while an account is signed in (`runtime.route_identity`).
    register_logged_out_owner(
        ensure_logged_out_owner(db_path=db_path, busy_timeout_ms=1_000)
    )
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="header.payload.signature",
        expires_at="2099-03-27T01:00:00Z",
        session_version="1",
    )
    # The worker only claims once Electron main has applied `configure`.
    mark_configured()


def insert_activity_log(
    db_path: Path,
    *,
    log_id: str,
    user_id: str,
    period_start: str,
    period_end: str,
    description: str = "desc",
) -> None:
    seed_activity_log(
        db_path,
        log_id=log_id,
        user_id=user_id,
        period_start=period_start,
        period_end=period_end,
        description=description,
    )


def build_test_llm_client() -> MockLLMClient:
    client = MockLLMClient()
    client.files = SimpleNamespace(
        upload=MagicMock(
            return_value=SimpleNamespace(
                uri="gemini://capture-1",
                name="files/capture-1",
            )
        ),
        delete=MagicMock(),
    )
    return client
