from __future__ import annotations

from pathlib import Path

from ..storage.migrations import MigrationError
from ..tooling.models import StoredToolRuntimeResource
from ..tooling.resources.resource_cleanup import (
    cleanup_runtime_resource,
    resource_cleanup_attempts_exhausted,
)
from ..tooling.resources.resource_store import load_tool_runtime_resource
from ..tooling.resources.resource_transition_store import (
    ToolRuntimeResourceEventInput,
    ToolRuntimeResourceTransitionStatus,
    persist_tool_runtime_resource_transition,
)
from .action_legacy_shared_temp_resource_authority import (
    LegacyActionSharedTempPrecleanupAuthority,
)
from .utc_timestamps import now_utc_iso


def reconcile_legacy_action_shared_temp_blockers(
    *,
    resolved_db_path: Path,
    busy_timeout_ms: int,
    authorities: tuple[LegacyActionSharedTempPrecleanupAuthority, ...],
) -> None:
    """Settle captured external blockers while the caller holds the runtime lock."""

    candidates = tuple(resource for row in authorities for resource in row.resources)
    for resource in candidates:
        _require_exact_resource(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
        )

    process_failed = False
    process_groups = (row for row in candidates if row.resource_kind == "process_group")
    for resource in sorted(process_groups, key=lambda row: row.resource_id):
        if not _cleanup_resource(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
        ):
            process_failed = True
    if process_failed:
        raise MigrationError("legacy Action process-group blocker cleanup failed")

    locks = (row for row in candidates if row.resource_kind == "lock")
    for resource in sorted(locks, key=lambda row: row.resource_id):
        if not _cleanup_resource(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
            resource=resource,
        ):
            raise MigrationError("legacy Action workspace-lock blocker cleanup failed")


def _cleanup_resource(
    *,
    resolved_db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
) -> bool:
    _require_exact_resource(
        resolved_db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=resource,
    )
    cleanup_error: str | None = None
    try:
        cleanup_runtime_resource(resource)
    except (OSError, RuntimeError, ValueError) as exc:
        cleanup_error = str(exc)

    if cleanup_error is None:
        status: ToolRuntimeResourceTransitionStatus = "cleaned"
        message = "legacy Action external resource cleanup completed"
    elif resource_cleanup_attempts_exhausted(resource):
        status = "abandoned"
        message = f"legacy Action cleanup retry budget exhausted: {cleanup_error}"
    else:
        status = "cleanup_failed"
        message = f"legacy Action external resource cleanup failed: {cleanup_error}"

    transition = persist_tool_runtime_resource_transition(
        db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource=resource,
        status=status,
        timestamp=now_utc_iso(),
        cleanup_error=cleanup_error,
        event=ToolRuntimeResourceEventInput(
            event_type=f"legacy_action_external_resource_{status}",
            message=f"{resource.resource_kind}: {message}",
            tool_invocation_id=resource.tool_invocation_id,
        ),
    )
    if not transition.applied:
        raise MigrationError("legacy Action external resource cleanup CAS failed")
    return status == "cleaned"


def _require_exact_resource(
    *,
    resolved_db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
) -> None:
    current = load_tool_runtime_resource(
        db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
        resource_id=resource.resource_id,
    )
    if current != resource:
        raise MigrationError("legacy Action external resource authority changed")
