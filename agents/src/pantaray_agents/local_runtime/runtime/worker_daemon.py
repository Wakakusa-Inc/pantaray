from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Final, cast

from pantaray_agents.tasks.types import ActionJobRuntimePayload
from pantaray_agents.utils.structured_logging import log_structured_event

from .identity import current_owner_id
from .job_capacity import CapacityLease, LocalWorkerCapacity
from .job_claim import (
    ClaimedLocalJob,
    claim_next_pending_job,
    peek_next_pending_job_type,
)
from .job_executor import execute_claimed_local_job
from .job_types import (
    LOCAL_ACTION_JOB_TYPE,
    LOCAL_ACTION_SUBAGENT_JOB_TYPE,
    LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
    LOCAL_INSIGHT_JOB_TYPE,
    LOCAL_MEMORY_UPDATE_JOB_TYPE,
    LOCAL_SUGGESTION_JOB_TYPE,
)
from .local_worker import (
    LocalJobExecutionError,
    LocalWorkerSpec,
    build_default_local_worker_specs,
    claimable_specs,
)
from .memory_embedding_scheduler import MemoryEmbeddingProjectionResult
from .periodic_schedule import (
    MemoryEmbeddingProjectionSlot,
    PeriodicTaskContext,
    build_periodic_schedule,
    run_due_periodic_tasks,
)
from .runtime_env import read_local_runtime_artifact_root, read_local_runtime_db_config
from .runtime_lock_coordinator import (
    RuntimeProcessLockLease,
    release_runtime_lock_lease,
)

logger = logging.getLogger(__name__)

_LOCAL_WORKER_IDLE_SLEEP_SECONDS: Final[float] = 0.1
_LOCAL_WORKER_STOP_WAIT_SECONDS: Final[float] = 1.0
_LOCAL_WORKER_DAEMON_OWNER: Final[str] = "local-worker-daemon"
_GENERAL_WORKER_MAX_RUNNING: Final[int] = 4
_GENERAL_JOB_TYPE_LIMITS: Final[dict[str, int]] = {
    LOCAL_SUGGESTION_JOB_TYPE: 1,
    LOCAL_ACTIVITY_SUMMARY_JOB_TYPE: 1,
    LOCAL_INSIGHT_JOB_TYPE: 1,
    LOCAL_MEMORY_UPDATE_JOB_TYPE: 1,
}
_THREAD_LOCK = threading.Lock()
_STOP_EVENT = threading.Event()
_THREAD: threading.Thread | None = None
_RUNTIME_PROCESS_LOCK: RuntimeProcessLockLease | None = None


class _WorkerDaemonFatalError(RuntimeError):
    """The worker cannot safely continue after an ambiguous dispatch result."""


def _run_action_job_runner(job_payload: object) -> None:
    from pantaray_agents.tasks.action_job import run_action_job

    run_action_job(cast(ActionJobRuntimePayload, job_payload))


def _select_next_pending_job_type(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    specs: Mapping[str, LocalWorkerSpec],
    capacity: LocalWorkerCapacity,
    owner_user_id: str,
) -> str | None:
    claimable_job_types = capacity.claimable_job_types(tuple(specs))
    if not claimable_job_types:
        return None
    selected_job_type = peek_next_pending_job_type(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        job_types=claimable_job_types,
        owner_user_id=owner_user_id,
    )
    return selected_job_type


def _claim_reserved_job(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    job_type: str,
    spec: LocalWorkerSpec,
    owner_user_id: str,
) -> ClaimedLocalJob | None:
    return claim_next_pending_job(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        job_type=job_type,
        owner_user_id=owner_user_id,
        claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
        process_running_status=spec.process_running_status,
        expected_process_pending_status=spec.process_pending_status,
    )


def _run_claimed_job_in_executor(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    claimed_job: ClaimedLocalJob,
    spec: LocalWorkerSpec,
    capacity: LocalWorkerCapacity,
    lease: CapacityLease,
) -> None:
    try:
        execute_claimed_local_job(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
            claimed_job=claimed_job,
            spec=spec,
        )
    except LocalJobExecutionError as exc:
        log_structured_event(
            logger,
            level="warning",
            evt="LOCAL_WORKER_DAEMON_JOB_FAILED",
            component="local_runtime.worker_daemon",
            job_type=exc.job_type,
            claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
            error_class=exc.original_exception_type,
        )
    except Exception as exc:
        log_structured_event(
            logger,
            level="error",
            evt="LOCAL_WORKER_DAEMON_FAILED",
            component="local_runtime.worker_daemon",
            job_type=spec.job_type,
            claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
            error_class=exc.__class__.__name__,
        )
    finally:
        try:
            capacity.release(lease)
        except Exception as exc:
            log_structured_event(
                logger,
                level="error",
                evt="LOCAL_WORKER_DAEMON_CAPACITY_RELEASE_FAILED",
                component="local_runtime.worker_daemon",
                job_type=spec.job_type,
                claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
                error_class=exc.__class__.__name__,
            )


