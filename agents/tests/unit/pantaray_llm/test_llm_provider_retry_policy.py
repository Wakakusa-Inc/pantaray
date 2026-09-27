from __future__ import annotations

from types import SimpleNamespace

import pytest

from pantaray_llm.providers.openai_responses import provider as openai_provider
from pantaray_llm.providers.openai_responses.transport import openai_api_transport


def test_openai_sdk_retry_is_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def build_client(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace()

    openai_provider.build_openai_client.cache_clear()
    monkeypatch.setattr(openai_provider, "AsyncOpenAI", build_client)
    try:
        openai_provider.build_openai_client(openai_api_transport(api_key="key"))
    finally:
        openai_provider.build_openai_client.cache_clear()

    assert captured["max_retries"] == 0
