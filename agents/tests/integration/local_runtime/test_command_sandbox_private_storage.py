from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from tests.unit.local_runtime.broker_test_support import _register_folder_mount

from pantaray_agents.local_runtime.tooling.action_session_temp_paths import (
    resolve_action_storage_paths,
)
from pantaray_agents.local_runtime.tooling.repository import load_execution_session

from .support import (
    SEATBELT_SKIP_REASON,
    bootstrap_runtime_testbed,
    compile_workspace_binary,
    execute_bash,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


@pytest.mark.asyncio
async def test_broad_folder_grant_cannot_expose_private_app_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_data = tmp_path / "app-data"
    app_data.mkdir()
    testbed = bootstrap_runtime_testbed(tmp_path=app_data, monkeypatch=monkeypatch)
    artifacts = tmp_path / "external-artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("LOCAL_ARTIFACT_ROOT", str(artifacts))
    session = load_execution_session(
        db_path=testbed.db_path,
        busy_timeout_ms=1_000,
        execution_session_id=testbed.context.execution_session_id,
    )
    assert session.action_id is not None
    storage = resolve_action_storage_paths(
        db_path=testbed.db_path, user_id="user-1", action_id=session.action_id
    )
    other = resolve_action_storage_paths(
        db_path=testbed.db_path, user_id="user-1", action_id="other-action"
    )
    other.workspace.mkdir(parents=True)
    secret = app_data / "credentials.json"
    private_artifact = artifacts / "private.txt"
    other_file = other.workspace / "private.txt"
    public_file = storage.tool_results / "published.txt"
    ordinary = storage.workspace / "ordinary.txt"
    for path in (secret, private_artifact, other_file, public_file, ordinary):
        path.write_text("original", encoding="utf-8")
    alias = storage.workspace / "secret-link"
    alias.symlink_to(secret)
    folder = _register_folder_mount(
        db_path=testbed.db_path, real_path=tmp_path, display_name="Broad folder"
    )
    with sqlite3.connect(testbed.db_path) as connection:
        connection.execute(
            """INSERT INTO workspace_manifest_roots(
                root_id, manifest_id, source_type, source_id, display_name,
                canonical_real_path, real_path, can_read, can_apply_patch,
                can_process_read, can_process_write, created_at
            ) VALUES ('broad', ?, 'folder', ?, 'Broad folder', ?, ?, 1, 1, 1, 1,
                '2026-09-11T00:00:00Z')""",
            (
                testbed.context.manifest_id,
                folder.folder_id,
                str(tmp_path),
                str(tmp_path),
            ),
        )
    # fopen without truncation probes write authority without altering app data.
    cases = [
        (testbed.db_path, False, False),
        (secret, False, False),
        (private_artifact, False, False),
        (other_file, False, False),
        (alias, False, False),
        (public_file, True, False),
        (ordinary, True, True),
    ]
    statements = "\n".join(
        f"check({json.dumps(str(path))}, {int(read)}, {int(write)});"
        for path, read, write in cases
    )
    compile_workspace_binary(
        workspace_path=storage.workspace,
        executable_name="storageprobe",
        source_code="""
#include <stdio.h>
static int failures = 0;
void check(const char *path, int read_allowed, int write_allowed) {
    FILE *read = fopen(path, "r");
    FILE *write = fopen(path, "r+");
    if ((read != NULL) != read_allowed || (write != NULL) != write_allowed) {
        fprintf(stderr, "unexpected access: %s read=%d write=%d\\n", path,
            read != NULL, write != NULL);
        failures++;
    }
    if (read) fclose(read);
    if (write) fclose(write);
}
int main(void) {
"""
        + statements
        + "\nreturn failures ? 1 : 0;\n}\n",
    )
    outcome = await execute_bash(testbed=testbed, command="storageprobe")
    assert outcome.status == "success", outcome.output
    for path in (secret, private_artifact, other_file, public_file, ordinary):
        assert path.read_text(encoding="utf-8") == "original"
