"""MockActionAgentRepository で共有する型・正規化 helper。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Protocol, TypedDict, cast

from pantaray_agents.action_status import ActionRuntimeStatus
from pantaray_agents.schema.agent.action import ActionHeaderRecord, ActionStepRecord

from ..schema.agent.base import StatusType
from ..schema.repositories.repository import DBRow, DBRows, JSONValue

type CoverageRowValue = JSONValue | datetime | StatusType
type CoverageRow = dict[str, CoverageRowValue]
type MockDBRow = DBRow
type MockDBRows = DBRows
type SourceOptionsPayload = dict[str, JSONValue]


class MemorySearchResultRow(TypedDict, total=False):
    source: str
    record_id: JSONValue
    created_at: JSONValue
    updated_at: JSONValue
    content: str
    memory_key: str
    available_ref_ids: list[str]
    storage_path: str
    block_id: str
    heading_path: str
    summary_type: JSONValue
    period_start: JSONValue
    period_end: JSONValue
    score: JSONValue


class ActionResponseLike(Protocol):
    def model_dump(self, *, exclude_none: bool = False) -> MockDBRow: ...


def _coerce_iso_datetime(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    raise ValueError("created_at/updated_at is required")


def _coerce_runtime_status(value: object) -> ActionRuntimeStatus:
    if isinstance(value, StatusType):
        raw = value.value
    else:
        if value is None:
            raise ValueError("status is required")
        raw = str(value).strip().lower()
    if raw not in {"idle", "processing", "success", "error", "canceled"}:
        raise ValueError(f"unsupported action status: {raw!r}")
    return cast(ActionRuntimeStatus, raw)


def validate_mock_action_row(payload: Mapping[str, object]) -> MockDBRow:
    created_at = _coerce_iso_datetime(payload.get("created_at"))
    updated_at = _coerce_iso_datetime(payload.get("updated_at"))
    prompt_name = payload.get("prompt_name")
    prompt_version = payload.get("prompt_version")
    if not isinstance(prompt_name, str) or not prompt_name.strip():
        raise ValueError("prompt_name is required")
    if not isinstance(prompt_version, str) or not prompt_version.strip():
        raise ValueError("prompt_version is required")
    final_output = payload.get("final_output")
    if not isinstance(final_output, str):
        raise ValueError("final_output is required")
    record = ActionHeaderRecord(
        action_id=str(payload.get("action_id") or ""),
        user_id=str(payload.get("user_id") or ""),
        suggestion_id=str(payload.get("suggestion_id") or ""),
        prompt_name=prompt_name.strip(),
        prompt_version=prompt_version.strip(),
        status=_coerce_runtime_status(payload.get("status")),
        final_output=final_output,
        final_prompt_text=(
            str(payload["final_prompt_text"])
            if isinstance(payload.get("final_prompt_text"), str)
            else None
        ),
        error=payload.get("error") if isinstance(payload.get("error"), dict) else None,
        created_at=created_at,
        updated_at=updated_at,
        steps_budget=payload.get("steps_budget")
        if isinstance(payload.get("steps_budget"), int)
        else None,
        llm_steps_budget=payload.get("llm_steps_budget")
        if isinstance(payload.get("llm_steps_budget"), int)
        else None,
        tool_steps_budget=payload.get("tool_steps_budget")
        if isinstance(payload.get("tool_steps_budget"), int)
        else None,
        token_budget=payload.get("token_budget")
        if isinstance(payload.get("token_budget"), int)
        else None,
        total_steps=payload.get("total_steps")
        if isinstance(payload.get("total_steps"), int)
        else None,
        total_llm_steps=payload.get("total_llm_steps")
        if isinstance(payload.get("total_llm_steps"), int)
        else None,
        total_tool_steps=payload.get("total_tool_steps")
        if isinstance(payload.get("total_tool_steps"), int)
        else None,
        total_prompt_tokens=payload.get("total_prompt_tokens")
        if isinstance(payload.get("total_prompt_tokens"), int)
        else None,
        total_completion_tokens=payload.get("total_completion_tokens")
        if isinstance(payload.get("total_completion_tokens"), int)
        else None,
    )
    return record.model_dump(exclude_none=False)


def validate_mock_action_step_row(payload: Mapping[str, object]) -> MockDBRow:
    return ActionStepRecord.model_validate(payload).model_dump(exclude_none=False)
