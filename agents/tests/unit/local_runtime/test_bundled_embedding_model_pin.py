"""The pin the desktop build stages must hold a manifest the runtime accepts.

`frontend/electron/embedding_model_release.json` carries the manifest verbatim,
and the build writes it beside the model files. The runtime recomputes
`artifact_revision` from every other field and refuses a manifest that disagrees
with it, so a pin edited by hand -- a bumped revision, an adjusted prefix or
token window -- would ship a release whose semantic memory search is silently
unavailable. The digest lives on this side, so the check does too.
"""

from __future__ import annotations

import json
from pathlib import Path

from pantaray_agents.local_runtime.embedding_local import (
    LocalEmbeddingManifest,
    artifact_revision_digest,
)

BUNDLED_MODEL_PIN_PATH = (
    Path(__file__).resolve().parents[4]
    / "frontend/electron/embedding_model_release.json"
)


def test_bundled_model_pin_carries_a_manifest_the_runtime_accepts() -> None:
    pin = json.loads(BUNDLED_MODEL_PIN_PATH.read_text("utf-8"))

    manifest = LocalEmbeddingManifest.model_validate(pin["manifest"])

    assert manifest.artifact_revision == artifact_revision_digest(
        **manifest.model_dump(exclude={"artifact_revision"})
    )
