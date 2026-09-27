from __future__ import annotations

import sqlite3

from .action_history_schema import (
    create_agent_suggestions_table,
    ensure_agent_suggestions_indexes,
)
from .action_status_alignment_fk import (
    drop_legacy_tables,
    rebuild_tables_with_legacy_foreign_keys,
)
from .connection import column_exists, table_exists
from .public_event_projection import (
    create_public_history_table,
    ensure_public_history_indexes,
)

CURRENT_HISTORY_TABLE = "agent_suggestion_history"
CURRENT_SUGGESTIONS_TABLE = "agent_suggestions"
LEGACY_HISTORY_TABLE = "agent_suggestion_history_legacy_v28"
LEGACY_SUGGESTIONS_TABLE = "agent_suggestions_legacy_v28"
LEGACY_TABLE_NAMES = (
    LEGACY_HISTORY_TABLE,
    LEGACY_SUGGESTIONS_TABLE,
)


def apply_remove_intervention_mode_migration(connection: sqlite3.Connection) -> None:
    legacy_suggestions_exists = table_exists(
        connection, table_name=LEGACY_SUGGESTIONS_TABLE
    )
    current_suggestions_exists = table_exists(
        connection, table_name=CURRENT_SUGGESTIONS_TABLE
    )
    current_history_exists = table_exists(connection, table_name=CURRENT_HISTORY_TABLE)
    legacy_history_exists = table_exists(connection, table_name=LEGACY_HISTORY_TABLE)
    migrate_suggestions = current_suggestions_exists and column_exists(
        connection,
        table_name=CURRENT_SUGGESTIONS_TABLE,
        column_name="intervention_mode",
    )

    history_source_table = _resolve_history_source_table(
        current_history_exists=current_history_exists,
        legacy_history_exists=legacy_history_exists,
    )
    rebuild_history = history_source_table is not None and (
        history_source_table == LEGACY_HISTORY_TABLE
        or _table_schema_mentions_identifier(
            connection,
            table_name=history_source_table,
            identifier="intervention_mode",
        )
        or column_exists(
            connection,
            table_name=history_source_table,
            column_name="intervention_mode",
        )
        or _table_references_parent(
            connection,
            table_name=history_source_table,
            parent_table_name=LEGACY_SUGGESTIONS_TABLE,
        )
    )

    connection.execute("PRAGMA defer_foreign_keys = ON;")

    if legacy_suggestions_exists and not current_suggestions_exists:
        create_agent_suggestions_table(connection)

    if legacy_suggestions_exists:
        _backfill_agent_suggestions_from_legacy(connection)

    if rebuild_history and history_source_table is not None:
        _rebuild_history_table(connection, source_table=history_source_table)

    if migrate_suggestions:
        _remove_intervention_mode_from_current_suggestions(connection)

    rebuild_tables_with_legacy_foreign_keys(
        connection,
        legacy_table_names=LEGACY_TABLE_NAMES,
    )
    drop_legacy_tables(
        connection,
        legacy_table_names=LEGACY_TABLE_NAMES,
    )

    ensure_agent_suggestions_indexes(connection)
    if table_exists(connection, table_name=CURRENT_HISTORY_TABLE):
        ensure_public_history_indexes(connection)


def _resolve_history_source_table(
    *,
    current_history_exists: bool,
    legacy_history_exists: bool,
) -> str | None:
    if legacy_history_exists:
        return LEGACY_HISTORY_TABLE
    if current_history_exists:
        return CURRENT_HISTORY_TABLE
    return None


