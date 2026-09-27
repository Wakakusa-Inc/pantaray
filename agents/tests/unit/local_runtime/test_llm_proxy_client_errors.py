from __future__ import annotations

import json

import pytest
from tests.unit.local_runtime.test_llm_proxy_client import (
    cloud_session as cloud_session,
)
from tests.unit.local_runtime.test_llm_proxy_client import (
    cloud_session_db as cloud_session_db,
)

from pantaray_agents.local_runtime.llm_proxy.client import LocalLlmProxyClient
from pantaray_agents.proxy_errors import build_llm_proxy_agent_error
from pantaray_agents.utils.llm_types import types
from pantaray_agents.utils.trace_context import TraceContextManager
from pantaray_llm.errors import LlmProxyExecutionError


class _FakeHttpResponse:
    def __init__(self, *, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload
        self.is_success = 200 <= status_code < 300

    def json(self) -> object:
        return self._payload


class _InvalidJsonHttpResponse:
    def __init__(self, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300

    def json(self) -> dict[str, object]:
        raise json.JSONDecodeError("Expecting value", "not-json", 0)


class _NonObjectJsonHttpResponse:
    def __init__(self, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300

    def json(self) -> list[object]:
        return ["not", "an", "object"]


class _RecordingAsyncClient:
    last_request: dict[str, object] | None = None

    def __init__(self, **_kwargs: object) -> None:
        self._response = _FakeHttpResponse(
            status_code=200,
            payload={
                "id": "resp_1",
                "model": "gpt-6-luna",
                "output": [
                    {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"answer": "ok"}),
                            }
                        ],
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "cached_prompt_tokens": 2,
                    "cache_write_prompt_tokens": 1,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
                "meta": {
                    "local_job_id": "req-1",
                    "upstream_provider": "openai",
                    "profile_id": "dummy.default",
                    "outcome": "complete",
                    "upstream_request_id": "resp_1",
                },
            },
        )

    async def __aenter__(self) -> _RecordingAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    async def post(
        self,
        url: str,
        *,
        data: dict[str, object],
        files: list[tuple[str, tuple[str, bytes, str]]],
        headers: dict[str, str],
    ) -> _FakeHttpResponse:
        type(self).last_request = {
            "url": url,
            "data": data,
            "files": files,
            "headers": headers,
        }
        return self._response


def _build_client() -> LocalLlmProxyClient:
    return LocalLlmProxyClient(proxy_url="https://llm.example.test/v1/responses")


@pytest.mark.asyncio
async def test_generate_content_raises_structured_proxy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=429,
                payload={
                    "error": {
                        "code": "PROXY_UPSTREAM_RATE_LIMITED",
                        "message": "The model provider is rate-limited.",
                        "details": {
                            "local_job_id": "req-3",
                            "upstream_provider": "openai",
                            "profile_id": "dummy.default",
                            "upstream_request_id": "openai-req-1",
                            "upstream_status_code": 429,
                            "upstream_code": "429",
                        },
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _ErrorAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-3"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_UPSTREAM_RATE_LIMITED"
    assert exc.retryable is True
    assert exc.local_job_id == "req-3"
    assert exc.upstream_provider == "openai"
    assert exc.profile_id == "dummy.default"
    assert exc.upstream_request_id == "openai-req-1"
    assert exc.upstream_status_code == 429
    assert exc.upstream_code == "429"


@pytest.mark.asyncio
async def test_generate_content_treats_auth_service_503_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _AuthUnavailableAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=503,
                payload={
                    "detail": {
                        "error_code": "HTTP_EXCEPTION_SERVER_ERROR",
                        "request_id": "request-auth-unavailable",
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _AuthUnavailableAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-auth-unavailable"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    assert exc_info.value.error_code == "PROXY_REQUEST_FAILED"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_generate_content_raises_non_retryable_wallet_proxy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=402,
                payload={
                    "error": {
                        "code": "PROXY_INSUFFICIENT_BALANCE",
                        "message": "Wallet balance is insufficient; inference was not started.",
                        "details": {
                            "local_job_id": "req-wallet",
                            "profile_id": "dummy.default",
                            "reason": "insufficient_balance",
                            "current_balance_microusd": 0,
                        },
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _ErrorAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-wallet"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_INSUFFICIENT_BALANCE"
    assert exc.retryable is False
    assert exc.local_job_id == "req-wallet"
    assert exc.profile_id == "dummy.default"


@pytest.mark.asyncio
async def test_generate_content_preserves_non_retryable_tool_call_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ToolCallErrorAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=200,
                payload={
                    "id": "openai-response-1",
                    "model": "gpt-6-luna",
                    "output": [],
                    "tool_use": None,
                    "finish_reason": "STOP",
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                    "meta": {
                        "local_job_id": "req-tool-contract",
                        "upstream_provider": "openai",
                        "profile_id": "dummy.default",
                        "outcome": "model_output_rejected",
                        "upstream_request_id": "openai-response-1",
                        "resolved_model": "gpt-6-luna-2026-09-22",
                    },
                    "model_error": {
                        "code": "PROXY_LLM_TOOL_CALL_INVALID",
                        "message": (
                            "The model provider returned 2 tool calls; exactly one is required."
                        ),
                        "recovery": "repair_next_turn",
                        "violation_reason": "multiple_calls",
                        "actual_tool_call_count": 2,
                    },
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _ToolCallErrorAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-tool-contract"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    error = exc_info.value
    assert error.error_code == "PROXY_LLM_TOOL_CALL_INVALID"
    assert error.retryable is False
    assert error.recovery == "repair_next_turn"
    assert error.tool_call_violation_reason == "multiple_calls"
    assert error.actual_tool_call_count == 2
    assert error.upstream_request_id == "openai-response-1"
    assert error.usage_metadata == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_generate_content_preserves_usage_for_invalid_model_error_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InvalidModelErrorAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=200,
                payload={
                    "id": "openai-response-invalid-model-error",
                    "model": "gpt-6-luna",
                    "output": [],
                    "usage": {
                        "prompt_tokens": 12,
                        "cached_prompt_tokens": 2,
                        "cache_write_prompt_tokens": 1,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                    "meta": {
                        "local_job_id": "req-invalid-model-error",
                        "upstream_provider": "openai",
                        "profile_id": "dummy.default",
                        "outcome": "model_output_rejected",
                        "upstream_request_id": ("openai-response-invalid-model-error"),
                    },
                    "model_error": {"code": "unexpected_error_code"},
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _InvalidModelErrorAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(
        user_id="user-1",
        local_job_id="req-invalid-model-error",
    ):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    error = exc_info.value
    assert error.error_code == "PROXY_INVALID_UPSTREAM_RESPONSE"
    assert error.retryable is True
    assert error.upstream_code == "invalid_model_error"
    assert error.usage_metadata == {
        "prompt_tokens": 12,
        "cached_prompt_tokens": 2,
        "cache_write_prompt_tokens": 1,
        "completion_tokens": 3,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_generate_content_raises_proxy_error_for_invalid_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _InvalidJsonAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _InvalidJsonHttpResponse(status_code=502)

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _InvalidJsonAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-invalid-json"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_INVALID_UPSTREAM_RESPONSE"
    assert exc.retryable is True
    assert exc.local_job_id == "req-invalid-json"
    assert exc.profile_id == "dummy.default"
    assert exc.upstream_provider is None
    assert exc.upstream_status_code == 502
    assert exc.upstream_code == "invalid_json"


@pytest.mark.asyncio
async def test_generate_content_parses_retryable_upstream_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ErrorAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=500,
                payload={
                    "error": {
                        "code": "PROXY_UPSTREAM_INTERNAL_ERROR",
                        "message": "The model provider returned an internal server error.",
                        "details": {
                            "local_job_id": "req-openai-500",
                            "upstream_provider": "openai",
                            "profile_id": "dummy.default",
                            "upstream_status_code": 500,
                            "upstream_code": "500",
                            "prompt_tokens": 120,
                            "cached_prompt_tokens": 20,
                            "cache_write_prompt_tokens": 30,
                            "completion_tokens": 12,
                            "total_tokens": 132,
                        },
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _ErrorAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-openai-500"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_UPSTREAM_INTERNAL_ERROR"
    assert exc.retryable is True
    assert exc.local_job_id == "req-openai-500"
    assert exc.upstream_provider == "openai"
    assert exc.profile_id == "dummy.default"
    assert exc.upstream_status_code == 500
    assert exc.upstream_code == "500"
    assert exc.usage_metadata == {
        "prompt_tokens": 120,
        "cached_prompt_tokens": 20,
        "cache_write_prompt_tokens": 30,
        "completion_tokens": 12,
        "total_tokens": 132,
    }


@pytest.mark.asyncio
async def test_generate_content_raises_proxy_error_for_non_object_json_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _NonObjectJsonAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _NonObjectJsonHttpResponse(status_code=200)

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _NonObjectJsonAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-non-object-json"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_INVALID_UPSTREAM_RESPONSE"
    assert exc.retryable is True
    assert exc.local_job_id == "req-non-object-json"
    assert exc.profile_id == "dummy.default"
    assert exc.upstream_provider is None
    assert exc.upstream_status_code == 200
    assert exc.upstream_code == "non_object_json"


@pytest.mark.asyncio
async def test_generate_content_requires_trace_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _RecordingAsyncClient,
    )
    client = _build_client()

    with pytest.raises(RuntimeError, match="TraceContext"):
        await client.aio.models.generate_content(
            contents=["no trace context"],
            config=types.GenerateContentConfig(
                inference_profile="dummy.default",
                system_instruction="system",
            ),
        )


@pytest.mark.asyncio
async def test_generate_content_requires_local_job_id_before_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _RecordingAsyncClient,
    )
    _RecordingAsyncClient.last_request = None
    client = _build_client()

    with TraceContextManager(user_id="user-1", request_id="legacy-request-id"):
        with pytest.raises(RuntimeError, match="local_job_id"):
            await client.aio.models.generate_content(
                contents=["missing local job"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    assert _RecordingAsyncClient.last_request is None


@pytest.mark.asyncio
async def test_generate_content_rejects_non_openai_meta_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _TavilyMetaAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=200,
                payload={
                    "id": "resp_1",
                    "model": "gpt-6-luna",
                    "output": [
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": "ok"}],
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "cached_prompt_tokens": 2,
                        "cache_write_prompt_tokens": 1,
                        "completion_tokens": 3,
                        "total_tokens": 15,
                    },
                    "meta": {
                        "local_job_id": "req-provider",
                        "upstream_provider": "tavily",
                        "profile_id": "dummy.default",
                        "outcome": "complete",
                    },
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _TavilyMetaAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-provider"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    assert exc_info.value.error_code == "PROXY_INVALID_UPSTREAM_RESPONSE"
    assert exc_info.value.usage_metadata == {
        "prompt_tokens": 12,
        "cached_prompt_tokens": 2,
        "cache_write_prompt_tokens": 1,
        "completion_tokens": 3,
        "total_tokens": 15,
    }


@pytest.mark.asyncio
async def test_generate_content_carries_the_media_failure_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _MediaTooLargeAsyncClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=400,
                payload={
                    "error": {
                        "code": "PROXY_INVALID_INPUT",
                        "message": (
                            "LLM request could not fit the provider request-size limit."
                        ),
                        "details": {
                            "reason": "active_media_too_large",
                            "request_size_bytes": 600_000_000,
                            "max_request_size_bytes": 512_000_000,
                        },
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        _MediaTooLargeAsyncClient,
    )
    client = _build_client()

    with TraceContextManager(user_id="user-1", local_job_id="req-media"):
        with pytest.raises(LlmProxyExecutionError) as exc_info:
            await client.aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(
                    inference_profile="dummy.default",
                    system_instruction="system",
                ),
            )

    exc = exc_info.value
    assert exc.error_code == "PROXY_INVALID_INPUT"
    assert exc.retryable is False
    assert exc.media_failure_reason == "active_media_too_large"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "action", "provider", "expected_action"),
    [
        (
            "PROXY_CONNECTION_NOT_CONFIGURED",
            "configure_connection",
            None,
            "configure_connection",
        ),
        ("PROXY_CONTINUATION_PROVIDER_MISMATCH", "abort", "openai_codex", "abort"),
        (
            "PROXY_MODEL_CAPABILITY_UNSUPPORTED",
            "configure_connection",
            "fireworks",
            "configure_connection",
        ),
        (
            "PROXY_AUTHENTICATION_FAILED",
            "reauthenticate",
            "openai_codex",
            "reauthenticate",
        ),
        (
            "PROXY_AUTHENTICATION_FAILED",
            "configure_connection",
            "anthropic",
            "configure_connection",
        ),
        ("PROXY_AUTHENTICATION_FAILED", None, "openai", "abort"),
        ("PROXY_AUTHENTICATION_FAILED", {"invalid": "action"}, "openai", "abort"),
    ],
)
async def test_connection_failure_reaches_agent_without_retry_or_lost_guidance(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    action: object,
    provider: str | None,
    expected_action: str,
) -> None:
    class ErrorClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=400,
                payload={
                    "error": {
                        "code": code,
                        "message": "Connection needs attention.",
                        "details": {
                            "suggested_action": action,
                            "upstream_provider": provider,
                            "local_job_id": "job-connection",
                        },
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        ErrorClient,
    )
    with TraceContextManager(user_id="user-1", local_job_id="job-connection"):
        with pytest.raises(LlmProxyExecutionError) as caught:
            await _build_client().aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(inference_profile="dummy.default"),
            )

    failure = caught.value
    assert failure.error_code == code
    assert failure.retryable is False
    assert failure.recovery == "stop"
    error = build_llm_proxy_agent_error(exception=failure, error_code_prefix="ACTION")
    details = error.error_details
    assert details is not None
    assert details["proxy_error_code"] == code
    assert details["retryable"] is False
    assert details["recovery"] == "stop"
    assert details["suggested_action"] == expected_action
    assert details.get("upstream_provider") == provider
    assert details["local_job_id"] == "job-connection"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reason", "recovery"),
    [("response_incomplete", "repair_next_turn"), ("response_blocked", "stop")],
)
async def test_http_tool_error_resolves_recovery_before_agent_projection(
    monkeypatch: pytest.MonkeyPatch, reason: str, recovery: str
) -> None:
    class ErrorClient(_RecordingAsyncClient):
        def __init__(self, **_kwargs: object) -> None:
            self._response = _FakeHttpResponse(
                status_code=502,
                payload={
                    "error": {
                        "code": "PROXY_LLM_TOOL_CALL_INVALID",
                        "message": "The model did not return a valid response.",
                        "details": {"tool_call_violation_reason": reason},
                    }
                },
            )

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
        ErrorClient,
    )
    with TraceContextManager(user_id="user-1", local_job_id="job-tool-error"):
        with pytest.raises(LlmProxyExecutionError) as caught:
            await _build_client().aio.models.generate_content(
                contents=["hello"],
                config=types.GenerateContentConfig(inference_profile="dummy.default"),
            )
    # Action and artifact runners consume the exception before any AgentError exists.
    assert caught.value.recovery == recovery
    assert caught.value.retryable is False
    error = build_llm_proxy_agent_error(
        exception=caught.value, error_code_prefix="ACTION"
    )
    assert error.error_details is not None
    assert error.error_details["recovery"] == recovery
    assert error.error_details["retryable"] is False
