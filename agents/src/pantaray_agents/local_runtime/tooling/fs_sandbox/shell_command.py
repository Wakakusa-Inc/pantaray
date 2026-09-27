from __future__ import annotations

import hashlib
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

from .paths import resolve_sandbox_path
from .policy import EditablePathPolicy
from .shell_validation import (
    TEST_FILE_PREDICATES,
    TEST_STRING_COMPARATORS,
    ParsedSandboxShellCommand,
    SandboxShellEffect,
    SandboxShellError,
    SandboxShellErrorCode,
    parse_sandbox_shell_commands,
    validate_sandbox_shell_command,
)

MAX_SHELL_OUTPUT_CHARS = 20_000


@dataclass(frozen=True, slots=True)
class SandboxShellResult:
    cmd: str
    exit_code: int
    stdout: str
    stderr: str
    changed_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CommandExecution:
    exit_code: int
    stdout: str = ""
    stderr: str = ""


def run_sandbox_shell_command(
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    cmd: str,
    protected_paths: tuple[str, ...] = (),
) -> SandboxShellResult:
    normalized_cmd = cmd.strip()
    commands = parse_sandbox_shell_commands(normalized_cmd)
    root = sandbox_root.resolve(strict=True)

    for command in commands:
        validate_sandbox_shell_command(
            command,
            sandbox_root=root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
        )

    if all(command.effect == SandboxShellEffect.READ_ONLY for command in commands):
        try:
            execution = _execute_commands(root=root, commands=commands)
        except OSError as exc:
            raise SandboxShellError(
                SandboxShellErrorCode.COMMAND_DENIED,
                str(exc),
            ) from exc
        return _shell_result(
            cmd=normalized_cmd,
            execution=execution,
            changed_paths=(),
        )

    before = _snapshot_tree(root)
    backup_root = _copy_rollback_tree(root)
    try:
        execution = _execute_commands(root=root, commands=commands)
        after = _snapshot_tree(root)
        changed_paths = _changed_paths(before=before, after=after)
        _require_changed_paths_editable(
            changed_paths=changed_paths,
            editable_policy=editable_policy,
        )
        _require_protected_paths_present(
            protected_paths=protected_paths,
            before=before,
            after=after,
        )
    except SandboxShellError:
        _restore_rollback_tree(root=root, backup_root=backup_root)
        raise
    except OSError as exc:
        _restore_rollback_tree(root=root, backup_root=backup_root)
        raise SandboxShellError(
            SandboxShellErrorCode.COMMAND_DENIED,
            str(exc),
        ) from exc
    finally:
        shutil.rmtree(backup_root.parent, ignore_errors=True)

    return _shell_result(
        cmd=normalized_cmd,
        execution=execution,
        changed_paths=changed_paths,
    )


def _shell_result(
    *, cmd: str, execution: CommandExecution, changed_paths: tuple[str, ...]
) -> SandboxShellResult:
    return SandboxShellResult(
        cmd=cmd,
        exit_code=execution.exit_code,
        stdout=_truncate_output(execution.stdout),
        stderr=_truncate_output(execution.stderr),
        changed_paths=changed_paths,
    )


def _execute_commands(
    *, root: Path, commands: tuple[ParsedSandboxShellCommand, ...]
) -> CommandExecution:
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    exit_code = 0
    for command in commands:
        if command.separator == "and" and exit_code != 0:
            continue
        result = _execute_command(root=root, argv=command.argv)
        stdout_parts.append(result.stdout)
        stderr_parts.append(result.stderr)
        exit_code = result.exit_code
    return CommandExecution(
        exit_code=exit_code,
        stdout="".join(stdout_parts),
        stderr="".join(stderr_parts),
    )


