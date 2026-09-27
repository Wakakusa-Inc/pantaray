from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import NamedTuple

from ..storage.migrations import MigrationError
from ..suggestion_state.public_projection import (
    FoldedSuggestionState,
    fold_suggestion_state_from_events,
    normalize_process_event_row,
)
from .action_legacy_shared_temp_runtime_purge_authority import (
    LegacyActionSharedTempRuntimePurgeAuthority,
    list_legacy_action_shared_temp_runtime_purge_authorities_in_connection,
)


class LegacySuggestionEvidence(NamedTuple):
    suggestion_id: str
    user_id: str
    answer: str | None
    has_suggestion: int | None
    interaction_contract: str | None
    user_reaction: str | None
    accepted_at: str | None
    rejected_at: str | None
    action_status: str | None
    action_failure_code: str | None
    action_failure_stage: str | None
    action_failure_message_public: str | None
    action_request_payload: str | None
    action_process_id: str | None
    action_command_id: str | None
    action_started_at: str | None
    created_at: str
    updated_at: str


class LegacySuggestionHistoryActionLaneEvidence(NamedTuple):
    suggestion_id: str
    user_id: str
    action_status: str | None
    action_failure_code: str | None
    action_failure_stage: str | None
    action_failure_message_public: str | None
    action_request_payload_present: int
    action_id: str | None
    action_created_at: str | None
    action_updated_at: str | None
    final_output: str | None
    last_sequence: int


class LegacySuggestionPublicEventEvidence(NamedTuple):
    event_id: str
    suggestion_id: str
    user_id: str
    action_id: str | None
    sequence: int
    event_name: str
    raw_payload_json: str
    created_at: str


class LegacyActionMemoryEvidence(NamedTuple):
    user_id: str
    node_id: str
    lifecycle: str
    integrity: str
    current_revision_id: str
    updated_at: str
    body_kind: str


class LegacySuggestionProjectionPurgeProof(NamedTuple):
    suggestion: LegacySuggestionEvidence
    history_action_lane: LegacySuggestionHistoryActionLaneEvidence
    public_events: tuple[LegacySuggestionPublicEventEvidence, ...]


class LegacyActionSharedTempSuggestionProjectionAuthority(NamedTuple):
    runtime_authority: LegacyActionSharedTempRuntimePurgeAuthority
    suggestion_projection: LegacySuggestionProjectionPurgeProof | None
    action_memory: LegacyActionMemoryEvidence | None


def list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[LegacyActionSharedTempSuggestionProjectionAuthority, ...]:
    return tuple(
        LegacyActionSharedTempSuggestionProjectionAuthority(
            runtime,
            _load_suggestion_projection(connection, runtime=runtime),
            _load_action_memory(connection, runtime=runtime),
        )
        for runtime in list_legacy_action_shared_temp_runtime_purge_authorities_in_connection(
            connection=connection, resolved_db_path=resolved_db_path
        )
    )


