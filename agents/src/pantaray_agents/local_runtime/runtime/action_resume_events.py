"""Publish the immutable identity of one Action approval continuation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.local_runtime.suggestion_state.event_names import (
    EVENT_ACTION_RESUME_REQUESTED,
)
from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
    append_public_process_event,
)
from pantaray_agents.local_runtime.suggestion_state.public_projection import (
    rebuild_history_projection,
)

from .process_events import append_process_event_in_connection


@dataclass(frozen=True, slots=True)
class ActionResumeEventIdentity:
    user_id: str
    action_id: str
    suggestion_id: str | None
    command_id: str
    accepted_at: str
    approval_session_id: str
    approval_tool_request_id: str
    predecessor_process_id: str
    process_id: str
    job_id: str
    requested_at: str


def append_action_resume_events_in_connection(
    *,
    connection: sqlite3.Connection,
    identity: ActionResumeEventIdentity,
) -> None:
    event_id = (
        f"{identity.job_id}-{identity.approval_session_id}-"
        f"{EVENT_ACTION_RESUME_REQUESTED}"
    )
    event_data: dict[str, object] = {
        "process_id": identity.process_id,
        "predecessor_process_id": identity.predecessor_process_id,
        "action_id": identity.action_id,
        "command_id": identity.command_id,
        "accepted_at": identity.accepted_at,
        "requested_at": identity.requested_at,
        "approval_session_id": identity.approval_session_id,
        "approval_tool_request_id": identity.approval_tool_request_id,
    }
    if identity.suggestion_id is not None:
        event_data["suggestion_id"] = identity.suggestion_id
        connection.execute(
            """
            UPDATE agent_suggestions
            SET action_process_id = ?, updated_at = ?
            WHERE user_id = ? AND suggestion_id = ?
            """,
            (
                identity.process_id,
                identity.requested_at,
                identity.user_id,
                identity.suggestion_id,
            ),
        )
    append_process_event_in_connection(
        connection=connection,
        process_id=identity.process_id,
        event_id=event_id,
        event_name=EVENT_ACTION_RESUME_REQUESTED,
        payload=event_data,
        created_at=identity.requested_at,
    )
    append_public_process_event(
        connection=connection,
        event_id=event_id,
        suggestion_id=identity.suggestion_id,
        user_id=identity.user_id,
        action_id=identity.action_id,
        event_name=EVENT_ACTION_RESUME_REQUESTED,
        payload={
            "data": event_data,
            "meta": {
                "action_id": identity.action_id,
                "command_id": identity.command_id,
                "process_id": identity.process_id,
            },
        },
        created_at=identity.requested_at,
    )
    if identity.suggestion_id is not None:
        rebuild_history_projection(
            connection=connection,
            user_id=identity.user_id,
            suggestion_id=identity.suggestion_id,
        )


__all__ = [
    "ActionResumeEventIdentity",
    "append_action_resume_events_in_connection",
]
