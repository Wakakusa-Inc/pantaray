"""ActionAgent runtime step helpers."""

from pantaray_agents.schema.agent.action_history import (
    GOAL_SCOPE_RE,
    SUPERVISOR_SCOPE_HANDLE,
)

from .counters import (
    DEFAULT_STEP_INCREMENT,
    CounterInvariantError,
    compute_step_counter_delta,
    get_llm_steps_taken,
    get_tool_steps_taken,
    increment_llm_steps_taken,
    increment_local_step_counter,
    increment_tool_steps_taken,
    require_local_step_counter_value,
    require_local_step_counters_map,
    require_scope_handle,
    require_step_counter_value,
    sync_steps_taken,
)
from .persistence import (
    DEFAULT_ACTION_STEP_PERSISTENCE_RETRY_POLICY,
    ActionStepPersistenceError,
    ActionStepPersistenceRetryPolicy,
    classify_repository_exception,
    extract_repository_error_message,
    is_retryable_repository_result,
    save_action_step_with_retry,
)

__all__ = [
    "ActionStepPersistenceError",
    "ActionStepPersistenceRetryPolicy",
    "classify_repository_exception",
    "compute_step_counter_delta",
    "CounterInvariantError",
    "DEFAULT_STEP_INCREMENT",
    "DEFAULT_ACTION_STEP_PERSISTENCE_RETRY_POLICY",
    "GOAL_SCOPE_RE",
    "SUPERVISOR_SCOPE_HANDLE",
    "extract_repository_error_message",
    "get_llm_steps_taken",
    "get_tool_steps_taken",
    "increment_llm_steps_taken",
    "increment_local_step_counter",
    "increment_tool_steps_taken",
    "is_retryable_repository_result",
    "require_local_step_counter_value",
    "require_local_step_counters_map",
    "require_scope_handle",
    "require_step_counter_value",
    "save_action_step_with_retry",
    "sync_steps_taken",
]
