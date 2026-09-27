from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from .support import (
    _configure_connection,
    _insert_user,
    apply_migrations,
    load_default_migrations,
)

USER_ID = "user-fts"


@dataclass(frozen=True, slots=True)
class FtsSyncCase:
    name: str
    table_name: str
    fts_table_name: str
    id_column: str
    id_value: str
    text_column: str
    insert_fixture: Callable[[sqlite3.Connection, str], None]


FTS_SYNC_CASES: tuple[FtsSyncCase, ...] = (
    FtsSyncCase(
        name="suggestions",
        table_name="agent_suggestions",
        fts_table_name="memory_search_agent_suggestions_fts",
        id_column="suggestion_id",
        id_value="sug-fts",
        text_column="answer",
        insert_fixture=lambda connection, text: _insert_suggestion_fixture(
            connection,
            text=text,
        ),
    ),
    FtsSyncCase(
        name="actions",
        table_name="agent_actions",
        fts_table_name="memory_search_agent_actions_fts",
        id_column="action_id",
        id_value="act-fts",
        text_column="final_output",
        insert_fixture=lambda connection, text: _insert_action_fixture(
            connection,
            text=text,
        ),
    ),
    FtsSyncCase(
        name="insights",
        table_name="agent_insights",
        fts_table_name="memory_search_agent_insights_fts",
        id_column="insight_id",
        id_value="ins-fts",
        text_column="short_term_insight_data",
        insert_fixture=lambda connection, text: _insert_insight_fixture(
            connection,
            text=text,
        ),
    ),
    FtsSyncCase(
        name="activity_logs",
        table_name="activity_logs",
        fts_table_name="memory_search_activity_logs_fts",
        id_column="log_id",
        id_value="log-fts",
        text_column="description",
        insert_fixture=lambda connection, text: _insert_activity_log_fixture(
            connection,
            text=text,
        ),
    ),
    FtsSyncCase(
        name="activity_summaries",
        table_name="activity_summaries",
        fts_table_name="memory_search_activity_summaries_fts",
        id_column="summary_id",
        id_value="sum-fts",
        text_column="summary",
        insert_fixture=lambda connection, text: _insert_activity_summary_fixture(
            connection,
            text=text,
        ),
    ),
)


@pytest.mark.parametrize("case", FTS_SYNC_CASES, ids=lambda case: case.name)
def test_memory_search_row_fts_triggers_keep_each_index_in_sync(
    tmp_path: Path,
    case: FtsSyncCase,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            case.insert_fixture(connection, f"origfts {case.name}")

            _assert_fts_match_count(connection, case.fts_table_name, "origfts", 1)

            connection.execute(
                (
                    f"UPDATE {case.table_name} SET {case.text_column} = ? "
                    f"WHERE {case.id_column} = ?"
                ),
                (f"newfts {case.name}", case.id_value),
            )
            _assert_fts_match_count(connection, case.fts_table_name, "origfts", 0)
            _assert_fts_match_count(connection, case.fts_table_name, "newfts", 1)

            connection.execute(
                f"DELETE FROM {case.table_name} WHERE {case.id_column} = ?",
                (case.id_value,),
            )
            _assert_fts_match_count(connection, case.fts_table_name, "newfts", 0)


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            _insert_user(connection, USER_ID)
    return db_path


def _insert_suggestion_fixture(connection: sqlite3.Connection, *, text: str) -> None:
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id,
            user_id,
            status,
            answer,
            prompt_name,
            prompt_version,
            has_suggestion,
            interaction_contract,
            created_at,
            updated_at
        ) VALUES (?, ?, 'success', ?, 'prompt', 'v1', 1, 'action_offer', ?, ?)
        """,
        (
            "sug-fts",
            USER_ID,
            text,
            "2026-03-24T00:00:00Z",
            "2026-03-24T00:00:00Z",
        ),
    )


def _insert_action_fixture(connection: sqlite3.Connection, *, text: str) -> None:
    _insert_suggestion_fixture(connection, text="action parent suggestion")
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id,
            user_id,
            suggestion_id,
            initial_user_message_id,
            status,
            execution_target_json,
            final_output,
            prompt_name,
            prompt_version,
            created_at,
            updated_at
        ) VALUES (
            ?, ?, ?, 'message-act-fts', 'success', '{"kind":"scratch"}', ?,
            'prompt', 'v1', ?, ?
        )
        """,
        (
            "act-fts",
            USER_ID,
            "sug-fts",
            text,
            "2026-03-24T00:01:00Z",
            "2026-03-24T00:01:00Z",
        ),
    )


def _insert_insight_fixture(connection: sqlite3.Connection, *, text: str) -> None:
    _insert_action_fixture(connection, text="insight parent action")
    connection.execute(
        """
        INSERT INTO agent_insights(
            insight_id,
            user_id,
            suggestion_id,
            action_id,
            status,
            short_term_insight_data,
            facts,
            prompt_name,
            prompt_version,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, 'success', ?, 'facts', 'prompt', 'v1', ?, ?)
        """,
        (
            "ins-fts",
            USER_ID,
            "sug-fts",
            "act-fts",
            text,
            "2026-03-24T00:02:00Z",
            "2026-03-24T00:02:00Z",
        ),
    )


def _insert_activity_log_fixture(connection: sqlite3.Connection, *, text: str) -> None:
    connection.execute(
        """
        INSERT INTO activity_logs(
            log_id,
            user_id,
            period_start,
            period_end,
            description,
            status,
            prompt_name,
            prompt_version,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, 'success', 'prompt', 'v1', ?, ?)
        """,
        (
            "log-fts",
            USER_ID,
            "2026-03-24T00:00:00Z",
            "2026-03-24T00:10:00Z",
            text,
            "2026-03-24T00:10:00Z",
            "2026-03-24T00:10:00Z",
        ),
    )


def _insert_activity_summary_fixture(
    connection: sqlite3.Connection,
    *,
    text: str,
) -> None:
    connection.execute(
        """
        INSERT INTO activity_summaries(
            summary_id,
            user_id,
            summary_type,
            period_start,
            period_end,
            summary,
            status,
            prompt_name,
            prompt_version,
            created_at,
            updated_at
        ) VALUES (?, ?, '1m', ?, ?, ?, 'success', 'prompt', 'v1', ?, ?)
        """,
        (
            "sum-fts",
            USER_ID,
            "2026-03-01T00:00:00Z",
            "2026-03-31T23:59:59Z",
            text,
            "2026-03-31T23:59:59Z",
            "2026-03-31T23:59:59Z",
        ),
    )


def _assert_fts_match_count(
    connection: sqlite3.Connection,
    table_name: str,
    term: str,
    expected_count: int,
) -> None:
    row = connection.execute(
        f"SELECT count(*) FROM {table_name} WHERE {table_name} MATCH ?",
        (term,),
    ).fetchone()
    assert row is not None
    assert row[0] == expected_count
