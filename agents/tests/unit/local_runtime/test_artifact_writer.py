from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.artifacts.bootstrap import (
    bootstrap_local_artifact_store,
)
from pantaray_agents.local_runtime.artifacts.text_documents import (
    LOCAL_ARTIFACT_ROOT_ENV,
    ensure_local_text_artifact,
    write_local_text_artifact,
)
from pantaray_agents.local_runtime.artifacts.writer import write_managed_file_artifact
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def test_write_managed_file_artifact_is_atomic_and_returns_logical_path(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "artifacts"
    bootstrap_local_artifact_store(root_path=root_path)

    result = write_managed_file_artifact(
        root_path=root_path,
        kind="generated",
        artifact_id="artifact-1",
        file_name="summary.txt",
        payload=b"hello artifact",
    )

    assert result.relative_path == "generated/artifact-1/summary.txt"
    assert result.absolute_path.read_bytes() == b"hello artifact"
    assert str(root_path.resolve()) not in result.relative_path
    assert result.file_size_bytes == len(b"hello artifact")


def test_ensure_local_text_artifact_creates_missing_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(LOCAL_ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    document = ensure_local_text_artifact(
        kind="long_term_insight",
        template="users/{user_id}/insights/long_term.md",
        user_id="user-1",
    )

    assert document.relative_path == "users/user-1/insights/long_term.md"
    assert document.plaintext == ""
    assert document.absolute_path.exists()
    assert document.absolute_path.read_text(encoding="utf-8") == ""


def test_write_local_text_artifact_persists_plaintext_round_trip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(LOCAL_ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    current = ensure_local_text_artifact(
        kind="long_term_insight",
        template="users/{user_id}/insights/long_term.md",
        user_id="user-1",
    )
    written = write_local_text_artifact(
        kind="long_term_insight",
        user_id="user-1",
        relative_path=current.relative_path,
        plaintext="# insight\n",
    )
    loaded = ensure_local_text_artifact(
        kind="long_term_insight",
        template="users/{user_id}/insights/long_term.md",
        user_id="user-1",
    )

    assert written.relative_path == current.relative_path
    assert written.sha256 == loaded.sha256
    assert loaded.plaintext == "# insight\n"


def test_write_managed_file_artifact_fsyncs_parent_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "artifacts"
    bootstrap_local_artifact_store(root_path=root_path)

    opened_paths: list[str] = []
    fsync_fds: list[int] = []

    original_os_open = __import__("os").open
    original_os_fsync = __import__("os").fsync

    def _tracking_os_open(path: str, flags: int, mode: int = 0o777) -> int:
        opened_paths.append(path)
        return original_os_open(path, flags, mode)

    def _tracking_os_fsync(fd: int) -> None:
        fsync_fds.append(fd)
        original_os_fsync(fd)

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.artifacts.writer.os.open", _tracking_os_open
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.artifacts.writer.os.fsync", _tracking_os_fsync
    )

    result = write_managed_file_artifact(
        root_path=root_path,
        kind="generated",
        artifact_id="artifact-fsync",
        file_name="summary.txt",
        payload=b"hello artifact",
    )

    assert result.absolute_path.exists()
    assert str(result.absolute_path.parent) in opened_paths
    assert len(fsync_fds) >= 2


def test_write_managed_file_artifact_cleans_partial_file_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "artifacts"
    bootstrap_local_artifact_store(root_path=root_path)

    def _fail_replace(_src: str | bytes | Path, _dst: str | bytes | Path) -> None:
        raise OSError("boom")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.artifacts.writer.os.replace", _fail_replace
    )

    with pytest.raises(Exception, match="failed to atomically write managed artifact"):
        write_managed_file_artifact(
            root_path=root_path,
            kind="generated",
            artifact_id="artifact-2",
            file_name="failed.txt",
            payload=b"boom",
        )

    artifact_dir = root_path / "generated" / "artifact-2"
    if artifact_dir.exists():
        assert list(artifact_dir.iterdir()) == []


def test_memory_artifact_files_persist_logical_paths_only(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    root_path = tmp_path / "artifacts"
    bootstrap_local_artifact_store(root_path=root_path)
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    result = write_managed_file_artifact(
        root_path=root_path,
        kind="generated",
        artifact_id="artifact-3",
        file_name="report.md",
        payload=b"# hello\n",
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    "user-1",
                    "ja",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO memory_artifacts(
                    artifact_id,
                    user_id,
                    source_type,
                    source_record_id,
                    root_path,
                    content_sha256,
                    logical_created_at,
                    logical_updated_at,
                    indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "artifact-3",
                    "user-1",
                    "facts",
                    "fact-3",
                    "generated/artifact-3",
                    result.checksum_sha256,
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                ),
            )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_artifact_files(
                file_id, artifact_id, relative_path, sha256, byte_size,
                mime_type, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "file-3",
                "artifact-3",
                result.relative_path,
                result.checksum_sha256,
                result.file_size_bytes,
                "text/markdown",
                "2026-03-23T00:00:00Z",
            ),
        )
        file_row = connection.execute(
            """
            SELECT relative_path
            FROM memory_artifact_files
            WHERE artifact_id = ?
            """,
            ("artifact-3",),
        ).fetchone()

    assert file_row is not None
    assert file_row[0] == result.relative_path
    assert str(root_path.resolve()) not in str(file_row[0])
