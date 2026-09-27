DROP INDEX IF EXISTS idx_workspace_folders_user_status;
DROP INDEX IF EXISTS idx_workspace_manifest_mounts_source;
DROP INDEX IF EXISTS idx_file_references_action_created;
DROP INDEX IF EXISTS idx_file_references_manifest;
DROP INDEX IF EXISTS idx_file_references_tool_invocation;

CREATE TEMP TABLE workspace_folder_organizations_v42 AS
SELECT user_id, folder_id, organization_id, created_at
FROM workspace_folder_organizations;

CREATE TEMP TABLE workspace_folder_projects_v42 AS
SELECT user_id, folder_id, project_id, created_at
FROM workspace_folder_projects;

DROP TABLE workspace_folder_organizations;
DROP TABLE workspace_folder_projects;

ALTER TABLE workspace_folders RENAME TO workspace_folders_legacy_v42;

CREATE TABLE workspace_folders (
    folder_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    canonical_real_path TEXT NOT NULL,
    real_path TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, folder_id),
    UNIQUE (user_id, canonical_real_path)
);

INSERT INTO workspace_folders(
    folder_id,
    user_id,
    display_name,
    canonical_real_path,
    real_path,
    status,
    created_at,
    updated_at
)
SELECT
    folder_id,
    user_id,
    display_name,
    canonical_real_path,
    real_path,
    status,
    created_at,
    updated_at
FROM workspace_folders_legacy_v42;

CREATE INDEX idx_workspace_folders_user_status
ON workspace_folders(user_id, status, display_name ASC);

CREATE TABLE workspace_folder_organizations (
    user_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, folder_id, organization_id),
    FOREIGN KEY (user_id, folder_id)
        REFERENCES workspace_folders(user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, organization_id)
        REFERENCES workspace_organizations(user_id, organization_id) ON DELETE CASCADE
);

INSERT INTO workspace_folder_organizations(
    user_id,
    folder_id,
    organization_id,
    created_at
)
SELECT user_id, folder_id, organization_id, created_at
FROM workspace_folder_organizations_v42;

CREATE TABLE workspace_folder_projects (
    user_id TEXT NOT NULL,
    folder_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, folder_id, project_id),
    FOREIGN KEY (user_id, folder_id)
        REFERENCES workspace_folders(user_id, folder_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, project_id)
        REFERENCES workspace_projects(user_id, project_id) ON DELETE CASCADE
);

INSERT INTO workspace_folder_projects(
    user_id,
    folder_id,
    project_id,
    created_at
)
SELECT user_id, folder_id, project_id, created_at
FROM workspace_folder_projects_v42;

DROP TABLE workspace_folders_legacy_v42;

ALTER TABLE workspace_manifests DROP COLUMN virtual_root_path;

CREATE TABLE workspace_manifest_roots (
    root_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('folder', 'scratch')),
    source_id TEXT,
    display_name TEXT NOT NULL,
    canonical_real_path TEXT NOT NULL,
    real_path TEXT NOT NULL,
    can_read INTEGER NOT NULL CHECK (can_read IN (0, 1)),
    can_apply_patch INTEGER NOT NULL CHECK (can_apply_patch IN (0, 1)),
    can_process_read INTEGER NOT NULL CHECK (can_process_read IN (0, 1)),
    can_process_write INTEGER NOT NULL CHECK (can_process_write IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE CASCADE,
    CHECK (
        (source_type = 'folder' AND source_id IS NOT NULL AND trim(source_id) <> '')
        OR (source_type = 'scratch' AND source_id = manifest_id)
    ),
    UNIQUE (manifest_id, canonical_real_path)
);

INSERT INTO workspace_manifest_roots(
    root_id,
    manifest_id,
    source_type,
    source_id,
    display_name,
    canonical_real_path,
    real_path,
    can_read,
    can_apply_patch,
    can_process_read,
    can_process_write,
    created_at
)
SELECT
    mount_id,
    manifest_id,
    source_type,
    source_id,
    display_name,
    canonical_real_path,
    real_path,
    can_read,
    can_apply_patch,
    can_process_read,
    can_process_write,
    created_at
FROM workspace_manifest_mounts;

CREATE INDEX idx_workspace_manifest_roots_source
ON workspace_manifest_roots(source_type, source_id);

ALTER TABLE file_references RENAME TO file_references_legacy_v42;

CREATE TABLE file_references (
    file_reference_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    manifest_id TEXT NOT NULL,
    root_id TEXT,
    tool_invocation_id TEXT,
    local_path TEXT NOT NULL,
    canonical_local_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (manifest_id) REFERENCES workspace_manifests(manifest_id) ON DELETE CASCADE,
    FOREIGN KEY (root_id) REFERENCES workspace_manifest_roots(root_id) ON DELETE CASCADE,
    FOREIGN KEY (tool_invocation_id) REFERENCES tool_invocations(invocation_id) ON DELETE SET NULL,
    UNIQUE (action_id, manifest_id, canonical_local_path)
);

INSERT INTO file_references(
    file_reference_id,
    user_id,
    action_id,
    manifest_id,
    root_id,
    tool_invocation_id,
    local_path,
    canonical_local_path,
    created_at
)
SELECT
    fr.file_reference_id,
    fr.user_id,
    fr.action_id,
    fr.manifest_id,
    fr.mount_id,
    fr.tool_invocation_id,
    CASE
        WHEN fr.virtual_path = wmm.virtual_path THEN wmm.real_path
        ELSE rtrim(wmm.real_path, '/') || '/' ||
            substr(fr.virtual_path, length(rtrim(wmm.virtual_path, '/')) + 2)
    END AS local_path,
    CASE
        WHEN fr.virtual_path = wmm.virtual_path THEN wmm.canonical_real_path
        ELSE rtrim(wmm.canonical_real_path, '/') || '/' ||
            substr(fr.virtual_path, length(rtrim(wmm.virtual_path, '/')) + 2)
    END AS canonical_local_path,
    fr.created_at
FROM file_references_legacy_v42 AS fr
JOIN workspace_manifest_mounts AS wmm
    ON wmm.mount_id = fr.mount_id;

DROP TABLE file_references_legacy_v42;
DROP TABLE workspace_manifest_mounts;

CREATE INDEX idx_file_references_action_created
ON file_references(action_id, created_at ASC);

CREATE INDEX idx_file_references_manifest
ON file_references(manifest_id);

CREATE INDEX idx_file_references_tool_invocation
ON file_references(tool_invocation_id);
