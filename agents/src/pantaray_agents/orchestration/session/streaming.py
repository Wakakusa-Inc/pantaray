"""エージェントAPI向け HTTP NDJSON ストリーミングのヘルパ。"""

from __future__ import annotations

import json
from typing import Final

import httpx2

from ..common.types import EventPayload, OnEventHandler

# デフォルトの全体タイムアウト（秒）。用途ごとに明示的な値を渡すことを推奨する。
DEFAULT_STREAM_TIMEOUT_SECONDS: Final[float | None] = None


async def post_ndjson_stream(
    url: str,
    json_body: EventPayload,
    headers: dict[str, str],
    on_event: OnEventHandler,
    *,
    timeout_seconds: float | None = DEFAULT_STREAM_TIMEOUT_SECONDS,
) -> None:
    """application/x-ndjson のストリーミングPOSTを開き、各行のイベントを中継する。

    - 各NDJSON行を {"event": str, "data": object} としてパース
    - 行ごとに `on_event(event, data)` を呼び出し
    - HTTPエラーやデコード失敗時は `on_event("error", ...)` を送る

    timeout_seconds が指定されている場合は、HTTP クライアント全体のタイムアウトとして適用される。
    タイムアウトした場合は、呼び出し元がストリーム終了として扱えるよう
    `on_event("stream_end", {"status": "timeout"})` を 1 回送出する。
    """
    timeout = httpx2.Timeout(timeout_seconds)
    try:
        async with httpx2.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST", url, json=json_body, headers=headers
            ) as resp:
                if resp.is_error:
                    # Try to parse JSON error body; if not JSON, synthesize
                    try:
                        body = await resp.aread()
                        text = body.decode("utf-8", errors="ignore")
                        parsed = json.loads(text)
                    except Exception:  # noqa: BLE001 - keep surface small here
                        parsed = {
                            "error_type": "internal_error",
                            "error_code": "HTTP_STREAM_ERROR",
                            "error_message": f"status={resp.status_code}",
                        }
                    await on_event("error", parsed)
                    return

                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        await on_event(
                            "error",
                            {
                                "error_type": "internal_error",
                                "error_code": "NDJSON_DECODE_ERROR",
                                "error_message": f"Invalid NDJSON line: {line[:200]}",
                                "severity": "error",
                            },
                        )
                        continue
                    event = obj.get("event")
                    data = obj.get("data") or {}
                    # Trust event names from agents; they are validated at call sites
                    await on_event(event, data)  # type: ignore[arg-type]
    except httpx2.TimeoutException:
        # ストリーム全体のタイムアウト。呼び出し側で status="timeout" を扱えるようにする。
        await on_event("stream_end", {"status": "timeout"})
