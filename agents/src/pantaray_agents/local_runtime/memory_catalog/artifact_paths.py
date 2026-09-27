from __future__ import annotations

from pathlib import Path, PurePosixPath


def tenant_artifact_relative_path(user_id: str) -> str:
    _validate_identity(user_id)
    return f"memory_catalog/users/{user_id}"


def legacy_tenant_artifact_relative_path(user_id: str) -> str:
    _validate_identity(user_id)
    return f"memory/users/{user_id}"


def memory_revision_relative_path(
    *, user_id: str, node_id: str, revision_id: str
) -> str:
    for value in (user_id, node_id, revision_id):
        _validate_identity(value)
    return "/".join(
        ("memory_catalog", "users", user_id, "nodes", node_id, "revisions", revision_id)
    )


def confined_artifact_path(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("artifact path must be a confined relative path")
    candidate = root.joinpath(*pure.parts)
    resolved_root = root.resolve()
    resolved_candidate = candidate.resolve()
    if resolved_root not in (resolved_candidate, *resolved_candidate.parents):
        raise ValueError("artifact path escapes its root")
    return candidate


def _validate_identity(value: str) -> None:
    if not value or "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError("memory artifact identity contains forbidden path characters")
