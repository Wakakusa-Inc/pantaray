from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pantaray_agents.schema.agent.action import ActionAgentResponse
from pantaray_agents.schema.agent.base import StatusType

from .local_action_repository_support import (
    ACTION_ID,
    SUGGESTION_ID,
    USER_ID,
    bootstrap_action_repository_db,
    build_action_repository,
    save_success_action,
)


def _insert_catalog_artifact_head(
    connection: sqlite3.Connection,
    *,
    source_type: str,
    source_record_id: str,
    identity: str,
    created_at: str,
) -> None:
    node_id = f"node-{identity}"
    revision_id = f"revision-{identity}"
    connection.execute(
        """
        INSERT INTO memory_nodes(
            user_id, node_id, source_type, source_record_id, lifecycle,
            integrity, current_revision_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'active', 'healthy', ?, ?, ?)
        """,
        (
            USER_ID,
            node_id,
            source_type,
            source_record_id,
            revision_id,
            created_at,
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO memory_revisions(
            user_id, revision_id, node_id, body_kind, artifact_root_path,
            fragment_schema_version, content_sha256, created_at
        ) VALUES (?, ?, ?, 'artifact_tree', ?, 1, ?, ?)
        """,
        (
            USER_ID,
            revision_id,
            node_id,
            f"memory_catalog/test/{identity}",
            f"sha-{identity}",
            created_at,
        ),
    )
    connection.execute(
        """
        INSERT INTO memory_fragments(
            user_id, fragment_id, revision_id, source_path, block_kind,
            block_index, content_text, content_sha256
        ) VALUES (?, ?, ?, 'index.md', 'document_root', 0, ?, ?)
        """,
        (
            USER_ID,
            f"fragment-{identity}",
            revision_id,
            f"{identity} body",
            f"fragment-sha-{identity}",
        ),
    )


@pytest.mark.asyncio
async def test_local_action_repository_save_action_round_trip(tmp_path: Path) -> None:
    db_path = bootstrap_action_repository_db(tmp_path)
    repo = build_action_repository(db_path)

    await save_success_action(repo)

    action_result = await repo.get_action(user_id=USER_ID, action_id=ACTION_ID)

    assert action_result.error is None
    assert action_result.data is not None
    assert action_result.data["status"] == "success"
    assert action_result.data["final_output"] == "done"
    assert action_result.data["token_budget"] == 120
    assert action_result.data["total_tokens"] == 18
    assert action_result.data["generation"] == 1


@pytest.mark.asyncio
async def test_local_action_repository_rejects_non_positive_token_budget(
    tmp_path: Path,
) -> None:
    db_path = bootstrap_action_repository_db(tmp_path)
    repo = build_action_repository(db_path)

    result = await repo.save_action(
        ActionAgentResponse(
            action_id=ACTION_ID,
            suggestion_id=SUGGESTION_ID,
            user_id=USER_ID,
            final_output="done",
            created_at="2026-03-24T00:10:00Z",
            status=StatusType.SUCCESS,
        ),
        final_prompt_text="final prompt",
        prompt_name="action/executing",
        prompt_version="1.0",
        token_budget=0,
    )

    assert result.data is None
    assert result.error == "token_budget must be a positive integer or null"


@pytest.mark.asyncio
async def test_local_action_repository_memory_source_coverage_snapshot_uses_sqlite_rows(
    tmp_path: Path,
) -> None:
    db_path = bootstrap_action_repository_db(tmp_path)
    repo = build_action_repository(db_path)
    await save_success_action(repo)
    now = datetime.now(UTC)
    created_at = now.isoformat().replace("+00:00", "Z")
    period_end = (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    suggestion_created_at = (
        (now - timedelta(minutes=1))
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO agent_insights(
                    insight_id,
                    user_id,
                    suggestion_id,
                    action_id,
                    status,
                    short_term_insight_data,
                    facts,
                    long_term_insight_sha256,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'success', ?, ?, ?, 'prompt', 'v1', ?, ?)
                """,
                (
                    "ins-1",
                    USER_ID,
                    SUGGESTION_ID,
                    ACTION_ID,
                    "Short insight",
                    "facts",
                    "",
                    created_at,
                    created_at,
                ),
            )
            _insert_catalog_artifact_head(
                connection,
                source_type="long_term_insight",
                source_record_id=USER_ID,
                identity="long-term",
                created_at=created_at,
            )
            _insert_catalog_artifact_head(
                connection,
                source_type="fact",
                source_record_id="fact-1",
                identity="fact",
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO activity_logs(
                    log_id,
                    user_id,
                    period_start,
                    period_end,
                    description,
                    status,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 'success', 'activity', '1.0', ?, ?)
                """,
                (
                    "log-1",
                    USER_ID,
                    (now - timedelta(minutes=25)).isoformat().replace("+00:00", "Z"),
                    period_end,
                    "Needle activity description",
                    period_end,
                    period_end,
                ),
            )
            connection.execute(
                """
                UPDATE agent_suggestions
                SET created_at = ?, updated_at = ?
                WHERE user_id = ? AND suggestion_id = ?
                """,
                (created_at, created_at, USER_ID, SUGGESTION_ID),
            )
            connection.execute(
                """
                UPDATE agent_actions
                SET created_at = ?, updated_at = ?
                WHERE user_id = ? AND action_id = ?
                """,
                (created_at, created_at, USER_ID, ACTION_ID),
            )

        result = await repo.get_memory_source_coverage_snapshot(
            user_id=USER_ID,
            suggestion_created_at=suggestion_created_at,
            max_parallel_queries=2,
        )

    assert result.error is None
    assert result.data is not None
    slots = {slot["source"]: slot for slot in result.data["slots"]}
    assert slots["long_term_insight"]["status"] == "present"
    assert slots["short_term_insight"]["status"] == "present"
    assert slots["facts"]["status"] == "present"
    assert slots["suggestions"]["status"] == "present"
    assert slots["actions"]["status"] == "present"
    assert slots["activity_description"]["status"] == "present"
