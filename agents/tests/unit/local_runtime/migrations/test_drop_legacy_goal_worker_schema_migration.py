from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _migrations_through

BUSY_TIMEOUT_MS = 1_000
V94_MIGRATION_NAME = "0094_action_subagent_resource_claims.sql"
V95_MIGRATION_NAME = "0095_drop_legacy_goal_worker_schema.sql"

RETIRED_TABLES = (
    "action_desires",
    "action_check_items",
    "action_goals",
    "action_requirements",
    "action_completed_goals",
)
RETIRED_COLUMNS = (
    "requirement_handle",
    "parallel_group_id",
    "parallel_depth",
    "parallel_index",
)


def _open(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    configure_connection(connection, BUSY_TIMEOUT_MS)
    return connection


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _step_columns(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(agent_action_steps)")
    }


@pytest.fixture
def v94_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(load_default_migrations(), V94_MIGRATION_NAME),
    )
    return db_path


def test_v94_still_carries_the_legacy_goal_worker_schema(v94_db: Path) -> None:
    with _open(v94_db) as connection:
        assert RETIRED_TABLES[0] in _table_names(connection)
        assert RETIRED_COLUMNS[0] in _step_columns(connection)


def test_v95_drops_the_legacy_plan_tables_and_step_columns(v94_db: Path) -> None:
    with _open(v94_db) as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            """
            INSERT INTO action_desires(
                desire_id, user_id, action_id, desire_type, content,
                position, created_at, updated_at
            ) VALUES ('D1','user-1','act-1','explicit','legacy',1,?,?)
            """,
            ("2026-09-03T00:00:00Z", "2026-09-03T00:00:00Z"),
        )
        connection.execute(
            """
            INSERT INTO agent_action_steps(
                step_id, action_id, user_id, step_type, step_name, status,
                retry_count, prompt_tokens, completion_tokens, created_at,
                step_number, local_step_number, short_step_id,
                goal_handle, requirement_handle,
                parallel_group_id, parallel_depth, parallel_index
            ) VALUES (
                'step-1','act-1','user-1','tool_execution','tool::read','success',
                0,0,0,?,1,1,'S-1-TOOL','S','R1','group-1',2,0
            )
            """,
            ("2026-09-03T00:00:00Z",),
        )
        connection.commit()

    apply_migrations(
        db_path=v94_db,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(load_default_migrations(), V95_MIGRATION_NAME),
    )

    with _open(v94_db) as connection:
        assert (
            connection.execute("SELECT migration_name FROM schema_versions").fetchone()[
                0
            ]
            == V95_MIGRATION_NAME
        )
        tables = _table_names(connection)
        assert all(name not in tables for name in RETIRED_TABLES)
        columns = _step_columns(connection)
        assert all(name not in columns for name in RETIRED_COLUMNS)
        # scope_handle として v2 で転用されている列は残す。
        assert "goal_handle" in columns
        assert connection.execute(
            "SELECT goal_handle, status FROM agent_action_steps WHERE step_id = 'step-1'"
        ).fetchone() == ("S", "success")
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v95_is_idempotent_on_reapply(v94_db: Path) -> None:
    for _ in range(2):
        apply_migrations(
            db_path=v94_db,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            migrations=_migrations_through(
                load_default_migrations(), V95_MIGRATION_NAME
            ),
        )

    with _open(v94_db) as connection:
        assert (
            connection.execute(
                "SELECT current_version FROM schema_versions"
            ).fetchone()[0]
            == 95
        )
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
