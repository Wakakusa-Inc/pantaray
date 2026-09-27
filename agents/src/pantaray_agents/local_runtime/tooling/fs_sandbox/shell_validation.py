from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from .paths import ResolvedSandboxPath, SandboxPathError, resolve_sandbox_path
from .policy import EditablePathPolicy

GLOB_CHARS = frozenset("*?[]")
CommandSeparator = Literal["start", "sequence", "and"]

COMMAND_SEPARATORS = frozenset((";", "&&"))
UNSUPPORTED_SHELL_TOKENS = frozenset(("|", "||", "&", "<", ">", ">>", "<<"))
UNSUPPORTED_SHELL_FRAGMENTS = ("`", "$", "\n", "\r")
TEST_FILE_PREDICATES = frozenset(("-d", "-e", "-f", "-r", "-s", "-w"))
TEST_STRING_COMPARATORS = frozenset(("=", "!="))


class SandboxShellEffect(StrEnum):
    READ_ONLY = "read_only"
    MUTATING = "mutating"


COMMAND_EFFECTS: dict[str, SandboxShellEffect] = {
    "find": SandboxShellEffect.READ_ONLY,
    "ls": SandboxShellEffect.READ_ONLY,
    "mkdir": SandboxShellEffect.MUTATING,
    "mv": SandboxShellEffect.MUTATING,
    "pwd": SandboxShellEffect.READ_ONLY,
    "rm": SandboxShellEffect.MUTATING,
    "rmdir": SandboxShellEffect.MUTATING,
    "test": SandboxShellEffect.READ_ONLY,
    "touch": SandboxShellEffect.MUTATING,
}


@dataclass(frozen=True, slots=True)
class ParsedSandboxShellCommand:
    argv: tuple[str, ...]
    separator: CommandSeparator
    effect: SandboxShellEffect


class SandboxShellErrorCode(StrEnum):
    INVALID_COMMAND = "INVALID_COMMAND"
    COMMAND_DENIED = "COMMAND_DENIED"
    PATH_DENIED = "PATH_DENIED"
    TIMEOUT = "TIMEOUT"


class SandboxShellError(ValueError):
    def __init__(self, code: SandboxShellErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = str(code)


def parse_sandbox_shell_commands(cmd: str) -> tuple[ParsedSandboxShellCommand, ...]:
    if not cmd:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            "cmd must not be empty",
        )
    if any(fragment in cmd for fragment in UNSUPPORTED_SHELL_FRAGMENTS):
        raise SandboxShellError(
            SandboxShellErrorCode.COMMAND_DENIED,
            "command substitution and environment expansion are not allowed",
        )
    try:
        lexer = shlex.shlex(cmd, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = tuple(lexer)
    except ValueError as exc:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            f"command could not be parsed: {exc}",
        ) from exc
    if not tokens:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            "cmd must not be empty",
        )

    commands: list[ParsedSandboxShellCommand] = []
    current: list[str] = []
    separator: CommandSeparator = "start"
    for token in tokens:
        if token in COMMAND_SEPARATORS:
            if not current:
                raise SandboxShellError(
                    SandboxShellErrorCode.INVALID_COMMAND,
                    "command separator cannot appear without a command",
                )
            commands.append(_build_parsed_command(tuple(current), separator))
            current = []
            separator = "and" if token == "&&" else "sequence"
            continue
        if _is_unsupported_shell_token(token):
            raise SandboxShellError(
                SandboxShellErrorCode.COMMAND_DENIED,
                f"unsupported shell syntax: {token}",
            )
        current.append(token)

    if not current:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            "command separator cannot appear at the end",
        )
    commands.append(_build_parsed_command(tuple(current), separator))
    return tuple(commands)


def _build_parsed_command(
    argv: tuple[str, ...], separator: CommandSeparator
) -> ParsedSandboxShellCommand:
    name = argv[0]
    effect = COMMAND_EFFECTS.get(name)
    if effect is None:
        raise SandboxShellError(
            SandboxShellErrorCode.COMMAND_DENIED,
            f"unsupported command: {name}",
        )
    return ParsedSandboxShellCommand(argv=argv, separator=separator, effect=effect)


