from __future__ import annotations

from typing import NoReturn
from unittest.mock import MagicMock

import pytest

from pantaray_agents.local_runtime.memory_catalog.errors import (
    MemoryReferenceInputError,
    MemoryReferenceNotFoundError,
)
from pantaray_agents.local_runtime.memory_catalog.models import (
    MemoryContextEpoch,
    MemoryContextItem,
    ResolvedContextItem,
)
from pantaray_agents.local_runtime.memory_catalog.resolver import (
    follow_memory_reference,
)


def test_broken_reference_enqueues_source_revision_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.in_transaction = False
    repairs: list[dict[str, object]] = []

    def raise_not_found(**_kwargs: object) -> NoReturn:
        raise MemoryReferenceNotFoundError("ref mapping is missing")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver."
        "_resolve_memory_reference",
        raise_not_found,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver.enqueue_memory_repair",
        lambda **kwargs: repairs.append(kwargs),
    )

    with pytest.raises(MemoryReferenceNotFoundError):
        follow_memory_reference(
            connection=connection,
            epoch=_epoch(),
            source_handle="ctx-source",
            local_ref_id="ref_1",
            enqueue_repair_on_failure=True,
        )

    assert repairs == [
        {
            "connection": connection,
            "user_id": "user-1",
            "node_id": "node-source",
            "detected_revision_id": "revision-source",
            "reason": "reference_resolution",
        }
    ]
    connection.commit.assert_called_once_with()


def test_invalid_reference_input_does_not_enqueue_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.in_transaction = False
    enqueue = MagicMock()

    def raise_invalid_input(**_kwargs: object) -> NoReturn:
        raise MemoryReferenceInputError("visible source does not contain the ref")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver."
        "_resolve_memory_reference",
        raise_invalid_input,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver.enqueue_memory_repair",
        enqueue,
    )

    with pytest.raises(MemoryReferenceInputError):
        follow_memory_reference(
            connection=connection,
            epoch=_epoch(),
            source_handle="ctx-source",
            local_ref_id="ref_unknown",
            enqueue_repair_on_failure=True,
        )

    enqueue.assert_not_called()
    connection.commit.assert_not_called()


def test_read_only_resolution_does_not_enqueue_broken_reference_repair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.in_transaction = False
    enqueue = MagicMock()

    def raise_not_found(**_kwargs: object) -> NoReturn:
        raise MemoryReferenceNotFoundError("ref mapping is missing")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver."
        "_resolve_memory_reference",
        raise_not_found,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.resolver.enqueue_memory_repair",
        enqueue,
    )

    with pytest.raises(MemoryReferenceNotFoundError):
        follow_memory_reference(
            connection=connection,
            epoch=_epoch(),
            source_handle="ctx-source",
            local_ref_id="ref_1",
            enqueue_repair_on_failure=False,
        )

    enqueue.assert_not_called()
    connection.commit.assert_not_called()


def _epoch() -> MemoryContextEpoch:
    return MemoryContextEpoch(
        epoch_id="epoch-1",
        run_id="run-1",
        user_id="user-1",
        items=(
            ResolvedContextItem(
                item=MemoryContextItem(
                    context_handle="ctx-source",
                    source="fact",
                    label="fact",
                    source_path="facts/index.md",
                    heading_path=None,
                    content='Claim. [[ref:ref_1 note:"related"]]',
                    observed_at="2026-08-07T00:00:00Z",
                ),
                user_id="user-1",
                fragment_id="fragment-source",
                revision_id="revision-source",
                node_id="node-source",
                reference_depth=0,
            ),
        ),
    )
