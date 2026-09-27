from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.tooling.resources.resource_recovery import (
    reconcile_tool_runtime_resources_for_startup,
)
from pantaray_agents.local_runtime.tooling.tool_result_finalization import (
    InvocationToolResultOwner,
    ToolResultFinalizationRequest,
    finalize_local_tool_result,
)

from .resource_recovery_test_support import (
    bootstrap_runtime_db,
    register_running_apply_patch_invocation,
    register_running_bash_invocation,
)

BUSY_TIMEOUT_MS = 1_000
COMPLETED_AT = "2026-03-23T00:00:03Z"


def test_invocation_completion_does_not_validate_unrelated_missing_root(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_bash_invocation(
        db_path=db_path,
        context=context,
    )
    shutil.rmtree(context.workspace_path)

    finalize_local_tool_result(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        request=ToolResultFinalizationRequest(
            owner=InvocationToolResultOwner(
                invocation_id=invocation_id,
                completed_at=COMPLETED_AT,
                status="completed",
                completion_scope="invocation",
            ),
            output={
                "status": "success",
                "stdout": "done",
                "stderr": "",
                "exit_code": 0,
            },
        ),
    )

    assert context.tool_results_path.is_dir()
    assert _invocation_status(db_path, invocation_id) == "completed"


def test_startup_recovery_does_not_validate_unrelated_missing_root(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_bash_invocation(
        db_path=db_path,
        context=context,
    )
    shutil.rmtree(context.workspace_path)

    recovered_count = reconcile_tool_runtime_resources_for_startup(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )

    assert recovered_count == 0
    assert context.tool_results_path.is_dir()
    assert _invocation_status(db_path, invocation_id) == "failed"


def test_file_reference_completion_validates_only_containing_root(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_apply_patch_invocation(
        db_path=db_path,
        context=context,
    )
    (context.workspace_path / "result.txt").write_text("done\n", encoding="utf-8")
    _register_missing_folder_root(
        db_path=db_path,
        manifest_id=context.manifest_id,
        missing_path=tmp_path / "missing-folder-root",
    )

    finalize_local_tool_result(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        request=ToolResultFinalizationRequest(
            owner=InvocationToolResultOwner(
                invocation_id=invocation_id,
                completed_at=COMPLETED_AT,
                status="completed",
                completion_scope="invocation",
            ),
            output={"status": "success", "applied_paths": ["result.txt"]},
            file_reference_paths=("result.txt",),
        ),
    )

    assert _invocation_status(db_path, invocation_id) == "completed"
    assert _file_reference_root_id(db_path, invocation_id) == ("root:action-1:scratch")


def test_file_reference_completion_rejects_path_outside_manifest_roots(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_apply_patch_invocation(
        db_path=db_path,
        context=context,
    )
    outside_path = tmp_path / "outside.txt"
    outside_path.write_text("outside\n", encoding="utf-8")

    with pytest.raises(MigrationError, match="outside manifest roots"):
        finalize_local_tool_result(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            request=ToolResultFinalizationRequest(
                owner=InvocationToolResultOwner(
                    invocation_id=invocation_id,
                    completed_at=COMPLETED_AT,
                    status="completed",
                    completion_scope="invocation",
                ),
                output={"status": "success", "applied_paths": ["outside.txt"]},
                file_reference_paths=(str(outside_path),),
            ),
        )

    assert _invocation_status(db_path, invocation_id) == "running"


def test_file_reference_completion_uses_most_specific_root(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_apply_patch_invocation(
        db_path=db_path,
        context=context,
    )
    nested_root = context.workspace_path / "nested"
    target = nested_root / "result.txt"
    nested_root.mkdir()
    target.write_text("done\n", encoding="utf-8")
    _register_folder_root(
        db_path=db_path,
        manifest_id=context.manifest_id,
        root_id="root:nested",
        real_path=nested_root,
        canonical_path=nested_root.resolve(),
    )

    finalize_local_tool_result(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        request=ToolResultFinalizationRequest(
            owner=InvocationToolResultOwner(
                invocation_id=invocation_id,
                completed_at=COMPLETED_AT,
                status="completed",
                completion_scope="invocation",
            ),
            output={"status": "success", "applied_paths": ["nested/result.txt"]},
            file_reference_paths=("nested/result.txt",),
        ),
    )

    assert _file_reference_root_id(db_path, invocation_id) == "root:nested"


def test_file_reference_completion_rejects_selected_root_retargeting(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_apply_patch_invocation(
        db_path=db_path,
        context=context,
    )
    nested_root = context.workspace_path / "nested"
    nested_root.mkdir()
    (nested_root / "result.txt").write_text("done\n", encoding="utf-8")
    nested_alias = tmp_path / "nested-alias"
    nested_alias.symlink_to(nested_root, target_is_directory=True)
    _register_folder_root(
        db_path=db_path,
        manifest_id=context.manifest_id,
        root_id="root:nested",
        real_path=nested_alias,
        canonical_path=nested_root.resolve(),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    nested_alias.unlink()
    nested_alias.symlink_to(outside, target_is_directory=True)

    with pytest.raises(MigrationError, match="approved target"):
        finalize_local_tool_result(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            request=ToolResultFinalizationRequest(
                owner=InvocationToolResultOwner(
                    invocation_id=invocation_id,
                    completed_at=COMPLETED_AT,
                    status="completed",
                    completion_scope="invocation",
                ),
                output={
                    "status": "success",
                    "applied_paths": ["nested/result.txt"],
                },
                file_reference_paths=("nested/result.txt",),
            ),
        )

    assert _invocation_status(db_path, invocation_id) == "running"


def test_file_reference_completion_rejects_child_symlink_escape(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_runtime_db(tmp_path)
    invocation_id = register_running_apply_patch_invocation(
        db_path=db_path,
        context=context,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
    (context.workspace_path / "escape").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(MigrationError, match="outside manifest roots"):
        finalize_local_tool_result(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            request=ToolResultFinalizationRequest(
                owner=InvocationToolResultOwner(
                    invocation_id=invocation_id,
                    completed_at=COMPLETED_AT,
                    status="completed",
                    completion_scope="invocation",
                ),
                output={
                    "status": "success",
                    "applied_paths": ["escape/secret.txt"],
                },
                file_reference_paths=("escape/secret.txt",),
            ),
        )

    assert _invocation_status(db_path, invocation_id) == "running"


def _invocation_status(db_path: Path, invocation_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status FROM tool_invocations WHERE invocation_id = ?",
            (invocation_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _register_missing_folder_root(
    *,
    db_path: Path,
    manifest_id: str,
    missing_path: Path,
) -> None:
    _register_folder_root(
        db_path=db_path,
        manifest_id=manifest_id,
        root_id="root:missing-folder",
        real_path=missing_path,
        canonical_path=missing_path.resolve(),
    )


def _register_folder_root(
    *,
    db_path: Path,
    manifest_id: str,
    root_id: str,
    real_path: Path,
    canonical_path: Path,
) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO workspace_manifest_roots(
                root_id,
                manifest_id,
                source_type,
                source_id,
                display_name,
                canonical_real_path,
                real_path,
                can_read,
                can_apply_patch,
                can_process_read,
                can_process_write,
                created_at
            ) VALUES (?, ?, 'folder', ?, ?, ?, ?, 1, 1, 1, 1, ?)
            """,
            (
                root_id,
                manifest_id,
                f"folder:{root_id}",
                root_id,
                str(canonical_path),
                str(real_path),
                "2026-03-23T00:00:00Z",
            ),
        )


def _file_reference_root_id(db_path: Path, invocation_id: str) -> str:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT root_id
            FROM file_references
            WHERE tool_invocation_id = ?
            """,
            (invocation_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])
