from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from .support import (
    _configure_connection,
    apply_migrations,
    load_default_migrations,
)

TIMESTAMP = "2026-03-23T00:00:00Z"


def test_workspace_settings_use_join_tables_for_context_links(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with _connection(db_path) as connection:
        _insert_user(connection)
        _insert_user(connection, user_id="user-2")
        assert "organization_id" not in _table_columns(connection, "workspace_projects")
        assert "organization_id" not in _table_columns(connection, "workspace_folders")
        assert "project_id" not in _table_columns(connection, "workspace_folders")

        _insert_organization(connection, "org-1", "user-1", "Org")
        _insert_organization(connection, "org-2", "user-2", "Other Org")
        _insert_project(connection, "project-1")
        _insert_project_organization(connection, "project-1", "org-1")

        with pytest.raises(sqlite3.IntegrityError):
            _insert_project_organization(connection, "project-1", "org-2")


def _connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    _configure_connection(connection, busy_timeout_ms=1_000)
    return connection


def _insert_user(connection: sqlite3.Connection, user_id: str = "user-1") -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', ?, ?)
        """,
        (user_id, TIMESTAMP, TIMESTAMP),
    )


def _insert_organization(
    connection: sqlite3.Connection,
    organization_id: str,
    user_id: str,
    display_name: str,
) -> None:
    connection.execute(
        """
        INSERT INTO workspace_organizations(
            organization_id, user_id, display_name, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (organization_id, user_id, display_name, TIMESTAMP, TIMESTAMP),
    )


def _insert_project(connection: sqlite3.Connection, project_id: str) -> None:
    connection.execute(
        """
        INSERT INTO workspace_projects(
            project_id, user_id, display_name, created_at, updated_at
        ) VALUES (?, 'user-1', 'Project', ?, ?)
        """,
        (project_id, TIMESTAMP, TIMESTAMP),
    )


def _insert_project_organization(
    connection: sqlite3.Connection,
    project_id: str,
    organization_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO workspace_project_organizations(
            user_id, project_id, organization_id, created_at
        ) VALUES ('user-1', ?, ?, ?)
        """,
        (project_id, organization_id, TIMESTAMP),
    )


def _table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row[1]) for row in rows}
