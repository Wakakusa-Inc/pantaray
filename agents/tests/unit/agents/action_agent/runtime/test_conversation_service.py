from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.agents.action_agent.runtime.conversation_service import (
    accept_goal_completion_review,
    advance_all_supervisor_cursors,
    advance_recipient_cursor,
    append_goal_message,
    drop_goal_conversation,
    request_goal_revision,
    start_goal_worker_turn,
    submit_goal_completion,
    yield_goal_worker_message,
)
from pantaray_agents.agents.action_agent.runtime.models.conversation import (
    GoalConversationStateModel,
    GoalMessageModel,
)

NOW = "2026-07-18T00:00:00+00:00"


def _conversation() -> GoalConversationStateModel:
    return GoalConversationStateModel(goal_id="G1")


def test_append_message_assigns_conversation_sequence_without_mutating_input() -> None:
    original = _conversation()

    updated = append_goal_message(
        original,
        message_id="step-1",
        direction="supervisor_to_worker",
        content="根拠を追加してください。",
        created_at=NOW,
    )

    assert original.messages == ()
    assert updated.next_sequence == 2
    assert updated.messages[0].sequence == 1
    assert updated.messages[0].direction == "supervisor_to_worker"


def test_duplicate_message_id_ignores_retry_timestamp_for_same_command() -> None:
    first = append_goal_message(
        _conversation(),
        message_id="step-1",
        direction="supervisor_to_worker",
        content="確認してください。",
        created_at=NOW,
    )

    assert (
        append_goal_message(
            first,
            message_id="step-1",
            direction="supervisor_to_worker",
            content="確認してください。",
            created_at="2026-07-18T00:00:01+00:00",
        )
        == first
    )
    with pytest.raises(ValueError, match="different payload"):
        append_goal_message(
            first,
            message_id="step-1",
            direction="supervisor_to_worker",
            content="別の指示です。",
            created_at=NOW,
        )


def test_completion_proposal_retry_is_idempotent_for_same_command() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=1, started_at=NOW, targeted=False
    )
    pending = submit_goal_completion(
        running,
        proposal_id="step-3",
        output="成果物",
        submitted_at=NOW,
    )

    retried = submit_goal_completion(
        pending,
        proposal_id="step-3",
        output="成果物",
        submitted_at="2026-07-18T00:00:01+00:00",
    )

    assert retried == pending
    with pytest.raises(ValueError, match="different payload"):
        submit_goal_completion(
            pending,
            proposal_id="step-3",
            output="別の成果物",
            submitted_at=NOW,
        )


def test_targeted_turn_requires_unread_supervisor_message() -> None:
    conversation = append_goal_message(
        _conversation(),
        message_id="step-1",
        direction="supervisor_to_worker",
        content="修正してください。",
        created_at=NOW,
    )

    running = start_goal_worker_turn(
        conversation,
        generation=3,
        started_at=NOW,
        targeted=True,
    )

    assert running.active_turn is not None
    assert running.active_turn.turn_number == 1
    assert running.active_turn.trigger_sequence == 1
    assert running.next_turn_number == 2
    with pytest.raises(ValueError, match="active turn"):
        start_goal_worker_turn(
            running,
            generation=4,
            started_at=NOW,
            targeted=True,
        )


def test_worker_message_yields_turn_and_preserves_goal_open_state() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=1, started_at=NOW, targeted=False
    )

    yielded = yield_goal_worker_message(
        running,
        message_id="step-2",
        content="選択基準が必要です。",
        created_at=NOW,
    )

    assert yielded.active_turn is None
    assert yielded.pending_completion is None
    assert yielded.messages[-1].direction == "worker_to_supervisor"


def test_completion_revision_reuses_same_conversation() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=1, started_at=NOW, targeted=False
    )
    pending = submit_goal_completion(
        running,
        proposal_id="step-3",
        output="成果物",
        submitted_at=NOW,
    )

    assert pending.active_turn is None
    assert pending.pending_completion is not None
    revised = request_goal_revision(
        pending,
        proposal_id="step-3",
        review_step_id="step-4",
        instruction="根拠を追加してください。",
        created_at=NOW,
    )

    assert revised.pending_completion is None
    assert revised.messages[-1].message_id == "step-4:instruction"
    assert revised.messages[-1].direction == "supervisor_to_worker"


