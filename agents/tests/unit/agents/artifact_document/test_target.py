from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pantaray_agents.agents.artifact_document import (
    ArtifactDocumentStore,
    ArtifactDocumentTarget,
)
from pantaray_agents.utils.artifact_patch.errors import ArtifactPatchConflictError

TARGET_TEMPLATE = "users/{user_id}/generated/doc.md"


@pytest.mark.asyncio
async def test_artifact_document_target_writes_reads_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    target = ArtifactDocumentTarget(
        logical_path="doc.md",
        kind="generated",
        template=TARGET_TEMPLATE,
        read_error_message="read failed",
        conflict_error_message="conflict",
    )
    store = ArtifactDocumentStore(target)

    relative_path, sha256 = await store.write(
        "user-1",
        "# Updated\n",
        hashlib.sha256(b"").hexdigest(),
    )
    await store.rollback("user-1", relative_path, "# Base\n")

    assert relative_path == "users/user-1/generated/doc.md"
    assert sha256 == hashlib.sha256(b"# Updated\n").hexdigest()
    assert await store.read("user-1") == "# Base\n"


@pytest.mark.asyncio
async def test_artifact_document_target_rejects_stale_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    target = ArtifactDocumentTarget(
        logical_path="doc.md",
        kind="generated",
        template=TARGET_TEMPLATE,
        read_error_message="read failed",
        conflict_error_message="conflict",
    )
    store = ArtifactDocumentStore(target)

    await store.write("user-1", "# Current\n", hashlib.sha256(b"").hexdigest())

    with pytest.raises(ArtifactPatchConflictError, match="conflict"):
        await store.write("user-1", "# Stale\n", "stale-sha")
