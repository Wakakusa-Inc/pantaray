"""Project durable assistant utterances into the ordinary Action history."""

from collections.abc import Sequence
from uuid import UUID, uuid5

from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    ActionPhase,
    HistoryEntry,
)
from pantaray_agents.schema.agent.action import StepType
from pantaray_agents.schema.agent.action_assistant_message import (
    ActionAssistantMessageStep,
    ActionLlmTurnCommit,
)
from pantaray_llm.contracts.action_turn import LlmCommentary

from . import common


def prepare_llm_turn_commit(
    state: ActionAgentState,
    *,
    llm_step_id: str,
    messages: Sequence[LlmCommentary],
    occurred_at: str,
) -> ActionLlmTurnCommit:
    """Reserve utterance positions before THINK in the caller's staged state."""
    user_step_id = next(
        entry["step_id"]
        for entry in reversed(common.get_history_for_scope(state, "S"))
        if entry["step_type"] == StepType.USER_REQUEST
    )
    prepared: list[ActionAssistantMessageStep] = []
    for message in messages:
        local_number = common.get_or_increment_local_step_number(state, "S")
        prepared.append(
            ActionAssistantMessageStep(
                step_id=str(uuid5(UUID(llm_step_id), message.source_message_id)),
                step_number=state["step"],
                local_step_number=local_number,
                short_step_id=common.build_short_step_id(
                    "S", local_number, StepType.ASSISTANT_MESSAGE
                ),
                content=message.text,
                created_at=occurred_at,
                assistant_phase=message.phase,
            )
        )
        state["step"] += 1
    return ActionLlmTurnCommit(user_step_id=user_step_id, messages=tuple(prepared))


def build_assistant_history_entry(
    message: ActionAssistantMessageStep, *, phase: ActionPhase
) -> HistoryEntry:
    """Share the utterance projection between response adoption and DB recovery."""
    entry: HistoryEntry = {
        "step_id": message.step_id,
        "step_number": message.step_number,
        "phase": phase,
        "step_type": StepType.ASSISTANT_MESSAGE,
        "summary": "",
        "assistant_message_text": message.content,
        "tool_id": None,
        "started_at": message.created_at,
        "completed_at": message.created_at,
        "short_step_id": message.short_step_id,
    }
    if message.assistant_phase is not None:
        entry["assistant_phase"] = message.assistant_phase
    return entry


def project_persisted_assistant_messages(
    state: ActionAgentState,
    messages: tuple[ActionAssistantMessageStep, ...],
    *,
    before_step_number: int,
) -> None:
    for message in messages:
        if not state["step"] <= message.step_number < before_step_number:
            continue
        local_number = common.get_or_increment_local_step_number(state, "S")
        if local_number != message.local_step_number or message.short_step_id != (
            common.build_short_step_id("S", local_number, StepType.ASSISTANT_MESSAGE)
        ):
            raise ValueError("persisted assistant message position is inconsistent")
        common.append_history_entry(
            state,
            scope_handle="S",
            entry=build_assistant_history_entry(message, phase="init"),
        )
        state["step"] = message.step_number + 1
