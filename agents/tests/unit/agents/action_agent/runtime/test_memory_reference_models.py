from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.agents.action_agent.runtime.models.memory_reference import (
    MemoryArtifactFileReferenceModel,
    MemoryArtifactReferenceModel,
)


def test_memory_reference_requires_projection_relative_path_and_digest() -> None:
    reference = MemoryArtifactReferenceModel(
        source_type="facts",
        source_record_id="fact-1",
        artifact_id="artifact-1",
        memory_key="memory_artifact:artifact-1",
        logical_updated_at="2026-07-18T00:00:00+00:00",
        files=(
            MemoryArtifactFileReferenceModel(
                storage_path="users/u1/facts/structured_facts.md",
                sha256="a" * 64,
                byte_size=12,
                mime_type="text/markdown",
            ),
        ),
    )

    assert reference.files[0].storage_path.endswith("structured_facts.md")


@pytest.mark.parametrize("path", ["/absolute.md", "../escape.md", "a/../b.md"])
def test_memory_reference_rejects_unsafe_path(path: str) -> None:
    with pytest.raises(ValidationError):
        MemoryArtifactFileReferenceModel(
            storage_path=path,
            sha256="a" * 64,
            byte_size=1,
            mime_type="text/plain",
        )
