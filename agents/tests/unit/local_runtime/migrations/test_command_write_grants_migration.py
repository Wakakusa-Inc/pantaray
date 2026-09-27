from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from ..broker_test_support import BROKER_ACTOR_PROCESS_ID, _seed_broker_actor_process
from ..resource_recovery_test_support import (
    bootstrap_runtime_db,
    register_running_bash_invocation,
)


def test_command_grants_keep_their_actor_and_follow_invocation_retention(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    _seed_broker_actor_process(db_path)
    invocation_id = register_running_bash_invocation(db_path=db_path, context=context)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, 1_000)
        insert = "INSERT INTO command_workspace_write_grants VALUES (?, ?, ?)"
        for owner, actor in (
            ("missing-invocation", BROKER_ACTOR_PROCESS_ID),
            (invocation_id, "missing-actor"),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
                with connection:
                    connection.execute(insert, (owner, actor, "/workspace"))
        with connection:
            connection.execute(
                insert, (invocation_id, BROKER_ACTOR_PROCESS_ID, "/workspace")
            )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with connection:
                connection.execute(
                    "DELETE FROM processes WHERE process_id = ?",
                    (BROKER_ACTOR_PROCESS_ID,),
                )
        with connection:
            connection.execute(
                "DELETE FROM tool_invocations WHERE invocation_id = ?", (invocation_id,)
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM command_workspace_write_grants"
        ).fetchone() == (0,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
