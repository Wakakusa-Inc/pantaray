from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import pantaray_agents.local_runtime.memory_catalog.reconciler as reconciler_module
import pantaray_agents.local_runtime.memory_catalog.repair_execution as repair_execution_module
import pantaray_agents.local_runtime.memory_catalog.revision_inspection as revision_inspection_module
from pantaray_agents.local_runtime.memory_catalog.artifact_domain_publication import (
    publish_fact_artifact,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.draft import create_memory_draft
from pantaray_agents.local_runtime.memory_catalog.errors import (
    MemoryCatalogIntegrityError,
)
from pantaray_agents.local_runtime.memory_catalog.lifecycle import (
    remove_abandoned_preparing_nodes,
)
from pantaray_agents.local_runtime.memory_catalog.models import (
    MemoryDocument,
    MemoryRevision,
)
from pantaray_agents.local_runtime.memory_catalog.reconciler import (
    reconcile_memory_catalog,
)
from pantaray_agents.local_runtime.memory_catalog.repair_queue import RepairJob
from pantaray_agents.local_runtime.memory_catalog.repository import (
    load_node_by_source,
)
from pantaray_agents.local_runtime.memory_catalog.resolver import (
    enqueue_memory_repair,
)
from pantaray_agents.local_runtime.runtime.memory_repair_scheduler import (
    run_memory_catalog_repair_once,
)
from pantaray_agents.local_runtime.storage.memory_update_lock import (
    MemoryUpdateLockLease,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import (
    immediate_transaction,
)

from .migrated_db import prepare_test_database
from .test_memory_artifact_publication import (
    _fact_draft,
    _publication,
)
from .test_memory_artifact_publication import (
    _runtime as _artifact_runtime,
)

BUSY_TIMEOUT_MS = 1_000


def _connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES ('user-1', 'ja', '2026-07-18T00:00:00Z', '2026-07-18T00:00:00Z')
        """
    )
    connection.commit()
    return connection


def _insert_preparing_memory_node(
    connection: sqlite3.Connection, *, node_id: str, source_type: str
) -> None:
    connection.execute(
        """
        INSERT INTO memory_nodes(
            node_id, user_id, source_type, source_record_id, lifecycle,
            integrity, current_revision_id, created_at, updated_at
        ) VALUES (?, 'user-1', ?, ?, 'preparing', 'healthy', NULL, ?, ?)
        """,
        (node_id, source_type, node_id, "2026-09-07T00:00:00Z", "2026-09-07T00:00:00Z"),
    )


def _insert_queued_memory_update_job(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, started_at, updated_at,
            heartbeat_at, next_event_seq
        ) VALUES ('memory-process', 'user-1', 'memory', 'enqueued', ?, ?, ?, 1)
        """,
        ("2026-09-07T00:00:00Z", "2026-09-07T00:00:00Z", "2026-09-07T00:00:00Z"),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, scheduled_at,
            logical_key
        ) VALUES ('memory-job', 'user-1', 'memory_update', 'memory-process',
                  'queued', ?, 'user-1')
        """,
        ("2026-09-07T00:00:00Z",),
    )


def test_startup_gc_keeps_the_nodes_a_requeued_memory_run_prepared(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    for source_type in ("fact", "long_term_insight", "agent_experience"):
        _insert_preparing_memory_node(
            connection, node_id=f"node-{source_type}", source_type=source_type
        )
    _insert_queued_memory_update_job(connection)
    connection.commit()

    assert remove_abandoned_preparing_nodes(connection=connection) == 0

    assert connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 3


def test_startup_gc_removes_memory_nodes_no_run_owns(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    for source_type in ("fact", "long_term_insight", "agent_experience"):
        _insert_preparing_memory_node(
            connection, node_id=f"node-{source_type}", source_type=source_type
        )
    connection.commit()

    assert remove_abandoned_preparing_nodes(connection=connection) == 3

    assert connection.execute("SELECT COUNT(*) FROM memory_nodes").fetchone()[0] == 0


def test_periodic_reconciler_cursor_eventually_scans_beyond_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from pantaray_agents.local_runtime.runtime import memory_repair_scheduler

    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        revisions = [
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id=f"cursor-log-{index}",
                content=f"cursor content {index}",
            )
            for index in range(3)
        ]
        connection.executemany(
            """
            UPDATE memory_revisions SET inline_body = inline_body || ' corrupt'
            WHERE user_id = 'user-1' AND revision_id = ?
            """,
            ((revision.revision_id,) for revision in revisions),
        )
        node_ids = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT node_id FROM memory_nodes
                WHERE user_id = 'user-1' ORDER BY node_id
                """
            ).fetchall()
        )
    connection.close()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    monkeypatch.setattr(
        memory_repair_scheduler,
        "MEMORY_REPAIR_PERIODIC_SCAN_LIMIT",
        2,
    )

    cursors: list[tuple[str | None, str | None]] = []
    for _ in range(2):
        run_memory_catalog_repair_once(
            db_path=tmp_path / "runtime.db",
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
        )
        with sqlite3.connect(tmp_path / "runtime.db") as verification:
            cursor = verification.execute(
                """
                SELECT last_user_id, last_node_id
                FROM memory_catalog_reconcile_state WHERE singleton_id = 1
                """
            ).fetchone()
        assert cursor is not None
        cursors.append((cursor[0], cursor[1]))

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        corrupt_count = verification.execute(
            "SELECT COUNT(*) FROM memory_nodes WHERE integrity = 'corrupt'"
        ).fetchone()[0]
    assert cursors == [("user-1", node_ids[1]), ("user-1", node_ids[2])]
    assert corrupt_count == 3