def _remove_intervention_mode_from_current_suggestions(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        UPDATE agent_suggestions
        SET has_suggestion = CASE
            WHEN status = 'processing' THEN NULL
            WHEN interaction_contract IS NOT NULL THEN 1
            ELSE 0
        END
        """
    )
    connection.execute("ALTER TABLE agent_suggestions DROP COLUMN intervention_mode")


def _backfill_agent_suggestions_from_legacy(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        INSERT INTO {CURRENT_SUGGESTIONS_TABLE}(
            suggestion_id,
            user_id,
            status,
            answer,
            thinking,
            error,
            prompt_text,
            response_text,
            prompt_name,
            prompt_version,
            has_suggestion,
            request_images_count,
            used_images_count,
            interaction_contract,
            user_reaction,
            accepted_at,
            rejected_at,
            action_status,
            action_failure_code,
            action_failure_stage,
            action_failure_message_public,
            action_request_payload,
            action_process_id,
            action_execution_id,
            action_command_id,
            action_started_at,
            process_event_sequence,
            created_at,
            updated_at
        )
        SELECT
            legacy.suggestion_id,
            legacy.user_id,
            legacy.status,
            legacy.answer,
            legacy.thinking,
            legacy.error,
            legacy.prompt_text,
            legacy.response_text,
            legacy.prompt_name,
            legacy.prompt_version,
            CASE
                WHEN legacy.status = 'processing' THEN NULL
                WHEN legacy.interaction_contract IS NOT NULL THEN 1
                ELSE 0
            END,
            legacy.request_images_count,
            legacy.used_images_count,
            legacy.interaction_contract,
            legacy.user_reaction,
            legacy.accepted_at,
            legacy.rejected_at,
            legacy.action_status,
            legacy.action_failure_code,
            legacy.action_failure_stage,
            legacy.action_failure_message_public,
            legacy.action_request_payload,
            legacy.action_process_id,
            legacy.action_execution_id,
            legacy.action_command_id,
            legacy.action_started_at,
            legacy.process_event_sequence,
            legacy.created_at,
            legacy.updated_at
        FROM {LEGACY_SUGGESTIONS_TABLE} AS legacy
        WHERE NOT EXISTS (
            SELECT 1
            FROM {CURRENT_SUGGESTIONS_TABLE} AS current
            WHERE current.suggestion_id = legacy.suggestion_id
        )
        """
    )


def _rebuild_history_table(
    connection: sqlite3.Connection, *, source_table: str
) -> None:
    if source_table == CURRENT_HISTORY_TABLE:
        if table_exists(connection, table_name=LEGACY_HISTORY_TABLE):
            connection.execute(f"DROP TABLE {LEGACY_HISTORY_TABLE}")
        connection.execute(
            f"ALTER TABLE {CURRENT_HISTORY_TABLE} RENAME TO {LEGACY_HISTORY_TABLE}"
        )
    elif table_exists(connection, table_name=CURRENT_HISTORY_TABLE):
        connection.execute(f"DROP TABLE {CURRENT_HISTORY_TABLE}")

    create_public_history_table(connection)
    _copy_agent_suggestion_history_from_legacy(connection)
    connection.execute(f"DROP TABLE {LEGACY_HISTORY_TABLE}")


def _copy_agent_suggestion_history_from_legacy(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        INSERT INTO {CURRENT_HISTORY_TABLE}(
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
            legacy.suggestion_id,
            legacy.user_id,
            legacy.suggestion_created_at,
            legacy.suggestion_updated_at,
            legacy.suggestion_status,
            CASE
                WHEN legacy.interaction_contract IS NOT NULL THEN 1
                ELSE 0
            END,
            legacy.answer,
            legacy.interaction_contract,
            legacy.user_reaction,
            legacy.accepted_at,
            legacy.rejected_at,
            legacy.action_status,
            legacy.action_failure_code,
            legacy.action_failure_stage,
            legacy.action_failure_message_public,
            legacy.action_request_payload_present,
            legacy.action_id,
            legacy.action_created_at,
            legacy.action_updated_at,
            legacy.final_output,
            legacy.last_sequence
        FROM {LEGACY_HISTORY_TABLE} AS legacy
        """
    )


def _table_references_parent(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    parent_table_name: str,
) -> bool:
    foreign_keys = connection.execute(
        f"PRAGMA foreign_key_list('{table_name}')"
    ).fetchall()
    return any(str(foreign_key[2]) == parent_table_name for foreign_key in foreign_keys)


def _table_schema_mentions_identifier(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    identifier: str,
) -> bool:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if row is None or row[0] is None:
        return False
    return identifier.lower() in str(row[0]).lower()
