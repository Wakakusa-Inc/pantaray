from __future__ import annotations


def _extract_error_code(message: str) -> str | None:
    prefix = message.split(":", 1)[0].strip()
    if not prefix.startswith("PATCH_"):
        return None
    if prefix != prefix.upper():
        return None
    if not all(character.isalnum() or character == "_" for character in prefix):
        return None
    return prefix


class PatchDslError(ValueError):
    """Base error for the deterministic patch DSL."""

    default_code = "PATCH_DSL_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or _extract_error_code(message) or self.default_code


class PatchDslParseError(PatchDslError):
    """The patch text is not valid patch DSL."""

    default_code = "PATCH_DSL_PARSE_ERROR"


class PatchDslPathError(PatchDslError):
    """The patch targets a disallowed or unsafe path."""

    default_code = "PATCH_DSL_PATH_ERROR"


class PatchContextNotFoundError(PatchDslError):
    """A chunk could not be matched against the current text."""

    default_code = "PATCH_CONTEXT_NOT_FOUND"


class PatchContextAmbiguousError(PatchDslError):
    """A chunk matched more than one location."""

    default_code = "PATCH_CONTEXT_AMBIGUOUS"
