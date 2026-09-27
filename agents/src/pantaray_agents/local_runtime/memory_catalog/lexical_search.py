from __future__ import annotations

import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import zip_longest

from .fragment_visibility import (
    MEMORY_FRAGMENT_COLUMNS,
    VISIBLE_FRAGMENT_JOINS,
    visible_fragment_predicate,
)
from .models import MemorySource

_QUERY_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
# memory_fragments_fts is tokenized with trigram, so a MATCH term is a substring
# of three characters or more and nothing shorter resolves through the index.
TRIGRAM_LENGTH = 3
# One OR-ed window costs about 0.8 ms on a 24k-fragment store holding 15 MB of
# text (sqlite 3.50, measured: 16 windows 20 ms, 48 windows 38 ms, 128 windows
# 138 ms), so this holds the index lane under ~40 ms there. It covers a query of
# 50 characters whole; a longer one is a paragraph rather than a recall phrase,
# and its words are still searched verbatim, so the cap bounds only how much
# partial recall a single query buys.
MAX_QUERY_TRIGRAM_WINDOWS = 48


def search_lexical_fragments(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    query: str,
    sources: tuple[MemorySource, ...],
    pinned_revisions: Mapping[MemorySource, str | None] | None,
    candidate_limit: int,
) -> tuple[sqlite3.Row, ...]:
    terms = _lexical_terms(query)
    visibility, visibility_parameters = visible_fragment_predicate(
        user_id=user_id,
        sources=sources,
        pinned_revisions=pinned_revisions,
    )
    return _interleave_rows(
        _indexed_lexical_rows(
            connection=connection,
            terms=terms.indexed,
            visibility=visibility,
            visibility_parameters=visibility_parameters,
            candidate_limit=candidate_limit,
        ),
        _scanned_lexical_rows(
            connection=connection,
            terms=terms.scanned,
            visibility=visibility,
            visibility_parameters=visibility_parameters,
            candidate_limit=candidate_limit,
        ),
        limit=candidate_limit,
    )


@dataclass(frozen=True, slots=True)
class _LexicalTerms:
    indexed: tuple[str, ...]
    scanned: tuple[str, ...]


def _lexical_terms(query: str) -> _LexicalTerms:
    """Sort the query's words into the matcher each one can reach.

    The index resolves a substring of three characters or more, so a word that
    long is matched through it. Japanese is written without spaces, so such a
    word is often a whole clause that no fragment holds verbatim; a word holding
    a non-ASCII character is therefore also expanded into its three-character
    windows, and bm25 orders a fragment by how many of them it holds.

    Below three characters the index is blind, and a full scan is worth its cost
    only where words are written that short: 申請 and 見積 are words, whereas
    ASCII "ai" or "db" is a piece of mail, detail and training. Those, and a
    single character of any script, which matches nearly every fragment, reach
    neither matcher.
    """
    indexed: list[str] = []
    windows: list[str] = []
    scanned: list[str] = []
    for word in dict.fromkeys(_QUERY_TOKEN_RE.findall(query.casefold())):
        if len(word) >= TRIGRAM_LENGTH:
            indexed.append(word)
            if not word.isascii():
                windows.extend(
                    word[start : start + TRIGRAM_LENGTH]
                    for start in range(len(word) - TRIGRAM_LENGTH + 1)
                )
        elif len(word) > 1 and not word.isascii():
            scanned.append(word)
    return _LexicalTerms(
        indexed=tuple(dict.fromkeys((*indexed, *windows[:MAX_QUERY_TRIGRAM_WINDOWS]))),
        scanned=tuple(scanned),
    )


def _indexed_lexical_rows(
    *,
    connection: sqlite3.Connection,
    terms: tuple[str, ...],
    visibility: str,
    visibility_parameters: tuple[object, ...],
    candidate_limit: int,
) -> tuple[sqlite3.Row, ...]:
    if not terms:
        return ()
    # _QUERY_TOKEN_RE keeps word characters only, so a term holds no FTS5
    # operator and quoting it is enough to keep it a literal phrase.
    return tuple(
        connection.execute(
            f"""
            SELECT {MEMORY_FRAGMENT_COLUMNS},
                   bm25(memory_fragments_fts) AS relevance
            FROM memory_fragments_fts
            JOIN memory_fragments AS fragments
              ON fragments.rowid = memory_fragments_fts.rowid
            {VISIBLE_FRAGMENT_JOINS}
            WHERE memory_fragments_fts MATCH ?
              AND {visibility}
            ORDER BY relevance, nodes.updated_at DESC, fragments.fragment_id
            LIMIT ?
            """,
            (
                " OR ".join(f'"{term}"' for term in terms),
                *visibility_parameters,
                candidate_limit,
            ),
        ).fetchall()
    )


def _scanned_lexical_rows(
    *,
    connection: sqlite3.Connection,
    terms: tuple[str, ...],
    visibility: str,
    visibility_parameters: tuple[object, ...],
    candidate_limit: int,
) -> tuple[sqlite3.Row, ...]:
    """Match the words the trigram index is too coarse to resolve.

    Design limit: this reads the content of every fragment the owner can see
    (~14 ms over 24k fragments holding 15 MB of text). Give two-character words
    an index of their own once that scan exceeds 100 ms.
    """
    if not terms:
        return ()
    # _QUERY_TOKEN_RE keeps word characters only, so a term carries no LIKE
    # wildcard.
    term_predicate = " OR ".join(
        "fragments.content_text LIKE '%' || ? || '%'" for _ in terms
    )
    return tuple(
        connection.execute(
            f"""
            SELECT {MEMORY_FRAGMENT_COLUMNS}
            FROM memory_fragments AS fragments
            {VISIBLE_FRAGMENT_JOINS}
            WHERE ({term_predicate})
              AND {visibility}
            ORDER BY nodes.updated_at DESC, fragments.fragment_id
            LIMIT ?
            """,
            (*terms, *visibility_parameters, candidate_limit),
        ).fetchall()
    )


def _interleave_rows(
    indexed: tuple[sqlite3.Row, ...],
    scanned: tuple[sqlite3.Row, ...],
    *,
    limit: int,
) -> tuple[sqlite3.Row, ...]:
    """Leave both matchers a share of the candidate pool."""
    merged: dict[str, sqlite3.Row] = {}
    for pair in zip_longest(indexed, scanned):
        for row in pair:
            if row is not None:
                merged.setdefault(str(row["fragment_id"]), row)
    return tuple(merged.values())[:limit]
