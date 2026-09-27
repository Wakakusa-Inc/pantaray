from __future__ import annotations

import sqlite3

from .schema_probes import table_columns, table_exists
from .sql_script import execute_sql_script

LEGACY_AGENT_INSIGHTS_COLUMNS = frozenset(
    {
        "insight_id",
        "user_id",
        "suggestion_id",
        "action_id",
        "insight_update_id",
        "status",
        "short_term_insight_data",
        "facts",
        "insight_profile_brief",
        "thinking",
        "error",
        "prompt_text",
        "response_text",
        "prompt_name",
        "prompt_version",
        "long_term_insight_storage_path",
        "long_term_insight_sha256",
        "created_at",
        "updated_at",
    }
)

RUN_STEP_TABLES = (
    "agent_insight_update_run_steps",
    "agent_fact_structuring_run_steps",
)


def apply_legacy_memory_schema_restore_migration(
    connection: sqlite3.Connection,
) -> None:
    _retire_incompatible_agent_insights(connection)
    execute_sql_script(connection, LEGACY_MEMORY_SCHEMA_SQL)
    for table_name in RUN_STEP_TABLES:
        _add_column_if_missing(
            connection,
            table_name=table_name,
            column_definition="thinking TEXT",
        )
    connection.execute(
        "INSERT INTO memory_search_agent_insights_fts(memory_search_agent_insights_fts) VALUES('rebuild')"
    )


def _retire_incompatible_agent_insights(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_insights"):
        return
    columns = table_columns(connection, table_name="agent_insights")
    if LEGACY_AGENT_INSIGHTS_COLUMNS <= columns:
        return
    execute_sql_script(
        connection,
        """
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ai;
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ad;
        DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_au;
        DROP TABLE IF EXISTS memory_search_agent_insights_fts;
        DROP INDEX IF EXISTS idx_agent_insights_user_created;
        """,
    )
    retired_table_name = _retired_agent_insights_table_name(connection)
    connection.execute(f'ALTER TABLE agent_insights RENAME TO "{retired_table_name}"')


def _retired_agent_insights_table_name(connection: sqlite3.Connection) -> str:
    base_name = "agent_insights_v2_retired"
    if not table_exists(connection, table_name=base_name):
        return base_name
    suffix = 2
    while table_exists(connection, table_name=f"{base_name}_{suffix}"):
        suffix += 1
    return f"{base_name}_{suffix}"


def _add_column_if_missing(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_definition: str,
) -> None:
    column_name = column_definition.split()[0]
    if column_name in table_columns(connection, table_name=table_name):
        return
    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_definition}")


LEGACY_MEMORY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_insights (
    insight_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    suggestion_id TEXT NOT NULL,
    action_id TEXT,
    insight_update_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    short_term_insight_data TEXT NOT NULL,
    facts TEXT NOT NULL,
    insight_profile_brief TEXT,
    thinking TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    long_term_insight_storage_path TEXT,
    long_term_insight_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id),
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id, suggestion_id) REFERENCES agent_suggestions(user_id, suggestion_id),
    FOREIGN KEY (user_id, action_id) REFERENCES agent_actions(user_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_insights_user_created
ON agent_insights(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_facts (
    fact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    facts_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    llm_output TEXT CHECK (llm_output IS NULL OR json_valid(llm_output)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_insight_ids TEXT CHECK (source_insight_ids IS NULL OR json_valid(source_insight_ids)),
    structured_fact_storage_path TEXT,
    structured_fact_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_facts_user_created
ON agent_facts(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_insight_update_runs (
    insight_update_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    insight_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    base_storage_path TEXT,
    base_sha256 TEXT,
    final_storage_path TEXT,
    final_sha256 TEXT,
    insight_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_runs_user_updated
ON agent_insight_update_runs(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_runs_insight_updated
ON agent_insight_update_runs(insight_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_insight_update_run_steps (
    insight_update_id TEXT NOT NULL,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    step_kind TEXT NOT NULL CHECK (step_kind IN ('llm', 'tool')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_name TEXT,
    tool_input_json TEXT CHECK (tool_input_json IS NULL OR json_valid(tool_input_json)),
    tool_output_json TEXT CHECK (tool_output_json IS NULL OR json_valid(tool_output_json)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    thinking TEXT,
    PRIMARY KEY (insight_update_id, step_number),
    FOREIGN KEY (insight_update_id) REFERENCES agent_insight_update_runs(insight_update_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_insight_update_run_steps_run
ON agent_insight_update_run_steps(insight_update_id, step_number);

CREATE TABLE IF NOT EXISTS agent_fact_structuring_runs (
    fact_run_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    fact_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    base_storage_path TEXT,
    base_sha256 TEXT,
    final_storage_path TEXT,
    final_sha256 TEXT,
    facts_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_insight_ids TEXT CHECK (source_insight_ids IS NULL OR json_valid(source_insight_ids)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_runs_user_updated
ON agent_fact_structuring_runs(user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_runs_fact_updated
ON agent_fact_structuring_runs(fact_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS agent_fact_structuring_run_steps (
    fact_run_id TEXT NOT NULL,
    step_number INTEGER NOT NULL CHECK (step_number > 0),
    step_kind TEXT NOT NULL CHECK (step_kind IN ('llm', 'tool')),
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error')),
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_name TEXT,
    tool_input_json TEXT CHECK (tool_input_json IS NULL OR json_valid(tool_input_json)),
    tool_output_json TEXT CHECK (tool_output_json IS NULL OR json_valid(tool_output_json)),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    thinking TEXT,
    PRIMARY KEY (fact_run_id, step_number),
    FOREIGN KEY (fact_run_id) REFERENCES agent_fact_structuring_runs(fact_run_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_fact_structuring_run_steps_run
ON agent_fact_structuring_run_steps(fact_run_id, step_number);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_agent_insights_fts USING fts5(
    short_term_insight_data,
    content='agent_insights',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_ai
AFTER INSERT ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_ad
AFTER DELETE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_au
AFTER UPDATE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;
"""
