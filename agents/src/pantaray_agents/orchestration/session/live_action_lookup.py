"""Live action process lookup over in-memory session records."""

from __future__ import annotations

from collections.abc import Iterable

from pantaray_agents.orchestration.session.records import SessionRecord


def has_live_action_process_in_sessions(
    *,
    sessions: Iterable[SessionRecord],
    user_id: str,
    process_id: str,
    suggestion_id: str,
    action_id: str,
    command_id: str,
) -> bool:
    normalized_user_id = user_id.strip()
    normalized_process_id = process_id.strip()
    normalized_suggestion_id = suggestion_id.strip()
    normalized_action_id = action_id.strip()
    normalized_command_id = command_id.strip()
    if not (
        normalized_user_id
        and normalized_process_id
        and normalized_suggestion_id
        and normalized_action_id
        and normalized_command_id
    ):
        return False

    for session in sessions:
        if str(session.user_id or "").strip() != normalized_user_id:
            continue
        process = session.processes.get(normalized_process_id)
        if process is None:
            continue
        if process.kind != "action":
            continue
        if process.suggestion_id != normalized_suggestion_id:
            continue
        if process.action_id != normalized_action_id:
            continue
        if process.command_id != normalized_command_id:
            continue
        if process.completed_at is not None:
            continue
        if process.acknowledged_at is not None:
            continue
        return True
    return False
