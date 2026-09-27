from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.application.action.ports import (
    ActionAssistantMessageEmission,
    ActionStepEmission,
    ActionToolStepEmission,
)
from pantaray_agents.local_runtime.runtime.action_job_runtime_repository import (
    ActionJobExecutionContext,
    ActionJobPreparation,
)
from pantaray_agents.local_runtime.runtime.action_queue import (
    build_local_action_enqueue_request,
)
from pantaray_agents.local_runtime.runtime.job_control import DeferredLocalJob
from pantaray_agents.local_runtime.runtime.job_enqueue import (
    enqueue_local_job_with_connection,
)
from pantaray_agents.local_runtime.runtime.job_queue_runtime import (
    claim_next_pending_action_job,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.schema.agent.action import (
    ActionExecutionResult,
    ActionRunResult,
    ActionScratchExecutionTarget,
    ActionUserMessageInput,
)
from pantaray_agents.schema.agent.image import ImageInput
from pantaray_agents.tasks.action_job import _run_action_job
from pantaray_agents.tasks.types import ActionContinuationRef, ActionJobRuntimePayload

RUNTIME_MODULE = "pantaray_agents.tasks.action_job_runtime"


def _payload(*, tool_approval: bool = False) -> ActionJobRuntimePayload:
    continuation_ref: ActionContinuationRef = (
        {
            "kind": "tool_approval",
            "approval_session_id": "approval-1",
            "tool_request_id": "tool-request-1",
        }
        if tool_approval
        else {"kind": "user_step", "user_step_id": "user-step-1"}
    )
    return {
        "job_id": "job-1",
        "process_id": "process-1",
        "action_id": "action-1",
        "user_id": "user-1",
        "continuation_ref": continuation_ref,
    }


def _context(*, tool_approval: bool = False) -> ActionJobExecutionContext:
    return ActionJobExecutionContext(
        suggestion_id=None,
        user_step_id="user-step-1",
        user_step_number=1,
        user_step_local_step_number=1,
        user_step_short_id="S-1-USER",
        user_step_created_at="2026-08-16T00:10:00Z",
        user_message=ActionUserMessageInput(
            message_id="message-1",
            content="Perform the work",
            images=(ImageInput(storage_path="images/input.png"),),
            language="ja",
        ),
        execution_target=ActionScratchExecutionTarget(),
        command_id="message-1",
        accepted_at="2026-08-16T00:10:00Z",
        approval_session_id="approval-1" if tool_approval else None,
        approval_tool_request_id="tool-request-1" if tool_approval else None,
        checkpoint_step_id="checkpoint-1" if tool_approval else None,
    )


def _claim_job(
    *,
    db_path: Path,
    payload: ActionJobRuntimePayload,
) -> ActionJobRuntimePayload:
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    enqueue_local_job_with_connection(
        db_path=str(db_path),
        busy_timeout_ms=1_000,
        request=build_local_action_enqueue_request(
            payload,
            scheduled_at="2026-08-16T00:00:00Z",
            suggestion_id=None,
        ),
    )
    claimed_payload = claim_next_pending_action_job(
        db_path=db_path,
        busy_timeout_ms=1_000,
        owner_user_id="user-1",
        claimed_by="worker-1",
    )
    assert claimed_payload == payload
    return claimed_payload


class _FakeTerminalWriter:
    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self.state = kwargs["state"]
        self.persisted: list[dict[str, object]] = []

    async def persist_terminal_until_success(self, **kwargs):  # noqa: ANN003, ANN201
        self.persisted.append(kwargs)
        self.state.terminal_written = True
        return kwargs["requested_status"]

    async def write_pause_terminal(self, **_kwargs) -> None:  # noqa: ANN003
        self.state.terminal_written = True


def _execution_result(req) -> ActionExecutionResult:  # noqa: ANN001
    return ActionExecutionResult(
        run_result=ActionRunResult(
            action_id=req.action_id,
            suggestion_id=req.suggestion_id,
            user_id=req.user_id,
            completed_at="2026-08-16T01:10:00Z",
            status="success",
            final_output="done",
            action_failure_code=None,
            error_payload=None,
            failure_stage=None,
            failure_message_public=None,
            final_prompt_text="final prompt",
            prompt_name="action/executing",
            prompt_version="1.0",
            total_steps=1,
            total_llm_steps=1,
            total_tool_steps=0,
            total_prompt_tokens=10,
            total_completion_tokens=5,
        ),
        execution_session_id=None,
        runtime_state_checkpoint=None,
    )


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    preparation: ActionJobPreparation,
    calls: dict[str, object],
    runtime_db_path: Path = Path("runtime.db"),
    action_step: ActionStepEmission | None = None,
) -> None:
    class _Repository:
        def __init__(self, *, db_path: Path, busy_timeout_ms: int) -> None:
            assert db_path == runtime_db_path
            assert busy_timeout_ms == 1_000

        def prepare_execution(self, **kwargs) -> ActionJobPreparation:  # noqa: ANN003
            calls["prepare"] = kwargs
            return preparation

        def finalize_skipped_action_start(self, **kwargs) -> None:  # noqa: ANN003
            calls["skip"] = kwargs["command"]

    class _ActionUseCase:
        async def execute_action_runtime(
            self,
            req,
            *,
            emit_action_step,
            emit_error,
        ):  # noqa: ANN001, ARG002
            calls["request"] = req
            if action_step is not None:
                await emit_action_step(action_step)
            return _execution_result(req)

    async def _get_action_application_service() -> _ActionUseCase:
        return _ActionUseCase()

    def _append_event(**kwargs) -> str:  # noqa: ANN003
        calls.setdefault("events", []).append(kwargs)
        return "event-2"

    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.read_local_runtime_db_config",
        lambda: (runtime_db_path, 1_000),
    )
    monkeypatch.setattr(f"{RUNTIME_MODULE}.ActionJobRuntimeRepository", _Repository)
    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.ActionJobTerminalWriter", _FakeTerminalWriter
    )
    monkeypatch.setattr(f"{RUNTIME_MODULE}.append_local_process_event", _append_event)
    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.deps.get_action_application_service",
        _get_action_application_service,
    )


