"""Assemble what one Executing THINK sends to the provider.

The prompt template marks its own seam: everything before ``{action_history}``
describes the Action, and everything after it is rebuilt every turn. Rendering
the two halves separately is what lets the history travel as conversation items
-- the fixed half becomes the request's own user message, the items follow it,
and the rebuilt half becomes the last of them -- while a template with nothing
after its history, which leaves the items no user item to end on, still gets the
two halves concatenated around the rendered history.

The fixed half is rendered once, from the values the Action's first turn saw, and
kept in the run state; what a later run reads differently reaches the model as
an update in its turn context (``support/world_state.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from string import Formatter
from typing import TYPE_CHECKING

from pantaray_agents.agents.action_agent.runtime.state import HistoryEntry
from pantaray_agents.agents.action_agent.runtime.tool_attachments import (
    collect_state_prompt_file_inputs,
)
from pantaray_agents.agents.action_agent.support.conversation_projection import (
    TURN_CONTEXT_HEADING,
    project_action_conversation,
)
from pantaray_agents.agents.action_agent.support.world_state import (
    WorldState,
    WorldStateUpdate,
    world_state_fields,
)
from pantaray_agents.schema.agent.action_history import SUPERVISOR_SCOPE_HANDLE
from pantaray_agents.utils.local_time import local_now_for_model
from pantaray_llm.contracts.conversation import LlmProviderTurn
from pantaray_llm.contracts.tool_use import LlmToolDefinition

from .context_budget import PreparedWindow, input_bytes, prepare_window

if TYPE_CHECKING:  # pragma: no cover
    from pantaray_agents.agents.action_agent import ActionAgent
    from pantaray_agents.agents.action_agent.runtime.graph import ActionGraphRuntime
    from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
    from pantaray_agents.agents.action_agent.services.prompt_rendering_service import (
        PromptRenderingService,
    )

HISTORY_PLACEHOLDER = "{action_history}"
TOOL_USE_RULE_PLACEHOLDER = "{tool_use_rules}"
SUPERVISOR_PARENT_RULE_KEY = "supervisor_soft_orchestration"
_FINAL_ANSWER_LANGUAGE_PLACEHOLDER = "{final_answer_language}"


@dataclass(frozen=True, slots=True)
class ExecutingTurn:
    """The parts of one Executing THINK that are fixed across repair attempts.

    The head in particular must be identical on every turn of a run, not just
    across one turn's attempts: it is the cache prefix, and on Anthropic it is
    also what a replayed thinking signature is verified against.
    """

    head: str
    tail: str
    system_instruction: str
    tool_bytes: int
    scope_handles: tuple[str, ...]
    sends_conversation: bool
    # What the head shows that this run may have read differently; None when
    # the turn is sent as one string, which shows this run's values throughout.
    world_state: WorldState | None = None

    def prepare(
        self,
        state: ActionAgentState,
        *,
        rendering: PromptRenderingService,
        repair_notice: str,
        provider_turns: Mapping[str, LlmProviderTurn],
    ) -> PreparedWindow:
        def assemble(boundary: int) -> PreparedWindow:
            return self._assemble(
                state,
                rendering=rendering,
                repair_notice=repair_notice,
                provider_turns=provider_turns,
                boundary=boundary,
            )

        return prepare_window(state, rendering=rendering, assemble=assemble)

    def _assemble(
        self,
        state: ActionAgentState,
        *,
        rendering: PromptRenderingService,
        repair_notice: str,
        provider_turns: Mapping[str, LlmProviderTurn],
        boundary: int,
    ) -> PreparedWindow:
        history = rendering.format_history(state, omit_before_step_number=boundary)
        entries = rendering.history_entries(state)
        update = self._world_state_update(entries, boundary=boundary)
        # The string rendering carries no recorded turn context, so it always
        # shows everything that differs from the head, whichever shape is sent.
        since_head = self._world_state_update((), boundary=boundary)
        recorded = (
            self.head
            + history
            + ("" if since_head is None else f"\n\n{since_head.text}")
            + self.tail
            + repair_notice
        )
        turn_context = (
            TURN_CONTEXT_HEADING + ("" if update is None else update.text) + self.tail
        )
        projection = (
            project_action_conversation(
                entries,
                omit_before_step_number=boundary,
                turn_context=turn_context,
                repair_notice=repair_notice,
                provider_turns=provider_turns,
            )
            if self.sends_conversation
            else None
        )
        # The omission boundary is resolved against the string rendering, so the
        # history's share is measured there whichever shape is sent; the input
        # estimate measures the shape that actually goes upstream, and the hard
        # 85% check after a rebuild is what keeps the two units safe together.
        history_bytes = input_bytes(history)
        if projection is None:
            return PreparedWindow(
                prompt=recorded,
                recorded_prompt=recorded,
                conversation=None,
                turn_context=None,
                world_state=None,
                file_inputs=tuple(
                    collect_state_prompt_file_inputs(
                        state=state,
                        prompt=recorded,
                        scope_handles=self.scope_handles,
                    )
                ),
                history_bytes=history_bytes,
                rendered_bytes=input_bytes(recorded, self.system_instruction)
                + self.tool_bytes,
            )
        return PreparedWindow(
            prompt=self.head,
            recorded_prompt=recorded,
            conversation=projection.conversation,
            turn_context=turn_context,
            world_state=None if update is None else update.values,
            file_inputs=projection.file_inputs,
            history_bytes=history_bytes,
            # Media rides on the same request but outside the serialized items,
            # as it did outside the prompt text, and stays in the measured
            # provider baseline rather than in this estimate.
            # A replayed turn's opaque payload stays out for the same reason:
            # 1,300 bytes of encrypted state cost about 20 input tokens, so
            # bytes / 4 would overstate it some fifteen times.
            rendered_bytes=input_bytes(self.head, self.system_instruction)
            + self.tool_bytes
            + sum(
                len(item.model_dump_json(exclude={"provider_turn"}).encode("utf-8"))
                for item in projection.conversation
            ),
        )

    def _world_state_update(
        self, entries: Sequence[HistoryEntry], *, boundary: int
    ) -> WorldStateUpdate | None:
        if self.world_state is None:
            return None
        return self.world_state.update_since(entries, omit_before_step_number=boundary)


def build_executing_turn(
    agent: ActionAgent,
    state: ActionAgentState,
    runtime: ActionGraphRuntime,
    *,
    tools: tuple[LlmToolDefinition, ...],
) -> ExecutingTurn:
    """Render the two halves of this turn and decide how to send them.

    The first turn sent as a conversation records the head's field values in
    the run state, so every later turn of the Action sends the same head.
    """

    rendering = runtime.services.rendering
    # Splitting on the placeholder rather than substituting into it is what
    # gives the history a place of its own. A template that omits the
    # placeholder puts the history last, which is where it already grows.
    head_template, _, tail_template = agent.executing_prompt.partition(
        HISTORY_PLACEHOLDER
    )
    fields = {
        "request_summary": rendering.render_request_summary(state),
        "target_context": rendering.render_target_context(state),
        "memory_context_model": rendering.render_memory_context_model(),
        "insight_data": state["context"].get("insight_data", ""),
        "structured_fact_data": state["context"].get("structured_fact_data", ""),
        "memory_source_coverage": rendering.format_memory_source_coverage(state),
        "memory_artifact_references": rendering.render_memory_artifact_references(
            state
        ),
        "linkable_persisted_memory": rendering.render_linkable_memory_context(state),
        "supervisor_pending_final_answer": (
            rendering.render_supervisor_pending_final_answer(state)
        ),
        "current_time": local_now_for_model(),
        "workspace_path_contract": rendering.render_workspace_path_contract(state),
        "workspace_context_rules": rendering.render_workspace_context_rules(),
        "workspace_context_prompt": rendering.render_workspace_context_prompt(state),
        "agents_md_instructions": _agents_md_section(state),
    }
    tail = tail_template.format(**fields)
    # A conversation has to end on a user item, and the tail is that item, so
    # a template with nothing after its history is sent as one string.
    sends_conversation = bool(tail)
    head_fields = fields
    world_state = None
    if sends_conversation:
        context = state["context"]
        recorded = context.get("executing_head_fields")
        if recorded is None:
            recorded = {
                name: fields[name]
                for _, name, _, _ in Formatter().parse(head_template)
                if name is not None
            }
            context["executing_head_fields"] = recorded
        head_fields = {**fields, **recorded}
        shown = world_state_fields(recorded)
        world_state = WorldState(
            head={name: recorded[name] for name in shown},
            current={name: fields[name] for name in shown},
            template=agent.executing_world_state_update,
        )
    return ExecutingTurn(
        head=head_template.format(**head_fields),
        tail=tail,
        system_instruction=_system_instruction(
            agent, language=runtime.request.language
        ),
        tool_bytes=sum(len(tool.model_dump_json().encode("utf-8")) for tool in tools),
        scope_handles=supervisor_prompt_scope_handles(state),
        sends_conversation=sends_conversation,
        world_state=world_state,
    )


def _agents_md_section(state: ActionAgentState) -> str:
    # Its own paragraph after Workspace Context, and nothing at all when absent.
    instructions = state["context"].get("agents_md_instructions", "")
    return f"\n\n{instructions}" if instructions else ""


def supervisor_prompt_scope_handles(state: ActionAgentState) -> tuple[str, ...]:
    """Every scope whose rows can own media the Supervisor prompt references."""

    return (SUPERVISOR_SCOPE_HANDLE, *state["goal_conversations"].keys())


def _system_instruction(agent: ActionAgent, *, language: str) -> str:
    instruction = (
        agent.executing_system_instruction
        or f"{agent.DEFAULT_SYSTEM_INSTRUCTION} Answer in English."
    ).replace(
        _FINAL_ANSWER_LANGUAGE_PLACEHOLDER,
        "Japanese" if language == "ja" else "English",
    )
    if TOOL_USE_RULE_PLACEHOLDER not in instruction:
        return instruction
    return instruction.replace(
        TOOL_USE_RULE_PLACEHOLDER,
        agent.executing_tool_use_rule(SUPERVISOR_PARENT_RULE_KEY),
    )


__all__ = [
    "ExecutingTurn",
    "build_executing_turn",
    "supervisor_prompt_scope_handles",
]
