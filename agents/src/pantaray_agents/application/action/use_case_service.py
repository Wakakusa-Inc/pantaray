"""Application-layer Action use-case orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.application.action.ports import (
    ActionStepEmitter,
    ActionUseCase,
)
from pantaray_agents.schema.agent.action import (
    ActionAgentRequest,
    ActionAgentResponse,
    ActionExecutionResult,
)
from pantaray_agents.schema.agent.base import AgentRequest, JSONValue


@dataclass(frozen=True)
class ActionUseCaseDeps:
    """Dependencies required to build the Action use-case facade."""

    agent: ActionAgent


class ActionUseCaseService(ActionUseCase):
    """Action application facade used by workers and routers."""

    def __init__(self, deps: ActionUseCaseDeps) -> None:
        self._agent = deps.agent
        self._persistence = self._agent.persistence
        self._response_service = self._agent.response_service
        self._resume_service = self._agent.resume_service
        self._cancellation_service = self._agent.cancellation_service
        self._runtime_services = self._agent.runtime_services
        self._execution_service = self._agent.execution_service
        self._entrypoint = self._agent.runtime_entrypoint

    async def process(self, request: AgentRequest) -> ActionAgentResponse:
        return await self._entrypoint.process(request)

    async def stream_action(
        self,
        request: ActionAgentRequest,
        *,
        emit_action_step: ActionStepEmitter,
        emit_error: Callable[[Mapping[str, JSONValue]], Awaitable[None]],
    ) -> ActionAgentResponse:
        return await self._entrypoint.stream_action(
            request,
            emit_action_step=emit_action_step,
            emit_error=emit_error,
        )

    async def execute_action_runtime(
        self,
        request: ActionAgentRequest,
        *,
        emit_action_step: ActionStepEmitter,
        emit_error: Callable[[Mapping[str, JSONValue]], Awaitable[None]],
    ) -> ActionExecutionResult:
        return await self._entrypoint.execute_action_runtime(
            request,
            emit_action_step=emit_action_step,
            emit_error=emit_error,
        )


__all__ = ["ActionUseCaseDeps", "ActionUseCaseService"]
