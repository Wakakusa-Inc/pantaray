from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    verify_database_integrity,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations as load_all_migrations,
)

from .support import _insert_user, _migrations_before

DELIVERY_STATE_MIGRATION_NAME = "0122_suggestion_delivery_state.sql"
USER_ID = "user-delivery"
BUSY_TIMEOUT_MS = 1_000
STORED_AT = "2026-09-30T00:00:00.000Z"


def _insert_suggestion(
    connection: sqlite3.Connection,
    suggestion_id: str,
    *,
    status: str,
    has_suggestion: int | None,
    delivery_state: str | None = None,
) -> None:
    columns = "suggestion_id, user_id, status, has_suggestion, created_at, updated_at"
    values: tuple[object, ...] = (
        suggestion_id,
        USER_ID,
        status,
        has_suggestion,
        STORED_AT,
        STORED_AT,
    )
    if delivery_state is not None:
        columns += ", delivery_state"
        values += (delivery_state,)
    connection.execute(
        f"INSERT INTO agent_suggestions({columns})"
        f" VALUES ({', '.join('?' for _ in values)})",
        values,
    )


def _upgraded_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    migrations = load_all_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, DELIVERY_STATE_MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_user(connection, USER_ID)
        _insert_suggestion(connection, "shown", status="success", has_suggestion=1)
        _insert_suggestion(connection, "nothing", status="success", has_suggestion=0)
        _insert_suggestion(
            connection, "running", status="processing", has_suggestion=None
        )
    apply_migrations(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS, migrations=migrations
    )
    verify_database_integrity(db_path, BUSY_TIMEOUT_MS)
    return db_path


def test_upgrade_marks_every_stored_suggestion_as_shown(tmp_path: Path) -> None:
    db_path = _upgraded_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT suggestion_id, delivery_state, updated_at FROM agent_suggestions"
            " ORDER BY suggestion_id"
        ).fetchall()

    # History orders by updated_at, so the backfill must not move any row.
    assert rows == [
        ("nothing", None, STORED_AT),
        ("running", None, STORED_AT),
        ("shown", "released", STORED_AT),
    ]


@pytest.mark.parametrize(
    ("has_suggestion", "delivery_state"),
    [(0, "held"), (None, "released"), (1, "pending")],
)
def test_only_a_stored_suggestion_carries_a_known_delivery_state(
    tmp_path: Path, has_suggestion: int | None, delivery_state: str
) -> None:
    db_path = _upgraded_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            _insert_suggestion(
                connection,
                "invalid",
                status="success",
                has_suggestion=has_suggestion,
                delivery_state=delivery_state,
            )


def test_an_owner_holds_at_most_one_suggestion(tmp_path: Path) -> None:
    db_path = _upgraded_db(tmp_path)

    with sqlite3.connect(db_path) as connection:
        _insert_suggestion(
            connection,
            "held-1",
            status="success",
            has_suggestion=1,
            delivery_state="held",
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            _insert_suggestion(
                connection,
                "held-2",
                status="success",
                has_suggestion=1,
                delivery_state="held",
            )
