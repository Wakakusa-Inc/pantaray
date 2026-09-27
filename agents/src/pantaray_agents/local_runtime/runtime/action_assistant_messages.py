"""Read durable assistant utterances for Action history initialization."""

import sqlite3

from pantaray_agents.schema.agent.action_assistant_message import (
    ActionAssistantMessageStep,
)


def read_preceding_assistant_messages(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    before_step_number: int,
) -> tuple[ActionAssistantMessageStep, ...]:
    return tuple(
        ActionAssistantMessageStep(
            step_id=row[0],
            step_number=row[1],
            local_step_number=row[2],
            short_step_id=row[3],
            content=row[4],
            created_at=row[5],
            assistant_phase="commentary" if row[6] == "assistant_commentary" else None,
        )
        for row in connection.execute(
            """SELECT step_id, step_number, local_step_number, short_step_id,
                      llm_response_text, created_at, step_name
            FROM agent_action_steps
            WHERE user_id = ? AND action_id = ? AND step_type = 'assistant_message'
              AND step_number < ?
            ORDER BY step_number, step_id""",
            (user_id, action_id, before_step_number),
        )
    )
