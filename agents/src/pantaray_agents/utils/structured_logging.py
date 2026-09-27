from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import traceback
from collections.abc import Iterator
from typing import Literal, NamedTuple

import jsonschema  # type: ignore[import-untyped]
from pydantic import ValidationError as ModelValidationError

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.utils.log_redaction import redact_text

_FINGERPRINT_LENGTH = 12
_CHAIN_SUMMARY_MAX_LENGTH = 500
_CHAIN_SUMMARY_TRUNCATION_MARK = "..."
_OMITTED_EXCEPTION_MESSAGE = "Exception message omitted: may contain private input"


class _ExceptionFrame(NamedTuple):
    module: str
    function: str
    line: int


def fingerprint_text(
    value: str | None, *, length: int = _FINGERPRINT_LENGTH
) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def log_structured_event(
    logger: logging.Logger,
    *,
    level: Literal["info", "warning", "error"],
    evt: str,
    component: str,
    exception: BaseException | None = None,
    **fields: JSONValue | None,
) -> None:
    payload: dict[str, JSONValue] = {
        "evt": evt,
        "component": component,
    }
    if exception is not None:
        payload["exception_chain"] = _exception_chain(exception)
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    getattr(logger, level)(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def summarize_exception_chain(error: BaseException) -> str:
    """Name every exception in the chain on one bounded, private-input-free line.

    For persisting a failure reason where a stack is not wanted. A class name
    alone does not say which of its raise sites ran, so each entry carries the
    innermost frame that raised it, plus a classified reason when the type has
    one. The chain runs outermost first, so truncation drops the head and keeps
    the root cause.
    """
    summary = " <- ".join(
        _summarize_exception(current) for current in _walk_exception_chain(error)
    )
    if len(summary) <= _CHAIN_SUMMARY_MAX_LENGTH:
        return summary
    kept = _CHAIN_SUMMARY_MAX_LENGTH - len(_CHAIN_SUMMARY_TRUNCATION_MARK)
    return _CHAIN_SUMMARY_TRUNCATION_MARK + summary[-kept:]


def _summarize_exception(error: BaseException) -> str:
    entry = type(error).__name__
    frames = _exception_frames(error)
    if frames:
        innermost = frames[-1]
        entry += f" at {innermost.module}:{innermost.function}:{innermost.line}"
    message = _classify_exception_message(error)
    if message is not None:
        entry += f": {message}"
    return entry


def _exception_chain(error: BaseException) -> list[JSONValue]:
    """Keep diagnostic reasons and frames without inputs, locals, or source lines."""
    return [
        {
            "error_class": type(current).__name__,
            "message": _classify_exception_message(current)
            or _OMITTED_EXCEPTION_MESSAGE,
            "stack": [
                {
                    "module": frame.module,
                    "function": frame.function,
                    "line": frame.line,
                }
                for frame in _exception_frames(current)
            ],
        }
        for current in _walk_exception_chain(error)
    ]


def _exception_frames(error: BaseException) -> list[_ExceptionFrame]:
    return [
        _ExceptionFrame(
            module=str(frame.f_globals.get("__name__", "")),
            function=frame.f_code.co_name,
            line=line,
        )
        for frame, line in traceback.walk_tb(error.__traceback__)
    ]


def _walk_exception_chain(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )


def _classify_exception_message(error: BaseException) -> str | None:
    """Classify one exception into a reason that cannot carry private input.

    ``None`` when the type has no such reason: its own text belongs in neither
    the log nor the database.
    """
    # Validation exception strings include the entire rejected private value.
    if isinstance(error, jsonschema.ValidationError):
        message = "JSON schema validation failed: " + "; ".join(
            f"{issue.validator} at {list(issue.schema_path)}"
            for issue in (error.context or [error])
        )
    elif isinstance(error, ModelValidationError):
        message = f"Model validation failed: {error.error_count()} errors"
    elif isinstance(error, OSError) and error.errno is not None:
        message = os.strerror(error.errno)
    elif isinstance(error, sqlite3.Error):
        message = f"SQLite error: {getattr(error, 'sqlite_errorname', 'unknown')}"
    else:
        return None
    return redact_text(message)


__all__ = ["fingerprint_text", "log_structured_event", "summarize_exception_chain"]
