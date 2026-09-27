from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pantaray_agents.local_runtime.runtime.process_lock import (
    RUNTIME_LOCK_FILE_SUFFIX,
)
from pantaray_agents.local_runtime.tooling.brokering.broker_common import (
    BROKER_TOOL_TIMEOUT_ERROR_TYPE,
)
from pantaray_agents.local_runtime.tooling.resources.resource_recovery import (
    PERIODIC_REAPER_ERROR_TYPE,
    STARTUP_RECOVERY_ERROR_TYPE,
)
from pantaray_agents.local_runtime.tooling.resources.tool_invocation_recovery import (
    ACTION_CANCELED_TOOL_INVOCATION_ERROR_TYPE,
)

from .storage.migrations import MigrationError

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
RUNTIME_LOCK_SCOPE_ID = f"runtime_global{RUNTIME_LOCK_FILE_SUFFIX}"
RecoveryAuditScope = Literal["tool_invocation", "tool_resource", "runtime_lock"]
RecoveryAuditSeverity = Literal["info", "warning", "abandoned"]


@dataclass(frozen=True, slots=True)
class RecoveryAuditEvent:
    scope: RecoveryAuditScope
    scope_id: str
    action_id: str | None
    invocation_id: str | None
    resource_id: str | None
    event_type: str
    severity: RecoveryAuditSeverity
    message: str
    created_at: str


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    connection.row_factory = sqlite3.Row
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def _normalize_tool_resource_event(row: sqlite3.Row) -> RecoveryAuditEvent:
    event_type = str(row["event_type"])
    return RecoveryAuditEvent(
        scope="tool_resource",
        scope_id=str(row["event_id"]),
        action_id=str(row["action_id"]) if row["action_id"] is not None else None,
        invocation_id=(
            str(row["tool_invocation_id"])
            if row["tool_invocation_id"] is not None
            else None
        ),
        resource_id=str(row["resource_id"]) if row["resource_id"] is not None else None,
        event_type=event_type,
        severity=_severity_from_event_type(event_type),
        message=str(row["message"]),
        created_at=str(row["created_at"]),
    )


def _normalize_runtime_lock_event(row: sqlite3.Row) -> RecoveryAuditEvent:
    event_type = str(row["event_type"])
    return RecoveryAuditEvent(
        scope="runtime_lock",
        scope_id=RUNTIME_LOCK_SCOPE_ID,
        action_id=None,
        invocation_id=None,
        resource_id=str(row["resource_id"]) if row["resource_id"] is not None else None,
        event_type=event_type,
        severity=_severity_from_event_type(event_type),
        message=str(row["message"]),
        created_at=str(row["created_at"]),
    )


def _severity_from_event_type(event_type: str) -> RecoveryAuditSeverity:
    if event_type.endswith("_abandoned"):
        return "abandoned"
    if event_type.endswith("_warning"):
        return "warning"
    return "info"


def _tool_invocation_event_type(error_type: str) -> str | None:
    if error_type == STARTUP_RECOVERY_ERROR_TYPE:
        return "startup_tool_invocation_warning"
    if error_type == PERIODIC_REAPER_ERROR_TYPE:
        return "periodic_tool_invocation_warning"
    if error_type == ACTION_CANCELED_TOOL_INVOCATION_ERROR_TYPE:
        return "action_cancel_tool_invocation_warning"
    if error_type == BROKER_TOOL_TIMEOUT_ERROR_TYPE:
        return "timeout_tool_invocation_warning"
    return None


def _normalize_tool_invocation_output(row: sqlite3.Row) -> RecoveryAuditEvent | None:
    storage_kind = row["output_storage_kind"]
    raw_output = row["output_json"]
    if storage_kind is None and raw_output is None:
        return None
    if storage_kind == "action_file":
        if raw_output is None:
            raise MigrationError(
                "recovery audit output has an invalid storage contract"
            )
        return None
    if storage_kind != "inline_json" or raw_output is None:
        raise MigrationError("recovery audit output has an invalid storage contract")
    output_json = json.loads(str(raw_output))
    if not isinstance(output_json, dict):
        return None
    error = output_json.get("error")
    if not isinstance(error, dict):
        return None
    error_type = error.get("type")
    if not isinstance(error_type, str):
        return None
    event_type = _tool_invocation_event_type(error_type)
    if event_type is None:
        return None
    message = error.get("message")
    return RecoveryAuditEvent(
        scope="tool_invocation",
        scope_id=str(row["output_id"]),
        action_id=str(row["action_id"]) if row["action_id"] is not None else None,
        invocation_id=str(row["invocation_id"]),
        resource_id=None,
        event_type=event_type,
        severity=_severity_from_event_type(event_type),
        message=message if isinstance(message, str) else error_type,
        created_at=str(row["created_at"]),
    )


