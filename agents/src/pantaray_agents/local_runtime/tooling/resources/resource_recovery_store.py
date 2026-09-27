from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from ...storage.migrations import MigrationError
from ..models import (
    StoredInflightToolInvocation,
    StoredToolRuntimeResource,
    ToolInvocationStatus,
)
from .process_identity import classify_process_identity
from .resource_db_support import TOOL_INVOCATION_INFLIGHT_STATUSES, configure_connection
from .resource_store import (
    list_recoverable_tool_runtime_resources_for_invocation,
)
from .resource_transition_store import (
    ToolRuntimeResourceEventInput,
    persist_tool_runtime_resource_transition,
)


class ToolRuntimeResourceReconciliationError(RuntimeError):
    """Recoverable resource bookkeeping failed after tool terminalization."""


def list_inflight_tool_invocations(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[StoredInflightToolInvocation, ...]:
    placeholders = ", ".join("?" for _ in TOOL_INVOCATION_INFLIGHT_STATUSES)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            f"""
            SELECT invocation_id, tool_id, action_id, status
            FROM tool_invocations
            WHERE status IN ({placeholders})
            ORDER BY started_at ASC
            """,
            TOOL_INVOCATION_INFLIGHT_STATUSES,
        ).fetchall()
    return tuple(
        StoredInflightToolInvocation(
            invocation_id=str(row["invocation_id"]),
            tool_id=str(row["tool_id"]),
            action_id=str(row["action_id"]),
            # The query predicate limits this DB value to declared invocation states.
            status=cast(ToolInvocationStatus, str(row["status"])),
        )
        for row in rows
    )


def list_inflight_tool_invocation_ids_for_action_session(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    action_id: str,
    execution_session_id: str,
) -> tuple[str, ...]:
    placeholders = ", ".join("?" for _ in TOOL_INVOCATION_INFLIGHT_STATUSES)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            f"""
            SELECT invocation_id
            FROM tool_invocations
            WHERE user_id = ? AND action_id = ? AND execution_session_id = ?
              AND status IN ({placeholders})
            ORDER BY started_at ASC, invocation_id ASC
            """,
            (
                user_id,
                action_id,
                execution_session_id,
                *TOOL_INVOCATION_INFLIGHT_STATUSES,
            ),
        ).fetchall()
    return tuple(str(row["invocation_id"]) for row in rows)


def finalize_tool_runtime_resources_for_invocation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
    finalized_at: str,
    cleanup_event_type: str | None = None,
    cleanup_message_suffix: str | None = None,
) -> None:
    try:
        resources = list_recoverable_tool_runtime_resources_for_invocation(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            invocation_id=invocation_id,
        )
        for resource in resources:
            if not _resource_is_absent(resource):
                continue
            event = (
                ToolRuntimeResourceEventInput(
                    event_type=cleanup_event_type,
                    message=f"{resource.resource_kind}: {cleanup_message_suffix}",
                    tool_invocation_id=resource.tool_invocation_id,
                )
                if cleanup_event_type is not None and cleanup_message_suffix is not None
                else None
            )
            transition = persist_tool_runtime_resource_transition(
                db_path=db_path,
                busy_timeout_ms=busy_timeout_ms,
                resource=resource,
                status="cleaned",
                timestamp=finalized_at,
                cleanup_error=None,
                event=event,
            )
            if not transition.applied and transition.current_resource.status not in {
                "cleaned",
                "abandoned",
            }:
                raise ToolRuntimeResourceReconciliationError(
                    "tool runtime resource changed during reconciliation: "
                    f"{resource.resource_id}"
                )
    except (MigrationError, OSError, sqlite3.Error) as exc:
        raise ToolRuntimeResourceReconciliationError(
            f"tool runtime resource reconciliation failed: {invocation_id}"
        ) from exc


def _resource_is_absent(resource: StoredToolRuntimeResource) -> bool:
    if resource.resource_kind == "process_group":
        if resource.pid is None:
            return True
        return (
            classify_process_identity(
                pid=resource.pid,
                expected_start_signature=resource.process_start_signature,
            )
            == "mismatch_or_absent"
        )
    if resource.resource_path is None:
        return True
    return not Path(resource.resource_path).exists()
