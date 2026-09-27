from __future__ import annotations

from datetime import UTC, datetime

from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.schema.websocket.server_messages import CompletionChunkMessage


def _bind_action_process(store: InMemorySessionStore) -> None:
    store.create_session("session-1", user_id="user-1")
    store.ensure_process("session-1", "process-1")
    store.set_process_metadata(
        "session-1",
        "process-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        command_id="command-1",
        kind="action",
    )


def _has_live_action_process(store: InMemorySessionStore) -> bool:
    return store.has_live_action_process(
        user_id="user-1",
        process_id="process-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        command_id="command-1",
    )


def test_live_action_process_ignores_resume_available() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    _bind_action_process(store)

    session = store.get("session-1")
    assert session is not None
    session.processes["process-1"].resume_available = False

    assert _has_live_action_process(store)


def test_live_action_process_ignores_session_created_at() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    _bind_action_process(store)

    session = store.get("session-1")
    assert session is not None
    session.created_at = 0.0

    assert _has_live_action_process(store)


def test_live_action_process_rejects_stale_session_activity() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    _bind_action_process(store)

    session = store.get("session-1")
    assert session is not None
    session.last_seen_at = 1.0

    assert not _has_live_action_process(store)


def test_has_active_session_uses_last_seen_before_created_at() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    store.create_session("session-1", user_id="user-1")

    session = store.get("session-1")
    assert session is not None
    session.created_at = 0.0
    session.last_seen_at = datetime.now(UTC).timestamp()

    assert store.has_active_session("session-1", user_id="user-1")


def test_has_active_session_rejects_stale_activity() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    store.create_session("session-1", user_id="user-1")

    session = store.get("session-1")
    assert session is not None
    session.last_seen_at = 1.0

    assert not store.has_active_session("session-1", user_id="user-1")


def test_live_action_process_requires_action_metadata() -> None:
    store = InMemorySessionStore(max_age_seconds=3600)
    store.create_session("session-1", user_id="user-1")
    store.ensure_process("session-1", "process-1")

    assert not _has_live_action_process(store)


def test_live_action_process_rejects_terminal_lifecycle() -> None:
    store = InMemorySessionStore(max_age_seconds=3600)
    _bind_action_process(store)

    session = store.get("session-1")
    assert session is not None
    session.processes["process-1"].completed_at = 1.0

    assert not _has_live_action_process(store)

    session.processes["process-1"].completed_at = None
    session.processes["process-1"].acknowledged_at = 1.0

    assert not _has_live_action_process(store)


def test_record_event_meta_creates_session_without_creating_process() -> None:
    store = InMemorySessionStore(max_age_seconds=3600)

    store.record_event_meta(
        "session-1",
        "event-1",
        "missing-process",
        None,
        event_name="process_started",
    )

    session = store.get("session-1")
    assert session is not None
    assert session.processes == {}
    assert session.last_seen_at is not None


def test_record_event_meta_touches_session_even_when_event_capacity_is_full() -> None:
    store = InMemorySessionStore(max_age_seconds=3600, max_events_per_session=1)
    store.record_event_meta("session-1", "event-1", None, None, event_name="first")

    session = store.get("session-1")
    assert session is not None
    session.last_seen_at = 1.0

    store.record_event_meta("session-1", "event-2", None, None, event_name="second")

    assert session.last_seen_at is not None
    assert session.last_seen_at > 1.0
    assert "event-2" not in session.events


def test_append_stream_chunk_touches_session_even_when_chunk_capacity_is_full() -> None:
    store = InMemorySessionStore(max_age_seconds=3600, max_chunks_per_process=1)
    store.append_completion_chunk(
        "session-1",
        "process-1",
        "event-1",
        CompletionChunkMessage(content="first"),
    )

    session = store.get("session-1")
    assert session is not None
    session.last_seen_at = 1.0

    store.append_completion_chunk(
        "session-1",
        "process-1",
        "event-2",
        CompletionChunkMessage(content="second"),
    )

    assert session.last_seen_at is not None
    assert session.last_seen_at > 1.0
    assert "event-2" not in session.events


def test_prune_uses_last_seen_at_before_created_at() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    store.create_session("session-1", user_id="user-1")

    session = store.get("session-1")
    assert session is not None
    session.created_at = 0.0
    session.last_seen_at = datetime.now(UTC).timestamp()

    store.prune()

    assert store.get("session-1") is not None


def test_prune_falls_back_to_created_at_when_last_seen_at_is_missing() -> None:
    store = InMemorySessionStore(max_age_seconds=1)
    store.create_session("session-1", user_id="user-1")

    session = store.get("session-1")
    assert session is not None
    session.created_at = 0.0
    session.last_seen_at = None

    store.prune()

    assert store.get("session-1") is None


def test_session_capacity_prunes_oldest_activity() -> None:
    store = InMemorySessionStore(max_age_seconds=3600, max_sessions=2)
    store.create_session("old-active-session", user_id="user-1")
    store.create_session("stale-session", user_id="user-1")

    old_active_session = store.get("old-active-session")
    stale_session = store.get("stale-session")
    assert old_active_session is not None
    assert stale_session is not None
    old_active_session.created_at = 0.0
    old_active_session.last_seen_at = datetime.now(UTC).timestamp()
    stale_session.created_at = 1.0
    stale_session.last_seen_at = 1.0

    store.create_session("new-session", user_id="user-1")

    assert store.get("old-active-session") is not None
    assert store.get("stale-session") is None
    assert store.get("new-session") is not None
