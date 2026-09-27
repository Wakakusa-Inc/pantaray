from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from ..models import StoredToolRuntimeResource
from ..resources.resource_cleanup import (
    cleanup_runtime_resource,
    resource_cleanup_attempts_exhausted,
)
from ..resources.resource_repository import (
    mark_tool_runtime_resource_cleaned,
)
from ..resources.resource_tracking import register_workspace_lock_resource
from ..resources.resource_transition_store import (
    ToolRuntimeResourceEventInput,
    ToolRuntimeResourceTransitionOutcome,
    persist_tool_runtime_resource_transition,
)
from .workspace_lock import (
    WorkspaceLockFile,
    WorkspaceLockRecord,
    create_workspace_lock_file,
    read_workspace_lock_record,
    release_workspace_lock_file,
    workspace_root_lock_path,
)
from .workspace_lock_repository import (
    StoredLockResource,
    list_recoverable_workspace_lock_resources,
)

WORKSPACE_LOCK_CONFLICT_ERROR = (
    "workspace mutation is already locked by another tool invocation"
)


class WorkspaceLockConflictError(RuntimeError):
    """Raised when a workspace mutation lock is already held."""


@dataclass(frozen=True, slots=True)
class WorkspaceLockLease:
    resource_id: str
    lock_id: str
    lock_path: Path
    lock_key: str
    execution_session_id: str
    tool_invocation_id: str
    action_id: str | None


@dataclass(frozen=True, slots=True)
class WorkspaceLockReleaseResult:
    warning_message: str | None


def acquire_workspace_root_lock(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    lock_key: str,
    workspace_root: Path,
    execution_session_id: str,
    tool_invocation_id: str,
    action_id: str | None,
    acquired_at: str,
) -> WorkspaceLockLease:
    lock_path = workspace_root_lock_path(db_path=db_path, lock_key=lock_key)
    resources = list_recoverable_workspace_lock_resources(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        lock_key=lock_key,
    )
    _validate_workspace_lock_file(
        lock_path=lock_path,
        resources=resources,
    )
    _cleanup_stale_workspace_locks(
        resources=resources,
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        current_tool_invocation_id=tool_invocation_id,
        cleaned_at=acquired_at,
    )
    _validate_workspace_lock_file(
        lock_path=lock_path,
        resources=(),
    )
    lock_id = str(uuid.uuid4())
    try:
        create_workspace_lock_file(
            lock_file=WorkspaceLockFile(
                lock_path=lock_path,
                record=WorkspaceLockRecord(
                    lock_id=lock_id,
                    tool_invocation_id=tool_invocation_id,
                    execution_session_id=execution_session_id,
                    lock_key=lock_key,
                    locked_path=str(workspace_root),
                    acquired_at=acquired_at,
                ),
            )
        )
    except FileExistsError as exc:
        raise WorkspaceLockConflictError(WORKSPACE_LOCK_CONFLICT_ERROR) from exc
    try:
        resource_id = register_workspace_lock_resource(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            execution_session_id=execution_session_id,
            tool_invocation_id=tool_invocation_id,
            action_id=action_id,
            lock_id=lock_id,
            lock_path=lock_path,
            created_at=acquired_at,
        )
    except Exception:
        release_workspace_lock_file(
            lock_path=lock_path,
            tool_invocation_id=tool_invocation_id,
            lock_id=lock_id,
        )
        raise
    if resource_id is None:
        release_workspace_lock_file(
            lock_path=lock_path,
            tool_invocation_id=tool_invocation_id,
            lock_id=lock_id,
        )
        raise RuntimeError(
            "workspace lock resource registration returned no resource_id"
        )
    return WorkspaceLockLease(
        resource_id=resource_id,
        lock_id=lock_id,
        lock_path=lock_path,
        lock_key=lock_key,
        execution_session_id=execution_session_id,
        tool_invocation_id=tool_invocation_id,
        action_id=action_id,
    )


def release_workspace_lock(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    lease: WorkspaceLockLease,
    released_at: str,
) -> WorkspaceLockReleaseResult:
    release_workspace_lock_file(
        lock_path=lease.lock_path,
        tool_invocation_id=lease.tool_invocation_id,
        lock_id=lease.lock_id,
    )
    try:
        mark_tool_runtime_resource_cleaned(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource_id=lease.resource_id,
            cleaned_at=released_at,
        )
    except Exception as exc:
        return WorkspaceLockReleaseResult(
            warning_message=f"workspace lock bookkeeping failed after release: {exc}"
        )
    return WorkspaceLockReleaseResult(warning_message=None)


