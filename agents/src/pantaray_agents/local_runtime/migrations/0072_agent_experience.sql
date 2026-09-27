PRAGMA foreign_keys = OFF;

CREATE TABLE memory_nodes_v0072 (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'activity_log', 'activity_summary', 'suggestion', 'action',
        'action_file_read', 'agent_experience', 'short_term_insight',
        'long_term_insight', 'fact'
    )),
    source_record_id TEXT NOT NULL,
    lifecycle TEXT NOT NULL CHECK (
        lifecycle IN ('preparing', 'active', 'tombstoned')
    ),
    integrity TEXT NOT NULL CHECK (integrity IN ('healthy', 'corrupt')),
    current_revision_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, node_id),
    UNIQUE (user_id, source_type, source_record_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, node_id, current_revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        (lifecycle = 'preparing' AND current_revision_id IS NULL)
        OR
        (lifecycle IN ('active', 'tombstoned') AND current_revision_id IS NOT NULL)
    ),
    CHECK (lifecycle != 'preparing' OR integrity = 'healthy')
);

INSERT INTO memory_nodes_v0072(
    user_id, node_id, source_type, source_record_id, lifecycle, integrity,
    current_revision_id, created_at, updated_at
)
SELECT
    user_id, node_id, source_type, source_record_id, lifecycle, integrity,
    current_revision_id, created_at, updated_at
FROM memory_nodes;

DROP TABLE memory_nodes;
ALTER TABLE memory_nodes_v0072 RENAME TO memory_nodes;

CREATE INDEX idx_memory_nodes_current_revision
    ON memory_nodes(user_id, current_revision_id);
CREATE INDEX idx_memory_nodes_lifecycle
    ON memory_nodes(user_id, lifecycle, integrity, updated_at);
CREATE INDEX idx_memory_nodes_record_exact
    ON memory_nodes(user_id, source_record_id);

