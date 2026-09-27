"""Add durable Action USER acceptance and root-process ownership."""

from __future__ import annotations

import sqlite3

from .action_process_envelopes import load_action_process_envelopes
from .action_user_process_lineage import plan_action_user_process_lineage
from .action_user_step_inventory import load_action_user_step_inventory
from .specs import MigrationError

_SOURCE_STEP_COLUMNS = tuple(
    """step_id action_id user_id parent_step_id step_number local_step_number
    short_step_id step_type step_name status goal_handle requirement_handle
    parallel_group_id parallel_depth parallel_index retry_count started_at completed_at
    execution_time_ms prompt_tokens completion_tokens user_request_text user_message_id
    user_message_json thinking llm_prompt_text llm_response_text tool_args tool_output
    runtime_state_checkpoint runtime_state_checkpoint_version error created_at""".split()
)


def apply_action_user_process_ownership_migration(
    connection: sqlite3.Connection,
) -> None:
    _require_source_schema(connection)
    process_envelopes = load_action_process_envelopes(connection)
    user_steps = load_action_user_step_inventory(connection)
    lineage = plan_action_user_process_lineage(
        user_steps=user_steps,
        process_envelopes=process_envelopes,
    )

    connection.execute(
        """
        CREATE UNIQUE INDEX uq_processes_user_action_process
        ON processes(user_id, action_id, process_id)
        """
    )
    _rebuild_action_steps(connection)
    cursor = connection.executemany(
        """
        UPDATE agent_action_steps
        SET accepted_sequence = ?, adopted_process_id = ?
        WHERE step_id = ? AND step_type = 'user_request'
        """,
        (
            (row.accepted_sequence, row.adopted_process_id, row.step_id)
            for row in lineage
        ),
    )
    if cursor.rowcount != len(lineage):
        raise MigrationError(
            "Action USER ownership backfill changed an invalid row count"
        )
    create_action_user_process_indexes(connection)
    _create_active_action_indexes(connection)
    create_action_user_process_triggers(connection)
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            "v86 foreign-key validation failed: "
            f"violations={len(violations)} first={tuple(violations[0])}"
        )


def _require_source_schema(connection: sqlite3.Connection) -> None:
    columns = tuple(
        str(row[1])
        for row in connection.execute("PRAGMA table_info(agent_action_steps)")
    )
    if columns != _SOURCE_STEP_COLUMNS:
        raise MigrationError("Action USER ownership source schema is incompatible")


