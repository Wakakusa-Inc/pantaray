from __future__ import annotations

import json
import logging

import pytest
from pydantic import BaseModel, ValidationError

from pantaray_agents.utils.structured_logging import (
    fingerprint_text,
    log_structured_event,
    summarize_exception_chain,
)


def test_fingerprint_text_hashes_without_echoing_source_value() -> None:
    source_value = "action-1234567890"

    fingerprint = fingerprint_text(source_value)

    assert fingerprint is not None
    assert fingerprint != source_value
    assert len(fingerprint) == 12


def test_log_structured_event_emits_json_without_none_fields(
    caplog,
) -> None:
    logger = logging.getLogger("tests.structured_logging")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        log_structured_event(
            logger,
            level="warning",
            evt="TEST_STRUCTURED_EVENT",
            component="tests.structured_logging",
            included_field="included",
            omitted_field=None,
        )

    payload = json.loads(caplog.records[-1].message)

    assert payload == {
        "component": "tests.structured_logging",
        "evt": "TEST_STRUCTURED_EVENT",
        "included_field": "included",
    }


def test_exception_diagnostics_omit_model_input_and_os_filename(caplog) -> None:
    class Payload(BaseModel):
        count: int

    with pytest.raises(ValidationError) as validation:
        Payload.model_validate({"count": "private-input"})
    error = FileNotFoundError(2, "No such file or directory", "/private/user/file")
    error.__cause__ = validation.value
    logger = logging.getLogger("tests.structured_logging")
    log_structured_event(
        logger, level="error", evt="FAILED", component="test", exception=error
    )
    content = caplog.records[-1].getMessage()
    assert "private-input" not in content
    assert "/private/user/file" not in content
    chain = json.loads(content)["exception_chain"]
    assert chain[0]["message"] == "No such file or directory"
    assert chain[1]["message"] == "Model validation failed: 1 errors"


def test_summarize_exception_chain_locates_each_class_and_classifies_reasons() -> None:
    class Payload(BaseModel):
        count: int

    with pytest.raises(ValidationError) as validation:
        Payload.model_validate({"count": "private-input"})
    try:
        raise FileNotFoundError(
            2, "No such file or directory", "/private/user/file"
        ) from validation.value
    except FileNotFoundError as error:
        summary = summarize_exception_chain(error)

    outer, inner = summary.split(" <- ")
    assert outer.startswith(
        f"FileNotFoundError at {__name__}"
        ":test_summarize_exception_chain_locates_each_class_and_classifies_reasons:"
    )
    assert outer.endswith(": No such file or directory")
    assert inner.startswith("ValidationError at ")
    assert inner.endswith(": Model validation failed: 1 errors")
    assert "private-input" not in summary
    assert "/private/user/file" not in summary


def test_summarize_exception_chain_truncation_keeps_the_root_cause() -> None:
    def _raise_root_cause() -> None:
        raise ValueError("private-document-body")

    error: BaseException
    try:
        _raise_root_cause()
    except ValueError as root:
        error = root
    for _ in range(20):
        try:
            raise RuntimeError("private-prompt-text") from error
        except RuntimeError as wrapper:
            error = wrapper

    summary = summarize_exception_chain(error)

    assert len(summary) == 500
    assert summary.startswith("...")
    assert summary.split(" <- ")[-1].startswith(
        f"ValueError at {__name__}:_raise_root_cause:"
    )
    # A generic exception contributes its class and location; the boilerplate
    # the log carries would only crowd the root cause out of the stored reason.
    assert "Exception message omitted" not in summary
    assert "private-prompt-text" not in summary
    assert "private-document-body" not in summary


def test_exception_chain_does_not_copy_private_generic_messages(caplog) -> None:
    logger = logging.getLogger("tests.structured_logging")
    try:
        try:
            raise ValueError("private-document-body /Users/private/document.md")
        except ValueError as cause:
            raise RuntimeError("private-prompt-text") from cause
    except RuntimeError as error:
        log_structured_event(
            logger, level="error", evt="FAILED", component="test", exception=error
        )
    content = caplog.records[-1].getMessage()
    assert "private-document-body" not in content
    assert "private-prompt-text" not in content
    assert "/Users/private/document.md" not in content
    chain = json.loads(content)["exception_chain"]
    assert [item["error_class"] for item in chain] == ["RuntimeError", "ValueError"]
    assert all(item["stack"] for item in chain)
    assert all(
        item["message"] == "Exception message omitted: may contain private input"
        for item in chain
    )
