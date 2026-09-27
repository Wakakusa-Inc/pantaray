from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import apply_migrations, load_default_migrations

MIGRATION_NAME = "0068_workspace_project_order.sql"
TIMESTAMP = "2026-08-08T00:00:00Z"


def test_workspace_project_order_migration_backfills_each_user(tmp_path: Path) -> None:
    migrations = load_default_migrations()
    migration_index = next(
        index
        for index, migration in enumerate(migrations)
        if migration.name == MIGRATION_NAME
    )
    migrations_through_project_order = migrations[: migration_index + 1]
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations[:migration_index],
    )

    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
        _insert_user(connection, "user-2")
        _insert_project(connection, "project-z", "user-1", "Beta")
        _insert_project(connection, "project-b", "user-1", "Bravo")
        _insert_project(connection, "project-a", "user-1", "Alpha")
        _insert_project(connection, "other-z", "user-2", "Zulu")
        _insert_project(connection, "other-a", "user-2", "Alpha")

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_project_order,
    )

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1]): row
            for row in connection.execute("PRAGMA table_info(workspace_projects)")
        }
        index_names = {
            str(row[1])
            for row in connection.execute("PRAGMA index_list(workspace_projects)")
        }
        index_columns = [
            str(row[2])
            for row in connection.execute(
                "PRAGMA index_info(idx_workspace_projects_user_status_order)"
            )
        ]
        rows = connection.execute(
            """
            SELECT user_id, project_id, sort_order
            FROM workspace_projects
            ORDER BY user_id, sort_order
            """
        ).fetchall()

    assert columns["sort_order"][3] == 1
    assert columns["sort_order"][4] == "0"
    assert "idx_workspace_projects_user_status_order" in index_names
    assert index_columns == [
        "user_id",
        "status",
        "sort_order",
        "display_name",
        "project_id",
    ]
    assert rows == [
        ("user-1", "project-a", 0),
        ("user-1", "project-z", 1),
        ("user-1", "project-b", 2),
        ("user-2", "other-a", 0),
        ("user-2", "other-z", 1),
    ]

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations_through_project_order,
    )


def _insert_user(connection: sqlite3.Connection, user_id: str) -> None:
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', ?, ?)
        """,
        (user_id, TIMESTAMP, TIMESTAMP),
    )


def _insert_project(
    connection: sqlite3.Connection,
    project_id: str,
    user_id: str,
    display_name: str,
) -> None:
    connection.execute(
        """
        INSERT INTO workspace_projects(
            project_id, user_id, display_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (project_id, user_id, display_name, TIMESTAMP, TIMESTAMP),
    )
