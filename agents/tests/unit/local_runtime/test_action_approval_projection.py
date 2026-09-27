from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.action_status import FinalizeActionTerminalCommand
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.suggestion_state.repository import (
    LocalSuggestionStateRepository,
)
from pantaray_agents.schema.repositories.repository import RepositoryErrorKind

from .migrated_db import prepare_test_database

_PAUSE_PAYLOAD: dict[str, object] = {
    "data": {
        "kind": "action",
        "reason": "approval_pending",
        "approval_blockers": [{"tool_request_id": "request-1"}],
    }
}


def _seed_pending_approval_action(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(user_id, ui_language, created_at, updated_at)
                VALUES ('user-1', 'ja', '2026-04-27T00:00:00Z', '2026-04-27T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_text,
                    response_text,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    created_at,
                    updated_at
                ) VALUES (
                    'suggestion-1',
                    'user-1',
                    'success',
                    'Run a command?',
                    'prompt',
                    'response',
                    'suggestion/meta_reasoning',
                    '1.0',
                    1,
                    'action_offer',
                    '2026-04-27T00:00:00Z',
                    '2026-04-27T00:00:00Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id,
                    user_id,
                    suggestion_id,
                    initial_user_message_id,
                    execution_target_json,
                    status,
                    final_output,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (
                    'action-1',
                    'user-1',
                    'suggestion-1',
                    'message-1',
                    '{"kind":"scratch"}',
                    'processing',
                    '',
                    'action/runtime',
                    '1.0',
                    '2026-04-27T00:00:01Z',
                    '2026-04-27T00:00:01Z'
                )
                """
            )
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,
                    action_id,
                    user_id,
                    step_number,
                    step_type,
                    step_name,
                    status,
                    tool_output,
                    started_at,
                    completed_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "step-1",
                    "action-1",
                    "user-1",
                    1,
                    "tool_execution",
                    "goal_worker::bash",
                    "processing",
                    json.dumps(
                        {
                            "status": "processing",
                            "output": {
                                "kind": "approval_required",
                                "approval_status": "pending",
                                "approval_session_id": "approval-1",
                                "tool_request_id": "request-1",
                            },
                        }
                    ),
                    "2026-04-27T00:00:02Z",
                    "2026-04-27T00:00:03Z",
                    "2026-04-27T00:00:03Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO approval_sessions(
                    approval_session_id,
                    user_id,
                    action_id,
                    tool_request_id,
                    tool_id,
                    intent_class,
                    approval_source,
                    status,
                    approved_capabilities_json,
                    command_summary_json,
                    requested_at,
                    decided_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "approval-1",
                    "user-1",
                    "action-1",
                    "request-1",
                    "bash",
                    "process_exec_local",
                    "prompt",
                    "pending",
                    json.dumps([]),
                    json.dumps(
                        {
                            "summary_kind": "bash",
                            "command": "ls -R .",
                            "cwd": ".",
                            "timeout_ms": 600_000,
                        }
                    ),
                    "2026-04-27T00:00:03Z",
                    None,
                    "2026-04-27T00:00:03Z",
                ),
            )


def _setup_repository(
    tmp_path: Path,
) -> tuple[Path, LocalSuggestionStateRepository]:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(db_path, 1_000, load_default_migrations())
    _seed_pending_approval_action(db_path)
    return db_path, LocalSuggestionStateRepository(
        db_path=db_path, busy_timeout_ms=1_000
    )


async def _append_pause(repository: LocalSuggestionStateRepository, event_id: str):
    return await repository.append_action_pause_if_processing(
        event_id=event_id,
        suggestion_id="suggestion-1",
        user_id="user-1",
        action_id="action-1",
        payload=_PAUSE_PAYLOAD,
    )


@pytest.mark.asyncio
async def test_action_pause_is_atomic_with_canonical_terminal_projection(
    tmp_path: Path,
) -> None:
    db_path, repository = _setup_repository(tmp_path)
    paused = await _append_pause(repository, "pause-1")
    replayed = await _append_pause(repository, "pause-1")
    with sqlite3.connect(db_path) as connection:
        paused_projection = connection.execute(
            "SELECT action_status FROM agent_suggestion_history"
        ).fetchone()[0]
        connection.execute("UPDATE agent_actions SET status = 'queued'")
    rejected = await _append_pause(repository, "pause-2")
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE agent_actions SET status = 'processing'")
    await repository.finalize_action_terminal_and_project_history(
        command=FinalizeActionTerminalCommand(
            process_completed_event_id="terminal-1",
            suggestion_id="suggestion-1",
            user_id="user-1",
            command_id="message-1",
            process_id="process-1",
            action_id="action-1",
            accepted_at="2026-04-27T00:00:01Z",
            completed_at="2026-04-27T00:00:04Z",
            action_status="success",
            final_output="done",
        )
    )

    superseded = await _append_pause(repository, "pause-3")
    with sqlite3.connect(db_path) as connection:
        projection = connection.execute(
            "SELECT actions.status, history.action_status, "
            "(SELECT group_concat(event_name, ',') FROM "
            "(SELECT event_name FROM agent_process_events ORDER BY sequence)) "
            "FROM agent_actions AS actions, agent_suggestion_history AS history"
        ).fetchone()

    assert paused.data is not None and replayed.data == paused.data
    assert paused_projection == "processing"
    assert rejected.error_kind is RepositoryErrorKind.CONFLICT
    assert superseded.error is None and superseded.data is None
    assert projection == ("success", "success", "process_paused,process_completed")
