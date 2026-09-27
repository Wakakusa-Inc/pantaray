from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_suggestion_projection_authority import (
    list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection,
)
from pantaray_agents.local_runtime.suggestion_state.public_projection import (
    rebuild_history_projection,
)

from .legacy_action_shared_temp_test_support import seed_legacy_shared_temp_action

_ROOT_SQL = "UPDATE tool_runtime_resources SET resource_path=?"


def _load(db_path: Path):
    resolved = db_path.resolve()
    with sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection(
            connection=connection, resolved_db_path=resolved
        )


def test_projection_proof_preserves_suggestion_lane_and_omits_standalone(
    tmp_path: Path,
) -> None:
    db_path, _, fixed_root = seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute(_ROOT_SQL, (str(fixed_root),))
        connection.execute(
            """UPDATE agent_suggestions SET status='success',answer='Keep this',
               has_suggestion=1,interaction_contract='action_offer',
               user_reaction='accepted',accepted_at='2026-08-29T00:00:03Z',
               action_status='success',action_process_id='process-1',
               action_command_id='command-1',action_started_at='2026-08-29T00:00:04Z'
               WHERE suggestion_id='suggestion-1'"""
        )
        connection.execute(
            """UPDATE agent_actions SET status='success',final_output='Action done',
               updated_at='2026-08-29T00:00:05Z' WHERE action_id='action-1'"""
        )
        connection.executescript(
            """INSERT INTO agent_process_events VALUES
               ('chunk','suggestion-1','user-1',NULL,1,'suggestion_chunk','{"data":{"content":"Keep this"}}','2026-08-29T00:00:00Z'),
               ('suggestion-end','suggestion-1','user-1',NULL,2,'process_completed','{"data":{"kind":"suggestion","status":"success","interaction_contract":"action_offer"}}','2026-08-29T00:00:00Z'),
               ('accepted','suggestion-1','user-1',NULL,3,'suggestion_reaction_committed','{"data":{"reaction":"accepted","committed_at":"2026-08-29T00:00:03Z"}}','2026-08-29T00:00:00Z'),
               ('action-start','suggestion-1','user-1','action-1',4,'process_started','{"data":{"kind":"action","action_id":"action-1","process_id":"process-1","command_id":"command-1"}}','2026-08-29T00:00:00Z'),
               ('action-end','suggestion-1','user-1','action-1',5,'process_completed','{"data":{"kind":"action","status":"success","action_id":"action-1","final_output":"Action done"}}','2026-08-29T00:00:00Z');"""
        )
        rebuild_history_projection(
            connection=connection, user_id="user-1", suggestion_id="suggestion-1"
        )

    proof = _load(db_path)[0].suggestion_projection
    assert proof is not None
    assert proof.suggestion.user_reaction == "accepted"
    assert proof.history_action_lane.final_output == "Action done"
    assert tuple(event.action_id for event in proof.public_events) == (
        None,
        None,
        None,
        "action-1",
        "action-1",
    )

    standalone_dir = tmp_path / "standalone"
    standalone_dir.mkdir()
    standalone_db, _, standalone_root = seed_legacy_shared_temp_action(standalone_dir)
    with sqlite3.connect(standalone_db) as connection, connection:
        connection.execute(_ROOT_SQL, (str(standalone_root),))
        connection.execute("UPDATE agent_actions SET suggestion_id=NULL")
    assert _load(standalone_db)[0].suggestion_projection is None
