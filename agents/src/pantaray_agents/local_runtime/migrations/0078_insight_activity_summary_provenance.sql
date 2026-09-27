DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ai;
DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_ad;
DROP TRIGGER IF EXISTS trg_memory_search_agent_insights_au;
DROP TABLE IF EXISTS memory_search_agent_insights_fts;

CREATE TABLE agent_insights_activity_summary_provenance (
    insight_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_activity_summary_id TEXT,
    suggestion_id TEXT,
    action_id TEXT,
    insight_update_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('processing', 'success', 'error', 'canceled', 'timeout')
    ),
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
    FOREIGN KEY (source_activity_summary_id)
        REFERENCES activity_summaries(summary_id) ON DELETE SET NULL,
    FOREIGN KEY (suggestion_id)
        REFERENCES agent_suggestions(suggestion_id) ON DELETE SET NULL,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE SET NULL
);

INSERT INTO agent_insights_activity_summary_provenance (
    insight_id,
    user_id,
    source_activity_summary_id,
    suggestion_id,
    action_id,
    insight_update_id,
    status,
    short_term_insight_data,
    facts,
    insight_profile_brief,
    thinking,
    error,
    prompt_text,
    response_text,
    prompt_name,
    prompt_version,
    long_term_insight_storage_path,
    long_term_insight_sha256,
    created_at,
    updated_at
)
SELECT
    insight_id,
    user_id,
    NULL,
    suggestion_id,
    action_id,
    insight_update_id,
    status,
    short_term_insight_data,
    facts,
    insight_profile_brief,
    thinking,
    error,
    prompt_text,
    response_text,
    prompt_name,
    prompt_version,
    long_term_insight_storage_path,
    long_term_insight_sha256,
    created_at,
    updated_at
FROM agent_insights;

DROP TABLE agent_insights;
ALTER TABLE agent_insights_activity_summary_provenance RENAME TO agent_insights;

CREATE INDEX idx_agent_insights_user_created
ON agent_insights(user_id, created_at DESC);

CREATE UNIQUE INDEX idx_agent_insights_user_source_activity_summary
ON agent_insights(user_id, source_activity_summary_id)
WHERE source_activity_summary_id IS NOT NULL AND status = 'success';

CREATE VIRTUAL TABLE memory_search_agent_insights_fts USING fts5(
    short_term_insight_data,
    content='agent_insights',
    content_rowid='rowid'
);

INSERT INTO memory_search_agent_insights_fts(memory_search_agent_insights_fts)
VALUES('rebuild');

CREATE TRIGGER trg_memory_search_agent_insights_ai
AFTER INSERT ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;

CREATE TRIGGER trg_memory_search_agent_insights_ad
AFTER DELETE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
END;

CREATE TRIGGER trg_memory_search_agent_insights_au
AFTER UPDATE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;
