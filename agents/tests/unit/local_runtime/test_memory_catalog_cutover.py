from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.memory_catalog.cutover import (
    CUTOVER_NAME,
    run_memory_catalog_cutover,
)
from pantaray_agents.local_runtime.memory_catalog.cutover_support import (
    create_preflight_backup,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.erasure import (
    erase_user_memory_offline,
)
from pantaray_agents.local_runtime.memory_catalog.errors import MemoryCutoverError
from pantaray_agents.local_runtime.memory_catalog.repository import (
    ensure_preparing_node,
)
from pantaray_agents.local_runtime.storage.memory_artifact_projection import (
    MemoryArtifactProjection,
    upsert_memory_artifact_projection,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
NOW = "2026-07-18T00:00:00Z"


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "runtime.db"
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO users(user_id, ui_language, created_at, updated_at)
            VALUES (?, 'ja', ?, ?)
            """,
            (USER_ID, NOW, NOW),
        )
    return db_path, artifact_root


def _insert_activity_log(
    connection: sqlite3.Connection, *, log_id: str, description: str, minute: int
) -> None:
    timestamp = f"2026-07-18T00:{minute:02d}:00Z"
    connection.execute(
        """
        INSERT INTO activity_logs(
            log_id, user_id, period_start, period_end, description, status,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'success', 'activity', '1.0', ?, ?)
        """,
        (log_id, USER_ID, timestamp, timestamp, description, timestamp, timestamp),
    )


def test_preflight_backup_removes_partial_copy_after_artifact_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    legacy_root = artifact_root / "memory"
    legacy_root.mkdir()

    def _leave_partial_copy_then_fail(
        source: Path,
        destination: Path,
        **_: object,
    ) -> None:
        assert source == legacy_root
        destination.mkdir(parents=True)
        (destination / "partial.md").write_text("partial", encoding="utf-8")
        raise OSError("simulated artifact backup failure")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.cutover_support.shutil.copytree",
        _leave_partial_copy_then_fail,
    )

    with pytest.raises(OSError, match="simulated artifact backup failure"):
        create_preflight_backup(db_path=db_path, artifact_root=artifact_root)

    assert not tuple(tmp_path.glob("runtime.db.pre-memory-catalog-*.bak"))
    assert not tuple(tmp_path.glob("artifacts.pre-memory-catalog-*.bak"))


def test_cutover_imports_valid_links_and_quarantines_broken_tags(
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    valid_tag = '[[ref:ref_valid note:"same provider boundary"]]'
    broken_tag = '[[ref:ref_broken note:"missing target"]]'
    with sqlite3.connect(db_path) as connection:
        _insert_activity_log(
            connection,
            log_id="source-valid",
            description=f"The same failure appeared. {valid_tag}",
            minute=0,
        )
        _insert_activity_log(
            connection,
            log_id="source-broken",
            description=f"This relation is invalid. {broken_tag}",
            minute=1,
        )
        _insert_activity_log(
            connection,
            log_id="target",
            description="The provider boundary failed earlier.",
            minute=2,
        )
        connection.execute(
            """
            INSERT INTO memory_record_references(
                user_id, owner_memory_key, local_ref_id, target_memory_key,
                reference_note, anchor_text, anchor_order, created_at, updated_at
            ) VALUES (?, ?, 'ref_valid', ?, 'same provider boundary',
                      'The same failure appeared.', 0, ?, ?)
            """,
            (
                USER_ID,
                "activity_log:source-valid",
                "activity_log:target",
                NOW,
                NOW,
            ),
        )

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )
    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        state = connection.execute(
            "SELECT state FROM memory_catalog_cutovers WHERE cutover_name = ?",
            (CUTOVER_NAME,),
        ).fetchone()
        assert state is not None and state["state"] == "completed"
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 3
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_links").fetchone()[0] == 1
        )
        quarantined = connection.execute(
            "SELECT reason, source_markup FROM memory_link_quarantine"
        ).fetchone()
        assert quarantined is not None
        assert quarantined["reason"] == "missing_mapping"
        assert quarantined["source_markup"] == broken_tag
        repaired = connection.execute(
            """
            SELECT revisions.inline_body
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.user_id = nodes.user_id
             AND revisions.revision_id = nodes.current_revision_id
            WHERE nodes.source_type = 'activity_log'
              AND nodes.source_record_id = 'source-broken'
            """
        ).fetchone()
    assert repaired is not None
    assert repaired["inline_body"] == "This relation is invalid."


def test_cutover_uses_latest_long_term_artifact_as_reference_owner(
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    reference = '[[ref:shared_ref note:"current relationship"]]'
    old_time = "2026-07-17T00:00:00Z"
    artifacts = (
        ("old-generation", old_time, "Old generation without the current reference."),
        ("new-generation", NOW, f"Current generation. {reference}"),
    )
    with sqlite3.connect(db_path) as connection:
        _insert_activity_log(
            connection,
            log_id="old-target",
            description="Legacy relationship target.",
            minute=1,
        )
        _insert_activity_log(
            connection,
            log_id="new-target",
            description="Current relationship target.",
            minute=2,
        )
        connection.executemany(
            """
            INSERT INTO memory_record_references(
                user_id, owner_memory_key, local_ref_id, target_memory_key,
                reference_note, anchor_text, anchor_order, created_at, updated_at
            ) VALUES (?, ?, 'shared_ref', ?, 'current relationship',
                      'Current generation.', 0, ?, ?)
            """,
            (
                (
                    USER_ID,
                    "long_term_insight:old-generation",
                    "activity_log:old-target",
                    old_time,
                    old_time,
                ),
                (
                    USER_ID,
                    "long_term_insight:new-generation",
                    "activity_log:new-target",
                    NOW,
                    NOW,
                ),
            ),
        )
    for generation, updated_at, content in artifacts:
        root_path = f"memory/users/{USER_ID}/long-term/{generation}"
        relative_path = "memory.md"
        artifact_path = artifact_root / root_path / relative_path
        artifact_path.parent.mkdir(parents=True)
        artifact_path.write_text(content, encoding="utf-8")
        payload = content.encode()
        upsert_memory_artifact_projection(
            db_path=str(db_path),
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            projection=MemoryArtifactProjection(
                user_id=USER_ID,
                source_type="long_term_insight",
                source_record_id=generation,
                root_path=root_path,
                relative_path=relative_path,
                content=content,
                sha256=hashlib.sha256(payload).hexdigest(),
                byte_size=len(payload),
                logical_created_at=updated_at,
                logical_updated_at=updated_at,
            ),
        )

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    with sqlite3.connect(db_path) as connection:
        target = connection.execute(
            """
            SELECT nodes.source_record_id
            FROM memory_links AS links
            JOIN memory_fragments AS fragments
              ON fragments.user_id = links.user_id
             AND fragments.fragment_id = links.target_fragment_id
            JOIN memory_revisions AS revisions
              ON revisions.user_id = fragments.user_id
             AND revisions.revision_id = fragments.revision_id
            JOIN memory_nodes AS nodes
              ON nodes.user_id = revisions.user_id
             AND nodes.node_id = revisions.node_id
            WHERE links.local_ref_id = 'shared_ref'
            """
        ).fetchone()

    assert target == ("new-target",)


def test_cutover_materializes_fact_artifact_into_catalog(tmp_path: Path) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    content = "# Facts\n\nA durable fact.\n"
    root_path = "memory/users/user-1/facts/fact-1"
    relative_path = "facts/index.md"
    artifact_path = artifact_root / root_path / relative_path
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(content, encoding="utf-8")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO agent_facts(
                fact_id, user_id, status, facts_profile_brief, prompt_name,
                prompt_version, source_insight_ids, created_at, updated_at
            ) VALUES ('fact-1', ?, 'success', 'brief', 'fact', '1.0', '[]', ?, ?)
            """,
            (USER_ID, NOW, NOW),
        )
    upsert_memory_artifact_projection(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        projection=MemoryArtifactProjection(
            user_id=USER_ID,
            source_type="facts",
            source_record_id="fact-1",
            root_path=root_path,
            relative_path=relative_path,
            content=content,
            sha256=hashlib.sha256(content.encode()).hexdigest(),
            byte_size=len(content.encode()),
            logical_created_at=NOW,
            logical_updated_at=NOW,
        ),
    )

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT revisions.artifact_root_path, fragments.content_text
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.user_id = nodes.user_id
             AND revisions.revision_id = nodes.current_revision_id
            JOIN memory_fragments AS fragments
              ON fragments.user_id = revisions.user_id
             AND fragments.revision_id = revisions.revision_id
            WHERE nodes.source_type = 'fact'
              AND nodes.source_record_id = 'fact-1'
              AND fragments.source_path = 'facts/index.md'
              AND fragments.block_kind = 'document_root'
            """
        ).fetchone()
    assert row is not None
    assert row["content_text"] == content
    catalog_path = str(row["artifact_root_path"])
    assert catalog_path.startswith("memory_catalog/users/user-1/")
    assert (artifact_root / catalog_path / relative_path).is_file()
    assert not (artifact_root / "memory").exists()
    assert not (artifact_root / "memory_catalog" / "cutover_staging").exists()
    assert not tuple(tmp_path.glob("runtime.db.pre-memory-catalog-*.bak"))
    assert not tuple(tmp_path.glob("artifacts.pre-memory-catalog-*.bak"))

    result = erase_user_memory_offline(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        user_id=USER_ID,
    )

    assert result.erased is True
    assert not (artifact_root / "memory_catalog" / "users" / USER_ID).exists()


def test_cutover_rejects_an_incomplete_prior_run(tmp_path: Path) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_catalog_cutovers(
                cutover_name, state, inventory_json, started_at
            ) VALUES (?, 'running', '{}', ?)
            """,
            (CUTOVER_NAME, NOW),
        )

    with pytest.raises(MemoryCutoverError, match="restore the preflight backup"):
        run_memory_catalog_cutover(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
        )


