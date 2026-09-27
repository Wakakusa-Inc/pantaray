from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from ..models import StoredToolRuntimeResourceEvent
from .resource_db_support import build_tool_runtime_resource_event, configure_connection


def record_tool_runtime_resource_event(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource_id: str | None,
    tool_invocation_id: str | None,
    action_id: str | None,
    event_type: str,
    message: str,
    created_at: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with connection:
            _record_tool_runtime_resource_event_in_connection(
                connection=connection,
                resource_id=resource_id,
                tool_invocation_id=tool_invocation_id,
                action_id=action_id,
                event_type=event_type,
                message=message,
                created_at=created_at,
            )


def _record_tool_runtime_resource_event_in_connection(
    *,
    connection: sqlite3.Connection,
    resource_id: str | None,
    tool_invocation_id: str | None,
    action_id: str | None,
    event_type: str,
    message: str,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO tool_runtime_resource_events(
            event_id,
            resource_id,
            tool_invocation_id,
            action_id,
            event_type,
            message,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            resource_id,
            tool_invocation_id,
            action_id,
            event_type,
            message,
            created_at,
        ),
    )


def list_tool_runtime_resource_events_for_invocation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
) -> tuple[StoredToolRuntimeResourceEvent, ...]:
    return _list_tool_runtime_resource_events(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        where_clause="tool_invocation_id = ?",
        parameters=(invocation_id,),
    )


def list_tool_runtime_resource_events_for_action(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    action_id: str,
) -> tuple[StoredToolRuntimeResourceEvent, ...]:
    return _list_tool_runtime_resource_events(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        where_clause="action_id = ?",
        parameters=(action_id,),
    )


def _list_tool_runtime_resource_events(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    where_clause: str,
    parameters: tuple[object, ...],
) -> tuple[StoredToolRuntimeResourceEvent, ...]:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        rows = connection.execute(
            f"""
            SELECT
                event_id,
                resource_id,
                tool_invocation_id,
                action_id,
                event_type,
                message,
                created_at
            FROM tool_runtime_resource_events
            WHERE {where_clause}
            ORDER BY created_at ASC, event_id ASC
            """,
            parameters,
        ).fetchall()
    return tuple(build_tool_runtime_resource_event(row) for row in rows)
