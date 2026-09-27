from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from pantaray_agents.schema.repository_errors import (
    is_retryable_repository_exception,
)
from pantaray_agents.utils.structured_logging import (
    fingerprint_text,
    log_structured_event,
    summarize_exception_chain,
)
from pantaray_agents.utils.trace_context import TraceContextManager

from ..storage.migrations import MigrationError
from .db_execution_context import bind_local_runtime_db_execution_context
from .identity import OwnerMismatchError, verify_current_owner
from .job_claim import (
    FINAL_JOB_STATUS,
    PROCESS_RUNTIME_STATUS,
    ClaimedLocalJob,
    finalize_local_job,
)
from .job_control import (
    DeferredLocalJob,
    requeue_claimed_local_job_after_dispatch_failure,
)
from .job_route_identity import bind_job_route_identity

logger = logging.getLogger(__name__)
_PERSIST_RETRY_INITIAL_DELAY_SECONDS = 0.1
_PERSIST_RETRY_MAX_DELAY_SECONDS = 2.0


class LocalJobExecutionError(RuntimeError):
    def __init__(self, *, job_type: str, original_exception: BaseException) -> None:
        self.job_type = job_type
        self.original_exception_type = original_exception.__class__.__name__
        super().__init__(
            f"{job_type} job failed: error_class={self.original_exception_type}"
        )


class LocalJobPayloadIdentityError(MigrationError):
    """A durable payload does not belong to the job that claimed it."""


class LocalWorkerSpecLike(Protocol):
    @property
    def job_type(self) -> str: ...

    @property
    def parse_payload(self) -> Callable[[str], object]: ...

    @property
    def run(self) -> Callable[[object], None]: ...

    @property
    def process_pending_status(self) -> PROCESS_RUNTIME_STATUS: ...

    @property
    def process_success_status(self) -> PROCESS_RUNTIME_STATUS: ...

    @property
    def process_failure_status(self) -> PROCESS_RUNTIME_STATUS: ...

    @property
    def success_job_status(self) -> FINAL_JOB_STATUS: ...

    @property
    def failure_job_status(self) -> FINAL_JOB_STATUS: ...

    @property
    def finalize_after_run(self) -> bool: ...


def execute_claimed_local_job(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    claimed_by: str,
    claimed_job: ClaimedLocalJob,
    spec: LocalWorkerSpecLike,
) -> bool:
    try:
        verify_current_owner(claimed_job["user_id"])
    except OwnerMismatchError:
        persist_local_job_transition_with_retry(
            operation=lambda: requeue_claimed_local_job_after_dispatch_failure(
                db_path=str(db_path),
                busy_timeout_ms=busy_timeout_ms,
                job_id=claimed_job["job_id"],
                process_id=claimed_job["process_id"],
                process_pending_status=spec.process_pending_status,
            ),
            retry_event="LOCAL_JOB_REQUEUE_RETRYING",
        )
        return False

    dispatched_to_runner = False
    try:
        payload = spec.parse_payload(claimed_job["payload_json"])
        _validate_job_payload_identity(claimed_job=claimed_job, payload=payload)
        with bind_local_runtime_db_execution_context(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
        ):
            with TraceContextManager(
                **_build_job_trace_context_kwargs(
                    job_type=spec.job_type,
                    claimed_job=claimed_job,
                    payload=payload,
                )
            ):
                # The identity is taken here rather than at claim time: a job
                # that has not started yet loses nothing by starting over on the
                # newer value (design 6.2).
                with bind_job_route_identity(
                    job_id=claimed_job["job_id"],
                    process_id=claimed_job["process_id"],
                    process_pending_status=spec.process_pending_status,
                    db_path=db_path,
                    busy_timeout_ms=busy_timeout_ms,
                    # A spec this executor finalizes is a background job: no
                    # terminal has been written for it, so the run can go back
                    # to `queued`. An Action and its subagent write their own
                    # terminal through the Stop fence and must not run again.
                    requeue_on_change=spec.finalize_after_run,
                ):
                    dispatched_to_runner = True
                    spec.run(payload)
    except DeferredLocalJob:
        return True
    except Exception as exc:
        log_structured_event(
            logger,
            level="error",
            evt="LOCAL_JOB_FAILED",
            exception=exc,
            component="local_runtime.local_worker",
            job_type=spec.job_type,
            claimed_by=claimed_by,
            error_class=exc.__class__.__name__,
            **_build_safe_job_log_fields(claimed_job=claimed_job),
        )
        if spec.finalize_after_run or not dispatched_to_runner:
            _finalize_local_job_with_retry(
                db_path=str(db_path),
                busy_timeout_ms=busy_timeout_ms,
                job_id=claimed_job["job_id"],
                final_status=spec.failure_job_status,
                process_final_status=spec.process_failure_status,
                # The rotating log file is the only other place this reason
                # exists, so the terminal keeps it where the job is read.
                failure_message=summarize_exception_chain(exc),
            )
        raise LocalJobExecutionError(
            job_type=spec.job_type,
            original_exception=exc,
        ) from exc

    if spec.finalize_after_run:
        _finalize_local_job_with_retry(
            db_path=str(db_path),
            busy_timeout_ms=busy_timeout_ms,
            job_id=claimed_job["job_id"],
            final_status=spec.success_job_status,
            process_final_status=spec.process_success_status,
        )
    return True


