"""Multipart LLM proxy adapter using the shared raw-source send boundary."""

import json
from collections.abc import Mapping

import httpx2

from pantaray_agents.local_runtime.context.source_transport import (
    SourceTransportError,
    source_http_request,
)
from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    is_mapping,
    read_optional_string,
)
from pantaray_llm.errors import PROXY_REQUEST_FAILED, LlmProxyExecutionError

LLM_PROXY_TIMEOUT_SECONDS = 180.0


async def post_request(
    *,
    proxy_url: str,
    request_json: Mapping[str, object],
    desktop_access_token: str,
    multipart_files: list[tuple[str, tuple[str, bytes, str]]],
) -> httpx2.Response:
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if is_mapping(metadata) else None
    try:
        async with source_http_request(
            read_optional_string(metadata_mapping, "user_id")
        ) as options:
            async with httpx2.AsyncClient(
                timeout=httpx2.Timeout(LLM_PROXY_TIMEOUT_SECONDS),
                http1=True,
                http2=False,
                follow_redirects=False,
                trust_env=True,
            ) as client:
                response = await client.post(
                    proxy_url,
                    data={"request": json.dumps(request_json, ensure_ascii=False)},
                    files=multipart_files,
                    headers={"Authorization": f"Bearer {desktop_access_token}"},
                    **options,
                )
        return response
    except SourceTransportError as exc:
        raise LlmProxyExecutionError(
            error_code=PROXY_REQUEST_FAILED,
            error_message=f"LLM {exc}",
            retryable=False,
        ) from exc
    except httpx2.HTTPError as exc:
        raise LlmProxyExecutionError(
            error_code=PROXY_REQUEST_FAILED,
            error_message=f"LLM proxy transport error: {exc}",
            retryable=True,
            local_job_id=read_optional_string(metadata_mapping, "local_job_id"),
        ) from exc
