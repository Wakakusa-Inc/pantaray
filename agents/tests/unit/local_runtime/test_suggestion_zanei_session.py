from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

from pantaray_agents.agents.artifact_react import ReactToolCall, ToolCallEnvelope
from pantaray_agents.agents.insight_agent.zanei_tools import (
    MAX_TIMELINE_PAGES_PER_RUN,
    PAGE_TOOL,
)
from pantaray_agents.local_runtime.context import store
from pantaray_agents.local_runtime.context.source_gate import ActiveSource, SourceGate
from pantaray_agents.local_runtime.context.source_protocol import (
    PageReadRequest,
    PageResponse,
)
from pantaray_agents.local_runtime.context.source_reader import ReadTimeout
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.tooling.suggestion_research.zanei import (
    RECORDING_UNAVAILABLE_STATUS,
    SuggestionZaneiSession,
)
from pantaray_agents.schema.context_source import SourceBinding

USER_ID = "user-1"
STORE_ID = "store-1"
BUSY_TIMEOUT_MS = 1_000


def _binding() -> SourceBinding:
    return SourceBinding(
        user_id=USER_ID,
        epoch=UUID(int=1),
        policy_revision="policy-1",
        store_id=STORE_ID,
        protocol_version=1,
    )


def _page(sequence: int, *, has_more: bool) -> PageResponse:
    absent = {"kind": "absent"}
    return PageResponse.model_validate(
        {
            "protocol_version": 1,
            "kind": "page",
            "store_identity": STORE_ID,
            "observations": (
                {
                    "append_sequence": sequence,
                    "id": f"event-{sequence}",
                    "ts": "2026-09-27T17:56:50Z",
                    "source": absent,
                    "event_type": {"kind": "value", "text": "app.terminate"},
                    "bundle_id": {"kind": "value", "text": "com.github.Electron"},
                    "app_name": {"kind": "value", "text": "Electron"},
                    "pid": None,
                    "window_title": absent,
                    "window_id": None,
                },
            ),
            "next_cursor": f"cursor-{sequence}",
            "upper_bound": "upper-1",
            "has_more": has_more,
            "coverage": {"after": sequence - 1, "through": sequence},
        }
    )


@dataclass
class _FakeReader:
    pages: list[object] = field(default_factory=list)
    requests: list[PageReadRequest] = field(default_factory=list)

    async def read_page(self, _source: ActiveSource, request: PageReadRequest):
        self.requests.append(request)
        return self.pages.pop(0)


@dataclass
class _RevokingReader:
    gate: SourceGate

    async def read_page(self, _source: ActiveSource, _request: PageReadRequest):
        # `SourceGate.revoke` drops the permit before it schedules the cancel.
        self.gate.revoke(USER_ID)
        raise asyncio.CancelledError


class _ExternalCancelReader:
    async def read_page(self, _source: ActiveSource, _request: PageReadRequest):
        raise asyncio.CancelledError


def _db_with_cursor(tmp_path: Path, cursor: str) -> Path:
    db_path = tmp_path / "runtime.db"
    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        with immediate_transaction(connection):
            connection.execute(
                "INSERT INTO users(user_id, ui_language, created_at, updated_at) "
                "VALUES (?, 'ja', 'now', 'now')",
                (USER_ID,),
            )
            store.compare_cursor(connection, _binding(), None, cursor)
    return db_path


def _stored_cursor(db_path: Path) -> str | None:
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS
    ) as connection:
        return store.get_cursor(connection, _binding())


def _active_gate() -> SourceGate:
    gate = SourceGate()
    gate.activate(_binding())
    return gate


def _session(
    reader: object, db_path: Path, gate: SourceGate | None = None
) -> SuggestionZaneiSession:
    return SuggestionZaneiSession(
        user_id=USER_ID,
        gate=gate or _active_gate(),
        reader=reader,  # type: ignore[arg-type]
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )


async def _timeline(session: SuggestionZaneiSession):
    (definition,) = (d for d in session.definitions() if d.name == PAGE_TOOL)
    call = ReactToolCall(
        tool_name=PAGE_TOOL,
        tool_args={},
        tool_call_envelope=ToolCallEnvelope(tool_id=PAGE_TOOL, reason=None, args={}),
    )
    return await definition.execute(call, 1)


async def test_the_run_reads_on_from_the_insight_cursor_without_moving_it(
    tmp_path: Path,
) -> None:
    db_path = _db_with_cursor(tmp_path, "cursor-3")
    reader = _FakeReader(pages=[_page(4, has_more=True), _page(5, has_more=False)])
    session = _session(reader, db_path)

    first = await _timeline(session)
    second = await _timeline(session)

    assert first.status == second.status == "success"
    assert [(r.cursor, r.upper_bound) for r in reader.requests] == [
        ("cursor-3", None),
        ("cursor-4", "upper-1"),
    ]
    assert _stored_cursor(db_path) == "cursor-3"


async def test_the_page_budget_spans_every_call_of_the_run(tmp_path: Path) -> None:
    db_path = _db_with_cursor(tmp_path, "cursor-0")
    reader = _FakeReader(
        pages=[
            _page(sequence, has_more=True)
            for sequence in range(1, MAX_TIMELINE_PAGES_PER_RUN + 1)
        ]
    )
    session = _session(reader, db_path)

    results = [await _timeline(session) for _ in range(MAX_TIMELINE_PAGES_PER_RUN + 1)]

    assert len(reader.requests) == MAX_TIMELINE_PAGES_PER_RUN
    assert isinstance(results[-1].output, dict)
    assert results[-1].output["page_budget_spent"] is True


async def test_recording_off_is_unavailable_without_reading(tmp_path: Path) -> None:
    reader = _FakeReader()
    session = _session(reader, _db_with_cursor(tmp_path, "c"), SourceGate())

    result = await _timeline(session)

    assert result.status == "success"
    assert isinstance(result.output, dict)
    assert result.output["status"] == RECORDING_UNAVAILABLE_STATUS
    assert reader.requests == []


async def test_a_revoked_permit_mid_read_is_unavailable_not_a_cancelled_run(
    tmp_path: Path,
) -> None:
    gate = _active_gate()
    session = _session(_RevokingReader(gate), _db_with_cursor(tmp_path, "c"), gate)

    result = await _timeline(session)

    assert isinstance(result.output, dict)
    assert result.output["status"] == RECORDING_UNAVAILABLE_STATUS
    task = asyncio.current_task()
    assert task is not None
    assert task.cancelling() == 0


async def test_cancelling_the_run_itself_still_propagates(tmp_path: Path) -> None:
    session = _session(_ExternalCancelReader(), _db_with_cursor(tmp_path, "c"))

    with pytest.raises(asyncio.CancelledError):
        await _timeline(session)


async def test_a_reader_failure_is_a_tool_error_the_run_can_continue_past(
    tmp_path: Path,
) -> None:
    reader = _FakeReader(pages=[ReadTimeout()])
    session = _session(reader, _db_with_cursor(tmp_path, "c"))

    result = await _timeline(session)

    assert result.status == "error"
