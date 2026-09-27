from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import pantaray_agents.dependencies as deps
from pantaray_agents.local_runtime.context.source_control import context_source_control
from pantaray_agents.local_runtime.context.source_gate import SourceInvalidated
from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.local_runtime.runtime.job_route_identity import (
    require_current_route_identity,
)
from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_artifact_root,
)
from pantaray_agents.local_runtime.runtime.suggestion_from_insight import (
    capture_paused_for_user,
    read_reconsidered_insight,
    reserve_suggestion_start,
)
from pantaray_agents.local_runtime.tooling.repository.workspace_context import (
    build_workspace_context_prompt,
)
from pantaray_agents.local_runtime.tooling.repository.workspace_settings import (
    list_workspace_settings,
)
from pantaray_agents.local_runtime.tooling.suggestion_research import (
    InsightActivityStart,
    build_suggestion_research_snapshot,
)
from pantaray_agents.schema.agent.suggestion import SuggestionAgentRequest
from pantaray_agents.schema.repository_errors import repository_data_or_raise
from pantaray_agents.tasks.job_retry import (
    defer_local_job_if_retryable,
    defer_local_job_transition_with_retry,
)
from pantaray_agents.tasks.types import SuggestionJobRuntimePayload

logger = logging.getLogger(__name__)

_SUGGESTION_TERMINAL_STATUSES = frozenset({"success", "error", "timeout", "canceled"})


async def _finalize_suggestion_start_error(
    *,
    repository,
    user_id: str,
    suggestion_id: str,
    error_code: str,
    error_message: str,
    exception_type: str,
) -> None:
    result = await repository.finalize_suggestion_start_error_if_processing(
        user_id=user_id,
        suggestion_id=suggestion_id,
        error_code=error_code,
        error_message=error_message,
        error_details={"exception_type": exception_type},
        metadata={"stage": "local_suggestion_worker"},
    )
    if result.error:
        raise RuntimeError(result.error)


async def _drop_if_capture_paused(
    *,
    repository,
    db_path: Path,
    busy_timeout_ms: int,
    payload: SuggestionJobRuntimePayload,
) -> bool:
    """Whether recording is off, ending this job's row when it is.

    Turning recording off stops new Suggestions. This job is the one path that
    could still make one out of the tail recorded before the toggle, so it
    produces nothing. The row the enqueueing transaction created is ended as
    canceled rather than left `processing`, which the suggestion route reports
    as a stream still in progress.

    Callers keep both the read and the cancel inside a block that defers, so a
    locked database retries the job instead of failing it for good.
    """
    if not capture_paused_for_user(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        user_id=payload["user_id"],
    ):
        return False
    logger.info(
        "Dropping Suggestion job %s because activity recording is paused",
        payload["job_id"],
    )
    result = await repository.cancel_suggestion_if_processing(
        user_id=payload["user_id"],
        suggestion_id=payload["suggestion_id"],
    )
    if result.error:
        raise RuntimeError(result.error)
    return True


async def _persist_terminal_response(
    *,
    repository,
    agent,
    response,
) -> None:
    payload = agent.build_persistence_payload(response)
    result = await repository.save_suggestion(
        response,
        prompt_name=payload["prompt_name"],
        prompt_version=payload["prompt_version"],
        prompt_text=payload["prompt_text"],
        response_text=payload["response_text"],
        request_images_count=payload["request_images_count"],
        used_images_count=payload["used_images_count"],
    )
    if result.error:
        raise RuntimeError(result.error)


async def _insight_activity_start(
    *, user_id: str, cursor: str | None
) -> InsightActivityStart | None:
    """The permit to read activity after this Insight, or None when there is none.

    An Insight stored before its cursor was recorded has no start, so this run
    reads no activity rather than reading from a later Insight's position.
    """
    if cursor is None:
        return None
    gate = context_source_control.gate
    async with gate.turn():
        source = gate.current(user_id)
    return (
        None if source is None else InsightActivityStart(source=source, cursor=cursor)
    )


async def _process_while_readable(
    *,
    agent,
    request: SuggestionAgentRequest,
    activity_start: InsightActivityStart | None,
):
    """Run the agent, or return None when the activity permit was revoked meanwhile.

    As in the short Insight, a run that can read raw activity runs under
    `SourceGate.track`: revoking the permit cancels it, model calls and run-step
    writes included, and nothing it produced is published.
    """
    if activity_start is None:
        return await agent.process(request)
    gate = context_source_control.gate
    source = activity_start.source
    try:
        async with gate.track(source):
            return await agent.process(request)
    except asyncio.CancelledError:
        # `SourceGate.revoke` drops the permit before it cancels this task; a
        # permit that still matches means the job itself was cancelled.
        if gate.current(source.binding.user_id) == source:
            raise
        task = asyncio.current_task()
        assert task is not None  # A coroutine driven by asyncio.run runs in a Task.
        task.uncancel()
        return None
    except SourceInvalidated:
        return None


async def _publish_while_readable(
    *, repository, agent, response, activity_start: InsightActivityStart | None
) -> bool:
    """Persist the response; False when the permit the run read under is gone."""
    if activity_start is None:
        await _persist_terminal_response(
            repository=repository, agent=agent, response=response
        )
        return True
    try:
        async with context_source_control.gate.guard(activity_start.source):
            await _persist_terminal_response(
                repository=repository, agent=agent, response=response
            )
    except SourceInvalidated:
        return False
    return True


async def _resolve_ui_language(user_id: str) -> str | None:
    repository = await deps.get_user_settings_repository()
    return repository_data_or_raise(
        await repository.get_ui_language(user_id),
        safe_message="failed to resolve the UI language",
    )


