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

from .support import _insert_user, _migrations_through

BUSY_TIMEOUT_MS = 1_000
V93_MIGRATION_NAME = "0093_action_subagent_processes.sql"
TIMESTAMP = "2026-09-01T00:00:00Z"
RELEASED_AT = "2026-09-01T00:01:00Z"


def _insert_action(
    connection: sqlite3.Connection, action_id: str, user_id: str
) -> None:
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id,user_id,initial_user_message_id,execution_target_json,
            status,final_output,prompt_name,prompt_version,created_at,updated_at
        ) VALUES (?,?,?,'{"kind":"scratch"}',
                  'processing','','action','1',?,?)
        """,
        (action_id, user_id, f"message-{action_id}", TIMESTAMP, TIMESTAMP),
    )


def _insert_process(
    connection: sqlite3.Connection,
    process_id: str,
    *,
    user_id: str,
    action_id: str,
    kind: str,
    parent_process_id: str | None = None,
    status: str = "running",
) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id,user_id,kind,status,action_id,started_at,updated_at,
            heartbeat_at,next_event_seq,parent_process_id
        ) VALUES (?,?,?,?,?,?,?,?,1,?)
        """,
        (
            process_id,
            user_id,
            kind,
            status,
            action_id,
            TIMESTAMP,
            TIMESTAMP,
            TIMESTAMP,
            parent_process_id,
        ),
    )


def _seed_lineage(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    parent_process_id: str,
    child_process_id: str,
) -> None:
    _insert_user(connection, user_id)
    _insert_action(connection, action_id, user_id)
    _insert_process(
        connection,
        parent_process_id,
        user_id=user_id,
        action_id=action_id,
        kind="action",
    )
    _insert_process(
        connection,
        child_process_id,
        user_id=user_id,
        action_id=action_id,
        kind="action_subagent",
        parent_process_id=parent_process_id,
    )


def _insert_claim(
    connection: sqlite3.Connection,
    claim_id: str,
    *,
    user_id: str = "user-1",
    action_id: str = "action-1",
    parent_process_id: str = "parent-1",
    child_process_id: str = "child-1",
    resource_kind: str = "workspace_path",
    root_identity: str = "workspace-root",
    normalized_key: str | None = None,
    released_at: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO action_subagent_resource_claims(
            claim_id,user_id,action_id,parent_process_id,child_process_id,
            resource_kind,root_identity,normalized_key,acquired_at,released_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (
            claim_id,
            user_id,
            action_id,
            parent_process_id,
            child_process_id,
            resource_kind,
            root_identity,
            normalized_key or f"path/{claim_id}",
            TIMESTAMP,
            released_at,
        ),
    )


def test_v94_upgrades_existing_lineage_and_preserves_release_until_user_erasure(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_through(migrations, V93_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _seed_lineage(
                connection,
                user_id="user-1",
                action_id="action-1",
                parent_process_id="parent-1",
                child_process_id="child-1",
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)

    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_claim(connection, "claim-1", resource_kind="external_resource")
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name LIKE 'idx_action_subagent_claims_%'"
            )
        }
        connection.execute(
            "UPDATE action_subagent_resource_claims SET released_at=? "
            "WHERE claim_id='claim-1'",
            (RELEASED_AT,),
        )
        connection.execute(
            "UPDATE action_subagent_resource_claims SET released_at=? "
            "WHERE claim_id='claim-1'",
            (RELEASED_AT,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="identity is immutable"):
            connection.execute(
                "UPDATE action_subagent_resource_claims SET child_process_id='parent-1' "
                "WHERE claim_id='claim-1'"
            )
        for released_at in (None, "2026-09-01T00:02:00Z"):
            with pytest.raises(sqlite3.IntegrityError, match="release is immutable"):
                connection.execute(
                    "UPDATE action_subagent_resource_claims SET released_at=? "
                    "WHERE claim_id='claim-1'",
                    (released_at,),
                )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("DELETE FROM processes WHERE process_id='child-1'")

        connection.execute("DELETE FROM users WHERE user_id='user-1'")
        remaining = connection.execute(
            "SELECT COUNT(*) FROM action_subagent_resource_claims"
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert indexes == {
        "idx_action_subagent_claims_child",
        "idx_action_subagent_claims_parent",
        "idx_action_subagent_claims_parent_active",
    }
    assert remaining == (0,)
    assert violations == []


def test_v94_rejects_invalid_lineage_and_more_than_64_claims(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _seed_lineage(
                connection,
                user_id="user-1",
                action_id="action-1",
                parent_process_id="parent-1",
                child_process_id="child-1",
            )
            _insert_process(
                connection,
                "other-parent",
                user_id="user-1",
                action_id="action-1",
                kind="action",
                status="completed",
            )
            _seed_lineage(
                connection,
                user_id="user-2",
                action_id="action-2",
                parent_process_id="parent-2",
                child_process_id="child-2",
            )

        invalid_lineages = (
            {"child_process_id": "missing"},
            {
                "user_id": "user-2",
                "action_id": "action-2",
                "parent_process_id": "parent-1",
            },
            {"parent_process_id": "other-parent"},
            {"child_process_id": "parent-1"},
        )
        for index, overrides in enumerate(invalid_lineages):
            with pytest.raises(sqlite3.IntegrityError, match="lineage is invalid"):
                _insert_claim(connection, f"invalid-{index}", **overrides)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_claim(connection, "invalid-kind", resource_kind="unknown")
        with pytest.raises(sqlite3.IntegrityError, match="must be acquired active"):
            _insert_claim(connection, "pre-released", released_at=RELEASED_AT)

        for index in range(64):
            _insert_claim(connection, f"claim-{index}")
        connection.execute(
            "UPDATE action_subagent_resource_claims SET released_at=? "
            "WHERE claim_id='claim-0'",
            (RELEASED_AT,),
        )
        with pytest.raises(sqlite3.IntegrityError, match="claim limit exceeded"):
            _insert_claim(connection, "claim-64")

        claim_count = connection.execute(
            "SELECT COUNT(*) FROM action_subagent_resource_claims"
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert claim_count == (64,)
    assert violations == []
