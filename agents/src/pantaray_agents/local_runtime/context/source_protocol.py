"""Closed protocol-v1 contract for the bundled Zanei context reader."""

from itertools import pairwise
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    TypeAdapter,
    ValidationError,
    model_validator,
)

PROTOCOL_VERSION = 1
MAX_INPUT_BYTES = 8 * 1024
MAX_PAGE_BYTES = 512 * 1024
MAX_EVIDENCE_BYTES = 64 * 1024
MAX_PAGE_ROWS = 256
SQLITE_INTEGER_MAX = (1 << 63) - 1

type NonEmptyText = Annotated[str, Field(min_length=1)]
type ProtocolVersion = Annotated[int, Field(strict=True, ge=1, le=1)]
type UInt64 = Annotated[int, Field(ge=0, le=(1 << 64) - 1)]
type ByteOffset = Annotated[int, Field(ge=0, le=SQLITE_INTEGER_MAX)]
type SQLitePositiveInteger = Annotated[int, Field(gt=0, le=SQLITE_INTEGER_MAX)]
type SQLiteInteger = Annotated[int, Field(ge=-(1 << 63), le=SQLITE_INTEGER_MAX)]
type FiniteJsonValue = (
    None
    | bool
    | int
    | FiniteFloat
    | str
    | list[FiniteJsonValue]
    | dict[str, FiniteJsonValue]
)
type EvidenceField = Literal[
    "source",
    "event_type",
    "bundle_id",
    "app_name",
    "window_title",
    "element_role",
    "element_title",
    "element_value",
    "text",
    "url",
    "tab_title",
    "previous_title",
    "key_combo",
]


class ProtocolError(ValueError):
    """The request or response violates the local CLI contract."""


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class PageReadRequest(_WireModel):
    kind: Literal["page"] = "page"
    protocol_version: ProtocolVersion = PROTOCOL_VERSION
    cursor: NonEmptyText | None
    upper_bound: NonEmptyText | None
    limit: Annotated[int, Field(ge=1, le=MAX_PAGE_ROWS)]


class EvidenceOrigin(_WireModel):
    store_identity: NonEmptyText
    append_sequence: SQLitePositiveInteger
    event_id: NonEmptyText
    observed_at: NonEmptyText
    field: EvidenceField


class EvidenceReadRequest(_WireModel):
    kind: Literal["evidence"] = "evidence"
    protocol_version: ProtocolVersion = PROTOCOL_VERSION
    origin: EvidenceOrigin
    start: ByteOffset
    end: ByteOffset | None

    @model_validator(mode="after")
    def require_ordered_range(self) -> Self:
        if self.end is not None and self.end < self.start:
            raise ValueError("evidence end must not precede start")
        return self


type ReadRequest = PageReadRequest | EvidenceReadRequest


class AbsentText(_WireModel):
    kind: Literal["absent"]


class ValueText(_WireModel):
    kind: Literal["value"]
    text: str


class OmittedText(_WireModel):
    kind: Literal["omitted"]
    utf8_bytes: UInt64


type ObservationText = Annotated[
    AbsentText | ValueText | OmittedText,
    Field(discriminator="kind"),
]


class Observation(_WireModel):
    append_sequence: SQLitePositiveInteger
    id: NonEmptyText
    ts: NonEmptyText
    source: ObservationText
    event_type: ObservationText
    bundle_id: ObservationText
    app_name: ObservationText
    pid: SQLiteInteger | None
    window_title: ObservationText
    window_id: SQLiteInteger | None


class SequenceRange(_WireModel):
    after: UInt64
    through: UInt64

    @model_validator(mode="after")
    def require_ordered_range(self) -> Self:
        if self.through < self.after:
            raise ValueError("range through must not precede after")
        return self


class PageResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["page"]
    store_identity: NonEmptyText
    observations: Annotated[
        tuple[Observation, ...],
        Field(max_length=MAX_PAGE_ROWS),
    ]
    next_cursor: NonEmptyText
    upper_bound: NonEmptyText
    has_more: bool
    coverage: SequenceRange

    @model_validator(mode="after")
    def require_observations_to_match_coverage(self) -> Self:
        sequences = tuple(item.append_sequence for item in self.observations)
        if sequences and (
            sequences[0] != self.coverage.after + 1
            or sequences[-1] != self.coverage.through
            or any(right != left + 1 for left, right in pairwise(sequences))
        ):
            raise ValueError("page observations do not match coverage")
        if not sequences and self.coverage.after != self.coverage.through:
            raise ValueError("empty page must have empty coverage")
        return self


class GapResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["gap"]
    store_identity: NonEmptyText
    reason: Literal[
        "retention_or_deletion",
        "store_changed",
        "continuity_unknown",
    ]
    affected_range: SequenceRange
    resume_cursor: NonEmptyText
    upper_bound: NonEmptyText


class AbsentContent(_WireModel):
    kind: Literal["absent"]