def _sort_audit_events(
    events: tuple[RecoveryAuditEvent, ...],
) -> tuple[RecoveryAuditEvent, ...]:
    scope_order = {"tool_resource": 0, "tool_invocation": 1, "runtime_lock": 2}
    severity_order = {"info": 0, "warning": 1, "abandoned": 2}
    return tuple(
        sorted(
            _collapse_resource_info_events(events),
            key=lambda event: (
                severity_order.get(event.severity, 99),
                event.created_at,
                scope_order.get(event.scope, 99),
                event.scope_id,
            ),
        )
    )


def _collapse_resource_info_events(
    events: tuple[RecoveryAuditEvent, ...],
) -> tuple[RecoveryAuditEvent, ...]:
    collapsed: list[RecoveryAuditEvent] = []
    seen_resource_info_keys: set[tuple[str | None, str | None, str]] = set()
    for event in events:
        if event.scope != "tool_resource" or event.severity != "info":
            collapsed.append(event)
            continue
        collapse_key = (event.action_id, event.invocation_id, event.event_type)
        if collapse_key in seen_resource_info_keys:
            continue
        seen_resource_info_keys.add(collapse_key)
        collapsed.append(event)
    return tuple(collapsed)


def list_recovery_audit_events_for_action(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    action_id: str,
) -> tuple[RecoveryAuditEvent, ...]:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        resource_rows = connection.execute(
            """
            SELECT
                event_id,
                resource_id,
                tool_invocation_id,
                action_id,
                event_type,
                message,
                created_at
            FROM tool_runtime_resource_events
            WHERE action_id = ?
            ORDER BY created_at ASC, event_id ASC
            """,
            (action_id,),
        ).fetchall()
        output_rows = connection.execute(
            """
            SELECT
                tool_outputs.output_id,
                tool_outputs.invocation_id,
                tool_outputs.output_json,
                tool_outputs.output_storage_kind,
                tool_outputs.created_at,
                tool_invocations.action_id
            FROM tool_outputs
            INNER JOIN tool_invocations
                ON tool_invocations.invocation_id = tool_outputs.invocation_id
            WHERE tool_invocations.action_id = ?
            ORDER BY tool_outputs.created_at ASC, tool_outputs.output_id ASC
            """,
            (action_id,),
        ).fetchall()
    resource_events = tuple(
        _normalize_tool_resource_event(row) for row in resource_rows
    )
    invocation_events = tuple(
        event
        for event in (_normalize_tool_invocation_output(row) for row in output_rows)
        if event is not None
    )
    return _sort_audit_events(resource_events + invocation_events)


def list_recovery_audit_events_for_invocation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
) -> tuple[RecoveryAuditEvent, ...]:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        resource_rows = connection.execute(
            """
            SELECT
                event_id,
                resource_id,
                tool_invocation_id,
                action_id,
                event_type,
                message,
                created_at
            FROM tool_runtime_resource_events
            WHERE tool_invocation_id = ?
            ORDER BY created_at ASC, event_id ASC
            """,
            (invocation_id,),
        ).fetchall()
        output_rows = connection.execute(
            """
            SELECT
                tool_outputs.output_id,
                tool_outputs.invocation_id,
                tool_outputs.output_json,
                tool_outputs.output_storage_kind,
                tool_outputs.created_at,
                tool_invocations.action_id
            FROM tool_outputs
            INNER JOIN tool_invocations
                ON tool_invocations.invocation_id = tool_outputs.invocation_id
            WHERE tool_outputs.invocation_id = ?
            ORDER BY tool_outputs.created_at ASC, tool_outputs.output_id ASC
            """,
            (invocation_id,),
        ).fetchall()
    resource_events = tuple(
        _normalize_tool_resource_event(row) for row in resource_rows
    )
    invocation_events = tuple(
        event
        for event in (_normalize_tool_invocation_output(row) for row in output_rows)
        if event is not None
    )
    return _sort_audit_events(resource_events + invocation_events)


def list_runtime_lock_recovery_audit_events(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> tuple[RecoveryAuditEvent, ...]:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        rows = connection.execute(
            """
            SELECT
                event_id,
                resource_id,
                event_type,
                message,
                created_at
            FROM runtime_lock_events
            ORDER BY created_at ASC, event_id ASC
            """
        ).fetchall()
    return tuple(_normalize_runtime_lock_event(row) for row in rows)


__all__ = [
    "RecoveryAuditEvent",
    "RecoveryAuditScope",
    "RecoveryAuditSeverity",
    "list_recovery_audit_events_for_action",
    "list_recovery_audit_events_for_invocation",
    "list_runtime_lock_recovery_audit_events",
]
