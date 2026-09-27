"""Suggestion state router tests."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.suggestion_state.repository import (
    LocalSuggestionStateRepository,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult

BUSY_TIMEOUT_MS = 1_000


@pytest.mark.asyncio
async def test_suggestion_state_with_pending_chunks(monkeypatch):
    from pantaray_agents.routers import suggestion as suggestion_router

    session_id = "sess-1"
    process_id = "proc-1"

    class DummyChunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class DummyChunkRecord:
        def __init__(self, event_id: str, data: DummyChunk) -> None:
            self.event_id = event_id
            self.data = data

    class DummyProcess:
        def __init__(self) -> None:
            self.next_chunk_index = 2
            self.suggestion_id = "sug-1"
            self.chunks = {1: DummyChunkRecord("event-1", DummyChunk("chunk-1"))}

    class DummySession:
        def __init__(self) -> None:
            self.user_id = "user-1"
            self.processes = {process_id: DummyProcess()}
            self.events = {
                "event-1": {
                    "event": "suggestion_chunk",
                    "process_id": process_id,
                    "chunk_index": 1,
                }
            }

    class DummyStore:
        def __init__(self) -> None:
            self._session = DummySession()

        def get(self, sid: str):
            return self._session if sid == session_id else None

        def iter_missing_chunks(self, sid: str, pid: str, start_index: int):
            if sid != session_id or pid != process_id or start_index > 1:
                return []
            record = self._session.processes[process_id].chunks[1]
            return [(1, "suggestion_chunk", record.data)]

    monkeypatch.setattr(
        "pantaray_agents.orchestration.router.SESSION_STORE",
        DummyStore(),
        raising=False,
    )

    class FakeRepository:
        async def get_suggestion_state(
            self, *, user_id: str, suggestion_id: str
        ) -> RepositoryResult[dict]:
            assert user_id == "user-1"
            assert suggestion_id == "sug-1"
            return RepositoryResult(
                data={
                    "suggestion_id": "sug-1",
                    "user_id": "user-1",
                    "status": "processing",
                    "has_suggestion": True,
                    "answer": "intermediate",
                    "thinking": "thoughts",
                    "suggestion_summary": "Action handoff summary",
                    "target_context_json": {
                        "organization_name": "Wakakusa",
                        "project_name": "Pantaray",
                    },
                    "prompt_name": "suggestion/main",
                    "prompt_version": "1.0",
                    "created_at": "2025-01-01T00:00:00Z",
                    "updated_at": "2025-01-01T00:00:05Z",
                    "request_images_count": 1,
                    "used_images_count": 1,
                }
            )

    class FakeAgent:
        def __init__(self) -> None:
            self.repository = FakeRepository()

    monkeypatch.setattr(
        suggestion_router,
        "_get_suggestion_state_repository",
        AsyncMock(return_value=FakeRepository()),
    )

    response = await suggestion_router.suggestion_state(
        user_id="user-1",
        suggestion_id="sug-1",
        session_id=session_id,
        process_id=process_id,
        last_chunk_index=0,
        suggestion_agent=FakeAgent(),
        resolved_user_id="user-1",
    )

    assert response.streaming_state.status == "streaming"
    assert response.streaming_state.resume_hint is not None
    assert response.streaming_state.resume_hint.next_chunk_index == 2
    assert response.streaming_state.resume_hint.last_cursor == "event-1"
    assert response.streaming_state.resume_hint.kind == "suggestion"
    assert response.streaming_state.pending_chunks
    first_chunk = response.streaming_state.pending_chunks[0]
    assert first_chunk.chunk_index == 1
    assert first_chunk.content == "chunk-1"
    assert response.final_state is not None
    assert response.final_state.status == "processing"
    # thought/thinking はクライアントへ返さない
    assert response.final_state.thinking is None
    assert response.final_state.suggestion_summary == "Action handoff summary"
    assert response.final_state.target_context is not None
    assert response.final_state.target_context.organization_name == "Wakakusa"
    assert response.final_state.target_context.project_name == "Pantaray"


@pytest.mark.asyncio
async def test_suggestion_state_tolerates_unknown_stored_reaction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from pantaray_agents.routers import suggestion as suggestion_router

    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES ('user-1', 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    answer,
                    prompt_text,
                    response_text,
                    prompt_name,
                    prompt_version,
                    has_suggestion,
                    interaction_contract,
                    user_reaction,
                    created_at,
                    updated_at
                ) VALUES ('sug-unknown', 'user-1', 'success', 'answer', 'prompt', 'response', 'suggestion', '1.0', 1, 'action_offer', 'future_value', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """
            )

    repository = LocalSuggestionStateRepository(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )

    class FakeAgent:
        pass

    monkeypatch.setattr(
        suggestion_router,
        "_get_suggestion_state_repository",
        AsyncMock(return_value=repository),
    )

    response = await suggestion_router.suggestion_state(
        user_id="user-1",
        suggestion_id="sug-unknown",
        session_id=None,
        process_id=None,
        last_chunk_index=None,
        suggestion_agent=FakeAgent(),
        resolved_user_id="user-1",
    )

    assert response.final_state is not None
    assert response.final_state.user_reaction is None


