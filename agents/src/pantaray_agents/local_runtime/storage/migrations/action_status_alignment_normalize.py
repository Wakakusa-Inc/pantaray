from __future__ import annotations

import json

from pantaray_agents.action_status import (
    ACTION_FAILURE_CODE_PROCESSING_ERROR,
    ACTION_FAILURE_CODE_TIMEOUT,
    ACTION_FAILURE_MESSAGE_RUNNING_FAILED,
    ACTION_FAILURE_STAGE_RUNNING_FAILED,
)

from .specs import MigrationError

ALLOWED_ACTION_RUNTIME_STATUSES = frozenset(
    {"idle", "processing", "success", "error", "canceled"}
)
LEGACY_ACTION_ERROR_STATUSES = frozenset({"timeout", "abandoned", "superseded"})
LEGACY_PROCESS_STATUS_MAP = {
    "enqueued": "enqueued",
    "running": "running",
    "paused": "paused",
    "success": "completed",
    "completed": "completed",
    "error": "failed",
    "failed": "failed",
    "canceled": "canceled",
    "timeout": "failed",
    "abandoned": "failed",
}
ALLOWED_JOB_STATUSES = frozenset(
    {
        "queued",
        "running",
        "paused",
        "retryable_error",
        "blocked",
        "completed",
        "failed",
        "abandoned",
        "canceled",
    }
)


def normalize_action_status_row(row: dict[str, object]) -> dict[str, object]:
    original_status = normalize_optional_status(row.get("action_status"))
    normalized_status = normalize_action_status(original_status)
    row["action_status"] = normalized_status
    (
        row["action_failure_code"],
        row["action_failure_stage"],
        row["action_failure_message_public"],
    ) = normalize_failure_triplet(
        original_status=original_status,
        normalized_status=normalized_status,
        failure_code=row.get("action_failure_code"),
        failure_stage=row.get("action_failure_stage"),
        failure_message=row.get("action_failure_message_public"),
    )
    return row


def normalize_action_terminal_row(row: dict[str, object]) -> dict[str, object]:
    original_status = normalize_optional_status(row.get("status"))
    row["status"] = normalize_action_status(original_status)
    return row


def normalize_process_row(row: dict[str, object]) -> dict[str, object]:
    row["status"] = normalize_process_status(str(row["status"] or ""))
    return row


def normalize_job_row(row: dict[str, object]) -> dict[str, object]:
    row["status"] = normalize_job_status(str(row["status"] or ""))
    return row


def normalize_payload_status(payload: dict[str, object]) -> dict[str, object]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload
    original_status = normalize_optional_status(data.get("status"))
    normalized_status = normalize_action_terminal_status(original_status)
    if normalized_status is None:
        return payload
    data["status"] = normalized_status
    failure_code, failure_stage, failure_message = normalize_failure_triplet(
        original_status=original_status,
        normalized_status=normalized_status,
        failure_code=data.get("failure_code"),
        failure_stage=data.get("failure_stage"),
        failure_message=data.get("failure_message_public"),
    )
    if failure_code is not None:
        data["failure_code"] = failure_code
        data["failure_stage"] = failure_stage
        data["failure_message_public"] = failure_message
    payload["data"] = data
    return payload


def normalize_action_status(status: str | None) -> str | None:
    if status is None:
        return None
    if status in ALLOWED_ACTION_RUNTIME_STATUSES:
        return status
    if status in LEGACY_ACTION_ERROR_STATUSES:
        return "error"
    raise MigrationError(f"Unsupported legacy action_status: {status}")


def normalize_action_terminal_status(status: str | None) -> str | None:
    if status is None:
        return None
    normalized = normalize_action_status(status)
    if normalized in {"idle", "processing"}:
        raise MigrationError(
            f"Terminal payload cannot keep non-terminal status: {status}"
        )
    return normalized


def normalize_process_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in LEGACY_PROCESS_STATUS_MAP:
        raise MigrationError(f"Unsupported legacy process status: {status}")
    return LEGACY_PROCESS_STATUS_MAP[normalized]


def normalize_job_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in ALLOWED_JOB_STATUSES:
        raise MigrationError(f"Unsupported legacy job status: {status}")
    return normalized


def normalize_failure_triplet(
    *,
    original_status: str | None,
    normalized_status: str | None,
    failure_code: object,
    failure_stage: object,
    failure_message: object,
) -> tuple[str | None, str | None, str | None]:
    code = normalize_optional_string(failure_code)
    stage = normalize_optional_string(failure_stage)
    message = normalize_optional_string(failure_message)
    if normalized_status != "error":
        return code, stage, message
    if code and stage and message:
        return code, stage, message
    if original_status == "timeout":
        return (
            code or ACTION_FAILURE_CODE_TIMEOUT,
            stage or ACTION_FAILURE_STAGE_RUNNING_FAILED,
            message or ACTION_FAILURE_MESSAGE_RUNNING_FAILED,
        )
    return (
        code or ACTION_FAILURE_CODE_PROCESSING_ERROR,
        stage or ACTION_FAILURE_STAGE_RUNNING_FAILED,
        message or ACTION_FAILURE_MESSAGE_RUNNING_FAILED,
    )


def decode_json_object(raw_value: object) -> dict[str, object]:
    if not isinstance(raw_value, str):
        raise MigrationError("expected JSON text column to be a string")
    decoded = json.loads(raw_value)
    if not isinstance(decoded, dict):
        raise MigrationError("expected JSON object payload")
    return decoded


def json_dumps_compact(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_optional_status(value: object) -> str | None:
    text = normalize_optional_string(value)
    return text.lower() if text is not None else None


def normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