def _finalize_local_job_with_retry(
    *,
    db_path: str,
    busy_timeout_ms: int,
    job_id: str,
    final_status: FINAL_JOB_STATUS,
    process_final_status: PROCESS_RUNTIME_STATUS,
    failure_message: str | None = None,
) -> None:
    """Persist only the terminal transition again after a transient DB failure."""
    persist_local_job_transition_with_retry(
        operation=lambda: finalize_local_job(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            job_id=job_id,
            final_status=final_status,
            process_final_status=process_final_status,
            failure_message=failure_message,
        ),
        retry_event="LOCAL_JOB_FINALIZE_RETRYING",
    )


def persist_local_job_transition_with_retry[ResultT](
    *,
    operation: Callable[[], ResultT],
    retry_event: str,
) -> ResultT:
    delay_seconds = _PERSIST_RETRY_INITIAL_DELAY_SECONDS
    while True:
        try:
            return operation()
        except Exception as exc:
            if not is_retryable_repository_exception(exc):
                raise
            log_structured_event(
                logger,
                level="warning",
                evt=retry_event,
                component="local_runtime.local_worker",
                error_class=exc.__class__.__name__,
                retry_delay_seconds=delay_seconds,
            )
            time.sleep(delay_seconds)
            delay_seconds = min(
                delay_seconds * 2,
                _PERSIST_RETRY_MAX_DELAY_SECONDS,
            )


def _build_safe_job_log_fields(
    *,
    claimed_job: Mapping[str, object],
) -> dict[str, str | None]:
    job_id = claimed_job.get("job_id")
    user_id = claimed_job.get("user_id")
    process_id = claimed_job.get("process_id")
    return {
        "job_id_fp": fingerprint_text(str(job_id or "") or None),
        "process_id_fp": fingerprint_text(str(process_id or "") or None),
        "user_id_fp": fingerprint_text(str(user_id or "") or None),
    }


def _validate_job_payload_identity(
    *,
    claimed_job: Mapping[str, object],
    payload: object,
) -> None:
    if not isinstance(payload, Mapping):
        raise LocalJobPayloadIdentityError("local job payload must be an object")
    for field in ("job_id", "process_id", "user_id"):
        payload_value = payload.get(field)
        claimed_value = claimed_job.get(field)
        if (
            _read_non_empty_str(payload_value) is None
            or _read_non_empty_str(claimed_value) is None
            or payload_value != claimed_value
        ):
            raise LocalJobPayloadIdentityError(
                f"local job payload {field} does not match claimed job"
            )


def _read_non_empty_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _build_job_trace_context_kwargs(
    *,
    job_type: str,
    claimed_job: Mapping[str, object],
    payload: object,
) -> dict[str, object]:
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    job_id = _read_non_empty_str(payload_mapping.get("job_id")) or _read_non_empty_str(
        claimed_job.get("job_id")
    )
    process_id = _read_non_empty_str(payload_mapping.get("process_id"))
    extra: dict[str, object] = {"job_type": job_type}
    if process_id:
        extra["process_id"] = process_id
    log_id = _read_non_empty_str(payload_mapping.get("log_id"))
    if log_id:
        extra["activity_log_id"] = log_id
    trace_context: dict[str, object] = {
        "user_id": _read_non_empty_str(payload_mapping.get("user_id"))
        or _read_non_empty_str(claimed_job.get("user_id")),
        "local_job_id": job_id,
        "suggestion_id": _read_non_empty_str(payload_mapping.get("suggestion_id")),
        "action_id": _read_non_empty_str(payload_mapping.get("action_id")),
        "extra": extra,
    }
    return trace_context


__all__ = [
    "LocalJobExecutionError",
    "LocalJobPayloadIdentityError",
    "execute_claimed_local_job",
]
