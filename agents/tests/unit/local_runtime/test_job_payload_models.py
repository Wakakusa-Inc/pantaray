from __future__ import annotations

import json

import pytest

from pantaray_agents.local_runtime.runtime.job_claim import ClaimedLocalJob
from pantaray_agents.local_runtime.runtime.job_dispatch import (
    LocalJobHandler,
    dispatch_claimed_job,
)
from pantaray_agents.local_runtime.runtime.job_payload_builder import (
    build_action_job_payload,
    build_memory_update_job_payload,
)
from pantaray_agents.local_runtime.runtime.job_payload_models import (
    parse_action_job_payload_json,
    parse_activity_summary_job_payload_json,
    parse_insight_job_payload_json,
    parse_memory_update_job_payload_json,
    parse_suggestion_job_payload_json,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.tasks.types import ActionContinuationRef


def test_parse_action_job_payload_json_validates_required_fields() -> None:
    payload = parse_action_job_payload_json(
        json.dumps(
            {
                "job_id": "job-1",
                "process_id": "process-1",
                "action_id": "action-1",
                "user_id": "user-1",
                "continuation_ref": {
                    "kind": "user_step",
                    "user_step_id": "step-1",
                },
            }
        )
    )

    assert payload["job_id"] == "job-1"
    assert payload["action_id"] == "action-1"
    assert payload["continuation_ref"] == {
        "kind": "user_step",
        "user_step_id": "step-1",
    }


@pytest.mark.parametrize(
    "continuation_ref",
    (
        {"kind": "user_step", "user_step_id": "step-1"},
        {
            "kind": "tool_approval",
            "approval_session_id": "approval-1",
            "tool_request_id": "tool-request-1",
        },
    ),
)
def test_action_job_payload_continuation_ref_round_trip(
    continuation_ref: ActionContinuationRef,
) -> None:
    payload = build_action_job_payload(
        {
            "job_id": "job-1",
            "process_id": "process-1",
            "action_id": "action-1",
            "user_id": "user-1",
            "continuation_ref": continuation_ref,
        }
    )

    assert parse_action_job_payload_json(json.dumps(payload)) == payload


@pytest.mark.parametrize(
    ("continuation_ref", "error_pattern"),
    (
        ({"user_step_id": "step-1"}, "non-empty string: kind"),
        ({"kind": "unknown", "user_step_id": "step-1"}, "unsupported.*kind"),
        ({"kind": "user_step"}, "non-empty string: user_step_id"),
        (
            {
                "kind": "user_step",
                "user_step_id": "step-1",
                "approval_session_id": "approval-1",
            },
            "unexpected fields: approval_session_id",
        ),
        (
            {"kind": "tool_approval", "approval_session_id": "approval-1"},
            "non-empty string: tool_request_id",
        ),
        (
            {
                "kind": "tool_approval",
                "approval_session_id": "approval-1",
                "tool_request_id": "tool-request-1",
                "user_step_id": "step-1",
            },
            "unexpected fields: user_step_id",
        ),
    ),
)
def test_parse_action_job_payload_rejects_invalid_continuation_ref(
    continuation_ref: dict[str, str],
    error_pattern: str,
) -> None:
    with pytest.raises(MigrationError, match=error_pattern):
        parse_action_job_payload_json(
            json.dumps(
                {
                    "job_id": "job-1",
                    "process_id": "process-1",
                    "action_id": "action-1",
                    "user_id": "user-1",
                    "continuation_ref": continuation_ref,
                }
            )
        )


def test_parse_action_job_payload_json_rejects_deprecated_content_transport() -> None:
    with pytest.raises(MigrationError, match="unexpected fields: screen_captures"):
        parse_action_job_payload_json(
            json.dumps(
                {
                    "job_id": "job-1",
                    "process_id": "process-1",
                    "action_id": "action-1",
                    "user_id": "user-1",
                    "continuation_ref": {
                        "kind": "user_step",
                        "user_step_id": "step-1",
                    },
                    "screen_captures": [],
                }
            )
        )


def test_dispatch_claimed_job_routes_by_job_type() -> None:
    claimed_job: ClaimedLocalJob = {
        "job_id": "job-1",
        "job_type": "execute_action",
        "process_id": "process-1",
        "claimed_by": "worker-1",
        "payload_json": json.dumps(
            {
                "job_id": "job-1",
                "process_id": "process-1",
                "action_id": "action-1",
                "user_id": "user-1",
                "continuation_ref": {
                    "kind": "user_step",
                    "user_step_id": "step-1",
                },
            }
        ),
    }
    observed: list[str] = []

    dispatch_claimed_job(
        claimed_job=claimed_job,
        handlers={
            "execute_action": LocalJobHandler(
                parse_payload=parse_action_job_payload_json,
                run=lambda payload: observed.append(payload["job_id"]),
            )
        },
    )

    assert observed == ["job-1"]


def test_parse_suggestion_job_payload_json_validates_required_fields() -> None:
    payload = parse_suggestion_job_payload_json(
        json.dumps(
            {
                "job_id": "job-2",
                "process_id": "process-2",
                "suggestion_id": "suggestion-2",
                "user_id": "user-2",
                "enqueued_at": "2026-03-27T00:00:02Z",
                "insight_id": "insight-2",
            }
        )
    )

    assert payload["job_id"] == "job-2"
    assert payload["suggestion_id"] == "suggestion-2"
    assert payload["enqueued_at"] == "2026-03-27T00:00:02Z"
    assert payload["insight_id"] == "insight-2"
    assert "screen_captures" not in payload


def test_parse_suggestion_job_payload_json_rejects_a_missing_insight_id() -> None:
    """The short Insight is the only Suggestion trigger, so its id is required."""
    with pytest.raises(MigrationError, match="insight_id"):
        parse_suggestion_job_payload_json(
            json.dumps(
                {
                    "job_id": "job-2",
                    "process_id": "process-2",
                    "suggestion_id": "suggestion-2",
                    "user_id": "user-2",
                    "enqueued_at": "2026-03-27T00:00:02Z",
                }
            )
        )


def test_parse_activity_summary_job_payload_json_validates_required_fields() -> None:
    payload = parse_activity_summary_job_payload_json(
        json.dumps(
            {
                "job_id": "job-activity-summary-1",
                "process_id": "process-activity-summary-1",
                "summary_id": "summary-1",
                "user_id": "user-1",
                "enqueued_at": "2026-03-27T00:00:03Z",
                "summary_type": "24h",
                "period_start": "2026-03-26T00:00:00Z",
                "period_end": "2026-03-27T00:00:00Z",
                "trigger_fact_structuring_after_success": True,
            }
        )
    )

    assert payload["summary_id"] == "summary-1"
    assert "trigger_fact_structuring_after_success" not in payload


def test_parse_insight_job_payload_json_keeps_only_the_run_window() -> None:
    payload = parse_insight_job_payload_json(
        json.dumps(
            {
                "job_id": "job-4",
                "process_id": "process-4",
                "insight_id": "insight-4",
                "user_id": "user-4",
                "period_start": "2026-03-27T00:00:00Z",
                "period_end": "2026-03-27T00:04:00Z",
                "source_activity_summary_id": "retired",
                "enqueued_at": "2026-03-27T00:00:04Z",
            }
        )
    )

    assert payload["insight_id"] == "insight-4"
    assert payload["period_start"] == "2026-03-27T00:00:00Z"
    assert payload["period_end"] == "2026-03-27T00:04:00Z"
    assert "source_activity_summary_id" not in payload


def test_build_memory_update_job_payload_round_trips_every_source() -> None:
    built = build_memory_update_job_payload(
        {
            "job_id": "job-7",
            "process_id": "process-7",
            "user_id": "user-7",
            "enqueued_at": "2026-09-07T00:00:00Z",
            "short_insight_ids": ["insight-1", "insight-2"],
            "summary_ids": ["summary-24h"],
            "action_terminals": [
                {
                    "source_id": "turn-1",
                    "action_id": "action-1",
                    "action_completed_at": "2026-09-06T23:00:00Z",
                    "source_action_revision_id": "revision-1",
                    "turn_start_step_number": 3,
                    "turn_end_step_number": 9,
                    "action_prompt_name": "action",
                    "action_prompt_version": "2.0",
                    "suggestion_id": "suggestion-1",
                }
            ],
        }
    )

    assert parse_memory_update_job_payload_json(json.dumps(built)) == built


def test_parse_memory_update_job_payload_json_rejects_an_empty_batch() -> None:
    with pytest.raises(MigrationError, match="has no source"):
        parse_memory_update_job_payload_json(
            json.dumps(
                {
                    "job_id": "job-8",
                    "process_id": "process-8",
                    "user_id": "user-8",
                    "enqueued_at": "2026-09-07T00:00:00Z",
                    "short_insight_ids": [],
                    "summary_ids": [],
                    "action_terminals": [],
                }
            )
        )


def test_parse_memory_update_job_payload_json_rejects_an_inverted_turn_range() -> None:
    with pytest.raises(MigrationError, match="step range is invalid"):
        parse_memory_update_job_payload_json(
            json.dumps(
                {
                    "job_id": "job-9",
                    "process_id": "process-9",
                    "user_id": "user-9",
                    "enqueued_at": "2026-09-07T00:00:00Z",
                    "short_insight_ids": [],
                    "summary_ids": [],
                    "action_terminals": [
                        {
                            "source_id": "turn-2",
                            "action_id": "action-2",
                            "action_completed_at": "2026-09-06T23:00:00Z",
                            "turn_start_step_number": 9,
                            "turn_end_step_number": 3,
                            "action_prompt_name": "action",
                            "action_prompt_version": "2.0",
                        }
                    ],
                }
            )
        )