async def _run_suggestion_job(payload: SuggestionJobRuntimePayload) -> None:
    repository = await deps.get_suggestion_repository()
    db_path, timeout_ms = read_local_runtime_db_config()
    try:
        existing = repository_data_or_raise(
            await repository.get_suggestion(
                user_id=payload["user_id"],
                suggestion_id=payload["suggestion_id"],
            ),
            safe_message="failed to check existing Suggestion",
        )
        if existing:
            status = str(existing.get("status") or "").strip().lower()
            if status in _SUGGESTION_TERMINAL_STATUSES:
                return
        # Recording turned off after this job was queued.
        if await _drop_if_capture_paused(
            repository=repository,
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            payload=payload,
        ):
            return
        insight = read_reconsidered_insight(
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            user_id=payload["user_id"],
            insight_id=payload["insight_id"],
        )
        activity_start = await _insight_activity_start(
            user_id=payload["user_id"], cursor=insight.source_cursor
        )
        workspace_settings = list_workspace_settings(
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            user_id=payload["user_id"],
        )
        workspace_context_prompt = build_workspace_context_prompt(workspace_settings)
        research_snapshot = build_suggestion_research_snapshot(
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            artifact_root=read_local_runtime_artifact_root(),
            user_id=payload["user_id"],
            workspace_settings=workspace_settings,
        )
        request = SuggestionAgentRequest(
            user_id=payload["user_id"],
            suggestion_id=payload["suggestion_id"],
            short_term_insight=insight.short_term_insight,
            reconsideration_reason=insight.reconsideration_reason,
            language=await _resolve_ui_language(payload["user_id"]),
            workspace_context_prompt=workspace_context_prompt or None,
        )
    except Exception as exc:
        await defer_local_job_if_retryable(
            exc=exc,
            job_id=payload["job_id"],
            process_id=payload["process_id"],
            process_pending_status="enqueued",
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
        )
        await _finalize_suggestion_start_error(
            repository=repository,
            user_id=payload["user_id"],
            suggestion_id=payload["suggestion_id"],
            error_code="SUGGESTION_PREFLIGHT_FAILED",
            error_message="Suggestion worker failed before execution.",
            exception_type=exc.__class__.__name__,
        )
        raise

    try:
        agent = await deps.get_suggestion_agent(
            research_snapshot=research_snapshot,
            activity_start=activity_start,
        )
        decision = reserve_suggestion_start(
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            user_id=payload["user_id"],
            job_id=payload["job_id"],
            process_id=payload["process_id"],
            now=datetime.now(UTC),
        )
        if decision == "superseded":
            canceled = await repository.cancel_suggestion_if_processing(
                user_id=payload["user_id"],
                suggestion_id=payload["suggestion_id"],
            )
            if canceled.error:
                raise RuntimeError(canceled.error)
            return
        if isinstance(decision, datetime):
            await defer_local_job_transition_with_retry(
                job_id=payload["job_id"],
                process_id=payload["process_id"],
                process_pending_status="enqueued",
                db_path=db_path,
                busy_timeout_ms=timeout_ms,
                scheduled_at=decision.isoformat().replace("+00:00", "Z"),
            )
        response = await _process_while_readable(
            agent=agent, request=request, activity_start=activity_start
        )
    except Exception as exc:
        await defer_local_job_if_retryable(
            exc=exc,
            job_id=payload["job_id"],
            process_id=payload["process_id"],
            process_pending_status="enqueued",
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
        )
        await _finalize_suggestion_start_error(
            repository=repository,
            user_id=payload["user_id"],
            suggestion_id=payload["suggestion_id"],
            error_code="SUGGESTION_WORKER_FAILED",
            error_message="Suggestion worker failed before terminal persistence.",
            exception_type=exc.__class__.__name__,
        )
        raise

    try:
        # Recording can be turned off while the agent runs, which the preflight
        # gate above cannot see. The same gate decides once more here, immediately
        # before the only persistence this job performs, so a Suggestion generated
        # after the toggle is dropped instead of stored.
        if await _drop_if_capture_paused(
            repository=repository,
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
            payload=payload,
        ):
            return
        # The same reasoning for the route: the Suggestion row is the only
        # thing this job publishes, and it belongs to whoever the run started
        # for, on the account the answer was inferred on.
        await require_current_route_identity()
        if response is not None and await _publish_while_readable(
            repository=repository,
            agent=agent,
            response=response,
            activity_start=activity_start,
        ):
            return
        logger.info(
            "Dropping Suggestion job %s because activity access was revoked",
            payload["job_id"],
        )
        canceled = await repository.cancel_suggestion_if_processing(
            user_id=payload["user_id"],
            suggestion_id=payload["suggestion_id"],
        )
        if canceled.error:
            raise RuntimeError(canceled.error)
    except Exception as exc:
        await defer_local_job_if_retryable(
            exc=exc,
            job_id=payload["job_id"],
            process_id=payload["process_id"],
            process_pending_status="enqueued",
            db_path=db_path,
            busy_timeout_ms=timeout_ms,
        )
        await _finalize_suggestion_start_error(
            repository=repository,
            user_id=payload["user_id"],
            suggestion_id=payload["suggestion_id"],
            error_code="SUGGESTION_WORKER_FAILED",
            error_message="Suggestion worker failed before terminal persistence.",
            exception_type=exc.__class__.__name__,
        )
        raise


def run_suggestion_job(payload: SuggestionJobRuntimePayload) -> None:
    asyncio.run(_run_suggestion_job(payload))
