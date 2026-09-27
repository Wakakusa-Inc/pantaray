from __future__ import annotations

import pytest

from pantaray_agents.security.storage_paths import (
    is_valid_image_storage_path,
    validate_image_storage_path,
)


@pytest.mark.parametrize(
    ("user_id", "path", "ok"),
    [
        ("user-1", "user-1/2025-12-28/550e8400-e29b-41d4-a716-446655440000.png", True),
        # prefix mismatch
        ("user-1", "user-2/2025-12-28/550e8400-e29b-41d4-a716-446655440000.png", False),
        # invalid date
        ("user-1", "user-1/2025-99-99/550e8400-e29b-41d4-a716-446655440000.png", False),
        ("user-1", "user-1/20251228/550e8400-e29b-41d4-a716-446655440000.png", False),
        # invalid uuid
        ("user-1", "user-1/2025-12-28/not-a-uuid.png", False),
        # invalid extension
        ("user-1", "user-1/2025-12-28/550e8400-e29b-41d4-a716-446655440000.bmp", False),
        # extra path segments
        (
            "user-1",
            "user-1/2025-12-28/sub/550e8400-e29b-41d4-a716-446655440000.png",
            False,
        ),
        # traversal-like
        ("user-1", "user-1/2025-12-28/../x.png", False),
        (
            "user-1",
            r"user-1\2025-12-28\550e8400-e29b-41d4-a716-446655440000.png",
            False,
        ),
        # control chars
        (
            "user-1",
            "user-1/2025-12-28/\n550e8400-e29b-41d4-a716-446655440000.png",
            False,
        ),
        # empty
        ("user-1", "", False),
        ("", "user-1/2025-12-28/550e8400-e29b-41d4-a716-446655440000.png", False),
    ],
)
def test_is_valid_image_storage_path(user_id: str, path: str, ok: bool) -> None:
    assert is_valid_image_storage_path(user_id=user_id, storage_path=path) is ok


def test_validate_image_storage_path_raises_on_other_user_prefix() -> None:
    with pytest.raises(ValueError, match=r"images\[\]\.storage_path is invalid"):
        validate_image_storage_path(
            user_id="user-1",
            storage_path="user-2/2025-12-28/550e8400-e29b-41d4-a716-446655440000.png",
        )


@pytest.mark.parametrize("extension", ["gif", "jpeg", "jpg", "png", "webp"])
def test_is_valid_image_storage_path_accepts_supported_formats(extension: str) -> None:
    path = f"user-1/2025-12-28/550e8400-e29b-41d4-a716-446655440000.{extension}"

    assert is_valid_image_storage_path(user_id="user-1", storage_path=path)


def test_validate_image_storage_path_rejects_non_image_extension() -> None:
    with pytest.raises(ValueError, match=r"images\[\]\.storage_path is invalid"):
        validate_image_storage_path(
            user_id="user-1",
            storage_path=("user-1/2025-12-28/550e8400-e29b-41d4-a716-446655440000.pdf"),
        )
