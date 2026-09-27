from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from tests.activity_log_seed import seed_activity_log

from pantaray_agents.local_runtime.runtime.activity_source_rows import (
    persist_activity_summary_result,
    reserve_activity_summary_processing,
)
from pantaray_agents.local_runtime.runtime.memory_agent_dispatcher import (
    dispatch_memory_agent_triggers_once,
)
from pantaray_agents.local_runtime.runtime.session_store import import_desktop_session
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database

NOW = datetime(2026, 8, 16, 2, 0, tzinfo=UTC)


def _prepare_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(db_path, 1_000, load_default_migrations())
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at="2099-08-16T00:00:00Z",
        session_version="1",
    )
    seed_activity_log(
        db_path,
        log_id="log-1",
        user_id="user-1",
        period_start="2026-08-15T23:56:00Z",
        period_end="2026-08-16T00:00:00Z",
    )
    return db_path


def _persist_summary(db_path: Path, *, summary_id: str, summary_type: str) -> None:
    period_start = (
        "2026-08-15T00:00:00Z" if summary_type == "24h" else "2026-08-15T23:00:00Z"
    )
    reserve_activity_summary_processing(
        db_path=db_path,
        busy_timeout_ms=1_000,
        summary_id=summary_id,
        user_id="user-1",
        summary_type=summary_type,
        period_start=period_start,
        period_end="2026-08-16T00:00:00Z",
        created_at="2026-08-16T00:10:00Z",
    )
    persist_activity_summary_result(
        db_path=db_path,
        busy_timeout_ms=1_000,
        summary_id=summary_id,
        user_id="user-1",
        summary_type=summary_type,
        period_start=period_start,
        period_end="2026-08-16T00:00:00Z",
        summary="summary",
        status="success",
        error=None,
        prompt_text="prompt",
        thinking=None,
        source_ids=["log-1"],
        updated_at="2026-08-16T00:10:01Z",
    )


def test_hourly_summary_records_no_memory_agent_trigger(tmp_path: Path) -> None:
    db_path = _prepare_db(tmp_path)
    _persist_summary(db_path, summary_id="summary-1h", summary_type="1h")

    result = dispatch_memory_agent_triggers_once(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        now=NOW,
    )

    assert result.outcomes == ()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM memory_agent_triggers"
        ).fetchone() == (0,)


def test_daily_summary_starts_a_unified_memory_run_on_its_own(
    tmp_path: Path,
) -> None:
    db_path = _prepare_db(tmp_path)
    _persist_summary(db_path, summary_id="summary-24h", summary_type="24h")

    result = dispatch_memory_agent_triggers_once(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id="user-1",
        now=NOW,
    )

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.trigger.trigger_kind == "memory_from_24h_summary"
    with sqlite3.connect(db_path) as connection:
        job = connection.execute(
            "SELECT job_type, logical_key, status FROM jobs WHERE job_id = ?",
            (outcome.job_id,),
        ).fetchone()
        trigger = connection.execute(
            """
            SELECT status, dispatched_job_id, outcome_code
            FROM memory_agent_triggers
            WHERE source_id = 'summary-24h'
            """
        ).fetchone()
    assert job == ("memory_update", "user-1", "queued")
    assert trigger == ("dispatched", outcome.job_id, "JOB_ENQUEUED")
