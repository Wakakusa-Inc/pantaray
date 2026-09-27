"""ストリーミング用の共通ヘルパ。

NDJSON行の生成、UTC現在時刻の付与、標準チャンク/終了イベントの生成を提供する。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from pantaray_agents.schema.agent.base import JSONValue, TaskStatusType
from pantaray_agents.schema.agent.streaming import CompletionChunk, StreamEndData

type StreamPayload = dict[str, JSONValue]


def now_iso_utc() -> str:
    """UTC現在時刻をISO 8601文字列で返す。"""
    return datetime.now(UTC).isoformat()


def ndjson_line(event: str, data: StreamPayload) -> str:
    """`{"event": ..., "data": ...}` 形式のNDJSON行を生成する。"""
    return json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n"


def make_completion_chunk(content: str, index: int) -> CompletionChunk:
    """`CompletionChunk` を現在時刻付きで生成する。"""
    return CompletionChunk(content=content, chunk_index=index, timestamp=now_iso_utc())


def coerce_task_status(value: object) -> TaskStatusType:
    """外部公開用のタスクステータスへ正規化する。

    目的:
        - 外部API（stream_end/status）に `queued` を出さない。
        - 実装の揺れ（DB/呼び出し元での型揺れ）を境界で吸収し、常に TaskStatusType に収める。

    変換規則:
        - TaskStatusType: そのまま返す
        - "queued": "processing" に丸める（外部非公開ポリシー）
        - 既知文字列: そのまま TaskStatusType に変換
        - その他: 安全側として error
    """
    if isinstance(value, TaskStatusType):
        return value
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw == "queued":
            return TaskStatusType.PROCESSING
        if raw in {"processing", "success", "error", "canceled", "timeout"}:
            return TaskStatusType(raw)
        return TaskStatusType.ERROR
    # StatusType 等の Enum（str継承）もここに落ちる可能性があるため、str化して再評価
    try:
        text = str(value).strip().lower()
    except Exception:
        return TaskStatusType.ERROR
    if text == "queued":
        return TaskStatusType.PROCESSING
    if text in {"processing", "success", "error", "canceled", "timeout"}:
        return TaskStatusType(text)
    return TaskStatusType.ERROR


def make_stream_end_for_suggestion(
    *,
    suggestion_id: str,
    user_id: str,
    has_suggestion: bool,
    total_chunks: int,
    status: TaskStatusType = TaskStatusType.SUCCESS,
    duration_ms: int = 0,
) -> StreamEndData:
    """Suggestion用の `StreamEndData` を現在時刻付きで生成する。"""
    return StreamEndData(
        suggestion_id=suggestion_id,
        has_suggestion=has_suggestion,
        user_id=user_id,
        completed_at=now_iso_utc(),
        status=status,
        total_chunks=total_chunks,
        duration_ms=duration_ms,
    )
