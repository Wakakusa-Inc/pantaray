from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.suggestion_state.repository import (
    LocalSuggestionStateRepository,
)

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
SUGGESTION_ID = "suggestion-1"


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES (?, 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                (USER_ID,),
            )
    return db_path


def _repo(db_path: Path) -> LocalSuggestionStateRepository:
    return LocalSuggestionStateRepository(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )


def _insert_suggestion_with_reaction(db_path: Path, *, user_reaction: str) -> None:
    with sqlite3.connect(db_path) as connection:
        with connection:
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
                    user_reaction,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'success', 'answer', 'prompt', 'response', 'suggestion', '1.0', 1, 'action_offer', ?, ?, ?)
                """,
                (
                    SUGGESTION_ID,
                    USER_ID,
                    user_reaction,
                    "2026-03-24T00:00:00Z",
                    "2026-03-24T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO agent_suggestion_history(
                    suggestion_id,
                    user_id,
                    suggestion_created_at,
                    suggestion_updated_at,
                    suggestion_status,
                    has_suggestion,
                    answer,
                    interaction_contract,
                    user_reaction,
                    action_request_payload_present,
                    last_sequence
                ) VALUES (?, ?, ?, ?, 'success', 1, 'answer', 'action_offer', ?, 0, 1)
                """,
                (
                    SUGGESTION_ID,
                    USER_ID,
                    "2026-03-24T00:00:00Z",
                    "2026-03-24T00:00:00Z",
                    user_reaction,
                ),
            )


@pytest.mark.asyncio
async def test_get_suggestion_state_normalizes_unknown_reaction_to_none(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    _insert_suggestion_with_reaction(db_path, user_reaction="future_value")

    result = await _repo(db_path).get_suggestion_state(
        user_id=USER_ID,
        suggestion_id=SUGGESTION_ID,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["user_reaction"] is None


@pytest.mark.asyncio
async def test_get_suggestion_history_row_normalizes_unknown_reaction_to_none(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    _insert_suggestion_with_reaction(db_path, user_reaction="future_value")

    result = await _repo(db_path).get_suggestion_history_row(
        user_id=USER_ID,
        suggestion_id=SUGGESTION_ID,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["user_reaction"] is None
