from __future__ import annotations

import json
import sqlite3
from typing import cast

from pydantic import ValidationError

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.tool_result import FormalToolStepOutput

from .specs import MigrationError

_LEGACY_OUTPUT_KEYS = frozenset({"status", "output"})
_LEGACY_ERROR_KEYS = frozenset({"status", "error"})


def apply_formal_tool_step_output_migration(
    connection: sqlite3.Connection,
) -> None:
    """Canonicalize every persisted legacy tool step into the strict v1 envelope."""

    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT step_id, status, tool_output
        FROM agent_action_steps
        WHERE step_type = 'tool_execution'
          AND tool_output IS NOT NULL
        ORDER BY created_at, step_id
        """
    ).fetchall()
    for row in rows:
        step_id = str(row["step_id"])
        envelope = _canonicalize_tool_step(
            connection=connection,
            step_id=step_id,
            persisted_status=str(row["status"]),
            raw_json=str(row["tool_output"]),
        )
        connection.execute(
            "UPDATE agent_action_steps SET tool_output = ? WHERE step_id = ?",
            (
                json.dumps(
                    envelope.model_dump(mode="json"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ),
                step_id,
            ),
        )


def _canonicalize_tool_step(
    *,
    connection: sqlite3.Connection,
    step_id: str,
    persisted_status: str,
    raw_json: str,
) -> FormalToolStepOutput:
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise MigrationError(
            f"legacy tool step contains invalid JSON: {step_id}"
        ) from exc
    if not isinstance(value, dict):
        raise MigrationError(f"legacy tool step must contain an object: {step_id}")

    if value.get("schema_version") == 1:
        try:
            envelope = FormalToolStepOutput.model_validate(value)
        except ValidationError as exc:
            raise MigrationError(
                f"formal tool step violates the v1 contract: {step_id}"
            ) from exc
        _require_matching_status(
            step_id=step_id,
            persisted_status=persisted_status,
            envelope_status=envelope.status,
        )
        return envelope

    keys = frozenset(value)
    if keys == _LEGACY_OUTPUT_KEYS:
        output = cast(JSONValue, value["output"])
    elif keys == _LEGACY_ERROR_KEYS:
        output = cast(JSONValue, {"error": value["error"]})
    else:
        raise MigrationError(
            f"legacy tool step has an unsupported output shape: {step_id}"
        )
    status = value.get("status")
    _require_matching_status(
        step_id=step_id,
        persisted_status=persisted_status,
        envelope_status=status,
    )

    storage_kind = "inline_json"
    owner_kind = "action_step"
    if status != "processing":
        invocation_storage_kind = _matching_invocation_storage_kind(
            connection=connection,
            step_id=step_id,
            output=output,
        )
        if invocation_storage_kind is not None:
            storage_kind = invocation_storage_kind
            owner_kind = "tool_invocation"
    try:
        return FormalToolStepOutput.model_validate(
            {
                "schema_version": 1,
                "status": status,
                "output": output,
                "output_storage_kind": storage_kind,
                "output_owner_kind": owner_kind,
            }
        )
    except ValidationError as exc:
        raise MigrationError(
            f"legacy tool step cannot be canonicalized: {step_id}"
        ) from exc


def _require_matching_status(
    *,
    step_id: str,
    persisted_status: object,
    envelope_status: object,
) -> None:
    if envelope_status not in {"success", "error", "processing"}:
        raise MigrationError(f"legacy tool step has an invalid status: {step_id}")
    if envelope_status != persisted_status:
        raise MigrationError(
            f"legacy tool step status disagrees with its row: {step_id}"
        )


def _matching_invocation_storage_kind(
    *,
    connection: sqlite3.Connection,
    step_id: str,
    output: JSONValue,
) -> str | None:
    rows = connection.execute(
        """
        SELECT outputs.output_json, outputs.output_storage_kind
        FROM tool_invocations AS invocations
        JOIN tool_outputs AS outputs
          ON outputs.invocation_id = invocations.invocation_id
        WHERE invocations.step_id = ?
        ORDER BY invocations.started_at DESC, invocations.invocation_id DESC
        """,
        (step_id,),
    ).fetchall()
    for row in rows:
        try:
            invocation_output = json.loads(str(row["output_json"]))
        except json.JSONDecodeError as exc:
            raise MigrationError(
                f"linked tool output contains invalid JSON: {step_id}"
            ) from exc
        if invocation_output != output:
            continue
        storage_kind = row["output_storage_kind"]
        if storage_kind not in {"inline_json", "action_file"}:
            raise MigrationError(
                f"linked tool output has invalid storage provenance: {step_id}"
            )
        return str(storage_kind)
    return None


__all__ = ["apply_formal_tool_step_output_migration"]
