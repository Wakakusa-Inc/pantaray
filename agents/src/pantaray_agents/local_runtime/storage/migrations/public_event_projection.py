from __future__ import annotations

import sqlite3

from ...public_events import normalize_public_event_name
from .connection import column_exists

PUBLIC_EVENT_TABLE = "agent_process_events"
PUBLIC_HISTORY_TABLE = "agent_suggestion_history"
LEGACY_EVENT_TABLE = "agent_process_events_legacy_v15"
LEGACY_HISTORY_TABLE = "agent_suggestion_history_legacy_v15"


def apply_public_event_projection_alignment_migration(
    connection: sqlite3.Connection,
) -> None:
    _migrate_public_events(connection)
    _migrate_public_history(connection)


def _migrate_public_events(connection: sqlite3.Connection) -> None:
    if _is_public_event_table_aligned(connection):
        _ensure_public_event_indexes(connection)
        return
    connection.execute(
        f"ALTER TABLE {PUBLIC_EVENT_TABLE} RENAME TO {LEGACY_EVENT_TABLE}"
    )
    _create_public_event_table(connection)
    legacy_has_projection_columns = all(
        column_exists(connection, table_name=LEGACY_EVENT_TABLE, column_name=name)
        for name in ("suggestion_id", "user_id", "sequence")
    )
    if legacy_has_projection_columns:
        event_name_column = "event_name"
        event_id_column = (
            "event_id"
            if column_exists(
                connection, table_name=LEGACY_EVENT_TABLE, column_name="event_id"
            )
            else "process_event_id"
        )
        action_id_column = (
            "action_id"
            if column_exists(
                connection, table_name=LEGACY_EVENT_TABLE, column_name="action_id"
            )
            else "NULL"
        )
        payload_column = (
            "payload"
            if column_exists(
                connection, table_name=LEGACY_EVENT_TABLE, column_name="payload"
            )
            else "payload_json"
        )
        event_name_cases = " ".join(
            f"WHEN {event_name_column} = '{legacy_name}' THEN '{normalized_name}'"
            for legacy_name, normalized_name in _legacy_public_event_name_mappings()
        )
        normalized_event_name_expr = (
            f"CASE {event_name_cases} ELSE {event_name_column} END"
        )
        connection.execute(
            f"""
            INSERT INTO {PUBLIC_EVENT_TABLE}(
                event_id,
                suggestion_id,
                user_id,
                action_id,
                sequence,
                event_name,
                payload,
                created_at
            )
            SELECT
                {event_id_column},
                suggestion_id,
                user_id,
                {action_id_column},
                sequence,
                {normalized_event_name_expr},
                {payload_column},
                created_at
            FROM {LEGACY_EVENT_TABLE}
            WHERE suggestion_id IS NOT NULL
              AND user_id IS NOT NULL
              AND sequence IS NOT NULL
            ORDER BY suggestion_id ASC, sequence ASC
            """
        )
    connection.execute(f"DROP TABLE {LEGACY_EVENT_TABLE}")
    _ensure_public_event_indexes(connection)


def _migrate_public_history(connection: sqlite3.Connection) -> None:
    if _is_public_history_table_aligned(connection):
        ensure_public_history_indexes(connection)
        return
    connection.execute(
        f"ALTER TABLE {PUBLIC_HISTORY_TABLE} RENAME TO {LEGACY_HISTORY_TABLE}"
    )
    create_public_history_table(connection)
    legacy_status = _legacy_column_expr(connection, "status")
    legacy_answer = _legacy_column_expr(connection, "answer")
    legacy_interaction_contract = _legacy_column_expr(
        connection, "interaction_contract"
    )
    legacy_user_reaction = _legacy_column_expr(connection, "user_reaction")
    legacy_accepted_at = _legacy_column_expr(connection, "accepted_at")
    legacy_rejected_at = _legacy_column_expr(connection, "rejected_at")
    legacy_action_status = _legacy_column_expr(connection, "action_status")
    legacy_action_failure_code = _legacy_column_expr(connection, "action_failure_code")
    legacy_action_failure_stage = _legacy_column_expr(
        connection, "action_failure_stage"
    )
    legacy_action_failure_message_public = _legacy_column_expr(
        connection, "action_failure_message_public"
    )
    legacy_action_id = _legacy_column_expr(connection, "action_id")
    legacy_action_updated_at = _legacy_column_expr(connection, "action_updated_at")
    legacy_final_output = _legacy_column_expr(connection, "final_output")
    legacy_last_sequence = _legacy_column_expr(connection, "last_sequence", default="0")
    legacy_suggestion_updated_at = _legacy_column_expr(
        connection, "suggestion_updated_at"
    )
    connection.execute(
        f"""
        INSERT INTO {PUBLIC_HISTORY_TABLE}(
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
        )
        SELECT
            s.suggestion_id,
            s.user_id,
            s.created_at,
            COALESCE({legacy_suggestion_updated_at}, s.updated_at, s.created_at),
            COALESCE({legacy_status}, s.status),
            CASE
                WHEN COALESCE({legacy_interaction_contract}, s.interaction_contract) IS NOT NULL
                    THEN 1
                ELSE 0
            END,
            COALESCE({legacy_answer}, s.answer, ''),
            CASE
                WHEN COALESCE({legacy_interaction_contract}, s.interaction_contract) IS NOT NULL
                    THEN COALESCE({legacy_interaction_contract}, s.interaction_contract)
                ELSE NULL
            END,
            COALESCE({legacy_user_reaction}, s.user_reaction),
            COALESCE({legacy_accepted_at}, s.accepted_at),
            COALESCE({legacy_rejected_at}, s.rejected_at),
            COALESCE({legacy_action_status}, s.action_status),
            COALESCE({legacy_action_failure_code}, s.action_failure_code),
            COALESCE({legacy_action_failure_stage}, s.action_failure_stage),
            COALESCE(
                {legacy_action_failure_message_public},
                s.action_failure_message_public
            ),
            CASE
                WHEN s.action_request_payload IS NULL THEN 0
                ELSE 1
            END,
            COALESCE({legacy_action_id}, a.action_id),
            a.created_at,
            COALESCE({legacy_action_updated_at}, a.updated_at),
            COALESCE({legacy_final_output}, a.final_output),
            COALESCE({legacy_last_sequence}, 0)
        FROM agent_suggestions AS s
        LEFT JOIN {LEGACY_HISTORY_TABLE} AS legacy
            ON legacy.suggestion_id = s.suggestion_id
        LEFT JOIN agent_actions AS a
            ON a.suggestion_id = s.suggestion_id
        """
    )
    connection.execute(f"DROP TABLE {LEGACY_HISTORY_TABLE}")
    ensure_public_history_indexes(connection)


