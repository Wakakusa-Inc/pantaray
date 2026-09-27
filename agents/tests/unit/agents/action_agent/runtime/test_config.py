from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.config import (
    require_positive_state_config_int,
)


def test_require_positive_state_config_int_returns_positive_int() -> None:
    value = require_positive_state_config_int(
        {"max_parallel_memory_queries": 3},
        key="max_parallel_memory_queries",
        error_message="invalid",
    )

    assert value == 3


def test_require_positive_state_config_int_rejects_bool() -> None:
    with pytest.raises(RuntimeError, match="invalid"):
        _ = require_positive_state_config_int(
            {"max_parallel_memory_queries": True},
            key="max_parallel_memory_queries",
            error_message="invalid",
        )