def _rebuild_action_steps(connection: sqlite3.Connection) -> None:
    (source_count,) = connection.execute(
        "SELECT COUNT(*) FROM agent_action_steps"
    ).fetchone()
    connection.execute("DROP TABLE IF EXISTS agent_action_steps_v0086")
    connection.execute(
        """
        CREATE TABLE agent_action_steps_v0086 (
            step_id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            parent_step_id TEXT,
            step_number INTEGER CHECK (step_number IS NULL OR step_number >= 1),
            local_step_number INTEGER,
            short_step_id TEXT,
            step_type TEXT NOT NULL CHECK (
                step_type IN ('user_request', 'llm_output', 'tool_execution')
            ),
            step_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'processing', 'success', 'error', 'timeout')
            ),
            goal_handle TEXT,
            requirement_handle TEXT,
            parallel_group_id TEXT,
            parallel_depth INTEGER CHECK (parallel_depth IS NULL OR parallel_depth >= 0),
            parallel_index INTEGER CHECK (parallel_index IS NULL OR parallel_index >= 0),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            started_at TEXT,
            completed_at TEXT,
            execution_time_ms INTEGER CHECK (execution_time_ms IS NULL OR execution_time_ms >= 0),
            prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
            completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
            user_request_text TEXT,
            user_message_id TEXT,
            user_message_json TEXT CHECK (
                user_message_json IS NULL OR json_valid(user_message_json)
            ),
            thinking TEXT,
            llm_prompt_text TEXT,
            llm_response_text TEXT,
            tool_args TEXT CHECK (tool_args IS NULL OR json_valid(tool_args)),
            tool_output TEXT CHECK (tool_output IS NULL OR json_valid(tool_output)),
            runtime_state_checkpoint TEXT CHECK (
                runtime_state_checkpoint IS NULL OR json_valid(runtime_state_checkpoint)
            ),
            runtime_state_checkpoint_version INTEGER CHECK (
                runtime_state_checkpoint_version IS NULL
                OR runtime_state_checkpoint_version >= 1
            ),
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            created_at TEXT NOT NULL,
            accepted_sequence INTEGER,
            adoption_canceled_at TEXT,
            expected_process_id TEXT,
            adopted_process_id TEXT,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (parent_step_id)
                REFERENCES agent_action_steps_v0086(step_id) ON DELETE SET NULL,
            FOREIGN KEY (user_id, action_id, expected_process_id)
                REFERENCES processes(user_id, action_id, process_id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id, action_id, adopted_process_id)
                REFERENCES processes(user_id, action_id, process_id) ON DELETE RESTRICT,
            CHECK (local_step_number IS NULL OR local_step_number > 0),
            CHECK (
                (short_step_id IS NULL AND local_step_number IS NULL)
                OR (short_step_id IS NOT NULL AND local_step_number IS NOT NULL)
            ),
            CHECK (short_step_id IS NULL OR LENGTH(short_step_id) <= 128),
            CHECK (step_type = 'user_request' OR step_number IS NOT NULL),
            CHECK (
                step_type <> 'user_request'
                OR (
                    goal_handle = 'S'
                    AND (
                        (step_number IS NULL AND local_step_number IS NULL AND short_step_id IS NULL)
                        OR (
                            step_number IS NOT NULL
                            AND local_step_number IS NOT NULL
                            AND short_step_id = 'S-' || local_step_number || '-USER'
                        )
                    )
                )
            ),
            CHECK (
                (
                    step_type = 'user_request'
                    AND user_request_text IS NOT NULL
                    AND LENGTH(TRIM(user_request_text)) > 0
                    AND thinking IS NULL
                    AND llm_prompt_text IS NULL
                    AND llm_response_text IS NULL
                    AND tool_args IS NULL
                    AND tool_output IS NULL
                )
                OR (step_type IN ('llm_output', 'tool_execution') AND user_request_text IS NULL)
            ),
            CHECK (
                (user_message_id IS NULL AND user_message_json IS NULL)
                OR (
                    step_type = 'user_request'
                    AND user_message_id IS NOT NULL
                    AND LENGTH(TRIM(user_message_id)) > 0
                    AND user_message_json IS NOT NULL
                )
            ),
            CHECK (
                (runtime_state_checkpoint IS NULL AND runtime_state_checkpoint_version IS NULL)
                OR (
                    runtime_state_checkpoint IS NOT NULL
                    AND runtime_state_checkpoint_version IS NOT NULL
                )
            ),
            CHECK (
                accepted_sequence IS NULL OR (
                    step_type = 'user_request' AND accepted_sequence > 0
                    AND typeof(accepted_sequence) = 'integer'
                )
            ),
            CHECK (
                step_type = 'user_request'
                OR (
                    adoption_canceled_at IS NULL
                    AND expected_process_id IS NULL
                    AND adopted_process_id IS NULL
                )
            ),
            CHECK (
                step_type <> 'user_request'
                OR accepted_sequence IS NOT NULL
                OR (
                    step_number IS NOT NULL
                    AND local_step_number IS NOT NULL
                    AND short_step_id IS NOT NULL
                    AND adoption_canceled_at IS NULL
                    AND expected_process_id IS NULL
                    AND adopted_process_id IS NULL
                )
            ),
            CHECK (
                adoption_canceled_at IS NULL
                OR (
                    step_number IS NULL
                    AND local_step_number IS NULL
                    AND short_step_id IS NULL
                    AND adopted_process_id IS NULL
                )
            ),
            CHECK (
                adopted_process_id IS NULL
                OR (
                    accepted_sequence IS NOT NULL
                    AND step_number IS NOT NULL
                    AND local_step_number IS NOT NULL
                    AND short_step_id IS NOT NULL
                    AND adoption_canceled_at IS NULL
                )
            ),
            CHECK (expected_process_id IS NULL OR accepted_sequence IS NOT NULL)
        )
        """
    )
    columns = ", ".join(_SOURCE_STEP_COLUMNS)
    connection.execute(
        f"INSERT INTO agent_action_steps_v0086({columns}) "
        f"SELECT {columns} FROM agent_action_steps ORDER BY step_id"
    )
    count_query = "SELECT COUNT(*) FROM agent_action_steps_v0086"
    (replacement_count,) = connection.execute(count_query).fetchone()
    if replacement_count != source_count:
        raise MigrationError("Action USER ownership rebuild changed the row count")
    connection.execute("DROP TABLE agent_action_steps")
    connection.execute(
        "ALTER TABLE agent_action_steps_v0086 RENAME TO agent_action_steps"
    )


