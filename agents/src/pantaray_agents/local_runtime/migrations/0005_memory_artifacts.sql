CREATE TABLE IF NOT EXISTS agent_insights (
    insight_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    suggestion_id TEXT NOT NULL,
    action_id TEXT,
    insight_update_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    short_term_insight_data TEXT NOT NULL,
    facts TEXT NOT NULL,
    insight_profile_brief TEXT,
    thinking TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    long_term_insight_storage_path TEXT,
    long_term_insight_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id),
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id, suggestion_id) REFERENCES agent_suggestions(user_id, suggestion_id),
    FOREIGN KEY (user_id, action_id) REFERENCES agent_actions(user_id, action_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_insights_user_created
ON agent_insights(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_facts (
    fact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    facts_profile_brief TEXT,
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    response_text TEXT,
    llm_output TEXT CHECK (llm_output IS NULL OR json_valid(llm_output)),
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_insight_ids TEXT CHECK (source_insight_ids IS NULL OR json_valid(source_insight_ids)),
    structured_fact_storage_path TEXT,
    structured_fact_sha256 TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_agent_facts_user_created
ON agent_facts(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_artifacts (
    artifact_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('long_term_insight', 'facts')),
    source_record_id TEXT NOT NULL,
    root_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    logical_created_at TEXT NOT NULL,
    logical_updated_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, source_type, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_artifacts_user_source_updated
ON memory_artifacts(user_id, source_type, logical_updated_at DESC);

CREATE TABLE IF NOT EXISTS memory_artifact_files (
    file_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    mime_type TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (artifact_id) REFERENCES memory_artifacts(artifact_id) ON DELETE CASCADE,
    UNIQUE (artifact_id, relative_path)
);

CREATE TABLE IF NOT EXISTS memory_artifact_blocks (
    block_rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    block_id TEXT NOT NULL UNIQUE,
    file_id TEXT NOT NULL,
    block_kind TEXT NOT NULL CHECK (block_kind IN ('heading', 'paragraph', 'list_item')),
    heading_path TEXT,
    block_index INTEGER NOT NULL CHECK (block_index >= 0),
    search_text TEXT NOT NULL,
    preview_text TEXT NOT NULL,
    start_offset INTEGER CHECK (start_offset IS NULL OR start_offset >= 0),
    end_offset INTEGER CHECK (end_offset IS NULL OR end_offset >= 0),
    FOREIGN KEY (file_id) REFERENCES memory_artifact_files(file_id) ON DELETE CASCADE,
    UNIQUE (file_id, block_index)
);

CREATE INDEX IF NOT EXISTS idx_memory_artifact_blocks_file_block
ON memory_artifact_blocks(file_id, block_index ASC);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_artifact_blocks_fts USING fts5(
    search_text,
    content='memory_artifact_blocks',
    content_rowid='block_rowid'
);
