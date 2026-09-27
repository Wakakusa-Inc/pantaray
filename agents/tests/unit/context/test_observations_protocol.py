import json
import traceback

import pytest
from pydantic import ValidationError

from pantaray_agents.local_runtime.context.source_protocol import (
    MAX_EVIDENCE_BYTES,
    MAX_INPUT_BYTES,
    MAX_PAGE_BYTES,
    MAX_PAGE_ROWS,
    AbsentContent,
    DeniedResponse,
    EvidenceOrigin,
    EvidenceReadRequest,
    EvidenceResponse,
    ExpiredResponse,
    IncompatibleResponse,
    InvalidRequestResponse,
    PageReadRequest,
    PageResponse,
    ProtocolError,
    ReadResponse,
    TextContent,
    UnavailableResponse,
    decode_response,
    encode_request,
    validate_response_binding,
)

STORE_ID = "store-01"
EVIDENCE_FIELDS = (
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
)


def _origin(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "store_identity": STORE_ID,
        "append_sequence": 2,
        "event_id": "evt_01",
        "observed_at": "2026-09-06T00:00:00Z",
        "field": "text",
    }
    value.update(changes)
    return value


def _observation(sequence: int = 1) -> dict[str, object]:
    return {
        "append_sequence": sequence,
        "id": f"evt_{sequence}",
        "ts": "2026-09-06T00:00:00Z",
        "source": {"kind": "value", "text": "macos.ax"},
        "event_type": {"kind": "value", "text": "content.snapshot"},
        "bundle_id": {"kind": "absent"},
        "app_name": {"kind": "omitted", "utf8_bytes": 1025},
        "pid": 42,
        "window_title": {"kind": "value", "text": ""},
        "window_id": None,
    }


def _page(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocol_version": 1,
        "kind": "page",
        "store_identity": STORE_ID,
        "observations": [_observation()],
        "next_cursor": "v1:next",
        "upper_bound": "v1:upper",
        "has_more": False,
        "coverage": {"after": 0, "through": 1},
    }
    value.update(changes)
    return value


def _content(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "kind": "text",
        "text": "😀",
        "start": 3,
        "end": 7,
        "total_bytes": 10,
        "remaining": [7, 10],
    }
    value.update(changes)
    return value


def _evidence(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocol_version": 1,
        "kind": "evidence",
        "origin": _origin(),
        "content": _content(),
        "metadata": {
            "event_type": "content.snapshot",
            "payload_without_text": {
                "text": None,
                "chars": 1,
                "cutoff": {"reason": "size_limit"},
            },
            "redaction_applied": True,
            "truncated": True,
        },
    }
    value.update(changes)
    return value


def _gap(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "protocol_version": 1,
        "kind": "gap",
        "store_identity": STORE_ID,
        "reason": "retention_or_deletion",
        "affected_range": {"after": 0, "through": 2},
        "resume_cursor": "v1:resume",
        "upper_bound": "v1:upper",
    }
    value.update(changes)
    return value


def _decode(value: dict[str, object]) -> ReadResponse:
    return decode_response(json.dumps(value).encode())


def _evidence_request(
    *,
    origin: EvidenceOrigin | None = None,
    start: int = 3,
    end: int | None = 10,
) -> EvidenceReadRequest:
    return EvidenceReadRequest(
        origin=origin or EvidenceOrigin.model_validate(_origin()),
        start=start,
        end=end,
    )


def test_requests_encode_exact_closed_shapes_and_input_budget() -> None:
    assert MAX_INPUT_BYTES == 8 * 1024
    assert MAX_PAGE_BYTES == 512 * 1024
    assert MAX_EVIDENCE_BYTES == 64 * 1024
    assert MAX_PAGE_ROWS == 256
    page = PageReadRequest(cursor=None, upper_bound="v1:bound", limit=256)
    assert json.loads(encode_request(page)) == {
        "kind": "page",
        "protocol_version": 1,
        "cursor": None,
        "upper_bound": "v1:bound",
        "limit": 256,
    }
    assert json.loads(encode_request(_evidence_request()))["origin"] == _origin()
    oversized = PageReadRequest(
        cursor="x" * MAX_INPUT_BYTES,
        upper_bound=None,
        limit=1,
    )
    with pytest.raises(ProtocolError, match="input budget"):
        encode_request(oversized)