CREATE TABLE memory_revision_intents_v0072 (
    user_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    base_revision_id TEXT,
    manifest_sha256 TEXT NOT NULL,
    artifact_root_path TEXT NOT NULL,
    intent_kind TEXT NOT NULL CHECK (intent_kind IN (
        'fact', 'long_term_insight', 'agent_experience',
        'fact_repair', 'long_term_insight_repair', 'agent_experience_repair'
    )),
    domain_payload_json TEXT NOT NULL CHECK (json_valid(domain_payload_json)),
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, revision_id),
    UNIQUE (user_id, node_id),
    UNIQUE (user_id, artifact_root_path),
    FOREIGN KEY (user_id, node_id)
        REFERENCES memory_nodes(user_id, node_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, node_id, base_revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

INSERT INTO memory_revision_intents_v0072(
    user_id, revision_id, node_id, base_revision_id, manifest_sha256,
    artifact_root_path, intent_kind, domain_payload_json, created_at
)
SELECT
    user_id, revision_id, node_id, base_revision_id, manifest_sha256,
    artifact_root_path, intent_kind, domain_payload_json, created_at
FROM memory_revision_intents;

DROP TABLE memory_revision_intents;
ALTER TABLE memory_revision_intents_v0072 RENAME TO memory_revision_intents;

CREATE TABLE workspace_manifest_roots_v0072 (
    root_id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (
        source_type IN ('folder', 'scratch', 'agent_experience')
    ),
    source_id TEXT,
    display_name TEXT NOT NULL,
    canonical_real_path TEXT NOT NULL,
    real_path TEXT NOT NULL,
    can_read INTEGER NOT NULL CHECK (can_read IN (0, 1)),
    can_apply_patch INTEGER NOT NULL CHECK (can_apply_patch IN (0, 1)),
    can_process_read INTEGER NOT NULL CHECK (can_process_read IN (0, 1)),
    can_process_write INTEGER NOT NULL CHECK (can_process_write IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (manifest_id)
        REFERENCES workspace_manifests(manifest_id) ON DELETE CASCADE,
    CHECK (
        (source_type = 'folder' AND source_id IS NOT NULL AND trim(source_id) <> '')
        OR (source_type = 'scratch' AND source_id = manifest_id)
        OR (
            source_type = 'agent_experience'
            AND source_id IS NOT NULL
            AND trim(source_id) <> ''
        )
    ),
    UNIQUE (manifest_id, canonical_real_path)
);

INSERT INTO workspace_manifest_roots_v0072(
    root_id, manifest_id, source_type, source_id, display_name,
    canonical_real_path, real_path, can_read, can_apply_patch,
    can_process_read, can_process_write, created_at
)
SELECT
    root_id, manifest_id, source_type, source_id, display_name,
    canonical_real_path, real_path, can_read, can_apply_patch,
    can_process_read, can_process_write, created_at
FROM workspace_manifest_roots;

DROP TABLE workspace_manifest_roots;
ALTER TABLE workspace_manifest_roots_v0072 RENAME TO workspace_manifest_roots;

CREATE INDEX idx_workspace_manifest_roots_source
    ON workspace_manifest_roots(source_type, source_id);

CREATE TABLE processes_v0072 (
    process_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'suggestion', 'suggestion_critic', 'action', 'insight', 'fact',
            'activity_description', 'activity_summary',
            'post_action_pipeline', 'agent_experience'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'enqueued', 'running', 'paused', 'completed', 'failed',
            'canceled', 'success', 'error', 'abandoned'
        )
    ),
    suggestion_id TEXT,
    action_id TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    heartbeat_at TEXT NOT NULL,
    terminal_event_id TEXT,
    acknowledged_at TEXT,
    current_job_id TEXT,
    next_event_seq INTEGER NOT NULL CHECK (next_event_seq >= 1),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

INSERT INTO processes_v0072(
    process_id, user_id, kind, status, suggestion_id, action_id, started_at,
    updated_at, completed_at, heartbeat_at, terminal_event_id,
    acknowledged_at, current_job_id, next_event_seq
)
SELECT
    process_id, user_id, kind, status, suggestion_id, action_id, started_at,
    updated_at, completed_at, heartbeat_at, terminal_event_id,
    acknowledged_at, current_job_id, next_event_seq
FROM processes;

DROP TABLE processes;
ALTER TABLE processes_v0072 RENAME TO processes;

CREATE INDEX idx_processes_user_updated
    ON processes(user_id, updated_at DESC);
CREATE INDEX idx_processes_kind_status
    ON processes(kind, status);
CREATE UNIQUE INDEX idx_processes_terminal_event_id
    ON processes(terminal_event_id) WHERE terminal_event_id IS NOT NULL;

CREATE TABLE agent_experience_extraction_runs (
    user_id TEXT NOT NULL,
    job_id TEXT NOT NULL PRIMARY KEY,
    action_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK (
        operation IN ('no_change', 'upsert', 'supersede')
    ),
    experience_id TEXT,
    superseded_experience_id TEXT,
    revision_id TEXT,
    prompt_name TEXT NOT NULL CHECK (length(trim(prompt_name)) > 0),
    prompt_version TEXT NOT NULL CHECK (length(trim(prompt_version)) > 0),
    completed_at TEXT NOT NULL,
    UNIQUE (user_id, action_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(job_id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    CHECK (
        (
            operation = 'no_change'
            AND experience_id IS NULL
            AND superseded_experience_id IS NULL
            AND revision_id IS NULL
        )
        OR (
            operation = 'upsert'
            AND experience_id IS NOT NULL
            AND superseded_experience_id IS NULL
            AND revision_id IS NOT NULL
        )
        OR (
            operation = 'supersede'
            AND experience_id IS NOT NULL
            AND superseded_experience_id IS NOT NULL
            AND experience_id <> superseded_experience_id
            AND revision_id IS NOT NULL
        )
    )
);

PRAGMA foreign_keys = ON;
