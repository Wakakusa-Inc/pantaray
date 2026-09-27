from __future__ import annotations

from pantaray_agents.local_runtime.tooling.repository.workspace_context import (
    build_workspace_context_catalog,
)
from pantaray_agents.local_runtime.tooling.repository.workspace_settings_models import (
    WorkspaceFolder,
    WorkspaceProject,
    WorkspaceSettings,
)


def test_workspace_context_preserves_saved_project_order() -> None:
    settings = WorkspaceSettings(
        read_access_scope="workspace",
        organizations=(),
        projects=(
            WorkspaceProject("project-z", "Zulu", 0, ()),
            WorkspaceProject("project-a", "Alpha", 1, ()),
        ),
        folders=(
            WorkspaceFolder(
                folder_id="folder-1",
                display_name="Repo",
                real_path="/repo",
                canonical_real_path="/repo",
                organization_ids=(),
                project_ids=("project-a", "project-z"),
            ),
        ),
    )

    catalog = build_workspace_context_catalog(settings)

    assert [project.display_name for project in catalog.projects] == ["Zulu", "Alpha"]
    assert catalog.folders[0].project_names == ("Zulu", "Alpha")
