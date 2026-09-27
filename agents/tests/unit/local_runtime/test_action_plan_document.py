from __future__ import annotations

import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest

from pantaray_agents.local_runtime.tooling import action_plan_document as plan_module
from pantaray_agents.local_runtime.tooling.action_plan_document import (
    ACTION_PLAN_FILENAME,
    ACTION_PLAN_MAX_BYTES,
    ACTION_PLAN_TEMP_PREFIX,
    ActionPlanDocumentError,
    ActionPlanTooLargeError,
    read_action_plan,
    remove_abandoned_action_plan_write,
    write_action_plan,
)
from pantaray_agents.local_runtime.tooling.action_session_temp_paths import (
    ActionStoragePaths,
    resolve_action_storage_paths,
)

USER_ID = "user-1"
ACTION_ID = "action-1"


def _create_workspace(tmp_path: Path) -> tuple[Path, ActionStoragePaths]:
    db_path = tmp_path / "runtime.db"
    paths = resolve_action_storage_paths(
        db_path=db_path,
        user_id=USER_ID,
        action_id=ACTION_ID,
    )
    paths.workspace.mkdir(parents=True)
    return db_path, paths


def _write(db_path: Path, content: str) -> None:
    write_action_plan(
        db_path=db_path,
        user_id=USER_ID,
        action_id=ACTION_ID,
        content=content,
    )


def _read(db_path: Path) -> str | None:
    return read_action_plan(db_path=db_path, user_id=USER_ID, action_id=ACTION_ID)


def test_action_plan_enforces_utf8_byte_limit_without_replacing_previous_content(
    tmp_path: Path,
) -> None:
    db_path, paths = _create_workspace(tmp_path)
    exact_limit = "é" * (ACTION_PLAN_MAX_BYTES // 2)
    _write(db_path, exact_limit)

    with pytest.raises(ActionPlanTooLargeError):
        _write(db_path, f"{exact_limit}a")

    assert _read(db_path) == exact_limit
    (paths.workspace / ACTION_PLAN_FILENAME).write_bytes(
        b"x" * (ACTION_PLAN_MAX_BYTES + 1)
    )

    with pytest.raises(ActionPlanTooLargeError):
        _read(db_path)


def test_action_plan_read_wraps_file_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, _paths = _create_workspace(tmp_path)

    def _deny_open(**_kwargs: object) -> int:
        raise PermissionError("read denied")

    monkeypatch.setattr(plan_module, "open_regular_file_at_descriptor", _deny_open)

    with pytest.raises(ActionPlanDocumentError, match="failed to open"):
        _read(db_path)


def test_action_plan_concurrent_writes_keep_one_complete_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, paths = _create_workspace(tmp_path)
    barrier = Barrier(3)
    release = Event()
    real_rename = plan_module.os.rename

    def _rename(source: str, destination: str, **fds: int) -> None:
        barrier.wait(timeout=5)
        release.wait(timeout=5)
        real_rename(source, destination, **fds)

    monkeypatch.setattr(plan_module.os, "rename", _rename)
    contents = ("first" * 1_000, "second" * 1_000)
    with ThreadPoolExecutor(max_workers=3) as executor:
        writes = tuple(executor.submit(_write, db_path, item) for item in contents)
        barrier.wait(timeout=5)
        recovery = executor.submit(
            remove_abandoned_action_plan_write, action_root=paths.action_root
        )
        try:
            with pytest.raises(TimeoutError):
                recovery.result(timeout=0.1)
        finally:
            release.set()
        tuple(write.result() for write in writes)
        recovery.result()

    assert (paths.workspace / ACTION_PLAN_FILENAME).read_text() in contents
    assert not any(
        path.name.startswith(ACTION_PLAN_TEMP_PREFIX)
        for path in paths.action_root.iterdir()
    )


def test_action_plan_rename_failure_keeps_old_document_and_removes_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, paths = _create_workspace(tmp_path)
    _write(db_path, "old")

    def _fail_rename(*_args: object, **_kwargs: object) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(plan_module.os, "rename", _fail_rename)

    with pytest.raises(ActionPlanDocumentError, match="atomically write"):
        _write(db_path, "new")

    assert (paths.workspace / ACTION_PLAN_FILENAME).read_text(encoding="utf-8") == "old"
    assert {path.name for path in paths.workspace.iterdir()} == {ACTION_PLAN_FILENAME}
    assert not any(
        path.name.startswith(ACTION_PLAN_TEMP_PREFIX)
        for path in paths.action_root.iterdir()
    )


def test_action_plan_refuses_to_replace_a_hardlinked_document(tmp_path: Path) -> None:
    db_path, paths = _create_workspace(tmp_path)
    _write(db_path, "old")
    plan = paths.workspace / ACTION_PLAN_FILENAME
    alias = paths.workspace / "alias.md"
    alias.hardlink_to(plan)

    with pytest.raises(ActionPlanDocumentError, match="external hard links"):
        _write(db_path, "new")

    assert plan.samefile(alias)
    assert plan.read_text(encoding="utf-8") == "old"
    assert not any(
        path.name.startswith(ACTION_PLAN_TEMP_PREFIX)
        for path in paths.action_root.iterdir()
    )


def test_action_plan_reports_replaced_content_when_directory_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, paths = _create_workspace(tmp_path)
    real_fsync = plan_module.os.fsync
    directory_fsync_count = 0

    def _fail_directory_fsync(file_descriptor: int) -> None:
        nonlocal directory_fsync_count
        if stat.S_ISDIR(os.fstat(file_descriptor).st_mode):
            directory_fsync_count += 1
            if directory_fsync_count == 2:
                raise OSError("directory fsync failed")
        real_fsync(file_descriptor)

    monkeypatch.setattr(plan_module.os, "fsync", _fail_directory_fsync)

    with pytest.raises(ActionPlanDocumentError, match="was replaced"):
        _write(db_path, "new")

    assert (paths.workspace / ACTION_PLAN_FILENAME).read_text(encoding="utf-8") == "new"
    assert directory_fsync_count == 2
