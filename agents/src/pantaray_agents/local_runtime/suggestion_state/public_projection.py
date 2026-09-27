from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from typing import cast

from pantaray_agents.action_status import (
    ACTION_STATUS_ERROR,
    ACTION_STATUS_IDLE,
    ACTION_STATUS_PROCESSING,
    ACTION_TERMINAL_STATUSES,
    ActionRuntimeStatus,
    parse_stored_suggestion_user_reaction,
)
from pantaray_agents.schema.repositories.repository import DBRow
from pantaray_agents.utils.structured_logging import (
    fingerprint_text,
    log_structured_event,
)

from ..storage.migrations import MigrationError
from .boolean_flags import (
    normalize_optional_sqlite_bool,
    normalize_required_sqlite_bool,
)
from .event_names import (
    EVENT_ACTION_REQUESTED,
    EVENT_ACTION_RESUME_REQUESTED,
)

EVENT_PROCESS_COMPLETED = "process_completed"
EVENT_PROCESS_PAUSED = "process_paused"
logger = logging.getLogger(__name__)

# Public process event payloads are validated incrementally by event type.
type ProcessEventRow = dict[str, object]


def normalize_history_row(row: sqlite3.Row) -> DBRow:
    normalized: DBRow = dict(row)
    normalized["has_suggestion"] = normalize_required_sqlite_bool(
        normalized.get("has_suggestion"),
        field_name="agent_suggestion_history.has_suggestion",
    )
    normalized["action_request_payload_present"] = normalize_required_sqlite_bool(
        normalized.get("action_request_payload_present"),
        field_name="agent_suggestion_history.action_request_payload_present",
    )
    normalized["user_reaction"] = parse_stored_suggestion_user_reaction(
        normalized.get("user_reaction")
    )
    return normalized


def normalize_process_event_row(row: sqlite3.Row) -> ProcessEventRow:
    normalized: ProcessEventRow = dict(row)
    normalized["payload"] = _decode_json_object(normalized.pop("payload", None))
    return normalized


def _is_action_process_started_payload(data_obj: ProcessEventRow) -> bool:
    kind = _normalize_optional_string(data_obj.get("kind"))
    if kind == "action":
        return True
    return _normalize_optional_string(data_obj.get("action_id")) is not None


@dataclass(frozen=True)
class FoldedSuggestionState:
    suggestion_id: str
    suggestion_text: str
    interaction_contract: str | None
    user_reaction: str | None
    accepted_at: str | None
    rejected_at: str | None
    action_status: ActionRuntimeStatus | None
    action_failure_code: str | None
    action_failure_stage: str | None
    action_failure_message_public: str | None
    final_output: str | None
    command_id: str | None
    process_id: str | None
    action_id: str | None
    approval_blockers: list[ProcessEventRow]
    updated_at: str | None
    last_sequence: int
    suggestion_status: str


