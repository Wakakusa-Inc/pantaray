from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pantaray_agents.agents.action_agent.runtime.user_image_attachments import (
    build_user_image_attachments,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.agent.image import ImageInput

_FIRST_PAYLOAD = b"\x89PNG\r\n\x1a\nfirst"
_SECOND_PAYLOAD = b"\xff\xd8\xff-second"
_FIRST_PATH = "user-1/2026-09-08/1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed.png"
_SECOND_PATH = "user-1/2026-09-08/2c9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed.jpg"


def _write_image(*, artifact_root: Path, storage_path: str, payload: bytes) -> None:
    image_path = artifact_root / "generated" / "images" / storage_path
    image_path.parent.mkdir(parents=True, exist_ok=True)
    image_path.write_bytes(payload)


def test_build_user_image_attachments_binds_content_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    _write_image(
        artifact_root=artifact_root, storage_path=_FIRST_PATH, payload=_FIRST_PAYLOAD
    )
    _write_image(
        artifact_root=artifact_root, storage_path=_SECOND_PATH, payload=_SECOND_PAYLOAD
    )
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    attachments = build_user_image_attachments(
        user_id="user-1",
        images=(
            ImageInput(storage_path=_FIRST_PATH),
            ImageInput(storage_path=_SECOND_PATH),
        ),
    )

    first_sha256 = hashlib.sha256(_FIRST_PAYLOAD).hexdigest()
    assert attachments[0] == {
        "type": "file",
        "ref": f"user_attachment:{first_sha256[:24]}",
        "blob_ref": f"attachment_blob_{first_sha256[:24]}",
        "display_path": "image-1.png",
        "mime_type": "image/png",
        "byte_size": len(_FIRST_PAYLOAD),
        "sha256": first_sha256,
        "source_kind": "local_image_blob",
        "storage_path": _FIRST_PATH,
    }
    assert attachments[1]["display_path"] == "image-2.jpg"
    assert attachments[1]["mime_type"] == "image/jpeg"
    assert attachments[1]["storage_path"] == _SECOND_PATH


def test_build_user_image_attachments_rejects_another_users_storage_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    _write_image(
        artifact_root=artifact_root, storage_path=_FIRST_PATH, payload=_FIRST_PAYLOAD
    )
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    with pytest.raises(ValueError, match="storage_path is invalid"):
        build_user_image_attachments(
            user_id="user-2",
            images=(ImageInput(storage_path=_FIRST_PATH),),
        )


def test_build_user_image_attachments_rejects_missing_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifact_root))

    with pytest.raises(MigrationError, match="was not found"):
        build_user_image_attachments(
            user_id="user-1",
            images=(ImageInput(storage_path=_FIRST_PATH),),
        )
