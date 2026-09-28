from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.agent.action import (
    ActionUserMessageInput,
    SuggestionApprovalInput,
)
from pantaray_agents.schema.agent.action_message import ActionProjectRef
from pantaray_agents.schema.agent.action_message_codec import (
    parse_action_user_message as parse_action_user_message_codec,
)
from pantaray_agents.schema.agent.action_message_codec import (
    parse_stored_action_user_message,
    render_action_user_visible_text,
)
from pantaray_agents.schema.agent.image import ImageInput
from pantaray_agents.tasks.action_user_message import (
    parse_action_user_message,
    render_action_user_request_text,
    serialize_action_user_message,
)


def test_action_user_message_round_trip_preserves_typed_approval_and_images() -> None:
    message = ActionUserMessageInput(
        message_id="message-1",
        content="Apply the approved change",
        supplement="Run the focused regression before finishing.",
        suggestion_approval=SuggestionApprovalInput(
            suggestion_id="suggestion-1",
            approved_at="2026-08-16T00:00:00Z",
            summary="Keep the edit narrow",
            organization_name="Wakakusa",
            project_name="Pantaray",
        ),
        images=(ImageInput(storage_path="captures/1.png"),),
        language="ja",
    )

    serialized = serialize_action_user_message(message)
    parsed = parse_action_user_message(serialized)

    assert parsed.version == 1
    assert parsed.content == message.content
    assert parsed.supplement == message.supplement
    assert parsed.images == message.images
    assert parsed.language == "ja"
    assert json.loads(serialized)["message_id"] == "message-1"
    assert render_action_user_request_text(message) == (
        "Apply the approved change\n\n"
        "Additional user conditions:\n"
        "Run the focused regression before finishing.\n\n"
        "Suggestion metadata:\n"
        "- Suggestion: suggestion-1\n"
        "- Suggestion summary: Keep the edit narrow\n"
        "- Organization: Wakakusa\n"
        "- Project: Pantaray\n"
        "- Approved at: 2026-08-16T00:00:00Z"
    )
    assert render_action_user_visible_text(
        content=message.content, supplement=message.supplement
    ) == (
        "Apply the approved change\n\n"
        "Additional user conditions:\n"
        "Run the focused regression before finishing."
    )


def test_project_refs_render_one_line_per_project_and_round_trip() -> None:
    demo = ActionProjectRef(
        project_id="project-1",
        display_name="Demo App",
        paths=("/workspace/demo-app", "/workspace/demo-api"),
        start=0,
        end=8,
    )
    message = ActionUserMessageInput(
        message_id="message-1",
        content="Apply the approved change",
        supplement="Demo App first, then Notes and Demo App again",
        supplement_project_refs=(
            demo,
            ActionProjectRef(
                project_id="project-2",
                display_name="Notes",
                paths=(),
                start=21,
                end=26,
            ),
            demo.model_copy(update={"start": 31, "end": 39}),
        ),
        suggestion_approval=SuggestionApprovalInput(
            suggestion_id="suggestion-1", approved_at="2026-08-16T00:00:00Z"
        ),
    )

    request_text = render_action_user_request_text(message)

    assert request_text.endswith(
        "- Approved at: 2026-08-16T00:00:00Z\n\n"
        "Referenced workspace projects:\n"
        "- Demo App: /workspace/demo-app, /workspace/demo-api\n"
        "- Notes: no folders registered"
    )
    assert (
        parse_stored_action_user_message(
            message_id="message-1",
            message_json=serialize_action_user_message(message),
            user_request_text=request_text,
        )
        == message
    )


def test_supplement_project_refs_require_a_supplement() -> None:
    with pytest.raises(ValidationError) as captured:
        ActionUserMessageInput(
            message_id="message-1",
            content="Demo App",
            supplement_project_refs=(
                ActionProjectRef(
                    project_id="project-1",
                    display_name="Demo App",
                    paths=(),
                    start=0,
                    end=8,
                ),
            ),
        )

    assert captured.value.errors(include_url=False)[0]["type"] == (
        "action_message_not_allowed"
    )


def test_action_user_message_rejects_untyped_image_shape() -> None:
    with pytest.raises(ValidationError):
        ActionUserMessageInput.model_validate(
            {
                "message_id": "message-1",
                "content": "Do the work",
                "images": [
                    {
                        "kind": "image",
                        "storage_path": "image.png",
                        "app_name": "must-not-be-accepted",
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "message_json",
    (
        "not-json",
        '{"version":2,"message_id":"m1","content":"Do the work","images":[]}',
        '{"version":1,"message_id":"m1","content":"Do the work","images":[],"extra":1}',
    ),
)
def test_parse_action_user_message_rejects_invalid_durable_shape(
    message_json: str,
) -> None:
    with pytest.raises(ValueError):
        parse_action_user_message_codec(message_json)
    with pytest.raises(MigrationError) as exc:
        parse_action_user_message(message_json)
    assert str(exc.value) == "Action USER message does not match V1 schema"
    assert isinstance(exc.value.__cause__, ValidationError)
