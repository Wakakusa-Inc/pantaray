"""One unified Memory run from a pending trigger to its published heads."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from pantaray_agents.agents.artifact_react import (
    ReactLoopResult,
    ReactToolCall,
    ReactToolDefinition,
    ToolCallEnvelope,
)
from pantaray_agents.agents.memory_agent import MemoryUpdateAgentResult
from pantaray_agents.local_runtime.memory_catalog.agent_experience_content import (
    AgentExperienceContent,
    AgentExperienceScope,
    experience_entry_path,
    render_agent_experience_markdown,
)
from pantaray_agents.local_runtime.memory_catalog.memory_run_binding import (
    derived_experience_ids,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemorySource
from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.job_claim import claim_next_pending_job
from pantaray_agents.local_runtime.runtime.job_control import DeferredLocalJob
from pantaray_agents.local_runtime.runtime.job_payload_models import (
    parse_memory_update_job_payload_json,
)
from pantaray_agents.local_runtime.runtime.job_route_identity import (
    bind_job_route_identity,
)
from pantaray_agents.local_runtime.runtime.job_types import (
    LOCAL_MEMORY_UPDATE_JOB_TYPE,
)
from pantaray_agents.local_runtime.runtime.memory_agent_dispatcher import (
    dispatch_memory_agent_triggers_once,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    import_desktop_session,
    mark_configured,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.local_runtime.tooling.memory_file_editor import (
    LocalMemoryFileEditorRuntime,
)
from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.agent.memory_update import MemoryUpdateContext
from pantaray_agents.tasks.internal_jobs.memory_update import (
    MemoryUpdateWorkerAgent,
    execute_memory_update_job,
)
from pantaray_agents.tasks.types import MemoryUpdateJobPayload

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
TRIGGER_AT = "2026-01-05T00:00:00Z"
DISPATCH_AT = datetime(2026, 1, 5, 1, 0, tzinfo=UTC)


class _ScriptedMemoryAgent:
    """Writes one file per category through the run's own editor tools."""

    def __init__(self, edits: tuple[tuple[str, str], ...]) -> None:
        self._edits = edits
        self.briefs: list[MemorySource] = []

    async def update(
        self,
        context: MemoryUpdateContext,
        *,
        tool_definitions: tuple[ReactToolDefinition, ...],
        tool_result_directory_fd: int,
    ) -> MemoryUpdateAgentResult:
        del tool_result_directory_fd
        write = next(item for item in tool_definitions if item.name == "write_file")
        draft_revision = context.draft_revision
        for step, (path, content) in enumerate(self._edits, start=1):
            args: dict[str, JSONValue] = {
                "path": path,
                "text": content,
                "expected_draft_revision": draft_revision,
            }
            result = await write.execute(
                ReactToolCall(
                    tool_name="write_file",
                    tool_args=args,
                    tool_call_envelope=ToolCallEnvelope(
                        tool_id="write_file", reason=None, args=args
                    ),
                ),
                step,
            )
            assert result.status == "success", result.output
            assert isinstance(result.output, dict)
            draft_revision = str(result.output["draft_revision"])
        return MemoryUpdateAgentResult(
            loop_result=ReactLoopResult(
                status="success",
                final_text="done",
                steps=(),
            )
        )

    async def generate_profile_brief(
        self, source: MemorySource, memory_text: str
    ) -> str:
        self.briefs.append(source)
        return f"## Profile Brief\n- {source}: {memory_text[:20]}"


