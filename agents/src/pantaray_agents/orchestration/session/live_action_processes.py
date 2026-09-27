"""Build stable keys for live action process lookups."""

from __future__ import annotations

from dataclasses import dataclass

from pantaray_agents.orchestration.common.normalization import (
    normalize_lower_string,
    normalize_string,
)
from pantaray_agents.schema.repositories.repository import DBRow

ACTION_STATUS_PROCESSING = "processing"
LIVE_ACTION_PROCESS_STATUSES = frozenset({"running", "paused"})


@dataclass(frozen=True)
class LiveActionProcessKey:
    """Stable identity for a live action process."""

    user_id: str
    process_id: str
    suggestion_id: str
    action_id: str
    command_id: str

    @classmethod
    def from_durable_action(
        cls,
        *,
        user_id: str,
        suggestion_id: str,
        action_row: DBRow,
        expected_action_id: str | None = None,
    ) -> LiveActionProcessKey | None:
        if (
            normalize_lower_string(action_row.get("action_status"))
            != ACTION_STATUS_PROCESSING
        ):
            return None
        process_status = normalize_lower_string(action_row.get("action_process_status"))
        if process_status not in LIVE_ACTION_PROCESS_STATUSES:
            return None

        action_id = normalize_string(action_row.get("action_id"))
        expected_action_id_norm = normalize_string(expected_action_id)
        if expected_action_id_norm is not None and action_id != expected_action_id_norm:
            return None

        return cls.from_values(
            user_id=user_id,
            process_id=action_row.get("action_process_id"),
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=action_row.get("action_command_id"),
        )

    @classmethod
    def from_values(
        cls,
        *,
        user_id: object,
        process_id: object,
        suggestion_id: object,
        action_id: object,
        command_id: object,
    ) -> LiveActionProcessKey | None:
        normalized_user_id = normalize_string(user_id)
        normalized_process_id = normalize_string(process_id)
        normalized_suggestion_id = normalize_string(suggestion_id)
        normalized_action_id = normalize_string(action_id)
        normalized_command_id = normalize_string(command_id)
        if not (
            normalized_user_id
            and normalized_process_id
            and normalized_suggestion_id
            and normalized_action_id
            and normalized_command_id
        ):
            return None
        return cls(
            user_id=normalized_user_id,
            process_id=normalized_process_id,
            suggestion_id=normalized_suggestion_id,
            action_id=normalized_action_id,
            command_id=normalized_command_id,
        )
