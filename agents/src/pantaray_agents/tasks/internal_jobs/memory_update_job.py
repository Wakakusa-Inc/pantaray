from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import ExitStack

from pantaray_agents.local_runtime.memory_catalog.artifact_recovery import (
    recover_pending_artifact_intent_for_source,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemorySource
from pantaray_agents.local_runtime.storage.memory_update_lock import (
    MemoryUpdateLockConflictError,
)
from pantaray_agents.local_runtime.tooling.memory_file_editor import (
    LocalMemoryFileEditorRuntime,
)
from pantaray_agents.tasks.internal_jobs.memory_lock_retry import (
    defer_memory_update_lock_conflict,
)
from pantaray_agents.tasks.job_retry import defer_local_job_if_retryable

type MemoryUpdateSource = tuple[MemorySource, str]


async def run_memory_update_job(
    *,
    runtime: LocalMemoryFileEditorRuntime,
    user_id: str,
    job_id: str,
    process_id: str,
    job_type: str,
    process_pending_status: str,
    resolve_sources: Callable[[], tuple[MemoryUpdateSource, ...]],
    is_complete: Callable[[], Awaitable[bool]],
    run: Callable[[], Awaitable[None]],
) -> None:
    with ExitStack() as lease_stack:
        try:
            lease_stack.enter_context(
                runtime.acquire_user_update_lock(user_id=user_id, owner_id=job_id)
            )
        except MemoryUpdateLockConflictError:
            await defer_memory_update_lock_conflict(
                job_id=job_id,
                process_id=process_id,
                job_type=job_type,
                process_pending_status=process_pending_status,
            )

        try:
            # Resolved under the lock: reading a memory identity races an
            # in-flight publication, and a failure here must defer with the job.
            for source, source_record_id in resolve_sources():
                recover_pending_artifact_intent_for_source(
                    db_path=runtime.db_path,
                    busy_timeout_ms=runtime.busy_timeout_ms,
                    artifact_root=runtime.artifact_root,
                    user_id=user_id,
                    source=source,
                    source_record_id=source_record_id,
                )
            if await is_complete():
                return
            try:
                await run()
            except Exception:
                if await is_complete():
                    return
                raise
        except Exception as exc:
            await defer_local_job_if_retryable(
                exc=exc,
                job_id=job_id,
                process_id=process_id,
                process_pending_status=process_pending_status,
                db_path=runtime.db_path,
                busy_timeout_ms=runtime.busy_timeout_ms,
            )
            raise


__all__ = ["MemoryUpdateSource", "run_memory_update_job"]
