"""ActionAgent cancellation service."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from pantaray_agents.agents.action_agent.runtime.log_safety import exception_type_name
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
from pantaray_agents.agents.action_agent.runtime.state.updates import (
    append_state_error,
    set_status_with_updated_at,
)
from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.local_runtime.runtime.db_execution_context import (
    resolve_local_runtime_db_config,
)
from pantaray_agents.repositories.runtime_ports import ActionRepositoryPort
from pantaray_agents.schema.agent.base import AgentError, StatusType
from pantaray_agents.utils.strict_numbers import is_strict_int
from pantaray_agents.utils.trace_context import get_trace_context

type ErrorBuilder = Callable[..., AgentError]


@dataclass(frozen=True)
class CancellationDeps:
    """Dependencies required by the cancellation service."""

    repository: ActionRepositoryPort
    logger: logging.Logger
    now_provider: Callable[[], str]
    build_agent_error: ErrorBuilder


class ActionCancellationService:
    """DB 上の action 状態を参照して self-stop 判定を行う service。"""

    def __init__(self, deps: CancellationDeps) -> None:
        self._deps = deps

    async def check_cancellation(self, state: ActionAgentState) -> bool:
        action_id = state.get("action_id")
        if not action_id:
            return False

        max_failures = _read_positive_int_from_state(
            state=state,
            key="cancel_check_max_consecutive_failures",
        )
        grace_seconds = _read_positive_int_from_state(
            state=state,
            key="cancel_check_failure_grace_seconds",
        )
        now_iso = self._deps.now_provider()

        def record_failure(reason: str) -> bool:
            return self._record_failure(
                state=state,
                now_iso=now_iso,
                action_id=str(action_id),
                max_failures=max_failures,
                grace_seconds=grace_seconds,
                reason=reason,
            )

        try:
            result = await self._deps.repository.get_action(
                user_id=str(state.get("user_id") or ""),
                action_id=str(action_id),
            )
        except Exception as exc:  # noqa: BLE001
            self._deps.logger.warning(
                "Failed to check action cancellation: action_id=%s exception_type=%s",
                action_id,
                exception_type_name(exc),
            )
            return record_failure(str(exc))

        if result.error or not result.data:
            return record_failure(str(result.error or "empty data"))

        raw_status = result.data.get("status")
        status_str = (
            raw_status.value
            if isinstance(raw_status, StatusType)
            else str(raw_status or "")
        )
        if status_str != "canceled":
            # An external Stop that still owns a live subagent child fences the
            # job instead of terminalizing the Action, so the fence — not the
            # projected Action status — is what stops this run. A canceled
            # Action is already decided and never depends on this read.
            try:
                stop_fence_recorded = _stop_fence_is_recorded(
                    user_id=str(state.get("user_id") or ""),
                    action_id=str(action_id),
                )
            except Exception as exc:  # noqa: BLE001
                self._deps.logger.warning(
                    "Failed to read the Action Stop fence: "
                    "action_id=%s exception_type=%s",
                    action_id,
                    exception_type_name(exc),
                )
                return record_failure(str(exc))
            if not stop_fence_recorded:
                _reset_failure_tracking(state)
                return False

        set_status_with_updated_at(state, status="canceled", updated_at=now_iso)
        state["next_action"] = None
        _reset_failure_tracking(state)
        return True

    def _record_failure(
        self,
        *,
        state: ActionAgentState,
        now_iso: str,
        action_id: str,
        max_failures: int,
        grace_seconds: int,
        reason: str,
    ) -> bool:
        failures = int(state.get("cancel_check_consecutive_failures", 0) or 0) + 1
        state["cancel_check_consecutive_failures"] = failures
        state["cancel_check_last_failure_at"] = now_iso

        first_failed_at = str(state.get("cancel_check_first_failure_at") or "")
        if not first_failed_at:
            state["cancel_check_first_failure_at"] = now_iso
            first_failed_at = now_iso

        elapsed_seconds = _elapsed_seconds(
            first_failed_at=first_failed_at,
            current_time_iso=now_iso,
        )
        if failures < max_failures or elapsed_seconds < float(grace_seconds):
            return False

        error = self._deps.build_agent_error(
            error_type="repository_error",
            error_code="ACTION_CANCEL_CHECK_UNAVAILABLE",
            error_message=(
                "Failed to check cancellation status repeatedly; aborting to avoid runaway."
            ),
            error_details={
                "action_id": action_id,
                "consecutive_failures": failures,
                "grace_seconds": grace_seconds,
                "elapsed_seconds": elapsed_seconds,
                "last_failure_reason": reason,
            },
        )
        append_state_error(state, error=error, updated_at=now_iso)
        set_status_with_updated_at(state, status="error", updated_at=now_iso)
        state["final_output"] = ""
        state["next_action"] = None
        return True


def _stop_fence_is_recorded(*, user_id: str, action_id: str) -> bool:
    """Read the Stop fence of the local runtime job this run is executing.

    A run outside the local runtime worker has no job identity to fence, so it
    keeps observing the projected Action status alone.
    """

    trace = get_trace_context()
    job_id = trace.local_job_id if trace is not None else None
    if not job_id:
        return False
    # Deferred: the Action terminal boundary reaches back into this package, so
    # importing the fence reader at module scope would be circular.
    from pantaray_agents.local_runtime.runtime.action_cancel_repository import (
        action_stop_fence_is_recorded,
    )

    db_path, busy_timeout_ms = resolve_local_runtime_db_config(
        fallback=read_local_runtime_db_config
    )
    return action_stop_fence_is_recorded(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        user_id=user_id,
        action_id=action_id,
        job_id=job_id,
    )


def _read_positive_int_from_state(
    *,
    state: ActionAgentState,
    key: str,
) -> int:
    raw = state.get(key)
    if not is_strict_int(raw) or raw <= 0:
        raise RuntimeError(
            "Action cancellation policy state invariant violated: "
            f"{key} must be a positive integer."
        )
    return raw


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_seconds(*, first_failed_at: str, current_time_iso: str) -> float:
    first_dt = _parse_iso(first_failed_at) or _parse_iso(current_time_iso)
    now_dt = _parse_iso(current_time_iso)
    if first_dt is None or now_dt is None:
        return 0.0
    return max(0.0, (now_dt - first_dt).total_seconds())


def _reset_failure_tracking(state: ActionAgentState) -> None:
    state.pop("cancel_check_consecutive_failures", None)
    state.pop("cancel_check_first_failure_at", None)
    state.pop("cancel_check_last_failure_at", None)
