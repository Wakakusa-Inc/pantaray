from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.agents.action_agent.services.memory_sql import execute_memory_sql
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                ui_language,
                created_at,
                updated_at
            ) VALUES ('user-1', 'ja', '2026-04-01T00:00:00Z', '2026-04-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            INSERT INTO users(
                user_id,
                ui_language,
                created_at,
                updated_at
            ) VALUES ('user-2', 'ja', '2026-04-01T00:00:00Z', '2026-04-01T00:00:00Z')
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
                'sug-1',
                'user-1',
                'success',
                'remember the sandbox git finding',
                'prompt',
                'response',
                'prompt',
                'v1',
                1,
                'action_offer',
                '2026-04-01T00:00:00Z',
                '2026-04-01T00:00:00Z'
            )
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
                'sug-2',
                'user-2',
                'success',
                'other user memory',
                'prompt',
                'response',
                'prompt',
                'v1',
                1,
                'action_offer',
                '2026-04-01T00:00:00Z',
                '2026-04-01T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO activity_logs(
                log_id,
                user_id,
                period_start,
                period_end,
                status,
                description,
                prompt_name,
                prompt_version,
                created_at,
                updated_at
            ) VALUES (
                'log-1',
                'user-1',
                '2026-04-01T00:00:00Z',
                '2026-04-01T00:05:00Z',
                'success',
                ?,
                'prompt',
                'v1',
                '2026-04-01T00:05:00Z',
                '2026-04-01T00:05:00Z'
            )
            """,
            ("x" * 5_000,),
        )
        _insert_memory_artifact_block(
            connection,
            user_id="user-1",
            artifact_id="artifact-user-1",
            file_id="file-user-1",
            block_id="block-user-1",
            preview_text="current user artifact block",
        )
        _insert_memory_artifact_block(
            connection,
            user_id="user-2",
            artifact_id="artifact-user-2",
            file_id="file-user-2",
            block_id="block-user-2",
            preview_text="other user artifact block",
        )
    return db_path


def _insert_memory_artifact_block(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    artifact_id: str,
    file_id: str,
    block_id: str,
    preview_text: str,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_artifacts(
            artifact_id,
            user_id,
            source_type,
            source_record_id,
            root_path,
            content_sha256,
            logical_created_at,
            logical_updated_at,
            indexed_at
        ) VALUES (?, ?, 'long_term_insight', ?, ?, ?, ?, ?, ?)
        """,
        (
            artifact_id,
            user_id,
            artifact_id,
            f"artifacts/{artifact_id}",
            f"sha-{artifact_id}",
            "2026-04-01T00:00:00Z",
            "2026-04-01T00:00:00Z",
            "2026-04-01T00:00:00Z",
        ),
    )
    connection.execute(
        """
        INSERT INTO memory_artifact_files(
            file_id,
            artifact_id,
            relative_path,
            sha256,
            byte_size,
            mime_type,
            updated_at
        ) VALUES (?, ?, 'index.md', ?, 10, 'text/markdown', ?)
        """,
        (file_id, artifact_id, f"sha-{file_id}", "2026-04-01T00:00:00Z"),
    )
    connection.execute(
        """
        INSERT INTO memory_artifact_blocks(
            block_id,
            file_id,
            block_kind,
            heading_path,
            block_index,
            search_text,
            preview_text
        ) VALUES (?, ?, 'paragraph', 'Heading', 0, ?, ?)
        """,
        (block_id, file_id, preview_text, preview_text),
    )


