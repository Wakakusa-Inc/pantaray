"""One LLM request resolves one route, and only that route's boundary sees it.

Every test records both send boundaries -- the cloud route's proxy client and
the provider client the direct dispatcher is lent -- so a request that leaves
for the wrong host, or leaves at all where the route refuses, is observable
(acceptance A05 / A06 / A07 / A08 / A19). The state is the store's own, applied
the way the control socket applies it, never patched.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from tests.unit.local_runtime.test_direct_llm_dispatch import (
    CHATGPT_CONNECTION,
    CHATGPT_TOKEN,
    OPENAI_CONNECTION,
    OPENAI_KEY,
    SendBoundary,
    responder,
)
from tests.unit.local_runtime.test_llm_proxy_client import _FakeHttpResponse

from pantaray_agents.local_runtime.llm_proxy import direct
from pantaray_agents.local_runtime.llm_proxy.client import LocalLlmProxyClient
from pantaray_agents.local_runtime.llm_proxy.types import ProxyResponse
from pantaray_agents.local_runtime.runtime.connection_store import (
    ChatGptConnection,
    ChatGptCredential,
    LlmConnection,
    bind_request_llm_connection,
    set_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import (
    OwnerMismatchError,
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    mark_configured,
    restore_expired_cloud_identity,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.proxy_errors import build_llm_proxy_agent_error
from pantaray_agents.utils.llm_types import types
from pantaray_agents.utils.trace_context import TraceContextManager
from pantaray_llm.contracts.tool_use import (
    LlmToolUseRequest,
)
from pantaray_llm.errors import LlmProxyExecutionError
from pantaray_llm.profiles import ACTIVITY_SUMMARY_PROFILE_ID

from .migrated_db import prepare_test_database

PROXY_URL = "https://llm.example.test/v1/llm/proxy"
ACCOUNT_OWNER = "account-user"
LOCAL_OWNER = "local-owner"
LOCAL_JOB_ID = "job-route"
CLOUD_RESPONSE_PAYLOAD: dict[str, object] = {
    "id": "resp_cloud",
    "model": "gpt-6-luna",
    "output": [
        {"role": "assistant", "content": [{"type": "output_text", "text": "hello"}]}
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    "meta": {
        "local_job_id": LOCAL_JOB_ID,
        "upstream_provider": "openai",
        "profile_id": ACTIVITY_SUMMARY_PROFILE_ID,
        "outcome": "complete",
    },
}


class CloudBoundary:
    """Lends the cloud route a client that records every POST to the proxy."""

    def __init__(self, response: object) -> None:
        self.requests: list[str] = []
        self.response = response

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        boundary = self

        class _Client:
            def __init__(self, **_kwargs: object) -> None: ...

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *_args: object) -> None:
                return None

            async def post(self, url: str, **_kwargs: object) -> object:
                boundary.requests.append(url)
                return boundary.response

        monkeypatch.setattr(
            "pantaray_agents.local_runtime.llm_proxy.client.httpx2.AsyncClient",
            _Client,
        )


type Boundaries = tuple[CloudBoundary, SendBoundary]


@pytest.fixture(autouse=True)
def logged_out_owner() -> None:
    """Startup registers the logged-out owner before anything can be claimed."""
    register_logged_out_owner(LOCAL_OWNER)
    yield
    reset_logged_out_owner()


@pytest.fixture
def boundaries(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Boundaries]:
    def install(
        *,
        cloud_response: object | None = None,
        provider_handler: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> Boundaries:
        cloud = CloudBoundary(
            cloud_response
            or _FakeHttpResponse(status_code=200, payload=CLOUD_RESPONSE_PAYLOAD)
        )
        cloud.install(monkeypatch)
        provider = SendBoundary(provider_handler or responder())
        monkeypatch.setattr(direct, "source_http_client", provider.http_client)
        return cloud, provider

    return install


def refuse_file_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """A route that sends nothing must not have opened the caller's files."""

    def fail_if_called(**_kwargs: object) -> object:
        raise AssertionError("file inputs must not be read before the route refuses")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.llm_proxy.request_builder.prepare_content_file",
        fail_if_called,
    )


def _migrated_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )
    return db_path


def sign_in(tmp_path: Path) -> None:
    """Apply a ``configure`` whose cloud session is present."""
    import_desktop_session(
        db_path=_migrated_db(tmp_path),
        busy_timeout_ms=1_000,
        user_id=ACCOUNT_OWNER,
        desktop_access_token="desktop-token",
        expires_at="2099-01-01T00:00:00Z",
        session_version="1",
    )
    mark_configured()


