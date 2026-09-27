"""メモリ内の WebSocket セッションストア。

各セッションごとのプロセス状態や live text chunk の履歴を保持し、
WS仕様に基づくセッション再開や欠落チャンクの再送を支援する。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from pydantic import BaseModel

from pantaray_agents.orchestration.session.live_action_lookup import (
    has_live_action_process_in_sessions,
)
from pantaray_agents.orchestration.session.records import (
    ChunkRecord,
    ProcessRecord,
    SessionRecord,
)
from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket.server_messages import (
    CompletionChunkMessage,
    SuggestionChunkMessage,
)

logger = logging.getLogger(__name__)


class InMemorySessionStore:
    """WSセッションとストリームチャンクのためのシンプルなメモリ内ストア。"""

    def __init__(
        self,
        max_age_seconds: int,
        *,
        max_sessions: int | None = None,
        max_processes_per_session: int | None = None,
        max_events_per_session: int | None = None,
        max_chunks_per_process: int | None = None,
    ) -> None:
        """ストアを初期化する。

        Args:
            max_age_seconds: セッションの最大保持時間（秒）。
            max_sessions: 保持するセッション数の上限。0以下/None は無制限。
            max_processes_per_session: 1セッションあたりのプロセス数上限。0以下/None は無制限。
            max_events_per_session: 1セッションあたりのイベントメタ数上限。0以下/None は無制限。
            max_chunks_per_process: 1プロセスあたりの保存チャンク数上限。0以下/None は無制限。
        """

        self._max_age_seconds = max_age_seconds
        self._max_sessions = self._normalize_limit(max_sessions)
        self._max_processes_per_session = self._normalize_limit(
            max_processes_per_session
        )
        self._max_events_per_session = self._normalize_limit(max_events_per_session)
        self._max_chunks_per_process = self._normalize_limit(max_chunks_per_process)
        self._sessions: dict[str, SessionRecord] = {}

    @staticmethod
    def _normalize_limit(value: int | None) -> int | None:
        """上限値を正規化する（0以下は無制限扱い）。"""
        if value is None:
            return None
        try:
            n = int(value)
        except Exception:
            return None
        return None if n <= 0 else n

    def _prune_over_session_capacity(self) -> None:
        """セッション数の上限を超えた場合、古いセッションから削除する。"""
        max_sessions = self._max_sessions
        if max_sessions is None:
            return
        while len(self._sessions) > max_sessions:
            oldest_session_id = min(
                self._sessions,
                key=lambda session_id: self._session_activity_at(
                    self._sessions[session_id]
                ),
                default=None,
            )
            if oldest_session_id is None:
                return
            self._sessions.pop(oldest_session_id, None)

    def _ensure_process_capacity(self, sess: SessionRecord, process_id: str) -> None:
        """セッションあたりのプロセス数上限を超える場合に例外を送出する。"""
        limit = self._max_processes_per_session
        if limit is None:
            return
        if process_id in sess.processes:
            return
        if len(sess.processes) >= limit:
            raise ValueError("WS session process limit exceeded")

    @staticmethod
    def _now() -> float:
        return datetime.now(UTC).timestamp()

    @staticmethod
    def _new_session(*, now: float, user_id: str | None) -> SessionRecord:
        return SessionRecord(created_at=now, last_seen_at=now, user_id=user_id)

    @staticmethod
    def _touch_session(sess: SessionRecord, *, now: float) -> None:
        sess.last_seen_at = now

    @staticmethod
    def _session_activity_at(sess: SessionRecord) -> float:
        if sess.last_seen_at is None:
            return sess.created_at
        return sess.last_seen_at

    def _is_session_expired(self, sess: SessionRecord, *, now: float) -> bool:
        return (now - self._session_activity_at(sess)) > self._max_age_seconds

    def _ensure_touched_session(self, session_id: str, *, now: float) -> SessionRecord:
        sess = self._sessions.get(session_id)
        if sess is None:
            sess = self._new_session(now=now, user_id=None)
            self._sessions[session_id] = sess
            return sess
        self._touch_session(sess, now=now)
        return sess

    def create_session(self, session_id: str, *, user_id: str | None) -> None:
        """現在時刻で新しいセッションレコードを作成する。

        Args:
            session_id: サーバが発行するWSセッションID。
            user_id: 当該セッションの所有者（WS接続ユーザーID）。
        """
        self._sessions[session_id] = self._new_session(now=self._now(), user_id=user_id)
        self._prune_over_session_capacity()
        try:
            logger.debug(
                "SessionStore create_session session_id=%s user_id=%s",
                session_id,
                user_id,
            )
        except Exception:
            pass

    def prune(self) -> None:
        """設定された最大経過時間に基づき、期限切れセッションを削除する。"""
        now = self._now()
        expired = [
            sid
            for sid, s in self._sessions.items()
            if self._is_session_expired(s, now=now)
        ]
        for sid in expired:
            self._sessions.pop(sid, None)
        if expired:
            try:
                logger.debug("SessionStore prune expired_sessions=%s", expired)
            except Exception:
                pass

    def get(self, session_id: str) -> SessionRecord | None:
        """IDでセッションを返す。存在しない場合は None。"""
        return self._sessions.get(session_id)

    def ensure_process(self, session_id: str, process_id: str) -> ProcessRecord:
        """セッション内にプロセスレコードを確保して返す（無ければ作成）。"""
        sess = self._ensure_touched_session(session_id, now=self._now())
        self._ensure_process_capacity(sess, process_id)
        proc = sess.processes.setdefault(process_id, ProcessRecord())
        try:
            logger.debug(
                "SessionStore ensure_process session_id=%s process_id=%s next_index=%s",
                session_id,
                process_id,
                proc.next_chunk_index,
            )
        except Exception:
            pass
        return proc

    def set_process_metadata(
        self,
        session_id: str,
        process_id: str,
        *,
        suggestion_id: str | None = None,
        action_id: str | None = None,
        command_id: str | None = None,
        kind: str | None = None,
    ) -> None:
        """プロセスに関連メタデータを設定する。"""
        sess = self._ensure_touched_session(session_id, now=self._now())
        self._ensure_process_capacity(sess, process_id)
        proc = sess.processes.setdefault(process_id, ProcessRecord())
        if suggestion_id is not None:
            proc.suggestion_id = suggestion_id
        if action_id is not None:
            proc.action_id = action_id
        if command_id is not None:
            proc.command_id = command_id
        if kind is not None:
            proc.kind = kind
        try:
            logger.debug(
                "SessionStore set_process_metadata session_id=%s process_id=%s suggestion_id=%s action_id=%s command_id=%s kind=%s",
                session_id,
                process_id,
                suggestion_id,
                action_id,
                command_id,
                kind,
            )
        except Exception:
            pass

    def get_process_metadata(self, session_id: str, process_id: str) -> dict | None:
        """プロセスに紐づくメタを辞書で返す。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return None
        proc = sess.processes.get(process_id)
        if not proc:
            return None
        return self._build_process_meta(process_id, proc)

    def append_stream_chunk(
        self,
        session_id: str,
        process_id: str,
        event_id: str,
        *,
        event_name: str,
        msg: BaseModel,
    ) -> int:
        """指定プロセスに live text chunk を追加し、割り当てインデックスを返す。"""
        sess = self._ensure_touched_session(session_id, now=self._now())
        self._ensure_process_capacity(sess, process_id)
        proc = sess.processes.setdefault(process_id, ProcessRecord())
        idx = proc.next_chunk_index
        proc.next_chunk_index = idx + 1

        # 容量上限を超える場合は「再開不可」としてチャンク保存を停止する（fail-closed）。
        if not proc.resume_available:
            return idx
        max_chunks = self._max_chunks_per_process
        if max_chunks is not None and len(proc.chunks) >= max_chunks:
            proc.resume_available = False
            return idx
        max_events = self._max_events_per_session
        if max_events is not None and len(sess.events) >= max_events:
            proc.resume_available = False
            return idx

        proc.chunks[idx] = ChunkRecord(
            event_name=event_name,
            event_id=event_id,
            data=msg,  # type: ignore[assignment]
        )
        meta = self._build_process_meta(process_id, proc)
        sess.events[event_id] = {
            "event": event_name,
            "process_id": process_id,
            "chunk_index": idx,
            "acked": False,
            **meta,
        }
        sess.last_event_id = event_id
        try:
            logger.debug(
                "SessionStore append_chunk session_id=%s process_id=%s index=%s event_id=%s",
                session_id,
                process_id,
                idx,
                event_id,
            )
        except Exception:
            pass
        return idx

    def append_completion_chunk(
        self,
        session_id: str,
        process_id: str,
        event_id: str,
        msg: CompletionChunkMessage,
    ) -> int:
        return self.append_stream_chunk(
            session_id,
            process_id,
            event_id,
            event_name="completion_chunk",
            msg=msg,
        )

    def clear_process(self, session_id: str, process_id: str) -> None:
        """指定プロセスに紐づくチャンク/メタデータを即座に解放する。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return
        proc_removed = sess.processes.pop(process_id, None)
        if proc_removed is None and not sess.events:
            return
        to_delete: list[str] = [
            event_id
            for event_id, meta in sess.events.items()
            if meta.get("process_id") == process_id
        ]
        for event_id in to_delete:
            sess.events.pop(event_id, None)
        try:
            logger.debug(
                "SessionStore clear_process session_id=%s process_id=%s removed_events=%s",
                session_id,
                process_id,
                len(to_delete),
            )
        except Exception:
            pass

    def discard_completed_process(self, session_id: str, process_id: str) -> None:
        """completed process metadata を即座に解放する。"""
        self.mark_process_acknowledged(session_id, process_id)
        self.clear_process(session_id, process_id)

    def mark_process_completion_emitted(
        self, session_id: str, process_id: str, *, status: str | None = None
    ) -> None:
        """process_completed を送信した時刻を記録する。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return
        proc = sess.processes.get(process_id)
        if not proc:
            return
        now = self._now()
        self._touch_session(sess, now=now)
        proc.completed_at = now
        proc.acknowledged_at = None
        try:
            logger.debug(
                "SessionStore mark_process_completed session_id=%s process_id=%s status=%s",
                session_id,
                process_id,
                status,
            )
        except Exception:
            pass

    def mark_process_acknowledged(self, session_id: str, process_id: str) -> None:
        """クライアントからのACKを受け取った時刻を記録する。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return
        proc = sess.processes.get(process_id)
        if not proc:
            return
        now = self._now()
        self._touch_session(sess, now=now)
        proc.acknowledged_at = now
        try:
            logger.debug(
                "SessionStore mark_process_acknowledged session_id=%s process_id=%s",
                session_id,
                process_id,
            )
        except Exception:
            pass

    def prune_completed(self, retention_seconds: int) -> None:
        """ACK が来なかった completed process metadata を保持期間経過後に削除する。"""
        if retention_seconds <= 0:
            return
        now = self._now()
        for session_id, sess in list(self._sessions.items()):
            to_remove: list[str] = []
            for process_id, proc in list(sess.processes.items()):
                if proc.acknowledged_at is not None:
                    to_remove.append(process_id)
                    continue
                if proc.completed_at is None:
                    continue
                if (now - proc.completed_at) > retention_seconds:
                    to_remove.append(process_id)
            for process_id in to_remove:
                self.clear_process(session_id, process_id)

    def record_event_meta(
        self,
        session_id: str,
        event_id: str,
        process_id: str | None,
        chunk_index: int | None,
        *,
        event_name: str | None = None,
        meta: dict | None = None,
    ) -> None:
        """再開チェック用に、非チャンクイベントのメタデータを記録する。"""
        sess = self._ensure_touched_session(session_id, now=self._now())
        max_events = self._max_events_per_session
        terminal_event = (
            event_name == OutboundEvent.PROCESS_COMPLETED.value
            and process_id in sess.processes
        )
        if terminal_event:
            sess.events = {
                stored_id: stored
                for stored_id, stored in sess.events.items()
                if stored_id == event_id
                or stored.get("event") != event_name
                or stored.get("process_id") != process_id
            }
        if (
            max_events is not None
            and len(sess.events) >= max_events
            and not terminal_event
        ):
            # 容量制限: 記録できない場合は best-effort で破棄する
            if process_id and process_id in sess.processes:
                sess.processes[process_id].resume_available = False
            return
        sess.events[event_id] = {
            "event": event_name,
            "process_id": process_id,
            "chunk_index": chunk_index,
            "acked": False,
        }
        if meta:
            for key, value in meta.items():
                if value is not None:
                    sess.events[event_id][key] = value
        sess.last_event_id = event_id
        try:
            logger.debug(
                "SessionStore record_event_meta session_id=%s event_id=%s process_id=%s chunk_index=%s",
                session_id,
                event_id,
                process_id,
                chunk_index,
            )
        except Exception:
            pass

    def is_resume_available(self, session_id: str, process_id: str) -> bool:
        """対象プロセスが resume_session で再開可能かを返す。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return False
        proc = sess.processes.get(process_id)
        if not proc:
            return False
        return bool(proc.resume_available)

    def has_active_session(self, session_id: str, *, user_id: str) -> bool:
        """指定 user の session が activity retention 内に存在するかを返す。"""
        sess = self._sessions.get(session_id)
        if not sess:
            return False
        if str(sess.user_id or "").strip() != user_id.strip():
            return False
        return not self._is_session_expired(sess, now=self._now())

    def has_live_action_process(
        self,
        *,
        user_id: str,
        process_id: str,
        suggestion_id: str,
        action_id: str,
        command_id: str,
    ) -> bool:
        """指定 action process が active な状態でメモリ上に存在するかを返す。"""
        now = self._now()
        return has_live_action_process_in_sessions(
            sessions=(
                session
                for session in self._sessions.values()
                if not self._is_session_expired(session, now=now)
            ),
            user_id=user_id,
            process_id=process_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
            command_id=command_id,
        )

    def iter_missing_chunks(
        self, session_id: str, process_id: str, start_index: int
    ) -> list[tuple[int, str, CompletionChunkMessage | SuggestionChunkMessage]]:
        """start_index 以降の live text chunk を返す。"""

        sess = self._sessions.get(session_id)
        if not sess:
            try:
                logger.debug(
                    "SessionStore iter_missing_chunks no_session session_id=%s process_id=%s start_index=%s",
                    session_id,
                    process_id,
                    start_index,
                )
            except Exception:
                pass
            return []
        proc = sess.processes.get(process_id)
        if not proc:
            try:
                logger.debug(
                    "SessionStore iter_missing_chunks no_process session_id=%s process_id=%s start_index=%s",
                    session_id,
                    process_id,
                    start_index,
                )
            except Exception:
                pass
            return []
        next_idx = proc.next_chunk_index
        chunks: list[
            tuple[int, str, CompletionChunkMessage | SuggestionChunkMessage]
        ] = []
        for i in range(start_index, next_idx):
            record = proc.chunks.get(i)
            if record:
                chunks.append((i, record.event_name, record.data))
        try:
            logger.debug(
                "SessionStore iter_missing_chunks session_id=%s process_id=%s start_index=%s count=%s",
                session_id,
                process_id,
                start_index,
                len(chunks),
            )
        except Exception:
            pass
        return chunks

    def replay_missing_chunks(
        self, session_id: str, process_id: str, start_index: int
    ) -> list[tuple[str, CompletionChunkMessage | SuggestionChunkMessage, dict]]:
        """start_index 以降の live text chunk とメタを返す。"""

        sess = self._sessions.get(session_id)
        if not sess:
            return []
        proc = sess.processes.get(process_id)
        if not proc:
            return []
        base_meta = self._build_process_meta(process_id, proc)
        return [
            (event_name, msg, dict(base_meta))
            for _, event_name, msg in self.iter_missing_chunks(
                session_id, process_id, start_index
            )
        ]

    def ack_event(self, session_id: str, event_id: str) -> dict | None:
        """特定イベントをACK済みとしてマークし、メタ情報を返す。"""

        sess = self._sessions.get(session_id)
        if not sess:
            return None
        meta = sess.events.get(event_id)
        if meta is None:
            return None
        meta["acked"] = True
        sess.last_acked_event_id = event_id
        return meta

    @staticmethod
    def _build_process_meta(process_id: str, proc: ProcessRecord) -> dict:
        meta: dict[str, str] = {"process_id": process_id}
        if proc.suggestion_id:
            meta["suggestion_id"] = proc.suggestion_id
        if proc.action_id:
            meta["action_id"] = proc.action_id
        if proc.command_id:
            meta["command_id"] = proc.command_id
        if proc.kind:
            meta["kind"] = proc.kind
        return meta
