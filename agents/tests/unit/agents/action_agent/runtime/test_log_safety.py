from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.log_safety import (
    safe_exception_origin,
    summarize_missing_required_string_fields,
)


def _raise_runtime_error() -> None:
    raise RuntimeError("internal invariant failed")


def test_summarize_missing_required_string_fields_reports_only_missing_entries() -> (
    None
):
    missing_fields = summarize_missing_required_string_fields(
        {
            "action_id": "act-123",
            "user_id": "  ",
            "manifest_id": None,
            "execution_session_id": "sess-123",
        },
        required_fields=(
            "action_id",
            "user_id",
            "manifest_id",
            "execution_session_id",
        ),
    )

    assert missing_fields == ["user_id", "manifest_id"]


def test_safe_exception_origin_returns_final_traceback_frame() -> None:
    try:
        _raise_runtime_error()
    except RuntimeError as exc:
        origin = safe_exception_origin(exc)
    else:  # pragma: no cover
        raise AssertionError("RuntimeError was not raised")

    assert origin is not None
    assert "test_log_safety.py" in origin
    assert "_raise_runtime_error" in origin
