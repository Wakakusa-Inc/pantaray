from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from pantaray_agents.agents.action_agent.tools.base import ToolPolicyValidationError
from pantaray_agents.local_runtime.runtime.job_control import DeferredLocalJob
from pantaray_llm.errors.provider_error import ProviderError


@contextmanager
def _boundary() -> Iterator[None]:
    yield


@pytest.mark.parametrize(
    "build",
    [
        lambda: ProviderError(status_code=401, code="PROXY_X", message="rejected"),
        lambda: DeferredLocalJob(job_id="job-1", scheduled_at="2026-09-18T00:00:00Z"),
        lambda: ToolPolicyValidationError(message="not allowed"),
    ],
    ids=lambda build: type(build()).__name__,
)
def test_a_data_carrying_error_survives_a_context_manager(
    build: Callable[[], BaseException],
) -> None:
    """``contextlib`` re-raises by assigning ``__traceback__``.

    A frozen dataclass rejects that assignment, so the original error reached the
    caller as a ``TypeError`` or ``FrozenInstanceError`` and every ``except`` that
    named it was skipped.
    """

    error = build()
    with pytest.raises(type(error)) as caught, _boundary():
        raise error
    assert caught.value is error
