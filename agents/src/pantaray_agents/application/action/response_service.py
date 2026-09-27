"""ActionAgent response and error service."""

from __future__ import annotations

from dataclasses import dataclass

from pantaray_agents.agents.action_agent.runtime.error_redaction import (
    redact_agent_error_for_client,
)
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
from pantaray_agents.application.action.persistence import ActionAgentPersistence
from pantaray_agents.schema.agent.action import (
    ActionAgentRequest,
    ActionAgentResponse,
    ActionExecutionResult,
    build_action_agent_response,
)
from pantaray_agents.schema.agent.base import AgentError, JSONValue

type AgentErrorPayload = dict[str, JSONValue]


@dataclass(frozen=True)
class ResponseDeps:
    """Dependencies required by the response service."""

    persistence: ActionAgentPersistence


class ActionResponseService:
    """state/response conversion and agent error construction."""

    def __init__(self, deps: ResponseDeps) -> None:
        self._deps = deps

    def state_to_response(self, state: ActionAgentState) -> ActionAgentResponse:
        return self._deps.persistence.state_to_response(state, redact_for_client=True)

    def state_to_execution_result(
        self,
        state: ActionAgentState,
    ) -> ActionExecutionResult:
        return self._deps.persistence.state_to_execution_result(state)

    def redact_error_for_client(self, error: AgentError) -> AgentError:
        return redact_agent_error_for_client(error)

    def build_public_error_response(
        self,
        *,
        request: ActionAgentRequest,
        created_at: str,
        error: AgentError,
    ) -> ActionAgentResponse:
        return self._build_error_response(
            request=request,
            created_at=created_at,
            error=self.redact_error_for_client(error),
        )

    def build_internal_error_response(
        self,
        *,
        request: ActionAgentRequest,
        created_at: str,
        error: AgentError,
    ) -> ActionAgentResponse:
        return self._build_error_response(
            request=request,
            created_at=created_at,
            error=error,
        )

    def build_agent_error(
        self,
        *,
        error_type: str,
        error_code: str,
        error_message: str,
        severity: str = "error",
        error_details: AgentErrorPayload | None = None,
        metadata: AgentErrorPayload | None = None,
    ) -> AgentError:
        return self._deps.persistence.build_agent_error(
            error_type=error_type,
            error_code=error_code,
            error_message=error_message,
            severity=severity,
            error_details=error_details,
            metadata=metadata,
        )

    @staticmethod
    def _build_error_response(
        *,
        request: ActionAgentRequest,
        created_at: str,
        error: AgentError,
    ) -> ActionAgentResponse:
        return build_action_agent_response(
            action_id=request.action_id,
            suggestion_id=request.suggestion_id,
            user_id=request.user_id,
            final_output="",
            created_at=created_at,
            status="error",
            error=error,
        )