@pytest.mark.asyncio
async def test_action_job_builds_request_only_from_loaded_user_step_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    payload = _payload()
    _install_runtime(
        monkeypatch,
        preparation=ActionJobPreparation(context=_context()),
        calls=calls,
    )

    await _run_action_job(payload)

    request = calls["request"]
    assert request.user_id == "user-1"
    assert request.action_id == "action-1"
    assert request.suggestion_id is None
    assert request.user_step_id == "user-step-1"
    assert request.user_step_created_at == "2026-08-16T00:10:00Z"
    assert request.user_message.content == "Perform the work"
    assert request.user_message.language == "ja"
    assert request.user_message.images[0].storage_path == "images/input.png"
    assert request.execution_target.kind == "scratch"
    assert request.approval_resume_session_id is None
    assert calls["prepare"]["payload"] == payload
    assert "mark_started" not in calls


@pytest.mark.asyncio
async def test_action_job_tool_approval_passes_loaded_resume_ids_without_start_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    payload = _payload(tool_approval=True)
    _install_runtime(
        monkeypatch,
        preparation=ActionJobPreparation(context=_context(tool_approval=True)),
        calls=calls,
    )

    await _run_action_job(payload)

    request = calls["request"]
    assert request.approval_resume_session_id == "approval-1"
    assert request.approval_resume_tool_request_id == "tool-request-1"


@pytest.mark.asyncio
async def test_action_job_skip_finalization_supports_action_without_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, object] = {}
    _install_runtime(
        monkeypatch,
        preparation=ActionJobPreparation(
            context=_context(),
            skip_outcome="already_terminal",
        ),
        calls=calls,
    )

    await _run_action_job(_payload())

    command = calls["skip"]
    assert command.user_id == "user-1"
    assert command.action_id == "action-1"
    assert command.suggestion_id is None
    assert command.command_id == "message-1"
    assert command.failure_stage == "start_failed"
    assert "request" not in calls


