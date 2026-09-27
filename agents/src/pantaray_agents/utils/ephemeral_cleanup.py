"""Best-effort cleanup for non-authoritative filesystem trees."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("pantaray.ephemeral_cleanup")


def remove_ephemeral_tree(*, path: Path, operation: str) -> bool:
    """Remove a disposable tree and report whether cleanup succeeded."""
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        return True
    except OSError as exc:
        logger.exception(
            "ephemeral tree cleanup failed",
            extra={
                "cleanup_operation": operation,
                "error_class": exc.__class__.__name__,
            },
        )
        return False
    return True


__all__ = ["remove_ephemeral_tree"]
