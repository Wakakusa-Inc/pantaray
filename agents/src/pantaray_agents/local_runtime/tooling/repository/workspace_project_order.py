from __future__ import annotations

import sqlite3
from pathlib import Path

from ...storage.migrations import MigrationError
from .common import _configure_connection


def replace_workspace_project_order(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    project_ids: tuple[str, ...],
    now: str,
) -> tuple[str, ...]:
    if len(project_ids) != len(set(project_ids)):
        raise MigrationError(_INVALID_PROJECT_ORDER_MESSAGE)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            active_project_ids = tuple(
                str(row["project_id"])
                for row in connection.execute(
                    """
                    SELECT project_id
                    FROM workspace_projects
                    WHERE user_id = ? AND status = 'active'
                    ORDER BY sort_order ASC, display_name ASC, project_id ASC
                    """,
                    (user_id,),
                ).fetchall()
            )
            if len(project_ids) != len(active_project_ids) or set(project_ids) != set(
                active_project_ids
            ):
                raise MigrationError(_INVALID_PROJECT_ORDER_MESSAGE)
            connection.executemany(
                """
                UPDATE workspace_projects
                SET sort_order = ?, updated_at = ?
                WHERE user_id = ? AND project_id = ? AND status = 'active'
                """,
                (
                    (sort_order, now, user_id, project_id)
                    for sort_order, project_id in enumerate(project_ids)
                ),
            )
    return project_ids


_INVALID_PROJECT_ORDER_MESSAGE = (
    "workspace project order must contain every active project exactly once"
)


__all__ = ["replace_workspace_project_order"]