def fold_suggestion_state_from_events(
    *,
    suggestion_id: str,
    rows: list[ProcessEventRow],
) -> FoldedSuggestionState:
    suggestion_chunks: list[str] = []
    interaction_contract: str | None = None
    user_reaction: str | None = None
    accepted_at: str | None = None
    rejected_at: str | None = None
    action_status: ActionRuntimeStatus | None = None
    action_failure_code: str | None = None
    action_failure_stage: str | None = None
    action_failure_message_public: str | None = None
    final_output: str | None = None
    command_id: str | None = None
    process_id: str | None = None
    action_id: str | None = None
    approval_blockers: list[ProcessEventRow] = []
    updated_at: str | None = None
    last_sequence = 0
    suggestion_status = "processing"

    for row in rows:
        current_sequence = _read_sequence(row, previous_sequence=last_sequence)
        last_sequence = current_sequence
        updated_at = _normalize_optional_string(row.get("created_at")) or updated_at
        raw_payload = row.get("payload")
        payload_obj: ProcessEventRow = (
            cast(ProcessEventRow, raw_payload) if isinstance(raw_payload, dict) else {}
        )
        raw_data = payload_obj.get("data")
        data_obj: ProcessEventRow = (
            cast(ProcessEventRow, raw_data) if isinstance(raw_data, dict) else {}
        )
        event_name = _normalize_optional_string(row.get("event_name")) or ""

        if event_name == "suggestion_chunk":
            content = data_obj.get("content")
            if isinstance(content, str):
                suggestion_chunks.append(content)
            continue
        if event_name == "suggestion_reaction_committed":
            reaction = parse_stored_suggestion_user_reaction(data_obj.get("reaction"))
            if reaction is not None:
                user_reaction = reaction
                committed_at = _normalize_optional_string(data_obj.get("committed_at"))
                if reaction == "accepted":
                    accepted_at = committed_at
                elif reaction == "rejected":
                    rejected_at = committed_at
            continue
        if event_name == EVENT_ACTION_REQUESTED:
            if action_status in {
                ACTION_STATUS_PROCESSING,
                *ACTION_TERMINAL_STATUSES,
            }:
                log_structured_event(
                    logger,
                    level="warning",
                    evt="SUGGESTION_STATE_ACTION_REQUESTED_AFTER_ADVANCE",
                    component="local_runtime.suggestion_state.public_projection",
                    suggestion_id_fp=fingerprint_text(suggestion_id),
                    sequence=current_sequence,
                    prior_action_status=action_status,
                    prior_process_id_fp=fingerprint_text(process_id),
                    prior_action_id_fp=fingerprint_text(action_id),
                    command_id_fp=fingerprint_text(
                        _normalize_optional_string(data_obj.get("command_id"))
                    ),
                )
            user_reaction = "accepted"
            accepted_at = _normalize_optional_string(data_obj.get("accepted_at"))
            command_id = _normalize_optional_string(data_obj.get("command_id"))
            process_id = (
                _normalize_optional_string(data_obj.get("process_id")) or process_id
            )
            action_id = (
                _normalize_optional_string(data_obj.get("action_id")) or action_id
            )
            action_status = ACTION_STATUS_IDLE
            approval_blockers = []
            continue
        if event_name == EVENT_ACTION_RESUME_REQUESTED:
            process_id = (
                _normalize_optional_string(data_obj.get("process_id")) or process_id
            )
            command_id = (
                _normalize_optional_string(data_obj.get("command_id")) or command_id
            )
            approval_blockers = []
            continue
        if event_name == "action_start_retry_required":
            user_reaction = "accepted"
            accepted_at = (
                _normalize_optional_string(data_obj.get("accepted_at")) or accepted_at
            )
            command_id = (
                _normalize_optional_string(data_obj.get("command_id")) or command_id
            )
            process_id = (
                _normalize_optional_string(data_obj.get("process_id")) or process_id
            )
            action_status = ACTION_STATUS_ERROR
            action_failure_code = _normalize_optional_string(
                data_obj.get("failure_code")
            )
            action_failure_stage = _normalize_optional_string(
                data_obj.get("failure_stage")
            )
            action_failure_message_public = _normalize_optional_string(
                data_obj.get("failure_message_public")
            )
            continue
        if event_name == "process_started":
            if _is_action_process_started_payload(data_obj):
                process_id = (
                    _normalize_optional_string(data_obj.get("process_id")) or process_id
                )
                action_id = (
                    _normalize_optional_string(data_obj.get("action_id")) or action_id
                )
                command_id = (
                    _normalize_optional_string(data_obj.get("command_id")) or command_id
                )
                accepted_at = (
                    _normalize_optional_string(data_obj.get("accepted_at"))
                    or accepted_at
                )
                action_status = ACTION_STATUS_PROCESSING
                approval_blockers = []
            continue
        if event_name == EVENT_PROCESS_COMPLETED:
            kind = _normalize_optional_string(data_obj.get("kind"))
            status = _normalize_optional_string(data_obj.get("status"))
            if kind == "suggestion":
                suggestion_status = status or suggestion_status
                interaction_contract = _normalize_optional_string(
                    data_obj.get("interaction_contract")
                )
                continue
            if kind == "action":
                action_status = _normalize_action_status_optional(status)
                process_id = (
                    _normalize_optional_string(data_obj.get("process_id")) or process_id
                )
                action_id = (
                    _normalize_optional_string(data_obj.get("action_id")) or action_id
                )
                command_id = (
                    _normalize_optional_string(data_obj.get("command_id")) or command_id
                )
                final_output = _normalize_optional_string(data_obj.get("final_output"))
                approval_blockers = []
                action_failure_code = _normalize_optional_string(
                    data_obj.get("failure_code")
                )
                action_failure_stage = _normalize_optional_string(
                    data_obj.get("failure_stage")
                )
                action_failure_message_public = _normalize_optional_string(
                    data_obj.get("failure_message_public")
                )
                continue
        if event_name == EVENT_PROCESS_PAUSED:
            kind = _normalize_optional_string(data_obj.get("kind"))
            reason = _normalize_optional_string(data_obj.get("reason"))
            if kind == "action" and reason == "approval_pending":
                action_status = ACTION_STATUS_PROCESSING
                process_id = (
                    _normalize_optional_string(data_obj.get("process_id")) or process_id
                )
                action_id = (
                    _normalize_optional_string(data_obj.get("action_id")) or action_id
                )
                command_id = (
                    _normalize_optional_string(data_obj.get("command_id")) or command_id
                )
                raw_blockers = data_obj.get("approval_blockers")
                approval_blockers = (
                    [
                        cast(ProcessEventRow, dict(item))
                        for item in raw_blockers
                        if isinstance(item, dict)
                    ]
                    if isinstance(raw_blockers, list)
                    else []
                )
                continue
        if event_name == "error":
            retry_failure_code = _normalize_optional_string(
                data_obj.get("failure_code")
            )
            if retry_failure_code is not None:
                user_reaction = "accepted"
                accepted_at = (
                    _normalize_optional_string(data_obj.get("accepted_at"))
                    or accepted_at
                )
                command_id = (
                    _normalize_optional_string(data_obj.get("command_id")) or command_id
                )
                process_id = (
                    _normalize_optional_string(data_obj.get("process_id")) or process_id
                )
                action_status = ACTION_STATUS_IDLE
                action_failure_code = retry_failure_code
                action_failure_stage = _normalize_optional_string(
                    data_obj.get("failure_stage")
                )
                action_failure_message_public = _normalize_optional_string(
                    data_obj.get("failure_message_public")
                )
                continue
            if action_status is None:
                action_failure_code = _normalize_optional_string(
                    data_obj.get("error_code")
                )
                action_failure_message_public = _normalize_optional_string(
                    data_obj.get("error_message")
                )

    return FoldedSuggestionState(
        suggestion_id=suggestion_id,
        suggestion_text="".join(suggestion_chunks),
        interaction_contract=interaction_contract,
        user_reaction=user_reaction,
        accepted_at=accepted_at,
        rejected_at=rejected_at,
        action_status=action_status,
        action_failure_code=action_failure_code,
        action_failure_stage=action_failure_stage,
        action_failure_message_public=action_failure_message_public,
        final_output=final_output,
        command_id=command_id,
        process_id=process_id,
        action_id=action_id,
        approval_blockers=approval_blockers,
        updated_at=updated_at,
        last_sequence=last_sequence,
        suggestion_status=suggestion_status,
    )


