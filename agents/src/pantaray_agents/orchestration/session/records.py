"""In-memory WebSocket session record shapes."""

from __future__ import annotations

from dataclasses import dataclass, field

from pantaray_agents.schema.websocket.server_messages import (
    CompletionChunkMessage,
    SuggestionChunkMessage,
)


@dataclass
class ChunkRecord:
    """保存された live text chunk のエントリー。"""

    event_name: str
    event_id: str
    data: CompletionChunkMessage | SuggestionChunkMessage


@dataclass
class ProcessRecord:
    """プロセスごとのチャンクインデックスとチャンクマップ。"""

    next_chunk_index: int = 0
    chunks: dict[int, ChunkRecord] = field(default_factory=dict)
    suggestion_id: str | None = None
    action_id: str | None = None
    command_id: str | None = None
    kind: str | None = None
    completed_at: float | None = None
    acknowledged_at: float | None = None
    resume_available: bool = True


@dataclass
class SessionRecord:
    """セッションごとのメタデータ、イベント索引、プロセス群。"""

    created_at: float
    last_seen_at: float | None = None
    user_id: str | None = None
    last_event_id: str | None = None
    last_acked_event_id: str | None = None
    events: dict[str, dict] = field(default_factory=dict)
    processes: dict[str, ProcessRecord] = field(default_factory=dict)
