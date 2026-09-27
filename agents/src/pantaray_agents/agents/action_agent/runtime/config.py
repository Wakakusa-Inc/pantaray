"""Action runtime state_config helpers."""

from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.state import ActionAgentStateConfig
from pantaray_agents.utils.strict_numbers import is_strict_int


def require_positive_state_config_int(
    state_config: ActionAgentStateConfig,
    *,
    key: str,
    error_message: str,
) -> int:
    value = state_config.get(key)
    if not is_strict_int(value) or value <= 0:
        raise RuntimeError(error_message)
    return value


__all__ = ["require_positive_state_config_int"]
