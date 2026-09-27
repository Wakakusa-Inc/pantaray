from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.runtime.connection_store import (
    ApiKeyConnection,
    ChatGptConnection,
    ChatGptCredential,
    LlmConnection,
    WebSearchCredential,
    apply_connection_configuration,
    bind_request_llm_connection,
    clear_llm_connection,
    clear_web_search_credential,
    peek_llm_connection,
    peek_web_search_credential,
    read_llm_connection,
    read_llm_route,
    read_optional_llm_connection,
    read_optional_web_search_credential,
    read_web_search_credential,
    read_web_search_route,
    request_llm_connection,
    set_llm_connection,
    set_web_search_credential,
)
from pantaray_agents.local_runtime.runtime.session_store import mark_configured
from pantaray_agents.local_runtime.storage.migrations import MigrationError

_CHATGPT_PAYLOAD: dict[str, object] = {
    "kind": "chatgpt",
    "model": "gpt-5-codex",
    "credential": {
        "access_token": "chatgpt-access-token",
        "expires_at": "2026-09-17T00:00:00Z",
        "account_id": "chatgpt-account",
    },
}


def _openai_connection() -> ApiKeyConnection:
    return ApiKeyConnection(provider="openai", model="gpt-5", api_key="openai-key")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {
                "kind": "api_key",
                "provider": "openai",
                "model": "gpt-5",
                "api_key": "openai-key",
            },
            _openai_connection(),
        ),
        (
            {
                "kind": "api_key",
                "provider": "anthropic",
                "model": "claude-opus-5",
                "api_key": "anthropic-key",
            },
            ApiKeyConnection(
                provider="anthropic", model="claude-opus-5", api_key="anthropic-key"
            ),
        ),
        (
            {
                "kind": "api_key",
                "provider": "fireworks",
                "model": "accounts/fireworks/models/kimi",
                "api_key": "fireworks-key",
            },
            ApiKeyConnection(
                provider="fireworks",
                model="accounts/fireworks/models/kimi",
                api_key="fireworks-key",
            ),
        ),
        (
            _CHATGPT_PAYLOAD,
            ChatGptConnection(
                model="gpt-5-codex",
                credential=ChatGptCredential(
                    access_token="chatgpt-access-token",
                    expires_at="2026-09-17T00:00:00Z",
                    account_id="chatgpt-account",
                ),
            ),
        ),
    ],
)
def test_read_llm_connection_builds_the_matching_variant(
    payload: dict[str, object], expected: LlmConnection
) -> None:
    assert read_llm_connection(payload) == expected


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"kind": "oauth", "model": "gpt-5"}, "llm_connection.kind"),
        (
            {
                "kind": "api_key",
                "provider": "gemini",
                "model": "gemini-3",
                "api_key": "key",
            },
            "llm_connection.provider",
        ),
        (
            {"kind": "api_key", "provider": "openai", "model": "gpt-5"},
            "api_key must be a string",
        ),
        ({"kind": "chatgpt", "model": "gpt-5-codex"}, "credential must be an object"),
        (
            {
                "kind": "chatgpt",
                "model": "gpt-5-codex",
                "credential": {"access_token": "token", "expires_at": "2026-09-17"},
            },
            "account_id must be a string",
        ),
    ],
)
def test_read_llm_connection_rejects_an_incomplete_payload(
    payload: dict[str, object], message: str
) -> None:
    with pytest.raises(MigrationError, match=message):
        read_llm_connection(payload)


def test_connection_rejections_never_quote_the_submitted_value() -> None:
    with pytest.raises(MigrationError) as llm_error:
        read_llm_connection(
            {
                "kind": "api_key",
                "provider": "sk-misplaced-secret",
                "model": "gpt-5",
                "api_key": "sk-misplaced-secret",
            }
        )
    with pytest.raises(MigrationError) as search_error:
        read_web_search_credential(
            {"provider": "tvly-misplaced-secret", "api_key": "tvly-misplaced-secret"}
        )

    assert "sk-misplaced-secret" not in str(llm_error.value)
    assert "tvly-misplaced-secret" not in str(search_error.value)


def test_read_web_search_credential_accepts_only_tavily() -> None:
    assert read_web_search_credential(
        {"provider": "tavily", "api_key": "tavily-key"}
    ) == WebSearchCredential(api_key="tavily-key")
    with pytest.raises(MigrationError, match="web_search_credential.provider"):
        read_web_search_credential({"provider": "brave", "api_key": "brave-key"})


def test_optional_readers_treat_a_missing_setting_as_none() -> None:
    assert read_optional_llm_connection({}) is None
    assert read_optional_web_search_credential({}) is None
    assert read_optional_llm_connection(
        {"llm_connection": _CHATGPT_PAYLOAD}
    ) == read_llm_connection(_CHATGPT_PAYLOAD)
    assert read_optional_web_search_credential(
        {"web_search_credential": {"provider": "tavily", "api_key": "tavily-key"}}
    ) == WebSearchCredential(api_key="tavily-key")


def test_routes_stay_unconfigured_until_configure_is_applied() -> None:
    set_llm_connection(_openai_connection())
    set_web_search_credential(WebSearchCredential(api_key="tavily-key"))

    assert read_llm_route() == "unconfigured"
    assert read_web_search_route() == "unconfigured"


def test_a_stored_setting_routes_directly_while_signed_out() -> None:
    mark_configured()
    assert read_llm_route() == "unconfigured"
    assert read_web_search_route() == "unconfigured"

    set_llm_connection(_openai_connection())
    set_web_search_credential(WebSearchCredential(api_key="tavily-key"))
    assert read_llm_route() == "direct"
    assert read_web_search_route() == "direct"

    clear_llm_connection()
    clear_web_search_credential()
    assert read_llm_route() == "unconfigured"
    assert read_web_search_route() == "unconfigured"


def test_apply_connection_configuration_replaces_both_settings_at_once() -> None:
    set_llm_connection(_openai_connection())
    set_web_search_credential(WebSearchCredential(api_key="tavily-key"))

    apply_connection_configuration(
        llm_connection=None,
        web_search_credential=WebSearchCredential(api_key="rotated-tavily-key"),
    )

    assert peek_llm_connection() is None
    assert peek_web_search_credential() == WebSearchCredential(
        api_key="rotated-tavily-key"
    )


def test_request_snapshot_does_not_follow_a_changed_connection() -> None:
    original = _openai_connection()
    replacement = ApiKeyConnection(
        provider="openai", model="gpt-6-luna", api_key="openai-key"
    )
    set_llm_connection(original)

    with bind_request_llm_connection(original):
        set_llm_connection(replacement)
        assert request_llm_connection() == original
        with bind_request_llm_connection(None):
            assert request_llm_connection() is None

    assert request_llm_connection() == replacement
