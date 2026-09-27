"""Durable shape and bounded submission contracts for Action USER messages."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from pantaray_agents.schema.action_conversation import ActionStatus

from .base import AgentError
from .image import ImageInput

ACTION_MESSAGE_ID_MAX_CODEPOINTS = 128
ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS = 32_000
ACTION_MESSAGE_SUPPLEMENT_MAX_CODEPOINTS = 8_000
ACTION_MESSAGE_MAX_IMAGES = 32


def _bounded_text(value: str, *, limit: int) -> str:
    normalized = _non_blank_text(value)
    if len(normalized) > limit:
        raise PydanticCustomError(
            "action_message_too_long",
            "value exceeds the Unicode code-point limit",
            {"limit": limit, "unit": "unicode_code_points"},
        )
    return normalized


def _non_blank_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise PydanticCustomError("action_message_blank", "value must not be blank")
    return normalized


def _bounded_id(value: str) -> str:
    return _bounded_text(value, limit=ACTION_MESSAGE_ID_MAX_CODEPOINTS)


def _bounded_content(value: str) -> str:
    return _bounded_text(value, limit=ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS)


ActionMessageId = Annotated[
    str,
    Field(
        json_schema_extra={
            "minLength": 1,
            "maxLength": ACTION_MESSAGE_ID_MAX_CODEPOINTS,
            "pattern": r"\S",
        }
    ),
    AfterValidator(_bounded_id),
]
type ActionMessageFailureType = Literal[
    "ActionNotFound",
    "ActionConflict",
    "MessageIdentityConflict",
    "ExpectedProcessConflict",
]
type ActionMessageValidationReason = Literal[
    "blank",
    "too_long",
    "not_allowed",
    "extra_field",
    "invalid",
    "too_many",
]
type ActionMessageValidationUnit = Literal["unicode_code_points"]


def _bounded_images(value: object) -> object:
    """Bound the raw image count before any item is validated."""

    if not isinstance(value, (list, tuple)):
        return value
    if len(value) > ACTION_MESSAGE_MAX_IMAGES:
        raise PydanticCustomError(
            "action_message_too_many",
            "message contains too many image references",
            {"limit": ACTION_MESSAGE_MAX_IMAGES, "unit": "image_references"},
        )
    # strict モデルは JSON 配列をそのまま tuple として受け取らないため、
    # before バリデータで正規化しておく。
    return tuple(value)


class SuggestionApprovalInput(BaseModel):
    """Suggestion provenance available only to the internal adapter."""

    model_config = ConfigDict(extra="forbid", strict=True)

    suggestion_id: str
    approved_at: str
    summary: str | None = None
    organization_name: str | None = None
    project_name: str | None = None

    _validate_suggestion_id = field_validator("suggestion_id")(_non_blank_text)
    _validate_approved_at = field_validator("approved_at")(_non_blank_text)


class ActionUserMessageInput(BaseModel):
    """Canonical durable USER envelope used by internal Action callers."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1] = 1
    message_id: str
    content: str
    images: tuple[ImageInput, ...] = ()
    language: Literal["en", "ja"] | None = None
    suggestion_approval: SuggestionApprovalInput | None = None
    supplement: Annotated[str, AfterValidator(_non_blank_text)] | None = None

    _validate_message_id = field_validator("message_id")(_non_blank_text)
    _validate_content = field_validator("content")(_non_blank_text)

    @model_validator(mode="after")
    def _require_suggestion_approval_for_supplement(self) -> Self:
        if self.supplement is not None and self.suggestion_approval is None:
            raise PydanticCustomError(
                "action_message_not_allowed",
                "supplement requires Suggestion approval metadata",
            )
        return self


class _ActionMessageHttpModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class ActionMessageHttpNewTarget(_ActionMessageHttpModel):
    kind: Literal["new"]
    approval_mode: Literal["prompt_each_time", "always_allow"] | None = None
    reply_to_suggestion_id: ActionMessageId | None = None


class ActionMessageHttpExistingTarget(_ActionMessageHttpModel):
    kind: Literal["existing"]
    action_id: ActionMessageId
    expected_process_id: ActionMessageId | None


ActionMessageHttpTarget = Annotated[
    ActionMessageHttpNewTarget | ActionMessageHttpExistingTarget,
    Field(discriminator="kind"),
]


