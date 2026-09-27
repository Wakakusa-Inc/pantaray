"""artifact_patch パーサの安全制限に関するユニットテスト。"""

from __future__ import annotations

import json

import pytest

from pantaray_agents.utils.artifact_patch.parser import (
    ArtifactCompletion,
    ArtifactGenericToolCall,
    ArtifactPatch,
    parse_artifact_document_tool_call,
    parse_artifact_document_tool_payload,
)


def _make_tool_call_with_chunks(n: int) -> str:
    payload = {
        "tool_id": "artifact_patch",
        "args": {
            "chunks": [
                {"lines": [{"op": "context", "text": f"line-{index}"}]}
                for index in range(n)
            ]
        },
    }
    return json.dumps(payload)


def test_parse_artifact_document_tool_call_preserves_large_chunks() -> None:
    text = _make_tool_call_with_chunks(1001)
    patch = parse_artifact_document_tool_call(text)
    assert isinstance(patch, ArtifactPatch)
    assert isinstance(patch.args["chunks"], list)
    assert len(patch.args["chunks"]) == 1001


def test_parse_artifact_document_tool_call_preserves_structured_patch_args() -> None:
    text = _make_tool_call_with_chunks(1)
    patch = parse_artifact_document_tool_call(text)
    assert isinstance(patch, ArtifactPatch)
    assert patch.args == {"chunks": [{"lines": [{"op": "context", "text": "line-0"}]}]}


def test_parse_artifact_document_tool_call_accepts_completed() -> None:
    payload = {"tool_id": "completed", "reason": "done", "args": {}}
    result = parse_artifact_document_tool_call(json.dumps(payload))
    assert isinstance(result, ArtifactCompletion)
    assert result.reason == "done"


def test_parse_artifact_document_tool_call_rejects_completed_args() -> None:
    payload = {"tool_id": "completed", "args": {"reason": "done"}}
    with pytest.raises(RuntimeError, match="completed args must be empty"):
        _ = parse_artifact_document_tool_call(json.dumps(payload))


def test_parse_artifact_document_tool_call_preserves_schema_invalid_args() -> None:
    payload = {"tool_id": "artifact_patch", "args": {"no_change": True}}
    result = parse_artifact_document_tool_call(json.dumps(payload))
    assert isinstance(result, ArtifactPatch)
    assert result.args == {"no_change": True}


def test_parse_artifact_document_tool_payload_preserves_empty_patch_args() -> None:
    result = parse_artifact_document_tool_payload(
        {"tool_id": "artifact_patch", "args": {}}
    )
    assert isinstance(result, ArtifactPatch)
    assert result.args == {}


def test_parse_artifact_document_tool_payload_preserves_args_reason() -> None:
    payload = {"tool_id": "artifact_patch", "args": {"reason": "   "}}
    result = parse_artifact_document_tool_payload(payload)
    assert isinstance(result, ArtifactPatch)
    assert result.args == {"reason": "   "}


def test_parse_artifact_document_tool_payload_accepts_generic_tool_envelope() -> None:
    result = parse_artifact_document_tool_payload(
        {"tool_id": "echo", "args": {"message": "hello"}}
    )

    assert isinstance(result, ArtifactGenericToolCall)
    assert result.tool_id == "echo"
    assert result.reason is None
    assert result.args == {"message": "hello"}
