"""Remove the duplicate Suggestion-to-Action link during the Action cutover."""

from __future__ import annotations

import sqlite3

from .specs import MigrationError

AGENT_SUGGESTION_COLUMNS = tuple(
    """suggestion_id user_id status answer thinking error prompt_text response_text
    prompt_name prompt_version has_suggestion request_images_count used_images_count
    interaction_contract user_reaction accepted_at rejected_at action_status
    action_failure_code action_failure_stage action_failure_message_public
    action_request_payload action_process_id action_execution_id action_command_id
    action_started_at process_event_sequence created_at updated_at suggestion_summary
    target_context_json""".split()
)

_TARGET_COLUMNS = tuple(
    column for column in AGENT_SUGGESTION_COLUMNS if column != "action_execution_id"
)
_REPLACED_TRIGGER_NAMES = (
    "reject_message_only_action_lane_insert",
    "reject_message_only_action_lane_update",
)


def require_canonical_suggestion_links(connection: sqlite3.Connection) -> None:
    """Require every legacy Action provenance ID to resolve to its Suggestion."""

    row = connection.execute(
        """
        SELECT actions.action_id, COALESCE(actions.suggestion_id, 'missing')
        FROM agent_actions AS actions
        LEFT JOIN agent_suggestions AS suggestions
          ON suggestions.suggestion_id = actions.suggestion_id
         AND suggestions.user_id = actions.user_id
        WHERE suggestions.suggestion_id IS NULL
        ORDER BY actions.action_id
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        raise MigrationError(
            "v82 preflight blocked: category=action_suggestion_link "
            f"id={row[0]} status={row[1]}"
        )


def rebuild_agent_suggestions(connection: sqlite3.Connection) -> None:
    """Preserve Suggestion data while dropping its reverse Action pointer."""

    preserved_objects = _load_preserved_schema_objects(connection)
    connection.execute("DROP TABLE IF EXISTS agent_suggestions_v0082")
    connection.execute(
        """
        CREATE TABLE agent_suggestions_v0082 (
            suggestion_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('processing', 'success', 'error', 'timeout', 'canceled')
            ),
            answer TEXT,
            thinking TEXT,
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            prompt_text TEXT,
            response_text TEXT,
            prompt_name TEXT,
            prompt_version TEXT,
            has_suggestion INTEGER CHECK (
                has_suggestion IS NULL OR has_suggestion IN (0, 1)
            ),
            request_images_count INTEGER NOT NULL DEFAULT 0 CHECK (
                request_images_count >= 0
            ),
            used_images_count INTEGER NOT NULL DEFAULT 0 CHECK (
                used_images_count >= 0
            ),
            interaction_contract TEXT CHECK (
                interaction_contract IS NULL
                OR interaction_contract IN ('action_offer', 'message_only')
            ),
            user_reaction TEXT,
            accepted_at TEXT,
            rejected_at TEXT,
            action_status TEXT CHECK (
                action_status IS NULL
                OR action_status IN ('idle', 'processing', 'success', 'error', 'canceled')
            ),
            action_failure_code TEXT,
            action_failure_stage TEXT,
            action_failure_message_public TEXT,
            action_request_payload TEXT CHECK (
                action_request_payload IS NULL OR json_valid(action_request_payload)
            ),
            action_process_id TEXT,
            action_command_id TEXT,
            action_started_at TEXT,
            process_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (
                process_event_sequence >= 0
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            suggestion_summary TEXT,
            target_context_json TEXT CHECK (
                target_context_json IS NULL OR json_valid(target_context_json)
            ),
            UNIQUE (user_id, suggestion_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        )
        """
    )
    columns = ", ".join(_TARGET_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO agent_suggestions_v0082(rowid, {columns})
        SELECT rowid, {columns}
        FROM agent_suggestions
        ORDER BY suggestion_id
        """
    )
    connection.execute("DROP TABLE agent_suggestions")
    connection.execute(
        "ALTER TABLE agent_suggestions_v0082 RENAME TO agent_suggestions"
    )
    for statement in preserved_objects:
        connection.execute(statement)
    _create_message_only_action_lane_triggers(connection)


def _load_preserved_schema_objects(connection: sqlite3.Connection) -> tuple[str, ...]:
    placeholders = ", ".join("?" for _ in _REPLACED_TRIGGER_NAMES)
    rows = connection.execute(
        f"""
        SELECT sql
        FROM sqlite_master
        WHERE tbl_name = 'agent_suggestions'
          AND type IN ('index', 'trigger')
          AND sql IS NOT NULL
          AND name NOT IN ({placeholders})
        ORDER BY type, name
        """,
        _REPLACED_TRIGGER_NAMES,
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _create_message_only_action_lane_triggers(
    connection: sqlite3.Connection,
) -> None:
    action_lane_present = """
        NEW.user_reaction IS NOT NULL
        OR NEW.accepted_at IS NOT NULL
        OR NEW.rejected_at IS NOT NULL
        OR NEW.action_status IS NOT NULL
        OR NEW.action_failure_code IS NOT NULL
        OR NEW.action_failure_stage IS NOT NULL
        OR NEW.action_failure_message_public IS NOT NULL
        OR NEW.action_request_payload IS NOT NULL
        OR NEW.action_process_id IS NOT NULL
        OR NEW.action_command_id IS NOT NULL
        OR NEW.action_started_at IS NOT NULL
    """
    for operation in ("INSERT", "UPDATE"):
        connection.execute(
            f"""
            CREATE TRIGGER reject_message_only_action_lane_{operation.lower()}
            BEFORE {operation} ON agent_suggestions
            WHEN NEW.interaction_contract = 'message_only'
             AND ({action_lane_present})
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'message_only suggestions must not carry action lane state'
                );
            END
            """
        )


__all__ = [
    "AGENT_SUGGESTION_COLUMNS",
    "rebuild_agent_suggestions",
    "require_canonical_suggestion_links",
]
