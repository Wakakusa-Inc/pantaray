import sqlite3
from uuid import UUID, uuid4

import pytest

from pantaray_agents.local_runtime.context import store
from pantaray_agents.local_runtime.memory_catalog.connection import (
    open_memory_catalog_connection,
)
from pantaray_agents.local_runtime.memory_catalog.domain_registration import (
    register_inline_domain_memory,
)
from pantaray_agents.local_runtime.memory_catalog.erasure import (
    erase_user_memory_offline,
    resume_pending_user_erasures,
)
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.transactions import (
    SQLiteTransactionOwnershipError,
    immediate_transaction,
)
from pantaray_agents.schema.context_source import (
    SourceBinding,
    SourceReady,
    SourceStopped,
    SourceTransitionApplied,
    SuspendSource,
)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    migrations = load_default_migrations()
    apply_migrations(path, 1000, migrations[:-1])
    with open_memory_catalog_connection(db_path=path, busy_timeout_ms=1000) as conn:
        with immediate_transaction(conn):
            conn.executemany(
                "INSERT INTO users VALUES (?, 'ja', NULL, 'now', 'now')",
                [("alice",), ("bob",)],
            )
    apply_migrations(path, 1000, migrations)
    apply_migrations(path, 1000, migrations)
    with open_memory_catalog_connection(db_path=path, busy_timeout_ms=1000) as conn:
        yield path, conn


def binding(user="alice", **changes):
    return SourceBinding(
        user_id=user,
        epoch=UUID(int=1),
        policy_revision="policy",
        store_id="store",
        protocol_version=1,
    ).model_copy(update=changes)


def stopped():
    return SourceStopped(
        kind="stopped", epoch=UUID(int=1), policy_revision="policy", reason="disabled"
    )


def request():
    return SuspendSource(
        kind="suspend",
        request_id=UUID(int=2),
        expected_epoch=UUID(int=1),
        reason="disabled",
        policy_revision="policy",
    )


def populate_source(conn, user="alice"):
    with immediate_transaction(conn):
        store.compare_source(conn, user, None, stopped())
        store.save_source_receipt(
            conn,
            user,
            request(),
            SourceTransitionApplied(kind="applied", state=stopped()),
        )
        store.compare_cursor(conn, binding(user), None, "end")


def test_migration_reopen_and_readonly_missing_source(database):
    path, conn = database
    conn.execute("PRAGMA query_only = ON")
    assert store.get_source(conn, "alice") is None
    assert store.get_cursor(conn, binding()) is None
    assert store.get_source_receipt(conn, "alice", request()) is None
    conn.execute("PRAGMA query_only = OFF")
    populate_source(conn)
    with open_memory_catalog_connection(db_path=path, busy_timeout_ms=1000) as reopened:
        assert store.get_source(reopened, "alice") == stopped()
        assert store.get_cursor(reopened, binding()) == "end"
        assert store.get_source_receipt(reopened, "alice", request()).state == stopped()
        assert reopened.execute("PRAGMA foreign_key_check").fetchall() == []


def test_source_cas_receipt_replay_and_subject_boundary(database):
    _, conn = database
    result = SourceTransitionApplied(kind="applied", state=stopped())
    with pytest.raises(SQLiteTransactionOwnershipError):
        store.compare_source(conn, "alice", None, stopped())
    with immediate_transaction(conn):
        store.compare_source(conn, "alice", None, stopped())
        store.save_source_receipt(conn, "alice", request(), result)
        store.save_source_receipt(conn, "alice", request(), result)
        store.compare_source(conn, "bob", None, stopped())
        store.save_source_receipt(conn, "bob", request(), result)
    for expected in (None, stopped().model_copy(update={"reason": "shutdown"})):
        with pytest.raises(store.ContextStoreConflict), immediate_transaction(conn):
            store.compare_source(conn, "alice", expected, stopped())
    with pytest.raises(store.ContextStoreConflict):
        store.get_source_receipt(
            conn, "alice", request().model_copy(update={"reason": "shutdown"})
        )
    with pytest.raises(store.ContextStoreConflict), immediate_transaction(conn):
        store.save_source_receipt(
            conn,
            "alice",
            request(),
            result.model_copy(
                update={"state": stopped().model_copy(update={"epoch": uuid4()})}
            ),
        )
    with pytest.raises(store.ContextStoreIntegrityError), immediate_transaction(conn):
        store.compare_source(
            conn, "alice", stopped(), SourceReady(kind="ready", binding=binding("bob"))
        )
    with immediate_transaction(conn):
        store.compare_source(
            conn, "alice", stopped(), SourceReady(kind="ready", binding=binding())
        )
    assert store.get_source_receipt(conn, "alice", request()) == result
    with pytest.raises(sqlite3.IntegrityError), immediate_transaction(conn):
        store.compare_source(conn, "absent", None, stopped())


