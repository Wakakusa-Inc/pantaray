from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import TypeGuard, cast
from urllib.parse import quote

from pantaray_agents.schema.agent.base import JSONValue

from .specs import MigrationError
from .sql_script import execute_sql_statements

LEGACY_INLINE_CHARACTER_LIMIT = 20_000
LEGACY_JSON_MEDIA_TYPE = "application/json"
_LEGACY_JSON_METADATA_KEYS = frozenset(
    {
        "storage",
        "path",
        "media_type",
        "byte_size",
        "character_count",
        "line_count",
    }
)
_LEGACY_JSON_FILENAME = re.compile(r"^output-[0-9a-f]{32}\.json$")


def apply_tool_output_storage_kind_migration(
    connection: sqlite3.Connection,
    *,
    migration_statements: tuple[str, ...],
) -> None:
    """Backfill only artifacts that the legacy host projector could own."""
    execute_sql_statements(connection, migration_statements)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        UPDATE tool_outputs
        SET output_storage_kind = CASE
            WHEN output_json IS NULL THEN NULL
            ELSE 'inline_json'
        END
        """
    )
    _backfill_terminal_artifacts(connection)
    _backfill_approval_preflight_artifacts(connection)


def _backfill_terminal_artifacts(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT
            outputs.output_id,
            outputs.output_json,
            invocations.invocation_id,
            roots.real_path AS tool_results_root
        FROM tool_outputs AS outputs
        JOIN tool_invocations AS invocations
          ON invocations.invocation_id = outputs.invocation_id
        JOIN workspace_manifest_roots AS roots
          ON roots.manifest_id = invocations.manifest_id
         AND roots.root_id = 'root:' || invocations.action_id || ':tool-results'
        WHERE json_type(outputs.output_json) = 'object'
          AND json_extract(outputs.output_json, '$.storage') = 'action_file'
          AND json_extract(outputs.output_json, '$.media_type') = 'application/json'
        """
    )
    action_file_output_ids = [
        str(row["output_id"])
        for row in rows
        if _is_owned_legacy_json_metadata(
            _load_json(str(row["output_json"])),
            tool_results_root=str(row["tool_results_root"]),
            owner_id=str(row["invocation_id"]),
        )
    ]
    connection.executemany(
        """
        UPDATE tool_outputs
        SET output_storage_kind = 'action_file'
        WHERE output_id = ?
        """,
        ((output_id,) for output_id in action_file_output_ids),
    )


def _backfill_approval_preflight_artifacts(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE agent_action_steps
        SET tool_output = json_set(
            tool_output,
            '$.output.command_summary_storage_kind',
            'inline_json'
        )
        WHERE tool_output IS NOT NULL
          AND json_extract(tool_output, '$.status') = 'processing'
          AND json_extract(tool_output, '$.output.kind') = 'approval_required'
        """
    )
    rows = connection.execute(
        """
        SELECT
            steps.step_id,
            steps.tool_output,
            roots.real_path AS tool_results_root
        FROM agent_action_steps AS steps
        JOIN workspace_manifests AS manifests
          ON manifests.user_id = steps.user_id
         AND manifests.action_id = steps.action_id
        JOIN workspace_manifest_roots AS roots
          ON roots.manifest_id = manifests.manifest_id
         AND roots.root_id = 'root:' || steps.action_id || ':tool-results'
        WHERE json_extract(steps.tool_output, '$.status') = 'processing'
          AND json_extract(steps.tool_output, '$.output.kind') = 'approval_required'
          AND json_extract(
                steps.tool_output,
                '$.output.command_summary.storage'
              ) = 'action_file'
          AND json_extract(
                steps.tool_output,
                '$.output.command_summary.media_type'
              ) = 'application/json'
        """
    )
    action_file_step_ids: list[str] = []
    for row in rows:
        tool_output = _load_json(str(row["tool_output"]))
        if not isinstance(tool_output, dict):
            continue
        output = tool_output.get("output")
        if not isinstance(output, dict):
            continue
        owner_id = output.get("tool_request_id")
        command_summary = output.get("command_summary")
        if not isinstance(owner_id, str) or not _is_owned_legacy_json_metadata(
            command_summary,
            tool_results_root=str(row["tool_results_root"]),
            owner_id=owner_id,
        ):
            continue
        action_file_step_ids.append(str(row["step_id"]))
    connection.executemany(
        """
        UPDATE agent_action_steps
        SET tool_output = json_set(
            tool_output,
            '$.output.command_summary_storage_kind',
            'action_file'
        )
        WHERE step_id = ?
        """,
        ((step_id,) for step_id in action_file_step_ids),
    )


def _load_json(raw_json: str) -> JSONValue:
    try:
        return cast(JSONValue, json.loads(raw_json))
    except json.JSONDecodeError as exc:
        raise MigrationError("tool output storage backfill found invalid JSON") from exc


def _is_owned_legacy_json_metadata(
    value: JSONValue,
    *,
    tool_results_root: str,
    owner_id: str,
) -> bool:
    if not isinstance(value, dict) or set(value) != _LEGACY_JSON_METADATA_KEYS:
        return False
    raw_path = value.get("path")
    if (
        value.get("storage") != "action_file"
        or value.get("media_type") != LEGACY_JSON_MEDIA_TYPE
        or not isinstance(raw_path, str)
        or not _is_non_path_identifier(owner_id)
    ):
        return False
    byte_size = value.get("byte_size")
    character_count = value.get("character_count")
    line_count = value.get("line_count")
    if (
        not _is_positive_integer(byte_size)
        or not _is_positive_integer(character_count)
        or not _is_positive_integer(line_count)
        or character_count <= LEGACY_INLINE_CHARACTER_LIMIT
    ):
        return False
    root_path = Path(tool_results_root)
    stored_path = Path(os.path.normpath(raw_path))
    owner_name = quote(owner_id, safe="-_")
    # File existence is not a provenance discriminator. A missing legacy artifact
    # remains an action-file reference so startup recovery can report the loss.
    return (
        root_path.is_absolute()
        and stored_path.is_absolute()
        and stored_path.parent == root_path / owner_name
        and _LEGACY_JSON_FILENAME.fullmatch(stored_path.name) is not None
    )


def _is_positive_integer(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_path_identifier(value: str) -> bool:
    return (
        bool(value)
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\0" not in value
    )


__all__ = ["apply_tool_output_storage_kind_migration"]