def _normalize_action_status_optional(value: str | None) -> ActionRuntimeStatus | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized in {ACTION_STATUS_IDLE, ACTION_STATUS_PROCESSING}:
        return cast(ActionRuntimeStatus, normalized)
    if normalized in ACTION_TERMINAL_STATUSES:
        return cast(ActionRuntimeStatus, normalized)
    raise ValueError(f"Unsupported action status in public projection: {value!r}")


def rebuild_history_projection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    suggestion_id: str,
) -> FoldedSuggestionState:
    rows = connection.execute(
        """
        SELECT *
        FROM agent_process_events
        WHERE user_id = ? AND suggestion_id = ?
        ORDER BY sequence ASC
        """,
        (user_id, suggestion_id),
    ).fetchall()
    folded = fold_suggestion_state_from_events(
        suggestion_id=suggestion_id,
        rows=[normalize_process_event_row(row) for row in rows],
    )
    suggestion_row = connection.execute(
        """
        SELECT
            created_at,
            updated_at,
            status,
            has_suggestion,
            answer,
            interaction_contract,
            action_request_payload,
            action_status,
            action_failure_code,
            action_failure_stage,
            action_failure_message_public
        FROM agent_suggestions
        WHERE user_id = ? AND suggestion_id = ?
        """,
        (user_id, suggestion_id),
    ).fetchone()
    if suggestion_row is None:
        raise MigrationError(
            f"suggestion not found for history projection: {suggestion_id}"
        )
    action_row = connection.execute(
        """
        SELECT action_id, created_at, updated_at, final_output
        FROM agent_actions
        WHERE user_id = ? AND suggestion_id = ?
        """,
        (user_id, suggestion_id),
    ).fetchone()
    canonical_action_id = None if action_row is None else str(action_row["action_id"])
    if folded.action_id is not None and folded.action_id != canonical_action_id:
        raise MigrationError(
            "Suggestion event Action relation does not match canonical Action"
        )
    has_suggestion = _resolve_has_suggestion(suggestion_row, folded)
    interaction_contract = folded.interaction_contract or _normalize_optional_string(
        suggestion_row["interaction_contract"]
    )
    if has_suggestion == 0:
        interaction_contract = None
    history_projection_values = (
        suggestion_id,
        user_id,
        str(suggestion_row["created_at"]),
        folded.updated_at or str(suggestion_row["updated_at"]),
        folded.suggestion_status,
        has_suggestion,
        folded.suggestion_text or str(suggestion_row["answer"] or ""),
        interaction_contract,
        folded.user_reaction,
        folded.accepted_at,
        folded.rejected_at,
        folded.action_status
        or _normalize_action_status_optional(
            _normalize_optional_string(suggestion_row["action_status"])
        ),
        folded.action_failure_code
        or _normalize_optional_string(suggestion_row["action_failure_code"]),
        folded.action_failure_stage
        or _normalize_optional_string(suggestion_row["action_failure_stage"]),
        folded.action_failure_message_public
        or _normalize_optional_string(suggestion_row["action_failure_message_public"]),
        0 if suggestion_row["action_request_payload"] is None else 1,
        canonical_action_id,
        None if action_row is None else action_row["created_at"],
        None if action_row is None else action_row["updated_at"],
        folded.final_output
        if folded.final_output is not None
        else None
        if action_row is None
        else action_row["final_output"],
        folded.last_sequence,
    )
    history_projection_placeholders = ", ".join("?" for _ in history_projection_values)
    connection.execute(
        f"""
        INSERT INTO agent_suggestion_history(
            suggestion_id,
            user_id,
            suggestion_created_at,
            suggestion_updated_at,
            suggestion_status,
            has_suggestion,
            answer,
            interaction_contract,
            user_reaction,
            accepted_at,
            rejected_at,
            action_status,
            action_failure_code,
            action_failure_stage,
            action_failure_message_public,
            action_request_payload_present,
            action_id,
            action_created_at,
            action_updated_at,
            final_output,
            last_sequence
        ) VALUES ({history_projection_placeholders})
        ON CONFLICT(suggestion_id) DO UPDATE SET
            user_id = excluded.user_id,
            suggestion_created_at = excluded.suggestion_created_at,
            suggestion_updated_at = excluded.suggestion_updated_at,
            suggestion_status = excluded.suggestion_status,
            has_suggestion = excluded.has_suggestion,
            answer = excluded.answer,
            interaction_contract = excluded.interaction_contract,
            user_reaction = excluded.user_reaction,
            accepted_at = excluded.accepted_at,
            rejected_at = excluded.rejected_at,
            action_status = excluded.action_status,
            action_failure_code = excluded.action_failure_code,
            action_failure_stage = excluded.action_failure_stage,
            action_failure_message_public = excluded.action_failure_message_public,
            action_request_payload_present = excluded.action_request_payload_present,
            action_id = excluded.action_id,
            action_created_at = excluded.action_created_at,
            action_updated_at = excluded.action_updated_at,
            final_output = excluded.final_output,
            last_sequence = excluded.last_sequence
        """,
        history_projection_values,
    )
    return folded


