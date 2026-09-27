from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from pantaray_agents.schema.memory_embeddings import (
    MEMORY_EMBEDDING_MAX_TEXT_CHARS,
    MemoryEmbeddingProfileId,
    resolve_memory_embedding_profile,
)

from .specs import MigrationError


# Local imports avoid the storage.migrations -> memory_catalog package cycle while
# still reusing the runtime's canonical dynamic-storage DDL.
def create_embedding_generation_storage(
    connection: sqlite3.Connection, *, generation_id: int, dimensions: int
) -> None:
    from pantaray_agents.local_runtime.memory_catalog.embedding_generation_storage import (
        create_embedding_generation_storage as create_storage,
    )

    create_storage(
        connection,
        generation_id=generation_id,
        dimensions=dimensions,
    )


def drop_embedding_generation_storage(
    connection: sqlite3.Connection, *, generation_id: int
) -> None:
    from pantaray_agents.local_runtime.memory_catalog.embedding_generation_storage import (
        drop_embedding_generation_storage as drop_storage,
    )

    drop_storage(connection, generation_id=generation_id)


def generation_entry_table(generation_id: int) -> str:
    return f"memory_embedding_entries_g{_require_generation_id(generation_id)}"


def generation_vector_table(generation_id: int) -> str:
    return f"memory_embedding_vectors_g{_require_generation_id(generation_id)}"


def _require_generation_id(generation_id: int) -> int:
    if (
        isinstance(generation_id, bool)
        or not isinstance(generation_id, int)
        or generation_id <= 0
    ):
        raise MigrationError("v84 generation_id must be positive")
    return generation_id


@dataclass(frozen=True)
class _GenerationIdentity:
    profile_id: MemoryEmbeddingProfileId
    model_id: str
    dimensions: int
    normalized: int
    distance_metric: str
    max_text_chars: int

    def current_chunking(self) -> _GenerationIdentity:
        return _GenerationIdentity(
            profile_id=self.profile_id,
            model_id=self.model_id,
            dimensions=self.dimensions,
            normalized=self.normalized,
            distance_metric=self.distance_metric,
            max_text_chars=MEMORY_EMBEDDING_MAX_TEXT_CHARS,
        )


@dataclass(frozen=True)
class _Generation:
    generation_id: int
    identity: _GenerationIdentity


@dataclass(frozen=True)
class _UserScopes:
    user_id: str
    active: _Generation | None
    building: _Generation | None


def apply_embedding_chunk_generation_rebase_migration(
    connection: sqlite3.Connection,
) -> None:
    connection.row_factory = sqlite3.Row
    generations = _load_and_validate_generations(connection)
    scopes = _load_and_validate_user_scopes(connection, generations)
    targets = tuple(scope for scope in scopes if _requires_rebase(scope))
    if not targets:
        _require_postconditions(connection)
        return
    timestamp = str(
        connection.execute("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now')").fetchone()[0]
    )
    generation_by_identity = {item.identity: item for item in generations}
    for scope in targets:
        source = scope.building or scope.active
        if source is None:
            raise AssertionError("rebase target must have a source generation")
        target_identity = source.identity.current_chunking()
        if scope.active is not None and scope.active.identity == target_identity:
            if scope.building is None:
                raise AssertionError(
                    "current active generation cannot require rebasing"
                )
            _delete_building_scope(
                connection,
                user_id=scope.user_id,
                generation_id=scope.building.generation_id,
            )
            continue
        target = generation_by_identity.get(target_identity)
        if target is None:
            target = _create_generation(
                connection,
                identity=target_identity,
                timestamp=timestamp,
            )
            generation_by_identity[target.identity] = target
        _replace_user_build(
            connection,
            scope=scope,
            target=target,
            timestamp=timestamp,
        )
    _drop_unused_generations(connection)
    _require_postconditions(connection)


def _requires_rebase(scope: _UserScopes) -> bool:
    if scope.building is not None:
        return scope.building.identity.max_text_chars != MEMORY_EMBEDDING_MAX_TEXT_CHARS
    return (
        scope.active is not None
        and scope.active.identity.max_text_chars != MEMORY_EMBEDDING_MAX_TEXT_CHARS
    )


def _load_and_validate_generations(
    connection: sqlite3.Connection,
) -> tuple[_Generation, ...]:
    rows = connection.execute(
        """
        SELECT generation_id, profile_id, model_id, dimensions, normalized,
               distance_metric, max_text_chars
        FROM memory_embedding_generations
        ORDER BY generation_id
        """
    ).fetchall()
    generations: list[_Generation] = []
    for row in rows:
        generation = _Generation(
            generation_id=_require_generation_id(_db_int(row["generation_id"])),
            identity=_GenerationIdentity(
                profile_id=cast(MemoryEmbeddingProfileId, str(row["profile_id"])),
                model_id=str(row["model_id"]),
                dimensions=_db_int(row["dimensions"]),
                normalized=_db_flag(row["normalized"]),
                distance_metric=str(row["distance_metric"]),
                max_text_chars=_db_int(row["max_text_chars"]),
            ),
        )
        _require_profile_identity(generation)
        _require_generation_storage(connection, generation)
        generations.append(generation)
    return tuple(generations)


