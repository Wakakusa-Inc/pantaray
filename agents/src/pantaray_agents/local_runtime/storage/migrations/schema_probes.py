from __future__ import annotations

import sqlite3


def manifest_runtime_authority_is_current(connection: sqlite3.Connection) -> bool:
    execution_session_columns = table_columns(
        connection,
        table_name="execution_sessions",
    )
    tool_invocation_columns = table_columns(
        connection,
        table_name="tool_invocations",
    )
    approval_session_columns = table_columns(
        connection,
        table_name="approval_sessions",
    )
    return (
        "workspace_id" not in execution_session_columns
        and "manifest_id" in tool_invocation_columns
        and "command_summary" not in tool_invocation_columns
        and "command_summary_json" in tool_invocation_columns
        and "manifest_id" in approval_session_columns
        and not table_exists(connection, table_name="artifact_manifest")
        and not table_exists(connection, table_name="workspaces")
        and not table_exists(connection, table_name="allowed_roots")
        and approval_scope_schema_is_global_only(connection)
    )


def agent_memory_run_logs_schema_is_current(connection: sqlite3.Connection) -> bool:
    return (
        table_has_columns(
            connection,
            table_name="agent_long_term_insight_state",
            required_columns={
                "user_id",
                "source_insight_id",
                "source_run_id",
                "storage_path",
                "sha256",
                "insight_profile_brief",
            },
        )
        and table_has_no_foreign_key_to(
            connection,
            table_name="agent_long_term_insight_state",
            foreign_table_name="agent_insights",
        )
        and table_has_columns(
            connection,
            table_name="agent_insight_update_runs",
            required_columns={
                "insight_update_id",
                "user_id",
                "insight_id",
                "status",
                "base_storage_path",
                "base_sha256",
                "final_storage_path",
                "final_sha256",
            },
        )
        and table_has_columns(
            connection,
            table_name="agent_insight_update_run_steps",
            required_columns={
                "insight_update_id",
                "step_number",
                "step_kind",
                "status",
                "llm_prompt_text",
                "llm_response_text",
                "tool_name",
                "tool_input_json",
                "tool_output_json",
                "error_code",
                "error_message",
            },
        )
        and table_columns_absent(
            connection,
            table_name="agent_insight_update_run_steps",
            forbidden_columns={"prompt_text", "response_text", "patch_text"},
        )
        and table_has_columns(
            connection,
            table_name="agent_fact_structuring_runs",
            required_columns={
                "fact_run_id",
                "user_id",
                "fact_id",
                "status",
                "base_storage_path",
                "base_sha256",
                "final_storage_path",
                "final_sha256",
            },
        )
        and table_has_columns(
            connection,
            table_name="agent_fact_structuring_run_steps",
            required_columns={
                "fact_run_id",
                "step_number",
                "step_kind",
                "status",
                "llm_prompt_text",
                "llm_response_text",
                "tool_name",
                "tool_input_json",
                "tool_output_json",
                "error_code",
                "error_message",
            },
        )
        and table_columns_absent(
            connection,
            table_name="agent_fact_structuring_run_steps",
            forbidden_columns={"prompt_text", "response_text", "patch_text"},
        )
    )


def table_has_no_foreign_key_to(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    foreign_table_name: str,
) -> bool:
    return all(
        str(row[2]) != foreign_table_name
        for row in connection.execute(f"PRAGMA foreign_key_list('{table_name}')")
    )


def table_has_columns(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    required_columns: set[str],
) -> bool:
    if not table_exists(connection, table_name=table_name):
        return False
    return required_columns <= table_columns(connection, table_name=table_name)


def table_columns_absent(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    forbidden_columns: set[str],
) -> bool:
    if not table_exists(connection, table_name=table_name):
        return False
    return forbidden_columns.isdisjoint(
        table_columns(connection, table_name=table_name)
    )


def table_exists(connection: sqlite3.Connection, *, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def approval_scope_schema_is_global_only(connection: sqlite3.Connection) -> bool:
    approval_preferences_sql = table_sql(
        connection,
        table_name="approval_preferences",
    )
    capability_grants_sql = table_sql(
        connection,
        table_name="capability_grants",
    )
    return (
        "scope_type = 'global'" in approval_preferences_sql
        and "REFERENCES workspaces" not in approval_preferences_sql
        and "scope_type = 'global'" in capability_grants_sql
    )


def table_sql(connection: sqlite3.Connection, *, table_name: str) -> str:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if row is None:
        return ""
    return str(row[0])


def table_columns(
    connection: sqlite3.Connection,
    *,
    table_name: str,
) -> frozenset[str]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return frozenset(str(row[1]) for row in rows)