class ActionMessageHttpMessage(_ActionMessageHttpModel):
    version: Literal[1]
    message_id: ActionMessageId
    content: Annotated[
        str,
        Field(
            json_schema_extra={
                "minLength": 1,
                "maxLength": ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS,
                "pattern": r"\S",
            }
        ),
    ]
    images: Annotated[
        tuple[ImageInput, ...],
        Field(json_schema_extra={"maxItems": ACTION_MESSAGE_MAX_IMAGES}),
    ]
    language: Literal["en", "ja"] | None = None

    _validate_content = field_validator("content")(_bounded_content)
    _validate_images = field_validator("images", mode="before")(_bounded_images)

    @field_validator("version", mode="before")
    @classmethod
    def _require_exact_wire_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise PydanticCustomError(
                "action_message_invalid",
                "HTTP Action message version must be the integer 1",
            )
        return value


class ActionMessageHttpRequest(_ActionMessageHttpModel):
    target: ActionMessageHttpTarget
    message: ActionMessageHttpMessage


class ActionResumeHttpRequest(_ActionMessageHttpModel):
    """Ask for the stopped run to be continued as one follow-up turn.

    There is no message: the caller pressed a button. ``message_id`` is the same
    user-wide idempotency key an ordinary submission carries, so a retry after a
    lost response continues the same turn instead of opening a second one.
    """

    message_id: ActionMessageId


class _ActionMessageHttpResponseBase(_ActionMessageHttpModel):
    action_id: str
    message_id: str
    step_id: str
    action_status: ActionStatus


class ActionMessageHttpStartedResponse(_ActionMessageHttpResponseBase):
    disposition: Literal["started"]
    process_id: str


class ActionMessageHttpDeferredResponse(_ActionMessageHttpResponseBase):
    disposition: Literal["pending", "not_executed"]
    process_id: None


ActionMessageHttpResponse = Annotated[
    ActionMessageHttpStartedResponse | ActionMessageHttpDeferredResponse,
    Field(discriminator="disposition"),
]


class ActionMessageHttpNotFoundFailure(_ActionMessageHttpModel):
    type: Literal["ActionNotFound"]


class ActionMessageHttpConflictFailure(_ActionMessageHttpModel):
    type: Literal[
        "ActionConflict",
        "MessageIdentityConflict",
        "ExpectedProcessConflict",
    ]


class ActionMessageHttpErrorDetail(_ActionMessageHttpModel):
    detail: str


class ActionMessageHttpServerErrorDetail(_ActionMessageHttpModel):
    detail: AgentError


ActionMessageHttpDefaultErrorDetail = (
    ActionMessageHttpErrorDetail | ActionMessageHttpServerErrorDetail
)


class ActionMessageValidationError(_ActionMessageHttpModel):
    type: Literal["ActionMessageValidationError"] = "ActionMessageValidationError"
    field: str
    reason: ActionMessageValidationReason
    limit: int | None
    unit: ActionMessageValidationUnit | None


def validate_action_user_message_for_submit(
    message: ActionUserMessageInput,
) -> ActionUserMessageInput:
    """Validate only new submissions without narrowing the durable V1 reader."""

    _bounded_id(message.message_id)
    _bounded_content(message.content)
    _bounded_images(message.images)
    if message.supplement is not None:
        _bounded_text(
            message.supplement,
            limit=ACTION_MESSAGE_SUPPLEMENT_MAX_CODEPOINTS,
        )
    approval = message.suggestion_approval
    if approval is not None:
        _bounded_id(approval.suggestion_id)
    return message


__all__ = [
    "ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS",
    "ACTION_MESSAGE_ID_MAX_CODEPOINTS",
    "ACTION_MESSAGE_MAX_IMAGES",
    "ACTION_MESSAGE_SUPPLEMENT_MAX_CODEPOINTS",
    "ActionMessageFailureType",
    "ActionMessageHttpConflictFailure",
    "ActionMessageHttpDeferredResponse",
    "ActionMessageHttpDefaultErrorDetail",
    "ActionMessageHttpErrorDetail",
    "ActionMessageHttpExistingTarget",
    "ActionMessageHttpMessage",
    "ActionMessageHttpNewTarget",
    "ActionMessageHttpNotFoundFailure",
    "ActionMessageHttpRequest",
    "ActionMessageHttpResponse",
    "ActionMessageHttpServerErrorDetail",
    "ActionMessageHttpStartedResponse",
    "ActionMessageHttpTarget",
    "ActionMessageId",
    "ActionMessageValidationError",
    "ActionMessageValidationReason",
    "ActionMessageValidationUnit",
    "ActionResumeHttpRequest",
    "ActionUserMessageInput",
    "SuggestionApprovalInput",
    "validate_action_user_message_for_submit",
]