def _submit_next_reserved_job(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    executor: ThreadPoolExecutor,
    specs: Mapping[str, LocalWorkerSpec],
    capacity: LocalWorkerCapacity,
    owner_user_id: str,
) -> bool:
    lease: CapacityLease | None = None
    claimed_job: ClaimedLocalJob | None = None
    spec: LocalWorkerSpec | None = None
    job_type: str | None = None
    try:
        job_type = _select_next_pending_job_type(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            specs=specs,
            capacity=capacity,
            owner_user_id=owner_user_id,
        )
        if job_type is None:
            return False
        spec = specs[job_type]
        lease = capacity.reserve(job_type)
        claimed_job = _claim_reserved_job(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            job_type=job_type,
            spec=spec,
            owner_user_id=owner_user_id,
        )
        if claimed_job is None:
            capacity.release(lease)
            lease = None
            return False
    except Exception as exc:
        if lease is not None:
            capacity.release(lease)
        log_structured_event(
            logger,
            level="error",
            evt="LOCAL_WORKER_DAEMON_SUBMIT_FAILED",
            component="local_runtime.worker_daemon",
            job_type=job_type,
            claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
            error_class=exc.__class__.__name__,
        )
        return False

    assert lease is not None
    assert claimed_job is not None
    assert spec is not None
    try:
        executor.submit(
            _run_claimed_job_in_executor,
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            claimed_job=claimed_job,
            spec=spec,
            capacity=capacity,
            lease=lease,
        )
    except Exception as exc:
        log_structured_event(
            logger,
            level="error",
            evt="LOCAL_WORKER_DAEMON_SUBMIT_FAILED",
            component="local_runtime.worker_daemon",
            job_type=job_type,
            claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
            error_class=exc.__class__.__name__,
        )
        raise _WorkerDaemonFatalError(
            "executor submit acceptance is unknown; worker must stop"
        ) from exc
    return True


def _release_runtime_lock_after_worker_exit(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    lease: RuntimeProcessLockLease,
) -> None:
    global _THREAD, _RUNTIME_PROCESS_LOCK
    with _THREAD_LOCK:
        if _RUNTIME_PROCESS_LOCK == lease:
            _RUNTIME_PROCESS_LOCK = None
        if _THREAD is threading.current_thread():
            _THREAD = None
    release_result = release_runtime_lock_lease(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        lease=lease,
    )
    if release_result.warning_message is not None:
        logger.warning("%s", release_result.warning_message)


def _sleep_worker_idle() -> None:
    if _STOP_EVENT.is_set():
        time.sleep(_LOCAL_WORKER_IDLE_SLEEP_SECONDS)
        return
    _STOP_EVENT.wait(timeout=_LOCAL_WORKER_IDLE_SLEEP_SECONDS)


def _consume_memory_embedding_projection_result(
    future: Future[MemoryEmbeddingProjectionResult],
) -> None:
    try:
        result = future.result()
    except Exception as exc:
        log_structured_event(
            logger,
            level="error",
            evt="LOCAL_MEMORY_EMBEDDING_PROJECTION_FAILED",
            component="local_runtime.worker_daemon",
            error_class=exc.__class__.__name__,
        )
        return
    if result.selected_count == 0:
        return
    log_structured_event(
        logger,
        level="info",
        evt="LOCAL_MEMORY_EMBEDDING_PROJECTION_COMPLETED",
        component="local_runtime.worker_daemon",
        selected_count=result.selected_count,
        indexed_count=result.indexed_count,
        failed_count=result.failed_count,
    )