def test_cutover_rejects_pending_user_erasure_without_mutating_it(
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO memory_artifact_deletions(
                user_id, deletion_id, artifact_path, reason, state,
                created_at, updated_at
            ) VALUES (
                ?, 'erase-1', 'memory_catalog/erasure/user-1-erase-1',
                'user_erasure', 'planned', ?, ?
            )
            """,
            (USER_ID, NOW, NOW),
        )

    with pytest.raises(MemoryCutoverError, match="user memory erasure"):
        run_memory_catalog_cutover(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
        )

    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM memory_artifact_deletions
            WHERE deletion_id = 'erase-1' AND state = 'planned'
            """
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM memory_catalog_cutovers"
            ).fetchone()[0]
            == 0
        )


def test_cutover_rebuilds_an_unactivated_partial_catalog(tmp_path: Path) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            _insert_activity_log(
                connection,
                log_id="source-partial",
                description="Authoritative activity.",
                minute=0,
            )
            register_inline_domain_memory(
                connection=connection,
                user_id=USER_ID,
                source="activity_log",
                source_record_id="source-partial",
                content="Untrusted partial activity.",
            )
            ensure_preparing_node(
                connection=connection,
                user_id=USER_ID,
                source="fact",
                source_record_id="orphan-fact",
            )
    partial_artifact = artifact_root / "memory_catalog" / "partial" / "orphan.md"
    partial_artifact.parent.mkdir(parents=True)
    partial_artifact.write_text("untrusted", encoding="utf-8")

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        nodes = connection.execute(
            """
            SELECT source_type, source_record_id, lifecycle
            FROM memory_nodes
            ORDER BY source_type, source_record_id
            """
        ).fetchall()
        cutover = connection.execute(
            "SELECT state, inventory_json FROM memory_catalog_cutovers"
        ).fetchone()
        body = connection.execute(
            """
            SELECT revisions.inline_body
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.user_id = nodes.user_id
             AND revisions.revision_id = nodes.current_revision_id
            WHERE nodes.source_type = 'activity_log'
              AND nodes.source_record_id = 'source-partial'
            """
        ).fetchone()

    assert [
        (row["source_type"], row["source_record_id"], row["lifecycle"]) for row in nodes
    ] == [("activity_log", "source-partial", "active")]
    assert body is not None and body["inline_body"] == "Authoritative activity."
    assert cutover is not None and cutover["state"] == "completed"
    inventory = json.loads(str(cutover["inventory_json"]))
    assert inventory["discarded_partial_catalog_rows"] > 0
    assert inventory["discarded_partial_catalog_artifacts"] is True
    assert not partial_artifact.exists()
    assert not tuple(tmp_path.glob("runtime.db.pre-memory-catalog-*.bak"))
    assert not tuple(tmp_path.glob("artifacts.pre-memory-catalog-*.bak"))


