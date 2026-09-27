from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from threading import Lock

from pantaray_agents.local_runtime.storage.migrations import MigrationError


@dataclass(frozen=True, slots=True)
class CapacityLease:
    job_type: str
    token: int


class LocalWorkerCapacity:
    """Counts running jobs of one worker pool; a ``None`` limit means unbounded."""

    def __init__(
        self,
        *,
        max_running: int | None,
        job_type_limits: Mapping[str, int | None],
    ) -> None:
        if max_running is not None and max_running <= 0:
            raise MigrationError("max_running must be positive")
        if not job_type_limits:
            raise MigrationError("job_type_limits must not be empty")
        for job_type, limit in job_type_limits.items():
            if not job_type.strip():
                raise MigrationError("job_type_limits must not contain empty job types")
            if limit is not None and limit <= 0:
                raise MigrationError("job_type_limits must contain positive limits")
        self._max_running = max_running
        self._job_type_limits = dict(job_type_limits)
        self._active_by_type: Counter[str] = Counter()
        self._active_lease_tokens: set[int] = set()
        self._next_lease_token = 0
        self._lock = Lock()

    def has_available_slot(self) -> bool:
        with self._lock:
            return not self._is_full_unlocked()

    def claimable_job_types(self, job_types: tuple[str, ...]) -> tuple[str, ...]:
        with self._lock:
            if self._is_full_unlocked():
                return ()
            return tuple(
                job_type
                for job_type in job_types
                if job_type in self._job_type_limits
                and not self._is_job_type_full_unlocked(job_type)
            )

    def reserve(self, job_type: str) -> CapacityLease:
        with self._lock:
            if self._is_full_unlocked():
                raise MigrationError("worker capacity is full")
            if job_type not in self._job_type_limits:
                raise MigrationError(f"unsupported local worker job_type: {job_type}")
            if self._is_job_type_full_unlocked(job_type):
                raise MigrationError(
                    f"local worker job_type is at capacity: {job_type}"
                )
            self._next_lease_token += 1
            lease = CapacityLease(job_type=job_type, token=self._next_lease_token)
            self._active_by_type[job_type] += 1
            self._active_lease_tokens.add(lease.token)
        return lease

    def release(self, lease: CapacityLease) -> None:
        with self._lock:
            if lease.token not in self._active_lease_tokens:
                raise MigrationError(
                    f"local worker capacity lease is not active: {lease.job_type}"
                )
            current = self._active_by_type[lease.job_type]
            if current <= 0:
                raise MigrationError(
                    f"local worker capacity count is inconsistent: {lease.job_type}"
                )
            if current == 1:
                del self._active_by_type[lease.job_type]
            else:
                self._active_by_type[lease.job_type] = current - 1
            self._active_lease_tokens.remove(lease.token)

    def active_count(self) -> int:
        with self._lock:
            return self._active_total_unlocked()

    def _active_total_unlocked(self) -> int:
        return sum(self._active_by_type.values())

    def _is_full_unlocked(self) -> bool:
        return (
            self._max_running is not None
            and self._active_total_unlocked() >= self._max_running
        )

    def _is_job_type_full_unlocked(self, job_type: str) -> bool:
        limit = self._job_type_limits[job_type]
        return limit is not None and self._active_by_type[job_type] >= limit


__all__ = ["CapacityLease", "LocalWorkerCapacity"]