class TextContent(_WireModel):
    kind: Literal["text"]
    text: str
    start: ByteOffset
    end: ByteOffset
    total_bytes: ByteOffset
    remaining: tuple[ByteOffset, ByteOffset] | None

    @model_validator(mode="after")
    def require_utf8_byte_range(self) -> Self:
        if self.end < self.start or self.end > self.total_bytes:
            raise ValueError("evidence content range is invalid")
        if self.end - self.start != len(self.text.encode("utf-8")):
            raise ValueError("evidence text does not match its UTF-8 byte range")
        if self.remaining is not None and not (
            self.remaining[0] == self.end
            and self.end > self.start
            and self.end < self.remaining[1] <= self.total_bytes
        ):
            raise ValueError("evidence remaining range is invalid")
        return self


type EvidenceContent = Annotated[
    AbsentContent | TextContent,
    Field(discriminator="kind"),
]


class EvidenceMetadata(_WireModel):
    event_type: NonEmptyText
    # EventData has 14 closed legacy variants in Zanei. This boundary preserves
    # their JSON object without duplicating that producer-owned schema.
    payload_without_text: dict[str, FiniteJsonValue]
    redaction_applied: bool
    truncated: bool


class EvidenceResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["evidence"]
    origin: EvidenceOrigin
    content: EvidenceContent
    metadata: EvidenceMetadata


class ExpiredResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["expired"]


class DeniedResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["denied"]


class InvalidRequestResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["invalid_request"]


class UnavailableResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["unavailable"]
    reason: Literal["config", "key", "store", "input"]


class IncompatibleResponse(_WireModel):
    protocol_version: ProtocolVersion
    kind: Literal["incompatible"]
    reason: Literal["protocol", "store_schema", "store_corrupt"]
    version: int | None


type ReadResponse = Annotated[
    PageResponse
    | GapResponse
    | EvidenceResponse
    | ExpiredResponse
    | DeniedResponse
    | InvalidRequestResponse
    | UnavailableResponse
    | IncompatibleResponse,
    Field(discriminator="kind"),
]

_RESPONSE_ADAPTER: TypeAdapter[ReadResponse] = TypeAdapter(
    ReadResponse,
    config=ConfigDict(strict=True, hide_input_in_errors=True),
)


def encode_request(request: ReadRequest) -> bytes:
    encoded = request.model_dump_json().encode("utf-8") + b"\n"
    if len(encoded) > MAX_INPUT_BYTES:
        raise ProtocolError("context-read request exceeds input budget")
    return encoded


def decode_response(raw: bytes) -> ReadResponse:
    try:
        return _RESPONSE_ADAPTER.validate_json(raw)
    except ValidationError:
        raise ProtocolError("context-read response violates protocol v1") from None


def validate_response_binding(
    request: ReadRequest,
    response: ReadResponse,
    *,
    store_identity: str,
) -> None:
    if (
        isinstance(request, EvidenceReadRequest)
        and request.origin.store_identity != store_identity
    ):
        raise ProtocolError("request store identity does not match source binding")
    if isinstance(response, (PageResponse, GapResponse)):
        if not isinstance(request, PageReadRequest):
            raise ProtocolError("page response does not match evidence request")
        if response.store_identity != store_identity:
            raise ProtocolError("response store identity does not match source binding")
        covered = (
            response.coverage
            if isinstance(response, PageResponse)
            else response.affected_range
        )
        if request.cursor is None and covered.after != 0:
            raise ProtocolError("initial response skips the beginning of the store")
        if isinstance(response, PageResponse):
            if (
                request.upper_bound is not None
                and response.upper_bound != request.upper_bound
            ):
                raise ProtocolError("response upper bound does not match request")
            if len(response.observations) > request.limit:
                raise ProtocolError("page response exceeds requested row limit")
            if (
                (response.has_more or response.observations)
                and request.cursor is not None
                and response.next_cursor == request.cursor
            ):
                raise ProtocolError("page continuation cursor did not advance")
        # Reset gaps replace an invalid snapshot; retention gaps stay within it.
        elif response.reason == "retention_or_deletion":
            if (
                request.upper_bound is not None
                and response.upper_bound != request.upper_bound
            ):
                raise ProtocolError("response upper bound does not match request")
            if request.cursor is not None and response.resume_cursor == request.cursor:
                raise ProtocolError("gap continuation cursor did not advance")
        elif (
            response.resume_cursor == request.cursor
            and response.upper_bound == request.upper_bound
        ):
            raise ProtocolError("reset gap position did not change")
    elif isinstance(response, EvidenceResponse):
        if not isinstance(request, EvidenceReadRequest):
            raise ProtocolError("evidence response does not match page request")
        if response.origin != request.origin:
            raise ProtocolError("evidence response origin does not match request")
        _validate_evidence_range(request, response.content)
    elif isinstance(response, (ExpiredResponse, DeniedResponse)) and not isinstance(
        request, EvidenceReadRequest
    ):
        raise ProtocolError("evidence failure does not match page request")


def _validate_evidence_range(
    request: EvidenceReadRequest,
    content: EvidenceContent,
) -> None:
    if isinstance(content, AbsentContent):
        return
    requested_end = request.end if request.end is not None else content.total_bytes
    if content.start != request.start or requested_end > content.total_bytes:
        raise ProtocolError("evidence response range does not match request")
    if content.remaining is None:
        if content.end != requested_end:
            raise ProtocolError("evidence response ended before requested range")
    elif content.remaining != (content.end, requested_end):
        raise ProtocolError("evidence remaining range does not match request")
