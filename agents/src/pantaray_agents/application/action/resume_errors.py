"""Action runtime resume error types."""

from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.models import ResumeFailureCode


class ResumeStateError(RuntimeError):
    """checkpoint resume の契約違反。"""

    def __init__(self, *, failure_code: ResumeFailureCode, message: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code
