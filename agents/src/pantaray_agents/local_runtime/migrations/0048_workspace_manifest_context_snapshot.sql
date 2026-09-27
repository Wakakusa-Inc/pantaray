ALTER TABLE workspace_manifests
ADD COLUMN workspace_context_snapshot_json TEXT NOT NULL
DEFAULT '{"folders":[],"organizations":[],"projects":[]}'
CHECK (json_valid(workspace_context_snapshot_json));
