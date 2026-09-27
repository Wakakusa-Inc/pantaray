from __future__ import annotations

import sqlite3

import pytest

from pantaray_agents.local_runtime.storage.transactions import (
    SQLiteAfterCommitRegistrationError,
    immediate_transaction,
    register_after_commit,
)


def test_after_commit_callback_runs_only_after_commit() -> None:
    connection = sqlite3.connect(":memory:")
    events: list[str] = []

    with immediate_transaction(connection):
        register_after_commit(
            connection=connection,
            callback=lambda: events.append("committed"),
        )
        assert events == []

    assert events == ["committed"]


def test_after_commit_callback_is_discarded_on_rollback() -> None:
    connection = sqlite3.connect(":memory:")
    events: list[str] = []

    with pytest.raises(RuntimeError, match="rollback"):
        with immediate_transaction(connection):
            register_after_commit(
                connection=connection,
                callback=lambda: events.append("committed"),
            )
            raise RuntimeError("rollback")

    assert events == []


def test_after_commit_registration_requires_owned_transaction() -> None:
    connection = sqlite3.connect(":memory:")

    with pytest.raises(SQLiteAfterCommitRegistrationError):
        register_after_commit(connection=connection, callback=lambda: None)