def _cleanup_stale_workspace_locks(
    *,
    resources: tuple[StoredLockResource, ...],
    db_path: Path,
    busy_timeout_ms: int,
    current_tool_invocation_id: str,
    cleaned_at: str,
) -> None:
    for stored in resources:
        resource = stored.resource
        if resource.tool_invocation_id == current_tool_invocation_id:
            raise WorkspaceLockConflictError(
                "workspace mutation lock is already held by this tool invocation"
            )
        if stored.tool_invocation_status in {"queued", "running"}:
            raise WorkspaceLockConflictError(WORKSPACE_LOCK_CONFLICT_ERROR)
        _cleanup_stale_workspace_lock_resource(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
            cleaned_at=cleaned_at,
        )


def _cleanup_stale_workspace_lock_resource(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
    cleaned_at: str,
) -> None:
    try:
        cleanup_runtime_resource(resource)
    except Exception as exc:
        if resource_cleanup_attempts_exhausted(resource):
            transition = persist_tool_runtime_resource_transition(
                db_path=db_path,
                busy_timeout_ms=busy_timeout_ms,
                resource=resource,
                status="abandoned",
                timestamp=cleaned_at,
                cleanup_error=str(exc),
                event=ToolRuntimeResourceEventInput(
                    event_type="workspace_lock_stale_abandoned",
                    message=f"workspace lock stale cleanup abandoned: {exc}",
                    tool_invocation_id=resource.tool_invocation_id,
                ),
            )
            if _cleanup_completed_concurrently(transition):
                return
            raise WorkspaceLockConflictError(
                "workspace mutation lock is in abandoned cleanup state"
            ) from exc
        transition = persist_tool_runtime_resource_transition(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
            status="cleanup_failed",
            timestamp=cleaned_at,
            cleanup_error=str(exc),
            event=ToolRuntimeResourceEventInput(
                event_type="workspace_lock_stale_warning",
                message=f"workspace lock stale cleanup failed: {exc}",
                tool_invocation_id=resource.tool_invocation_id,
            ),
        )
        if _cleanup_completed_concurrently(transition):
            return
        raise WorkspaceLockConflictError(WORKSPACE_LOCK_CONFLICT_ERROR) from exc
    transition = persist_tool_runtime_resource_transition(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=resource,
        status="cleaned",
        timestamp=cleaned_at,
        cleanup_error=None,
        event=ToolRuntimeResourceEventInput(
            event_type="workspace_lock_stale_completed",
            message="workspace lock stale cleanup completed",
            tool_invocation_id=resource.tool_invocation_id,
        ),
    )
    _cleanup_completed_concurrently(transition)


def _cleanup_completed_concurrently(
    transition: ToolRuntimeResourceTransitionOutcome,
) -> bool:
    if transition.applied:
        return False
    if transition.current_resource.status == "cleaned":
        return True
    if transition.current_resource.status == "abandoned":
        raise WorkspaceLockConflictError(
            "workspace mutation lock is in abandoned cleanup state"
        )
    raise WorkspaceLockConflictError(WORKSPACE_LOCK_CONFLICT_ERROR)


def _validate_workspace_lock_file(
    *,
    lock_path: Path,
    resources: tuple[StoredLockResource, ...],
) -> None:
    if not lock_path.exists():
        return
    lock_record = read_workspace_lock_record(lock_path=lock_path)
    if lock_record is None:
        raise WorkspaceLockConflictError(
            "workspace mutation lock payload is unreadable"
        )
    if not any(
        stored.resource.tool_invocation_id == lock_record.tool_invocation_id
        for stored in resources
    ):
        raise WorkspaceLockConflictError(
            "workspace mutation lock is held by an unknown owner"
        )


__all__ = [
    "WORKSPACE_LOCK_CONFLICT_ERROR",
    "WorkspaceLockConflictError",
    "WorkspaceLockLease",
    "WorkspaceLockReleaseResult",
    "acquire_workspace_root_lock",
    "release_workspace_lock",
]
