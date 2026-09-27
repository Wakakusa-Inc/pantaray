from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.agent_state import LocalActionRepository
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.schema.agent.action import ActionAgentResponse
from pantaray_agents.schema.agent.base import StatusType

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
SUGGESTION_ID = "sug-1"
ACTION_ID = "act-1"


def bootstrap_action_repository_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES (?, 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                (USER_ID,),
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_text,
                    response_text,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'success', 'answer', 'prompt', 'response', 'prompt', 'v1', 1, 'action_offer', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """,
                (SUGGESTION_ID, USER_ID),
            )
            connection.execute(
                """
                INSERT INTO agent_actions(
                    action_id, user_id, suggestion_id, initial_user_message_id,
                    execution_target_json, status, final_output,
                    prompt_name, prompt_version, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, 'message-1', '{"kind":"scratch"}', 'queued', '',
                    'action/executing', '1.0',
                    '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z'
                )
                """,
                (ACTION_ID, USER_ID, SUGGESTION_ID),
            )
    return db_path


def build_action_repository(db_path: Path) -> LocalActionRepository:
    return LocalActionRepository(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )


async def save_success_action(
    repo: LocalActionRepository,
    *,
    action_id: str = ACTION_ID,
) -> None:
    result = await repo.save_action(
        ActionAgentResponse(
            action_id=action_id,
            suggestion_id=SUGGESTION_ID,
            user_id=USER_ID,
            final_output="done",
            created_at="2026-03-24T00:10:00Z",
            status=StatusType.SUCCESS,
        ),
        final_prompt_text="final prompt",
        prompt_name="action/executing",
        prompt_version="1.0",
        steps_budget=12,
        token_budget=120,
        total_steps=2,
        total_llm_steps=1,
        total_tool_steps=1,
        total_prompt_tokens=11,
        total_completion_tokens=7,
    )
    assert result.error is None


async def save_processing_action(
    repo: LocalActionRepository,
    *,
    action_id: str = ACTION_ID,
) -> None:
    result = await repo.save_action(
        ActionAgentResponse(
            action_id=action_id,
            suggestion_id=SUGGESTION_ID,
            user_id=USER_ID,
            final_output="",
            created_at="2026-03-24T00:10:00Z",
            status=StatusType.PROCESSING,
        ),
        final_prompt_text=None,
        prompt_name="action/executing",
        prompt_version="1.0",
    )
    assert result.error is None


def insert_action_step(
    *,
    db_path: Path,
    step_id: str,
    short_step_id: str,
    completed_at: str,
    created_at: str,
    step_number: int = 1,
) -> None:
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id,
                    action_id,
                    user_id,
                    step_number,
                    local_step_number,
                    short_step_id,
                    step_type,
                    step_name,
                    status,
                    goal_handle,
                    retry_count,
                    prompt_tokens,
                    completion_tokens,
                    completed_at,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'llm_output', 'supervisor_think', 'success', 'G1', 0, 0, 0, ?, ?)
                """,
                (
                    step_id,
                    ACTION_ID,
                    USER_ID,
                    step_number,
                    1,
                    short_step_id,
                    completed_at,
                    created_at,
                ),
            )


__all__ = [
    "ACTION_ID",
    "BUSY_TIMEOUT_MS",
    "SUGGESTION_ID",
    "USER_ID",
    "bootstrap_action_repository_db",
    "build_action_repository",
    "insert_action_step",
    "save_processing_action",
    "save_success_action",
]
