from __future__ import annotations

from dataclasses import dataclass

from pantaray_agents.local_runtime.artifacts import ArtifactKind


@dataclass(frozen=True, slots=True)
class ArtifactDocumentTarget:
    logical_path: str
    kind: ArtifactKind
    template: str
    read_error_message: str
    conflict_error_message: str
    empty_user_error_message: str = "user_id is empty"

    def require_user_id(self, user_id: str) -> None:
        if not user_id:
            raise ValueError(self.empty_user_error_message)