def create_action_user_process_indexes(connection: sqlite3.Connection) -> None:
    for statement in (
        "CREATE INDEX idx_agent_action_steps_action_created ON agent_action_steps(action_id, created_at ASC)",
        """CREATE INDEX idx_agent_action_steps_short_step_id_resolution
           ON agent_action_steps(action_id, short_step_id, completed_at DESC,
                                 created_at DESC, step_id DESC)""",
        "CREATE INDEX idx_agent_action_steps_goal_handle ON agent_action_steps(goal_handle)",
        "CREATE INDEX idx_agent_action_steps_requirement_handle ON agent_action_steps(requirement_handle)",
        """CREATE UNIQUE INDEX uq_agent_action_steps_user_message
           ON agent_action_steps(user_id, user_message_id)
           WHERE user_message_id IS NOT NULL""",
        """CREATE UNIQUE INDEX uq_agent_action_steps_action_accepted_sequence
           ON agent_action_steps(action_id, accepted_sequence)
           WHERE accepted_sequence IS NOT NULL""",
        """CREATE INDEX idx_agent_action_steps_expected_process
           ON agent_action_steps(user_id, action_id, expected_process_id)
           WHERE expected_process_id IS NOT NULL""",
        """CREATE INDEX idx_agent_action_steps_adopted_process
           ON agent_action_steps(user_id, action_id, adopted_process_id)
           WHERE adopted_process_id IS NOT NULL""",
    ):
        connection.execute(statement)


def _create_active_action_indexes(connection: sqlite3.Connection) -> None:
    for statement in (
        """CREATE UNIQUE INDEX uq_processes_active_action
           ON processes(action_id)
           WHERE kind = 'action' AND action_id IS NOT NULL
             AND status IN ('enqueued', 'running', 'paused')""",
        """CREATE UNIQUE INDEX uq_jobs_active_action
           ON jobs(logical_key)
           WHERE job_type = 'execute_action' AND logical_key IS NOT NULL
             AND status IN ('queued', 'running', 'paused', 'retryable_error')""",
    ):
        connection.execute(statement)


def create_action_user_process_triggers(connection: sqlite3.Connection) -> None:
    for statement in (
        """
        CREATE TRIGGER trg_action_user_process_identity_insert
        BEFORE INSERT ON agent_action_steps
        WHEN (
            NEW.expected_process_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM processes
                WHERE user_id = NEW.user_id AND action_id = NEW.action_id
                  AND process_id = NEW.expected_process_id AND kind = 'action'
            )
        ) OR (
            NEW.adopted_process_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM processes
                WHERE user_id = NEW.user_id AND action_id = NEW.action_id
                  AND process_id = NEW.adopted_process_id AND kind = 'action'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'Action USER process must reference an Action process');
        END
        """,
        """
        CREATE TRIGGER trg_action_user_process_identity_update
        BEFORE UPDATE OF user_id, action_id, accepted_sequence, expected_process_id, adopted_process_id
        ON agent_action_steps
        WHEN (
            OLD.accepted_sequence IS NOT NULL AND NEW.accepted_sequence IS NOT OLD.accepted_sequence
        ) OR (
            OLD.expected_process_id IS NOT NULL
            AND NEW.expected_process_id IS NOT OLD.expected_process_id
        ) OR (
            OLD.adopted_process_id IS NOT NULL
            AND NEW.adopted_process_id IS NOT OLD.adopted_process_id
        ) OR (
            NEW.expected_process_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM processes
                WHERE user_id = NEW.user_id AND action_id = NEW.action_id
                  AND process_id = NEW.expected_process_id AND kind = 'action'
            )
        ) OR (
            NEW.adopted_process_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM processes
                WHERE user_id = NEW.user_id AND action_id = NEW.action_id
                  AND process_id = NEW.adopted_process_id AND kind = 'action'
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'Action USER process identity is invalid or immutable');
        END
        """,
    ):
        connection.execute(statement)
    _create_referenced_process_kind_trigger(connection)


def _create_referenced_process_kind_trigger(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        """
        CREATE TRIGGER trg_action_user_referenced_process_kind
        BEFORE UPDATE OF kind ON processes
        WHEN NEW.kind <> 'action' AND EXISTS (
            SELECT 1 FROM agent_action_steps
            WHERE user_id = OLD.user_id AND action_id = OLD.action_id
              AND (expected_process_id = OLD.process_id OR adopted_process_id = OLD.process_id)
        )
        BEGIN
            SELECT RAISE(ABORT, 'Referenced Action USER process kind is immutable');
        END
        """
    )


__all__ = [
    "apply_action_user_process_ownership_migration",
    "create_action_user_process_indexes",
    "create_action_user_process_triggers",
]
