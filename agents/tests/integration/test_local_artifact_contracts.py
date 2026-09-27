from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.integration.local_artifact_test_support import (
    WORKER_CLAIM_OWNER,
    insert_activity_log,
    insert_user,
    live_summary_window,
)
from tests.integration.local_artifact_test_support import (
    reset_local_store_owner as reset_local_store_owner,
)
from tests.integration.runtime_dependency_stub import install_runtime_dependency_stub

from pantaray_agents.local_runtime.runtime.activity_local_executor import (
    ActivitySummaryExecutionResult,
)
from pantaray_agents.local_runtime.runtime.local_worker import (
    build_default_local_worker_specs,
    drain_local_jobs,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.orchestration.runtime.activity_job_queue import (
    enqueue_activity_summary_job,
)
from pantaray_agents.schema.agent.activity import ActivitySummaryAgentResponse
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    register_active_settings_module,
)


@pytest.fixture(autouse=True)
def _stub_runtime_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime_dependency_stub(monkeypatch=monkeypatch)


def test_activity_summary_does_not_trigger_memory_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    insert_user(db_path)
    window = live_summary_window()
    insert_activity_log(
        db_path,
        log_id="log-1",
        user_id="user-1",
        period_start=window.log_period_start,
        period_end=window.period_end,
        description="User reviewed project notes",
    )

    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", "1000")
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)

    async def _fake_run_local_activity_summary_agent(**_kwargs):  # noqa: ANN003
        return ActivitySummaryExecutionResult(
            response=ActivitySummaryAgentResponse(
                summary_id="summary-1",
                user_id="user-1",
                summary_type="24h",
                summary="The user concentrated on project documentation.",
                thinking=None,
                period_start=window.period_start,
                period_end=window.period_end,
                source_ids=["log-1"],
                created_at=window.period_end,
                status="success",
                error=None,
            ),
            prompt_text="prompt",
        )

    monkeypatch.setattr(
        "pantaray_agents.tasks.internal_jobs.activity.run_local_activity_summary_agent",
        _fake_run_local_activity_summary_agent,
    )

    enqueue_activity_summary_job(
        user_id="user-1",
        summary_id="summary-1",
        summary_type="24h",
        period_start=window.period_start,
        period_end=window.period_end,
    )

    completed = drain_local_jobs(
        db_path=db_path,
        busy_timeout_ms=1_000,
        claimed_by=WORKER_CLAIM_OWNER,
        specs=build_default_local_worker_specs(action_runner=lambda _payload: None),
        max_jobs=8,
    )

    with sqlite3.connect(db_path) as connection:
        job_count = connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status = 'completed'"
        ).fetchone()
        memory_job_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type IN ('generate_insight', 'update_insight', 'structure_facts')
            """
        ).fetchone()
        summary_status = connection.execute(
            "SELECT status FROM activity_summaries WHERE summary_id = 'summary-1'"
        ).fetchone()

    assert completed == 1
    assert job_count == (1,)
    assert memory_job_count == (0,)
    # A canceled Summary reaches the same counts without ever running the agent.
    assert summary_status == ("success",)
