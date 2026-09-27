from __future__ import annotations

import os
from pathlib import Path

import pytest

import pantaray_agents.local_runtime.memory_catalog.run_workspace as run_workspace_module
from pantaray_agents.local_runtime.memory_catalog.run_workspace import (
    MemoryRunWorkspaceScope,
    cleanup_orphaned_memory_run_workspaces,
    memory_run_workspaces_path,
)


def test_same_logical_run_gets_isolated_scoped_workspaces(tmp_path: Path) -> None:
    with MemoryRunWorkspaceScope() as first_scope:
        first = first_scope.create(
            artifact_root=tmp_path,
            user_id="user-1",
            run_id="run-1",
        )
        with MemoryRunWorkspaceScope() as second_scope:
            second = second_scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-1",
            )

            assert first.root_path != second.root_path
            assert first.root_path.parent == memory_run_workspaces_path(
                artifact_root=tmp_path,
                user_id="user-1",
            )
            for workspace in (first, second):
                assert (
                    workspace.tool_results_path == workspace.root_path / "tool-results"
                )
                assert not (workspace.root_path / "draft").exists()
                assert workspace.tool_results_path.is_dir()
                assert workspace.root_path.stat().st_mode & 0o777 == 0o700

            (first.tool_results_path / "first.json").write_text(
                "first",
                encoding="utf-8",
            )
            assert not (second.tool_results_path / "first.json").exists()
        assert not second.root_path.exists()
        assert first.root_path.exists()
    assert not first.root_path.exists()


@pytest.mark.parametrize("identity", ("", ".", "..", "a/b", "a\\b", "a\0b"))
def test_invalid_workspace_identity_is_rejected(
    tmp_path: Path,
    identity: str,
) -> None:
    with MemoryRunWorkspaceScope() as scope:
        with pytest.raises(ValueError, match="identity"):
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id=identity,
            )


def test_scope_rejects_a_second_workspace(tmp_path: Path) -> None:
    with MemoryRunWorkspaceScope() as scope:
        scope.create(artifact_root=tmp_path, user_id="user-1", run_id="run-1")
        with pytest.raises(RuntimeError, match="already owns"):
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-2",
            )


def test_workspace_name_failure_happens_before_directory_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    open_calls = 0

    def fail_uuid() -> object:
        raise RuntimeError("uuid failed")

    def track_open(**_kwargs: object) -> int:
        nonlocal open_calls
        open_calls += 1
        raise AssertionError("directory must not open before workspace name exists")

    monkeypatch.setattr(run_workspace_module.uuid, "uuid4", fail_uuid)
    monkeypatch.setattr(
        run_workspace_module,
        "_open_workspaces_directory",
        track_open,
    )

    with MemoryRunWorkspaceScope() as scope:
        with pytest.raises(RuntimeError, match="uuid failed"):
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-1",
            )

    assert open_calls == 0


def test_scope_closes_deletion_authority_exactly_once(tmp_path: Path) -> None:
    scope = MemoryRunWorkspaceScope()
    scope.__enter__()
    try:
        scope.create(
            artifact_root=tmp_path,
            user_id="user-1",
            run_id="run-1",
        )
        workspaces_fd = scope._workspaces_fd
        assert workspaces_fd is not None
    finally:
        scope.close()

    scope.close()
    with pytest.raises(OSError):
        os.fstat(workspaces_fd)


def test_scope_retries_workspace_removal_until_it_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_rmtree = run_workspace_module.shutil.rmtree
    removal_attempts = 0

    def flaky_rmtree(path: str, *, dir_fd: int) -> None:
        nonlocal removal_attempts
        removal_attempts += 1
        if removal_attempts < 3:
            raise OSError("workspace is temporarily busy")
        original_rmtree(path, dir_fd=dir_fd)

    monkeypatch.setattr(run_workspace_module.time, "sleep", lambda _seconds: None)

    with MemoryRunWorkspaceScope() as scope:
        workspace = scope.create(
            artifact_root=tmp_path,
            user_id="user-1",
            run_id="run-1",
        )
        monkeypatch.setattr(run_workspace_module.shutil, "rmtree", flaky_rmtree)

    assert removal_attempts == 3
    assert not workspace.root_path.exists()


def test_scope_logs_exhausted_cleanup_without_masking_scope_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    removal_attempts = 0

    def fail_rmtree(_path: str, *, dir_fd: int) -> None:
        del dir_fd
        nonlocal removal_attempts
        removal_attempts += 1
        raise OSError("workspace remains busy")

    monkeypatch.setattr(run_workspace_module.time, "sleep", lambda _seconds: None)
    caplog.set_level("ERROR", logger=run_workspace_module.__name__)

    with MemoryRunWorkspaceScope() as scope:
        workspace = scope.create(
            artifact_root=tmp_path,
            user_id="user-1",
            run_id="run-1",
        )
        monkeypatch.setattr(run_workspace_module.shutil, "rmtree", fail_rmtree)
        scope_result = "durable-success"

    assert scope_result == "durable-success"
    assert removal_attempts == 3
    assert workspace.root_path.is_dir()
    assert "Failed ephemeral cleanup" in caplog.text
    assert workspace.root_path.name in caplog.text


