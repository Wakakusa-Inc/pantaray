from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

import httpx2

from pantaray_agents.local_runtime.llm_proxy.content_files import MultipartFile
from pantaray_agents.local_runtime.llm_proxy.direct import execute_direct_llm_request
from pantaray_agents.local_runtime.llm_proxy.model_error import (
    build_invalid_success_response_error,
    parse_model_output_error,
    validate_tool_response_contract,
)
from pantaray_agents.local_runtime.llm_proxy.request_builder import (
    BuiltLlmRequest,
    build_llm_request,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    coerce_non_empty_string as _coerce_non_empty_string,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_error_usage as _extract_error_usage,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_meta as _extract_meta,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_provider_turn as _extract_provider_turn,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_text as _extract_text_from_response,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_thinking as _extract_thinking,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_tool_use as _extract_tool_use,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_usage as _extract_usage,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    is_mapping as _is_mapping,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    parse_response_text as _parse_response_text,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    read_llm_provider as _read_llm_provider,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    read_optional_int as _read_optional_int,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    read_optional_string as _read_optional_string,
)
from pantaray_agents.local_runtime.llm_proxy.transport import post_request
from pantaray_agents.local_runtime.llm_proxy.types import (
    ProxyResponse,
    ProxyStreamChunk,
)
from pantaray_agents.local_runtime.runtime.bootstrap import LLM_PROXY_URL_ENV
from pantaray_agents.local_runtime.runtime.connection_store import (
    llm_connection_can_send,
    read_llm_route,
    request_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import verify_current_owner
from pantaray_agents.local_runtime.runtime.job_route_identity import (
    require_current_route_identity,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    AUTH_CONTEXT_EXPIRED_STATE,
    ActiveDesktopSession,
    load_active_desktop_session,
    read_auth_context_state,
)
from pantaray_agents.utils.trace_context import get_trace_context
from pantaray_agents.utils.url_validation import parse_network_url
from pantaray_llm.contracts.action_turn import LlmActionTurnResponse
from pantaray_llm.contracts.request import LlmRequest
from pantaray_llm.contracts.tool_use import LlmToolUseResponse
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import (
    PROXY_AUTHENTICATION_FAILED,
    PROXY_CONNECTION_NOT_CONFIGURED,
    PROXY_INVALID_UPSTREAM_RESPONSE,
    PROXY_REQUEST_FAILED,
    LlmProvider,
    LlmProxyExecutionError,
    ProxyErrorCode,
    ProxySuggestedAction,
    coerce_proxy_error_code,
    coerce_proxy_suggested_action,
    coerce_tool_call_violation_reason,
    is_retryable_proxy_error_code,
    resolve_proxy_recovery,
)

STREAM_CHUNK_TARGET_CHARS = 96
SESSION_STORE_CALLER_TIMEOUT_MS = 1
SESSION_STORE_UNUSED_DB_PATH = Path("/dev/null")
SUPPORTED_GENERATE_KWARGS = frozenset({"contents", "config"})


def _parse_proxy_error(payload: Mapping[str, object]) -> LlmProxyExecutionError:
    error = payload.get("error")
    if not _is_mapping(error):
        return LlmProxyExecutionError(
            error_code=PROXY_REQUEST_FAILED,
            error_message="LLM proxy request failed",
            retryable=True,
        )
    code = error.get("code")
    message = error.get("message")
    details = error.get("details")
    details_mapping = details if _is_mapping(details) else None
    error_code = coerce_proxy_error_code(code)
    violation_reason = coerce_tool_call_violation_reason(
        details_mapping.get("tool_call_violation_reason")
        if details_mapping is not None
        else None
    )
    error_message = (
        message
        if isinstance(message, str) and message.strip()
        else "LLM proxy request failed"
    )
    return LlmProxyExecutionError(
        error_code=error_code,
        error_message=error_message,
        retryable=is_retryable_proxy_error_code(error_code),
        recovery=resolve_proxy_recovery(
            error_code=error_code, tool_call_violation_reason=violation_reason
        ),
        suggested_action=coerce_proxy_suggested_action(
            details_mapping.get("suggested_action")
            if details_mapping is not None
            else None
        ),
        local_job_id=_read_optional_string(details_mapping, "local_job_id"),
        upstream_provider=_read_llm_provider(details_mapping),
        upstream_request_id=_read_optional_string(
            details_mapping, "upstream_request_id"
        ),
        profile_id=_read_optional_string(details_mapping, "profile_id"),
        upstream_status_code=_read_optional_int(
            details_mapping, "upstream_status_code"
        ),
        upstream_code=_read_optional_string(details_mapping, "upstream_code"),
        usage_metadata=_extract_error_usage(details_mapping),
        tool_call_violation_reason=violation_reason,
        actual_tool_call_count=_read_optional_int(
            details_mapping, "actual_tool_call_count"
        ),
        tool_name=_read_optional_string(details_mapping, "tool_name"),
        response_status=_read_optional_string(details_mapping, "response_status"),
        argument_path=_read_optional_string(details_mapping, "argument_path"),
        schema_keyword=_read_optional_string(details_mapping, "schema_keyword"),
        media_failure_reason=_read_optional_string(details_mapping, "reason"),
    )


def _build_invalid_upstream_response_error(
    *,
    message: str,
    request_json: Mapping[str, object],
    response_status_code: int,
    upstream_code: str,
) -> LlmProxyExecutionError:
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if _is_mapping(metadata) else None
    local_job_id = _read_optional_string(metadata_mapping, "local_job_id")
    profile_id = _read_optional_string(request_json, "inference_profile")
    return LlmProxyExecutionError(
        error_code=PROXY_INVALID_UPSTREAM_RESPONSE,
        error_message=message,
        retryable=is_retryable_proxy_error_code(PROXY_INVALID_UPSTREAM_RESPONSE),
        local_job_id=local_job_id,
        upstream_provider=None,
        profile_id=profile_id,
        upstream_status_code=response_status_code,
        upstream_code=upstream_code,
    )


def _split_stream_text(text: str) -> list[str]:
    if not text:
        return [""]
    words = text.split(" ")
    chunks: list[str] = []
    buffer: list[str] = []
    for word in words:
        candidate = " ".join([*buffer, word]).strip()
        if buffer and len(candidate) > STREAM_CHUNK_TARGET_CHARS:
            chunks.append(" ".join(buffer))
            buffer = [word]
            continue
        buffer.append(word)
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks or [text]


def _cloud_request_json(
    *,
    request: LlmRequest,
    session: ActiveDesktopSession,
) -> dict[str, object]:
    """Wrap the shared request in the cloud proxy's multipart envelope.

    The envelope is assembled here rather than dumped from one model because
    each part needs the serialization its own contract expects: the optional
    envelope fields are absent instead of null, message blocks drop their unset
    descriptor fields, and tool_use keeps its nulls, because a required field
    that holds null -- ``LlmToolResult.output`` for a tool that returned nothing
    -- is rejected at ingress the moment it goes missing.
    """

    payload: dict[str, object] = {
        "inference_profile": request.purpose,
        "messages": [
            message.model_dump(mode="json", exclude_none=True)
            for message in request.messages
        ],
        "metadata": {
            "request_kind": "llm_inference",
            "user_id": session.user_id,
            "local_job_id": request.trace.local_job_id,
            "session_version": session.session_version,
        },
    }
    if request.response_format is not None:
        payload["response_format"] = request.response_format.model_dump(mode="json")
    if request.tool_use is not None:
        payload["tool_use"] = request.tool_use.model_dump(mode="json")
    if request.prompt_cache_key is not None:
        payload["prompt_cache_key"] = request.prompt_cache_key
    return payload


def _uploaded_blobs(multipart_files: list[MultipartFile]) -> dict[str, UploadedBlob]:
    """Key the request's media by ``blob_ref`` for an in-process adapter.

    The cloud proxy's ingress builds the same mapping out of the multipart form
    it received. The filename is a multipart decoration and has no meaning to
    the adapter, which resolves a descriptor by its ``blob_ref``.
    """

    return {
        blob_ref: UploadedBlob(
            field_name=blob_ref, payload=payload, mime_type=mime_type
        )
        for blob_ref, (_filename, payload, mime_type) in multipart_files
    }


def _refused_route_error(
    *,
    error_code: ProxyErrorCode,
    error_message: str,
    suggested_action: ProxySuggestedAction | None,
    local_job_id: str,
    config: object | None,
    upstream_provider: LlmProvider | None = None,
) -> LlmProxyExecutionError:
    """A route that sends nothing, reported the way a sent request would be.

    The caller is an agent that only catches ``LlmProxyExecutionError``, and its
    job and purpose identify the refusal in the same fields an upstream failure
    fills in. The purpose is read straight off the caller's config: the request
    itself is never built, because building it would read the caller's files for
    a request this route has already refused.
    """

    return LlmProxyExecutionError(
        error_code=error_code,
        error_message=error_message,
        retryable=False,
        suggested_action=suggested_action,
        local_job_id=local_job_id,
        upstream_provider=upstream_provider,
        profile_id=_read_inference_profile(config),
    )


def _connection_not_configured_error(
    *, local_job_id: str, config: object | None
) -> LlmProxyExecutionError:
    return _refused_route_error(
        error_code=PROXY_CONNECTION_NOT_CONFIGURED,
        error_message="No LLM connection is configured.",
        # The shared contract derives `configure_connection` for this code.
        suggested_action=None,
        local_job_id=local_job_id,
        config=config,
    )


def _read_inference_profile(config: object | None) -> str | None:
    if config is None:
        return None
    value = (
        config.get("inference_profile")
        if _is_mapping(config)
        else getattr(config, "inference_profile", None)
    )
    return value if isinstance(value, str) and value.strip() else None


def _read_llm_proxy_url() -> str | None:
    raw = os.getenv(LLM_PROXY_URL_ENV)
    if raw is None or not raw.strip():
        return None
    parsed_url = parse_network_url(
        raw,
        env_name=LLM_PROXY_URL_ENV,
        allow_path=True,
    ).url
    return str(parsed_url)


class _ModelsClient:
    def __init__(self, parent: LocalLlmProxyClient) -> None:
        self._parent = parent

    async def generate_content(self, **kwargs: object) -> ProxyResponse:
        return await self._parent.generate_content(**kwargs)

    def generate_content_stream(
        self, **kwargs: object
    ) -> AsyncIterator[ProxyStreamChunk]:
        return self._parent.generate_content_stream(**kwargs)


class _AioClient:
    def __init__(self, parent: LocalLlmProxyClient) -> None:
        self.models = _ModelsClient(parent)


class LocalLlmProxyClient:
    def __init__(self, *, proxy_url: str | None) -> None:
        self._proxy_url = proxy_url
        self.aio = _AioClient(self)

    @staticmethod
    def _load_active_session(user_id: str) -> ActiveDesktopSession:
        return load_active_desktop_session(
            db_path=SESSION_STORE_UNUSED_DB_PATH,
            busy_timeout_ms=SESSION_STORE_CALLER_TIMEOUT_MS,
            user_id=user_id,
        )

    @staticmethod
    def _require_trace_identity() -> tuple[str, str]:
        trace_context = get_trace_context()
        if trace_context is None:
            raise RuntimeError("TraceContext is required for LLM proxy calls")
        user_id = _coerce_non_empty_string(trace_context.user_id, field_name="user_id")
        local_job_id = _coerce_non_empty_string(
            trace_context.local_job_id,
            field_name="local_job_id",
        )
        return user_id, local_job_id

    async def _post_request(
        self,
        *,
        request_json: Mapping[str, object],
        desktop_access_token: str,
        response_schema: object | None,
        multipart_files: list[MultipartFile],
    ) -> ProxyResponse:
        if self._proxy_url is None:
            # Electron leaves the URL out while Pantaray account login is disabled,
            # so a cloud session should not exist; refuse instead of guessing.
            raise RuntimeError(
                f"{LLM_PROXY_URL_ENV} is not set: the Pantaray Cloud route is unavailable."
            )
        response: httpx2.Response = await post_request(
            proxy_url=self._proxy_url,
            request_json=request_json,
            desktop_access_token=desktop_access_token,
            multipart_files=multipart_files,
        )

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise _build_invalid_upstream_response_error(
                message="LLM proxy returned invalid JSON",
                request_json=request_json,
                response_status_code=response.status_code,
                upstream_code="invalid_json",
            ) from exc
        if not _is_mapping(payload):
            raise _build_invalid_upstream_response_error(
                message="LLM proxy returned non-object JSON",
                request_json=request_json,
                response_status_code=response.status_code,
                upstream_code="non_object_json",
            )
        if not response.is_success:
            raise _parse_proxy_error(payload)
        finish_reason = payload.get("finish_reason")
        if finish_reason == "error":
            raise _parse_proxy_error(payload)
        usage: dict[str, int] | None = None
        try:
            usage = _extract_usage(payload)
            model_output_error = parse_model_output_error(
                request_json=request_json,
                response_payload=payload,
            )
            if model_output_error is not None:
                raise model_output_error
            text = _extract_text_from_response(payload)
            tool_use = _extract_tool_use(payload)
            validate_tool_response_contract(
                request_json=request_json,
                response_payload=payload,
                tool_use=tool_use,
            )
            parsed = _parse_response_text(text=text, response_schema=response_schema)
            meta = _extract_meta(payload)
            thinking = _extract_thinking(payload)
            provider_turn = _extract_provider_turn(payload)
        except LlmProxyExecutionError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise build_invalid_success_response_error(
                message="LLM proxy returned an invalid success response.",
                request_json=request_json,
                response_payload=payload,
                usage_metadata=usage,
            ) from exc
        legacy_tool_use = tool_use if isinstance(tool_use, LlmToolUseResponse) else None
        return ProxyResponse(
            text=text,
            usage_metadata=usage,
            parsed=parsed,
            meta=meta,
            thinking=thinking,
            tool_calls=tuple(legacy_tool_use.calls)
            if legacy_tool_use is not None
            else (),
            dropped_tool_call_names=(
                tuple(legacy_tool_use.dropped_call_names)
                if legacy_tool_use is not None
                else ()
            ),
            tool_continuation=(
                legacy_tool_use.continuation if legacy_tool_use is not None else None
            ),
            action_turn=tool_use
            if isinstance(tool_use, LlmActionTurnResponse)
            else None,
            provider_turn=provider_turn,
        )

    def _build_request(
        self, kwargs: Mapping[str, object], *, user_id: str, local_job_id: str
    ) -> BuiltLlmRequest:
        return build_llm_request(
            contents=kwargs.get("contents"),
            config=kwargs.get("config"),
            user_id=user_id,
            local_job_id=local_job_id,
        )

    async def generate_content(self, **kwargs: object) -> ProxyResponse:
        """Send one inference on the route this request resolves to (design 6.4).

        The route is decided once, here, and a failure on one route is never
        retried on another. Whichever route resolves, it authorizes the request
        -- a live cloud session, or the current owner for a direct connection --
        before the builder reads any of the caller's file inputs.

        A job that started on a different route never reaches the decision: it
        stops here, before the route is read and before any file is opened, so
        the work of one owner is never inferred on another's account (design
        6.2, 7.3).
        """

        unexpected_keys = sorted(set(kwargs) - SUPPORTED_GENERATE_KWARGS)
        if unexpected_keys:
            unexpected_fields = ", ".join(unexpected_keys)
            raise RuntimeError(
                f"Unsupported local LLM proxy call fields: {unexpected_fields}"
            )
        user_id, local_job_id = self._require_trace_identity()
        await require_current_route_identity()
        config = kwargs.get("config")
        match read_llm_route():
            # ``read_llm_route`` folds an expired cloud session into ``cloud``
            # so a lapsed session asks for re-authentication instead of falling
            # back to a stored connection. Nothing is sent upstream.
            case "cloud" if read_auth_context_state() == AUTH_CONTEXT_EXPIRED_STATE:
                raise _refused_route_error(
                    error_code=PROXY_AUTHENTICATION_FAILED,
                    error_message="The Pantaray session expired. Sign in again.",
                    suggested_action="reauthenticate",
                    local_job_id=local_job_id,
                    config=config,
                )
            case "cloud":
                session = self._load_active_session(user_id)
                built = self._build_request(
                    kwargs, user_id=user_id, local_job_id=local_job_id
                )
                return await self._post_request(
                    request_json=_cloud_request_json(
                        request=built.request, session=session
                    ),
                    desktop_access_token=session.desktop_access_token,
                    response_schema=built.response_schema,
                    multipart_files=built.multipart_files,
                )
            case "direct":
                # No cloud session authorizes a direct request, so the owner of
                # the work does: the trace identity must still be the one whose
                # connection this is.
                verify_current_owner(user_id)
                connection = request_llm_connection()
                if connection is None:
                    # Cleared between the route read and this one.
                    raise _connection_not_configured_error(
                        local_job_id=local_job_id, config=config
                    )
                if not llm_connection_can_send(connection):
                    # Only a ChatGPT token can fail this: main renews it five
                    # minutes ahead (design 6.6), so a lapsed one means the
                    # renewal has not landed. The same predicate keeps the
                    # worker from claiming background jobs meanwhile.
                    raise _refused_route_error(
                        error_code=PROXY_AUTHENTICATION_FAILED,
                        error_message="The ChatGPT connection expired. Sign in again.",
                        suggested_action="reauthenticate",
                        local_job_id=local_job_id,
                        config=config,
                        upstream_provider="openai_codex",
                    )
                built = self._build_request(
                    kwargs, user_id=user_id, local_job_id=local_job_id
                )
                return await execute_direct_llm_request(
                    connection=connection,
                    request=built.request,
                    uploaded_blobs=_uploaded_blobs(built.multipart_files),
                    user_id=user_id,
                    response_schema=built.response_schema,
                )
            case _:
                raise _connection_not_configured_error(
                    local_job_id=local_job_id, config=config
                )

    async def generate_content_stream(
        self, **kwargs: object
    ) -> AsyncIterator[ProxyStreamChunk]:
        response = await self.generate_content(**kwargs)
        chunks = _split_stream_text(response.text)
        for index, chunk_text in enumerate(chunks):
            is_last_chunk = index == len(chunks) - 1
            yield ProxyStreamChunk(
                text=chunk_text,
                usage_metadata=response.usage_metadata if is_last_chunk else None,
                thinking=response.thinking if is_last_chunk else None,
            )


def build_local_llm_proxy_client() -> LocalLlmProxyClient:
    return LocalLlmProxyClient(proxy_url=_read_llm_proxy_url())


__all__ = ["LocalLlmProxyClient", "build_local_llm_proxy_client"]