def _decode_json_object(raw_value: object) -> ProcessEventRow | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise MigrationError("expected JSON text column to be a string")
    decoded = json.loads(raw_value)
    if not isinstance(decoded, dict):
        raise MigrationError("expected JSON object payload")
    return cast(ProcessEventRow, decoded)


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_sequence(row: ProcessEventRow, *, previous_sequence: int) -> int:
    raw_sequence = row.get("sequence")
    if raw_sequence is None:
        raise ValueError("public event sequence is missing")
    if isinstance(raw_sequence, bool) or not isinstance(raw_sequence, (int, str)):
        raise ValueError("public event sequence must be an integer")
    try:
        current_sequence = int(raw_sequence)
    except (TypeError, ValueError) as exc:
        raise ValueError("public event sequence must be an integer") from exc
    if current_sequence <= 0:
        raise ValueError("public event sequence must be positive")
    if current_sequence <= previous_sequence:
        raise ValueError("public event sequence must be strictly increasing")
    return current_sequence


def _resolve_has_suggestion(
    suggestion_row: sqlite3.Row,
    folded: FoldedSuggestionState,
) -> int:
    raw_value = normalize_optional_sqlite_bool(
        suggestion_row["has_suggestion"],
        field_name="agent_suggestions.has_suggestion",
    )
    if raw_value is not None:
        return int(raw_value)
    if folded.interaction_contract is not None:
        return 1
    return 0
