from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
    PublicProcessEventConflictError,
    append_public_process_event,
)
from pantaray_agents.local_runtime.suggestion_state.public_projection import (
    fold_suggestion_state_from_events,
)
from pantaray_agents.local_runtime.suggestion_state.shared import configure_connection

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000


def _event_row(
    *, sequence: int, event_name: str, data: dict[str, object]
) -> dict[str, object]:
    return {
        "sequence": sequence,
        "event_name": event_name,
        "created_at": "2026-03-25T00:00:00Z",
        "payload": {"data": data},
    }


def _bootstrap_public_event_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute(
                """
                INSERT INTO users(user_id, ui_language, created_at, updated_at)
                VALUES ('user-1', 'ja', '2026-03-25T00:00:00Z', '2026-03-25T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, 'user-1', 'processing', '2026-03-25T00:00:00Z', '2026-03-25T00:00:00Z')
                """,
                ("sug-1",),
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, 'user-1', 'processing', '2026-03-25T00:00:00Z', '2026-03-25T00:00:00Z')
                """,
                ("sug-2",),
            )
    return db_path


def test_append_public_process_event_is_idempotent_for_same_event_id(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_public_event_db(tmp_path)
    payload = {"data": {"kind": "suggestion", "status": "success"}}
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            first_sequence = append_public_process_event(
                connection=connection,
                event_id="event-1",
                suggestion_id="sug-1",
                user_id="user-1",
                action_id=None,
                event_name="process_completed",
                payload=payload,
                created_at="2026-03-25T00:00:01Z",
            )
            second_sequence = append_public_process_event(
                connection=connection,
                event_id="event-1",
                suggestion_id="sug-1",
                user_id="user-1",
                action_id=None,
                event_name="process_completed",
                payload=payload,
                created_at="2026-03-25T00:00:01Z",
            )
            row_count = connection.execute(
                "SELECT COUNT(*) FROM agent_process_events WHERE event_id = 'event-1'"
            ).fetchone()

    assert first_sequence == 1
    assert second_sequence == 1
    assert row_count is not None
    assert row_count[0] == 1


def test_append_public_process_event_rejects_event_id_context_conflict(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_public_event_db(tmp_path)
    payload = {"data": {"kind": "suggestion", "status": "success"}}
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            append_public_process_event(
                connection=connection,
                event_id="event-1",
                suggestion_id="sug-1",
                user_id="user-1",
                action_id=None,
                event_name="process_completed",
                payload=payload,
                created_at="2026-03-25T00:00:01Z",
            )
            with pytest.raises(PublicProcessEventConflictError):
                append_public_process_event(
                    connection=connection,
                    event_id="event-1",
                    suggestion_id="sug-2",
                    user_id="user-1",
                    action_id=None,
                    event_name="process_completed",
                    payload=payload,
                    created_at="2026-03-25T00:00:01Z",
                )


def test_append_public_process_event_rejects_event_id_payload_conflict(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_public_event_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            append_public_process_event(
                connection=connection,
                event_id="event-1",
                suggestion_id="sug-1",
                user_id="user-1",
                action_id=None,
                event_name="process_completed",
                payload={"data": {"kind": "suggestion", "status": "success"}},
                created_at="2026-03-25T00:00:01Z",
            )
            with pytest.raises(PublicProcessEventConflictError):
                append_public_process_event(
                    connection=connection,
                    event_id="event-1",
                    suggestion_id="sug-1",
                    user_id="user-1",
                    action_id=None,
                    event_name="process_completed",
                    payload={"data": {"kind": "suggestion", "status": "error"}},
                    created_at="2026-03-25T00:00:01Z",
                )


def test_append_public_process_event_rejects_event_id_user_conflict(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_public_event_db(tmp_path)
    payload = {"data": {"kind": "suggestion", "status": "success"}}
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            connection.execute(
                """
                INSERT INTO users(user_id, ui_language, created_at, updated_at)
                VALUES ('user-2', 'ja', '2026-03-25T00:00:00Z', '2026-03-25T00:00:00Z')
                """
            )
            append_public_process_event(
                connection=connection,
                event_id="event-1",
                suggestion_id="sug-1",
                user_id="user-1",
                action_id=None,
                event_name="process_completed",
                payload=payload,
                created_at="2026-03-25T00:00:01Z",
            )
            with pytest.raises(PublicProcessEventConflictError):
                append_public_process_event(
                    connection=connection,
                    event_id="event-1",
                    suggestion_id="sug-1",
                    user_id="user-2",
                    action_id=None,
                    event_name="process_completed",
                    payload=payload,
                    created_at="2026-03-25T00:00:01Z",
                )


def test_fold_suggestion_state_from_events_accepts_action_runtime_statuses() -> None:
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="action_requested",
                data={
                    "accepted_at": "2026-03-25T00:00:00Z",
                    "command_id": "cmd-1",
                    "process_id": "proc-1",
                },
            ),
            _event_row(
                sequence=2,
                event_name="process_started",
                data={
                    "kind": "action",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "accepted_at": "2026-03-25T00:00:00Z",
                },
            ),
            _event_row(
                sequence=3,
                event_name="process_completed",
                data={
                    "kind": "action",
                    "status": "error",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "failure_code": "ACTION_PROCESSING_TIMEOUT",
                    "failure_stage": "running_failed",
                    "failure_message_public": "Action execution failed.",
                },
            ),
        ],
    )

    assert folded.action_status == "error"
    assert folded.action_failure_code == "ACTION_PROCESSING_TIMEOUT"


def test_fold_cutover_terminal_event_clears_approval_blockers() -> None:
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="action_requested",
                data={
                    "accepted_at": "2026-03-25T00:00:00Z",
                    "command_id": "cmd-1",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                },
            ),
            _event_row(
                sequence=2,
                event_name="process_started",
                data={
                    "kind": "action",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                },
            ),
            _event_row(
                sequence=3,
                event_name="process_paused",
                data={
                    "kind": "action",
                    "reason": "approval_pending",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "approval_blockers": [
                        {
                            "approval_session_id": "approval-1",
                            "tool_request_id": "request-1",
                        }
                    ],
                },
            ),
            _event_row(
                sequence=4,
                event_name="process_completed",
                data={
                    "kind": "action",
                    "status": "error",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "failure_code": "ACTION_CREATION_CUTOVER",
                    "failure_stage": "resume_failed",
                    "failure_message_public": (
                        "Action execution could not be resumed after a local data upgrade."
                    ),
                },
            ),
        ],
    )

    assert folded.action_status == "error"
    assert folded.action_failure_code == "ACTION_CREATION_CUTOVER"
    assert folded.action_failure_stage == "resume_failed"
    assert folded.approval_blockers == []


def test_fold_action_requested_binds_reserved_action_and_process() -> None:
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="action_requested",
                data={
                    "accepted_at": "2026-03-25T00:00:00Z",
                    "command_id": "message-1",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                },
            )
        ],
    )

    assert folded.command_id == "message-1"
    assert folded.process_id == "proc-1"
    assert folded.action_id == "act-1"
    assert folded.action_status == "idle"


def test_fold_suggestion_state_from_events_keeps_action_processing_on_approval_pause() -> (
    None
):
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="action_requested",
                data={
                    "accepted_at": "2026-03-25T00:00:00Z",
                    "command_id": "cmd-1",
                    "process_id": "proc-1",
                },
            ),
            _event_row(
                sequence=2,
                event_name="process_started",
                data={
                    "kind": "action",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "accepted_at": "2026-03-25T00:00:00Z",
                },
            ),
            _event_row(
                sequence=3,
                event_name="process_paused",
                data={
                    "kind": "action",
                    "status": "processing",
                    "reason": "approval_pending",
                    "process_id": "proc-1",
                    "action_id": "act-1",
                    "command_id": "cmd-1",
                    "completed_at": "2026-03-25T00:00:05Z",
                    "approval_blockers": [
                        {
                            "action_id": "act-1",
                            "approval_session_id": "approval-1",
                            "tool_request_id": "tool-request-1",
                            "tool_id": "bash",
                            "intent_class": "process_exec_local",
                            "command_summary": {"kind": "bash", "command": "pwd"},
                        }
                    ],
                },
            ),
        ],
    )

    assert folded.action_status == "processing"
    assert folded.action_id == "act-1"
    assert folded.process_id == "proc-1"


def test_fold_suggestion_state_from_events_treats_resume_as_same_action(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("WARNING")

    rows = [
        _event_row(
            sequence=1,
            event_name="action_requested",
            data={
                "accepted_at": "2026-03-25T00:00:00Z",
                "command_id": "cmd-1",
                "process_id": "proc-1",
            },
        ),
        _event_row(
            sequence=2,
            event_name="process_started",
            data={
                "kind": "action",
                "process_id": "proc-1",
                "action_id": "act-1",
                "command_id": "cmd-1",
                "accepted_at": "2026-03-25T00:00:00Z",
            },
        ),
        _event_row(
            sequence=3,
            event_name="process_paused",
            data={
                "kind": "action",
                "status": "processing",
                "reason": "approval_pending",
                "process_id": "proc-1",
                "action_id": "act-1",
                "command_id": "cmd-1",
                "completed_at": "2026-03-25T00:00:04Z",
                "approval_blockers": [
                    {
                        "action_id": "act-1",
                        "approval_session_id": "approval-1",
                        "tool_request_id": "tool-request-1",
                        "tool_id": "bash",
                        "intent_class": "process_exec_local",
                        "command_summary": {"kind": "bash", "command": "pwd"},
                    },
                    {
                        "action_id": "act-1",
                        "approval_session_id": "approval-2",
                        "tool_request_id": "tool-request-2",
                        "tool_id": "apply_patch",
                        "intent_class": "surgical_edit",
                        "command_summary": {
                            "kind": "apply_patch",
                            "target_paths": ["todo.md"],
                        },
                    },
                ],
            },
        ),
        _event_row(
            sequence=4,
            event_name="action_resume_requested",
            data={
                "process_id": "proc-2",
                "action_id": "act-1",
                "command_id": "cmd-1",
                "accepted_at": "2026-03-25T00:00:00Z",
                "requested_at": "2026-03-25T00:00:05Z",
                "approval_session_id": "approval-1",
                "approval_tool_request_id": "tool-request-1",
            },
        ),
    ]
    resuming = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=rows,
    )

    assert resuming.action_status == "processing"
    assert resuming.action_id == "act-1"
    assert resuming.process_id == "proc-2"
    assert resuming.approval_blockers == []

    rows.append(
        _event_row(
            sequence=5,
            event_name="process_paused",
            data={
                "kind": "action",
                "status": "processing",
                "reason": "approval_pending",
                "process_id": "proc-2",
                "action_id": "act-1",
                "command_id": "cmd-1",
                "completed_at": "2026-03-25T00:00:06Z",
                "approval_blockers": [
                    {
                        "action_id": "act-1",
                        "approval_session_id": "approval-2",
                        "tool_request_id": "tool-request-2",
                        "tool_id": "apply_patch",
                        "intent_class": "surgical_edit",
                        "command_summary": {
                            "kind": "apply_patch",
                            "target_paths": ["todo.md"],
                        },
                    }
                ],
            },
        )
    )
    paused_again = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=rows,
    )

    assert [
        blocker["approval_session_id"] for blocker in paused_again.approval_blockers
    ] == ["approval-2"]
    assert "SUGGESTION_STATE_ACTION_REQUESTED_AFTER_ADVANCE" not in caplog.text


def test_fold_suggestion_state_from_events_rejects_unsupported_action_status() -> None:
    with pytest.raises(
        ValueError, match="Unsupported action status in public projection"
    ):
        fold_suggestion_state_from_events(
            suggestion_id="sug-1",
            rows=[
                _event_row(
                    sequence=1,
                    event_name="process_completed",
                    data={
                        "kind": "action",
                        "status": "abandoned",
                    },
                )
            ],
        )


def test_fold_suggestion_state_from_events_normalizes_reaction() -> None:
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="suggestion_reaction_committed",
                data={
                    "reaction": " Accepted ",
                    "committed_at": "2026-03-25T00:00:00Z",
                },
            ),
        ],
    )

    assert folded.user_reaction == "accepted"
    assert folded.accepted_at == "2026-03-25T00:00:00Z"
    assert folded.rejected_at is None


def test_fold_suggestion_state_from_events_ignores_stale_reaction() -> None:
    folded = fold_suggestion_state_from_events(
        suggestion_id="sug-1",
        rows=[
            _event_row(
                sequence=1,
                event_name="suggestion_reaction_committed",
                data={
                    "reaction": "ignored",
                    "committed_at": "2026-03-25T00:00:00Z",
                },
            ),
        ],
    )

    assert folded.user_reaction is None
    assert folded.accepted_at is None
    assert folded.rejected_at is None
