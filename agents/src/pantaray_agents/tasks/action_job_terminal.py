from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from pantaray_agents.action_status import (
    ACTION_FAILURE_MESSAGE_RUNNING_FAILED,
    ACTION_STATUS_PROCESSING,
    ActionRuntimeStatus,
    ActionTerminalStatus,
    build_finalize_action_terminal_command,
    derive_action_terminal_failure,
    is_action_terminal_status,
)
from pantaray_agents.local_runtime.runtime.action_subagent_parent_lifecycle import (
    ActionChildSettlementPendingError,
)
from pantaray_agents.local_runtime.runtime.action_terminal_repository import (
    InvalidActionMemoryDraftError,
)
from pantaray_agents.orchestration.common.types import JSONValue
from pantaray_agents.schema.agent.action import (
    ActionRunResult,
    RuntimeStateCheckpointPayload,
)

from .action_job_support import (
    ACTION_FAILURE_CODE_PERSIST_TERMINAL_PAYLOAD_INVALID,
    ACTION_FAILURE_STAGE_PERSIST_FINAL_STATE_FAILED,
    is_retryable_terminal_persistence_error,
    terminal_persistence_failure_code,
    terminal_retry_delay_seconds,
)

logger = logging.getLogger(__name__)
type ActionEventPayload = dict[str, JSONValue]


@dataclass(slots=True)
class ActionJobTerminalState:
    terminal_written: bool = False
    terminal_status: ActionRuntimeStatus | None = None
    terminal_completed_at: str | None = None
    last_fatal_error_code: str | None = None


