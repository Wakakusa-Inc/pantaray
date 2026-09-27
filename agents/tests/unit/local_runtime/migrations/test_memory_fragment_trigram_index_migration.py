from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationSpec,
    _configure_connection,
    apply_migrations,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations as load_all_migrations,
)

from .support import _insert_user

TRIGRAM_MIGRATION_NAME = "0115_memory_fragment_trigram_index.sql"
USER_ID = "user-trigram"
TIMESTAMP = "2026-09-18T00:00:00Z"
BUSY_TIMEOUT_MS = 1_000


def test_trigram_migration_indexes_stored_fragments_and_keeps_them_in_sync(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_all_migrations()

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before_trigram(migrations),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection, USER_ID)
            _insert_fragment(
                connection,
                record_id="fact-stored",
                content="サクラクレパスの経費精算を申請した",
            )
        assert _match_count(connection, "サクラクレパス") == 0

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=BUSY_TIMEOUT_MS)
        assert _match_count(connection, "サクラクレパス") == 1
        assert _match_count(connection, "経費精算") == 1
        with connection:
            _insert_fragment(
                connection,
                record_id="fact-added",
                content="エンタープライズサーチの事前検証",
            )
        assert _match_count(connection, "事前検証") == 1
        with connection:
            connection.execute(
                "DELETE FROM memory_fragments WHERE user_id = ? AND fragment_id = ?",
                (USER_ID, _fragment_id("fact-added")),
            )
        assert _match_count(connection, "事前検証") == 0
        connection.execute(
            "INSERT INTO memory_fragments_fts(memory_fragments_fts)"
            " VALUES('integrity-check')"
        )


def _migrations_before_trigram(
    migrations: tuple[MigrationSpec, ...],
) -> tuple[MigrationSpec, ...]:
    names = tuple(migration.name for migration in migrations)
    return migrations[: names.index(TRIGRAM_MIGRATION_NAME)]


def _fragment_id(record_id: str) -> str:
    return f"fragment-{record_id}"


def _insert_fragment(
    connection: sqlite3.Connection,
    *,
    record_id: str,
    content: str,
) -> None:
    node_id = f"node-{record_id}"
    revision_id = f"revision-{record_id}"
    connection.execute(
        """
        INSERT INTO memory_nodes(
            user_id, node_id, source_type, source_record_id, lifecycle,
            integrity, current_revision_id, created_at, updated_at
        ) VALUES (?, ?, 'fact', ?, 'active', 'healthy', ?, ?, ?)
        """,
        (USER_ID, node_id, record_id, revision_id, TIMESTAMP, TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO memory_revisions(
            user_id, revision_id, node_id, body_kind, inline_body,
            fragment_schema_version, content_sha256, created_at
        ) VALUES (?, ?, ?, 'inline', ?, 1, ?, ?)
        """,
        (USER_ID, revision_id, node_id, content, f"sha-{record_id}", TIMESTAMP),
    )
    connection.execute(
        """
        INSERT INTO memory_fragments(
            user_id, fragment_id, revision_id, source_path, block_kind,
            block_index, heading_path, content_text, content_sha256
        ) VALUES (?, ?, ?, ?, 'paragraph', 0, NULL, ?, ?)
        """,
        (
            USER_ID,
            _fragment_id(record_id),
            revision_id,
            f"facts/{record_id}.md",
            content,
            f"sha-{record_id}",
        ),
    )


def _match_count(connection: sqlite3.Connection, term: str) -> int:
    row = connection.execute(
        "SELECT count(*) FROM memory_fragments_fts WHERE memory_fragments_fts MATCH ?",
        (f'"{term}"',),
    ).fetchone()
    assert row is not None
    return int(row[0])
