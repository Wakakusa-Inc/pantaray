from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.runtime.job_capacity import LocalWorkerCapacity
from pantaray_agents.local_runtime.storage.migrations import MigrationError


def test_local_worker_capacity_rejects_double_release() -> None:
    capacity = LocalWorkerCapacity(
        max_running=1,
        job_type_limits={"structure_facts": 1},
    )
    lease = capacity.reserve("structure_facts")

    capacity.release(lease)

    with pytest.raises(MigrationError, match="capacity lease is not active"):
        capacity.release(lease)