def test_failed_repair_jobs_do_not_starve_later_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        revisions = [
            register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id=f"retry-log-{index}",
                content=f"retry content {index}",
            )
            for index in range(3)
        ]
        nodes = [
            load_node_by_source(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id=f"retry-log-{index}",
            )
            for index in range(3)
        ]
        for node, revision in zip(nodes, revisions, strict=True):
            assert node is not None
            enqueue_memory_repair(
                connection=connection,
                user_id="user-1",
                node_id=node.node_id,
                detected_revision_id=revision.revision_id,
                reason="test_failure",
            )
    connection.close()
    attempted: list[str] = []

    def fail_repair(
        *,
        db_path: Path,
        busy_timeout_ms: int,
        artifact_root: Path,
        job: RepairJob,
    ) -> bool:
        _ = db_path, busy_timeout_ms, artifact_root
        attempted.append(job.node_id)
        raise MemoryCatalogIntegrityError("forced repair failure")

    monkeypatch.setattr(repair_execution_module, "repair_job", fail_repair)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    reconcile_memory_catalog(
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=2,
    )
    first_attempts = tuple(attempted)
    reconcile_memory_catalog(
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=2,
    )

    assert len(first_attempts) == 2
    assert len(attempted) == 3
    assert attempted[-1] not in first_attempts


def test_locked_user_repair_waits_without_blocking_other_users(tmp_path: Path) -> None:
    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        connection.execute(
            """
            INSERT INTO users(user_id, ui_language, created_at, updated_at)
            VALUES ('user-2', 'ja', '2026-07-18T00:00:00Z',
                    '2026-07-18T00:00:00Z')
            """
        )
        for user_id in ("user-1", "user-2"):
            revision = register_inline_domain_memory(
                connection=connection,
                user_id=user_id,
                source="activity_log",
                source_record_id=f"locked-repair-{user_id}",
                content=f"intact memory for {user_id}",
            )
            node = load_node_by_source(
                connection=connection,
                user_id=user_id,
                source="activity_log",
                source_record_id=f"locked-repair-{user_id}",
            )
            assert node is not None
            enqueue_memory_repair(
                connection=connection,
                user_id=user_id,
                node_id=node.node_id,
                detected_revision_id=revision.revision_id,
                reason="reference_resolution",
            )
    connection.close()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        initial_user_1 = verification.execute(
            """
            SELECT state, attempt_count, next_attempt_at, last_error_code
            FROM memory_repair_queue WHERE user_id = 'user-1'
            """
        ).fetchone()
    assert initial_user_1 is not None

    with MemoryUpdateLockLease(
        root_path=artifact_root,
        user_id="user-1",
        owner_id="test-writer",
    ):
        _, completed = reconcile_memory_catalog(
            db_path=tmp_path / "runtime.db",
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
            scan_limit=10,
        )

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        user_1_after_contention = verification.execute(
            """
            SELECT state, attempt_count, next_attempt_at, last_error_code
            FROM memory_repair_queue WHERE user_id = 'user-1'
            """
        ).fetchone()
        user_2_state = verification.execute(
            "SELECT state FROM memory_repair_queue WHERE user_id = 'user-2'"
        ).fetchone()

    assert completed == 1
    assert user_1_after_contention == initial_user_1
    assert user_2_state == ("completed",)

    _, completed = reconcile_memory_catalog(
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=10,
    )

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        user_1_state = verification.execute(
            """
            SELECT state, attempt_count, last_error_code
            FROM memory_repair_queue WHERE user_id = 'user-1'
            """
        ).fetchone()
    assert completed == 1
    assert user_1_state == ("completed", 0, None)


