from __future__ import annotations

import importlib
import math
import sqlite3
import struct
from collections.abc import Sequence
from typing import Protocol, cast


class _SQLiteVectorModule(Protocol):
    def load(self, connection: sqlite3.Connection) -> None: ...


sqlite_vec = cast(_SQLiteVectorModule, importlib.import_module("sqlite_vec"))

SQLITE_VECTOR_EXPECTED_VERSION = "v0.1.9"


class SQLiteVectorExtensionError(RuntimeError):
    """Raised when the required sqlite-vec extension cannot be loaded."""


class SQLiteVectorValueError(ValueError):
    """Raised when a vector cannot be represented as a finite float32 blob."""


def load_sqlite_vector_extension(connection: sqlite3.Connection) -> None:
    extension_loading_enabled = False
    try:
        connection.enable_load_extension(True)
        extension_loading_enabled = True
        sqlite_vec.load(connection)
        version = connection.execute("SELECT vec_version()").fetchone()
    except (AttributeError, RuntimeError, sqlite3.Error) as exc:
        raise SQLiteVectorExtensionError(
            "the required sqlite-vec extension could not be loaded"
        ) from exc
    finally:
        if extension_loading_enabled:
            try:
                connection.enable_load_extension(False)
            except (AttributeError, RuntimeError, sqlite3.Error) as exc:
                raise SQLiteVectorExtensionError(
                    "sqlite-vec extension loading could not be disabled"
                ) from exc
    if version is None or version[0] != SQLITE_VECTOR_EXPECTED_VERSION:
        raise SQLiteVectorExtensionError(
            "sqlite-vec version mismatch: "
            f"expected {SQLITE_VECTOR_EXPECTED_VERSION}, got "
            f"{version[0] if version is not None else 'no version'}"
        )


def encode_float32_vector(vector: Sequence[float], *, dimensions: int) -> bytes:
    values = _validate_vector(vector, dimensions=dimensions)
    try:
        encoded = struct.pack(f"<{dimensions}f", *values)
    except (OverflowError, struct.error) as exc:
        raise SQLiteVectorValueError("vector cannot be represented as float32") from exc
    decode_float32_vector(encoded, dimensions=dimensions)
    return encoded


def decode_float32_vector(blob: bytes, *, dimensions: int) -> tuple[float, ...]:
    expected_bytes = dimensions * 4
    if not isinstance(blob, bytes) or len(blob) != expected_bytes:
        raise SQLiteVectorValueError(f"vector must be {expected_bytes} bytes")
    try:
        values = struct.unpack(f"<{dimensions}f", blob)
    except struct.error as exc:
        raise SQLiteVectorValueError("vector blob is invalid") from exc
    return _validate_vector(values, dimensions=dimensions)


def _validate_vector(vector: Sequence[float], *, dimensions: int) -> tuple[float, ...]:
    if isinstance(dimensions, bool) or dimensions <= 0 or len(vector) != dimensions:
        raise SQLiteVectorValueError(f"vector must contain {dimensions} values")
    values: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SQLiteVectorValueError("vector must contain only numbers")
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            raise SQLiteVectorValueError("vector must contain only finite values")
        values.append(numeric_value)
    if not any(value != 0.0 for value in values):
        raise SQLiteVectorValueError("vector must not be zero")
    return tuple(values)


__all__ = [
    "SQLITE_VECTOR_EXPECTED_VERSION",
    "SQLiteVectorExtensionError",
    "SQLiteVectorValueError",
    "decode_float32_vector",
    "encode_float32_vector",
    "load_sqlite_vector_extension",
]
