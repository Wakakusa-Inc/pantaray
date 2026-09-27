from __future__ import annotations

from abc import ABC

from pantaray_agents.agents.core.base import BaseAgent, ContextDataPayload
from pantaray_agents.schema.agent import AgentRequest, AgentResponse
from pantaray_agents.schema.agent.base import AgentError


class ReactAgentBase[T: AgentResponse](BaseAgent[T], ABC):
    """Base for agents that own their own ReAct process flow."""

    async def _validate_request(self, _request: AgentRequest) -> AgentRequest:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    async def _fetch_context_data(self, _request: AgentRequest) -> ContextDataPayload:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    def _build_prompt(self, _context_data: ContextDataPayload) -> str:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    async def _process_llm_response(self, _prompt: str) -> ContextDataPayload:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    def _create_success_response(
        self,
        _request: AgentRequest,
        _extracted_data: ContextDataPayload,
    ) -> T:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    async def _save_response(self, _response: T) -> None:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    def _get_id_attrs(self) -> dict[str, str]:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")

    async def _handle_agent_error(
        self, _error: AgentError, _response_params: dict[str, object]
    ) -> T:
        raise RuntimeError(f"{type(self).__name__} owns its ReAct process flow")