def _worker_loop(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    artifact_root: Path,
    runtime_process_lock: RuntimeProcessLockLease,
) -> None:
    action_executor: ThreadPoolExecutor | None = None
    general_executor: ThreadPoolExecutor | None = None
    embedding_executor: ThreadPoolExecutor | None = None
    fatal_shutdown = False
    try:
        specs = build_default_local_worker_specs(action_runner=_run_action_job_runner)
        agent_job_types = (LOCAL_ACTION_JOB_TYPE, LOCAL_ACTION_SUBAGENT_JOB_TYPE)
        action_specs = {job_type: specs[job_type] for job_type in agent_job_types}
        general_specs = {
            job_type: spec
            for job_type, spec in specs.items()
            if job_type not in agent_job_types
        }
        # Actions and their subagents run concurrently without a global cap (product
        # decision). Turns of one Action stay sequential through the jobs/processes
        # active-Action unique indexes, and each parent keeps at most four active
        # subagents through the processes trigger from migration 0093.
        action_capacity = LocalWorkerCapacity(
            max_running=None,
            job_type_limits=dict.fromkeys(agent_job_types),
        )
        general_capacity = LocalWorkerCapacity(
            max_running=_GENERAL_WORKER_MAX_RUNNING,
            job_type_limits=_GENERAL_JOB_TYPE_LIMITS,
        )
        # ThreadPoolExecutor requires a bound; it starts threads lazily and reuses
        # idle ones, so sys.maxsize gives one thread per running Action or subagent.
        action_executor = ThreadPoolExecutor(
            max_workers=sys.maxsize,
            thread_name_prefix="local-action-worker",
        )
        general_executor = ThreadPoolExecutor(
            max_workers=_GENERAL_WORKER_MAX_RUNNING,
            thread_name_prefix="local-general-worker",
        )
        embedding_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="local-memory-embedding-worker",
        )
        embedding_slot = MemoryEmbeddingProjectionSlot(embedding_executor, _STOP_EVENT)
        periodic_tasks = build_periodic_schedule(embedding_slot=embedding_slot)
        next_periodic_run_monotonic = {task.name: 0.0 for task in periodic_tasks}
        while (
            not _STOP_EVENT.is_set()
            or (action_capacity.active_count() + general_capacity.active_count()) > 0
            or embedding_slot.is_busy()
        ):
            submitted = False
            try:
                embedding_future = embedding_slot.consume_if_done()
                if embedding_future is not None:
                    _consume_memory_embedding_projection_result(embedding_future)
                if not _STOP_EVENT.is_set():
                    owner_user_id = current_owner_id()
                    claimable_action_specs = claimable_specs(action_specs)
                    claimable_general_specs = claimable_specs(general_specs)
                    if claimable_action_specs:
                        submitted = _submit_next_reserved_job(
                            db_path=db_path,
                            busy_timeout_ms=busy_timeout_ms,
                            executor=action_executor,
                            specs=claimable_action_specs,
                            capacity=action_capacity,
                            owner_user_id=owner_user_id,
                        )
                    while (
                        claimable_general_specs
                        and general_capacity.has_available_slot()
                    ):
                        general_submitted = _submit_next_reserved_job(
                            db_path=db_path,
                            busy_timeout_ms=busy_timeout_ms,
                            executor=general_executor,
                            specs=claimable_general_specs,
                            capacity=general_capacity,
                            owner_user_id=owner_user_id,
                        )
                        if not general_submitted:
                            break
                        submitted = True
                    worker_is_idle = (
                        not submitted
                        and action_capacity.active_count() == 0
                        and general_capacity.active_count() == 0
                    )
                    # Periodic enqueues run after submission, so their jobs wait at most one idle tick (~100 ms) to be claimed.
                    next_periodic_run_monotonic = run_due_periodic_tasks(
                        tasks=periodic_tasks,
                        context=PeriodicTaskContext(
                            db_path=db_path,
                            busy_timeout_ms=busy_timeout_ms,
                            artifact_root=artifact_root,
                            owner_user_id=owner_user_id,
                            worker_is_idle=worker_is_idle,
                        ),
                        next_run_monotonic_by_task=next_periodic_run_monotonic,
                    )
            except _WorkerDaemonFatalError:
                fatal_shutdown = True
                raise
            except Exception as exc:
                log_structured_event(
                    logger,
                    level="error",
                    evt="LOCAL_WORKER_DAEMON_FAILED",
                    component="local_runtime.worker_daemon",
                    claimed_by=_LOCAL_WORKER_DAEMON_OWNER,
                    error_class=exc.__class__.__name__,
                )
            if not submitted:
                _sleep_worker_idle()
    finally:
        if action_executor is not None:
            action_executor.shutdown(wait=fatal_shutdown, cancel_futures=False)
        if general_executor is not None:
            general_executor.shutdown(wait=fatal_shutdown, cancel_futures=False)
        if embedding_executor is not None:
            embedding_executor.shutdown(wait=fatal_shutdown, cancel_futures=False)
        _release_runtime_lock_after_worker_exit(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            lease=runtime_process_lock,
        )


def start_local_action_worker_daemon(
    *, runtime_process_lock: RuntimeProcessLockLease
) -> None:
    global _THREAD, _RUNTIME_PROCESS_LOCK
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    artifact_root = read_local_runtime_artifact_root()
    with _THREAD_LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            raise RuntimeError("local worker daemon is already running")
        if _THREAD is not None and not _THREAD.is_alive():
            _THREAD = None
        if _RUNTIME_PROCESS_LOCK is not None:
            release_result = release_runtime_lock_lease(
                db_path=db_path,
                busy_timeout_ms=busy_timeout_ms,
                lease=_RUNTIME_PROCESS_LOCK,
            )
            if release_result.warning_message is not None:
                logger.warning("%s", release_result.warning_message)
            _RUNTIME_PROCESS_LOCK = None
        _STOP_EVENT.clear()
        thread = threading.Thread(
            target=_worker_loop,
            kwargs={
                "db_path": db_path,
                "busy_timeout_ms": busy_timeout_ms,
                "artifact_root": artifact_root,
                "runtime_process_lock": runtime_process_lock,
            },
            name="local-worker",
            daemon=True,
        )
        _THREAD = thread
        _RUNTIME_PROCESS_LOCK = runtime_process_lock
        try:
            thread.start()
        except Exception:
            _THREAD = None
            if _RUNTIME_PROCESS_LOCK == runtime_process_lock:
                _RUNTIME_PROCESS_LOCK = None
            raise


def stop_local_action_worker_daemon() -> None:
    with _THREAD_LOCK:
        thread = _THREAD
        _STOP_EVENT.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=_LOCAL_WORKER_STOP_WAIT_SECONDS)


__all__ = [
    "start_local_action_worker_daemon",
    "stop_local_action_worker_daemon",
]
