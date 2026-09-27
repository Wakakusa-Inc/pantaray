from __future__ import annotations

EVENT_ACTION_REQUESTED = "action_requested"
EVENT_ACTION_RESUME_REQUESTED = "action_resume_requested"
EVENT_PROCESS_STARTED = "process_started"
EVENT_ERROR = "error"
EVENT_SUGGESTION_REACTION_COMMITTED = "suggestion_reaction_committed"

ACTION_RELAY_INTERNAL_EVENT_NAMES: frozenset[str] = frozenset(
    {
        EVENT_ACTION_REQUESTED,
        EVENT_ACTION_RESUME_REQUESTED,
    }
)
