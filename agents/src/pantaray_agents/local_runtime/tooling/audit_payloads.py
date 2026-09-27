from __future__ import annotations

from hashlib import sha256

from pantaray_agents.schema.agent.base import JSONValue

RUN_PYTHON_CODE_FIELD = "code"
RUN_PYTHON_CODE_SHA256_FIELD = "sha256"
RUN_PYTHON_CODE_SIZE_BYTES_FIELD = "size_bytes"
RUN_PYTHON_CODE_LINE_COUNT_FIELD = "line_count"


class AuditPayloadError(RuntimeError):
    """Raised when a tool audit payload cannot be safely summarized."""


def build_run_python_request_audit_args(
    *,
    args: dict[str, JSONValue],
    generated_python_code: str | None = None,
) -> dict[str, JSONValue]:
    code_value = (
        generated_python_code
        if generated_python_code is not None
        else args.get(RUN_PYTHON_CODE_FIELD)
    )
    if not isinstance(code_value, str) or not code_value:
        raise AuditPayloadError("run_python audit payload requires non-empty code")
    encoded = code_value.encode("utf-8")
    sanitized_args = dict(args)
    sanitized_args[RUN_PYTHON_CODE_FIELD] = {
        RUN_PYTHON_CODE_SHA256_FIELD: sha256(encoded).hexdigest(),
        RUN_PYTHON_CODE_SIZE_BYTES_FIELD: len(encoded),
        RUN_PYTHON_CODE_LINE_COUNT_FIELD: len(code_value.splitlines()),
    }
    return sanitized_args


__all__ = ["AuditPayloadError", "build_run_python_request_audit_args"]
