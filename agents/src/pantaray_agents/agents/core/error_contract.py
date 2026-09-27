from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pantaray_agents.schema.agent.base import (
    AgentError,
    ErrorSeverity,
    ErrorType,
    JSONValue,
)


class AgentErrorPhase(StrEnum):
    VALIDATION = "validation"
    CONTEXT_FETCH = "context_fetch"
    RUN_START = "run_start"
    LLM = "llm"
    PATCH = "patch"
    COMMIT = "commit"
    STEP_RECORD = "step_record"
    ERROR_PERSISTENCE = "error_persistence"
    CONFLICT = "conflict"
    RESPONSE_BUILD = "response_build"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class AgentErrorSpec:
    suffix: str
    error_type: ErrorType
    db_message: str


ERROR_SPEC_BY_PHASE: dict[AgentErrorPhase, AgentErrorSpec] = {
    AgentErrorPhase.VALIDATION: AgentErrorSpec(
        suffix="VALIDATION_ERROR",
        error_type=ErrorType.VALIDATION_ERROR,
        db_message="Agent request validation failed.",
    ),
    AgentErrorPhase.CONTEXT_FETCH: AgentErrorSpec(
        suffix="FETCH_CONTEXT_ERROR",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent context fetch failed.",
    ),
    AgentErrorPhase.RUN_START: AgentErrorSpec(
        suffix="RUN_START_ERROR",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent run start persistence failed.",
    ),
    AgentErrorPhase.LLM: AgentErrorSpec(
        suffix="LLM_RESPONSE_ERROR",
        error_type=ErrorType.LLM_API_ERROR,
        db_message="Agent LLM response processing failed.",
    ),
    AgentErrorPhase.PATCH: AgentErrorSpec(
        suffix="PATCH_ERROR",
        error_type=ErrorType.INTERNAL_ERROR,
        db_message="Agent patch application failed.",
    ),
    AgentErrorPhase.COMMIT: AgentErrorSpec(
        suffix="COMMIT_ERROR",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent commit persistence failed.",
    ),
    AgentErrorPhase.STEP_RECORD: AgentErrorSpec(
        suffix="STEP_RECORD_ERROR",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent step recording failed.",
    ),
    AgentErrorPhase.ERROR_PERSISTENCE: AgentErrorSpec(
        suffix="ERROR_PERSISTENCE_ERROR",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent error persistence failed.",
    ),
    AgentErrorPhase.CONFLICT: AgentErrorSpec(
        suffix="CONFLICT",
        error_type=ErrorType.REPOSITORY_ERROR,
        db_message="Agent commit conflict detected.",
    ),
    AgentErrorPhase.RESPONSE_BUILD: AgentErrorSpec(
        suffix="RESPONSE_BUILD_ERROR",
        error_type=ErrorType.INTERNAL_ERROR,
        db_message="Agent response build failed.",
    ),
    AgentErrorPhase.UNEXPECTED: AgentErrorSpec(
        suffix="UNEXPECTED_ERROR",
        error_type=ErrorType.INTERNAL_ERROR,
        db_message="Agent processing failed unexpectedly.",
    ),
}


class AgentPhaseError(RuntimeError):
    phase: AgentErrorPhase
    cause: Exception

    def __init__(self, phase: AgentErrorPhase, cause: Exception) -> None:
        super().__init__(f"{phase.value}: {type(cause).__name__}")
        self.phase = phase
        self.cause = cause


def build_agent_error(
    *,
    prefix: str,
    phase: AgentErrorPhase,
    exception: Exception | None = None,
    severity: ErrorSeverity = ErrorSeverity.ERROR,
) -> AgentError:
    spec = ERROR_SPEC_BY_PHASE[phase]
    return AgentError(
        error_type=spec.error_type.value,
        error_code=f"{prefix}_{spec.suffix}",
        error_message=spec.db_message,
        severity=severity.value,
        metadata=_build_error_metadata(phase=phase, exception=exception),
    )


def _build_error_metadata(
    *, phase: AgentErrorPhase, exception: Exception | None
) -> dict[str, JSONValue]:
    metadata: dict[str, JSONValue] = {"phase": phase.value}
    if exception is not None:
        metadata["exception_type"] = type(exception).__name__
    return metadata


__all__ = [
    "AgentErrorPhase",
    "AgentErrorSpec",
    "AgentPhaseError",
    "ERROR_SPEC_BY_PHASE",
    "build_agent_error",
]
