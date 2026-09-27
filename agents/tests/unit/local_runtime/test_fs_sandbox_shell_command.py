from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.fs_sandbox import (
    EditablePathPolicy,
    SandboxShellError,
    run_sandbox_shell_command,
)


def test_read_only_command_plan_does_not_snapshot_or_copy_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "facts.md").write_text("fact\n", encoding="utf-8")

    def fail_if_called(*_args: object, **_kwargs: object) -> None:
        pytest.fail("read-only commands must not enter the rollback snapshot path")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.tooling.fs_sandbox.shell_command._snapshot_tree",
        fail_if_called,
    )
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.tooling.fs_sandbox.shell_command._copy_rollback_tree",
        fail_if_called,
    )

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(("facts.md",)),
        cmd="pwd; find . -maxdepth 0; ls .; test -d .",
    )

    assert result.exit_code == 0
    assert result.changed_paths == ()
    assert "facts.md" in result.stdout


@pytest.mark.parametrize(
    "cmd",
    (
        "test -n facts.md && find . -maxdepth 0",
        "test 2 -gt 1 && find . -maxdepth 0",
    ),
)
def test_rejects_test_expressions_the_executor_does_not_support(
    tmp_path: Path,
    cmd: str,
) -> None:
    with pytest.raises(SandboxShellError) as exc_info:
        run_sandbox_shell_command(
            sandbox_root=tmp_path,
            editable_policy=EditablePathPolicy(("**",)),
            cmd=cmd,
        )

    assert exc_info.value.code == "INVALID_COMMAND"
    assert str(exc_info.value) == "test: unsupported expression"


@pytest.mark.parametrize(
    "expression",
    (
        "test facts.md",
        "test -f facts.md",
        "test facts.md = facts.md",
        "test facts.md != other.md",
    ),
)
def test_executes_supported_test_expressions(
    tmp_path: Path,
    expression: str,
) -> None:
    (tmp_path / "facts.md").write_text("fact\n", encoding="utf-8")

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(("**",)),
        cmd=expression,
    )

    assert result.exit_code == 0


def test_find_max_depth_prunes_nested_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "hidden.md").write_text("hidden\n", encoding="utf-8")
    original_iterdir = Path.iterdir

    def guarded_iterdir(path: Path):  # noqa: ANN202
        if path == nested:
            pytest.fail("find must not traverse beyond max depth")
        return original_iterdir(path)

    def fail_unbounded_rglob(_path: Path, _pattern: str):  # noqa: ANN202
        pytest.fail("find must not use an unbounded recursive glob")

    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)
    monkeypatch.setattr(Path, "rglob", fail_unbounded_rglob)

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(("**",)),
        cmd="find . -maxdepth 1",
    )

    assert result.exit_code == 0
    assert result.stdout.splitlines() == [".", "nested"]


def test_rm_unlinks_symlink_without_deleting_target(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target.name)

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(("target.txt", "link.txt")),
        cmd="rm link.txt",
    )

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "keep\n"
    assert not link.exists()
    assert not link.is_symlink()
    assert result.changed_paths == ("link.txt",)


def test_rm_unlinks_symlink_to_outside_sandbox_without_deleting_target(
    tmp_path: Path,
) -> None:
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    outside_target = tmp_path / "outside.txt"
    outside_target.write_text("keep\n", encoding="utf-8")
    link = sandbox / "link.txt"
    link.symlink_to(outside_target)

    result = run_sandbox_shell_command(
        sandbox_root=sandbox,
        editable_policy=EditablePathPolicy(("link.txt",)),
        cmd="rm link.txt",
    )

    assert result.exit_code == 0
    assert outside_target.read_text(encoding="utf-8") == "keep\n"
    assert not link.is_symlink()
    assert result.changed_paths == ("link.txt",)


def test_mv_moves_symlink_without_moving_target(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("keep\n", encoding="utf-8")
    source_link = tmp_path / "source-link.txt"
    source_link.symlink_to(target.name)
    destination_link = tmp_path / "destination-link.txt"

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(
            ("target.txt", "source-link.txt", "destination-link.txt")
        ),
        cmd="mv source-link.txt destination-link.txt",
    )

    assert result.exit_code == 0
    assert target.read_text(encoding="utf-8") == "keep\n"
    assert not source_link.exists()
    assert destination_link.is_symlink()
    assert destination_link.readlink() == Path(target.name)


def test_rmdir_does_not_remove_symlink_target_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target.name, target_is_directory=True)

    result = run_sandbox_shell_command(
        sandbox_root=tmp_path,
        editable_policy=EditablePathPolicy(("link",)),
        cmd="rmdir link",
    )

    assert result.exit_code == 1
    assert target.is_dir()
    assert link.is_symlink()
