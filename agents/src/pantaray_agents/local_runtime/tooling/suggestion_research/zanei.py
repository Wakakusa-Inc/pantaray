"""Computer activity recorded after the Insight a Suggestion run decides on.

The reads belong to ``insight_agent.zanei_tools.ZaneiTools``. This session only
opens one per run, starting at the stream cursor the short Insight committed, so
the run sees what happened after the observations in its prompt. It reads that
cursor and never writes it: the position stays owned by the short Insight.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.agents.artifact_react import (
    ReactToolCall,
    ReactToolDefinition,
    ReactToolResult,
    tool_error_response,
)
from pantaray_agents.agents.insight_agent.zanei_tools import (
    EVENT_REQUEST_SCHEMA,
    EVENT_TOOL,
    MAX_TIMELINE_PAGES_PER_RUN,
    PAGE_REQUEST_SCHEMA,
    PAGE_TOOL,
    ZaneiTools,
)
from pantaray_agents.local_runtime.context import store
from pantaray_agents.local_runtime.context.source_gate import (
    SourceGate,
    SourceInvalidated,
)
from pantaray_agents.local_runtime.context.source_reader import SourceReader
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)

RECORDING_UNAVAILABLE_STATUS = "recording_unavailable"
ZANEI_READ_FAILED_ERROR_CODE = "ZANEI_READ_FAILED"


@dataclass(slots=True)
class SuggestionZaneiSession:
    user_id: str
    gate: SourceGate
    reader: SourceReader
    db_path: Path
    busy_timeout_ms: int
    tools: ZaneiTools | None = None

    def definitions(self) -> tuple[ReactToolDefinition, ...]:
        return (
            ReactToolDefinition(
                name=PAGE_TOOL,
                description=(
                    "Read the computer activity recorded after the latest "
                    "short-term Insight's observations, oldest first, up to the "
                    "first call. Each events row follows event_columns; "
                    "context_index selects the page-local contexts entry. The "
                    "host keeps the cursor; call again while has_more is true, "
                    "because the newest events come last. No events with "
                    "has_more false means nothing was recorded since. A run may "
                    f"read at most {MAX_TIMELINE_PAGES_PER_RUN} pages, and fewer "
                    "when they are large; once a result reports "
                    "page_budget_spent, decide with what you read."
                ),
                request_schema=PAGE_REQUEST_SCHEMA,
                response_schema={"type": "object"},
                execute=self._timeline,
            ),
            ReactToolDefinition(
                name=EVENT_TOOL,
                description=(
                    "Read one field of an event returned by zanei_timeline. "
                    "Use text for captured/copied text, element_value for AX "
                    "values, url for browser location. start is a UTF-8 byte "
                    "offset; use next_start to continue truncated text."
                ),
                request_schema=EVENT_REQUEST_SCHEMA,
                response_schema={"type": "object"},
                execute=self._query,
            ),
        )

    async def _timeline(self, call: ReactToolCall, step: int) -> ReactToolResult:
        return await self._read(call, step, timeline=True)

    async def _query(self, call: ReactToolCall, step: int) -> ReactToolResult:
        return await self._read(call, step, timeline=False)

    async def _read(
        self, call: ReactToolCall, step: int, *, timeline: bool
    ) -> ReactToolResult:
        # One session per run, so the page budget and cursor span every call.
        if self.tools is None:
            self.tools = await self._open()
            if self.tools is None:
                return _unavailable(call)
        tools = self.tools
        try:
            if timeline:
                return await tools.timeline(call, step)
            return await tools.query(call, step)
        except asyncio.CancelledError:
            # `SourceGate.revoke` drops the permit before it cancels the
            # in-flight read. A permit that still matches means the run itself
            # was cancelled, which must propagate.
            if self.gate.current(self.user_id) == tools.source:
                raise
            task = asyncio.current_task()
            assert task is not None  # A coroutine driven by asyncio.run runs in a Task.
            task.uncancel()
            return _unavailable(call)
        except SourceInvalidated:
            # Revoked between two calls; the reader rejects the stale permit.
            return _unavailable(call)
        except RuntimeError as exc:
            # ZaneiTools raises this for a reader transport or protocol failure.
            # The run decides without this evidence instead of failing.
            return tool_error_response(
                tool_name=call.tool_name,
                error_code=ZANEI_READ_FAILED_ERROR_CODE,
                message=str(exc),
            )

    async def _open(self) -> ZaneiTools | None:
        async with self.gate.turn():
            source = self.gate.current(self.user_id)
        if source is None:
            return None
        with open_memory_catalog_connection(
            db_path=self.db_path, busy_timeout_ms=self.busy_timeout_ms
        ) as connection:
            cursor = store.get_cursor(connection, source.binding)
        return ZaneiTools(
            reader=self.reader,
            source=source,
            cursor=cursor,
            upper_bound=None,
        )


def _unavailable(call: ReactToolCall) -> ReactToolResult:
    return ReactToolResult(
        tool_name=call.tool_name,
        status="success",
        output={
            "status": RECORDING_UNAVAILABLE_STATUS,
            "message": (
                "Computer activity recording is not available, so activity after "
                "the Insight cannot be checked."
            ),
        },
    )


__all__ = ["RECORDING_UNAVAILABLE_STATUS", "SuggestionZaneiSession"]
