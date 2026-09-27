from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import cast

from pantaray_agents.local_runtime.embedding_local import (
    LocalEmbeddingUnavailableError,
    load_local_embedding_model,
)
from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_db_config,
)

from .embedding_generations import (
    current_embedding_specification,
    start_embedding_reprojection,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Rebuild one user's semantic index with the installed embedding model."""
    args = _build_parser().parse_args(argv)
    user_id = cast(str, args.user_id)
    try:
        model = load_local_embedding_model()
    except LocalEmbeddingUnavailableError as exc:
        raise SystemExit(f"local embedding model is unavailable: {exc}") from exc
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    generation = start_embedding_reprojection(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        user_id=user_id,
        specification=current_embedding_specification(model.manifest),
    )
    print(
        json.dumps(
            {
                "generation_id": generation.generation_id,
                "profile_id": generation.specification.profile_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "pantaray_agents.local_runtime.memory_catalog.reproject_embeddings"
        )
    )
    parser.add_argument("--user-id", required=True)
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