@dataclass(slots=True)
class ActionJobTerminalWriter:
    db_path: object
    busy_timeout_ms: int
    job_id: str
    process_id: str
    user_id: str
    suggestion_id: str | None
    action_id: str
    command_id: str
    accepted_at: str
    state: ActionJobTerminalState
    mark_local_action_job_paused: object
    persist_terminal_action_status_strict: Callable[..., Awaitable[object]]

    async def write_pause_terminal(
        self,
        *,
        completed_at: str,
        approval_blockers: list[ActionEventPayload],
    ) -> bool:
        """Park this run on its approval anchor, or report a Stop fence winning."""

        if self.state.terminal_written:
            return True
        if not approval_blockers:
            raise RuntimeError("process pause requires at least one approval blocker")
        payload: ActionEventPayload = {
            "action_id": self.action_id,
            "user_id": self.user_id,
            "status": ACTION_STATUS_PROCESSING,
            "completed_at": str(completed_at),
            "reason": "approval_pending",
            "approval_blockers": approval_blockers,
        }
        if self.suggestion_id is not None:
            payload["suggestion_id"] = self.suggestion_id
        parked = self.mark_local_action_job_paused(
            db_path=self.db_path,
            busy_timeout_ms=self.busy_timeout_ms,
            job_id=self.job_id,
            process_id=self.process_id,
            payload=payload,
        )
        if parked is None:
            return False
        self.state.terminal_written = True
        self.state.terminal_status = ACTION_STATUS_PROCESSING
        self.state.terminal_completed_at = str(completed_at)
        return True

    async def persist_terminal_until_success(
        self,
        *,
        requested_status: ActionTerminalStatus,
        completed_at: str,
        reason: str,
        runtime_state_checkpoint: RuntimeStateCheckpointPayload | None,
        run_result: ActionRunResult | None = None,
    ) -> ActionTerminalStatus:
        consecutive_failures = 0
        process_completed_event_id = str(uuid.uuid4())
        current_error_code = (
            str(self.state.last_fatal_error_code)
            if requested_status == "error" and self.state.last_fatal_error_code
            else None
        )
        persisted_final_output = (
            str(run_result.final_output).strip()
            if run_result is not None
            and requested_status == "success"
            and str(run_result.final_output).strip()
            else None
        )
        if not is_action_terminal_status(requested_status):
            raise RuntimeError(
                f"Unsupported terminal action_status: {requested_status!r}"
            )
        derived_failure = derive_action_terminal_failure(requested_status)
        failure_stage = (
            derived_failure.failure_stage if derived_failure is not None else None
        )
        failure_message_public = (
            derived_failure.failure_message_public
            if derived_failure is not None
            else None
        )
        if current_error_code is None and derived_failure is not None:
            current_error_code = derived_failure.failure_code
        if run_result is not None:
            if run_result.action_failure_code is not None:
                current_error_code = str(run_result.action_failure_code)
            if run_result.failure_stage is not None:
                failure_stage = str(run_result.failure_stage)
            if run_result.failure_message_public is not None:
                failure_message_public = str(run_result.failure_message_public)
        command = build_finalize_action_terminal_command(
            process_completed_event_id=process_completed_event_id,
            user_id=self.user_id,
            suggestion_id=self.suggestion_id,
            accepted_at=self.accepted_at,
            command_id=self.command_id,
            process_id=self.process_id,
            action_id=self.action_id,
            completed_at=str(completed_at),
            action_status=requested_status,
            failure_code=current_error_code,
            error_payload=(
                dict(error_payload)
                if run_result is not None
                and isinstance(
                    (error_payload := getattr(run_result, "error_payload", None)),
                    dict,
                )
                else None
            ),
            final_output=persisted_final_output,
            memory_draft_json=(
                run_result.memory_draft.model_dump_json()
                if run_result is not None and run_result.memory_draft is not None
                else None
            ),
            failure_stage=failure_stage,
            failure_message_public=failure_message_public,
            final_prompt_text=(
                run_result.final_prompt_text if run_result is not None else None
            ),
            prompt_name=run_result.prompt_name if run_result is not None else None,
            prompt_version=(
                run_result.prompt_version if run_result is not None else None
            ),
            total_steps=run_result.total_steps if run_result is not None else None,
            total_llm_steps=(
                run_result.total_llm_steps if run_result is not None else None
            ),
            total_tool_steps=(
                run_result.total_tool_steps if run_result is not None else None
            ),
            total_prompt_tokens=(
                run_result.total_prompt_tokens if run_result is not None else None
            ),
            total_completion_tokens=(
                run_result.total_completion_tokens if run_result is not None else None
            ),
        )
        while True:
            try:
                persisted_result = await self.persist_terminal_action_status_strict(
                    command=command,
                    job_id=self.job_id,
                    runtime_state_checkpoint=runtime_state_checkpoint,
                )
                self.state.terminal_written = True
                self.state.terminal_status = persisted_result.action_status
                self.state.terminal_completed_at = str(completed_at)
                return persisted_result.action_status
            except ActionChildSettlementPendingError:
                # The barrier already committed the child cancel requests; wait
                # for their own workers to reach a safe terminal boundary.
                consecutive_failures += 1
                settlement_delay_seconds = terminal_retry_delay_seconds(
                    consecutive_failures=consecutive_failures
                )
                logger.info(
                    "Action job terminal is waiting for child settlement: process_id=%s action_id=%s "
                    "requested_status=%s reason=%s retry_delay_seconds=%.1f",
                    self.process_id,
                    self.action_id,
                    requested_status,
                    reason,
                    settlement_delay_seconds,
                )
                await asyncio.sleep(settlement_delay_seconds)
            except InvalidActionMemoryDraftError:
                self.state.last_fatal_error_code = (
                    ACTION_FAILURE_CODE_PERSIST_TERMINAL_PAYLOAD_INVALID
                )
                command = replace(
                    command,
                    action_status="error",
                    failure_code=ACTION_FAILURE_CODE_PERSIST_TERMINAL_PAYLOAD_INVALID,
                    error_payload=None,
                    final_output=None,
                    memory_draft_json=None,
                    failure_stage=ACTION_FAILURE_STAGE_PERSIST_FINAL_STATE_FAILED,
                    failure_message_public=ACTION_FAILURE_MESSAGE_RUNNING_FAILED,
                )
            except Exception as exc:  # noqa: BLE001
                if not is_retryable_terminal_persistence_error(exc):
                    self.state.last_fatal_error_code = (
                        terminal_persistence_failure_code(exc)
                    )
                    logger.error(
                        "Action job terminal persistence failed without retry: process_id=%s action_id=%s "
                        "requested_status=%s reason=%s error=%s",
                        self.process_id,
                        self.action_id,
                        requested_status,
                        reason,
                        exc,
                    )
                    raise
                consecutive_failures += 1
                delay_seconds = terminal_retry_delay_seconds(
                    consecutive_failures=consecutive_failures
                )
                logger.warning(
                    "Action job terminal persistence failed; retrying: process_id=%s action_id=%s "
                    "requested_status=%s reason=%s consecutive_failures=%s retry_delay_seconds=%.1f error=%s",
                    self.process_id,
                    self.action_id,
                    requested_status,
                    reason,
                    consecutive_failures,
                    delay_seconds,
                    exc,
                )
                await asyncio.sleep(delay_seconds)
