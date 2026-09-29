from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pantaray_agents.local_runtime.agent_state import LocalSuggestionRepository
from pantaray_agents.local_runtime.runtime.welcome_suggestion import (
    WELCOME_SUGGESTION_PROMPT_NAME,
    record_welcome_suggestion,
    welcome_suggestion_id,
)
from pantaray_agents.local_runtime.storage.migrations import load_default_migrations
from pantaray_agents.orchestration.ws.suggestion_relay import (
    read_relayable_suggestion_processes,
)
from pantaray_agents.schema.agent.base import StatusType
from pantaray_agents.schema.agent.suggestion import SuggestionAgentResponse

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
WELCOME = "まずはあなたの仕事を理解するところから始めます。"


class _ActivityRepositoryStub:
    async def get_recent_activity_logs(self, *, user_id: str, limit: int):
        return SimpleNamespace(data=[], error=None)

    async def get_recent_activity_summary(
        self, *, user_id: str, summary_type: str, limit: int
    ):
        return SimpleNamespace(data=[], error=None)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, ui_language, created_at, updated_at)
            VALUES (?, 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
            """,
            (USER_ID,),
        )
    return db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _record(db_path: Path, *, now: str, answer: str = WELCOME) -> bool:
    with _connect(db_path) as connection:
        return record_welcome_suggestion(
            connection=connection, user_id=USER_ID, answer=answer, now=now
        )


def test_the_welcome_is_a_finished_message_only_suggestion_stored_once(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    now = _iso(datetime.now(UTC))

    assert _record(db_path, now=now) is True
    assert _record(db_path, now=now, answer="another greeting") is False

    with _connect(db_path) as connection:
        suggestions = connection.execute(
            "SELECT * FROM agent_suggestions WHERE user_id = ?", (USER_ID,)
        ).fetchall()
        processes = connection.execute(
            "SELECT * FROM processes WHERE user_id = ?", (USER_ID,)
        ).fetchall()
    assert len(suggestions) == 1
    assert suggestions[0]["suggestion_id"] == welcome_suggestion_id(USER_ID)
    assert suggestions[0]["status"] == "success"
    assert suggestions[0]["has_suggestion"] == 1
    assert suggestions[0]["interaction_contract"] == "message_only"
    assert suggestions[0]["answer"] == WELCOME
    assert suggestions[0]["prompt_name"] == WELCOME_SUGGESTION_PROMPT_NAME
    assert len(processes) == 1
    assert processes[0]["kind"] == "suggestion"
    assert processes[0]["status"] == "completed"
    assert processes[0]["suggestion_id"] == welcome_suggestion_id(USER_ID)
    assert processes[0]["completed_at"] == now


def test_a_live_session_relays_the_welcome_it_started_before(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)
    session_start = datetime.now(UTC)
    _record(db_path, now=_iso(session_start + timedelta(seconds=1)))

    relayed = read_relayable_suggestion_processes(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=USER_ID,
        since=_iso(session_start),
    )
    later_session = read_relayable_suggestion_processes(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=USER_ID,
        since=_iso(session_start + timedelta(minutes=1)),
    )

    assert [process.suggestion_id for process in relayed] == [
        welcome_suggestion_id(USER_ID)
    ]
    assert later_session == []


@pytest.mark.asyncio
async def test_the_suggestion_agent_does_not_see_the_welcome_as_a_past_suggestion(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    repo = LocalSuggestionRepository(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        activity_repository=_ActivityRepositoryStub(),
    )
    _record(db_path, now=_iso(datetime.now(UTC)))
    await repo.create_processing_suggestion_row(
        user_id=USER_ID,
        suggestion_id="sug-1",
        created_at=datetime.now(UTC).isoformat(),
    )
    await repo.save_suggestion(
        SuggestionAgentResponse(
            suggestion_id="sug-1",
            user_id=USER_ID,
            created_at="2026-03-24T00:00:00Z",
            answer="Review again?",
            thinking="thinking",
            status=StatusType.SUCCESS,
            has_suggestion=True,
            interaction_contract="message_only",
        ),
        prompt_name="suggestion",
        prompt_version="react_v2",
    )

    recent = await repo.get_recent_suggestions(USER_ID)

    assert recent.data is not None
    assert [entry["answer"] for entry in recent.data] == ["Review again?"]
