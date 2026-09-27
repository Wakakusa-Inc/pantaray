"""Pure Supervisor / Goal Worker conversation transitions."""

from __future__ import annotations

from typing import Literal

from .models.conversation import (
    GoalCompletionProposalModel,
    GoalConversationStateModel,
    GoalMessageModel,
    GoalWorkerTurnCursorModel,
    MessageDirection,
)

type ConversationRecipient = Literal["supervisor", "worker"]


def _copy_conversation(
    conversation: GoalConversationStateModel,
    *,
    next_sequence: int | None = None,
    next_turn_number: int | None = None,
    supervisor_cursor: int | None = None,
    worker_cursor: int | None = None,
    messages: tuple[GoalMessageModel, ...] | None = None,
    active_turn: GoalWorkerTurnCursorModel | None = None,
    preserve_active_turn: bool = False,
    pending_completion: GoalCompletionProposalModel | None = None,
    preserve_pending_completion: bool = False,
) -> GoalConversationStateModel:
    return GoalConversationStateModel(
        goal_id=conversation.goal_id,
        next_sequence=(
            conversation.next_sequence if next_sequence is None else next_sequence
        ),
        next_turn_number=(
            conversation.next_turn_number
            if next_turn_number is None
            else next_turn_number
        ),
        supervisor_read_through_sequence=(
            conversation.supervisor_read_through_sequence
            if supervisor_cursor is None
            else supervisor_cursor
        ),
        worker_read_through_sequence=(
            conversation.worker_read_through_sequence
            if worker_cursor is None
            else worker_cursor
        ),
        messages=conversation.messages if messages is None else messages,
        active_turn=(conversation.active_turn if preserve_active_turn else active_turn),
        pending_completion=(
            conversation.pending_completion
            if preserve_pending_completion
            else pending_completion
        ),
    )


def append_goal_message(
    conversation: GoalConversationStateModel,
    *,
    message_id: str,
    direction: MessageDirection,
    content: str,
    created_at: str,
) -> GoalConversationStateModel:
    existing = next(
        (
            message
            for message in conversation.messages
            if message.message_id == message_id
        ),
        None,
    )
    if existing is not None:
        if existing.direction == direction and existing.content == content:
            return conversation
        raise ValueError("duplicate message id has different payload")
    message = GoalMessageModel(
        message_id=message_id,
        sequence=conversation.next_sequence,
        direction=direction,
        content=content,
        created_at=created_at,
    )
    return _copy_conversation(
        conversation,
        next_sequence=conversation.next_sequence + 1,
        messages=(*conversation.messages, message),
        preserve_active_turn=True,
        preserve_pending_completion=True,
    )


def start_goal_worker_turn(
    conversation: GoalConversationStateModel,
    *,
    generation: int,
    started_at: str,
    targeted: bool,
) -> GoalConversationStateModel:
    if conversation.active_turn is not None:
        raise ValueError("cannot dispatch a conversation with an active turn")
    if conversation.pending_completion is not None:
        raise ValueError("cannot dispatch while completion review is pending")
    unread_sequences = tuple(
        message.sequence
        for message in conversation.messages
        if message.direction == "supervisor_to_worker"
        and message.sequence > conversation.worker_read_through_sequence
    )
    if targeted and not unread_sequences:
        raise ValueError("targeted dispatch requires an unread Supervisor message")
    if not targeted and (conversation.next_turn_number != 1 or unread_sequences):
        raise ValueError("initial dispatch requires an untouched conversation")
    turn = GoalWorkerTurnCursorModel(
        turn_number=conversation.next_turn_number,
        trigger_sequence=max(unread_sequences) if targeted else None,
        generation=generation,
        status="running",
        started_at=started_at,
    )
    return _copy_conversation(
        conversation,
        next_turn_number=conversation.next_turn_number + 1,
        active_turn=turn,
        preserve_pending_completion=True,
    )


def pause_goal_worker_turn(
    conversation: GoalConversationStateModel,
) -> GoalConversationStateModel:
    turn = conversation.active_turn
    if turn is None or turn.status != "running":
        raise ValueError("approval pause requires a running turn")
    return _copy_conversation(
        conversation,
        active_turn=turn.model_copy(update={"status": "paused"}),
        preserve_pending_completion=True,
    )