def validate_sandbox_shell_command(
    command: ParsedSandboxShellCommand,
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    protected_paths: tuple[str, ...],
) -> None:
    argv = command.argv
    name = argv[0]
    if name == "find":
        _validate_find(argv, sandbox_root=sandbox_root)
    elif name == "ls":
        _validate_ls(argv, sandbox_root=sandbox_root)
    elif name == "mkdir":
        _validate_paths_command(
            argv,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
            allowed_options=frozenset(("-p", "--")),
            must_be_editable=True,
            must_exist=False,
            reject_protected=True,
        )
    elif name == "mv":
        _validate_mv(
            argv,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
        )
    elif name == "pwd":
        _validate_no_args(argv)
    elif name == "rm":
        _validate_paths_command(
            argv,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
            allowed_options=frozenset(("-f", "-r", "-rf", "-fr", "--")),
            must_be_editable=True,
            must_exist=False,
            reject_protected=True,
            follow_final_symlink=False,
        )
    elif name == "rmdir":
        _validate_paths_command(
            argv,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
            allowed_options=frozenset(("--",)),
            must_be_editable=True,
            must_exist=False,
            reject_protected=True,
            follow_final_symlink=False,
        )
    elif name == "test":
        _validate_test(argv, sandbox_root=sandbox_root)
    elif name == "touch":
        _validate_paths_command(
            argv,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            protected_paths=protected_paths,
            allowed_options=frozenset(("--",)),
            must_be_editable=True,
            must_exist=False,
            reject_protected=True,
        )


def _validate_find(command: tuple[str, ...], *, sandbox_root: Path) -> None:
    args = command[1:]
    expression_start = _find_expression_start(args)
    paths = args[:expression_start] or (".",)
    for path in paths:
        _require_sandbox_path(
            path,
            sandbox_root=sandbox_root,
            must_exist=True,
            reject_glob=True,
        )

    expression = args[expression_start:]
    index = 0
    while index < len(expression):
        token = expression[index]
        if token in ("-print",):
            index += 1
            continue
        if token in ("-maxdepth", "-mindepth"):
            index = _require_integer_option_value(expression, index)
            continue
        if token == "-type":
            index = _require_enum_option_value(
                expression,
                index,
                allowed_values=frozenset(("f", "d")),
            )
            continue
        if token == "-name":
            index = _require_pattern_option_value(expression, index)
            continue
        if token == "-path":
            index = _require_pattern_option_value(expression, index)
            continue
        raise SandboxShellError(
            SandboxShellErrorCode.COMMAND_DENIED,
            f"unsupported find expression: {token}",
        )


def _validate_ls(command: tuple[str, ...], *, sandbox_root: Path) -> None:
    paths = _command_paths(
        command,
        allowed_options=frozenset(("-1", "-a", "-al", "-la", "-l", "-R", "--")),
    )
    for path in paths:
        _require_sandbox_path(
            path,
            sandbox_root=sandbox_root,
            must_exist=True,
            reject_glob=True,
        )


def _validate_mv(
    command: tuple[str, ...],
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    protected_paths: tuple[str, ...],
) -> None:
    paths = _command_paths(command, allowed_options=frozenset(("--",)))
    if len(paths) != 2:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            "mv requires exactly two paths",
        )
    old_path, new_path = paths
    old_resolved = _require_sandbox_path(
        old_path,
        sandbox_root=sandbox_root,
        editable_policy=editable_policy,
        must_be_editable=True,
        must_exist=True,
        reject_glob=True,
        follow_final_symlink=False,
    )
    new_resolved = _require_sandbox_path(
        new_path,
        sandbox_root=sandbox_root,
        editable_policy=editable_policy,
        must_be_editable=True,
        must_exist=False,
        reject_glob=True,
    )
    new_relative_path = _mv_destination_relative_path(
        source_relative_path=old_resolved.relative_path,
        destination=new_resolved.path,
        destination_relative_path=new_resolved.relative_path,
    )
    destination_path = sandbox_root / new_relative_path
    if destination_path.exists():
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"destination already exists: {new_relative_path}",
        )
    if _overlaps_protected_path(old_resolved.relative_path, protected_paths):
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"cannot move protected path: {old_resolved.relative_path}",
        )
    if _overlaps_protected_path(new_relative_path, protected_paths):
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"cannot move into protected path: {new_relative_path}",
        )


def _validate_paths_command(
    command: tuple[str, ...],
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy | None = None,
    protected_paths: tuple[str, ...] = (),
    allowed_options: frozenset[str],
    must_be_editable: bool,
    must_exist: bool,
    reject_protected: bool,
    follow_final_symlink: bool = True,
) -> None:
    paths = _command_paths(command, allowed_options=allowed_options)
    if not paths:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            f"{command[0]} requires at least one path",
        )
    for path in paths:
        resolved = _require_sandbox_path(
            path,
            sandbox_root=sandbox_root,
            editable_policy=editable_policy,
            must_be_editable=must_be_editable,
            must_exist=must_exist,
            reject_glob=True,
            follow_final_symlink=follow_final_symlink,
        )
        if reject_protected and _overlaps_protected_path(
            resolved.relative_path,
            protected_paths,
        ):
            raise SandboxShellError(
                SandboxShellErrorCode.PATH_DENIED,
                f"cannot modify protected path: {resolved.relative_path}",
            )