def test_execute_memory_sql_reads_allowed_tables(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=(
            "SELECT suggestion_id, answer FROM agent_suggestions "
            "WHERE suggestion_id = 'sug-1'"
        ),
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["columns"] == ["suggestion_id", "answer"]
    assert result.data["rows"] == [
        {
            "suggestion_id": "sug-1",
            "answer": "remember the sandbox git finding",
        }
    ]
    assert result.data["truncated"] is False


def test_execute_memory_sql_scopes_rows_to_current_user(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql="SELECT suggestion_id, answer FROM agent_suggestions ORDER BY suggestion_id",
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["rows"] == [
        {
            "suggestion_id": "sug-1",
            "answer": "remember the sandbox git finding",
        }
    ]


def test_execute_memory_sql_rejects_main_table_bypass(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql="SELECT suggestion_id FROM main.agent_suggestions",
        limit=20,
    )

    assert result.data is None
    assert result.error is not None


def test_execute_memory_sql_rejects_cte_name_spoof_bypass(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=(
            "WITH agent_suggestions AS ("
            "SELECT suggestion_id FROM main.agent_suggestions"
            ") SELECT suggestion_id FROM agent_suggestions"
        ),
        limit=20,
    )

    assert result.data is None
    assert result.error is not None


def test_execute_memory_sql_allows_non_conflicting_cte_names(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=(
            "WITH recent AS ("
            "SELECT suggestion_id, answer FROM agent_suggestions"
            ") SELECT suggestion_id, answer FROM recent"
        ),
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["rows"] == [
        {
            "suggestion_id": "sug-1",
            "answer": "remember the sandbox git finding",
        }
    ]


def test_execute_memory_sql_rejects_private_view_name_spoof(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=(
            "WITH __memory_sql_agent_suggestions AS ("
            "SELECT suggestion_id FROM agent_suggestions"
            ") SELECT suggestion_id FROM __memory_sql_agent_suggestions"
        ),
        limit=20,
    )

    assert result.data is None
    assert result.error is not None


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 'agent_suggestions' AS table_name",
        'SELECT "agent_suggestions" AS table_name',
        "SELECT 1 AS value -- agent_suggestions",
        "SELECT 1 AS agent_suggestions",
        (
            "WITH \"agent_suggestions\"(suggestion_id) AS (VALUES ('fake')) "
            "SELECT suggestion_id FROM agent_suggestions"
        ),
    ],
)
def test_execute_memory_sql_rejects_queries_without_memory_table_reads(
    tmp_path: Path,
    sql: str,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=sql,
        limit=20,
    )

    assert result.data is None
    assert result.error is not None


def test_execute_memory_sql_allows_empty_results_after_memory_table_read(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql="SELECT suggestion_id FROM agent_suggestions WHERE answer LIKE '%missing%'",
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["rows"] == []


def test_execute_memory_sql_rejects_legacy_artifact_projection_tables(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=(
            "SELECT block_id, preview_text FROM memory_artifact_blocks "
            "ORDER BY block_id"
        ),
        limit=20,
    )

    assert result.data is None
    assert result.error == (
        "memory_sql: query must reference at least one allowed memory table."
    )


def test_execute_memory_sql_allows_safe_aggregate_functions(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql="SELECT COUNT(*) AS suggestion_count FROM agent_suggestions",
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["rows"] == [{"suggestion_count": 1}]


@pytest.mark.parametrize(
    ("sql", "expected_rows"),
    [
        (
            "SELECT suggestion_id FROM agent_suggestions WHERE answer LIKE '%sandbox%'",
            [{"suggestion_id": "sug-1"}],
        ),
        (
            "SELECT suggestion_id FROM agent_suggestions WHERE answer GLOB '*sandbox*'",
            [{"suggestion_id": "sug-1"}],
        ),
        (
            "SELECT lower(status) AS status FROM agent_suggestions",
            [{"status": "success"}],
        ),
    ],
)
def test_execute_memory_sql_allows_common_search_functions(
    tmp_path: Path,
    sql: str,
    expected_rows: list[dict[str, object]],
) -> None:
    db_path = _bootstrap_db(tmp_path)
    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=sql,
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["rows"] == expected_rows


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE agent_suggestions SET answer = 'bad'",
        "PRAGMA table_info(agent_suggestions)",
        "SELECT user_id FROM users",
        "SELECT format('%1000000s', answer) FROM agent_suggestions",
        "SELECT printf('%1000000s', answer) FROM agent_suggestions",
        "SELECT hex(randomblob(8)) FROM agent_suggestions",
        "SELECT load_extension('x') FROM agent_suggestions",
        "SELECT zeroblob(1000000) FROM agent_suggestions",
    ],
)
def test_execute_memory_sql_rejects_unsafe_or_disallowed_queries(
    tmp_path: Path,
    sql: str,
) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=sql,
        limit=20,
    )

    assert result.data is None
    assert result.error is not None


def test_execute_memory_sql_limits_rows_and_cell_text(tmp_path: Path) -> None:
    db_path = _bootstrap_db(tmp_path)

    result = execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        sql=("SELECT log_id, description FROM activity_logs ORDER BY period_end DESC"),
        limit=1,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data["row_count"] == 1
    assert result.data["truncated"] is True
    description = result.data["rows"][0]["description"]
    assert isinstance(description, str)
    assert len(description) < 5_000
    assert description.endswith("...")
