from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.llm_proxy.model_error import (
    build_invalid_tool_response_error,
)
from pantaray_agents.proxy_errors import build_llm_proxy_agent_error
from pantaray_llm.errors import PROXY_UPSTREAM_INTERNAL_ERROR, LlmProxyExecutionError
from pantaray_llm.errors.error_contract import (
    __all__ as error_contract_exports,
)
from pantaray_llm.errors.error_contract import (
    build_proxy_agent_error,
    coerce_proxy_error_code,
    is_retryable_proxy_error_code,
)


def test_upstream_internal_error_is_exported_and_has_specific_message() -> None:
    assert "PROXY_UPSTREAM_INTERNAL_ERROR" in error_contract_exports

    payload = build_proxy_agent_error(
        surface_id="llm",
        error_code=PROXY_UPSTREAM_INTERNAL_ERROR,
        upstream_provider="openai",
        upstream_status_code=500,
        upstream_code="500",
        profile_id="fact_structuring.patch_loop",
    )

    assert payload["error_details"]["retryable"] is True
    assert payload["error_details"]["suggested_action"] == "retry_later"
    assert payload["error_message"] == (
        "The external provider returned an internal server error. Retry later "
        "rather than changing the request."
    )


def test_tool_call_contract_violation_is_non_retryable_and_preserves_reason() -> None:
    payload = build_proxy_agent_error(
        surface_id="llm",
        error_code="PROXY_LLM_TOOL_CALL_INVALID",
        tool_call_violation_reason="multiple_calls",
        actual_tool_call_count=2,
    )

    assert is_retryable_proxy_error_code("PROXY_LLM_TOOL_CALL_INVALID") is False
    assert payload["error_details"]["retryable"] is False
    assert payload["error_details"]["suggested_action"] == "adjust_input"
    assert payload["error_details"]["tool_call_violation_reason"] == "multiple_calls"
    assert payload["error_details"]["actual_tool_call_count"] == 2


@pytest.mark.parametrize(
    ("code", "action"),
    [
        ("PROXY_CONNECTION_NOT_CONFIGURED", "configure_connection"),
        ("PROXY_CONTINUATION_PROVIDER_MISMATCH", "abort"),
        ("PROXY_MODEL_CAPABILITY_UNSUPPORTED", "configure_connection"),
    ],
)
def test_connection_codes_keep_their_non_retryable_contract(code, action) -> None:
    error = build_proxy_agent_error(
        surface_id="llm", error_code=coerce_proxy_error_code(code)
    )
    assert error["error_code"] == code
    assert error["error_details"]["retryable"] is False
    assert error["error_details"]["recovery"] == "stop"
    assert error["error_details"]["suggested_action"] == action
    assert error["error_message"] != "The proxy request failed."


def test_invalid_tool_response_stop_survives_agent_projection() -> None:
    failure = build_invalid_tool_response_error(
        message="Missing required native response.",
        request_json={"inference_profile": "memory_update"},
        response_payload={"meta": {"upstream_provider": "anthropic"}},
    )
    error = build_llm_proxy_agent_error(exception=failure, error_code_prefix="MEMORY")
    assert error.error_details is not None
    assert error.error_details["recovery"] == "stop"
    assert error.error_details["suggested_action"] == "abort"
    assert error.error_details["retryable"] is False
    assert error.error_details["upstream_provider"] == "anthropic"


def test_source_stop_is_not_reclassified_as_retryable_by_agent_projection() -> None:
    # source_transport rejects revoked access as REQUEST_FAILED with retryable=False.
    failure = LlmProxyExecutionError(
        error_code="PROXY_REQUEST_FAILED",
        error_message="Source access was revoked.",
        retryable=False,
    )
    error = build_llm_proxy_agent_error(exception=failure, error_code_prefix="ACTION")
    assert error.error_details is not None
    assert error.error_details["retryable"] is False
    assert error.error_details["recovery"] == "stop"
    assert error.error_details["suggested_action"] == "abort"
