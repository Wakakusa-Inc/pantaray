from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_llm.contracts.request import LlmProxyRequest, LlmRequest


def _content() -> dict[str, object]:
    return {
        "messages": [
            {"role": "user", "content": [{"type": "input_text", "text": "prompt"}]}
        ],
        "prompt_cache_key": "action-1",
    }


def test_cloud_envelope_projects_content_and_only_the_local_job_trace() -> None:
    content = _content()
    content["response_format"] = {
        "type": "json_schema",
        "json_schema": {"type": "object", "properties": {}},
    }
    envelope = {
        **content,
        "inference_profile": "action.executing",
        "metadata": {
            "request_kind": "llm_inference",
            "user_id": "cloud-user",
            "session_version": "cloud-session",
            "local_job_id": "job-1",
        },
    }
    request = LlmProxyRequest.model_validate(envelope)
    assert request.model_dump(mode="json", exclude_none=True) == envelope
    assert request.to_request().model_dump(mode="json", exclude_none=True) == {
        **content,
        "purpose": "action.executing",
        "trace": {"local_job_id": "job-1"},
    }


@pytest.mark.parametrize("field", ["user_id", "session_version"])
def test_common_trace_rejects_cloud_identity(field: str) -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        LlmRequest.model_validate(
            {
                **_content(),
                "purpose": "test",
                "trace": {"local_job_id": "job", field: "cloud-value"},
            }
        )


@pytest.mark.parametrize("field", ["user_id", "session_version"])
def test_cloud_envelope_still_requires_cloud_identity(field: str) -> None:
    metadata = {
        "request_kind": "llm_inference",
        "user_id": "cloud-user",
        "session_version": "cloud-session",
        "local_job_id": "job",
    }
    del metadata[field]
    with pytest.raises(ValidationError, match=field):
        LlmProxyRequest.model_validate(
            {**_content(), "inference_profile": "test", "metadata": metadata}
        )


@pytest.mark.parametrize("mode", ["tool_use", "action_turn"])
def test_common_request_rejects_conflicting_output_contracts(mode: str) -> None:
    tool_use: dict[str, object] = {
        "mode": mode,
        "tools": [
            {
                "name": "completed",
                "description": "Finish",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "max_parallel_tool_calls": 1,
    }
    if mode == "tool_use":
        tool_use.pop("mode")
        tool_use["continuation_mode"] = "disabled"
    with pytest.raises(ValidationError, match="mutually exclusive"):
        LlmRequest.model_validate(
            {
                **_content(),
                "purpose": "test",
                "trace": {"local_job_id": "job"},
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"type": "object"},
                },
                "tool_use": tool_use,
            }
        )