def test_clean_repair_inspection_does_not_publish_an_identical_revision(
    tmp_path: Path,
) -> None:
    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        revision = register_inline_domain_memory(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="clean-repair-log",
            content="intact memory",
        )
        node = load_node_by_source(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="clean-repair-log",
        )
        assert node is not None
        enqueue_memory_repair(
            connection=connection,
            user_id="user-1",
            node_id=node.node_id,
            detected_revision_id=revision.revision_id,
            reason="reference_resolution",
        )
    connection.close()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    _, completed = reconcile_memory_catalog(
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=10,
    )

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        revision_count = verification.execute(
            "SELECT COUNT(*) FROM memory_revisions WHERE node_id = ?",
            (node.node_id,),
        ).fetchone()[0]
        state = verification.execute(
            "SELECT state FROM memory_repair_queue WHERE reason = 'reference_resolution'"
        ).fetchone()[0]
    assert completed == 1
    assert revision_count == 1
    assert state == "completed"


def test_scan_os_error_does_not_enqueue_integrity_repair_or_advance_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        register_inline_domain_memory(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="unreadable-log",
            content="intact memory",
        )
    connection.close()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    def fail_inspection(**_kwargs: object) -> None:
        raise OSError("temporary read failure")

    monkeypatch.setattr(revision_inspection_module, "inspect_revision", fail_inspection)

    with pytest.raises(OSError, match="temporary read failure"):
        reconcile_memory_catalog(
            db_path=tmp_path / "runtime.db",
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
            scan_limit=10,
        )

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        repair_count = verification.execute(
            "SELECT COUNT(*) FROM memory_repair_queue"
        ).fetchone()[0]
        cursor = verification.execute(
            """
            SELECT last_user_id, last_node_id
            FROM memory_catalog_reconcile_state WHERE singleton_id = 1
            """
        ).fetchone()
    assert repair_count == 0
    assert cursor == (None, None)


