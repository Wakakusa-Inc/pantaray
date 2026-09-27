from __future__ import annotations

import sqlite3
from pathlib import Path

from ...storage.migrations import MigrationError
from ..models import StoredToolDefinition, ToolDefinitionSeed
from .common import (
    _configure_connection,
    _deserialize_json_string_map,
    _deserialize_string_list,
    _serialize_json,
)


def seed_tool_definitions(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    definitions: tuple[ToolDefinitionSeed, ...],
) -> None:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            for definition in definitions:
                connection.execute(
                    """
                    INSERT INTO tool_definitions(
                        tool_id,
                        tool_name,
                        tool_description,
                        category,
                        risk_level,
                        intent_class,
                        required_capabilities_json,
                        input_schema_json,
                        output_schema_json,
                        rate_limit_json,
                        timeout_ms,
                        llm_guide_json,
                        is_enabled,
                        version,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    ON CONFLICT(tool_id) DO UPDATE SET
                        tool_name = excluded.tool_name,
                        tool_description = excluded.tool_description,
                        category = excluded.category,
                        risk_level = excluded.risk_level,
                        intent_class = excluded.intent_class,
                        required_capabilities_json = excluded.required_capabilities_json,
                        input_schema_json = excluded.input_schema_json,
                        output_schema_json = excluded.output_schema_json,
                        rate_limit_json = excluded.rate_limit_json,
                        timeout_ms = excluded.timeout_ms,
                        llm_guide_json = excluded.llm_guide_json,
                        is_enabled = excluded.is_enabled,
                        version = excluded.version,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    """,
                    (
                        definition.tool_id,
                        definition.tool_name,
                        definition.tool_description,
                        definition.category,
                        definition.risk_level,
                        definition.intent_class,
                        _serialize_json(list(definition.required_capabilities)),
                        _serialize_json(definition.input_schema_json),
                        (
                            _serialize_json(definition.output_schema_json)
                            if definition.output_schema_json is not None
                            else None
                        ),
                        (
                            _serialize_json(definition.rate_limit_json)
                            if definition.rate_limit_json is not None
                            else None
                        ),
                        definition.default_timeout_ms,
                        _serialize_json(definition.llm_guide_json),
                        1 if definition.is_enabled else 0,
                        definition.version,
                    ),
                )


def load_tool_definition(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    tool_id: str,
) -> StoredToolDefinition:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            """
            SELECT
                tool_id,
                intent_class,
                required_capabilities_json,
                timeout_ms,
                llm_guide_json,
                output_schema_json
            FROM tool_definitions
            WHERE tool_id = ?
            """,
            (tool_id,),
        ).fetchone()
    if row is None:
        raise MigrationError(f"tool definition not found: {tool_id}")
    required_capabilities_json = row["required_capabilities_json"]
    if required_capabilities_json is None:
        raise MigrationError(
            f"required_capabilities_json must not be NULL for tool definition: {tool_id}"
        )
    return StoredToolDefinition(
        tool_id=str(row["tool_id"]),
        intent_class=str(row["intent_class"]),
        required_capabilities=_deserialize_string_list(
            required_capabilities_json,
            field_name="required_capabilities_json",
        ),
        default_timeout_ms=(
            int(row["timeout_ms"]) if row["timeout_ms"] is not None else None
        ),
        llm_guide_json=_deserialize_json_string_map(
            row["llm_guide_json"], field_name="llm_guide_json"
        ),
        output_schema_json=(
            _deserialize_json_string_map(
                row["output_schema_json"], field_name="output_schema_json"
            )
            if row["output_schema_json"] is not None
            else None
        ),
    )
