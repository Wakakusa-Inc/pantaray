"""Plan exact Action USER-to-process lineage without reading storage."""

from __future__ import annotations

from typing import NamedTuple

from pydantic import ValidationError

from pantaray_agents.schema.agent.action_message import ActionUserMessageInput
from pantaray_agents.schema.agent.action_message_codec import (
    parse_action_user_message,
    render_action_user_request_text,
)

from .action_process_envelopes import ActionProcessEnvelope
from .action_user_step_inventory import ActionUserStepEvidence
from .specs import MigrationError


class ActionUserProcessLineage(NamedTuple):
    step_id: str
    accepted_sequence: int
    adopted_process_id: str | None


def plan_action_user_process_lineage(
    *,
    user_steps: tuple[ActionUserStepEvidence, ...],
    process_envelopes: tuple[ActionProcessEnvelope, ...],
) -> tuple[ActionUserProcessLineage, ...]:
    """Bind current root process claims and preserve unclaimed historical USER rows."""
    users_by_step: dict[str, ActionUserStepEvidence] = {}
    for evidence in user_steps:
        if evidence.step_id in users_by_step:
            raise MigrationError(
                f"Action USER evidence is duplicated: step_id={evidence.step_id}"
            )
        users_by_step[evidence.step_id] = evidence

    users_by_message: dict[tuple[str, str, str], list[ActionUserStepEvidence]] = {}
    for evidence in user_steps:
        if evidence.user_message_id is not None:
            key = (evidence.action_id, evidence.user_id, evidence.user_message_id)
            users_by_message.setdefault(key, []).append(evidence)

    process_by_step: dict[str, str] = {}
    claimed_processes: set[str] = set()
    direct_claimed_steps: set[str] = set()
    direct_claims = tuple(
        envelope for envelope in process_envelopes if envelope.user_step_id is not None
    )
    message_claims = tuple(
        envelope
        for envelope in process_envelopes
        if envelope.claimed_user_message_id is not None
    )
    for envelope in (*direct_claims, *message_claims):
        claimed_evidence = _resolve_claimed_user(
            envelope=envelope,
            users_by_step=users_by_step,
            users_by_message=users_by_message,
        )
        if claimed_evidence is None:
            continue
        if envelope.claimed_user_message_id is not None and (
            claimed_evidence.step_id in direct_claimed_steps
        ):
            continue
        if envelope.process_id in claimed_processes:
            raise MigrationError(
                "Action USER lineage has a duplicate process origin: "
                f"process_id={envelope.process_id}"
            )
        if claimed_evidence.step_id in process_by_step:
            raise MigrationError(
                "Action USER step has multiple process claims: "
                f"step_id={claimed_evidence.step_id}"
            )
        _validate_claimed_message(claimed_evidence)
        claimed_processes.add(envelope.process_id)
        process_by_step[claimed_evidence.step_id] = envelope.process_id
        if envelope.user_step_id is not None:
            direct_claimed_steps.add(claimed_evidence.step_id)

    plan: list[ActionUserProcessLineage] = []
    for evidence in user_steps:
        adopted_process_id = process_by_step.get(evidence.step_id)
        if adopted_process_id is None and (
            evidence.user_message_id is not None
            or evidence.user_message_json is not None
        ):
            raise MigrationError(
                "Typed Action USER step has no process claim: "
                f"step_id={evidence.step_id}"
            )
        plan.append(
            ActionUserProcessLineage(
                step_id=evidence.step_id,
                accepted_sequence=evidence.accepted_sequence,
                adopted_process_id=adopted_process_id,
            )
        )
    return tuple(plan)


def _resolve_claimed_user(
    *,
    envelope: ActionProcessEnvelope,
    users_by_step: dict[str, ActionUserStepEvidence],
    users_by_message: dict[tuple[str, str, str], list[ActionUserStepEvidence]],
) -> ActionUserStepEvidence | None:
    if (
        envelope.user_step_id is not None
        and envelope.claimed_user_message_id is not None
    ):
        raise MigrationError(
            "Action process has multiple USER claim identities: "
            f"process_id={envelope.process_id}"
        )
    if envelope.user_step_id is not None:
        evidence = users_by_step.get(envelope.user_step_id)
        if evidence is None:
            raise MigrationError(
                "Action user_step claim does not resolve to USER evidence: "
                f"step_id={envelope.user_step_id}"
            )
    elif envelope.claimed_user_message_id is not None:
        key = (
            envelope.action_id,
            envelope.user_id,
            envelope.claimed_user_message_id,
        )
        candidates = users_by_message.get(key, ())
        if len(candidates) != 1:
            raise MigrationError(
                "Action user_message claim does not resolve uniquely to USER evidence: "
                f"message_id={envelope.claimed_user_message_id} "
                f"count={len(candidates)}"
            )
        evidence = candidates[0]
    else:
        return None
    if (envelope.action_id, envelope.user_id) != (
        evidence.action_id,
        evidence.user_id,
    ):
        raise MigrationError(
            f"Action USER process ownership is inconsistent: step_id={evidence.step_id}"
        )
    return evidence


def _validate_claimed_message(evidence: ActionUserStepEvidence) -> None:
    message_id = evidence.user_message_id
    message_json = evidence.user_message_json
    if message_id is None or message_json is None:
        raise MigrationError(
            f"Action USER step is missing its typed message: step_id={evidence.step_id}"
        )
    try:
        message = parse_action_user_message(message_json)
    except ValidationError as exc:
        raise MigrationError(
            f"Action USER message does not match V1 schema: step_id={evidence.step_id}"
        ) from exc
    if message.message_id != message_id:
        raise MigrationError(
            "Action USER step message identity is inconsistent: "
            f"step_id={evidence.step_id}"
        )
    if render_action_user_request_text(message) != evidence.user_request_text:
        raise MigrationError(
            "Action USER step rendered text is inconsistent: "
            f"step_id={evidence.step_id}"
        )
    _validate_suggestion_provenance(evidence, message)


def _validate_suggestion_provenance(
    evidence: ActionUserStepEvidence,
    message: ActionUserMessageInput,
) -> None:
    approval = message.suggestion_approval
    is_initial_message = evidence.initial_user_message_id == evidence.user_message_id
    if is_initial_message and evidence.suggestion_id is not None and approval is None:
        raise MigrationError(
            "Suggestion-linked initial USER message lacks approval metadata: "
            f"step_id={evidence.step_id}"
        )
    if approval is not None and (
        not is_initial_message or approval.suggestion_id != evidence.suggestion_id
    ):
        raise MigrationError(
            "Action suggestion provenance does not match USER message: "
            f"step_id={evidence.step_id}"
        )


__all__ = ["ActionUserProcessLineage", "plan_action_user_process_lineage"]
