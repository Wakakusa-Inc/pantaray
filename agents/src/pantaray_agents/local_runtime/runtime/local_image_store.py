"""Read and write user-scoped generic image artifacts for Action input."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final
from uuid import uuid4

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathMissingError,
    DescriptorPathPolicyError,
    open_regular_file_descriptor,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.security.image_media_types import (
    IMAGE_MIME_TYPE_BY_EXTENSION,
)
from pantaray_agents.security.storage_paths import validate_image_storage_path

from .runtime_env import read_local_runtime_artifact_root

GENERIC_IMAGE_DIRECTORY = "generated/images"
# Where a partially written image lives until it is whole, outside
# `generated/images` so a reader can never resolve a storage_path onto one.
# `frontend/electron/src/capture/screenCapture.ts` stages a capture here too.
_IMAGE_TEMP_DIRECTORY = ".tmp/generated-images"
# The write side of the canonical extension table.
_EXTENSION_BY_IMAGE_MIME_TYPE: Final[Mapping[str, str]] = MappingProxyType(
    {
        mime_type: extension
        for extension, mime_type in IMAGE_MIME_TYPE_BY_EXTENSION.items()
    }
)


@dataclass(frozen=True, slots=True)
class LocalImageBlob:
    storage_path: str
    image_relative_path: str
    mime_type: str
    payload: bytes


def read_local_image_blob(
    *,
    user_id: str,
    storage_path: str,
) -> LocalImageBlob | None:
    """Read one generic image without accepting arbitrary filesystem paths."""

    normalized_user_id = user_id.strip()
    normalized_storage_path = storage_path.strip()
    if not normalized_user_id:
        raise MigrationError("user_id must not be empty")
    if not normalized_storage_path:
        raise MigrationError("storage_path must not be empty")
    validate_image_storage_path(
        user_id=normalized_user_id,
        storage_path=normalized_storage_path,
    )
    extension = "." + normalized_storage_path.rsplit(".", maxsplit=1)[-1].lower()
    mime_type = IMAGE_MIME_TYPE_BY_EXTENSION[extension]
    image_relative_path = f"{GENERIC_IMAGE_DIRECTORY}/{normalized_storage_path}"
    try:
        descriptor = open_regular_file_descriptor(
            root_path=read_local_runtime_artifact_root(),
            relative_path=image_relative_path,
        )
    except DescriptorPathMissingError:
        return None
    except DescriptorPathPolicyError as exc:
        raise MigrationError(
            f"local image artifact path is unsafe: {image_relative_path}"
        ) from exc
    try:
        with open(descriptor, "rb", closefd=False) as handle:
            payload = handle.read()
    finally:
        os.close(descriptor)
    if not payload:
        raise MigrationError(
            f"local image artifact payload must not be empty: {image_relative_path}"
        )
    return LocalImageBlob(
        storage_path=normalized_storage_path,
        image_relative_path=image_relative_path,
        mime_type=mime_type,
        payload=payload,
    )


def write_local_image_blob(
    *,
    user_id: str,
    payload: bytes,
    mime_type: str,
) -> LocalImageBlob:
    """Store one image the runtime produced, under the user's own namespace.

    Electron writes a screen capture into the same namespace, so the two agree
    on the layout (`{user_id}/{UTC day}/{uuid}.{ext}`) and on the staging
    directory the rename comes from. The name is built here rather than
    accepted: a storage_path is what later authorizes a read.

    Raises:
        MigrationError: the media type is not one this namespace stores.
        ValueError: ``user_id`` cannot name a namespace.
    """

    extension = _EXTENSION_BY_IMAGE_MIME_TYPE.get(mime_type)
    if extension is None:
        raise MigrationError(f"local image media type is not stored: {mime_type}")
    if not payload:
        raise MigrationError("local image artifact payload must not be empty")
    normalized_user_id = user_id.strip()
    utc_day = datetime.now(UTC).strftime("%Y-%m-%d")
    storage_path = f"{normalized_user_id}/{utc_day}/{uuid4()}{extension}"
    validate_image_storage_path(user_id=normalized_user_id, storage_path=storage_path)
    image_relative_path = f"{GENERIC_IMAGE_DIRECTORY}/{storage_path}"
    artifact_root = read_local_runtime_artifact_root()
    staging_directory = artifact_root / _IMAGE_TEMP_DIRECTORY
    staging_directory.mkdir(parents=True, exist_ok=True)
    target_path = artifact_root / image_relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staged_name = tempfile.mkstemp(dir=staging_directory, suffix=extension)
    try:
        with open(descriptor, "wb") as staged:
            staged.write(payload)
        # Within one filesystem, so the image appears under its storage_path
        # whole or not at all. A rename does not follow a symlink standing at
        # the target, so it cannot be redirected out of the namespace either.
        os.replace(staged_name, target_path)
    except BaseException:
        Path(staged_name).unlink(missing_ok=True)
        raise
    return LocalImageBlob(
        storage_path=storage_path,
        image_relative_path=image_relative_path,
        mime_type=mime_type,
        payload=payload,
    )


__all__ = ["LocalImageBlob", "read_local_image_blob", "write_local_image_blob"]
