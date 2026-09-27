from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime import (
    action_messages,
    append_local_process_event,
    session_store,
)
from pantaray_agents.local_runtime.runtime.action_message_models import (
    ExistingActionTarget,
    StartedActionMessageResult,
)
from pantaray_agents.local_runtime.storage import migrations
from pantaray_agents.orchestration.ws.action_relay_authority import (
    ActionRelayAuthorityError,
    load_action_relay_authority,
)
from pantaray_agents.schema.agent.action import (
    ActionUserMessageInput,
    SuggestionApprovalInput,
)

_BUSY_TIMEOUT_MS = 1_000


@pytest.fixture
def runtime_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    session_store.reset_desktop_session_store()
    db_path = tmp_path / "runtime.db"
    migrations.apply_migrations(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        migrations=migrations.load_default_migrations(),
    )
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", str(_BUSY_TIMEOUT_MS))
    session_store.import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at="2099-08-16T00:00:00Z",
        session_version="1",
    )
    yield db_path
    session_store.reset_desktop_session_store()


def _submit(
    db_path: Path,
    *,
    message_id: str = "message-1",
    suggestion_id: str | None = None,
) -> StartedActionMessageResult:
    if suggestion_id is not None:
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """INSERT INTO agent_suggestions(
                       suggestion_id,user_id,status,has_suggestion,
                       interaction_contract,answer,target_context_json,created_at,updated_at)
                   VALUES (?,'user-1','success',1,'action_offer','Do the work','{}','now','now')""",
                (suggestion_id,),
            )
    approval = (
        SuggestionApprovalInput(
            suggestion_id=suggestion_id, approved_at="2026-08-16T00:00:01Z"
        )
        if suggestion_id is not None
        else None
    )
    result = action_messages.submit_action_message(
        action_messages.SubmitActionMessageCommand(
            user_id="user-1",
            target=action_messages.NewActionTarget(suggestion_id=suggestion_id),
            message=ActionUserMessageInput(
                message_id=message_id,
                content="Do the work",
                suggestion_approval=approval,
            ),
        )
    )
    assert isinstance(result, StartedActionMessageResult)
    return result


def _set_statuses(
    db_path: Path,
    turn: StartedActionMessageResult,
    statuses: tuple[str, str, str],
) -> None:
    action_status, process_status, job_status = statuses
    current_job_id = turn.job_id if process_status in {"running", "paused"} else None
    with sqlite3.connect(db_path) as connection:
        for table, key, status, row_id in (
            ("agent_actions", "action_id", action_status, turn.action_id),
            ("processes", "process_id", process_status, turn.process_id),
            ("jobs", "job_id", job_status, turn.job_id),
        ):
            connection.execute(
                f"UPDATE {table} SET status=? WHERE {key}=?", (status, row_id)
            )
        connection.execute(
            "UPDATE processes SET current_job_id=? WHERE process_id=?",
            (current_job_id, turn.process_id),
        )


@pytest.mark.parametrize(
    ("suggestion_id", "statuses"),
    [
        (None, ("queued", "enqueued", "queued")),
        (None, ("processing", "enqueued", "queued")),
        (None, ("queued", "running", "running")),
        (None, ("processing", "running", "running")),
        (None, ("processing", "running", "retryable_error")),
        ("suggestion-1", ("processing", "paused", "paused")),
    ],
)
def test_active_authority_accepts_canonical_runtime_states(
    runtime_db: Path,
    suggestion_id: str | None,
    statuses: tuple[str, str, str],
) -> None:
    turn = _submit(runtime_db, suggestion_id=suggestion_id)
    _set_statuses(runtime_db, turn, statuses)

    authority = load_action_relay_authority(
        user_id="user-1", action_id=turn.action_id, process_id=turn.process_id
    )
    assert (authority.suggestion_id, authority.command_id) == (
        suggestion_id,
        turn.message_id,
    )
    assert (authority.action_status, authority.terminal_cursor) == (statuses[0], None)


def test_terminal_authority_uses_latest_adopted_user_and_stream_end_cursor(
    runtime_db: Path,
) -> None:
    turn = _submit(runtime_db)
    _set_statuses(runtime_db, turn, ("processing", "running", "running"))
    followup = action_messages.submit_action_message(
        action_messages.SubmitActionMessageCommand(
            user_id="user-1",
            target=ExistingActionTarget(
                action_id=turn.action_id, expected_process_id=turn.process_id
            ),
            message=ActionUserMessageInput(message_id="message-2", content="Steer"),
        )
    )
    with sqlite3.connect(runtime_db) as connection:
        connection.execute(
            """UPDATE agent_action_steps
               SET step_number=2,local_step_number=2,short_step_id='S-2-USER',
                   adopted_process_id=? WHERE step_id=?""",
            (turn.process_id, followup.user_step_id),
        )
    append_local_process_event(
        db_path=runtime_db,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        process_id=turn.process_id,
        event_type="stream_end",
        payload={},
    )
    _set_statuses(runtime_db, turn, ("queued", "completed", "completed"))
    with sqlite3.connect(runtime_db) as connection:
        cursor = connection.execute(
            "SELECT process_event_rowid FROM process_events WHERE process_id=?",
            (turn.process_id,),
        ).fetchone()[0]

    authority = load_action_relay_authority(
        user_id="user-1", action_id=turn.action_id, process_id=turn.process_id
    )
    assert (authority.command_id, authority.terminal_cursor) == ("message-2", cursor)


def test_authority_rejects_cross_owner_and_stale_process(runtime_db: Path) -> None:
    first = _submit(runtime_db)
    second = _submit(runtime_db, message_id="message-other")

    with pytest.raises(ActionRelayAuthorityError):
        load_action_relay_authority(
            user_id="user-1",
            action_id=first.action_id,
            process_id=second.process_id,
        )
    with pytest.raises(migrations.MigrationError):
        load_action_relay_authority(
            user_id="user-other",
            action_id=first.action_id,
            process_id=first.process_id,
        )
