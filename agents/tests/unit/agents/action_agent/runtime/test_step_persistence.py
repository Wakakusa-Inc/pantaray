from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.agents.action_agent.runtime.steps.persistence import (
    ActionStepPersistenceError,
    ActionStepPersistenceRetryPolicy,
    save_action_step_with_retry,
)
from pantaray_agents.schema.repositories.repository import (
    RepositoryErrorKind,
    RepositoryResult,
)


def test_runtime_persists_action_steps_only_through_step_helpers() -> None:
    runtime_root = (
        Path(__file__).parents[5] / "src/pantaray_agents/agents/action_agent/runtime"
    )
    allowed_roots = {runtime_root / "steps"}

    offenders: list[str] = []
    for path in runtime_root.rglob("*.py"):
        if any(path.is_relative_to(allowed_root) for allowed_root in allowed_roots):
            continue
        text = path.read_text(encoding="utf-8")
        if ".repository.save_action_step(" in text:
            offenders.append(str(path.relative_to(runtime_root)))

    assert offenders == []


@pytest.mark.asyncio
async def test_save_action_step_with_retry_does_not_retry_structured_constraint_error() -> (
    None
):
    attempts = 0

    async def _save_once() -> RepositoryResult[dict[str, object]]:
        nonlocal attempts
        attempts += 1
        return RepositoryResult(
            error="CHECK constraint failed: step_number >= 1",
            error_kind=RepositoryErrorKind.CONSTRAINT,
            retryable=False,
        )

    with pytest.raises(ActionStepPersistenceError, match="step_number >= 1"):
        await save_action_step_with_retry(
            save_once=_save_once,
            step_name="supervisor_think",
            step_id="step-1",
            retry_policy=ActionStepPersistenceRetryPolicy(
                max_attempts=3,
                initial_delay_seconds=0.0,
                backoff_multiplier=1.0,
            ),
        )

    assert attempts == 1


@pytest.mark.asyncio
async def test_save_action_step_with_retry_retries_structured_transient_error() -> None:
    attempts = 0

    async def _save_once() -> RepositoryResult[dict[str, object]]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return RepositoryResult(
                error="database is locked",
                error_kind=RepositoryErrorKind.TRANSIENT,
                retryable=True,
            )
        return RepositoryResult(data={"step_id": "step-1"})

    result = await save_action_step_with_retry(
        save_once=_save_once,
        step_name="supervisor_think",
        step_id="step-1",
        retry_policy=ActionStepPersistenceRetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.0,
            backoff_multiplier=1.0,
        ),
    )

    assert result.data == {"step_id": "step-1"}
    assert attempts == 3


@pytest.mark.asyncio
async def test_save_action_step_with_retry_retries_raw_transient_sqlite_exception() -> (
    None
):
    attempts = 0

    async def _save_once() -> RepositoryResult[dict[str, object]]:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        return RepositoryResult(data={"step_id": "step-1"})

    result = await save_action_step_with_retry(
        save_once=_save_once,
        step_name="supervisor_think",
        step_id="step-1",
        retry_policy=ActionStepPersistenceRetryPolicy(
            max_attempts=3,
            initial_delay_seconds=0.0,
            backoff_multiplier=1.0,
        ),
    )

    assert result.data == {"step_id": "step-1"}
    assert attempts == 3


@pytest.mark.asyncio
async def test_save_action_step_with_retry_does_not_retry_unknown_exception() -> None:
    attempts = 0

    async def _save_once() -> RepositoryResult[dict[str, object]]:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("unexpected failure")

    with pytest.raises(ActionStepPersistenceError, match="unexpected failure"):
        await save_action_step_with_retry(
            save_once=_save_once,
            step_name="supervisor_think",
            step_id="step-1",
            retry_policy=ActionStepPersistenceRetryPolicy(
                max_attempts=3,
                initial_delay_seconds=0.0,
                backoff_multiplier=1.0,
            ),
        )

    assert attempts == 1


@pytest.mark.asyncio
async def test_save_action_step_with_retry_rejects_unstructured_repository_result() -> (
    None
):
    attempts = 0

    async def _save_once() -> RepositoryResult[dict[str, object]]:
        nonlocal attempts
        attempts += 1
        return RepositoryResult(error="database is locked")

    with pytest.raises(
        ActionStepPersistenceError,
        match="RepositoryResult must provide structured retry semantics",
    ):
        await save_action_step_with_retry(
            save_once=_save_once,
            step_name="supervisor_think",
            step_id="step-1",
            retry_policy=ActionStepPersistenceRetryPolicy(
                max_attempts=3,
                initial_delay_seconds=0.0,
                backoff_multiplier=1.0,
            ),
        )

    assert attempts == 1
