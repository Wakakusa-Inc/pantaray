"""Canonical command descriptions shared by consent and invocation auditing."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pantaray_agents.schema.agent.base import JSONValue


def build_apply_patch_summary(
    *,
    patch_paths: tuple[str, ...],
    outside_workspace_folder: Path | None = None,
    outside_workspace_grantable: bool = False,
) -> dict[str, JSONValue]:
    summary: dict[str, JSONValue] = {
        "summary_kind": "apply_patch",
        "target_paths": list(patch_paths),
    }
    return _with_outside_workspace(
        summary,
        outside_workspace_folder,
        can_allow_for_conversation=outside_workspace_grantable,
    )


def build_bash_summary(
    *,
    command: str,
    cwd_relative_path: str,
    timeout_ms: int,
    use_login_environment: bool,
    outside_workspace_folder: Path | None = None,
) -> dict[str, JSONValue]:
    summary: dict[str, JSONValue] = {
        "summary_kind": "bash",
        "command": command,
        "cwd": cwd_relative_path,
        "timeout_ms": timeout_ms,
        "use_login_environment": use_login_environment,
    }
    # An outside command cwd is approvable only when it could be granted.
    return _with_outside_workspace(
        summary, outside_workspace_folder, can_allow_for_conversation=True
    )


def build_run_python_summary(
    *,
    cwd_relative_path: str,
    code: str,
    args_count: int,
    timeout_ms: int,
    outside_workspace_folder: Path | None = None,
) -> dict[str, JSONValue]:
    encoded_code = code.encode("utf-8")
    summary: dict[str, JSONValue] = {
        "summary_kind": "run_python",
        "cwd": cwd_relative_path,
        "code_sha256": sha256(encoded_code).hexdigest(),
        "code_size_bytes": len(encoded_code),
        "args_count": args_count,
        "timeout_ms": timeout_ms,
    }
    # An outside command cwd is approvable only when it could be granted.
    return _with_outside_workspace(
        summary, outside_workspace_folder, can_allow_for_conversation=True
    )


def _with_outside_workspace(
    summary: dict[str, JSONValue],
    folder: Path | None,
    *,
    can_allow_for_conversation: bool,
) -> dict[str, JSONValue]:
    if folder is not None:
        # The approval UI reads this exact shape to name the folder being opened
        # and to offer "Allow for this conversation".
        summary["outside_workspace"] = {
            "folder_path": str(folder),
            "folder_display_name": folder.name or str(folder),
            "can_allow_for_conversation": can_allow_for_conversation,
        }
    return summary