def test_request_rejects_invalid_version_limit_and_bool_integer() -> None:
    base = {"cursor": None, "upper_bound": None, "limit": 1}
    for version in (True, 0, 2):
        with pytest.raises(ValidationError):
            PageReadRequest.model_validate({**base, "protocol_version": version})
    for limit in (0, 257, True):
        with pytest.raises(ValidationError):
            PageReadRequest.model_validate({**base, "limit": limit})


def test_evidence_origin_fields_match_rust_enum_and_are_closed() -> None:
    for field in EVIDENCE_FIELDS:
        assert EvidenceOrigin.model_validate(_origin(field=field)).field == field
    for field in ("unknown", "arbitrary.pointer"):
        with pytest.raises(ValidationError):
            EvidenceOrigin.model_validate(_origin(field=field))
    with pytest.raises(ValidationError):
        EvidenceOrigin.model_validate({**_origin(), "path": "/private/raw"})


def test_page_decodes_distinct_text_variants_and_coverage() -> None:
    response = _decode(_page())
    assert isinstance(response, PageResponse)
    observation = response.observations[0]
    assert observation.source.kind == "value"
    assert observation.bundle_id.kind == "absent"
    assert observation.app_name.kind == "omitted"
    assert response.coverage.after == 0
    validate_response_binding(
        PageReadRequest(cursor=None, upper_bound=None, limit=1),
        response,
        store_identity=STORE_ID,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"protocol_version": True},
        {"protocol_version": 2},
        {"store_identity": ""},
        {"coverage": {"after": 2, "through": 1}},
        {"coverage": {"after": 1, "through": 3}},
        {
            "observations": [_observation(1), _observation(3)],
            "coverage": {"after": 0, "through": 3},
        },
        {
            "observations": [
                _observation(sequence) for sequence in range(1, MAX_PAGE_ROWS + 2)
            ],
            "coverage": {"after": 0, "through": MAX_PAGE_ROWS + 1},
        },
        {"unexpected": "field"},
    ],
)
def test_page_rejects_invalid_version_shape_count_or_coverage(
    change: dict[str, object],
) -> None:
    with pytest.raises(ProtocolError):
        _decode(_page(**change))


def test_gap_decodes_each_rust_reason() -> None:
    for reason in ("retention_or_deletion", "store_changed", "continuity_unknown"):
        response = _decode(_gap(reason=reason))
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound=None, limit=1),
            response,
            store_identity=STORE_ID,
        )


@pytest.mark.parametrize(
    "response",
    [
        _page(observations=[_observation(2)], coverage={"after": 1, "through": 2}),
        _gap(affected_range={"after": 1, "through": 2}),
    ],
)
def test_initial_response_cannot_skip_store_prefix(response: dict[str, object]) -> None:
    with pytest.raises(ProtocolError, match="initial response"):
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound=None, limit=1),
            _decode(response),
            store_identity=STORE_ID,
        )


def test_advertised_evidence_range_stays_within_request_domain() -> None:
    with pytest.raises(ProtocolError):
        _decode(
            _evidence(content=_content(total_bytes=1 << 63, remaining=[7, 1 << 63]))
        )


def test_page_binding_enforces_requested_row_limit() -> None:
    response = _decode(
        _page(
            observations=[_observation(1), _observation(2)],
            coverage={"after": 0, "through": 2},
        )
    )
    with pytest.raises(ProtocolError, match="row limit"):
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound=None, limit=1),
            response,
            store_identity=STORE_ID,
        )


@pytest.mark.parametrize("response", [_page(), _gap()])
def test_page_and_retention_gap_bind_fixed_upper_bound(
    response: dict[str, object],
) -> None:
    with pytest.raises(ProtocolError, match="upper bound"):
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound="v1:upper", limit=1),
            _decode({**response, "upper_bound": "other"}),
            store_identity=STORE_ID,
        )