@pytest.mark.asyncio
async def test_suggestion_state_uses_session_store_when_db_missing(monkeypatch):
    """DB未保存でも、session store にプロセスがあれば 404 にせず streaming_state を返すこと。"""
    from pantaray_agents.routers import suggestion as suggestion_router

    session_id = "sess-1"
    process_id = "proc-1"

    class DummyChunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class DummyChunkRecord:
        def __init__(self, event_id: str, data: DummyChunk) -> None:
            self.event_id = event_id
            self.data = data

    class DummyProcess:
        def __init__(self) -> None:
            self.next_chunk_index = 1
            self.suggestion_id = "sug-1"
            self.chunks = {0: DummyChunkRecord("event-0", DummyChunk("chunk-0"))}

    class DummySession:
        def __init__(self) -> None:
            self.user_id = "user-1"
            self.processes = {process_id: DummyProcess()}
            self.events = {
                "event-0": {
                    "event": "suggestion_chunk",
                    "process_id": process_id,
                    "chunk_index": 0,
                }
            }

    class DummyStore:
        def __init__(self) -> None:
            self._session = DummySession()

        def get(self, sid: str):
            return self._session if sid == session_id else None

        def iter_missing_chunks(self, sid: str, pid: str, start_index: int):
            if sid != session_id or pid != process_id:
                return []
            # last_chunk_index が未指定なら start_index=0 -> 返す
            if start_index > 0:
                return []
            record = self._session.processes[process_id].chunks[0]
            return [(0, "suggestion_chunk", record.data)]

    monkeypatch.setattr(
        "pantaray_agents.orchestration.router.SESSION_STORE",
        DummyStore(),
        raising=False,
    )

    class FakeRepository:
        async def get_suggestion_state(
            self, *, user_id: str, suggestion_id: str
        ) -> RepositoryResult[dict]:
            assert user_id == "user-1"
            assert suggestion_id == "sug-1"
            return RepositoryResult(data=None, error="No data found")

    class FakeAgent:
        def __init__(self) -> None:
            self.repository = FakeRepository()

    monkeypatch.setattr(
        suggestion_router,
        "_get_suggestion_state_repository",
        AsyncMock(return_value=FakeRepository()),
    )

    response = await suggestion_router.suggestion_state(
        user_id="user-1",
        suggestion_id="sug-1",
        session_id=session_id,
        process_id=process_id,
        last_chunk_index=None,
        suggestion_agent=FakeAgent(),
        resolved_user_id="user-1",
    )

    assert response.streaming_state.status == "streaming"
    assert response.streaming_state.pending_chunks
    assert response.final_state is None


@pytest.mark.asyncio
async def test_suggestion_state_does_not_use_foreign_session(monkeypatch):
    """session_id が別ユーザーのものなら、session store を使わず 404 になること。"""
    from pantaray_agents.routers import suggestion as suggestion_router

    session_id = "sess-foreign"
    process_id = "proc-1"

    class DummyProcess:
        def __init__(self) -> None:
            self.next_chunk_index = 1
            self.suggestion_id = "sug-1"

    class DummySession:
        def __init__(self) -> None:
            self.user_id = "other-user"
            self.processes = {process_id: DummyProcess()}
            self.events = {}

    class DummyStore:
        def get(self, sid: str):
            return DummySession() if sid == session_id else None

        def iter_missing_chunks(self, sid: str, pid: str, start_index: int):
            return []

    monkeypatch.setattr(
        "pantaray_agents.orchestration.router.SESSION_STORE",
        DummyStore(),
        raising=False,
    )

    class FakeRepository:
        async def get_suggestion_state(
            self, *, user_id: str, suggestion_id: str
        ) -> RepositoryResult[dict]:
            return RepositoryResult(data=None, error="No data found")

    class FakeAgent:
        def __init__(self) -> None:
            self.repository = FakeRepository()

    monkeypatch.setattr(
        suggestion_router,
        "_get_suggestion_state_repository",
        AsyncMock(return_value=FakeRepository()),
    )

    with pytest.raises(HTTPException) as exc:
        await suggestion_router.suggestion_state(
            user_id="user-1",
            suggestion_id="sug-1",
            session_id=session_id,
            process_id=process_id,
            last_chunk_index=None,
            suggestion_agent=FakeAgent(),
            resolved_user_id="user-1",
        )

    assert exc.value.status_code == 404