def test_missing_artifact_enqueues_repair_and_scan_continues_with_batch(
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _artifact_runtime(tmp_path)
    artifact_revision = publish_fact_artifact(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        publication=_publication(_fact_draft(db_path)),
    )
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        with immediate_transaction(connection):
            inline_revision = register_inline_domain_memory(
                connection=connection,
                user_id="user-1",
                source="activity_log",
                source_record_id="same-batch-log",
                content="intact memory",
            )
            connection.execute(
                """
                UPDATE memory_revisions SET inline_body = inline_body || ' corrupt'
                WHERE user_id = 'user-1' AND revision_id = ?
                """,
                (inline_revision.revision_id,),
            )
        node_ids = tuple(
            str(row[0])
            for row in connection.execute(
                """
                SELECT node_id FROM memory_nodes
                WHERE user_id = 'user-1' ORDER BY node_id
                """
            ).fetchall()
        )

    artifact_path = (
        artifact_root / str(artifact_revision.artifact_root_path) / "facts/index.md"
    )
    artifact_path.unlink()

    enqueued, _ = reconcile_memory_catalog(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=10,
    )

    with sqlite3.connect(db_path) as verification:
        repairs = verification.execute(
            """
            SELECT node_id, reason FROM memory_repair_queue
            WHERE user_id = 'user-1' ORDER BY node_id
            """
        ).fetchall()
        cursor = verification.execute(
            """
            SELECT last_user_id, last_node_id
            FROM memory_catalog_reconcile_state WHERE singleton_id = 1
            """
        ).fetchone()

    assert enqueued == 2
    assert repairs == [(node_id, "revision_integrity") for node_id in node_ids]
    assert cursor == ("user-1", node_ids[-1])


def test_rollback_os_error_keeps_current_head_and_schedules_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = _connection(tmp_path)
    with immediate_transaction(connection):
        register_inline_domain_memory(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="rollback-log",
            content="older memory",
        )
        current_revision = register_inline_domain_memory(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="rollback-log",
            content="current memory",
        )
        node = load_node_by_source(
            connection=connection,
            user_id="user-1",
            source="activity_log",
            source_record_id="rollback-log",
        )
        assert node is not None
        enqueue_memory_repair(
            connection=connection,
            user_id="user-1",
            node_id=node.node_id,
            detected_revision_id=current_revision.revision_id,
            reason="revision_integrity",
        )
    connection.close()
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    monkeypatch.setattr(reconciler_module, "_scan_current_heads", lambda **_: 0)

    def fail_inspection(**_kwargs: object) -> None:
        raise OSError("temporary candidate read failure")

    monkeypatch.setattr(revision_inspection_module, "inspect_revision", fail_inspection)

    _, completed = reconcile_memory_catalog(
        db_path=tmp_path / "runtime.db",
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=10,
    )

    with sqlite3.connect(tmp_path / "runtime.db") as verification:
        current = verification.execute(
            """
            SELECT current_revision_id, integrity FROM memory_nodes
            WHERE user_id = 'user-1' AND node_id = ?
            """,
            (node.node_id,),
        ).fetchone()
        repair = verification.execute(
            """
            SELECT state, attempt_count, last_error_code
            FROM memory_repair_queue WHERE reason = 'revision_integrity'
            """
        ).fetchone()
    assert completed == 0
    assert current == (current_revision.revision_id, "healthy")
    assert repair == ("pending", 1, "OSError")


def test_rollback_skips_missing_history_artifact_and_uses_older_revision(
    tmp_path: Path,
) -> None:
    db_path, artifact_root = _artifact_runtime(tmp_path)
    oldest_revision = publish_fact_artifact(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        publication=_publication(_fact_draft(db_path)),
    )

    def publish_next_revision(*, content: str) -> MemoryRevision:
        with sqlite3.connect(db_path) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute(
                "UPDATE agent_fact_structuring_runs SET status = 'processing' "
                "WHERE fact_run_id = 'run-1'"
            )
            connection.execute("DELETE FROM fact_activity_consumptions")
            node = load_node_by_source(
                connection=connection,
                user_id="user-1",
                source="fact",
                source_record_id="fact-1",
            )
            assert node is not None
        draft = create_memory_draft(
            user_id="user-1",
            owner_node_id=oldest_revision.node_id,
            base_revision_id=node.current_revision_id,
            documents=(MemoryDocument("facts/index.md", content),),
        )
        return publish_fact_artifact(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            artifact_root=artifact_root,
            publication=_publication(draft),
        )

    missing_history_revision = publish_next_revision(
        content="# Facts\n- Missing history\n"
    )
    current_revision = publish_next_revision(content="# Facts\n- Broken current\n")
    with sqlite3.connect(db_path) as connection:
        connection.executemany(
            "UPDATE memory_revisions SET created_at = ? WHERE revision_id = ?",
            (
                ("2026-07-18T00:00:00Z", oldest_revision.revision_id),
                ("2026-07-18T00:01:00Z", missing_history_revision.revision_id),
                ("2026-07-18T00:02:00Z", current_revision.revision_id),
            ),
        )

    for revision in (missing_history_revision, current_revision):
        assert revision.artifact_root_path is not None
        (artifact_root / revision.artifact_root_path / "facts/index.md").unlink()

    enqueued, completed = reconcile_memory_catalog(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        artifact_root=artifact_root,
        scan_limit=10,
    )

    with sqlite3.connect(db_path) as connection:
        node_row = connection.execute(
            "SELECT current_revision_id, integrity FROM memory_nodes WHERE node_id = ?",
            (oldest_revision.node_id,),
        ).fetchone()
        fact_row = connection.execute(
            "SELECT structured_fact_sha256 FROM agent_facts WHERE fact_id = 'fact-1'"
        ).fetchone()
        repair_row = connection.execute(
            "SELECT state FROM memory_repair_queue WHERE node_id = ?",
            (oldest_revision.node_id,),
        ).fetchone()

    assert enqueued == 1
    assert completed == 1
    assert node_row == (oldest_revision.revision_id, "healthy")
    assert fact_row == (oldest_revision.content_sha256,)
    assert repair_row == ("completed",)
