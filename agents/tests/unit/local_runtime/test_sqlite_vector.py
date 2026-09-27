from __future__ import annotations

import sqlite3

import pytest

from pantaray_agents.local_runtime.storage import sqlite_vector
from pantaray_agents.local_runtime.storage.sqlite_vector import (
    SQLITE_VECTOR_EXPECTED_VERSION,
    SQLiteVectorExtensionError,
    load_sqlite_vector_extension,
)


def test_sqlite_vector_loader_enables_expected_extension() -> None:
    with sqlite3.connect(":memory:") as connection:
        load_sqlite_vector_extension(connection)

        assert connection.execute("SELECT vec_version()").fetchone() == (
            SQLITE_VECTOR_EXPECTED_VERSION,
        )


def test_sqlite_vector_loader_wraps_runtime_load_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sqlite_vector.sqlite_vec,
        "load",
        lambda _connection: (_ for _ in ()).throw(RuntimeError("load failed")),
    )
    with sqlite3.connect(":memory:") as connection:
        with pytest.raises(SQLiteVectorExtensionError, match="could not be loaded"):
            load_sqlite_vector_extension(connection)
