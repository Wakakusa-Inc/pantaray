from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.integration.local_artifact_test_support import (
    WORKER_CLAIM_OWNER,
    SummaryWindow,
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
from pantaray_agents.local_runtime.runtime.job_claim import claim_next_pending_job
from pantaray_agents.local_runtime.runtime.job_executor import LocalJobExecutionError
from pantaray_agents.local_runtime.runtime.job_types import (
    LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    LOCAL_SUGGESTION_JOB_TYPE,
)
from pantaray_agents.local_runtime.runtime.local_worker import (
    build_default_local_worker_specs,
    drain_local_jobs,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
    repair_inflight_jobs_for_startup,
)
from pantaray_agents.orchestration.runtime.activity_job_queue import (
    enqueue_activity_summary_job,
)
from pantaray_agents.schema.agent.activity import ActivitySummaryAgentResponse
from pantaray_agents.schema.agent.base import AgentError, ErrorSeverity, ErrorType
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    register_active_settings_module,
)

DB_BUSY_TIMEOUT_MS = 1_000
MAX_PIPELINE_JOB_COUNT = 8


@pytest.fixture(autouse=True)
def _stub_runtime_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    install_runtime_dependency_stub(monkeypatch=monkeypatch)


def _configure_local_runtime_env(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    artifact_root = tmp_path / "artifacts"
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=DB_BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    insert_user(db_path)
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", str(DB_BUSY_TIMEOUT_MS))
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)
    return artifact_root, db_path


def _build_worker_specs():
    return build_default_local_worker_specs(action_runner=lambda _payload: None)


def _seed_live_summary_window(db_path: Path) -> SummaryWindow:
    window = live_summary_window()
    insert_activity_log(
        db_path,
        log_id="log-1",
        user_id="user-1",
        period_start=window.log_period_start,
        period_end=window.period_end,
        description="User reviewed project notes",
    )
    return window


def _count_rows(db_path: Path, sql: str, params: tuple[object, ...] = ()) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(sql, params).fetchone()
    if row is None:
        raise AssertionError("Expected count row was not found")
    return int(row[0])


def test_activity_summary_restart_recovery_does_not_trigger_memory_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifact_root, db_path = _configure_local_runtime_env(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    window = _seed_live_summary_window(db_path)

    async def _fake_run_local_activity_summary_agent(**_kwargs):
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
    claimed = claim_next_pending_job(
        db_path=str(db_path),
        busy_timeout_ms=DB_BUSY_TIMEOUT_MS,
        job_type=LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
        owner_user_id="user-1",
        claimed_by=WORKER_CLAIM_OWNER,
        process_running_status="running",
        expected_process_pending_status="enqueued",
    )

    assert claimed is not None
    assert (
        repair_inflight_jobs_for_startup(
            db_path=db_path,
            busy_timeout_ms=DB_BUSY_TIMEOUT_MS,
        )
        == 1
    )

    completed = drain_local_jobs(
        db_path=db_path,
        busy_timeout_ms=DB_BUSY_TIMEOUT_MS,
        claimed_by=WORKER_CLAIM_OWNER,
        specs=_build_worker_specs(),
        max_jobs=MAX_PIPELINE_JOB_COUNT,
    )
    assert completed == 1
    # A canceled Summary reaches the same counts without ever running the agent.
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM activity_summaries "
            "WHERE summary_id = 'summary-1' AND status = 'success'",
        )
        == 1
    )
    assert (
        _count_rows(
            db_path,
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type IN ('generate_insight', 'update_insight', 'structure_facts')
            """,
        )
        == 0
    )
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')",
        )
        == 0
    )
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM processes WHERE status IN ('enqueued', 'running')",
        )
        == 0
    )


def test_activity_summary_failure_does_not_trigger_memory_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _artifact_root, db_path = _configure_local_runtime_env(
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    window = _seed_live_summary_window(db_path)

    async def _fake_failed_activity_summary_agent(**_kwargs):
        return ActivitySummaryExecutionResult(
            response=ActivitySummaryAgentResponse(
                summary_id="summary-error",
                user_id="user-1",
                summary_type="24h",
                summary="",
                thinking=None,
                period_start=window.period_start,
                period_end=window.period_end,
                source_ids=["log-1"],
                created_at=window.period_end,
                status="error",
                error=AgentError(
                    error_type=ErrorType.INTERNAL_ERROR.value,
                    error_code="ACTIVITY_SUMMARY_FAILED",
                    error_message="summary generation failed",
                    severity=ErrorSeverity.ERROR.value,
                ),
            ),
            prompt_text="prompt",
        )

    monkeypatch.setattr(
        "pantaray_agents.tasks.internal_jobs.activity.run_local_activity_summary_agent",
        _fake_failed_activity_summary_agent,
    )

    enqueue_activity_summary_job(
        user_id="user-1",
        summary_id="summary-error",
        summary_type="24h",
        period_start=window.period_start,
        period_end=window.period_end,
    )

    # The executor's error names the job and the exception class only; the
    # agent's own message stays out of it.
    with pytest.raises(LocalJobExecutionError) as failure:
        drain_local_jobs(
            db_path=db_path,
            busy_timeout_ms=DB_BUSY_TIMEOUT_MS,
            claimed_by=WORKER_CLAIM_OWNER,
            specs=_build_worker_specs(),
            max_jobs=MAX_PIPELINE_JOB_COUNT,
        )
    assert failure.value.job_type == LOCAL_ACTIVITY_SUMMARY_JOB_TYPE

    assert (
        _count_rows(
            db_path,
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type IN ('generate_insight', 'update_insight', 'structure_facts')
            """,
        )
        == 0
    )
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM jobs WHERE job_type = ?",
            (LOCAL_SUGGESTION_JOB_TYPE,),
        )
        == 0
    )
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM activity_summaries WHERE summary_id = ? AND status = 'error'",
            ("summary-error",),
        )
        == 1
    )
    assert (
        _count_rows(
            db_path,
            "SELECT COUNT(*) FROM activity_summaries WHERE summary_id = ? AND status = 'processing'",
            ("summary-error",),
        )
        == 0
    )
