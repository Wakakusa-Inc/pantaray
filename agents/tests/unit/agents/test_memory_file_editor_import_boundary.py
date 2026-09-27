from __future__ import annotations

import ast
from pathlib import Path


def test_memory_file_editor_shared_package_has_no_local_or_action_imports() -> None:
    root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "pantaray_agents"
        / "agents"
        / "memory_file_editor"
    )
    forbidden = (
        "pantaray_agents.local_runtime",
        "pantaray_agents.agents.action_agent",
        "pantaray_cloud",
    )

    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = tuple(_imported_module(node) for node in ast.walk(tree))
        offenders = [
            name
            for name in imports
            if name is not None and any(name.startswith(prefix) for prefix in forbidden)
        ]
        assert offenders == [], f"{path} imports forbidden modules: {offenders}"


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
