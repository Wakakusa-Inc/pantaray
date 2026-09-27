from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..models import StoredToolRuntimeResource, ToolRuntimeResourceStatus
from .cleanup import CleanupFailure
from .resource_cleanup import resource_cleanup_attempts_exhausted
from .resource_transition_store import (
    ToolRuntimeResourceEventInput,
    persist_tool_runtime_resource_transition,
)

CleanupPersistedStatus = ToolRuntimeResourceStatus | Literal["unchanged"]
CleanupFailureStatus = Literal["cleanup_failed", "abandoned"]


@dataclass(frozen=True, slots=True)
class CleanupPersistenceResult:
    resource_status_after_persistence: CleanupPersistedStatus


class CleanupPersistenceError(CleanupFailure):
    def __init__(
        self,
        message: str,
        *,
        resource_status_after_persistence: CleanupPersistedStatus,
    ) -> None:
        super().__init__(message)
        self.resource_status_after_persistence = resource_status_after_persistence


def persist_action_cleanup_success(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
    cleaned_at: str,
) -> CleanupPersistenceResult:
    resource_status_after_persistence: CleanupPersistedStatus = "unchanged"
    try:
        transition = persist_tool_runtime_resource_transition(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
            status="cleaned",
            timestamp=cleaned_at,
            cleanup_error=None,
            event=ToolRuntimeResourceEventInput(
                event_type="action_cancel_post_cleanup_completed",
                message=(
                    f"{resource.resource_kind}: "
                    "post-terminal action cancel cleanup completed"
                ),
                tool_invocation_id=resource.tool_invocation_id,
            ),
        )
        resource_status_after_persistence = transition.current_resource.status
        if not transition.applied and resource_status_after_persistence != "cleaned":
            raise CleanupPersistenceError(
                "resource changed during cleanup success persistence: "
                f"{resource.resource_id}",
                resource_status_after_persistence=resource_status_after_persistence,
            )
    except Exception as exc:  # noqa: BLE001
        raise CleanupPersistenceError(
            "failed to persist post-terminal cleanup success for resource "
            f"{resource.resource_id}",
            resource_status_after_persistence=resource_status_after_persistence,
        ) from exc
    return CleanupPersistenceResult(
        resource_status_after_persistence=resource_status_after_persistence
    )


def persist_action_cleanup_failure(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
    failed_at: str,
    cleanup_error: str,
) -> CleanupPersistenceResult:
    resource_status_after_persistence: CleanupPersistedStatus = "unchanged"
    try:
        if resource_cleanup_attempts_exhausted(resource):
            transition_status: CleanupFailureStatus = "abandoned"
            event_type = "action_cancel_post_cleanup_abandoned"
            message = (
                f"{resource.resource_kind}: "
                f"post-terminal action cancel cleanup abandoned after retry budget: {cleanup_error}"
            )
        else:
            transition_status = "cleanup_failed"
            event_type = "action_cancel_post_cleanup_warning"
            message = (
                f"{resource.resource_kind}: "
                f"post-terminal action cancel cleanup failed: {cleanup_error}"
            )
        transition = persist_tool_runtime_resource_transition(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
            status=transition_status,
            timestamp=failed_at,
            cleanup_error=cleanup_error,
            event=ToolRuntimeResourceEventInput(
                event_type=event_type,
                message=message,
                tool_invocation_id=resource.tool_invocation_id,
            ),
        )
        resource_status_after_persistence = transition.current_resource.status
        if not transition.applied and resource_status_after_persistence == "active":
            raise CleanupPersistenceError(
                "resource changed during cleanup failure persistence: "
                f"{resource.resource_id}",
                resource_status_after_persistence=resource_status_after_persistence,
            )
    except Exception as exc:  # noqa: BLE001
        raise CleanupPersistenceError(
            "failed to persist post-terminal cleanup failure for resource "
            f"{resource.resource_id}",
            resource_status_after_persistence=resource_status_after_persistence,
        ) from exc
    return CleanupPersistenceResult(
        resource_status_after_persistence=resource_status_after_persistence
    )


__all__ = [
    "CleanupPersistenceError",
    "CleanupPersistenceResult",
    "persist_action_cleanup_failure",
    "persist_action_cleanup_success",
]
