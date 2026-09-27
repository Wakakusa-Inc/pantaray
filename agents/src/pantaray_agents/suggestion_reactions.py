from __future__ import annotations

from typing import Final, Literal, cast

SuggestionUserReaction = Literal["accepted", "rejected"]

SUGGESTION_USER_REACTION_ACCEPTED: Final[Literal["accepted"]] = "accepted"
SUGGESTION_USER_REACTION_REJECTED: Final[Literal["rejected"]] = "rejected"
SUGGESTION_USER_REACTIONS: Final[frozenset[SuggestionUserReaction]] = frozenset(
    {
        SUGGESTION_USER_REACTION_ACCEPTED,
        SUGGESTION_USER_REACTION_REJECTED,
    }
)


def parse_stored_suggestion_user_reaction(
    value: object,
) -> SuggestionUserReaction | None:
    """Parse DB/projection reaction values for read paths.

    Stored reactions are product vocabulary, not structural state-machine values.
    Read paths must tolerate stale or future values so UI rendering does not crash.
    """

    if value is None:
        return None
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized in SUGGESTION_USER_REACTIONS:
        return cast(SuggestionUserReaction, normalized)
    return None


def require_stored_suggestion_user_reaction(value: object) -> SuggestionUserReaction:
    """Validate stored reaction values at strict write/command boundaries."""

    reaction = parse_stored_suggestion_user_reaction(value)
    if reaction is None:
        raise ValueError(f"Unsupported suggestion user reaction: {value!r}")
    return reaction


def normalize_public_suggestion_reaction_for_write(
    value: object,
) -> SuggestionUserReaction:
    """Normalize UI/API suggestion reactions to the current stored vocabulary."""

    if value is None:
        raise ValueError("Unsupported suggestion user reaction: None")
    normalized = str(value).strip().lower()
    if normalized == "dismiss":
        return SUGGESTION_USER_REACTION_REJECTED
    return require_stored_suggestion_user_reaction(normalized)


__all__ = [
    "SUGGESTION_USER_REACTION_ACCEPTED",
    "SUGGESTION_USER_REACTION_REJECTED",
    "SUGGESTION_USER_REACTIONS",
    "SuggestionUserReaction",
    "normalize_public_suggestion_reaction_for_write",
    "parse_stored_suggestion_user_reaction",
    "require_stored_suggestion_user_reaction",
]
