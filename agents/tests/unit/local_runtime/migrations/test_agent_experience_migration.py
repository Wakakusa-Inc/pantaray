from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    verify_database_integrity,
)

from .support import (
    _configure_connection,
    _insert_user,
    _migrations_before,
    apply_migrations,
    load_default_migrations,
)

MIGRATION_NAME = "0072_agent_experience.sql"
BUSY_TIMEOUT_MS = 1_000


def test_agent_experience_migration_preserves_catalog_and_extends_runtime(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_user(connection, "user-1")
        _insert_action_and_job(connection)
        connection.execute(
            """
            INSERT INTO memory_nodes(
                user_id, node_id, source_type, source_record_id, lifecycle,
                integrity, current_revision_id, created_at, updated_at
            ) VALUES (
                'user-1', 'node-existing', 'fact', 'fact-existing',
                'preparing', 'healthy', NULL,
                '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO memory_revisions(
                user_id, revision_id, node_id, body_kind, inline_body,
                artifact_root_path, fragment_schema_version, content_sha256,
                profile_brief, created_at
            ) VALUES (
                'user-1', 'revision-existing', 'node-existing', 'inline',
                'preserved body', NULL, 1, ?, NULL,
                '2026-08-09T00:00:00Z'
            )
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            UPDATE memory_nodes
            SET lifecycle = 'active', current_revision_id = 'revision-existing'
            WHERE user_id = 'user-1' AND node_id = 'node-existing'
            """
        )
        connection.execute(
            """
            INSERT INTO memory_fragments(
                user_id, fragment_id, revision_id, source_path, block_kind,
                block_index, heading_path, content_text, content_sha256
            ) VALUES (
                'user-1', 'fragment-existing', 'revision-existing', 'body.md',
                'paragraph', 1, NULL, 'preserved body', ?
            )
            """,
            ("a" * 64,),
        )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )
    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        preserved = connection.execute(
            """
            SELECT nodes.source_type, nodes.current_revision_id,
                   revisions.inline_body, fragments.content_text
            FROM memory_nodes AS nodes
            JOIN memory_revisions AS revisions
              ON revisions.user_id = nodes.user_id
             AND revisions.revision_id = nodes.current_revision_id
            JOIN memory_fragments AS fragments
              ON fragments.user_id = revisions.user_id
             AND fragments.revision_id = revisions.revision_id
            WHERE nodes.node_id = 'node-existing'
              AND fragments.fragment_id = 'fragment-existing'
            """
        ).fetchone()
        process_children = connection.execute(
            """
            SELECT events.event_name, jobs.process_id
            FROM processes AS processes
            JOIN process_events AS events
              ON events.process_id = processes.process_id
            JOIN jobs AS jobs
              ON jobs.process_id = processes.process_id
            WHERE processes.process_id = 'process-existing'
            """
        ).fetchone()
        connection.execute(
            """
            INSERT INTO memory_nodes(
                user_id, node_id, source_type, source_record_id, lifecycle,
                integrity, current_revision_id, created_at, updated_at
                ) VALUES (
                    'user-1', 'node-experience', 'agent_experience', 'user-1',
                'preparing', 'healthy', NULL,
                '2026-08-09T00:01:00Z', '2026-08-09T00:01:00Z'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO processes(
                process_id, user_id, kind, status, started_at, updated_at,
                heartbeat_at, next_event_seq
            ) VALUES (
                'process-experience', 'user-1', 'agent_experience', 'enqueued',
                '2026-08-09T00:01:00Z', '2026-08-09T00:01:00Z',
                '2026-08-09T00:01:00Z', 1
            )
            """
        )
        connection.execute(
            """
                INSERT INTO agent_experience_extraction_runs(
                    user_id, job_id, action_id, operation,
                    experience_id, prompt_name, prompt_version, completed_at
                ) VALUES (
                    'user-1', 'job-1', 'action-1', 'no_change', NULL,
                    'agent_experience/extract', 'v1', '2026-08-09T00:02:00Z'
                )
                """
        )
        connection.execute(
            """
            INSERT INTO workspace_manifests(
                manifest_id, user_id, action_id, scratch_root_path,
                created_at, status
            ) VALUES (
                'manifest-experience', 'user-1', 'action-1', '/tmp/scratch',
                '2026-08-09T00:02:00Z', 'ready'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO workspace_manifest_roots(
                root_id, manifest_id, source_type, source_id, display_name,
                canonical_real_path, real_path, can_read, can_apply_patch,
                can_process_read, can_process_write, created_at
            ) VALUES (
                'root-experience', 'manifest-experience', 'agent_experience',
                'revision-experience', 'Agent Experience',
                '/tmp/artifacts/agent_experience',
                '/tmp/artifacts/agent_experience', 1, 0, 0, 0,
                '2026-08-09T00:02:00Z'
            )
            """
        )
        foreign_key_violations = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

    assert preserved == (
        "fact",
        "revision-existing",
        "preserved body",
        "preserved body",
    )
    assert process_children == ("preserved_event", "process-existing")
    assert foreign_key_violations == []


def test_agent_experience_migration_keeps_constraints_closed(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, BUSY_TIMEOUT_MS)
        _insert_user(connection, "user-1")
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO memory_nodes(
                    user_id, node_id, source_type, source_record_id, lifecycle,
                    integrity, current_revision_id, created_at, updated_at
                ) VALUES (
                    'user-1', 'node-invalid', 'unknown', 'invalid',
                    'preparing', 'healthy', NULL,
                    '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
                )
                """
            )


def _insert_action_and_job(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, created_at, updated_at
        ) VALUES (
            'suggestion-1', 'user-1', 'success',
            '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id, user_id, suggestion_id, status, final_output,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES (
            'action-1', 'user-1', 'suggestion-1', 'success', 'done',
            'action/test', 'v1',
            '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z'
        )
        """
    )
    connection.execute(
        """
        UPDATE agent_suggestions
        SET action_execution_id = 'action-1',
            action_command_id = 'message-action-1'
        WHERE suggestion_id = 'suggestion-1'
        """
    )
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status,
            started_at, updated_at, heartbeat_at, next_event_seq
        ) VALUES (
            'process-existing', 'user-1', 'fact', 'completed',
            '2026-08-09T00:00:00Z', '2026-08-09T00:00:00Z',
            '2026-08-09T00:00:00Z', 2
        )
        """
    )
    connection.execute(
        """
        INSERT INTO process_events(
            process_id, event_seq, event_id, event_name, payload_json,
            created_at
        ) VALUES (
            'process-existing', 1, 'event-existing', 'preserved_event', '{}',
            '2026-08-09T00:00:00Z'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, scheduled_at
        ) VALUES (
            'job-1', 'user-1', 'structure_facts',
            'process-existing', 'completed',
            '2026-08-09T00:01:00Z'
        )
        """
    )
