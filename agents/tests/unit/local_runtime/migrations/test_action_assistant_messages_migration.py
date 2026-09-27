from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.unit.local_runtime.action_seed import insert_agent_action

from pantaray_agents.local_runtime.runtime.action_assistant_messages import (
    read_preceding_assistant_messages,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)


def test_upgrade_preserves_steps_references_and_accepts_assistant_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = tuple(m for m in load_default_migrations() if m.version <= 107)
    apply_migrations(db_path, 1_000, migrations[:-1])
    insert_agent_action(db_path=db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            """INSERT INTO processes (
                process_id,user_id,action_id,kind,status,started_at,updated_at,
                heartbeat_at,next_event_seq
            ) VALUES ('run-1','user-1','action-1','action','failed',
                '2026-09-09','2026-09-09','2026-09-09',1)"""
        )
        connection.execute(
            """INSERT INTO agent_action_steps (
                step_id,action_id,user_id,step_number,local_step_number,short_step_id,
                step_type,step_name,status,goal_handle,user_request_text,
                accepted_sequence,adopted_process_id,created_at
            ) VALUES ('user-step','action-1','user-1',1,1,'S-1-USER',
                'user_request','user_request','success','S','依頼',1,'run-1','2026-09-09')"""
        )
        connection.execute(
            """INSERT INTO agent_action_steps (
                step_id,action_id,user_id,parent_step_id,step_number,local_step_number,
                short_step_id,step_type,step_name,status,goal_handle,llm_response_text,
                runtime_state_checkpoint,runtime_state_checkpoint_version,created_at
            ) VALUES ('think-step','action-1','user-1','user-step',2,2,'S-2-THINK',
                'llm_output','think','success','S','stored response','{"history":[]}',4,'2026-09-09')"""
        )
        original_columns = ",".join(
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_action_steps)")
        )
        before = connection.execute(
            "SELECT * FROM agent_action_steps ORDER BY step_id"
        ).fetchall()
        dependents = connection.execute(
            "SELECT name,sql FROM sqlite_schema WHERE tbl_name='agent_action_steps' AND type IN ('index','trigger') ORDER BY name"
        ).fetchall()
    apply_migrations(db_path, 1_000, migrations)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        assert (
            connection.execute(
                f"SELECT {original_columns} FROM agent_action_steps ORDER BY step_id"
            ).fetchall()
            == before
        )
        assert (
            connection.execute(
                "SELECT name,sql FROM sqlite_schema WHERE tbl_name='agent_action_steps' AND type IN ('index','trigger') AND name <> 'uq_agent_action_steps_assistant_ref' ORDER BY name"
            ).fetchall()
            == dependents
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute(
            """INSERT INTO agent_action_steps (
                step_id,action_id,user_id,step_number,local_step_number,short_step_id,
                step_type,step_name,status,goal_handle,llm_response_text,
                adopted_process_id,started_at,completed_at,created_at
            ) VALUES ('assistant-step','action-1','user-1',3,3,'S-3-ASSISTANT',
                'assistant_message','assistant_message','success','S','アシスタントの発言',
                'run-1','2026-09-09','2026-09-09','2026-09-09')"""
        )
        messages = read_preceding_assistant_messages(
            connection,
            user_id="user-1",
            action_id="action-1",
            before_step_number=4,
        )
        assert [(message.short_step_id, message.content) for message in messages] == [
            ("S-3-ASSISTANT", "アシスタントの発言")
        ]
        assert not read_preceding_assistant_messages(
            connection,
            user_id="other-user",
            action_id="action-1",
            before_step_number=4,
        )
        for assignment in (
            "llm_response_text=NULL",
            "user_request_text='incorrect role'",
            "adopted_process_id=NULL",
            "short_step_id='S-3-USER'",
        ):
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    f"UPDATE agent_action_steps SET {assignment} WHERE step_id='assistant-step'"
                )

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            connection.execute(
                """INSERT INTO agent_action_steps (
                    step_id,action_id,user_id,step_number,local_step_number,short_step_id,
                    step_type,step_name,status,goal_handle,llm_response_text,
                    adopted_process_id,started_at,completed_at,created_at
                ) SELECT 'duplicate-utterance',action_id,user_id,step_number,local_step_number,
                    short_step_id,step_type,step_name,status,goal_handle,'違う発言',
                    adopted_process_id,started_at,completed_at,created_at
                FROM agent_action_steps WHERE step_id='assistant-step'"""
            )