def expire_session(tmp_path: Path) -> None:
    """Apply a ``configure`` that restores a session main could not refresh."""
    restore_expired_cloud_identity(
        db_path=_migrated_db(tmp_path),
        busy_timeout_ms=1_000,
        user_id=ACCOUNT_OWNER,
        session_version="1",
    )
    mark_configured()


def configure_connection(connection: LlmConnection = OPENAI_CONNECTION) -> None:
    """Apply a ``configure`` with no cloud session and a stored connection."""
    mark_configured()
    set_llm_connection(connection)


async def generate(
    *,
    owner: str = LOCAL_OWNER,
    proxy_client: LocalLlmProxyClient | None = None,
    contents: list[object] | None = None,
    tool_use: LlmToolUseRequest | None = None,
) -> ProxyResponse:
    with TraceContextManager(user_id=owner, local_job_id=LOCAL_JOB_ID):
        return await (
            proxy_client or LocalLlmProxyClient(proxy_url=PROXY_URL)
        ).aio.models.generate_content(
            contents=contents if contents is not None else ["hello"],
            config=types.GenerateContentConfig(
                inference_profile=ACTIVITY_SUMMARY_PROFILE_ID, tool_use=tool_use
            ),
        )


def agent_guidance(error: LlmProxyExecutionError) -> Mapping[str, object]:
    """What the Action agent finally reads off the failure."""
    details = build_llm_proxy_agent_error(
        exception=error, error_code_prefix="ACTION"
    ).error_details
    assert details is not None
    return details


async def test_a_present_cloud_session_reaches_only_the_pantaray_proxy(
    boundaries: Callable[..., Boundaries], tmp_path: Path
) -> None:
    configure_connection()
    sign_in(tmp_path)
    cloud, provider = boundaries()

    result = await generate(owner=ACCOUNT_OWNER)

    assert cloud.requests == [PROXY_URL]
    assert provider.requests == []
    assert result.text == "hello"


async def test_a_stored_connection_reaches_only_its_own_provider(
    boundaries: Callable[..., Boundaries],
) -> None:
    configure_connection()
    cloud, provider = boundaries()

    result = await generate()

    assert cloud.requests == []
    assert provider.targets == [
        ("api.openai.com", "/v1/responses/input_tokens"),
        ("api.openai.com", "/v1/responses"),
    ]
    assert provider.requests[-1].headers["authorization"] == f"Bearer {OPENAI_KEY}"
    # `test_direct_llm_dispatch` pins the whole response against the cloud
    # parsing; what this route has to deliver is that same contract, populated.
    assert result.text == "hello"
    assert result.meta == {
        "local_job_id": LOCAL_JOB_ID,
        "upstream_provider": "openai",
        "profile_id": ACTIVITY_SUMMARY_PROFILE_ID,
        "outcome": "complete",
        "upstream_request_id": "resp_1",
    }
    assert result.usage_metadata is not None


@pytest.mark.parametrize(
    "connection",
    [OPENAI_CONNECTION, CHATGPT_CONNECTION],
    ids=["api_key", "chatgpt"],
)
async def test_next_request_uses_the_new_model_on_the_same_account(
    boundaries: Callable[..., Boundaries], connection: LlmConnection
) -> None:
    configure_connection(connection)
    cloud, provider = boundaries()

    await generate()
    with bind_request_llm_connection(connection):
        set_llm_connection(replace(connection, model="gpt-5.6-terra"))
        await generate()
    await generate()

    assert cloud.requests == []
    assert [
        json.loads(request.content)["model"]
        for request in provider.requests
        if request.url.path.endswith("/responses")
    ] == [connection.model, connection.model, "gpt-5.6-terra"]


@pytest.mark.parametrize(
    "configured", [True, False], ids=["no-connection", "no-configure"]
)
async def test_an_unconfigured_llm_route_sends_nothing(
    boundaries: Callable[..., Boundaries], configured: bool
) -> None:
    if configured:
        mark_configured()
    cloud, provider = boundaries()

    with pytest.raises(LlmProxyExecutionError) as caught:
        await generate()

    failure = caught.value
    assert failure.error_code == "PROXY_CONNECTION_NOT_CONFIGURED"
    assert failure.retryable is False
    assert failure.local_job_id == LOCAL_JOB_ID
    assert failure.profile_id == ACTIVITY_SUMMARY_PROFILE_ID
    assert agent_guidance(failure)["suggested_action"] == "configure_connection"
    assert cloud.requests == []
    assert provider.requests == []