@pytest.mark.parametrize(
    "changes",
    [
        {"epoch": UUID(int=3)},
        {"policy_revision": "new"},
    ],
)
def test_a_renewed_permit_resumes_the_same_stream(database, changes):
    """A restart renews the epoch; the store, and so the cursor, stay put."""
    _, conn = database
    with immediate_transaction(conn):
        store.compare_cursor(conn, binding(), None, "end")
    assert store.get_cursor(conn, binding(**changes)) == "end"


@pytest.mark.parametrize(
    "changes",
    [
        {"store_id": "new"},
        {"user_id": "bob"},
    ],
)
def test_streams_are_keyed_by_store_and_user_with_cursor_cas(database, changes):
    _, conn = database
    alternate = binding(**changes)
    with immediate_transaction(conn):
        store.compare_cursor(conn, binding(), None, "start")
        store.compare_cursor(conn, alternate, None, "other")
    with pytest.raises(store.ContextStoreConflict), immediate_transaction(conn):
        store.compare_cursor(conn, binding(), "old", "end")
    with immediate_transaction(conn):
        store.compare_cursor(conn, binding(), "start", "end")
    assert store.get_cursor(conn, alternate) == "other"


def test_source_transition_failure_rolls_back_cursor_and_receipt(database):
    _, conn = database
    with pytest.raises(RuntimeError, match="injected"), immediate_transaction(conn):
        store.compare_source(conn, "alice", None, stopped())
        store.save_source_receipt(
            conn,
            "alice",
            request(),
            SourceTransitionApplied(kind="applied", state=stopped()),
        )
        store.compare_cursor(conn, binding(), None, "next")
        raise RuntimeError("injected")
    assert store.get_source(conn, "alice") is None
    assert store.get_source_receipt(conn, "alice", request()) is None
    assert store.get_cursor(conn, binding()) is None


@pytest.mark.parametrize("fail_first", [False, True])
def test_real_erasure_cascades_context_and_resumes_atomic_detach(
    database, tmp_path, fail_first
):
    path, conn = database
    populate_source(conn)
    populate_source(conn, "bob")
    with immediate_transaction(conn):
        for user in ("alice", "bob"):
            register_inline_domain_memory(
                connection=conn,
                user_id=user,
                source="activity_log",
                source_record_id="activity",
                content="derived meaning",
            )
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    if fail_first:
        conn.execute(
            "CREATE TRIGGER fail_erasure BEFORE DELETE ON users WHEN old.user_id='alice' BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected"):
            erase_user_memory_offline(
                db_path=path,
                busy_timeout_ms=1000,
                artifact_root=artifact_root,
                user_id="alice",
            )
        assert store.get_source(conn, "alice") == stopped()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM memory_revisions WHERE user_id='alice'"
            ).fetchone()[0]
            == 1
        )
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("DROP TRIGGER fail_erasure")
        assert (
            resume_pending_user_erasures(
                db_path=path, busy_timeout_ms=1000, artifact_root=artifact_root
            )
            == 1
        )
    else:
        assert erase_user_memory_offline(
            db_path=path,
            busy_timeout_ms=1000,
            artifact_root=artifact_root,
            user_id="alice",
        ).erased
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'context_%'"
    ).fetchall()
    assert len(tables) == 3
    for (table,) in tables:
        assert (
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id='alice'"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id='bob'"
            ).fetchone()[0]
            == 1
        )
    assert store.get_source(conn, "bob") == stopped()
    assert store.get_cursor(conn, binding("bob")) == "end"
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