def test_creation_rejects_symlinked_user_directory(tmp_path: Path) -> None:
    users_root = tmp_path / "memory_catalog" / "users"
    users_root.mkdir(parents=True)
    outside_user = tmp_path / "outside-user"
    (outside_user / "workspaces").mkdir(parents=True)
    (users_root / "user-1").symlink_to(outside_user, target_is_directory=True)

    with MemoryRunWorkspaceScope() as scope:
        with pytest.raises(OSError):
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-1",
            )

    assert tuple((outside_user / "workspaces").iterdir()) == ()


def test_creation_rejects_symlinked_artifact_root(tmp_path: Path) -> None:
    outside_root = tmp_path / "outside-root"
    outside_root.mkdir()
    artifact_root = tmp_path / "linked-artifacts"
    artifact_root.symlink_to(outside_root, target_is_directory=True)

    with MemoryRunWorkspaceScope() as scope:
        with pytest.raises(OSError):
            scope.create(
                artifact_root=artifact_root,
                user_id="user-1",
                run_id="run-1",
            )

    assert tuple(outside_root.iterdir()) == ()


def test_creation_rejects_symlinked_workspaces_directory(tmp_path: Path) -> None:
    user_root = tmp_path / "memory_catalog" / "users" / "user-1"
    user_root.mkdir(parents=True)
    outside_workspaces = tmp_path / "outside-workspaces"
    outside_workspaces.mkdir()
    (user_root / "workspaces").symlink_to(
        outside_workspaces,
        target_is_directory=True,
    )

    with MemoryRunWorkspaceScope() as scope:
        with pytest.raises(OSError):
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-1",
            )

    assert tuple(outside_workspaces.iterdir()) == ()


def test_scope_removes_through_held_fd_after_user_path_is_replaced(
    tmp_path: Path,
) -> None:
    outside_user = tmp_path / "outside-user"
    outside_workspaces = outside_user / "workspaces"
    outside_workspaces.mkdir(parents=True)
    victim = outside_workspaces / "victim"
    victim.mkdir()

    with MemoryRunWorkspaceScope() as scope:
        workspace = scope.create(
            artifact_root=tmp_path,
            user_id="user-1",
            run_id="run-1",
        )
        original_user = workspace.root_path.parents[1]
        renamed_user = original_user.with_name("user-1-original")
        original_user.rename(renamed_user)
        original_user.symlink_to(outside_user, target_is_directory=True)

    assert tuple((renamed_user / "workspaces").iterdir()) == ()
    assert victim.is_dir()


def test_partial_creation_is_removed_by_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_mkdir = os.mkdir

    def fail_tool_results(
        path: str | bytes,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> None:
        if path == "tool-results":
            raise OSError("tool result directory failed")
        original_mkdir(path, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", fail_tool_results)
    with pytest.raises(OSError, match="tool result directory"):
        with MemoryRunWorkspaceScope() as scope:
            scope.create(
                artifact_root=tmp_path,
                user_id="user-1",
                run_id="run-1",
            )

    workspaces_root = memory_run_workspaces_path(
        artifact_root=tmp_path,
        user_id="user-1",
    )
    assert tuple(workspaces_root.iterdir()) == ()


def test_startup_cleanup_never_follows_user_or_workspace_symlinks(
    tmp_path: Path,
) -> None:
    users_root = tmp_path / "memory_catalog" / "users"
    real_workspaces = users_root / "real-user" / "workspaces"
    orphan = real_workspaces / "orphan"
    orphan.mkdir(parents=True)

    outside_user = tmp_path / "outside-user"
    outside_user_workspaces = outside_user / "workspaces"
    outside_user_victim = outside_user_workspaces / "victim"
    outside_user_victim.mkdir(parents=True)
    (users_root / "linked-user").symlink_to(outside_user, target_is_directory=True)

    linked_workspaces_user = users_root / "linked-workspaces-user"
    linked_workspaces_user.mkdir()
    linked_workspaces_outside = tmp_path / "linked-workspaces-outside"
    linked_workspaces_victim = linked_workspaces_outside / "victim"
    linked_workspaces_victim.mkdir(parents=True)
    (linked_workspaces_user / "workspaces").symlink_to(
        linked_workspaces_outside,
        target_is_directory=True,
    )

    outside_workspace = tmp_path / "outside-workspace"
    outside_workspace.mkdir()
    (outside_workspace / "evidence").write_text("keep", encoding="utf-8")
    (real_workspaces / "linked-run").symlink_to(
        outside_workspace,
        target_is_directory=True,
    )

    result = cleanup_orphaned_memory_run_workspaces(artifact_root=tmp_path)

    assert result.removed_count == 1
    assert result.failed_count == 3
    assert outside_user_victim.is_dir()
    assert linked_workspaces_victim.is_dir()
    assert (outside_workspace / "evidence").read_text(encoding="utf-8") == "keep"
