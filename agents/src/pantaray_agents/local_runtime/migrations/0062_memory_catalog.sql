CREATE TABLE memory_nodes (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN (
        'activity_log', 'activity_summary', 'suggestion', 'action',
        'short_term_insight', 'long_term_insight', 'fact'
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

CREATE TABLE memory_revisions (
    user_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    body_kind TEXT NOT NULL CHECK (body_kind IN ('inline', 'artifact_tree')),
    inline_body TEXT,
    artifact_root_path TEXT,
    fragment_schema_version INTEGER NOT NULL CHECK (fragment_schema_version > 0),
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, revision_id),
    UNIQUE (user_id, node_id, revision_id),
    FOREIGN KEY (user_id, node_id) REFERENCES memory_nodes(user_id, node_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CHECK (
        (body_kind = 'inline' AND inline_body IS NOT NULL AND artifact_root_path IS NULL)
        OR
        (body_kind = 'artifact_tree' AND inline_body IS NULL AND artifact_root_path IS NOT NULL)
    )
);

CREATE TABLE memory_revision_parents (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    child_revision_id TEXT NOT NULL,
    parent_revision_id TEXT NOT NULL,
    PRIMARY KEY (user_id, child_revision_id),
    FOREIGN KEY (user_id, node_id, child_revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, node_id, parent_revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id) ON DELETE CASCADE,
    CHECK (child_revision_id != parent_revision_id)
);

CREATE TABLE memory_fragments (
    user_id TEXT NOT NULL,
    fragment_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    block_kind TEXT NOT NULL CHECK (block_kind IN (
        'record_root', 'document_root', 'heading', 'paragraph', 'list_item',
        'block_quote', 'code_block', 'table', 'other'
    )),
    block_index INTEGER NOT NULL CHECK (block_index >= 0),
    heading_path TEXT,
    content_text TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    PRIMARY KEY (user_id, fragment_id),
    UNIQUE (user_id, revision_id, fragment_id),
    UNIQUE (user_id, revision_id, source_path, block_index),
    FOREIGN KEY (user_id, revision_id)
        REFERENCES memory_revisions(user_id, revision_id) ON DELETE CASCADE
);

CREATE TABLE memory_links (
    user_id TEXT NOT NULL,
    source_revision_id TEXT NOT NULL,
    local_ref_id TEXT NOT NULL,
    source_fragment_id TEXT NOT NULL,
    target_fragment_id TEXT NOT NULL,
    reference_note TEXT NOT NULL CHECK (
        length(trim(reference_note)) > 0
        AND instr(reference_note, char(10)) = 0
        AND instr(reference_note, char(13)) = 0
    ),
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, source_revision_id, local_ref_id),
    FOREIGN KEY (user_id, source_revision_id, source_fragment_id)
        REFERENCES memory_fragments(user_id, revision_id, fragment_id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_id, target_fragment_id)
        REFERENCES memory_fragments(user_id, fragment_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE memory_revision_intents (
    user_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    base_revision_id TEXT,
    manifest_sha256 TEXT NOT NULL,
    artifact_root_path TEXT NOT NULL,
    intent_kind TEXT NOT NULL CHECK (intent_kind IN (
        'fact', 'long_term_insight', 'fact_repair', 'long_term_insight_repair'
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

CREATE TABLE memory_evidence_edges (
    user_id TEXT NOT NULL,
    derived_revision_id TEXT NOT NULL,
    source_revision_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL CHECK (length(trim(evidence_role)) > 0),
    PRIMARY KEY (user_id, derived_revision_id, source_revision_id, evidence_role),
    FOREIGN KEY (user_id, derived_revision_id)
        REFERENCES memory_revisions(user_id, revision_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, source_revision_id)
        REFERENCES memory_revisions(user_id, revision_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE memory_link_quarantine (
    user_id TEXT NOT NULL,
    quarantine_id TEXT NOT NULL,
    owner_source TEXT NOT NULL,
    owner_record_id TEXT NOT NULL,
    local_ref_id TEXT NOT NULL,
    source_path TEXT,
    source_markup TEXT NOT NULL,
    legacy_target_memory_key TEXT,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, quarantine_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE memory_artifact_deletions (
    user_id TEXT NOT NULL,
    deletion_id TEXT NOT NULL,
    artifact_path TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('revision_gc', 'user_erasure')),
    state TEXT NOT NULL CHECK (
        state IN ('planned', 'quarantined', 'database_detached')
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, deletion_id),
    UNIQUE (user_id, artifact_path)
);

CREATE TABLE memory_catalog_cutovers (
    cutover_name TEXT PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('running', 'completed', 'failed')),
    inventory_json TEXT NOT NULL CHECK (json_valid(inventory_json)),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    error_code TEXT,
    CHECK (
        (state = 'completed' AND completed_at IS NOT NULL AND error_code IS NULL)
        OR (state = 'failed' AND completed_at IS NOT NULL AND error_code IS NOT NULL)
        OR (state = 'running' AND completed_at IS NULL AND error_code IS NULL)
    )
);

CREATE TABLE memory_repair_queue (
    user_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    detected_revision_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'completed')),
    created_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (user_id, node_id, detected_revision_id),
    FOREIGN KEY (user_id, node_id)
        REFERENCES memory_nodes(user_id, node_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, detected_revision_id)
        REFERENCES memory_revisions(user_id, revision_id) ON DELETE CASCADE
);

CREATE INDEX idx_memory_links_target
    ON memory_links(user_id, target_fragment_id);
CREATE INDEX idx_memory_nodes_current_revision
    ON memory_nodes(user_id, current_revision_id);
CREATE INDEX idx_memory_nodes_lifecycle
    ON memory_nodes(user_id, lifecycle, integrity, updated_at);
CREATE INDEX idx_memory_fragments_revision
    ON memory_fragments(user_id, revision_id, source_path, block_index);
CREATE UNIQUE INDEX idx_one_user_erasure
    ON memory_artifact_deletions(user_id) WHERE reason = 'user_erasure';

CREATE VIRTUAL TABLE memory_fragments_fts USING fts5(
    content_text,
    content='memory_fragments',
    content_rowid='rowid'
);

CREATE TRIGGER memory_fragments_fts_ai AFTER INSERT ON memory_fragments BEGIN
    INSERT INTO memory_fragments_fts(rowid, content_text)
    VALUES (new.rowid, new.content_text);
END;

CREATE TRIGGER memory_fragments_fts_ad AFTER DELETE ON memory_fragments BEGIN
    INSERT INTO memory_fragments_fts(memory_fragments_fts, rowid, content_text)
    VALUES ('delete', old.rowid, old.content_text);
END;