def _is_public_event_table_aligned(connection: sqlite3.Connection) -> bool:
    return all(
        column_exists(connection, table_name=PUBLIC_EVENT_TABLE, column_name=name)
        for name in ("event_id", "payload", "suggestion_id", "user_id", "sequence")
    ) and not column_exists(
        connection, table_name=PUBLIC_EVENT_TABLE, column_name="process_event_id"
    )


def _is_public_history_table_aligned(connection: sqlite3.Connection) -> bool:
    return all(
        column_exists(connection, table_name=PUBLIC_HISTORY_TABLE, column_name=name)
        for name in (
            "suggestion_id",
            "suggestion_created_at",
            "suggestion_updated_at",
            "suggestion_status",
            "has_suggestion",
            "action_request_payload_present",
        )
    ) and not column_exists(
        connection, table_name=PUBLIC_HISTORY_TABLE, column_name="history_id"
    )


def _legacy_public_event_name_mappings() -> tuple[tuple[str, str], ...]:
    legacy_event_names = ("action_start_retry_required",)
    return tuple(
        (
            legacy_event_name,
            normalize_public_event_name(event_name=legacy_event_name),
        )
        for legacy_event_name in legacy_event_names
    )


def _create_public_event_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE {PUBLIC_EVENT_TABLE} (
            event_id TEXT PRIMARY KEY,
            suggestion_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            action_id TEXT,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            event_name TEXT NOT NULL CHECK (
                event_name IN (
                    'process_started',
                    'suggestion_chunk',
                    'suggestion_reaction_committed',
                    'action_requested',
                    'action_resume_requested',
                    'action_summary',
                    'completion_chunk',
                    'process_paused',
                    'process_completed',
                    'error'
                )
            ),
            payload TEXT NOT NULL CHECK (json_valid(payload)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            UNIQUE (suggestion_id, sequence)
        )
        """
    )


def create_public_history_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        CREATE TABLE {PUBLIC_HISTORY_TABLE} (
            suggestion_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            suggestion_created_at TEXT NOT NULL,
            suggestion_updated_at TEXT NOT NULL,
            suggestion_status TEXT NOT NULL CHECK (
                suggestion_status IN ('processing', 'success', 'error', 'timeout', 'canceled')
            ),
            has_suggestion INTEGER NOT NULL CHECK (has_suggestion IN (0, 1)),
            answer TEXT NOT NULL,
            interaction_contract TEXT CHECK (
                interaction_contract IS NULL
                OR interaction_contract IN ('action_offer', 'message_only')
            ),
            user_reaction TEXT,
            accepted_at TEXT,
            rejected_at TEXT,
            action_status TEXT CHECK (
                action_status IS NULL
                OR action_status IN (
                    'idle',
                    'processing',
                    'success',
                    'error',
                    'canceled'
                )
            ),
            action_failure_code TEXT,
            action_failure_stage TEXT,
            action_failure_message_public TEXT,
            action_request_payload_present INTEGER NOT NULL DEFAULT 0 CHECK (
                action_request_payload_present IN (0, 1)
            ),
            action_id TEXT,
            action_created_at TEXT,
            action_updated_at TEXT,
            final_output TEXT,
            last_sequence INTEGER NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
            CHECK (interaction_contract <> 'message_only' OR user_reaction IS NULL),
            CHECK (
                (has_suggestion = 1 AND interaction_contract IS NOT NULL)
                OR (has_suggestion = 0 AND interaction_contract IS NULL)
            ),
            FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL
        )
        """
    )


def _legacy_column_expr(
    connection: sqlite3.Connection, column_name: str, *, default: str = "NULL"
) -> str:
    return (
        f"legacy.{column_name}"
        if column_exists(
            connection, table_name=LEGACY_HISTORY_TABLE, column_name=column_name
        )
        else default
    )


def _ensure_public_event_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_process_events_suggestion_sequence
        ON agent_process_events(suggestion_id, sequence ASC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_process_events_user_created
        ON agent_process_events(user_id, created_at DESC)
        """
    )


def ensure_public_history_indexes(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_suggestion_history_user_created
        ON agent_suggestion_history(user_id, suggestion_created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_suggestion_history_visible
        ON agent_suggestion_history(user_id, has_suggestion, suggestion_created_at DESC)
        """
    )
