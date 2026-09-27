from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    reset_desktop_session_store,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)


@pytest.fixture(autouse=True)
def _reset_session_store() -> None:
    reset_desktop_session_store()
    yield
    reset_desktop_session_store()


def _activate_session(db_path: Path, *, user_id: str = "user-1") -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=user_id,
        desktop_access_token="header.payload.signature",
        expires_at="2099-03-27T01:00:00Z",
        session_version="1",
    )


def test_activity_summary_enqueue_rolls_back_job_when_event_insert_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", "1000")
    _activate_session(db_path)

    from pantaray_agents.local_runtime.runtime import activity_queue
    from pantaray_agents.local_runtime.runtime.activity_source_rows import (
        reserve_activity_summary_processing,
    )
    from pantaray_agents.orchestration.runtime import activity_job_queue

    reserve_activity_summary_processing(
        db_path=db_path,
        busy_timeout_ms=1_000,
        summary_id="summary-1",
        user_id="user-1",
        summary_type="24h",
        period_start="2026-03-26T00:00:00Z",
        period_end="2026-03-27T00:00:00Z",
        created_at="2026-03-27T00:00:00Z",
    )

    def _boom(**_kwargs: object) -> str:
        raise RuntimeError("event insert failed")

    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            activity_queue,
            "append_process_event_in_connection",
            _boom,
        )
        with pytest.raises(RuntimeError, match="event insert failed"):
            activity_job_queue.enqueue_activity_summary_job(
                user_id="user-1",
                summary_id="summary-1",
                summary_type="24h",
                period_start="2026-03-26T00:00:00Z",
                period_end="2026-03-27T00:00:00Z",
            )

    with sqlite3.connect(db_path) as connection:
        source_row = connection.execute(
            """
            SELECT status
            FROM activity_summaries
            WHERE summary_id = 'summary-1'
            """
        ).fetchone()
        job_count = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE logical_key = 'summary-1'"
        ).fetchone()

    assert source_row == ("processing",)
    assert job_count == (0,)

    result = activity_job_queue.enqueue_activity_summary_job(
        user_id="user-1",
        summary_id="summary-1",
        summary_type="24h",
        period_start="2026-03-26T00:00:00Z",
        period_end="2026-03-27T00:00:00Z",
    )

    with sqlite3.connect(db_path) as connection:
        job_and_event = connection.execute(
            """
            SELECT COUNT(jobs.job_id), COUNT(process_events.event_id)
            FROM jobs
            JOIN process_events USING (process_id)
            WHERE jobs.job_id = ?
            """,
            (result["job_id"],),
        ).fetchone()

    assert job_and_event == (1, 1)