def test_failed_rebuild_keeps_a_complete_preflight_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            _insert_activity_log(
                connection,
                log_id="source-partial",
                description="Authoritative activity.",
                minute=0,
            )
            register_inline_domain_memory(
                connection=connection,
                user_id=USER_ID,
                source="activity_log",
                source_record_id="source-partial",
                content="Untrusted partial activity.",
            )
    partial_artifact = artifact_root / "memory_catalog" / "partial" / "orphan.md"
    partial_artifact.parent.mkdir(parents=True)
    partial_artifact.write_text("untrusted", encoding="utf-8")

    def _fail_planning(**_: object) -> None:
        raise ValueError("simulated planning failure")

    monkeypatch.setattr(
        "pantaray_agents.local_runtime.memory_catalog.cutover._plan_records",
        _fail_planning,
    )

    with pytest.raises(MemoryCutoverError, match="restore"):
        run_memory_catalog_cutover(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
        )

    with sqlite3.connect(db_path) as connection:
        state, inventory_json = connection.execute(
            """
            SELECT state, inventory_json
            FROM memory_catalog_cutovers
            WHERE cutover_name = ?
            """,
            (CUTOVER_NAME,),
        ).fetchone()
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 0
        )
    inventory = json.loads(str(inventory_json))
    database_backup = Path(str(inventory["backup_database"]))
    artifact_backup = Path(str(inventory["backup_artifacts"]))
    assert state == "failed"
    assert database_backup.is_file()
    with sqlite3.connect(database_backup) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 1
        )
    assert (artifact_backup / "memory_catalog" / "partial" / "orphan.md").read_text(
        encoding="utf-8"
    ) == "untrusted"


def test_empty_cutover_retires_the_legacy_memory_tree(tmp_path: Path) -> None:
    db_path, artifact_root = _bootstrap(tmp_path)
    legacy_file = artifact_root / "memory" / "users" / USER_ID / "orphan.md"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text("retired memory", encoding="utf-8")

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    assert not (artifact_root / "memory").exists()
    assert not tuple(tmp_path.glob("runtime.db.pre-memory-catalog-*.bak"))
    assert not tuple(tmp_path.glob("artifacts.pre-memory-catalog-*.bak"))
    residual_staging = artifact_root / "memory_catalog" / "cutover_staging" / "old"
    residual_staging.mkdir(parents=True)
    (residual_staging / "memory.md").write_text("staged memory", encoding="utf-8")
    residual_legacy = artifact_root / "memory" / "users" / USER_ID / "old.md"
    residual_legacy.parent.mkdir(parents=True)
    residual_legacy.write_text("legacy memory", encoding="utf-8")

    run_memory_catalog_cutover(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
    )

    assert not (artifact_root / "memory_catalog" / "cutover_staging").exists()
    assert not (artifact_root / "memory").exists()
