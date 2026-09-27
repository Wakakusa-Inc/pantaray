from __future__ import annotations

from dataclasses import dataclass

from pantaray_llm.contracts.json_value import JSONValue


# Not frozen: re-raising through a context manager assigns ``__traceback__``.
@dataclass(eq=False)
class ProviderError(Exception):
    """A provider-boundary failure with the proxy error contract's code and HTTP status."""

    status_code: int
    code: str
    message: str
    details: dict[str, JSONValue] | None = None


__all__ = ["ProviderError"]
