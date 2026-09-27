from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import load_default_migrations

from .support import _insert_user, _migrations_before, apply_migrations


def test_upgrade_preserves_existing_consent_and_constrains_initial_mode(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path,
        1_000,
        _migrations_before(migrations, "0106_action_initial_approval_mode.sql"),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, "user-1")
        connection.execute(
            """
            INSERT INTO agent_actions(
                action_id,user_id,initial_user_message_id,execution_target_json,
                status,final_output,prompt_name,prompt_version,created_at,updated_at
            ) VALUES ('action-1','user-1','message-1','{"kind":"scratch"}',
                      'success','done','action','1','2026-09-09','2026-09-09')
            """
        )
        connection.execute(
            """INSERT INTO action_approval_modes VALUES
            ('action-1','user-1','always_allow','2026-09-09','2026-09-09')"""
        )
    apply_migrations(db_path, 1_000, migrations)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute(
            """SELECT initial_approval_mode, approval_mode FROM agent_actions
            JOIN action_approval_modes USING (action_id)"""
        ).fetchone() == (None, "always_allow")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "UPDATE agent_actions SET initial_approval_mode = 'invalid'"
            )