def yield_goal_worker_message(
    conversation: GoalConversationStateModel,
    *,
    message_id: str,
    content: str,
    created_at: str,
) -> GoalConversationStateModel:
    if conversation.active_turn is None:
        raise ValueError("Worker message requires an active turn")
    appended = append_goal_message(
        conversation,
        message_id=message_id,
        direction="worker_to_supervisor",
        content=content,
        created_at=created_at,
    )
    return _copy_conversation(
        appended,
        preserve_pending_completion=True,
    )


def submit_goal_completion(
    conversation: GoalConversationStateModel,
    *,
    proposal_id: str,
    output: str,
    submitted_at: str,
) -> GoalConversationStateModel:
    existing = conversation.pending_completion
    if existing is not None:
        if existing.proposal_id == proposal_id and existing.output == output:
            return conversation
        if existing.proposal_id == proposal_id:
            raise ValueError("duplicate proposal id has different payload")
        raise ValueError("another completion proposal is already pending")
    turn = conversation.active_turn
    if turn is None:
        raise ValueError("completion proposal requires an active turn")
    proposal = GoalCompletionProposalModel(
        proposal_id=proposal_id,
        turn_number=turn.turn_number,
        output=output,
        submitted_at=submitted_at,
    )
    return _copy_conversation(conversation, pending_completion=proposal)


def request_goal_revision(
    conversation: GoalConversationStateModel,
    *,
    proposal_id: str,
    review_step_id: str,
    instruction: str,
    created_at: str,
) -> GoalConversationStateModel:
    proposal = conversation.pending_completion
    if proposal is None or proposal.proposal_id != proposal_id:
        raise ValueError("completion proposal is stale or missing")
    cleared = _copy_conversation(conversation)
    return append_goal_message(
        cleared,
        message_id=f"{review_step_id}:instruction",
        direction="supervisor_to_worker",
        content=instruction,
        created_at=created_at,
    )


def accept_goal_completion_review(
    conversation: GoalConversationStateModel,
    *,
    proposal_id: str,
) -> tuple[GoalConversationStateModel, GoalCompletionProposalModel]:
    proposal = conversation.pending_completion
    if proposal is None or proposal.proposal_id != proposal_id:
        raise ValueError("completion proposal is stale or missing")
    return _copy_conversation(conversation), proposal


def drop_goal_conversation(
    conversation: GoalConversationStateModel,
) -> GoalConversationStateModel:
    return _copy_conversation(conversation)


def advance_recipient_cursor(
    conversation: GoalConversationStateModel,
    *,
    recipient: ConversationRecipient,
) -> GoalConversationStateModel:
    direction: MessageDirection = (
        "worker_to_supervisor" if recipient == "supervisor" else "supervisor_to_worker"
    )
    sequences = tuple(
        message.sequence
        for message in conversation.messages
        if message.direction == direction
    )
    if not sequences:
        return conversation
    if recipient == "supervisor":
        return _copy_conversation(
            conversation,
            supervisor_cursor=max(sequences),
            preserve_active_turn=True,
            preserve_pending_completion=True,
        )
    return _copy_conversation(
        conversation,
        worker_cursor=max(sequences),
        preserve_active_turn=True,
        preserve_pending_completion=True,
    )


def advance_all_supervisor_cursors(
    conversations: dict[str, GoalConversationStateModel],
) -> dict[str, GoalConversationStateModel]:
    return {
        goal_id: advance_recipient_cursor(conversation, recipient="supervisor")
        for goal_id, conversation in conversations.items()
    }


__all__ = [
    "ConversationRecipient",
    "accept_goal_completion_review",
    "advance_all_supervisor_cursors",
    "advance_recipient_cursor",
    "append_goal_message",
    "drop_goal_conversation",
    "pause_goal_worker_turn",
    "request_goal_revision",
    "start_goal_worker_turn",
    "submit_goal_completion",
    "yield_goal_worker_message",
]
