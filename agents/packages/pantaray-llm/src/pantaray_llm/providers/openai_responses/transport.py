"""OpenAI Responses API を話す接続先の差分（URL・認証ヘッダー・要求方針）。

アダプター本体（provider.py）は接続先を知らず、この transport だけを見て
クライアント生成・トークン数の事前検査・ストリーミングの要否を切り替える。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type OpenAiResponsesProvider = Literal["openai", "openai_codex", "fireworks"]

OPENAI_API_BASE_URL = "https://api.openai.com/v1"
CHATGPT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
FIREWORKS_BASE_URL = "https://api.fireworks.ai/inference/v1"
# ChatGPT backend に名乗るクライアント識別子。
CHATGPT_ORIGINATOR = "pantaray"


@dataclass(frozen=True, slots=True)
class OpenAiResponsesTransport:
    provider: OpenAiResponsesProvider
    base_url: str
    # SDK が Authorization: Bearer として送る値（API キーまたは OAuth access token）。
    api_key: str
    # 認証・識別のために追加で送るヘッダー。lru_cache のキーにするため tuple。
    extra_headers: tuple[tuple[str, str], ...] = ()
    # ChatGPT backend は stream: true 以外を拒否するので SSE を読み切って最終応答にする。
    stream: bool = False
    # responses.input_tokens.count は api.openai.com だけが提供する。
    supports_input_token_count: bool = False
    # ChatGPT backend は reasoning.encrypted_content の include を常に要求する。
    always_include_encrypted_reasoning: bool = False


def openai_api_transport(
    *, api_key: str, base_url: str = OPENAI_API_BASE_URL
) -> OpenAiResponsesTransport:
    """`base_url` は診断用の capture proxy など、公式エンドポイントの代替を指す。"""

    return OpenAiResponsesTransport(
        provider="openai",
        base_url=base_url,
        api_key=api_key,
        supports_input_token_count=True,
    )


def chatgpt_codex_transport(
    *, access_token: str, account_id: str
) -> OpenAiResponsesTransport:
    return OpenAiResponsesTransport(
        provider="openai_codex",
        base_url=CHATGPT_CODEX_BASE_URL,
        api_key=access_token,
        extra_headers=(
            ("chatgpt-account-id", account_id),
            ("originator", CHATGPT_ORIGINATOR),
            ("OpenAI-Beta", "responses=experimental"),
            # The SDK never announces SSE; Codex sends this on every /responses call.
            ("Accept", "text/event-stream"),
        ),
        stream=True,
        always_include_encrypted_reasoning=True,
    )


def fireworks_transport(*, api_key: str) -> OpenAiResponsesTransport:
    return OpenAiResponsesTransport(
        provider="fireworks", base_url=FIREWORKS_BASE_URL, api_key=api_key
    )


__all__ = [
    "CHATGPT_CODEX_BASE_URL",
    "FIREWORKS_BASE_URL",
    "OPENAI_API_BASE_URL",
    "OpenAiResponsesProvider",
    "OpenAiResponsesTransport",
    "chatgpt_codex_transport",
    "fireworks_transport",
    "openai_api_transport",
]
