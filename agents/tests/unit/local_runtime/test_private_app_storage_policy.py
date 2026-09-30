from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from tests.unit.local_runtime.ripgrep_backend_test_support import (
    install_fake_ripgrep_backend,
)

from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_artifact_root,
)
from pantaray_agents.local_runtime.tooling.brokering.broker import (
    BrokerPolicyError,
    execute_broker_tool,
)
from pantaray_agents.local_runtime.tooling.brokering.manifest_paths import (
    load_tool_results_root,
)
from pantaray_agents.local_runtime.tooling.brokering.tool_path_policy import (
    EXEC_CWD_DENIED,
    READ_PATH_DENIED,
)
from pantaray_agents.local_runtime.tooling.repository.workspace_settings import (
    READ_ACCESS_SCOPE_FULL_ACCESS,
)
from pantaray_agents.schema.agent.base import JSONValue

from .broker_test_support import BROKER_ACTOR_PROCESS_ID
from .path_access_policy_support import (
    ACTION_ID,
    USER_ID,
    bootstrap_path_policy_runtime_db,
)

_TOOL_IDS = ("read", "list", "glob", "grep", "bash")


async def _run(
    *, db_path: Path, context: object, tool_id: str, args: dict[str, JSONValue]
):
    return await execute_broker_tool(
        db_path=db_path,
        busy_timeout_ms=1_000,
        tool_id=tool_id,
        user_id=USER_ID,
        actor_process_id=BROKER_ACTOR_PROCESS_ID,
        manifest_id=context.manifest_id,  # type: ignore[attr-defined]
        execution_session_id=context.execution_session_id,  # type: ignore[attr-defined]
        tool_request_id=f"request-{uuid4().hex}",
        preflight_only=tool_id == "bash",
        args=args,
    )


def _search_args(tool_id: str, base: str) -> dict[str, JSONValue]:
    if tool_id == "read":
        return {"path": base}
    if tool_id == "list":
        return {"path": base, "max_depth": 6, "limit": 50}
    if tool_id == "glob":
        return {"base_path": base, "pattern": "**/*.txt", "limit": 50}
    return {
        "base_path": base,
        "pattern": "needle",
        "include_glob": "**/*.txt",
        "max_matches": 50,
    }


def _case_alias(path: Path) -> Path:
    alias = path.with_name(path.name.swapcase())
    return alias if alias.exists() else path


@pytest.mark.asyncio
async def test_full_access_read_tools_refuse_private_app_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_ripgrep_backend(monkeypatch)
    db_path, context = bootstrap_path_policy_runtime_db(
        tmp_path,
        allowed_tool_ids=_TOOL_IDS,
        read_access_scope=READ_ACCESS_SCOPE_FULL_ACCESS,
    )
    storage = db_path.parent
    (storage / "notes.txt").write_text("needle secret\n", encoding="utf-8")
    workspace = context.workspace_path
    (workspace / "storage-link").symlink_to(storage)
    up_to_storage = os.path.relpath(storage, workspace)
    artifact_root = read_local_runtime_artifact_root()
    artifact_root.mkdir(parents=True, exist_ok=True)

    targets = (
        str(storage),
        str(_case_alias(storage.resolve())),
        "storage-link",
        up_to_storage,
        str(workspace.parent),  # another part of the Action's own storage
        str(artifact_root),
    )
    for tool_id in ("read", "list", "glob", "grep"):
        for target in targets:
            with pytest.raises(BrokerPolicyError) as caught:
                await _run(
                    db_path=db_path,
                    context=context,
                    tool_id=tool_id,
                    args=_search_args(tool_id, target),
                )
            assert caught.value.code == READ_PATH_DENIED, (tool_id, target)
            assert "memory_sql" in str(caught.value.fix_hint)

    for path in (
        str(storage / "notes.txt"),
        "storage-link/notes.txt",
        f"{up_to_storage}/notes.txt",
        str(storage / "notes-missing.txt"),
    ):
        with pytest.raises(BrokerPolicyError) as caught:
            await _run(
                db_path=db_path,
                context=context,
                tool_id="read",
                args={"path": path},
            )
        assert caught.value.code == READ_PATH_DENIED, path


@pytest.mark.asyncio
async def test_own_workspace_and_results_stay_readable_inside_app_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_ripgrep_backend(monkeypatch)
    db_path, context = bootstrap_path_policy_runtime_db(
        tmp_path,
        allowed_tool_ids=_TOOL_IDS,
        read_access_scope=READ_ACCESS_SCOPE_FULL_ACCESS,
    )
    (db_path.parent / "notes.txt").write_text("needle secret\n", encoding="utf-8")
    workspace_file = context.workspace_path / "work.txt"
    workspace_file.write_text("needle work\n", encoding="utf-8")
    results = load_tool_results_root(
        db_path=db_path,
        busy_timeout_ms=1_000,
        user_id=USER_ID,
        manifest_id=context.manifest_id,
        action_id=ACTION_ID,
    )
    results.mkdir(parents=True, exist_ok=True)
    result_file = results / "result.txt"
    result_file.write_text("needle result\n", encoding="utf-8")

    for path, content in ((workspace_file, "needle work\n"), (result_file, None)):
        read = await _run(
            db_path=db_path,
            context=context,
            tool_id="read",
            args={"path": str(path)},
        )
        assert read.status == "success"
        if content is not None:
            assert read.output["content"] == content

    # Searched from above app storage, only the Action's own roots show, also
    # through a case alias on a case-insensitive volume.
    above_storage = str(_case_alias(tmp_path.resolve()))
    for tool_id in ("list", "glob", "grep"):
        outcome = await _run(
            db_path=db_path,
            context=context,
            tool_id=tool_id,
            args=_search_args(tool_id, above_storage),
        )
        items = outcome.output["entries" if tool_id == "list" else "matches"]
        paths = [Path(str(item["path"])) for item in items]
        # list stops at max_depth 6, which reaches the workspace folder itself.
        visible = context.workspace_path if tool_id == "list" else workspace_file
        assert any(path.samefile(visible) for path in paths), tool_id
        for private in (db_path.parent, db_path.parent / "notes.txt"):
            assert not any(path.samefile(private) for path in paths), tool_id
        assert "needle secret" not in (outcome.search_text or ""), tool_id


@pytest.mark.asyncio
async def test_command_cwd_in_app_storage_points_to_memory_sql(
    tmp_path: Path,
) -> None:
    db_path, context = bootstrap_path_policy_runtime_db(
        tmp_path,
        allowed_tool_ids=_TOOL_IDS,
        read_access_scope=READ_ACCESS_SCOPE_FULL_ACCESS,
    )

    with pytest.raises(BrokerPolicyError) as caught:
        await _run(
            db_path=db_path,
            context=context,
            tool_id="bash",
            args={"command": "ls", "cwd": str(db_path.parent)},
        )

    assert caught.value.code == EXEC_CWD_DENIED
    assert "private app storage" in str(caught.value)
    assert "memory_sql" in str(caught.value.fix_hint)
