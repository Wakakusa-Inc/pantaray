from __future__ import annotations

import os
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathMissingError,
    DescriptorPathPolicyError,
    open_regular_file_descriptor,
)


def _read(*, root_path: Path, relative_path: str) -> bytes:
    descriptor = open_regular_file_descriptor(
        root_path=root_path,
        relative_path=relative_path,
    )
    try:
        with open(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def test_reads_below_a_root_reached_through_a_symlinked_ancestor(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real" / "artifacts"
    real_root.mkdir(parents=True)
    (real_root / "generated").mkdir()
    (real_root / "generated" / "image.png").write_bytes(b"payload")
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    payload = _read(
        root_path=tmp_path / "link" / "artifacts",
        relative_path="generated/image.png",
    )

    assert payload == b"payload"


def test_rejects_a_symlink_planted_below_the_root(tmp_path: Path) -> None:
    root_path = tmp_path / "real" / "artifacts"
    root_path.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"secret")
    (root_path / "generated").mkdir()
    (root_path / "generated" / "image.png").symlink_to(outside)
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    with pytest.raises(DescriptorPathPolicyError):
        _read(
            root_path=tmp_path / "link" / "artifacts",
            relative_path="generated/image.png",
        )


def test_rejects_a_root_replaced_by_a_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "image.png").write_bytes(b"secret")
    (tmp_path / "artifacts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DescriptorPathPolicyError):
        _read(root_path=tmp_path / "artifacts", relative_path="image.png")


def test_rejects_a_missing_root(tmp_path: Path) -> None:
    with pytest.raises(DescriptorPathMissingError):
        _read(root_path=tmp_path / "artifacts", relative_path="image.png")


def test_rejects_a_relative_root(tmp_path: Path) -> None:
    with pytest.raises(DescriptorPathPolicyError):
        _read(root_path=Path("artifacts"), relative_path="image.png")
