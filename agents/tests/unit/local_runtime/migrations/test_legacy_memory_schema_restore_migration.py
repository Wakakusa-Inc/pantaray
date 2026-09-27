from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    MigrationSpec,
)

from .support import (
    LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
    LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
    _configure_connection,
    _insert_user,
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
RESTORE_MIGRATION_NAME = "0061_restore_legacy_memory_schema.sql"
V2_TIP_VERSION = 60
V2_TIP_MIGRATION_NAME = "0060_memory_record_render_state.sql"

LEGACY_AGENT_INSIGHTS_COLUMNS = {
    "insight_id",
    "user_id",
    "suggestion_id",
    "action_id",
    "insight_update_id",
    "status",
    "short_term_insight_data",
    "facts",
    "insight_profile_brief",
    "thinking",
    "error",
    "prompt_text",
    "response_text",
    "prompt_name",
    "prompt_version",
    "long_term_insight_storage_path",
    "long_term_insight_sha256",
    "created_at",
    "updated_at",
}

LEGACY_AGENT_FACTS_COLUMNS = {
    "fact_id",
    "user_id",
    "status",
    "facts_profile_brief",
    "error",
    "prompt_text",
    "response_text",
    "llm_output",
    "prompt_name",
    "prompt_version",
    "source_insight_ids",
    "structured_fact_storage_path",
    "structured_fact_sha256",
    "created_at",
    "updated_at",
}

LEGACY_RUN_STEP_COLUMNS = {
    "step_number",
    "step_kind",
    "status",
    "llm_prompt_text",
    "llm_response_text",
    "thinking",
    "tool_name",
    "tool_input_json",
    "tool_output_json",
    "error_code",
    "error_message",
    "created_at",
}


def test_restore_migration_is_harmless_on_fresh_database(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        _assert_legacy_memory_schema(connection)
        _assert_schema_version(
            connection,
            LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
            LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
        )
        assert not _table_exists(connection, "agent_insights_v2_retired")
        _assert_agent_insights_fts_accepts_legacy_rows(connection)


def test_restore_migration_repairs_upgraded_v2_database(
    tmp_path: Path,
    caplog,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, RESTORE_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection, "user-1")
            _insert_suggestion(connection)
            _insert_action(connection)
            _simulate_v2_memory_schema(connection)
            _mark_schema_as_v2_tip(connection)

    caplog.set_level(
        logging.WARNING,
        logger="pantaray_agents.local_runtime.storage.migrations.runner",
    )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        _assert_legacy_memory_schema(connection)
        _assert_schema_version(
            connection,
            LATEST_LOCAL_RUNTIME_MIGRATION_NAME,
            LATEST_LOCAL_RUNTIME_SCHEMA_VERSION,
        )
        assert _table_exists(connection, "agent_insights_v2_retired")
        assert _table_exists(connection, "memory_records")
        assert _scalar(connection, "SELECT COUNT(*) FROM memory_records") == 1
        assert _scalar(connection, "SELECT COUNT(*) FROM agent_insights") == 0
        assert (
            _scalar(connection, "SELECT COUNT(*) FROM agent_insights_v2_retired") == 1
        )
        _assert_agent_insights_fts_accepts_legacy_rows(connection)

    assert "retired context migration version 60" in caplog.text
    assert "continuing to the compatibility restore migration" in caplog.text


def test_newer_schema_version_is_rejected_without_database_mutation(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    newer_version = LATEST_LOCAL_RUNTIME_SCHEMA_VERSION + 1
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                UPDATE schema_versions
                SET current_version = ?, migration_name = ?
                WHERE component = 'local_runtime'
                """,
                (newer_version, f"{newer_version:04d}_newer_build.sql"),
            )
        state_before = connection.execute(
            """
            SELECT current_version, migration_name, checksum
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        journal_count_before = _scalar(
            connection,
            "SELECT COUNT(*) FROM migration_journal",
        )

    with pytest.raises(MigrationError, match="newer than migration plan tip"):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            migrations=migrations,
        )

    with sqlite3.connect(db_path) as connection:
        state_after = connection.execute(
            """
            SELECT current_version, migration_name, checksum
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        journal_count_after = _scalar(
            connection,
            "SELECT COUNT(*) FROM migration_journal",
        )
    assert state_after == state_before
    assert journal_count_after == journal_count_before


def _migrations_before(
    migrations: tuple[MigrationSpec, ...],
    migration_name: str,
) -> tuple[MigrationSpec, ...]:
    for index, migration in enumerate(migrations):
        if migration.name == migration_name:
            return migrations[:index]
    raise AssertionError(f"Migration not found: {migration_name}")


def _assert_legacy_memory_schema(connection: sqlite3.Connection) -> None:
    assert LEGACY_AGENT_INSIGHTS_COLUMNS <= _columns(connection, "agent_insights")
    assert LEGACY_AGENT_FACTS_COLUMNS <= _columns(connection, "agent_facts")
    assert {"insight_update_id"} | LEGACY_RUN_STEP_COLUMNS <= _columns(
        connection,
        "agent_insight_update_run_steps",
    )
    assert {"fact_run_id"} | LEGACY_RUN_STEP_COLUMNS <= _columns(
        connection,
        "agent_fact_structuring_run_steps",
    )
    assert _table_exists(connection, "agent_insight_update_runs")
    assert _table_exists(connection, "agent_fact_structuring_runs")
    assert _table_exists(connection, "memory_search_agent_insights_fts")


def _assert_agent_insights_fts_accepts_legacy_rows(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_user(connection, "user-fts")
        _insert_suggestion(connection, user_id="user-fts", suggestion_id="sug-fts")
        _insert_action(
            connection,
            user_id="user-fts",
            suggestion_id="sug-fts",
            action_id="act-fts",
        )
        connection.execute(
            """
            INSERT INTO agent_insights(
                insight_id,
                user_id,
                suggestion_id,
                action_id,
                insight_update_id,
                status,
                short_term_insight_data,
                facts,
                insight_profile_brief,
                prompt_name,
                prompt_version,
                long_term_insight_storage_path,
                long_term_insight_sha256,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, 'success', ?, 'facts', ?, 'prompt', 'v1', ?, ?, ?, ?)
            """,
            (
                "ins-fts",
                "user-fts",
                "sug-fts",
                "act-fts",
                "upd-fts",
                "restore needle",
                "brief",
                "users/user-fts/insights/long_term.md",
                "sha-fts",
                "2026-07-06T00:00:00Z",
                "2026-07-06T00:00:00Z",
            ),
        )
    assert (
        _scalar(
            connection,
            "SELECT COUNT(*) FROM memory_search_agent_insights_fts WHERE memory_search_agent_insights_fts MATCH 'needle'",
        )
        == 1
    )


def _simulate_v2_memory_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ai;
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ad;
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_au;
        DROP TABLE IF EXISTS memory_search_agent_insights_fts;
        DROP INDEX IF EXISTS idx_agent_insights_user_created;
        ALTER TABLE agent_insights RENAME TO agent_insights_legacy_0057;
        CREATE TABLE agent_insights (
            insight_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            suggestion_id TEXT NOT NULL,
            action_id TEXT,
            status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
            short_term_insight_data TEXT NOT NULL,
            facts TEXT NOT NULL,
            thinking TEXT,
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            prompt_text TEXT,
            response_text TEXT,
            prompt_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id),
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL,
            FOREIGN KEY (user_id, suggestion_id) REFERENCES agent_suggestions(user_id, suggestion_id),
            FOREIGN KEY (user_id, action_id) REFERENCES agent_actions(user_id, action_id)
        );
        DROP TABLE agent_insights_legacy_0057;
        CREATE INDEX idx_agent_insights_user_created
        ON agent_insights(user_id, created_at DESC);
        DROP TABLE agent_fact_structuring_run_steps;
        DROP TABLE agent_fact_structuring_runs;
        DROP TABLE agent_insight_update_run_steps;
        DROP TABLE agent_insight_update_runs;
        DROP TABLE agent_facts;
        CREATE TABLE memory_records (
            record_id TEXT PRIMARY KEY,
            statement TEXT NOT NULL
        );
        INSERT INTO memory_records(record_id, statement)
        VALUES ('record-v2', 'v2 raw material remains');
        """
    )
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
        ) VALUES (?, ?, ?, ?, 'success', ?, 'facts', 'prompt', 'v2', ?, ?)
        """,
        (
            "ins-v2",
            "user-1",
            "sug-1",
            "act-1",
            "v2 retained insight",
            "2026-07-06T00:00:00Z",
            "2026-07-06T00:00:00Z",
        ),
    )


def _mark_schema_as_v2_tip(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE schema_versions
        SET current_version = ?,
            migration_name = ?,
            checksum = 'archive-v2-checksum',
            applied_at = '2026-07-06T00:00:00Z'
        WHERE component = 'local_runtime'
        """,
        (V2_TIP_VERSION, V2_TIP_MIGRATION_NAME),
    )
    for version in range(53, V2_TIP_VERSION + 1):
        connection.execute(
            """
            INSERT INTO migration_journal(
                migration_run_id,
                migration_name,
                component,
                from_version,
                to_version,
                started_at,
                completed_at,
                status,
                app_version,
                checksum
            ) VALUES (?, ?, 'local_runtime', ?, ?, ?, ?, 'completed', 'archive', ?)
            """,
            (
                f"archive-{version}",
                f"{version:04d}_archive_context_v1.sql",
                version - 1,
                version,
                "2026-07-06T00:00:00Z",
                "2026-07-06T00:00:00Z",
                f"archive-checksum-{version}",
            ),
        )