def _validate_test(command: tuple[str, ...], *, sandbox_root: Path) -> None:
    args = command[1:]
    operands: tuple[str, ...]
    if len(args) == 1:
        operands = args
    elif len(args) == 2 and args[0] in TEST_FILE_PREDICATES:
        operands = args[1:]
    elif len(args) == 3 and args[1] in TEST_STRING_COMPARATORS:
        operands = (args[0], args[2])
    else:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            "test: unsupported expression",
        )

    for operand in operands:
        _require_sandbox_path(
            operand,
            sandbox_root=sandbox_root,
            must_exist=False,
            reject_glob=True,
        )


def _validate_no_args(command: tuple[str, ...]) -> None:
    if len(command) == 1:
        return
    raise SandboxShellError(
        SandboxShellErrorCode.INVALID_COMMAND,
        f"{command[0]} does not accept arguments",
    )


def _command_paths(
    command: tuple[str, ...],
    *,
    allowed_options: frozenset[str],
) -> tuple[str, ...]:
    paths: list[str] = []
    parsing_options = True
    for token in command[1:]:
        if parsing_options and token == "--":
            parsing_options = False
            continue
        if parsing_options and token.startswith("-"):
            if token not in allowed_options:
                raise SandboxShellError(
                    SandboxShellErrorCode.COMMAND_DENIED,
                    f"unsupported option for {command[0]}: {token}",
                )
            continue
        paths.append(token)
    return tuple(paths)


def _require_sandbox_path(
    path: str,
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy | None = None,
    must_be_editable: bool = False,
    must_exist: bool,
    reject_glob: bool,
    follow_final_symlink: bool = True,
) -> ResolvedSandboxPath:
    if reject_glob and any(char in path for char in GLOB_CHARS):
        raise SandboxShellError(
            SandboxShellErrorCode.COMMAND_DENIED,
            "wildcards are not allowed in path arguments; use find instead",
        )
    try:
        resolved = resolve_sandbox_path(
            sandbox_root=sandbox_root,
            relative_path=path,
            must_exist=must_exist,
            follow_final_symlink=follow_final_symlink,
        )
        if must_be_editable:
            if editable_policy is None:
                raise SandboxShellError(
                    SandboxShellErrorCode.INVALID_COMMAND,
                    "editable_policy is required",
                )
            editable_policy.require_editable(resolved)
    except SandboxPathError as exc:
        raise SandboxShellError(str(exc.code), str(exc)) from exc
    return resolved


def _is_unsupported_shell_token(token: str) -> bool:
    return token in UNSUPPORTED_SHELL_TOKENS or (
        any(char in token for char in "<>|&(){}") and token not in COMMAND_SEPARATORS
    )


def _find_expression_start(args: tuple[str, ...]) -> int:
    for index, token in enumerate(args):
        if token.startswith("-"):
            return index
    return len(args)


def _require_integer_option_value(tokens: tuple[str, ...], index: int) -> int:
    value_index = index + 1
    if value_index >= len(tokens) or not tokens[value_index].isdigit():
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            f"{tokens[index]} requires a non-negative integer",
        )
    return value_index + 1


def _require_enum_option_value(
    tokens: tuple[str, ...],
    index: int,
    *,
    allowed_values: frozenset[str],
) -> int:
    value_index = index + 1
    if value_index >= len(tokens) or tokens[value_index] not in allowed_values:
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            f"{tokens[index]} requires one of: {', '.join(sorted(allowed_values))}",
        )
    return value_index + 1


def _require_pattern_option_value(tokens: tuple[str, ...], index: int) -> int:
    value_index = index + 1
    if value_index >= len(tokens):
        raise SandboxShellError(
            SandboxShellErrorCode.INVALID_COMMAND,
            f"{tokens[index]} requires a pattern",
        )
    pattern = tokens[value_index]
    if pattern.startswith("/") or ".." in Path(pattern).parts:
        raise SandboxShellError(
            SandboxShellErrorCode.PATH_DENIED,
            f"pattern escapes the sandbox: {pattern}",
        )
    return value_index + 1


def _mv_destination_relative_path(
    *,
    source_relative_path: str,
    destination: Path,
    destination_relative_path: str,
) -> str:
    if destination.exists() and destination.is_dir():
        source_name = Path(source_relative_path).name
        return f"{destination_relative_path.rstrip('/')}/{source_name}"
    return destination_relative_path


def _overlaps_protected_path(
    relative_path: str,
    protected_paths: tuple[str, ...],
) -> bool:
    normalized = relative_path.strip("/")
    return any(
        normalized == protected_path
        or protected_path.startswith(f"{normalized}/")
        or normalized.startswith(f"{protected_path}/")
        for protected_path in protected_paths
    )
