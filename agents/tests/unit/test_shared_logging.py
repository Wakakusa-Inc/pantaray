"""Tests for configure_logging in pantaray_agents.app.shared."""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Iterator

import pytest

from pantaray_agents.app.shared import (
    PY_LOG_FILE_BACKUP_COUNT,
    PY_LOG_FILE_MAX_BYTES,
    configure_logging,
)
from pantaray_agents.utils.log_redaction import RedactingFormatter

_LOGGER_CONFIGURED_ATTR = "_pantaray_logging_configured"


@pytest.fixture(autouse=True)
def restore_root_logger() -> Iterator[None]:
    """Let each test configure the root logger from a clean slate."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers.clear()
    if hasattr(root, _LOGGER_CONFIGURED_ATTR):
        delattr(root, _LOGGER_CONFIGURED_ATTR)
    try:
        yield
    finally:
        for handler in root.handlers:
            handler.close()
        root.handlers.clear()
        root.handlers.extend(saved_handlers)
        root.setLevel(saved_level)
        if hasattr(root, _LOGGER_CONFIGURED_ATTR):
            delattr(root, _LOGGER_CONFIGURED_ATTR)


def _rotating_handlers(
    handlers: list[logging.Handler],
) -> list[logging.handlers.RotatingFileHandler]:
    return [
        handler
        for handler in handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


def _console_handlers(handlers: list[logging.Handler]) -> list[logging.StreamHandler]:
    return [
        handler
        for handler in handlers
        if isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


def _handlers_added_by(
    root: logging.Logger, before: list[logging.Handler]
) -> list[logging.Handler]:
    # Ignore handlers owned by pytest's caplog (a StreamHandler subclass).
    return [handler for handler in root.handlers if handler not in before]


def test_local_backend_uses_rotating_file_without_console(tmp_path) -> None:
    log_file = tmp_path / "agent.log"
    root = logging.getLogger()
    before = list(root.handlers)
    configure_logging(
        log_level="ERROR", log_file_path=str(log_file), enable_console=False
    )
    added = _handlers_added_by(root, before)

    rotating = _rotating_handlers(added)
    assert len(rotating) == 1
    assert _console_handlers(added) == []
    assert rotating[0].maxBytes == PY_LOG_FILE_MAX_BYTES
    assert rotating[0].backupCount == PY_LOG_FILE_BACKUP_COUNT
    assert isinstance(rotating[0].formatter, RedactingFormatter)
    assert root.level == logging.ERROR


def test_console_handler_added_when_enabled(tmp_path) -> None:
    # Mirrors the cloud backend path (file + console).
    log_file = tmp_path / "agent.log"
    root = logging.getLogger()
    before = list(root.handlers)
    configure_logging(
        log_level="INFO", log_file_path=str(log_file), enable_console=True
    )
    added = _handlers_added_by(root, before)

    assert len(_rotating_handlers(added)) == 1
    assert len(_console_handlers(added)) == 1


def test_creates_parent_directory(tmp_path) -> None:
    log_file = tmp_path / "nested" / "logs" / "agent.log"
    configure_logging(
        log_level="ERROR", log_file_path=str(log_file), enable_console=False
    )
    assert log_file.parent.is_dir()


def test_error_level_filters_info(tmp_path) -> None:
    log_file = tmp_path / "agent.log"
    configure_logging(
        log_level="ERROR", log_file_path=str(log_file), enable_console=False
    )
    logger = logging.getLogger("test.level.filter")
    logger.error("boom-marker")
    logger.info("noise-marker")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "boom-marker" in content
    assert "noise-marker" not in content


def test_redaction_is_applied_end_to_end(tmp_path) -> None:
    log_file = tmp_path / "agent.log"
    configure_logging(
        log_level="ERROR", log_file_path=str(log_file), enable_console=False
    )
    logger = logging.getLogger("test.redact")
    logger.error(
        "request failed for %s",
        "https://api.example.com/x?token=super-secret-token-value",
    )
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_file.read_text(encoding="utf-8")
    assert "super-secret-token-value" not in content
    assert "<redacted>" in content


def test_configure_once_only_adjusts_level(tmp_path) -> None:
    log_file = tmp_path / "agent.log"
    configure_logging(
        log_level="ERROR", log_file_path=str(log_file), enable_console=False
    )
    root = logging.getLogger()
    handler_count = len(root.handlers)

    configure_logging(
        log_level="DEBUG", log_file_path=str(log_file), enable_console=False
    )
    assert len(root.handlers) == handler_count  # no duplicate handlers
    assert root.level == logging.DEBUG  # level still adjusted
