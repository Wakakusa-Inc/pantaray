"""Session resume / replay responsibilities for orchestration WS."""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from typing import Literal

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.orchestration.ws.action_relay import ACTION_EVENT_CURSOR_START_ID
from pantaray_agents.orchestration.ws.action_relay_authority import (
    ActionRelayAuthorityError,
    load_action_relay_authority,
)
from pantaray_agents.orchestration.ws.error_meta import (
    build_session_error_meta,
)
from pantaray_agents.orchestration.ws.session_resume_helpers import (
    resolve_action_start_after_cursor,
)
from pantaray_agents.schema.agent.base import ErrorSeverity, ErrorType
from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket.server_messages import (
    SessionExpiredMessage,
    SessionResumedMessage,
)
from pantaray_agents.utils.metrics import (
    record_action_replay_live_attach_failed,
    record_ws_dependency_fail,
    record_ws_resume_expired,
    record_ws_resume_requested,
    record_ws_resume_succeeded,
)
from pantaray_agents.utils.public_error import public_ws_error
from pantaray_agents.utils.ws_observability import now_monotonic_seconds

logger = logging.getLogger(__name__)

WS_RESUME_MAX_ATTEMPTS_PER_PROCESS = 3
WS_RESUME_ATTEMPT_WINDOW_SECONDS = 60.0
ResumeSessionKind = Literal["suggestion", "action"]


