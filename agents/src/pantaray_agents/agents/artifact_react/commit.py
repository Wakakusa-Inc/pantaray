from __future__ import annotations

from dataclasses import dataclass

from pantaray_agents.schema.agent.base import JSONValue


@dataclass(frozen=True)
class PatchCommitResult:
    committed_text: str
    storage_path: str
    sha256: str
    base_sha256: str

    def to_tool_output(self) -> JSONValue:
        return {
            "status": "success",
            "storage_path": self.storage_path,
            "sha256": self.sha256,
            "base_sha256": self.base_sha256,
        }
