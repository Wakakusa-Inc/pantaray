"""Execution context boundary model."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from pantaray_agents.schema.read_access import ReadAccessScope

EXECUTION_CONTEXT_STATE_FIELDS = (
    "manifest_id",
    "execution_session_id",
    "execution_network_policy",
    "action_temp_dir",
    "app_runtime_python",
    "read_access_scope",
)


class ExecutionContextModel(BaseModel):
    """Checkpoint/restore で保持する local execution context。"""

    model_config = ConfigDict(extra="forbid", strict=True)

    manifest_id: str
    execution_session_id: str
    execution_network_policy: str
    action_temp_dir: str
    app_runtime_python: str
    read_access_scope: ReadAccessScope

    @field_validator(
        "manifest_id",
        "execution_session_id",
        "execution_network_policy",
        "action_temp_dir",
        "app_runtime_python",
        "read_access_scope",
    )
    @classmethod
    def _require_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("execution context fields must be non-empty strings.")
        return normalized

    @classmethod
    def from_optional_values(
        cls,
        *,
        manifest_id: object | None,
        execution_session_id: object | None,
        execution_network_policy: object | None,
        action_temp_dir: object | None,
        app_runtime_python: object | None,
        read_access_scope: object | None,
    ) -> ExecutionContextModel | None:
        raw_values = (
            manifest_id,
            execution_session_id,
            execution_network_policy,
            action_temp_dir,
            app_runtime_python,
            read_access_scope,
        )
        if all(value is None for value in raw_values):
            return None
        return cls.model_validate(
            {
                "manifest_id": manifest_id,
                "execution_session_id": execution_session_id,
                "execution_network_policy": execution_network_policy,
                "action_temp_dir": action_temp_dir,
                "app_runtime_python": app_runtime_python,
                "read_access_scope": read_access_scope,
            }
        )


def execution_context_from_state(
    state: Mapping[str, object],
) -> ExecutionContextModel | None:
    if not any(field_name in state for field_name in EXECUTION_CONTEXT_STATE_FIELDS):
        return None
    return ExecutionContextModel.model_validate(
        {
            field_name: state.get(field_name)
            for field_name in EXECUTION_CONTEXT_STATE_FIELDS
        }
    )


def require_execution_context_from_state(
    state: Mapping[str, object],
    *,
    missing_message: str,
    invalid_message: str,
) -> ExecutionContextModel:
    try:
        execution_context = execution_context_from_state(state)
    except ValidationError as exc:
        raise RuntimeError(f"{invalid_message}: {exc}") from exc
    if execution_context is None:
        raise RuntimeError(missing_message)
    return execution_context


def execution_context_state_patch(
    execution_context: ExecutionContextModel,
) -> dict[str, str]:
    return {
        "manifest_id": execution_context.manifest_id,
        "execution_session_id": execution_context.execution_session_id,
        "execution_network_policy": execution_context.execution_network_policy,
        "action_temp_dir": execution_context.action_temp_dir,
        "app_runtime_python": execution_context.app_runtime_python,
        "read_access_scope": execution_context.read_access_scope,
    }


__all__ = [
    "EXECUTION_CONTEXT_STATE_FIELDS",
    "ExecutionContextModel",
    "execution_context_from_state",
    "execution_context_state_patch",
    "require_execution_context_from_state",
]
