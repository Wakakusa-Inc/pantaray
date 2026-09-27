from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.agents.action_agent.runtime.checkpoint import (
    RUNTIME_STATE_CHECKPOINT_VERSION,
)
from pantaray_agents.local_runtime.runtime import (
    action_legacy_shared_temp_core_authority as authority_module,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .legacy_action_shared_temp_test_support import seed_legacy_shared_temp_action


def _load(
    db_path: Path,
) -> tuple[authority_module.LegacyActionSharedTempCoreAuthority, ...]:
    return authority_module.load_legacy_action_shared_temp_core_authorities(
        db_path=db_path, busy_timeout_ms=1_000
    )


def test_loads_exact_legacy_shared_temp_core_authority(tmp_path: Path) -> None:
    db_path, context, fixed_root = seed_legacy_shared_temp_action(tmp_path)

    authorities = _load(db_path)

    assert len(authorities) == 1
    authority = authorities[0]
    assert (authority.user_id, authority.action_id) == ("user-1", "action-1")
    assert authority.fixed_root_path == fixed_root
    assert authority.manifest.manifest_id == context.manifest_id
    assert authority.sessions[0].action_temp_dir == str(fixed_root)
    assert authority.checkpoints[0].version == RUNTIME_STATE_CHECKPOINT_VERSION
    assert json.loads(authority.checkpoints[0].raw_json)["action_id"] == "action-1"


def test_db_symlink_retarget_does_not_mix_storage_owners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_a = tmp_path / "owner-a"
    owner_b = tmp_path / "owner-b"
    for owner in (owner_a, owner_b):
        owner.mkdir()
    db_a, _, fixed_root_a = seed_legacy_shared_temp_action(owner_a)
    db_b, _, _ = seed_legacy_shared_temp_action(owner_b)
    db_link = tmp_path / "runtime.db"
    db_link.symlink_to(db_a)
    real_connect = sqlite3.connect

    def connect_then_retarget(database: str, *, uri: bool) -> sqlite3.Connection:
        connection = real_connect(database, uri=uri)
        db_link.unlink()
        db_link.symlink_to(db_b)
        return connection

    monkeypatch.setattr(authority_module.sqlite3, "connect", connect_then_retarget)

    authorities = _load(db_link)

    assert authorities[0].fixed_root_path == fixed_root_a


def test_rejects_producer_checkpoint_payload_owner_mismatch(tmp_path: Path) -> None:
    db_path, _, _ = seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """UPDATE agent_action_steps SET runtime_state_checkpoint=json_set(
                   runtime_state_checkpoint,'$.user_id','user-2')"""
        )

    with pytest.raises(MigrationError, match="checkpoint payload ownership"):
        _load(db_path)


@pytest.mark.parametrize("version", [1, 3])
def test_accepts_known_historical_checkpoint_common_projection(
    tmp_path: Path, version: int
) -> None:
    db_path, _, _ = seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE agent_action_steps SET runtime_state_checkpoint_version=?",
            (version,),
        )

    assert _load(db_path)[0].checkpoints[0].version == version


@pytest.mark.parametrize(
    ("version", "manifest_id"),
    [(5, "manifest:action-1"), (4, None), (4, "manifest:other")],
)
def test_rejects_unknown_or_inconsistent_historical_checkpoint(
    tmp_path: Path, version: int, manifest_id: str | None
) -> None:
    db_path, _, _ = seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """UPDATE agent_action_steps
               SET runtime_state_checkpoint_version=?,
                   runtime_state_checkpoint=json_set(
                       runtime_state_checkpoint,'$.manifest_id',?)""",
            (version, manifest_id),
        )

    with pytest.raises(MigrationError, match="checkpoint"):
        _load(db_path)


def test_rejects_mixed_legacy_and_session_leaf_paths(tmp_path: Path) -> None:
    db_path, context, fixed_root = seed_legacy_shared_temp_action(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE execution_sessions SET action_temp_dir = ?",
            (str(fixed_root / context.execution_session_id),),
        )

    with pytest.raises(MigrationError, match="manifest/session authority"):
        _load(db_path)
