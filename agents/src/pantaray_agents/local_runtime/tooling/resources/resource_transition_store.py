from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ...storage.transactions import immediate_transaction
from ..models import StoredToolRuntimeResource
from .resource_db_support import configure_connection
from .resource_event_store import _record_tool_runtime_resource_event_in_connection
from .resource_store import (
    _compare_and_update_tool_runtime_resource_status_in_connection,
    _load_tool_runtime_resource_in_connection,
)

ToolRuntimeResourceTransitionStatus = Literal[
    "cleaned",
    "cleanup_failed",
    "abandoned",
]


@dataclass(frozen=True, slots=True)
class ToolRuntimeResourceEventInput:
    event_type: str
    message: str
    tool_invocation_id: str | None


@dataclass(frozen=True, slots=True)
class ToolRuntimeResourceTransitionOutcome:
    applied: bool
    current_resource: StoredToolRuntimeResource


def persist_tool_runtime_resource_transition(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    resource: StoredToolRuntimeResource,
    status: ToolRuntimeResourceTransitionStatus,
    timestamp: str,
    cleanup_error: str | None,
    event: ToolRuntimeResourceEventInput | None,
) -> ToolRuntimeResourceTransitionOutcome:
    """Compare-and-set one resource status and its coupled event atomically."""

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            return persist_tool_runtime_resource_transition_in_connection(
                connection=connection,
                resource=resource,
                status=status,
                timestamp=timestamp,
                cleanup_error=cleanup_error,
                event=event,
            )


def persist_tool_runtime_resource_transition_in_connection(
    *,
    connection: sqlite3.Connection,
    resource: StoredToolRuntimeResource,
    status: ToolRuntimeResourceTransitionStatus,
    timestamp: str,
    cleanup_error: str | None,
    event: ToolRuntimeResourceEventInput | None,
) -> ToolRuntimeResourceTransitionOutcome:
    """Compare-and-set one resource using the caller's transaction."""

    applied = _compare_and_update_tool_runtime_resource_status_in_connection(
        connection=connection,
        resource=resource,
        status=status,
        timestamp=timestamp,
        cleanup_error=cleanup_error,
    )
    current_resource = _load_tool_runtime_resource_in_connection(
        connection=connection,
        resource_id=resource.resource_id,
    )
    if applied and event is not None:
        _record_tool_runtime_resource_event_in_connection(
            connection=connection,
            resource_id=resource.resource_id,
            tool_invocation_id=event.tool_invocation_id,
            action_id=resource.action_id,
            event_type=event.event_type,
            message=event.message,
            created_at=timestamp,
        )
    return ToolRuntimeResourceTransitionOutcome(
        applied=applied,
        current_resource=current_resource,
    )


__all__ = [
    "ToolRuntimeResourceEventInput",
    "ToolRuntimeResourceTransitionOutcome",
    "ToolRuntimeResourceTransitionStatus",
    "persist_tool_runtime_resource_transition",
    "persist_tool_runtime_resource_transition_in_connection",
]
