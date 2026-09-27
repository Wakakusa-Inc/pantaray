from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.migrations.runner import apply_migrations
from pantaray_agents.local_runtime.storage.migrations.specs import (
    MigrationSpec,
    load_default_migrations,
)


def test_agent_run_step_tables_repair_migration_restores_missing_step_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    migration_48 = _migration_named(
        migrations,
        "0048_workspace_manifest_context_snapshot.sql",
    )
    migration_49 = _migration_named(
        migrations,
        "0049_agent_run_step_tables_repair.sql",
    )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations,
            "0048_workspace_manifest_context_snapshot.sql",
        ),
    )

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection=connection, busy_timeout_ms=1_000)
        with connection:
            connection.execute("DROP TABLE agent_insight_update_run_steps")
            connection.execute("DROP TABLE agent_fact_structuring_run_steps")

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection=connection, busy_timeout_ms=1_000)
        insight_step_columns = _table_columns(
            connection,
            "agent_insight_update_run_steps",
        )
        fact_step_columns = _table_columns(
            connection,
            "agent_fact_structuring_run_steps",
        )
        schema_row = connection.execute(
            """
            SELECT current_version, migration_name, checksum
            FROM schema_versions
            WHERE component = 'local_runtime'
            """
        ).fetchone()
        repair_journal_row = connection.execute(
            """
            SELECT from_version, to_version, status
            FROM migration_journal
            WHERE migration_name = ?
            """,
            (migration_49.name,),
        ).fetchone()

    expected_columns = {
        "step_number",
        "step_kind",
        "status",
        "llm_prompt_text",
        "llm_response_text",
        "tool_name",
        "tool_input_json",
        "tool_output_json",
        "error_code",
        "error_message",
        "created_at",
    }
    assert {"insight_update_id"} | expected_columns <= insight_step_columns
    assert {"fact_run_id"} | expected_columns <= fact_step_columns
    latest_migration = migrations[-1]
    assert schema_row == (
        latest_migration.version,
        latest_migration.name,
        latest_migration.checksum_sha256,
    )
    assert repair_journal_row == (
        migration_48.version,
        migration_49.version,
        "completed",
    )


def _migration_named(
    migrations: tuple[MigrationSpec, ...],
    name: str,
) -> MigrationSpec:
    return next(migration for migration in migrations if migration.name == name)


def _migrations_through(
    migrations: tuple[MigrationSpec, ...],
    name: str,
) -> tuple[MigrationSpec, ...]:
    index = next(
        index for index, migration in enumerate(migrations) if migration.name == name
    )
    return migrations[: index + 1]


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {
        row[1]
        for row in connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    }