async def test_an_expired_cloud_session_sends_nothing_even_with_a_stored_connection(
    boundaries: Callable[..., Boundaries], tmp_path: Path
) -> None:
    configure_connection()
    expire_session(tmp_path)
    cloud, provider = boundaries()

    with pytest.raises(LlmProxyExecutionError) as caught:
        await generate(owner=ACCOUNT_OWNER)

    failure = caught.value
    assert failure.error_code == "PROXY_AUTHENTICATION_FAILED"
    assert failure.retryable is False
    assert failure.profile_id == ACTIVITY_SUMMARY_PROFILE_ID
    assert agent_guidance(failure)["suggested_action"] == "reauthenticate"
    assert cloud.requests == []
    assert provider.requests == []


@pytest.mark.parametrize(
    ("connection", "repair"),
    [
        (CHATGPT_CONNECTION, "reauthenticate"),
        (OPENAI_CONNECTION, "configure_connection"),
    ],
    ids=["chatgpt", "api-key"],
)
async def test_a_rejected_credential_names_the_repair_its_own_kind_needs(
    boundaries: Callable[..., Boundaries],
    connection: LlmConnection,
    repair: str,
) -> None:
    configure_connection(connection)
    cloud, provider = boundaries(provider_handler=responder(status_code=401))

    with pytest.raises(LlmProxyExecutionError) as caught:
        await generate()

    failure = caught.value
    assert failure.error_code == "PROXY_AUTHENTICATION_FAILED"
    assert failure.retryable is False
    assert agent_guidance(failure)["suggested_action"] == repair
    assert cloud.requests == []


async def test_a_cloud_failure_never_reaches_a_stored_connection(
    boundaries: Callable[..., Boundaries], tmp_path: Path
) -> None:
    configure_connection()
    sign_in(tmp_path)
    cloud, provider = boundaries(
        cloud_response=_FakeHttpResponse(
            status_code=402,
            payload={
                "error": {
                    "code": "PROXY_INSUFFICIENT_BALANCE",
                    "message": "Wallet balance is insufficient.",
                }
            },
        )
    )

    with pytest.raises(LlmProxyExecutionError) as caught:
        await generate(owner=ACCOUNT_OWNER)

    assert caught.value.error_code == "PROXY_INSUFFICIENT_BALANCE"
    assert caught.value.retryable is False
    assert cloud.requests == [PROXY_URL]
    assert provider.requests == []


async def test_a_lapsed_chatgpt_token_is_never_sent(
    boundaries: Callable[..., Boundaries],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_connection(
        ChatGptConnection(
            model="gpt-5.6-sol",
            credential=ChatGptCredential(
                access_token=CHATGPT_TOKEN,
                expires_at="2020-01-01T00:00:00Z",
                account_id="acct-9",
            ),
        )
    )
    cloud, provider = boundaries()
    refuse_file_reads(monkeypatch)

    with pytest.raises(LlmProxyExecutionError) as caught:
        await generate(contents=file_contents(tmp_path))

    failure = caught.value
    assert failure.error_code == "PROXY_AUTHENTICATION_FAILED"
    assert failure.upstream_provider == "openai_codex"
    assert failure.local_job_id == LOCAL_JOB_ID
    assert failure.profile_id == ACTIVITY_SUMMARY_PROFILE_ID
    assert agent_guidance(failure)["suggested_action"] == "reauthenticate"
    assert cloud.requests == []
    assert provider.requests == []


async def test_another_owners_request_is_refused_before_its_files_are_read(
    boundaries: Callable[..., Boundaries],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A direct connection is the current owner's; the owner check comes first."""

    configure_connection()
    cloud, provider = boundaries()
    refuse_file_reads(monkeypatch)

    with pytest.raises(OwnerMismatchError):
        await generate(owner="someone-else", contents=file_contents(tmp_path))

    assert cloud.requests == []
    assert provider.requests == []


def file_contents(tmp_path: Path) -> list[object]:
    pdf_path = tmp_path / "attachment-blob.pdf"
    pdf_payload = b"%PDF-1.7\ncontent\n"
    pdf_path.write_bytes(pdf_payload)
    return [
        "read this file",
        {
            "file_data": {
                "blob_ref": "attachment_blob_pdf",
                "application_ref": "tool_attachment:abc",
                "filename": "attachment-blob.pdf",
                "mime_type": "application/pdf",
                "blob_path": str(pdf_path),
                "byte_size": len(pdf_payload),
                "sha256": hashlib.sha256(pdf_payload).hexdigest(),
            }
        },
    ]
