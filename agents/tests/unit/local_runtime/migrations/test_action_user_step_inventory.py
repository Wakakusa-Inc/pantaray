import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.action_user_step_inventory import (
    load_action_user_step_inventory,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import (
    _insert_user,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

TIMESTAMP = "2026-08-29T00:00:00Z"
PRE_CONTRACT_MIGRATION_NAME = "0088_owner_queued_job_poll_index.sql"


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db_path = tmp_path / "runtime.db"
    migrations = _migrations_through(
        load_default_migrations(), PRE_CONTRACT_MIGRATION_NAME
    )
    apply_migrations(db_path, 1_000, migrations)
    active = sqlite3.connect(db_path)
    configure_connection(active, 1_000)
    yield active
    active.close()


def _insert_scope(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    _insert_user(connection, "user-2")
    connection.executemany(
        "INSERT INTO agent_actions(action_id,user_id,initial_user_message_id,"
        "execution_target_json,status,final_output,prompt_name,prompt_version,"
        'created_at,updated_at) VALUES (?,?,?,\'{"kind":"scratch"}\','
        "'processing','','action','1',?,?)",
        (
            ("action-1", "user-1", "message-1", TIMESTAMP, TIMESTAMP),
            ("action-2", "user-2", "message-2", TIMESTAMP, TIMESTAMP),
        ),
    )


def _insert_step(
    connection: sqlite3.Connection,
    step_id: str,
    *,
    action_id: str = "action-1",
    user_id: str = "user-1",
    step_number: int = 1,
    created_at: str = TIMESTAMP,
) -> None:
    connection.execute(
        "INSERT INTO agent_action_steps(step_id,action_id,user_id,step_number,"
        "local_step_number,short_step_id,step_type,step_name,status,"
        "user_request_text,user_message_id,user_message_json,created_at,goal_handle) VALUES "
        "(?1,?2,?3,?4,?4,printf('S-%d-USER',?4),'user_request','user request',"
        "'success',' request-'||?1||' ','message-'||?1,'{\"version\":1}',?5,'S')",
        (step_id, action_id, user_id, step_number, created_at),
    )


def test_inventory_is_read_only_single_query_and_assigns_stable_action_order(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_step(connection, "step-z", step_number=2)
        _insert_step(connection, "step-b", created_at="2026-08-27T23:30:00Z")
        _insert_step(connection, "step-a", created_at="2026-08-28T00:00:00+01:00")
        _insert_step(connection, "step-d", created_at="2026-08-27T23:30:00.000002Z")
        _insert_step(connection, "step-c", created_at="2026-08-27T23:30:00.000001Z")
        _insert_step(connection, "step-tie-b", created_at="2026-08-27T23:30:01Z")
        _insert_step(connection, "step-tie-a", created_at="2026-08-28T00:30:01+01:00")
        connection.execute(
            "UPDATE agent_action_steps SET user_message_id=NULL,"
            "user_message_json=NULL WHERE step_id='step-a'"
        )
        _insert_step(connection, "step-x", action_id="action-2", user_id="user-2")
    statements: list[str] = []
    connection.execute("PRAGMA query_only = ON")
    connection.set_trace_callback(statements.append)

    inventory = load_action_user_step_inventory(connection)

    connection.set_trace_callback(None)
    assert [
        (evidence.action_id, evidence.step_id, evidence.accepted_sequence)
        for evidence in inventory
    ] == [
        ("action-1", "step-a", 1),
        ("action-1", "step-b", 2),
        ("action-1", "step-c", 3),
        ("action-1", "step-d", 4),
        ("action-1", "step-tie-a", 5),
        ("action-1", "step-tie-b", 6),
        ("action-1", "step-z", 7),
        ("action-2", "step-x", 1),
    ]
    assert (inventory[0].user_message_id, inventory[0].user_message_json) == (
        None,
        None,
    )
    assert inventory[0].initial_user_message_id == "message-1"
    assert inventory[0].created_at == "2026-08-27T23:00:00.000000Z"
    assert inventory[0].suggestion_id is None
    assert inventory[0].user_request_text == " request-step-a "
    selects = [sql for sql in statements if sql.lstrip().startswith("SELECT")]
    assert len(selects) == 1
    assert "jobs" not in selects[0] and "payload" not in selects[0]


def test_inventory_orders_years_below_1000_chronologically(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_step(connection, "step-year-10", created_at="0010-01-01T00:00:00Z")
        _insert_step(connection, "step-year-2", created_at="0002-01-01T00:00:00Z")

    inventory = load_action_user_step_inventory(connection)

    assert [(entry.step_id, entry.created_at) for entry in inventory[:2]] == [
        ("step-year-2", "0002-01-01T00:00:00.000000Z"),
        ("step-year-10", "0010-01-01T00:00:00.000000Z"),
    ]


def test_inventory_scope_ignores_unrelated_canonical_pending_user(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_step(connection, "legacy-step")
        connection.execute(
            """
            INSERT INTO agent_action_steps(
                step_id, action_id, user_id, step_type, step_name, status,
                goal_handle, user_request_text, user_message_id, user_message_json,
                accepted_sequence, created_at
            ) VALUES (
                'pending-step', 'action-2', 'user-2', 'user_request',
                'user request', 'success', 'S', 'pending request',
                'message-pending', ?, 1, ?
            )
            """,
            (
                '{"version":1,"message_id":"message-pending",'
                '"content":"pending request","images":[]}',
                TIMESTAMP,
            ),
        )

    inventory = load_action_user_step_inventory(
        connection,
        action_ids=frozenset({"action-1"}),
    )

    assert [(entry.action_id, entry.step_id) for entry in inventory] == [
        ("action-1", "legacy-step")
    ]


def test_inventory_empty_scope_returns_no_rows(
    connection: sqlite3.Connection,
) -> None:
    with connection:
        _insert_scope(connection)
        _insert_step(connection, "step-1")

    assert load_action_user_step_inventory(connection, action_ids=frozenset()) == ()


@pytest.mark.parametrize(
    ("mutation", "pattern"),
    (
        ("UPDATE agent_action_steps SET action_id=' action-1'", "step_action_id"),
        ("UPDATE agent_action_steps SET user_id='user-2'", "ownership"),
        ("UPDATE agent_action_steps SET status='error'", "not successful"),
        ("UPDATE agent_action_steps SET step_number=0", "invalid step_number"),
        ("UPDATE agent_action_steps SET local_step_number=0", "local_step_number"),
        ("UPDATE agent_action_steps SET short_step_id='bad'", "short identity"),
        ("UPDATE agent_action_steps SET goal_handle=NULL", "goal_handle"),
        ("UPDATE agent_action_steps SET goal_handle='G1'", "short identity"),
        (
            "UPDATE agent_action_steps SET goal_handle='G1',short_step_id='G1-1-USER'",
            "short identity",
        ),
        (
            "UPDATE agent_action_steps SET created_at=' 2026-08-28T00:00:00Z'",
            "created_at",
        ),
        (
            "UPDATE agent_action_steps SET created_at='2026-08-28T00:00:00'",
            "created_at",
        ),
        (
            "UPDATE agent_action_steps SET created_at='2026-08-28T00:00:00.0000001Z'",
            "created_at",
        ),
        (
            "UPDATE agent_action_steps SET created_at='2026-08-28T0000001234567+00:00'",
            "created_at",
        ),
        (
            "UPDATE agent_action_steps SET created_at='2026-08-28T00:00:00+0100001234567'",
            "created_at",
        ),
        (
            "UPDATE agent_action_steps SET created_at='0001-01-01T00:00:00+01:00'",
            "created_at",
        ),
        ("UPDATE agent_action_steps SET created_at='invalid'", "created_at"),
        ("UPDATE agent_action_steps SET step_id=' step-1'", "invalid step_id"),
        ("UPDATE agent_actions SET initial_user_message_id=' message'", "initial_user"),
        ("UPDATE agent_actions SET suggestion_id='suggestion '", "suggestion_id"),
        ("UPDATE agent_action_steps SET user_message_id=' message'", "user_message_id"),
        ("UPDATE agent_action_steps SET user_message_json=NULL", "message pair"),
    ),
)
def test_inventory_rejects_invalid_structural_evidence(
    connection: sqlite3.Connection, mutation: str, pattern: str
) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("PRAGMA ignore_check_constraints = ON")
    with connection:
        _insert_scope(connection)
        connection.execute("DELETE FROM agent_actions WHERE action_id='action-2'")
        _insert_step(connection, "step-1")
        connection.execute(mutation)
    connection.execute("PRAGMA query_only = ON")

    with pytest.raises(MigrationError, match=pattern):
        load_action_user_step_inventory(connection)
