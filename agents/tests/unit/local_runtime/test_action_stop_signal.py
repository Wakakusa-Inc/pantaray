"""実行中の呼び出しが読む「停止された」の耐久事実。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.runtime.action_stop_signal import (
    action_stop_requested,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)

from .action_seed import insert_agent_action
from .migrated_db import prepare_test_database

_BUSY_TIMEOUT_MS = 1_000
_JOB_ID = "job-1"


def _runtime_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    insert_agent_action(db_path=db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, user_id, job_type, status, attempt, scheduled_at
            ) VALUES (?, 'user-1', 'execute_action', 'running', 0, ?)
            """,
            (_JOB_ID, "2026-09-08T00:00:00Z"),
        )
    return db_path


def _stop_requested(db_path: Path, *, job_id: str | None = _JOB_ID) -> bool:
    return action_stop_requested(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        user_id="user-1",
        action_id="action-1",
        job_id=job_id,
    )


def test_a_running_action_without_a_stop_keeps_going(tmp_path: Path) -> None:
    assert _stop_requested(_runtime_db(tmp_path)) is False


def test_the_job_stop_fence_is_observed_before_the_action_terminal(
    tmp_path: Path,
) -> None:
    """子が生きている Stop は fence だけを書く。実行中の呼び出しはそれを読む。"""

    db_path = _runtime_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE jobs SET cancel_requested_at = ? WHERE job_id = ?",
            ("2026-09-08T00:00:01Z", _JOB_ID),
        )
        assert (
            connection.execute(
                "SELECT status FROM agent_actions WHERE action_id = 'action-1'"
            ).fetchone()[0]
            != "canceled"
        )

    assert _stop_requested(db_path) is True
    # 別 job の fence は、この run を止めない。
    assert _stop_requested(db_path, job_id="job-other") is False


def test_a_canceled_action_stops_a_run_without_a_job(tmp_path: Path) -> None:
    db_path = _runtime_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE agent_actions SET status = 'canceled' WHERE action_id = 'action-1'"
        )

    assert _stop_requested(db_path, job_id=None) is True