@pytest.mark.parametrize("response", [_page(has_more=True), _page(), _gap()])
def test_page_and_retention_gap_continuation_must_advance(
    response: dict[str, object],
) -> None:
    cursor_field = "next_cursor" if response["kind"] == "page" else "resume_cursor"
    request = PageReadRequest(cursor="v1:start", upper_bound=None, limit=1)
    with pytest.raises(ProtocolError, match="did not advance"):
        validate_response_binding(
            request,
            _decode({**response, cursor_field: "v1:start"}),
            store_identity=STORE_ID,
        )
    terminal = _decode(
        _page(
            next_cursor="v1:start",
            has_more=False,
            observations=[],
            coverage={"after": 1, "through": 1},
        )
    )
    validate_response_binding(request, terminal, store_identity=STORE_ID)


@pytest.mark.parametrize("reason", ["store_changed", "continuity_unknown"])
@pytest.mark.parametrize(
    ("cursor", "upper_bound"),
    [
        ("v1:reset", "v1:old-upper"),
        ("v1:reset", "v1:new-upper"),
        ("v1:new", "v1:old-upper"),
    ],
)
def test_reset_gap_must_change_at_least_one_position_token(
    reason: str, cursor: str, upper_bound: str
) -> None:
    request = PageReadRequest(cursor="v1:reset", upper_bound="v1:old-upper", limit=1)
    response = _decode(
        _gap(reason=reason, resume_cursor=cursor, upper_bound=upper_bound)
    )
    if cursor == request.cursor and upper_bound == request.upper_bound:
        with pytest.raises(ProtocolError, match="reset gap position"):
            validate_response_binding(request, response, store_identity=STORE_ID)
    else:
        validate_response_binding(request, response, store_identity=STORE_ID)


@pytest.mark.parametrize("field", ["cursor", "upper_bound"])
def test_page_request_rejects_empty_position_token(field: str) -> None:
    with pytest.raises(ValidationError):
        PageReadRequest.model_validate_json(
            json.dumps({"cursor": None, "upper_bound": None, "limit": 1, field: ""})
        )


@pytest.mark.parametrize("field", ["after", "through"])
@pytest.mark.parametrize("value", [False, 0.0, "0"])
def test_decoder_rejects_coerced_coverage(field: str, value: object) -> None:
    with pytest.raises(ProtocolError):
        _decode(
            _page(observations=[], coverage={"after": 0, "through": 0, field: value})
        )


def test_evidence_validates_whole_origin_utf8_and_remaining_range() -> None:
    response = _decode(_evidence())
    assert isinstance(response, EvidenceResponse)
    assert isinstance(response.content, TextContent)
    assert response.content.text == "😀"
    assert response.content.remaining == (7, 10)
    validate_response_binding(
        _evidence_request(),
        response,
        store_identity=STORE_ID,
    )


def test_evidence_rejects_any_origin_mismatch() -> None:
    replacements = {
        "store_identity": "other",
        "append_sequence": 3,
        "event_id": "other",
        "observed_at": "2026-09-06T00:00:01Z",
        "field": "url",
    }
    for field, replacement in replacements.items():
        response = _decode(_evidence(origin=_origin(**{field: replacement})))
        with pytest.raises(ProtocolError, match="origin"):
            validate_response_binding(
                _evidence_request(), response, store_identity=STORE_ID
            )


@pytest.mark.parametrize(
    ("content", "read_request"),
    [
        (_content(start=0, end=4, remaining=[4, 10]), _evidence_request()),
        (_content(remaining=[7, 9]), _evidence_request()),
        (_content(remaining=None), _evidence_request()),
        (_content(), _evidence_request(end=11)),
    ],
)
def test_evidence_rejects_request_range_mismatch(
    content: dict[str, object],
    read_request: EvidenceReadRequest,
) -> None:
    response = _decode(_evidence(content=content))
    with pytest.raises(ProtocolError, match="range"):
        validate_response_binding(read_request, response, store_identity=STORE_ID)


def test_evidence_rejects_text_that_does_not_match_utf8_byte_range() -> None:
    with pytest.raises(ProtocolError):
        _decode(_evidence(content=_content(end=8)))


def test_evidence_rejects_zero_length_chunk_with_remaining_range() -> None:
    with pytest.raises(ProtocolError):
        _decode(_evidence(content=_content(text="", start=3, end=3, remaining=[3, 10])))


