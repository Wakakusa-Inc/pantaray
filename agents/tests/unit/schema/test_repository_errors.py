from __future__ import annotations

import errno

import pytest

from pantaray_agents.schema.repository_errors import (
    is_retryable_repository_exception,
)


@pytest.mark.parametrize("error_number", (errno.ENOSPC, errno.EIO))
def test_storage_capacity_and_io_errors_are_retryable(error_number: int) -> None:
    assert is_retryable_repository_exception(OSError(error_number, "storage failure"))
