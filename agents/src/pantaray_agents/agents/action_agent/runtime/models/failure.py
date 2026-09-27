"""Resume failure boundary model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from pantaray_agents.action_status import (
    RESUME_FAILURE_CODES,
    build_resume_failure,
)

ResumeFailureCode = Literal[
    "ACTION_RESUME_CHECKPOINT_INVALID",
    "ACTION_RESUME_STATE_INCONSISTENT",
    "ACTION_RESUME_APPROVAL_STATE_INVALID",
    "ACTION_RESUME_GOAL_WORKER_STATE_INVALID",
    "ACTION_RESUME_RUNTIME_CONTEXT_INVALID",
    "ACTION_RESUME_NOT_ALLOWED",
    "ACTION_ORCHESTRATION_MODE_RETIRED",
]


class ResumeFailureException(ValueError):
    """Resume checkpoint/runtime contract violation with explicit failure code."""

    def __init__(self, *, failure_code: ResumeFailureCode, message: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


class ResumeFailureModel(BaseModel):
    """resume failure taxonomy の canonical payload。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    failure_code: ResumeFailureCode
    failure_stage: Literal["resume_failed"]
    failure_message_public: Literal["Action execution failed."]

    @classmethod
    def from_failure_code(cls, failure_code: ResumeFailureCode) -> ResumeFailureModel:
        if failure_code not in RESUME_FAILURE_CODES:
            raise ValueError(f"Unsupported resume failure_code: {failure_code!r}")
        failure = build_resume_failure(failure_code=failure_code)
        return cls.model_validate(failure, from_attributes=True)
