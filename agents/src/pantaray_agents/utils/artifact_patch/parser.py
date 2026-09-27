"""artifact document tool 呼び出し JSON のパーサ。

LLM から返ってくる JSON は信頼できないため、厳密に検証し、
失敗時は例外として呼び出し側（ループ制御）へ返す。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pantaray_agents.schema.agent.base import JSONValue

MAX_PATCH_LINES = 1000


@dataclass(frozen=True)
class ArtifactPatch:
    """artifact_patch の解釈結果。"""

    tool_id: str
    reason: str | None
    args: dict[str, JSONValue]


@dataclass(frozen=True)
class ArtifactCompletion:
    """completed の解釈結果。"""

    reason: str | None


@dataclass(frozen=True)
class ArtifactGenericToolCall:
    """artifact ReAct tool call parsed from LLM output."""

    tool_id: str
    reason: str | None
    args: dict[str, JSONValue]


@dataclass(frozen=True)
class ArtifactToolEnvelope:
    """LLM output tool envelope."""

    tool_id: str
    reason: str | None
    args: dict[str, JSONValue]


type ArtifactDocumentToolOutput = (
    ArtifactPatch | ArtifactCompletion | ArtifactGenericToolCall
)


def parse_artifact_document_tool_payload(payload: object) -> ArtifactDocumentToolOutput:
    """artifact document tool の payload object を解釈する。"""

    tool_call = _parse_tool_envelope(payload)

    if tool_call.tool_id == "completed":
        return _parse_completed_tool_call(tool_call)

    if tool_call.tool_id == "artifact_patch":
        return _parse_patch_tool_call(tool_call)

    return ArtifactGenericToolCall(
        tool_id=tool_call.tool_id,
        reason=tool_call.reason,
        args=tool_call.args,
    )


def _parse_tool_envelope(payload: object) -> ArtifactToolEnvelope:
    if not isinstance(payload, dict):
        raise RuntimeError("tool payload must be an object")
    tool_id = payload.get("tool_id")
    if not isinstance(tool_id, str) or not tool_id.strip():
        raise RuntimeError("tool_id must be a non-empty string")
    reason = payload.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise RuntimeError("reason must be a string when provided")
    normalized_reason = reason.strip() if isinstance(reason, str) else None
    args = payload.get("args")
    if not isinstance(args, dict):
        raise RuntimeError("args must be an object")
    return ArtifactToolEnvelope(
        tool_id=tool_id.strip(),
        reason=normalized_reason or None,
        args=_parse_json_object(args),
    )


def _parse_completed_tool_call(tool_call: ArtifactToolEnvelope) -> ArtifactCompletion:
    if tool_call.args:
        raise RuntimeError("completed args must be empty")
    return ArtifactCompletion(reason=tool_call.reason)


def _parse_patch_tool_call(tool_call: ArtifactToolEnvelope) -> ArtifactPatch:
    return ArtifactPatch(
        tool_id=tool_call.tool_id,
        reason=tool_call.reason,
        args=tool_call.args,
    )


def _parse_json_object(value: dict[object, object]) -> dict[str, JSONValue]:
    parsed: dict[str, JSONValue] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise RuntimeError("args keys must be strings")
        parsed[key] = _parse_json_value(item)
    return parsed


def _parse_json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_parse_json_value(item) for item in value]
    if isinstance(value, dict):
        return _parse_json_object(value)
    raise RuntimeError("args must contain JSON-compatible values")


def parse_artifact_document_tool_output(
    output: str | object,
) -> ArtifactDocumentToolOutput:
    """LLM出力（文字列または構造化payload）を artifact document tool として解釈する。"""

    if isinstance(output, str):
        return parse_artifact_document_tool_call(output)
    return parse_artifact_document_tool_payload(output)


def parse_artifact_document_tool_call(text: str) -> ArtifactDocumentToolOutput:
    """LLM出力（JSON文字列）を artifact document tool としてパースする。

    Args:
        text: LLM が返した文字列（JSON object を期待）。

    Returns:
        ArtifactDocumentToolOutput: パース結果。

    Raises:
        RuntimeError: JSON形式不正、想定スキーマ不一致、必須フィールド欠落など。
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:  # pragma: no cover - 分岐は呼び出し側で検証
        raise RuntimeError("output must be a single JSON object") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("output JSON must be an object")

    return parse_artifact_document_tool_payload(payload)
