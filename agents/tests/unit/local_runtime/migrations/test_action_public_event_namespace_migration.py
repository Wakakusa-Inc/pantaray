from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_invalidation_events import (
    ActionInvalidationIdentityError,
    ActionInvalidationTransactionError,
    append_action_invalidation_event,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
    PublicProcessEventActionOwnerError,
    PublicProcessEventConflictError,
    append_public_process_event,
)
from pantaray_agents.schema.action_conversation import (
    ActionMessageAcceptedEventData,
    ActionMessageAdoptedEventData,
)

from .support import (
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 1_000
MIGRATION_NAME = "0087_action_public_event_namespace.sql"
TIMESTAMP = "2026-08-29T00:00:00Z"


def _apply_before_v87(db_path: Path) -> None:
    migrations = _migrations_before(load_default_migrations(), MIGRATION_NAME)
    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)


def _configure(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    configure_connection(connection, BUSY_TIMEOUT_MS)


def _seed_owners(connection: sqlite3.Connection) -> None:
    for user_id in ("user-1", "user-2"):
        _insert_user(connection, user_id)
    connection.execute(
        "INSERT INTO agent_suggestions(suggestion_id,user_id,status,created_at,updated_at) "
        "VALUES (?,?,'success',?,?)",
        ("suggestion-1", "user-1", TIMESTAMP, TIMESTAMP),
    )
    connection.executemany(
        "INSERT INTO agent_actions(action_id,user_id,suggestion_id,"
        "initial_user_message_id,execution_target_json,status,final_output,"
        "prompt_name,prompt_version,created_at,updated_at) "
        "VALUES (?,?,?,?,'{\"kind\":\"scratch\"}','success','','action','1',?,?)",
        (
            ("action-1", "user-1", "suggestion-1", "message-1", TIMESTAMP, TIMESTAMP),
            ("action-2", "user-1", None, "message-2", TIMESTAMP, TIMESTAMP),
        ),
    )


def _insert_event(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    suggestion_id: str | None,
    user_id: str,
    action_id: str | None,
    sequence: int,
    event_name: str,
) -> None:
    connection.execute(
        "INSERT INTO agent_process_events(event_id,suggestion_id,user_id,action_id,"
        "sequence,event_name,payload,created_at) VALUES (?,?,?,?,?,?,'{}',?)",
        (
            event_id,
            suggestion_id,
            user_id,
            action_id,
            sequence,
            event_name,
            TIMESTAMP,
        ),
    )


def _event_rows(connection: sqlite3.Connection) -> list[tuple[object, ...]]:
    rows = connection.execute(
        "SELECT event_id,suggestion_id,user_id,action_id,sequence,event_name,payload,"
        "created_at FROM agent_process_events ORDER BY event_id"
    ).fetchall()
    return [tuple(row) for row in rows]


def test_v87_upgrades_history_and_keeps_legacy_dual_owner_producer(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v87(db_path)
    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        _seed_owners(connection)
        _insert_event(
            connection,
            event_id="suggestion-event",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id=None,
            sequence=1,
            event_name="process_started",
        )
        _insert_event(
            connection,
            event_id="dual-event",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id="action-1",
            sequence=2,
            event_name="action_requested",
        )
        _insert_event(
            connection,
            event_id="standalone-event",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-2",
            sequence=1,
            event_name="process_completed",
        )
        before = _event_rows(connection)

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        assert _event_rows(connection) == before
        sequence = append_public_process_event(
            connection=connection,
            event_id="legacy-producer-event",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id="action-1",
            event_name="action_requested",
            payload={},
            created_at=TIMESTAMP,
        )
        _insert_event(
            connection,
            event_id="accepted-event",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-1",
            sequence=4,
            event_name="action_message_accepted",
        )
        _insert_event(
            connection,
            event_id="separate-suggestion-event",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id=None,
            sequence=4,
            event_name="suggestion_chunk",
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert sequence == 3


def test_v87_fresh_schema_enforces_namespace_owner_and_sequence(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        _seed_owners(connection)
        _insert_event(
            connection,
            event_id="accepted",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-1",
            sequence=1,
            event_name="action_message_accepted",
        )
        _insert_event(
            connection,
            event_id="other-action",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-2",
            sequence=1,
            event_name="action_message_adopted",
        )
        _insert_event(
            connection,
            event_id="historical-dual",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id="action-1",
            sequence=2,
            event_name="action_requested",
        )

        def reject(
            *,
            event_id: str,
            suggestion_id: str | None,
            user_id: str,
            action_id: str | None,
            sequence: int,
            event_name: str,
        ) -> None:
            with pytest.raises(sqlite3.IntegrityError):
                _insert_event(
                    connection,
                    event_id=event_id,
                    suggestion_id=suggestion_id,
                    user_id=user_id,
                    action_id=action_id,
                    sequence=sequence,
                    event_name=event_name,
                )

        reject(
            event_id="new-dual",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id="action-1",
            sequence=3,
            event_name="action_message_accepted",
        )
        reject(
            event_id="new-suggestion-only",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id=None,
            sequence=3,
            event_name="action_message_adopted",
        )
        reject(
            event_id="ownerless",
            suggestion_id=None,
            user_id="user-1",
            action_id=None,
            sequence=3,
            event_name="error",
        )
        reject(
            event_id="cross-action-owner",
            suggestion_id=None,
            user_id="user-2",
            action_id="action-1",
            sequence=3,
            event_name="action_message_accepted",
        )
        reject(
            event_id="cross-suggestion-owner",
            suggestion_id="suggestion-1",
            user_id="user-2",
            action_id=None,
            sequence=3,
            event_name="suggestion_chunk",
        )
        reject(
            event_id="duplicate-action-sequence",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-1",
            sequence=1,
            event_name="action_message_adopted",
        )
        reject(
            event_id="duplicate-suggestion-sequence",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id=None,
            sequence=2,
            event_name="suggestion_chunk",
        )
        reject(
            event_id="public-action-step",
            suggestion_id=None,
            user_id="user-1",
            action_id="action-1",
            sequence=3,
            event_name="action_step",
        )

        indexes = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index'"
            )
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='agent_process_events'"
            ).fetchone()[0]
        )
        assert "action_message_accepted" in table_sql
        assert "action_message_adopted" in table_sql
        assert "action_step" not in table_sql
        assert (
            "WHERE action_id IS NOT NULL"
            in indexes["uq_agent_process_events_action_sequence"]
        )
        assert "uq_agent_process_events_standalone_sequence" not in indexes
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_action_invalidation_uses_action_namespace_and_identity_only_payload(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        _seed_owners(connection)
        _insert_event(
            connection,
            event_id="historical-dual",
            suggestion_id="suggestion-1",
            user_id="user-1",
            action_id="action-1",
            sequence=2,
            event_name="action_requested",
        )
        connection.execute(
            """
            INSERT INTO processes(
                process_id, user_id, kind, status, suggestion_id, action_id,
                started_at, updated_at, completed_at, heartbeat_at, next_event_seq
            ) VALUES (
                'process-1', 'user-1', 'action', 'completed', 'suggestion-1',
                'action-1', ?, ?, ?, ?, 1
            )
            """,
            (TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
        )
        connection.execute(
            """
            INSERT INTO agent_action_steps(
                step_id, action_id, user_id, step_number, local_step_number,
                short_step_id, step_type, step_name, status, goal_handle,
                user_request_text, user_message_id, user_message_json, created_at,
                accepted_sequence, adopted_process_id
            ) VALUES (
                'step-3', 'action-1', 'user-1', 3, 3, 'S-3-USER',
                'user_request', 'User Request', 'success', 'S', 'Continue',
                'message-3', '{}', ?, 3, 'process-1'
            )
            """,
            (TIMESTAMP,),
        )
        accepted = ActionMessageAcceptedEventData(
            action_id="action-1",
            message_id="message-3",
            step_id="step-3",
        )
        accepted_sequence = append_action_invalidation_event(
            connection=connection,
            event_id="accepted-4",
            user_id="user-1",
            data=accepted,
            created_at=TIMESTAMP,
        )
        adopted_sequence = append_action_invalidation_event(
            connection=connection,
            event_id="adopted-5",
            user_id="user-1",
            data=ActionMessageAdoptedEventData(
                action_id="action-1",
                message_id="message-3",
                step_id="step-3",
                process_id="process-1",
            ),
            created_at=TIMESTAMP,
        )
        replay_sequence = append_action_invalidation_event(
            connection=connection,
            event_id="accepted-4",
            user_id="user-1",
            data=accepted,
            created_at=TIMESTAMP,
        )
        rows = connection.execute(
            """
            SELECT suggestion_id, action_id, sequence, event_name, payload
            FROM agent_process_events
            WHERE event_id IN ('accepted-4', 'adopted-5')
            ORDER BY sequence
            """
        ).fetchall()

        with pytest.raises(PublicProcessEventConflictError):
            append_action_invalidation_event(
                connection=connection,
                event_id="accepted-4",
                user_id="user-1",
                data=accepted,
                created_at="2026-08-29T00:00:01Z",
            )
        invalid_events = (
            ActionMessageAcceptedEventData(
                action_id="action-1", message_id="message-3", step_id="missing-step"
            ),
            ActionMessageAcceptedEventData(
                action_id="action-2", message_id="message-3", step_id="step-3"
            ),
            ActionMessageAcceptedEventData(
                action_id="action-1", message_id="other-message", step_id="step-3"
            ),
            ActionMessageAdoptedEventData(
                action_id="action-1",
                message_id="message-3",
                step_id="step-3",
                process_id="other-process",
            ),
        )
        for index, invalid_event in enumerate(invalid_events):
            with pytest.raises(ActionInvalidationIdentityError):
                append_action_invalidation_event(
                    connection=connection,
                    event_id=f"invalid-{index}",
                    user_id="user-1",
                    data=invalid_event,
                    created_at=TIMESTAMP,
                )
        with pytest.raises(ActionInvalidationIdentityError):
            append_action_invalidation_event(
                connection=connection,
                event_id="cross-owner",
                user_id="user-2",
                data=accepted,
                created_at=TIMESTAMP,
            )
        with pytest.raises(PublicProcessEventActionOwnerError):
            append_public_process_event(
                connection=connection,
                event_id="generic-cross-owner",
                suggestion_id=None,
                user_id="user-2",
                action_id="action-1",
                event_name="process_completed",
                payload={},
                created_at=TIMESTAMP,
            )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM agent_process_events WHERE event_id LIKE 'invalid-%'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM agent_process_events").fetchone()[
                0
            ]
            == 3
        )

    assert accepted_sequence == 3
    assert adopted_sequence == 4
    assert replay_sequence == 3
    assert [tuple(row[:4]) for row in rows] == [
        (None, "action-1", 3, "action_message_accepted"),
        (None, "action-1", 4, "action_message_adopted"),
    ]
    assert json.loads(str(rows[0]["payload"])) == {
        "data": {
            "action_id": "action-1",
            "message_id": "message-3",
            "step_id": "step-3",
        }
    }
    assert json.loads(str(rows[1]["payload"])) == {
        "data": {
            "action_id": "action-1",
            "message_id": "message-3",
            "step_id": "step-3",
            "process_id": "process-1",
        }
    }


def test_action_invalidation_requires_transaction_and_canonical_step(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    accepted = ActionMessageAcceptedEventData(
        action_id="missing-action",
        message_id="message-1",
        step_id="step-1",
    )
    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        with pytest.raises(ActionInvalidationTransactionError):
            append_action_invalidation_event(
                connection=connection,
                event_id="accepted-1",
                user_id="user-1",
                data=accepted,
                created_at=TIMESTAMP,
            )
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(ActionInvalidationIdentityError):
            append_action_invalidation_event(
                connection=connection,
                event_id="accepted-1",
                user_id="user-1",
                data=accepted,
                created_at=TIMESTAMP,
            )


@pytest.mark.parametrize("invalid_history", ("sequence_collision", "cross_owner"))
def test_v87_rolls_back_invalid_history(
    tmp_path: Path,
    invalid_history: str,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_v87(db_path)
    with sqlite3.connect(db_path) as connection:
        _configure(connection)
        _seed_owners(connection)
        if invalid_history == "sequence_collision":
            _insert_event(
                connection,
                event_id="dual",
                suggestion_id="suggestion-1",
                user_id="user-1",
                action_id="action-1",
                sequence=1,
                event_name="action_requested",
            )
            _insert_event(
                connection,
                event_id="standalone",
                suggestion_id=None,
                user_id="user-1",
                action_id="action-1",
                sequence=1,
                event_name="process_completed",
            )
        else:
            _insert_event(
                connection,
                event_id="cross-owner",
                suggestion_id=None,
                user_id="user-2",
                action_id="action-1",
                sequence=1,
                event_name="process_completed",
            )
        before = _event_rows(connection)

    with pytest.raises(MigrationError, match=MIGRATION_NAME):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component='local_runtime'"
        ).fetchone()
        indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        table_sql = str(
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' "
                "AND name='agent_process_events'"
            ).fetchone()[0]
        )
        assert _event_rows(connection) == before
        assert version == (86,)
        assert "action_message_accepted" not in table_sql
        assert "uq_agent_process_events_standalone_sequence" in indexes
        assert "uq_agent_process_events_action_sequence" not in indexes
        assert connection.execute(
            "SELECT status FROM migration_journal WHERE to_version=87"
        ).fetchone() == ("failed",)
