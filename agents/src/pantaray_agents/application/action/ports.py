"""Application-layer contracts for Action use cases."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from pantaray_agents.schema.action_conversation import (
    ActionStepEventPayload,
    ActionStepStatus,
)
from pantaray_agents.schema.agent.action import (
    ActionAgentRequest,
    ActionAgentResponse,
    ActionExecutionResult,
)
from pantaray_agents.schema.agent.base import AgentRequest, JSONValue
from pantaray_agents.schema.repositories.repository import RepositoryErrorKind
from pantaray_agents.schema.repository_errors import AgentRepositoryError


@dataclass(frozen=True, slots=True)
class ActionToolStepEmission:
    step_id: str
    step_number: int
    step_name: str
    label: str
    # Tool-specific input stays inside the server; only its public subject is emitted.
    tool_args: dict[str, JSONValue]
    status: ActionStepStatus
    started_at: str
    completed_at: str | None


@dataclass(frozen=True, slots=True)
class ActionAssistantMessageEmission:
    step_id: str
    step_number: int


type ActionStepEmission = ActionToolStepEmission | ActionAssistantMessageEmission
type ActionStepEmitter = Callable[[ActionStepEmission], Awaitable[None]]


class ActionStepEventPersistenceError(AgentRepositoryError):
    def __init__(
        self,
        *,
        event: ActionStepEventPayload,
        error_kind: RepositoryErrorKind,
        retryable: bool,
    ) -> None:
        super().__init__(
            stage="save",
            safe_message="Action step event persistence failed",
            error_kind=error_kind,
            retryable=retryable,
        )
        self.event = event


class ActionUseCase(Protocol):
    """Action use-case contract for HTTP and local runtime callers."""

    async def process(self, request: AgentRequest) -> ActionAgentResponse: ...

    async def stream_action(
        self,
        request: ActionAgentRequest,
        *,
        emit_action_step: ActionStepEmitter,
        emit_error: Callable[[Mapping[str, JSONValue]], Awaitable[None]],
    ) -> ActionAgentResponse: ...

    async def execute_action_runtime(
        self,
        request: ActionAgentRequest,
        *,
        emit_action_step: ActionStepEmitter,
        emit_error: Callable[[Mapping[str, JSONValue]], Awaitable[None]],
    ) -> ActionExecutionResult: ...


__all__ = [
    "ActionAssistantMessageEmission",
    "ActionStepEmission",
    "ActionStepEventPersistenceError",
    "ActionToolStepEmission",
    "ActionStepEmitter",
    "ActionUseCase",
]
