"""RepositoryResult boundary helpers."""

from __future__ import annotations

from typing import overload

from pantaray_agents.schema.repositories.repository import RepositoryResult


@overload
def ensure_repository_result[RepoT](
    result_obj: RepositoryResult[RepoT],
    error_message: str,
    *,
    allow_empty: bool = False,
) -> RepoT: ...


@overload
def ensure_repository_result[RepoT](
    result_obj: RepositoryResult[RepoT],
    error_message: str,
    *,
    allow_empty: bool = True,
) -> RepoT | None: ...


def ensure_repository_result[RepoT](
    result_obj: RepositoryResult[RepoT],
    error_message: str,
    *,
    allow_empty: bool = False,
) -> RepoT | None:
    if result_obj.error:
        raise RuntimeError(f"{error_message}: {result_obj.error}")
    if result_obj.data is None:
        if allow_empty:
            return None
        raise RuntimeError(error_message)
    return result_obj.data