def _insert_suggestion(
    connection: sqlite3.Connection,
    *,
    user_id: str = "user-1",
    suggestion_id: str = "sug-1",
) -> None:
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
        ) VALUES (?, ?, 'success', 'answer', 'prompt', 'v1', 1, 'action_offer', ?, ?)
        """,
        (
            suggestion_id,
            user_id,
            "2026-07-06T00:00:00Z",
            "2026-07-06T00:00:00Z",
        ),
    )


def _insert_action(
    connection: sqlite3.Connection,
    *,
    user_id: str = "user-1",
    suggestion_id: str = "sug-1",
    action_id: str = "act-1",
) -> None:
    if "initial_user_message_id" in _columns(connection, "agent_actions"):
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
                ?, ?, ?, ?, 'success', '{"kind":"scratch"}', 'output',
                'prompt', 'v1', ?, ?
            )
            """,
            (
                action_id,
                user_id,
                suggestion_id,
                f"message-{action_id}",
                "2026-07-06T00:00:00Z",
                "2026-07-06T00:00:00Z",
            ),
        )
    else:
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id,
                user_id,
                suggestion_id,
                status,
                final_output,
                prompt_name,
                prompt_version,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, 'success', 'output', 'prompt', 'v1', ?, ?)
            """,
            (
                action_id,
                user_id,
                suggestion_id,
                "2026-07-06T00:00:00Z",
                "2026-07-06T00:00:00Z",
            ),
        )
    connection.execute(
        """
        UPDATE agent_suggestions
        SET action_command_id = ?
        WHERE user_id = ? AND suggestion_id = ?
        """,
        (f"message-{action_id}", user_id, suggestion_id),
    )


def _assert_schema_version(
    connection: sqlite3.Connection,
    migration_name: str,
    version: int,
) -> None:
    row = connection.execute(
        """
        SELECT current_version, migration_name
        FROM schema_versions
        WHERE component = 'local_runtime'
        """
    ).fetchone()
    assert row == (version, migration_name)


def _columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({table_name})")
    }


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    return (
        connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table_name,),
        ).fetchone()
        is not None
    )


def _scalar(connection: sqlite3.Connection, sql: str) -> object:
    row = connection.execute(sql).fetchone()
    assert row is not None
    return row[0]
