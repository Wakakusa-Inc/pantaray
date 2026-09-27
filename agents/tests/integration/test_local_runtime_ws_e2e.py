"""End-to-end: a short Insight's reconsideration reason reaches the live WS."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tests.integration.local_runtime_ws_test_support import (
    TEST_USER_ID,
    LocalRuntimeWsHarness,
    drain_ws_until,
    receive_ws_json,
    ws_connect,
)
from tests.integration.local_runtime_ws_test_support import (
    local_runtime_ws_harness as local_runtime_ws_harness,
)
from tests.integration.local_runtime_ws_test_support import (
    short_runtime_root as short_runtime_root,
)

from pantaray_agents.local_runtime.runtime.job_types import LOCAL_SUGGESTION_JOB_TYPE
from pantaray_agents.local_runtime.runtime.suggestion_from_insight import (
    enqueue_suggestion_for_insight,
    suggestion_id_for_insight,
)
from pantaray_agents.schema.events import OutboundEvent

SHORT_TERM_INSIGHT = "The user is verifying the local runtime end to end."
RECONSIDERATION_REASON = "The verification stalled on the WebSocket relay."


def _commit_reconsidered_short_insight(db_path: Path, *, user_id: str) -> str:
    """Commit the short Insight exactly as the runtime's Insight run does."""
    insight_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(db_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO agent_insights(insight_id, user_id, status,
               short_term_insight_data, facts, reconsideration_reason, prompt_name,
               prompt_version, created_at, updated_at)
               VALUES (?, ?, 'success', ?, '', ?, 'insight', '1.0', ?, ?)""",
            (
                insight_id,
                user_id,
                SHORT_TERM_INSIGHT,
                RECONSIDERATION_REASON,
                now,
                now,
            ),
        )
        enqueue_suggestion_for_insight(
            connection=connection,
            user_id=user_id,
            insight_id=insight_id,
            now=now,
        )
        connection.commit()
    return insight_id


def _count_unfinished_suggestion_jobs(db_path: Path) -> int:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM jobs
            WHERE job_type = ?
              AND status IN ('queued', 'running')
            """,
            (LOCAL_SUGGESTION_JOB_TYPE,),
        ).fetchone()
    return int(row[0])


def test_runtime_suggestion_is_relayed_once_to_the_live_session(
    local_runtime_ws_harness: LocalRuntimeWsHarness,
) -> None:
    with ws_connect(local_runtime_ws_harness.client, user_id=TEST_USER_ID) as ws:
        session_started = receive_ws_json(ws, timeout_s=2.0)
        assert session_started["event"] == OutboundEvent.SESSION_STARTED.value

        insight_id = _commit_reconsidered_short_insight(
            local_runtime_ws_harness.db_path,
            user_id=TEST_USER_ID,
        )
        messages = drain_ws_until(
            ws,
            stop_events={OutboundEvent.PROCESS_COMPLETED.value},
            timeout_s=20.0,
        )
        try:
            messages.append(receive_ws_json(ws, timeout_s=1.0))
        except TimeoutError:
            pass

    suggestion_id = suggestion_id_for_insight(insight_id)
    event_names = [str(message.get("event")) for message in messages]
    assert event_names.count(OutboundEvent.PROCESS_STARTED.value) == 1
    assert event_names.count(OutboundEvent.SUGGESTION_CHUNK.value) == 1
    assert event_names.count(OutboundEvent.PROCESS_COMPLETED.value) == 1

    started = next(
        message
        for message in messages
        if message["event"] == OutboundEvent.PROCESS_STARTED.value
    )
    assert started["data"]["suggestion_id"] == suggestion_id
    chunk = next(
        message
        for message in messages
        if message["event"] == OutboundEvent.SUGGESTION_CHUNK.value
    )
    assert (
        chunk["data"]["content"] == "Continue the focused local runtime verification."
    )
    completed = next(
        message
        for message in messages
        if message["event"] == OutboundEvent.PROCESS_COMPLETED.value
    )
    assert completed["data"]["status"] == "success"
    assert completed["data"]["suggestion_id"] == suggestion_id
    assert completed["data"]["interaction_contract"] == "action_offer"

    stored = next(
        row
        for row in local_runtime_ws_harness.suggestion_repository.data["suggestions"]
        if str(row.get("suggestion_id") or "") == suggestion_id
    )
    assert str(stored.get("status") or "") == "success"
    assert _count_unfinished_suggestion_jobs(local_runtime_ws_harness.db_path) == 0
