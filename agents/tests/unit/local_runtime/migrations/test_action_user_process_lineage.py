from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.action_process_envelopes import (
    ActionProcessEnvelope,
)
from pantaray_agents.local_runtime.storage.migrations.action_user_process_lineage import (
    ActionUserProcessLineage,
    plan_action_user_process_lineage,
)
from pantaray_agents.local_runtime.storage.migrations.action_user_step_inventory import (
    ActionUserStepEvidence,
)
from pantaray_agents.schema.agent.action_message import (
    ActionUserMessageInput,
    SuggestionApprovalInput,
)
from pantaray_agents.schema.agent.action_message_codec import (
    render_action_user_request_text,
    serialize_action_user_message,
)


def _approval(suggestion_id: str = "suggestion-1") -> SuggestionApprovalInput:
    return SuggestionApprovalInput(
        suggestion_id=suggestion_id,
        approved_at="2026-08-29T00:00:00Z",
    )


def _user(
    step_id: str = "step-1",
    *,
    action_id: str = "action-1",
    user_id: str = "user-1",
    accepted_sequence: int = 1,
    message_id: str = "message-1",
    initial_message_id: str = "message-1",
    suggestion_id: str | None = None,
    approval: SuggestionApprovalInput | None = None,
    content: str = "request",
) -> ActionUserStepEvidence:
    message = ActionUserMessageInput(
        message_id=message_id,
        content=content,
        suggestion_approval=approval,
    )
    return ActionUserStepEvidence(
        step_id=step_id,
        action_id=action_id,
        user_id=user_id,
        accepted_sequence=accepted_sequence,
        step_number=accepted_sequence,
        local_step_number=accepted_sequence,
        short_step_id=f"S-{accepted_sequence}-USER",
        created_at="2026-08-29T00:00:00.000000Z",
        initial_user_message_id=initial_message_id,
        suggestion_id=suggestion_id,
        user_message_id=message_id,
        user_message_json=serialize_action_user_message(message),
        user_request_text=render_action_user_request_text(message),
    )


def _process(
    step_id: str | None = "step-1",
    *,
    process_id: str = "process-1",
    action_id: str = "action-1",
    user_id: str = "user-1",
    claimed_message_id: str | None = None,
) -> ActionProcessEnvelope:
    return ActionProcessEnvelope(
        job_id=f"job-{process_id}",
        process_id=process_id,
        action_id=action_id,
        user_id=user_id,
        user_step_id=step_id,
        claimed_user_message_id=claimed_message_id,
    )


def test_plan_binds_exact_claims_and_preserves_unclaimed_rows() -> None:
    claimed = _user()
    untyped = _user("step-2", accepted_sequence=2)._replace(
        user_message_id=None, user_message_json=None
    )
    plan = plan_action_user_process_lineage(
        user_steps=(claimed, untyped),
        process_envelopes=(_process(), _process(None, process_id="approval-process")),
    )

    assert plan == (
        ActionUserProcessLineage("step-1", 1, "process-1"),
        ActionUserProcessLineage("step-2", 2, None),
    )


def test_plan_uses_v85_message_claim_only_without_direct_step_claim() -> None:
    user = _user()
    certificate = _process(
        None,
        process_id="legacy-process",
        claimed_message_id="message-1",
    )

    assert plan_action_user_process_lineage(
        user_steps=(user,), process_envelopes=(certificate,)
    ) == (ActionUserProcessLineage("step-1", 1, "legacy-process"),)
    assert plan_action_user_process_lineage(
        user_steps=(user,),
        process_envelopes=(certificate, _process(process_id="root-process")),
    ) == (ActionUserProcessLineage("step-1", 1, "root-process"),)


@pytest.mark.parametrize(
    "user_step",
    (
        _user(
            suggestion_id="suggestion-1",
            approval=_approval(),
        ),
        _user(
            message_id="message-2",
            initial_message_id="message-1",
            suggestion_id="suggestion-1",
        ),
        _user(content="x" * 32_001),
        _user()._replace(
            user_message_json=(
                '{ "content": "request", "message_id": "message-1", "version": 1 }'
            )
        ),
    ),
)
def test_plan_accepts_runtime_message_contract(
    user_step: ActionUserStepEvidence,
) -> None:
    assert plan_action_user_process_lineage(
        user_steps=(user_step,), process_envelopes=(_process(),)
    ) == (ActionUserProcessLineage("step-1", 1, "process-1"),)


BASE_USER = _user()
BASE_PROCESS = _process()


@pytest.mark.parametrize(
    ("user_steps", "processes", "pattern"),
    (
        (
            (BASE_USER._replace(user_message_id=None, user_message_json=None),),
            (BASE_PROCESS,),
            "missing its typed message",
        ),
        (
            (BASE_USER._replace(user_message_json="not-json"),),
            (BASE_PROCESS,),
            "does not match V1 schema",
        ),
        (
            (BASE_USER._replace(user_message_id="other-message"),),
            (BASE_PROCESS,),
            "message identity",
        ),
        (
            (BASE_USER._replace(user_request_text="other request"),),
            (BASE_PROCESS,),
            "rendered text",
        ),
        (
            (BASE_USER,),
            (),
            "has no process claim",
        ),
        (
            (_user(suggestion_id="suggestion-1"),),
            (BASE_PROCESS,),
            "lacks approval metadata",
        ),
        (
            (
                _user(
                    suggestion_id="suggestion-1",
                    approval=_approval("suggestion-2"),
                ),
            ),
            (BASE_PROCESS,),
            "provenance",
        ),
        (
            (_user(approval=_approval()),),
            (BASE_PROCESS,),
            "provenance",
        ),
        (
            (
                _user(
                    message_id="message-2",
                    initial_message_id="message-1",
                    suggestion_id="suggestion-1",
                    approval=_approval(),
                ),
            ),
            (BASE_PROCESS,),
            "provenance",
        ),
        (
            (BASE_USER,),
            (_process(action_id="other-action"),),
            "ownership",
        ),
        (
            (BASE_USER,),
            (_process(user_id="other-user"),),
            "ownership",
        ),
        (
            (BASE_USER,),
            (_process("missing-step"),),
            "does not resolve",
        ),
        (
            (BASE_USER,),
            (_process(None, claimed_message_id="missing-message"),),
            "does not resolve uniquely",
        ),
        (
            (BASE_USER, _user("step-2")),
            (_process(None, claimed_message_id="message-1"),),
            "does not resolve uniquely",
        ),
        (
            (BASE_USER,),
            (BASE_PROCESS, _process(process_id="process-2")),
            "multiple process claims",
        ),
        (
            (BASE_USER,),
            (
                _process(None, claimed_message_id="message-1"),
                _process(
                    None,
                    process_id="process-2",
                    claimed_message_id="message-1",
                ),
            ),
            "multiple process claims",
        ),
        (
            (BASE_USER,),
            (_process(claimed_message_id="message-1"),),
            "multiple USER claim identities",
        ),
        (
            (BASE_USER, _user("step-2", accepted_sequence=2)),
            (BASE_PROCESS, _process("step-2")),
            "duplicate process origin",
        ),
        (
            (BASE_USER, BASE_USER),
            (BASE_PROCESS,),
            "evidence is duplicated",
        ),
    ),
)
def test_plan_rejects_ambiguous_or_inconsistent_claims(
    user_steps: tuple[ActionUserStepEvidence, ...],
    processes: tuple[ActionProcessEnvelope, ...],
    pattern: str,
) -> None:
    with pytest.raises(MigrationError, match=pattern):
        plan_action_user_process_lineage(
            user_steps=user_steps,
            process_envelopes=processes,
        )