def test_completion_accept_returns_output_and_clears_proposal() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=1, started_at=NOW, targeted=False
    )
    pending = submit_goal_completion(
        running,
        proposal_id="step-3",
        output="成果物",
        submitted_at=NOW,
    )

    accepted, proposal = accept_goal_completion_review(pending, proposal_id="step-3")

    assert accepted.pending_completion is None
    assert proposal.output == "成果物"


def test_active_turn_must_be_latest_turn() -> None:
    with pytest.raises(ValueError, match="latest Worker turn"):
        GoalConversationStateModel(
            goal_id="G1",
            next_turn_number=3,
            active_turn={
                "turn_number": 1,
                "trigger_sequence": None,
                "generation": 1,
                "status": "running",
                "started_at": "2026-07-18T00:00:00Z",
            },
        )


def test_targeted_turn_trigger_must_reference_supervisor_message() -> None:
    with pytest.raises(ValueError, match="Supervisor message"):
        GoalConversationStateModel(
            goal_id="G1",
            next_sequence=2,
            next_turn_number=2,
            messages=(
                {
                    "message_id": "worker-message",
                    "sequence": 1,
                    "direction": "worker_to_supervisor",
                    "content": "report",
                    "created_at": "2026-07-18T00:00:00Z",
                },
            ),
            active_turn={
                "turn_number": 1,
                "trigger_sequence": 1,
                "generation": 1,
                "status": "running",
                "started_at": "2026-07-18T00:00:01Z",
            },
        )


def test_drop_clears_active_turn_and_pending_proposal() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=4, started_at=NOW, targeted=False
    )
    pending = submit_goal_completion(
        running,
        proposal_id="p1",
        output="result",
        submitted_at=NOW,
    )

    dropped = drop_goal_conversation(pending)

    assert dropped.active_turn is None
    assert dropped.pending_completion is None


def test_cursor_advances_only_for_recipient_direction() -> None:
    conversation = append_goal_message(
        _conversation(),
        message_id="s1",
        direction="supervisor_to_worker",
        content="指示",
        created_at=NOW,
    )
    conversation = append_goal_message(
        conversation,
        message_id="w1",
        direction="worker_to_supervisor",
        content="報告",
        created_at=NOW,
    )

    worker_read = advance_recipient_cursor(conversation, recipient="worker")
    assert worker_read.worker_read_through_sequence == 1
    assert worker_read.supervisor_read_through_sequence == 0
    supervisor_read = advance_recipient_cursor(worker_read, recipient="supervisor")
    assert supervisor_read.supervisor_read_through_sequence == 2


def test_conversation_rejects_cursor_for_the_wrong_direction() -> None:
    with pytest.raises(ValidationError, match="supervisor cursor exceeds Worker"):
        GoalConversationStateModel(
            goal_id="G1",
            next_sequence=2,
            supervisor_read_through_sequence=1,
            messages=(
                GoalMessageModel(
                    message_id="s1",
                    sequence=1,
                    direction="supervisor_to_worker",
                    content="指示",
                    created_at=NOW,
                ),
            ),
        )


def test_conversation_rejects_proposal_from_an_older_turn() -> None:
    running = start_goal_worker_turn(
        _conversation(), generation=1, started_at=NOW, targeted=False
    )
    pending = submit_goal_completion(
        running,
        proposal_id="p1",
        output="result",
        submitted_at=NOW,
    )

    payload = pending.model_dump()
    payload["next_turn_number"] = pending.next_turn_number + 1
    with pytest.raises(ValidationError, match="latest Worker turn"):
        GoalConversationStateModel.model_validate(payload)


def test_supervisor_command_advances_all_worker_message_cursors() -> None:
    first = append_goal_message(
        GoalConversationStateModel(goal_id="G1"),
        message_id="w1",
        direction="worker_to_supervisor",
        content="報告1",
        created_at=NOW,
    )
    second = append_goal_message(
        GoalConversationStateModel(goal_id="G2"),
        message_id="w2",
        direction="worker_to_supervisor",
        content="報告2",
        created_at=NOW,
    )

    advanced = advance_all_supervisor_cursors({"G1": first, "G2": second})

    assert advanced["G1"].supervisor_read_through_sequence == 1
    assert advanced["G2"].supervisor_read_through_sequence == 1


def test_conversation_model_rejects_non_monotonic_sequence() -> None:
    with pytest.raises(ValidationError):
        GoalConversationStateModel(
            goal_id="G1",
            next_sequence=2,
            messages=(
                GoalMessageModel(
                    message_id="m1",
                    sequence=2,
                    direction="supervisor_to_worker",
                    content="invalid",
                    created_at=NOW,
                ),
            ),
        )