def _execute_command(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    name = argv[0]
    if name == "find":
        return _execute_find(root=root, argv=argv)
    if name == "ls":
        return _execute_ls(root=root, argv=argv)
    if name == "mkdir":
        return _execute_mkdir(root=root, argv=argv)
    if name == "mv":
        return _execute_mv(root=root, argv=argv)
    if name == "pwd":
        return CommandExecution(exit_code=0, stdout=f"{root}\n")
    if name == "rm":
        return _execute_rm(root=root, argv=argv)
    if name == "rmdir":
        return _execute_rmdir(root=root, argv=argv)
    if name == "test":
        return _execute_test(root=root, argv=argv)
    if name == "touch":
        return _execute_touch(root=root, argv=argv)
    raise SandboxShellError(
        SandboxShellErrorCode.COMMAND_DENIED,
        f"unsupported command: {name}",
    )


def _execute_find(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    args = argv[1:]
    expression_start = _find_expression_start(args)
    raw_paths = args[:expression_start] or (".",)
    expression = args[expression_start:]
    max_depth, min_depth, type_filter, name_pattern, path_pattern = _find_filters(
        expression
    )
    output: list[str] = []
    for raw_path in raw_paths:
        base = _resolved_path(root=root, raw_path=raw_path, must_exist=True)
        for path in _walk_find_paths(base=base, max_depth=max_depth):
            relative_to_base = path.relative_to(base)
            depth = 0 if relative_to_base == Path(".") else len(relative_to_base.parts)
            if depth < min_depth:
                continue
            if type_filter == "f" and not path.is_file():
                continue
            if type_filter == "d" and not path.is_dir():
                continue
            relative_output = path.relative_to(root).as_posix()
            if name_pattern is not None and not fnmatch(path.name, name_pattern):
                continue
            if path_pattern is not None and not fnmatch(relative_output, path_pattern):
                continue
            output.append(relative_output)
    return CommandExecution(
        exit_code=0, stdout="\n".join(sorted(output)) + ("\n" if output else "")
    )


def _execute_ls(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    paths = _command_paths(
        argv,
        allowed_options=frozenset(("-1", "-a", "-al", "-la", "-l", "-R", "--")),
    ) or (".",)
    recursive = _has_option(argv, "-R")
    include_hidden = any(option in argv for option in ("-a", "-al", "-la"))
    output: list[str] = []
    for raw_path in paths:
        path = _resolved_path(root=root, raw_path=raw_path, must_exist=True)
        output.extend(
            _format_ls_entries(
                root=root,
                path=path,
                recursive=recursive,
                include_hidden=include_hidden,
            )
        )
    return CommandExecution(
        exit_code=0, stdout="\n".join(output) + ("\n" if output else "")
    )


def _execute_mkdir(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    parents = _has_option(argv, "-p")
    for raw_path in _command_paths(argv, allowed_options=frozenset(("-p", "--"))):
        path = _resolved_path(root=root, raw_path=raw_path, must_exist=False)
        try:
            path.mkdir(parents=parents, exist_ok=parents)
        except OSError as exc:
            return CommandExecution(exit_code=1, stderr=f"mkdir: {exc}\n")
    return CommandExecution(exit_code=0)


def _execute_mv(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    source_raw, destination_raw = _command_paths(
        argv, allowed_options=frozenset(("--",))
    )
    source = _resolved_path(
        root=root,
        raw_path=source_raw,
        must_exist=True,
        follow_final_symlink=False,
    )
    destination = _resolved_path(root=root, raw_path=destination_raw, must_exist=False)
    if destination.exists() and destination.is_dir():
        destination = destination / source.name
    if destination.exists():
        return CommandExecution(
            exit_code=1, stderr=f"mv: destination exists: {destination_raw}\n"
        )
    if not destination.parent.exists():
        return CommandExecution(
            exit_code=1, stderr=f"mv: parent does not exist: {destination.parent}\n"
        )
    source.rename(destination)
    return CommandExecution(exit_code=0)


def _execute_rm(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    force = (
        _has_option(argv, "-f") or _has_option(argv, "-rf") or _has_option(argv, "-fr")
    )
    recursive = (
        _has_option(argv, "-r") or _has_option(argv, "-rf") or _has_option(argv, "-fr")
    )
    for raw_path in _command_paths(
        argv,
        allowed_options=frozenset(("-f", "-r", "-rf", "-fr", "--")),
    ):
        path = _resolved_path(
            root=root,
            raw_path=raw_path,
            must_exist=False,
            follow_final_symlink=False,
        )
        if not path.exists() and not path.is_symlink():
            if force:
                continue
            return CommandExecution(
                exit_code=1, stderr=f"rm: no such file: {raw_path}\n"
            )
        if path.is_dir() and not path.is_symlink():
            if not recursive:
                return CommandExecution(
                    exit_code=1, stderr=f"rm: is a directory: {raw_path}\n"
                )
            shutil.rmtree(path)
        else:
            path.unlink()
    return CommandExecution(exit_code=0)


def _execute_rmdir(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    for raw_path in _command_paths(argv, allowed_options=frozenset(("--",))):
        path = _resolved_path(
            root=root,
            raw_path=raw_path,
            must_exist=False,
            follow_final_symlink=False,
        )
        try:
            path.rmdir()
        except OSError as exc:
            return CommandExecution(exit_code=1, stderr=f"rmdir: {exc}\n")
    return CommandExecution(exit_code=0)


def _execute_test(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    args = argv[1:]
    if len(args) == 1:
        return CommandExecution(exit_code=0 if args[0] else 1)
    if len(args) == 2 and args[0] in TEST_FILE_PREDICATES:
        path = _resolved_path(root=root, raw_path=args[1], must_exist=False)
        result = {
            "-d": path.is_dir(),
            "-e": path.exists(),
            "-f": path.is_file(),
            "-r": path.exists(),
            "-s": path.is_file() and path.stat().st_size > 0,
            "-w": path.exists(),
        }[args[0]]
        return CommandExecution(exit_code=0 if result else 1)
    if len(args) == 3 and args[1] in TEST_STRING_COMPARATORS:
        equal = args[0] == args[2]
        return CommandExecution(exit_code=0 if equal == (args[1] == "=") else 1)
    return CommandExecution(exit_code=2, stderr="test: unsupported expression\n")


def _execute_touch(*, root: Path, argv: tuple[str, ...]) -> CommandExecution:
    for raw_path in _command_paths(argv, allowed_options=frozenset(("--",))):
        path = _resolved_path(root=root, raw_path=raw_path, must_exist=False)
        if not path.parent.exists():
            return CommandExecution(
                exit_code=1, stderr=f"touch: parent does not exist: {path.parent}\n"
            )
        path.touch(exist_ok=True)
    return CommandExecution(exit_code=0)


def _snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root).as_posix()
        if path.is_symlink():
            snapshot[relative_path] = f"symlink:{path.readlink().as_posix()}"
        elif path.is_dir():
            snapshot[relative_path] = "dir"
        elif path.is_file():
            snapshot[relative_path] = f"file:{_sha256_file(path)}"
        else:
            snapshot[relative_path] = "other"
    return snapshot


def _changed_paths(
    *,
    before: dict[str, str],
    after: dict[str, str],
) -> tuple[str, ...]:
    paths = set(before) | set(after)
    return tuple(sorted(path for path in paths if before.get(path) != after.get(path)))


def _require_changed_paths_editable(
    *,
    changed_paths: tuple[str, ...],
    editable_policy: EditablePathPolicy,
) -> None:
    for path in changed_paths:
        if editable_policy.allows(path):
            continue
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"command changed a non-editable path: {path}",
        )


def _require_protected_paths_present(
    *,
    protected_paths: tuple[str, ...],
    before: dict[str, str],
    after: dict[str, str],
) -> None:
    for path in protected_paths:
        if path not in before:
            continue
        if path in after:
            continue
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"command removed protected path: {path}",
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _truncate_output(text: str) -> str:
    if len(text) <= MAX_SHELL_OUTPUT_CHARS:
        return text
    suffix = "\n...[truncated]"
    return f"{text[: MAX_SHELL_OUTPUT_CHARS - len(suffix)]}{suffix}"


def _copy_rollback_tree(root: Path) -> Path:
    temp_parent = Path(
        tempfile.mkdtemp(prefix=f".{root.name}.rollback.", dir=str(root.parent))
    )
    backup_root = temp_parent / "backup"
    shutil.copytree(root, backup_root, symlinks=True)
    return backup_root


def _restore_rollback_tree(*, root: Path, backup_root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(backup_root, root, symlinks=True)


def _resolved_path(
    *,
    root: Path,
    raw_path: str,
    must_exist: bool,
    follow_final_symlink: bool = True,
) -> Path:
    return resolve_sandbox_path(
        sandbox_root=root,
        relative_path=raw_path,
        must_exist=must_exist,
        follow_final_symlink=follow_final_symlink,
    ).path


def _command_paths(
    argv: tuple[str, ...],
    *,
    allowed_options: frozenset[str],
) -> tuple[str, ...]:
    paths: list[str] = []
    parsing_options = True
    for token in argv[1:]:
        if parsing_options and token == "--":
            parsing_options = False
            continue
        if parsing_options and token.startswith("-") and token in allowed_options:
            continue
        paths.append(token)
    return tuple(paths)


def _has_option(argv: tuple[str, ...], option: str) -> bool:
    return option in argv[1:]


def _find_expression_start(args: tuple[str, ...]) -> int:
    for index, token in enumerate(args):
        if token.startswith("-"):
            return index
    return len(args)


def _find_filters(
    expression: tuple[str, ...],
) -> tuple[int | None, int, str | None, str | None, str | None]:
    max_depth: int | None = None
    min_depth = 0
    type_filter: str | None = None
    name_pattern: str | None = None
    path_pattern: str | None = None
    index = 0
    while index < len(expression):
        token = expression[index]
        if token == "-print":
            index += 1
        elif token == "-maxdepth":
            max_depth = int(expression[index + 1])
            index += 2
        elif token == "-mindepth":
            min_depth = int(expression[index + 1])
            index += 2
        elif token == "-type":
            type_filter = expression[index + 1]
            index += 2
        elif token == "-name":
            name_pattern = expression[index + 1]
            index += 2
        elif token == "-path":
            path_pattern = expression[index + 1]
            index += 2
        else:
            index += 1
    return max_depth, min_depth, type_filter, name_pattern, path_pattern


def _walk_find_paths(*, base: Path, max_depth: int | None) -> Iterator[Path]:
    yield base
    if base.is_file() or base.is_symlink() or max_depth == 0:
        return

    pending: list[tuple[Path, int]] = [(base, 0)]
    while pending:
        directory, depth = pending.pop()
        children = tuple(sorted(directory.iterdir()))
        child_depth = depth + 1
        yield from children
        if max_depth is not None and child_depth >= max_depth:
            continue
        pending.extend(
            (child, child_depth)
            for child in reversed(children)
            if child.is_dir() and not child.is_symlink()
        )


def _format_ls_entries(
    *,
    root: Path,
    path: Path,
    recursive: bool,
    include_hidden: bool,
) -> list[str]:
    if path.is_file():
        return [path.relative_to(root).as_posix()]
    paths = sorted(path.rglob("*") if recursive else path.iterdir())
    return [
        item.relative_to(root).as_posix()
        for item in paths
        if include_hidden or not item.name.startswith(".")
    ]