def _require_profile_identity(generation: _Generation) -> None:
    try:
        profile = resolve_memory_embedding_profile(generation.identity.profile_id)
    except (KeyError, ValueError) as exc:
        raise MigrationError(
            "v84 embedding generation has an unknown profile: "
            f"generation_id={generation.generation_id}"
        ) from exc
    actual = (
        generation.identity.model_id,
        generation.identity.dimensions,
        bool(generation.identity.normalized),
        generation.identity.distance_metric,
    )
    expected = (
        profile.model_id,
        profile.dimensions,
        profile.normalized,
        "cosine",
    )
    if actual != expected:
        raise MigrationError(
            "v84 embedding generation profile mismatch: "
            f"generation_id={generation.generation_id}"
        )


def _require_generation_storage(
    connection: sqlite3.Connection, generation: _Generation
) -> None:
    entries = generation_entry_table(generation.generation_id)
    vectors = generation_vector_table(generation.generation_id)
    entry_sql = _schema_sql(connection, object_type="table", name=entries)
    vector_sql = _schema_sql(connection, object_type="table", name=vectors)
    trigger_sql = _schema_sql(
        connection,
        object_type="trigger",
        name=f"{entries}_ad",
    )
    if (
        entry_sql is None
        or f"generation_id = {generation.generation_id}" not in entry_sql
        or vector_sql is None
        or f"FLOAT[{generation.identity.dimensions}]" not in vector_sql
        or trigger_sql is None
    ):
        raise MigrationError(
            "v84 embedding generation storage mismatch: "
            f"generation_id={generation.generation_id}"
        )


def _schema_sql(
    connection: sqlite3.Connection, *, object_type: str, name: str
) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
        (object_type, name),
    ).fetchone()
    return None if row is None or row["sql"] is None else str(row["sql"])


def _load_and_validate_user_scopes(
    connection: sqlite3.Connection,
    generations: tuple[_Generation, ...],
) -> tuple[_UserScopes, ...]:
    generation_by_id = {item.generation_id: item for item in generations}
    rows = connection.execute(
        """
        SELECT user_id, generation_id, state
        FROM memory_embedding_user_generations
        ORDER BY user_id, state, generation_id
        """
    ).fetchall()
    scopes_by_user: dict[str, dict[str, _Generation]] = {}
    for row in rows:
        user_id = _required_text(row["user_id"], field_name="user_id")
        state = str(row["state"])
        generation_id = _db_int(row["generation_id"])
        generation = generation_by_id.get(generation_id)
        if generation is None:
            raise MigrationError(
                "v84 embedding scope references a missing generation: "
                f"user_id={user_id} generation_id={generation_id}"
            )
        user_scopes = scopes_by_user.setdefault(user_id, {})
        if state not in {"active", "building"} or state in user_scopes:
            raise MigrationError(
                "v84 embedding scope state is ambiguous: "
                f"user_id={user_id} state={state}"
            )
        user_scopes[state] = generation
    return tuple(
        _UserScopes(
            user_id=user_id,
            active=states.get("active"),
            building=states.get("building"),
        )
        for user_id, states in scopes_by_user.items()
    )


