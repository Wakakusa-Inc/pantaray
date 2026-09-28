"""Pure codec for the canonical durable Action USER message."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError

from .action_message import (
    ActionProjectRef,
    ActionUserMessageInput,
    SuggestionApprovalInput,
)

_ACTION_USER_MESSAGE_ADAPTER = TypeAdapter(ActionUserMessageInput)


def serialize_action_user_message(message: ActionUserMessageInput) -> str:
    return message.model_dump_json()


def parse_action_user_message(message_json: str) -> ActionUserMessageInput:
    return _ACTION_USER_MESSAGE_ADAPTER.validate_json(message_json)


def parse_stored_action_user_message(
    *, message_id: str | None, message_json: str | None, user_request_text: str
) -> ActionUserMessageInput | None:
    """Validate the durable envelope; legacy rows have no typed attribution."""
    if message_id is None and message_json is None:
        return None
    if message_id is None or message_json is None:
        raise ValueError("Action USER message identity and JSON must both be present")
    try:
        message = parse_action_user_message(message_json)
    except ValidationError as exc:
        raise ValueError(
            "Action USER message JSON violates the durable schema"
        ) from exc
    if (
        message.message_id != message_id
        or render_action_user_request_text(message) != user_request_text
    ):
        raise ValueError("Action USER message identity or request text is inconsistent")
    return message


def render_action_user_visible_text(*, content: str, supplement: str | None) -> str:
    sections = [content]
    if supplement is not None:
        sections.append(f"Additional user conditions:\n{supplement}")
    return "\n\n".join(sections)


def render_action_user_request_text(message: ActionUserMessageInput) -> str:
    sections = [
        render_action_user_visible_text(
            content=message.content, supplement=message.supplement
        )
    ]
    approval = message.suggestion_approval
    if approval is not None:
        metadata_lines = _render_suggestion_metadata(approval)
        sections.append("Suggestion metadata:\n" + "\n".join(metadata_lines))
    project_refs = (*message.project_refs, *message.supplement_project_refs)
    if project_refs:
        sections.append(_render_project_refs(project_refs))
    return "\n\n".join(sections)


def _render_suggestion_metadata(approval: SuggestionApprovalInput) -> list[str]:
    metadata_lines = [f"- Suggestion: {approval.suggestion_id}"]
    if approval.summary:
        metadata_lines.append(f"- Suggestion summary: {approval.summary}")
    if approval.organization_name:
        metadata_lines.append(f"- Organization: {approval.organization_name}")
    if approval.project_name:
        metadata_lines.append(f"- Project: {approval.project_name}")
    metadata_lines.append(f"- Approved at: {approval.approved_at}")
    return metadata_lines


def _render_project_refs(refs: tuple[ActionProjectRef, ...]) -> str:
    first_by_project: dict[str, ActionProjectRef] = {}
    for ref in refs:
        first_by_project.setdefault(ref.project_id, ref)
    lines = [
        f"- {ref.display_name}: "
        + (", ".join(ref.paths) if ref.paths else "no folders registered")
        for ref in first_by_project.values()
    ]
    return "Referenced workspace projects:\n" + "\n".join(lines)


__all__ = [
    "parse_action_user_message",
    "parse_stored_action_user_message",
    "render_action_user_request_text",
    "render_action_user_visible_text",
    "serialize_action_user_message",
]