@pytest.mark.asyncio
async def test_action_job_defers_claim_when_preparation_database_is_locked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    payload = _payload()
    claimed_payload = _claim_job(db_path=db_path, payload=payload)

    class _LockedRepository:
        def __init__(self, *, db_path: Path, busy_timeout_ms: int) -> None:
            assert db_path == tmp_path / "runtime.db"
            assert busy_timeout_ms == 1_000

        def prepare_execution(self, **_kwargs: object) -> ActionJobPreparation:
            raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.read_local_runtime_db_config",
        lambda: (db_path, 1_000),
    )
    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.ActionJobRuntimeRepository",
        _LockedRepository,
    )

    with pytest.raises(DeferredLocalJob):
        await _run_action_job(claimed_payload)

    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, claimed_by, claimed_at FROM jobs WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()

    assert job_row == ("queued", None, None)
    assert process_row == ("enqueued", None)


@pytest.mark.asyncio
async def test_action_job_defers_retryable_execution_failure_without_terminal_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "runtime.db"
    payload = _payload()
    claimed_payload = _claim_job(db_path=db_path, payload=payload)

    terminal_writers: list[_FakeTerminalWriter] = []

    class _Repository:
        def __init__(self, *, db_path: Path, busy_timeout_ms: int) -> None:
            assert db_path == tmp_path / "runtime.db"
            assert busy_timeout_ms == 1_000

        def prepare_execution(self, **_kwargs: object) -> ActionJobPreparation:
            return ActionJobPreparation(context=_context())

    class _TerminalWriter(_FakeTerminalWriter):
        def __init__(self, **kwargs) -> None:  # noqa: ANN003
            super().__init__(**kwargs)
            terminal_writers.append(self)

    class _ActionUseCase:
        async def execute_action_runtime(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            raise sqlite3.OperationalError("database is locked")

    async def _get_action_application_service() -> _ActionUseCase:
        return _ActionUseCase()

    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.read_local_runtime_db_config",
        lambda: (db_path, 1_000),
    )
    monkeypatch.setattr(f"{RUNTIME_MODULE}.ActionJobRuntimeRepository", _Repository)
    monkeypatch.setattr(f"{RUNTIME_MODULE}.ActionJobTerminalWriter", _TerminalWriter)
    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.deps.get_action_application_service",
        _get_action_application_service,
    )

    with pytest.raises(DeferredLocalJob):
        await _run_action_job(claimed_payload)

    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status, claimed_by, claimed_at FROM jobs WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()
        process_row = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()

    assert job_row == ("queued", None, None)
    assert process_row == ("enqueued", None)
    assert len(terminal_writers) == 1
    assert terminal_writers[0].persisted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("assistant", [False, True])
async def test_action_job_defers_terminal_step_event_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assistant: bool,
) -> None:
    db_path = tmp_path / "runtime.db"
    payload = _payload()
    claimed_payload = _claim_job(db_path=db_path, payload=payload)

    def _fail_action_step_append(**_kwargs: object) -> None:
        raise sqlite3.OperationalError("database is locked")

    _install_runtime(
        monkeypatch,
        preparation=ActionJobPreparation(context=_context()),
        calls={},
        runtime_db_path=db_path,
        action_step=(
            ActionAssistantMessageEmission(step_id="step-1", step_number=2)
            if assistant
            else ActionToolStepEmission(
                step_id="step-1",
                step_number=2,
                step_name="tool::read",
                label="Read",
                tool_args={"args": {"path": "src/main.py"}},
                status="success",
                started_at="2026-08-16T01:00:00Z",
                completed_at="2026-08-16T01:00:01Z",
            )
        ),
    )
    monkeypatch.setattr(
        f"{RUNTIME_MODULE}.append_local_action_step_event",
        _fail_action_step_append,
    )

    with pytest.raises(DeferredLocalJob):
        await _run_action_job(claimed_payload)

    with sqlite3.connect(db_path) as connection:
        job_row = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (payload["job_id"],)
        ).fetchone()
        process_row = connection.execute(
            "SELECT status FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
        event_row = connection.execute(
            "SELECT event_name, json_extract(payload_json, '$.step_id'), "
            "json_extract(payload_json, '$.status'), "
            "json_extract(payload_json, '$.subject') FROM process_events "
            "WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
        attempt_row = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()

    assert job_row == ("queued",)
    assert process_row == ("enqueued",)
    assert event_row == (
        "action_step",
        "step-1",
        "success",
        None if assistant else "src/main.py",
    )
    assert attempt_row == ("failed", "ACTION_JOB_OPERATIONAL_RETRY")
