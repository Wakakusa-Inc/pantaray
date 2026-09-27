from __future__ import annotations

import sqlite3
from pathlib import Path

from ...storage.migrations import MigrationError
from ...storage.users import ensure_user_row
from .common import _configure_connection


def delete_workspace_organization(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    organization_id: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=user_id)
            _delete_workspace_item(
                connection=connection,
                table_name="workspace_organizations",
                id_column="organization_id",
                user_id=user_id,
                item_id=organization_id,
                item_name="workspace organization",
            )


def delete_workspace_project(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    project_id: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=user_id)
            _delete_workspace_item(
                connection=connection,
                table_name="workspace_projects",
                id_column="project_id",
                user_id=user_id,
                item_id=project_id,
                item_name="workspace project",
            )


def delete_workspace_folder(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    folder_id: str,
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=user_id)
            _delete_workspace_item(
                connection=connection,
                table_name="workspace_folders",
                id_column="folder_id",
                user_id=user_id,
                item_id=folder_id,
                item_name="workspace folder",
            )


def _delete_workspace_item(
    *,
    connection: sqlite3.Connection,
    table_name: str,
    id_column: str,
    user_id: str,
    item_id: str,
    item_name: str,
) -> None:
    cursor = connection.execute(
        f"""
        DELETE FROM {table_name}
        WHERE user_id = ? AND {id_column} = ? AND status = 'active'
        """,
        (user_id, item_id),
    )
    if cursor.rowcount != 1:
        raise MigrationError(f"{item_name} not found: {item_id}")