def _bootstrap(tmp_path: Path) -> LocalMemoryFileEditorRuntime:
    runtime = LocalMemoryFileEditorRuntime(
        artifact_root=tmp_path / "artifacts",
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )
    apply_migrations(
        db_path=runtime.db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    import_desktop_session(
        db_path=runtime.db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=USER_ID,
        desktop_access_token="header.payload.signature",
        expires_at="2099-08-16T00:00:00Z",
        session_version="1",
    )
    with sqlite3.connect(runtime.db_path) as connection:
        with immediate_transaction(connection):
            connection.execute(
                """
                INSERT INTO activity_summaries(
                    summary_id, user_id, summary_type, period_start, period_end,
                    summary, status, prompt_name, prompt_version,
                    created_at, updated_at
                ) VALUES ('summary-1', ?, '24h', '2026-01-04T00:00:00Z', ?,
                          'Shipped the unified memory run.', 'success',
                          'activity_summary', '1.0', ?, ?)
                """,
                (USER_ID, TRIGGER_AT, TRIGGER_AT, TRIGGER_AT),
            )
            connection.execute(
                """
                INSERT INTO memory_agent_triggers(
                    user_id, trigger_kind, source_id, status, created_at
                ) VALUES (?, 'memory_from_24h_summary', 'summary-1', 'pending', ?)
                """,
                (USER_ID, TRIGGER_AT),
            )
    return runtime


def _claimed_payload(runtime: LocalMemoryFileEditorRuntime) -> MemoryUpdateJobPayload:
    dispatch_memory_agent_triggers_once(
        db_path=runtime.db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=USER_ID,
        now=DISPATCH_AT,
    )
    claimed = claim_next_pending_job(
        db_path=str(runtime.db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        job_type=LOCAL_MEMORY_UPDATE_JOB_TYPE,
        owner_user_id=USER_ID,
        claimed_by="worker-1",
        process_running_status="running",
        expected_process_pending_status="enqueued",
    )
    assert claimed is not None
    return parse_memory_update_job_payload_json(claimed["payload_json"])


@pytest.mark.asyncio
async def test_a_due_trigger_runs_the_agent_and_publishes_every_touched_category(
    tmp_path: Path,
) -> None:
    runtime = _bootstrap(tmp_path)
    payload = _claimed_payload(runtime)
    assert payload["summary_ids"] == ["summary-1"]
    experience_id = derived_experience_ids(payload["job_id"])[0]
    agent = _ScriptedMemoryAgent(
        (
            ("facts/tooling.md", "# Tooling\n\n- Ships memory runs.\n"),
            ("insights/patterns.md", "# Patterns\n\n- Values one run per user.\n"),
            (
                experience_entry_path(experience_id),
                render_agent_experience_markdown(
                    _experience_content(experience_id),
                ),
            ),
        )
    )

    await execute_memory_update_job(
        payload=payload,
        runtime=runtime,
        build_agent=_builder(agent),
    )

    with sqlite3.connect(runtime.db_path) as connection:
        heads = connection.execute(
            """
            SELECT nodes.source_type, nodes.lifecycle,
                   revisions.profile_brief IS NOT NULL
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.revision_id = nodes.current_revision_id
            ORDER BY nodes.source_type
            """
        ).fetchall()
        completed = connection.execute(
            """
            SELECT payload_json FROM process_events
            WHERE process_id = ? AND event_name = 'memory_update_completed'
            """,
            (payload["process_id"],),
        ).fetchall()

    assert heads == [
        ("agent_experience", "active", 0),
        ("fact", "active", 1),
        ("long_term_insight", "active", 1),
    ]
    assert agent.briefs == ["fact", "long_term_insight"]
    assert len(completed) == 1
    assert json.loads(str(completed[0][0])) == {
        "published_sources": ["agent_experience", "fact", "long_term_insight"]
    }


def _experience_content(experience_id: str) -> AgentExperienceContent:
    return AgentExperienceContent(
        experience_id=experience_id,
        scope=AgentExperienceScope(kind="user", key=None),
        applies_when="A memory run touches several categories.",
        observed_approach="Published each category in its own transaction.",
        outcome="effective",
        next_time_rule="Record every activation before the next category starts.",
        observed_result="A rerun skipped the category that already landed.",
        supersedes_experience_id=None,
    )


def _builder(agent: MemoryUpdateWorkerAgent) -> object:
    async def build() -> MemoryUpdateWorkerAgent:
        return agent

    return build


class _AgentThatReplacesTheRoute:
    """Ends its run on a different account than it started on."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    async def update(
        self,
        context: MemoryUpdateContext,
        *,
        tool_definitions: tuple[ReactToolDefinition, ...],
        tool_result_directory_fd: int,
    ) -> MemoryUpdateAgentResult:
        del context, tool_definitions, tool_result_directory_fd
        # A second sign-in of the same account is a new cloud identity.
        import_desktop_session(
            db_path=self._db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            user_id=USER_ID,
            desktop_access_token="header.payload.signature",
            expires_at="2099-08-16T00:00:00Z",
            session_version="2",
        )
        return MemoryUpdateAgentResult(
            loop_result=ReactLoopResult(status="success", final_text="done", steps=())
        )

    async def generate_profile_brief(
        self, source: MemorySource, memory_text: str
    ) -> str:
        del source, memory_text
        raise AssertionError("a replaced route must not reach publication")


@pytest.mark.asyncio
async def test_a_run_that_ends_on_a_replaced_route_publishes_no_memory(
    tmp_path: Path,
) -> None:
    """Every edit stays in the run-only workspace and the job starts over."""
    runtime = _bootstrap(tmp_path)
    payload = _claimed_payload(runtime)
    register_logged_out_owner("local-owner")
    mark_configured()

    try:
        with bind_job_route_identity(
            job_id=payload["job_id"],
            process_id=payload["process_id"],
            process_pending_status="enqueued",
            db_path=runtime.db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            requeue_on_change=True,
        ):
            with pytest.raises(DeferredLocalJob):
                await execute_memory_update_job(
                    payload=payload,
                    runtime=runtime,
                    build_agent=_builder(_AgentThatReplacesTheRoute(runtime.db_path)),
                )
    finally:
        reset_logged_out_owner()

    with sqlite3.connect(runtime.db_path) as connection:
        heads = connection.execute(
            """
            SELECT nodes.source_type
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.revision_id = nodes.current_revision_id
            """
        ).fetchall()
        completed = connection.execute(
            """
            SELECT COUNT(*) FROM process_events
            WHERE process_id = ? AND event_name = 'memory_update_completed'
            """,
            (payload["process_id"],),
        ).fetchone()
        job_row = connection.execute(
            "SELECT status, claimed_by FROM jobs WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()
    assert heads == []
    assert completed == (0,)
    assert job_row == ("queued", None)