class SessionResumeMixin:
    """Action replay and session resume responsibilities."""

    def _allow_resume_attempt(self, *, process_id: str) -> bool:
        now = now_monotonic_seconds()
        dq = self._resume_attempts.setdefault(process_id, deque())
        cutoff = now - float(WS_RESUME_ATTEMPT_WINDOW_SECONDS)
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= int(WS_RESUME_MAX_ATTEMPTS_PER_PROCESS):
            return False
        dq.append(now)
        return True

    def _resolve_action_start_after_cursor(
        self,
        *,
        process_id: str,
        last_cursor: str | None,
    ) -> int | None:
        return resolve_action_start_after_cursor(
            process_id=process_id,
            last_cursor=last_cursor,
        )

    async def _send_action_resume_expired(self) -> None:
        record_ws_resume_expired("action", reason="resume_data_unavailable")
        await self.send_event(
            OutboundEvent.SESSION_EXPIRED.value,
            SessionExpiredMessage(
                reason="resume_data_unavailable",
                max_session_age_seconds=self._session_max_age_seconds,
            ),
        )

    async def _send_action_resume_local_state_error(
        self,
        *,
        process_id: str,
        stage: str,
        operation: str,
        error_message: str,
    ) -> None:
        record_ws_dependency_fail(dependency="local_state", operation=operation)
        await self.send_error(
            public_ws_error(
                error_code="WS_DEPENDENCY_UNAVAILABLE",
                request_id=self.session_id,
                error_type=ErrorType.INTERNAL_ERROR,
                severity=ErrorSeverity.ERROR,
                error_message=error_message,
                extra_error_details={"dependency": "local_state"},
            ),
            process_id=process_id,
            meta=build_session_error_meta(
                stage=stage,
                error_code="WS_DEPENDENCY_UNAVAILABLE",
                process_id=process_id,
            ),
        )

    async def resume_session(
        self,
        session_id: str,
        process_id: str,
        last_cursor: str | None,
        last_chunk_index: int | None,
        kind: ResumeSessionKind,
        *,
        suggestion_id: str | None = None,
        action_id: str | None = None,
        command_id: str | None = None,
    ) -> None:
        process_id_norm = str(process_id)
        if not self._allow_resume_attempt(process_id=process_id_norm):
            await self.send_error(
                public_ws_error(
                    error_code="WS_RESUME_RETRY_LIMIT_EXCEEDED",
                    request_id=self.session_id,
                    error_type=ErrorType.VALIDATION_ERROR,
                    severity=ErrorSeverity.ERROR,
                    error_message="resume_session retry limit exceeded",
                ),
                process_id=process_id_norm,
                meta=build_session_error_meta(
                    stage="resume_retry_limit_exceeded",
                    error_code="WS_RESUME_RETRY_LIMIT_EXCEEDED",
                    process_id=process_id_norm,
                ),
            )
            return

        if action_id is None:
            if kind == "action":
                record_ws_resume_requested("action")
                await self._send_action_resume_expired()
                return
            await super().resume_session(
                session_id,
                process_id_norm,
                last_cursor,
                last_chunk_index,
                "suggestion",
            )
            return

        record_ws_resume_requested("action")
        try:
            authority = load_action_relay_authority(
                user_id=str(self.user_id),
                action_id=str(action_id),
                process_id=process_id_norm,
            )
        except ActionRelayAuthorityError:
            await self._send_action_resume_expired()
            return
        except (MigrationError, sqlite3.Error, OSError) as exc:
            if self._rate_limiter.should_log(
                "ws_resume:load_action_authority", interval_seconds=60.0
            ):
                logger.warning(
                    "resume_session: Action authority read failed. session_id=%s process_id=%s error=%s",
                    self.session_id,
                    process_id_norm,
                    exc,
                    exc_info=True,
                )
            await self._send_action_resume_local_state_error(
                process_id=process_id_norm,
                stage="resume_load_authority_failed",
                operation="load_authority",
                error_message="Failed to load Action resume authority from local storage.",
            )
            return

        try:
            client_cursor = self._resolve_action_start_after_cursor(
                process_id=process_id_norm,
                last_cursor=last_cursor,
            )
        except (MigrationError, sqlite3.Error, OSError) as exc:
            if self._rate_limiter.should_log(
                "ws_resume:resolve_action_cursor", interval_seconds=60.0
            ):
                logger.warning(
                    "resume_session: Action cursor resolution failed. session_id=%s process_id=%s error=%s",
                    self.session_id,
                    process_id_norm,
                    exc,
                    exc_info=True,
                )
            await self._send_action_resume_local_state_error(
                process_id=process_id_norm,
                stage="resume_cursor_resolution_failed",
                operation="resolve_cursor",
                error_message="Failed to resolve Action resume cursor from local storage.",
            )
            return
        if client_cursor is None:
            await self._send_action_resume_expired()
            return

        terminal = authority.terminal_cursor is not None
        if terminal:
            start_event_id = ACTION_EVENT_CURSOR_START_ID
            start_after_cursor = authority.terminal_cursor - 1
        else:
            start_event_id = str(last_cursor or ACTION_EVENT_CURSOR_START_ID)
            start_after_cursor = client_cursor
        try:
            forwarder_task = await self._attach_action_process_to_current_session(
                process_id=authority.process_id,
                logical_run_id=authority.root_process_id,
                suggestion_id=authority.suggestion_id,
                action_id=authority.action_id,
                command_id=authority.command_id,
                start_event_id=start_event_id,
                start_after_cursor=start_after_cursor,
            )
            if terminal:
                if forwarder_task is None:
                    raise RuntimeError("Action terminal relay task was not started")
                await forwarder_task
                if authority.process_id in self._action_processes:
                    raise RuntimeError("Action terminal relay did not complete")
        except Exception as exc:
            await self._release_action_start_resources(process_id=authority.process_id)
            record_ws_dependency_fail(
                dependency="ws_handler", operation="attach_action"
            )
            record_action_replay_live_attach_failed(
                path="resume_session", reason="attach_failed"
            )
            if self._rate_limiter.should_log(
                "ws_resume:attach_action", interval_seconds=60.0
            ):
                logger.warning(
                    "resume_session: attach_action_process failed. session_id=%s process_id=%s error=%s",
                    self.session_id,
                    process_id_norm,
                    exc,
                    exc_info=True,
                )
            await self._send_live_attach_error(
                error_code="ACTION_RELAY_ATTACH_FAILED",
            )
            return

        if terminal:
            return

        record_ws_resume_succeeded("action", missing_chunks_count=0)
        await self.send_event(
            OutboundEvent.SESSION_RESUMED.value,
            SessionResumedMessage(resumed_from_chunk=0, missing_chunks=[]),
        )