def _create_generation(
    connection: sqlite3.Connection,
    *,
    identity: _GenerationIdentity,
    timestamp: str,
) -> _Generation:
    generation_id = int(
        connection.execute(
            "SELECT COALESCE(MAX(generation_id), 0) + 1 "
            "FROM memory_embedding_generations"
        ).fetchone()[0]
    )
    connection.execute(
        """
        INSERT INTO memory_embedding_generations(
            generation_id, profile_id, model_id, dimensions, normalized,
            distance_metric, max_text_chars, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generation_id,
            identity.profile_id,
            identity.model_id,
            identity.dimensions,
            identity.normalized,
            identity.distance_metric,
            identity.max_text_chars,
            timestamp,
        ),
    )
    create_embedding_generation_storage(
        connection,
        generation_id=generation_id,
        dimensions=identity.dimensions,
    )
    return _Generation(generation_id=generation_id, identity=identity)


def _replace_user_build(
    connection: sqlite3.Connection,
    *,
    scope: _UserScopes,
    target: _Generation,
    timestamp: str,
) -> None:
    if scope.building is not None:
        _delete_building_scope(
            connection,
            user_id=scope.user_id,
            generation_id=scope.building.generation_id,
        )
    connection.execute(
        """
        INSERT INTO memory_embedding_user_generations(
            user_id, generation_id, state, created_at, updated_at, activated_at
        ) VALUES (?, ?, 'building', ?, ?, NULL)
        """,
        (scope.user_id, target.generation_id, timestamp, timestamp),
    )
    entries = generation_entry_table(target.generation_id)
    connection.execute(f"DELETE FROM {entries} WHERE user_id = ?", (scope.user_id,))
    connection.execute(
        """
        DELETE FROM memory_embedding_work
        WHERE user_id = ? AND generation_id = ?
        """,
        (scope.user_id, target.generation_id),
    )
    connection.execute(
        """
        WITH RECURSIVE fragment_chunks(
            user_id, fragment_id, chunk_index, content_length
        ) AS (
            SELECT user_id, fragment_id, 0, length(content_text)
            FROM memory_fragments
            WHERE user_id = ?
              AND block_kind NOT IN ('record_root', 'document_root')
              AND length(content_text) > 0
            UNION ALL
            SELECT user_id, fragment_id, chunk_index + 1, content_length
            FROM fragment_chunks
            WHERE (chunk_index + 1) * ? < content_length
        )
        INSERT INTO memory_embedding_work(
            user_id, generation_id, fragment_id, chunk_index, state,
            attempt_count, next_attempt_at, last_error_code, created_at, updated_at
        )
        SELECT user_id, ?, fragment_id, chunk_index, 'pending',
               0, NULL, NULL, ?, ?
        FROM fragment_chunks
        """,
        (
            scope.user_id,
            target.identity.max_text_chars,
            target.generation_id,
            timestamp,
            timestamp,
        ),
    )


def _delete_building_scope(
    connection: sqlite3.Connection, *, user_id: str, generation_id: int
) -> None:
    deleted = connection.execute(
        """
        DELETE FROM memory_embedding_user_generations
        WHERE user_id = ? AND generation_id = ? AND state = 'building'
        """,
        (user_id, generation_id),
    ).rowcount
    if deleted != 1:
        raise MigrationError(
            "v84 embedding building scope disappeared during rebase: "
            f"user_id={user_id} generation_id={generation_id}"
        )


def _drop_unused_generations(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT generations.generation_id
        FROM memory_embedding_generations AS generations
        LEFT JOIN memory_embedding_user_generations AS scopes
          ON scopes.generation_id = generations.generation_id
        WHERE scopes.generation_id IS NULL
        ORDER BY generations.generation_id
        """
    ).fetchall()
    for row in rows:
        generation_id = _require_generation_id(_db_int(row["generation_id"]))
        drop_embedding_generation_storage(connection, generation_id=generation_id)
        connection.execute(
            "DELETE FROM memory_embedding_generations WHERE generation_id = ?",
            (generation_id,),
        )


def _require_postconditions(connection: sqlite3.Connection) -> None:
    wrong_building = connection.execute(
        """
        SELECT scopes.user_id
        FROM memory_embedding_user_generations AS scopes
        JOIN memory_embedding_generations AS generations
          ON generations.generation_id = scopes.generation_id
        WHERE scopes.state = 'building' AND generations.max_text_chars != ?
        ORDER BY scopes.user_id
        LIMIT 1
        """,
        (MEMORY_EMBEDDING_MAX_TEXT_CHARS,),
    ).fetchone()
    if wrong_building is not None:
        raise MigrationError(
            "v84 postcondition failed: wrong building generation remains for "
            f"user_id={wrong_building['user_id']}"
        )
    wrong_active_without_building = connection.execute(
        """
        SELECT active.user_id
        FROM memory_embedding_user_generations AS active
        JOIN memory_embedding_generations AS generations
          ON generations.generation_id = active.generation_id
        WHERE active.state = 'active'
          AND generations.max_text_chars != ?
          AND NOT EXISTS (
              SELECT 1
              FROM memory_embedding_user_generations AS building
              JOIN memory_embedding_generations AS target
                ON target.generation_id = building.generation_id
              WHERE building.user_id = active.user_id
                AND building.state = 'building'
                AND target.max_text_chars = ?
          )
        ORDER BY active.user_id
        LIMIT 1
        """,
        (MEMORY_EMBEDDING_MAX_TEXT_CHARS, MEMORY_EMBEDDING_MAX_TEXT_CHARS),
    ).fetchone()
    if wrong_active_without_building is not None:
        raise MigrationError(
            "v84 postcondition failed: wrong active generation has no current build for "
            f"user_id={wrong_active_without_building['user_id']}"
        )


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"v84 {field_name} must be a non-empty string")
    return value.strip()


def _db_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MigrationError("v84 embedding integer column is invalid")
    return value


def _db_flag(value: object) -> int:
    parsed = _db_int(value)
    if parsed not in (0, 1):
        raise MigrationError("v84 embedding boolean column is invalid")
    return parsed


__all__ = ["apply_embedding_chunk_generation_rebase_migration"]
