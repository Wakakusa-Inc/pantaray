from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from pantaray_agents.agents.action_agent.runtime.checkpoint import (
    RUNTIME_STATE_CHECKPOINT_VERSION,
    build_runtime_state_checkpoint,
)
from pantaray_agents.agents.action_agent.runtime.state import create_initial_state
from pantaray_agents.local_runtime.tooling.models import ActionExecutionContext

from .resource_recovery_test_support import bootstrap_runtime_db

TIMESTAMP = "2026-08-29T00:00:00Z"


def seed_legacy_shared_temp_action(
    tmp_path: Path,
) -> tuple[Path, ActionExecutionContext, Path]:
    db_path, raw_context = bootstrap_runtime_db(tmp_path)
    context = cast(ActionExecutionContext, raw_context)
    fixed_root = context.action_temp_dir.parent
    state = create_initial_state(
        user_id="user-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        started_at=TIMESTAMP,
        max_steps=20,
        max_tool_steps=10,
        token_budget=None,
        manifest_id=context.manifest_id,
        execution_session_id=context.execution_session_id,
        execution_network_policy=context.network_policy,
        action_temp_dir=str(fixed_root),
        app_runtime_python=str(context.app_runtime_python),
        read_access_scope=context.read_access_scope,
    )
    checkpoint = build_runtime_state_checkpoint(state)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE execution_sessions SET action_temp_dir = ?",
            (str(fixed_root),),
        )
        connection.execute(
            """INSERT INTO agent_action_steps(
                   step_id,action_id,user_id,step_number,local_step_number,short_step_id,
                   step_type,step_name,status,runtime_state_checkpoint,
                   runtime_state_checkpoint_version,created_at)
               VALUES ('checkpoint-1','action-1','user-1',1,1,'S-1-THINK',
                       'llm_output','thinking','success',?,?,?)""",
            (json.dumps(checkpoint), RUNTIME_STATE_CHECKPOINT_VERSION, TIMESTAMP),
        )
    return db_path, context, fixed_root
