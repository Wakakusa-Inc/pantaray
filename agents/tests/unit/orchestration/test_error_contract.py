from __future__ import annotations

from pantaray_agents.orchestration.common.errors import error_from_payload


def test_error_from_payload_preserves_stable_code_and_sanitizes_message() -> None:
    message = error_from_payload(
        {
            "error_type": "validation_error",
            "error_code": "ACTION_TOOL_ARGS_INVALID_RETRY_EXCEEDED",
            "error_message": "secret path: /Users/example/private.txt",
            "error_details": {"request_id": "request-1", "secret": "hidden"},
            "severity": "error",
            "metadata": {"private": "hidden"},
        },
        "ACTION_STREAM_ERROR",
    )

    assert message.error_type == "validation_error"
    assert message.error_code == "ACTION_TOOL_ARGS_INVALID_RETRY_EXCEEDED"
    assert message.error_message == (
        "The operation could not continue because its input was invalid."
    )
    assert message.error_details == {"request_id": "request-1"}
    assert message.metadata is None


def test_error_from_payload_normalizes_internal_type_to_public_category() -> None:
    message = error_from_payload(
        {
            "error_type": "runtime_timeout",
            "error_code": "ACTION_PROCESSING_TIMEOUT",
            "error_message": "raw timeout detail",
            "error_details": None,
            "severity": "critical",
            "metadata": None,
        },
        "ACTION_STREAM_ERROR",
    )

    assert message.error_type == "timeout_error"
    assert message.error_code == "ACTION_PROCESSING_TIMEOUT"
    assert message.error_message == "The operation timed out."
    assert message.severity == "critical"


def test_error_from_payload_uses_generic_code_only_for_malformed_payload() -> None:
    message = error_from_payload(
        {"request_id": "request-2", "error_message": "untyped failure"},
        "SUGGESTION_JOB_ERROR",
    )

    assert message.error_type == "internal_error"
    assert message.error_code == "SUGGESTION_JOB_ERROR"
    assert message.error_details == {"request_id": "request-2"}
