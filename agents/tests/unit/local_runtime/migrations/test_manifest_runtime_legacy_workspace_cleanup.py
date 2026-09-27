from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import (
    MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME,
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

TIMESTAMP = "2026-03-23T00:00:00Z"


def test_manifest_authority_cutover_removes_legacy_workspace_schema(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )
    with _connection(db_path) as connection:
        _insert_user(connection, "user-1")
        _insert_workspace(connection)
        _insert_approval_preference(
            connection,
            preference_id="preference-global",
            scope_type="global",
            scope_ref=None,
        )
        _insert_capability_grant(
            connection,
            grant_id="grant-global",
            preference_id="preference-global",
            scope_type="global",
            scope_ref=None,
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(
            migrations, MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME
        ),
    )

    with _connection(db_path) as connection:
        assert "workspaces" not in _table_names(connection)
        assert "allowed_roots" not in _table_names(connection)
        assert _approval_preference_rows(connection) == [
            ("preference-global", "global", None)
        ]
        assert _capability_grant_rows(connection) == [("grant-global", "global", None)]
        assert "REFERENCES workspaces" not in _table_sql(
            connection,
            "approval_preferences",
        )
        assert "scope_type = 'global'" in _table_sql(connection, "approval_preferences")
        assert "scope_type = 'global'" in _table_sql(connection, "capability_grants")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def _connection(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    _configure_connection(connection, busy_timeout_ms=1_000)
    return connection


def _insert_workspace(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO allowed_roots(
            root_id, user_id, bookmark_data, normalized_path, access_mode,
            created_at, updated_at
        ) VALUES ('root-1', 'user-1', X'00', '/tmp/repo', 'read_write', ?, ?)
        """,
        (TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO workspaces(
            workspace_id, user_id, kind, root_id, normalized_path, repo_root_path,
            vcs_kind, toolchain_hint_json, trust_level, default_exec_policy_json,
            created_at, updated_at
        ) VALUES (
            'workspace-1', 'user-1', 'user_repo', 'root-1', '/tmp/repo',
            '/tmp/repo', 'git', '{}', 'user_selected', '{}', ?, ?
        )
        """,
        (TIMESTAMP, TIMESTAMP),
    )


def _insert_approval_preference(
    connection: sqlite3.Connection,
    *,
    preference_id: str,
    scope_type: str,
    scope_ref: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO approval_preferences(
            preference_id, user_id, scope_type, scope_ref, approval_mode,
            applies_to_json, created_at, updated_at, updated_by, revoked_at
        ) VALUES (
            ?, 'user-1', ?, ?, 'always_allow',
            '["workspace_edit_and_command"]', ?, ?, 'user', NULL
        )
        """,
        (preference_id, scope_type, scope_ref, TIMESTAMP, TIMESTAMP),
    )


def _insert_capability_grant(
    connection: sqlite3.Connection,
    *,
    grant_id: str,
    preference_id: str,
    scope_type: str,
    scope_ref: str | None,
) -> None:
    connection.execute(
        """
        INSERT INTO capability_grants(
            grant_id, user_id, preference_id, capability, scope_type, scope_ref,
            grant_source, granted_at, granted_by, revoked_at, revocation_reason
        ) VALUES (
            ?, 'user-1', ?, 'workspace_edit_and_command', ?, ?,
            'settings', ?, 'user', NULL, NULL
        )
        """,
        (grant_id, preference_id, scope_type, scope_ref, TIMESTAMP),
    )


def _approval_preference_rows(
    connection: sqlite3.Connection,
) -> list[tuple[str, str, str | None]]:
    return connection.execute(
        "SELECT preference_id, scope_type, scope_ref FROM approval_preferences"
    ).fetchall()


def _capability_grant_rows(
    connection: sqlite3.Connection,
) -> list[tuple[str, str, str | None]]:
    return connection.execute(
        "SELECT grant_id, scope_type, scope_ref FROM capability_grants"
    ).fetchall()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in rows}


def _table_sql(connection: sqlite3.Connection, table_name: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    assert row is not None
    return str(row[0])