@pytest.mark.parametrize("nonfinite", [float("nan"), float("inf"), -float("inf")])
def test_metadata_rejects_nested_nonfinite_number(nonfinite: float) -> None:
    response = _evidence()
    metadata = response["metadata"]
    assert isinstance(metadata, dict)
    payload = metadata["payload_without_text"]
    assert isinstance(payload, dict)
    payload["nested"] = [nonfinite]
    with pytest.raises(ProtocolError):
        _decode(response)


@pytest.mark.parametrize("absent_end", [None, 10])
def test_absent_empty_and_json_null_remain_distinct(absent_end: int | None) -> None:
    absent = _decode(_evidence(content={"kind": "absent"}))
    empty = _decode(
        _evidence(
            content={
                "kind": "text",
                "text": "",
                "start": 0,
                "end": 0,
                "total_bytes": 0,
                "remaining": None,
            }
        )
    )
    assert isinstance(absent, EvidenceResponse)
    assert isinstance(absent.content, AbsentContent)
    assert absent.metadata.payload_without_text["text"] is None
    assert isinstance(empty, EvidenceResponse)
    assert isinstance(empty.content, TextContent)
    validate_response_binding(
        _evidence_request(start=0, end=absent_end),
        absent,
        store_identity=STORE_ID,
    )
    validate_response_binding(
        _evidence_request(start=0, end=None),
        empty,
        store_identity=STORE_ID,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "expired"},
        {"kind": "denied"},
        {"kind": "invalid_request"},
        {"kind": "unavailable", "reason": "config"},
        {"kind": "unavailable", "reason": "key"},
        {"kind": "unavailable", "reason": "store"},
        {"kind": "unavailable", "reason": "input"},
        {"kind": "incompatible", "reason": "protocol", "version": 2},
        {"kind": "incompatible", "reason": "store_schema", "version": 9},
        {"kind": "incompatible", "reason": "store_corrupt", "version": None},
    ],
)
def test_all_explicit_failure_variants_are_preserved(
    payload: dict[str, object],
) -> None:
    response_types = {
        "expired": ExpiredResponse,
        "denied": DeniedResponse,
        "invalid_request": InvalidRequestResponse,
        "unavailable": UnavailableResponse,
        "incompatible": IncompatibleResponse,
    }
    assert isinstance(
        _decode({"protocol_version": 1, **payload}), response_types[payload["kind"]]
    )


def test_binding_rejects_store_and_success_kind_mismatches() -> None:
    page = _decode(_page())
    with pytest.raises(ProtocolError, match="store identity"):
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound=None, limit=1),
            page,
            store_identity="other",
        )
    with pytest.raises(ProtocolError, match="evidence request"):
        validate_response_binding(
            _evidence_request(),
            page,
            store_identity=STORE_ID,
        )
    with pytest.raises(ProtocolError, match="evidence failure"):
        validate_response_binding(
            PageReadRequest(cursor=None, upper_bound=None, limit=1),
            _decode({"protocol_version": 1, "kind": "expired"}),
            store_identity=STORE_ID,
        )
    wrong_store = EvidenceOrigin.model_validate(_origin(store_identity="other"))
    with pytest.raises(ProtocolError, match="request store identity"):
        validate_response_binding(
            _evidence_request(origin=wrong_store),
            _decode({"protocol_version": 1, "kind": "denied"}),
            store_identity=STORE_ID,
        )


def test_decoder_rejects_unknown_kind_reason_and_extra_fields() -> None:
    invalid = [
        {"protocol_version": 1, "kind": "unknown"},
        {"protocol_version": 1, "kind": "unavailable", "reason": "other"},
        {"protocol_version": 1, "kind": "expired", "secret": "raw"},
    ]
    for payload in invalid:
        with pytest.raises(ProtocolError, match="protocol v1"):
            _decode(payload)


@pytest.mark.parametrize("kind", ["expired", "unknown"])
def test_decoder_does_not_expose_recorded_input_in_traceback(kind: str) -> None:
    secret = "RECORDED-SENSITIVE-TEXT"
    with pytest.raises(ProtocolError) as caught:
        decode_response(
            json.dumps({"protocol_version": 1, "kind": kind, "extra": secret}).encode()
        )
    assert secret not in "".join(traceback.format_exception(caught.value))
