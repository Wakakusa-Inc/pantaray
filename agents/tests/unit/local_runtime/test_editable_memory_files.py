from __future__ import annotations

import errno
import fcntl
import os
import stat
import unicodedata
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathMissingError,
    DescriptorPathPolicyError,
)
from pantaray_agents.local_runtime.descriptor_write import CommittedFileWriteError
from pantaray_agents.local_runtime.memory_catalog import editable_files
from pantaray_agents.local_runtime.memory_catalog.editable_files import (
    EDITABLE_MEMORY_ROOTS,
    MemoryFileConflictError,
    create_editable_memory_root,
    locked_memory_files,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemoryDocument


def test_current_files_keep_external_edits_and_private_permissions(
    tmp_path: Path,
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    expected: list[MemoryDocument] = []
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        for category in EDITABLE_MEMORY_ROOTS:
            path = f"{category}/project/notes.md"
            files.write(path=path, text="old\r\n", expected_text=None)
            files.write(path=path, text="new\r\n", expected_text="old\r\n")
            assert files.read(path) == "new\r\n"
            assert stat.S_IMODE((root / path).stat().st_mode) == 0o600
            expected.append(MemoryDocument(path, "new\r\n"))
        assert files.documents() == tuple(expected)
    (root / expected[0].source_path).write_text("human correction\n")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        assert files.documents()[0].content == "human correction\n"
        with pytest.raises(MemoryFileConflictError):
            files.write(
                path=expected[0].source_path,
                text="stale change",
                expected_text="new\r\n",
            )
        assert files.read(expected[0].source_path) == "human correction\n"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    ) == sorted(item.source_path for item in expected)


def test_stale_edits_and_existing_destinations_preserve_current_content(
    tmp_path: Path,
) -> None:
    create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        source = "facts/source.md"
        destination = "facts/destination.md"
        files.write(path=source, text="current", expected_text=None)
        files.write(path=destination, text="keep", expected_text=None)
        with pytest.raises(MemoryFileConflictError):
            files.write(path=source, text="lost update", expected_text="stale")
        with pytest.raises(MemoryFileConflictError):
            files.write(path=source, text="clobber", expected_text=None)
        with pytest.raises(MemoryFileConflictError):
            files.move(source=source, destination=destination, expected_text="current")
        with pytest.raises(MemoryFileConflictError):
            files.delete(path=source, expected_text="stale")
        assert files.read(source) == "current"
        assert files.read(destination) == "keep"


def test_move_and_delete_update_only_current_files(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="insights/old.md", text="knowledge", expected_text=None)
        files.move(
            source="insights/old.md",
            destination="insights/project/new.md",
            expected_text="knowledge",
        )
        assert files.documents() == (
            MemoryDocument("insights/project/new.md", "knowledge"),
        )
        assert not (root / "insights/old.md").exists()
        with pytest.raises(ValueError, match="between editable categories"):
            files.move(
                source="insights/project/new.md",
                destination="facts/new.md",
                expected_text="knowledge",
            )
        files.delete(path="insights/project/new.md", expected_text="knowledge")
        assert files.documents() == ()
        assert not any(path.is_file() for path in root.rglob("*"))


@pytest.mark.parametrize("operation", ["move", "delete"])
def test_sync_failure_reports_committed_changes_without_losing_move_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/source.md", text="knowledge", expected_text=None)

        def fail_sync(_fd: int) -> None:
            raise OSError(errno.EIO, "directory sync failed")

        monkeypatch.setattr(os, "fsync", fail_sync)
        with pytest.raises(CommittedFileWriteError):
            if operation == "move":
                files.move(
                    source="facts/source.md",
                    destination="facts/destination.md",
                    expected_text="knowledge",
                )
            else:
                files.delete(path="facts/source.md", expected_text="knowledge")
        if operation == "move":
            assert files.read("facts/source.md") == "knowledge"
            assert files.read("facts/destination.md") == "knowledge"
        else:
            assert not (root / "facts/source.md").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../other/secret.md",
        "/facts/secret.md",
        "facts/../other.md",
        "outside/file.md",
        "facts/.pantaray-patch-stale.tmp",
        "facts/.hidden/note.md",
        "facts/note.md~",
    ],
)
def test_invalid_paths_do_not_write_outside_categories(
    tmp_path: Path, path: str
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        with pytest.raises(ValueError):
            files.write(path=path, text="unsafe", expected_text=None)
    assert not list(root.iterdir())


@pytest.mark.parametrize("link_kind", ["directory", "file"])
def test_symlinks_cannot_read_or_overwrite_another_users_files(
    tmp_path: Path, link_kind: str
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    other = create_editable_memory_root(artifact_root=tmp_path, user_id="user-2")
    (other / "facts").mkdir()
    secret = other / "facts/secret.md"
    secret.write_text("other user's content")
    if link_kind == "directory":
        (root / "facts").symlink_to(other / "facts", target_is_directory=True)
    else:
        (root / "facts").mkdir()
        (root / "facts/secret.md").symlink_to(secret)
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        with pytest.raises(DescriptorPathPolicyError):
            files.read("facts/secret.md")
        with pytest.raises(DescriptorPathPolicyError):
            files.write(path="facts/secret.md", text="overwrite", expected_text=None)
        with pytest.raises(DescriptorPathPolicyError):
            files.documents()
    assert secret.read_text() == "other user's content"


def test_directory_lock_covers_reader_and_index_work_without_lock_file(
    tmp_path: Path,
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    competing = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
            files.documents()
            with pytest.raises(BlockingIOError):
                fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(competing, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(competing)
    assert not list(root.iterdir())


def test_missing_root_is_not_silently_recreated(tmp_path: Path) -> None:
    with pytest.raises(DescriptorPathMissingError):
        with locked_memory_files(artifact_root=tmp_path, user_id="user-1"):
            pytest.fail("missing current memory cannot be treated as an empty tree")
    assert not list(tmp_path.iterdir())


def test_failed_cleanup_temporary_file_is_not_memory_content(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/current.md", text="current", expected_text=None)
        (root / "facts/.pantaray-patch-interrupted.tmp").write_text("uncommitted")
        assert files.documents() == (MemoryDocument("facts/current.md", "current"),)


def test_parent_replacement_cannot_redirect_a_locked_write(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    other = create_editable_memory_root(artifact_root=tmp_path, user_id="user-2")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-2") as files:
        files.write(path="facts/current.md", text="other user", expected_text=None)
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/current.md", text="old", expected_text=None)
        original = root.parent.with_name("original-user-1")
        root.parent.rename(original)
        root.parent.symlink_to(other.parent, target_is_directory=True)
        files.write(path="facts/current.md", text="new", expected_text="old")
        assert files.read("facts/current.md") == "new"
    assert (other / "facts/current.md").read_text() == "other user"
    assert (original / "files/facts/current.md").read_text() == "new"


def test_case_only_move_changes_the_directory_entry(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/note.md", text="knowledge", expected_text=None)
        files.move(
            source="facts/note.md",
            destination="facts/Note.md",
            expected_text="knowledge",
        )
        assert files.documents() == (MemoryDocument("facts/Note.md", "knowledge"),)
    assert [path.name for path in (root / "facts").iterdir()] == ["Note.md"]


def test_move_does_not_overwrite_a_distinct_hard_link(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/source.md", text="knowledge", expected_text=None)
        (root / "facts/other.md").hardlink_to(root / "facts/source.md")
        with pytest.raises(MemoryFileConflictError):
            files.move(
                source="facts/source.md",
                destination="facts/other.md",
                expected_text="knowledge",
            )
        assert {item.source_path for item in files.documents()} == {
            "facts/source.md",
            "facts/other.md",
        }


def test_oversized_external_file_fails_without_allocating_or_truncating_it(
    tmp_path: Path,
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    (root / "facts").mkdir()
    target = root / "facts/large.md"
    size = editable_files.MAX_MEMORY_FILE_BYTES + 1
    with target.open("wb") as handle:
        handle.truncate(size)
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        for read in (lambda: files.read("facts/large.md"), files.documents):
            with pytest.raises(OSError) as caught:
                read()
            assert caught.value.errno == errno.EFBIG
    assert target.stat().st_size == size


def test_aggregate_read_and_write_limits_preserve_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(editable_files, "MAX_MEMORY_TOTAL_BYTES", 4)
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/first.md", text="abc", expected_text=None)
        with pytest.raises(OSError) as caught:
            files.write(path="facts/second.md", text="de", expected_text=None)
        assert caught.value.errno == errno.EFBIG
        assert files.documents() == (MemoryDocument("facts/first.md", "abc"),)
        (root / "facts/second.md").write_text("de")
        with pytest.raises(OSError) as caught:
            files.documents()
        assert caught.value.errno == errno.EFBIG
        files.write(path="facts/second.md", text="z", expected_text="de")
        assert files.documents() == (
            MemoryDocument("facts/first.md", "abc"),
            MemoryDocument("facts/second.md", "z"),
        )
    assert (root / "facts/first.md").read_text() == "abc"
    assert (root / "facts/second.md").read_text() == "z"


@pytest.mark.parametrize("destination", ["facts/next.md", "facts/new/deeper/next.md"])
def test_empty_files_and_parent_directories_obey_entry_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    monkeypatch.setattr(editable_files, "MAX_MEMORY_TREE_ENTRIES", 2)
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/current.md", text="", expected_text=None)
        with pytest.raises(OSError) as caught:
            files.write(path=destination, text="", expected_text=None)
        assert caught.value.errno == errno.EFBIG
        assert files.documents() == (MemoryDocument("facts/current.md", ""),)
    assert [p.name for p in (root / "facts").iterdir()] == ["current.md"]


def test_move_rejects_new_directories_that_exceed_entry_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(editable_files, "MAX_MEMORY_TREE_ENTRIES", 2)
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/current.md", text="", expected_text=None)
        with pytest.raises(OSError) as caught:
            files.move(
                source="facts/current.md",
                destination="facts/new/next.md",
                expected_text="",
            )
        assert caught.value.errno == errno.EFBIG
        assert files.documents() == (MemoryDocument("facts/current.md", ""),)
    assert not (root / "facts/new").exists()


def test_metadata_and_editor_backups_are_not_current_memory(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/current.md", text="current", expected_text=None)
        for name in (".DS_Store", ".current.md.swp", "current.md~"):
            (root / "facts" / name).write_bytes(b"\xffstale")
        (root / "facts/.hidden").mkdir()
        (root / "facts/.hidden/old.md").write_text("stale")
        assert files.documents() == (MemoryDocument("facts/current.md", "current"),)


def test_case_alias_of_distinct_hard_link_is_not_a_case_only_move(
    tmp_path: Path,
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/source.md", text="knowledge", expected_text=None)
        (root / "facts/Other.md").hardlink_to(root / "facts/source.md")
        if not (root / "facts/other.md").exists():
            pytest.skip("requires a case-insensitive filesystem")
        with pytest.raises(MemoryFileConflictError):
            files.move(
                source="facts/source.md",
                destination="facts/other.md",
                expected_text="knowledge",
            )
        assert {item.source_path for item in files.documents()} == {
            "facts/source.md",
            "facts/Other.md",
        }


def test_directory_depth_is_bounded_before_creation_and_during_external_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(editable_files, "MAX_MEMORY_DIRECTORY_DEPTH", 3)
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/a/b/current.md", text="current", expected_text=None)
        with pytest.raises(ValueError, match="directory levels"):
            files.write(path="facts/a/b/c/new.md", text="", expected_text=None)
        assert not (root / "facts/a/b/c").exists()
        assert files.documents() == (MemoryDocument("facts/a/b/current.md", "current"),)
        (root / "facts/a/b/c").mkdir()
        (root / "facts/a/b/c/external.md").write_text("external")
        with pytest.raises(OSError) as caught:
            files.documents()
        assert caught.value.errno == errno.EFBIG
        assert files.read("facts/a/b/current.md") == "current"


def test_case_alias_of_existing_parent_resolves_the_move_destination(
    tmp_path: Path,
) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/project/note.md", text="knowledge", expected_text=None)
        files.write(path="facts/project/sibling.md", text="keep", expected_text=None)
        if not (root / "facts/Project").exists():
            pytest.skip("requires a case-insensitive filesystem")
        destination = "facts/Project/Note.md"
        files.move(
            source="facts/project/note.md",
            destination=destination,
            expected_text="knowledge",
        )
        assert files.read(destination) == "knowledge"
        assert (root / destination).read_text() == "knowledge"
        assert {item.source_path for item in files.documents()} == {
            "facts/project/Note.md",
            "facts/project/sibling.md",
        }
    assert [p.name for p in (root / "facts").iterdir()] == ["project"]
    assert {p.name for p in (root / "facts/project").iterdir()} == {
        "Note.md",
        "sibling.md",
    }


def test_unicode_normalization_alias_supports_case_only_move(tmp_path: Path) -> None:
    root = create_editable_memory_root(artifact_root=tmp_path, user_id="user-1")
    with locked_memory_files(artifact_root=tmp_path, user_id="user-1") as files:
        files.write(path="facts/café.md", text="knowledge", expected_text=None)
        source = "facts/" + unicodedata.normalize("NFD", "café.md")
        destination = "facts/CAFÉ.md"
        if not (root / source).exists():
            pytest.skip("requires a normalization-insensitive filesystem")
        files.move(source=source, destination=destination, expected_text="knowledge")
        assert files.documents() == (MemoryDocument(destination, "knowledge"),)
