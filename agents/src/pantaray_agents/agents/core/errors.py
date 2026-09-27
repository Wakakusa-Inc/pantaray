"""Agent core 層の明示的な例外定義。"""

from __future__ import annotations

from fastapi import status

from pantaray_agents.schema.agent.base import ErrorSeverity, ErrorType


class PublicAgentHTTPError(RuntimeError):
    """公開API向けにサニタイズして返す内部例外の基底。"""

    error_code: str
    status_code: int
    error_type: ErrorType
    severity: ErrorSeverity
    public_message: str | None

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_type: ErrorType = ErrorType.INTERNAL_ERROR,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        public_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.error_type = error_type
        self.severity = severity
        self.public_message = public_message


class AgentDependencyConfigError(PublicAgentHTTPError, TypeError):
    """Agent 依存注入設定の不整合。"""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code="AGENT_DEPENDENCY_CONFIG_ERROR",
        )


__all__ = ["AgentDependencyConfigError", "PublicAgentHTTPError"]