def _load_action_memory(
    connection: sqlite3.Connection,
    *,
    runtime: LegacyActionSharedTempRuntimePurgeAuthority,
) -> LegacyActionMemoryEvidence | None:
    action = runtime.action
    rows = connection.execute(
        """SELECT nodes.user_id,nodes.node_id,nodes.lifecycle,nodes.integrity,
                  nodes.current_revision_id,nodes.updated_at,revisions.body_kind
           FROM memory_nodes AS nodes LEFT JOIN memory_revisions AS revisions
             ON revisions.user_id=nodes.user_id AND revisions.node_id=nodes.node_id
            AND revisions.revision_id=nodes.current_revision_id
           WHERE nodes.source_type='action' AND nodes.source_record_id=?
           ORDER BY nodes.user_id,nodes.node_id""",
        (action.action_id,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise MigrationError("legacy Action memory evidence is inconsistent")
    evidence = LegacyActionMemoryEvidence._make(rows[0])
    if (
        evidence.user_id != action.user_id
        or evidence.lifecycle != "active"
        or evidence.integrity != "healthy"
        or not isinstance(evidence.current_revision_id, str)
        or not evidence.current_revision_id.strip()
        or evidence.body_kind != "inline"
    ):
        raise MigrationError("legacy Action memory evidence is inconsistent")
    return evidence


def _load_suggestion_projection(
    connection: sqlite3.Connection,
    *,
    runtime: LegacyActionSharedTempRuntimePurgeAuthority,
) -> LegacySuggestionProjectionPurgeProof | None:
    action = runtime.action
    if action.suggestion_id is None:
        return None
    suggestion_id = action.suggestion_id
    suggestion_row = connection.execute(
        f"SELECT {_SUGGESTION_COLUMNS} FROM agent_suggestions WHERE suggestion_id=?",
        (suggestion_id,),
    ).fetchone()
    history_row = connection.execute(
        f"SELECT {_HISTORY_COLUMNS} FROM agent_suggestion_history WHERE suggestion_id=?",
        (suggestion_id,),
    ).fetchone()
    if suggestion_row is None or history_row is None:
        raise MigrationError("legacy Action Suggestion projection is incomplete")
    suggestion = LegacySuggestionEvidence._make(suggestion_row)
    if suggestion.user_id != action.user_id or history_row[1] != action.user_id:
        raise MigrationError("legacy Suggestion projection owner is inconsistent")

    event_rows = connection.execute(
        f"""SELECT {_PUBLIC_EVENT_COLUMNS} FROM agent_process_events
            WHERE suggestion_id=? ORDER BY sequence,event_id""",
        (suggestion_id,),
    ).fetchall()
    events = tuple(LegacySuggestionPublicEventEvidence._make(row) for row in event_rows)
    if any(
        event.user_id != action.user_id
        or event.action_id not in {None, action.action_id}
        for event in events
    ):
        raise MigrationError("legacy Action Suggestion event relation is inconsistent")
    normalized_events = [normalize_process_event_row(row) for row in event_rows]
    folded = fold_suggestion_state_from_events(
        suggestion_id=suggestion_id, rows=normalized_events
    )
    if tuple(history_row) != _expected_history(
        suggestion=suggestion, runtime=runtime, folded=folded
    ):
        raise MigrationError("legacy Suggestion history projection is inconsistent")

    remaining = fold_suggestion_state_from_events(
        suggestion_id=suggestion_id,
        rows=[
            row
            for event, row in zip(events, normalized_events, strict=True)
            if event.action_id is None
        ],
    )
    if (
        folded.suggestion_text != remaining.suggestion_text
        or folded.interaction_contract != remaining.interaction_contract
        or folded.user_reaction != remaining.user_reaction
        or folded.accepted_at != remaining.accepted_at
        or folded.rejected_at != remaining.rejected_at
        or folded.suggestion_status != remaining.suggestion_status
    ):
        raise MigrationError("legacy Action removal changes the Suggestion lane")
    if remaining.approval_blockers or any(
        (
            remaining.action_status,
            remaining.action_failure_code,
            remaining.action_failure_stage,
            remaining.action_failure_message_public,
            remaining.final_output,
            remaining.command_id,
            remaining.process_id,
            remaining.action_id,
        )
    ):
        raise MigrationError("legacy Action removal leaves a projected Action lane")
    return LegacySuggestionProjectionPurgeProof(
        suggestion,
        LegacySuggestionHistoryActionLaneEvidence._make(
            (history_row[0], history_row[1], *history_row[11:21])
        ),
        events,
    )


def _expected_history(
    *,
    suggestion: LegacySuggestionEvidence,
    runtime: LegacyActionSharedTempRuntimePurgeAuthority,
    folded: FoldedSuggestionState,
) -> tuple[str | int | None, ...]:
    action = runtime.action
    if folded.action_id is not None and folded.action_id != action.action_id:
        raise MigrationError("legacy Suggestion fold belongs to a different Action")
    has_suggestion = suggestion.has_suggestion
    if has_suggestion is None:
        has_suggestion = int(folded.interaction_contract is not None)
    interaction_contract = (
        folded.interaction_contract or suggestion.interaction_contract
    )
    if has_suggestion == 0:
        interaction_contract = None
    return (
        suggestion.suggestion_id,
        suggestion.user_id,
        suggestion.created_at,
        folded.updated_at or suggestion.updated_at,
        folded.suggestion_status,
        has_suggestion,
        folded.suggestion_text or suggestion.answer or "",
        interaction_contract,
        folded.user_reaction,
        folded.accepted_at,
        folded.rejected_at,
        folded.action_status or _optional_text(suggestion.action_status),
        folded.action_failure_code or _optional_text(suggestion.action_failure_code),
        folded.action_failure_stage or _optional_text(suggestion.action_failure_stage),
        folded.action_failure_message_public
        or _optional_text(suggestion.action_failure_message_public),
        int(suggestion.action_request_payload is not None),
        action.action_id,
        action.created_at,
        action.updated_at,
        folded.final_output if folded.final_output is not None else action.final_output,
        folded.last_sequence,
    )


def _optional_text(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


_SUGGESTION_COLUMNS = """suggestion_id,user_id,answer,has_suggestion,interaction_contract,user_reaction,accepted_at,rejected_at,action_status,action_failure_code,action_failure_stage,action_failure_message_public,action_request_payload,action_process_id,action_command_id,action_started_at,created_at,updated_at"""
_HISTORY_COLUMNS = """suggestion_id,user_id,suggestion_created_at,suggestion_updated_at,suggestion_status,has_suggestion,answer,interaction_contract,user_reaction,accepted_at,rejected_at,action_status,action_failure_code,action_failure_stage,action_failure_message_public,action_request_payload_present,action_id,action_created_at,action_updated_at,final_output,last_sequence"""
_PUBLIC_EVENT_COLUMNS = """event_id,suggestion_id,user_id,action_id,sequence,event_name,payload,created_at"""
