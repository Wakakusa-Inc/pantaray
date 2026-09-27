from __future__ import annotations

PUBLIC_EVENT_NAME_ERROR = "error"
PUBLIC_EVENT_NAME_ACTION_START_RETRY_REQUIRED = "action_start_retry_required"


def normalize_public_event_name(*, event_name: str) -> str:
    if event_name == PUBLIC_EVENT_NAME_ACTION_START_RETRY_REQUIRED:
        return PUBLIC_EVENT_NAME_ERROR
    return event_name
