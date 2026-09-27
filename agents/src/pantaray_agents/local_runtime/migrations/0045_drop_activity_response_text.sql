DROP TRIGGER IF EXISTS trg_memory_search_activity_logs_ai;
DROP TRIGGER IF EXISTS trg_memory_search_activity_logs_ad;
DROP TRIGGER IF EXISTS trg_memory_search_activity_logs_au;
DROP TRIGGER IF EXISTS trg_memory_search_activity_summaries_ai;
DROP TRIGGER IF EXISTS trg_memory_search_activity_summaries_ad;
DROP TRIGGER IF EXISTS trg_memory_search_activity_summaries_au;

CREATE TABLE activity_logs_new (
    log_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_capture_paths TEXT CHECK (source_capture_paths IS NULL OR json_valid(source_capture_paths)),
    used_image_count INTEGER CHECK (used_image_count IS NULL OR used_image_count >= 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, period_start, period_end)
);

INSERT INTO activity_logs_new(
    rowid,
    log_id,
    user_id,
    period_start,
    period_end,
    description,
    status,
    error,
    prompt_text,
    prompt_name,
    prompt_version,
    source_capture_paths,
    used_image_count,
    created_at,
    updated_at
)
SELECT
    rowid,
    log_id,
    user_id,
    period_start,
    period_end,
    description,
    status,
    error,
    prompt_text,
    prompt_name,
    prompt_version,
    source_capture_paths,
    used_image_count,
    created_at,
    updated_at
FROM activity_logs;

DROP TABLE activity_logs;
ALTER TABLE activity_logs_new RENAME TO activity_logs;

CREATE INDEX idx_activity_logs_user_period
ON activity_logs(user_id, period_start DESC);

CREATE TABLE activity_summaries_new (
    summary_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    summary_type TEXT NOT NULL CHECK (summary_type IN ('1h', '24h', '1w', '1m', '3m')),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'success', 'error', 'canceled', 'timeout')),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    prompt_text TEXT,
    prompt_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    source_ids TEXT CHECK (source_ids IS NULL OR json_valid(source_ids)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    fact_followup_fact_id TEXT,
    fact_followup_enqueued_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    UNIQUE (user_id, summary_type, period_start, period_end)
);

INSERT INTO activity_summaries_new(
    rowid,
    summary_id,
    user_id,
    summary_type,
    period_start,
    period_end,
    summary,
    status,
    error,
    prompt_text,
    prompt_name,
    prompt_version,
    source_ids,
    created_at,
    updated_at,
    fact_followup_fact_id,
    fact_followup_enqueued_at
)
SELECT
    rowid,
    summary_id,
    user_id,
    summary_type,
    period_start,
    period_end,
    summary,
    status,
    error,
    prompt_text,
    prompt_name,
    prompt_version,
    source_ids,
    created_at,
    updated_at,
    fact_followup_fact_id,
    fact_followup_enqueued_at
FROM activity_summaries;

DROP TABLE activity_summaries;
ALTER TABLE activity_summaries_new RENAME TO activity_summaries;

CREATE INDEX idx_activity_summaries_user_period
ON activity_summaries(user_id, summary_type, period_start DESC);

CREATE INDEX idx_activity_summaries_fact_followup_fact_id
ON activity_summaries(fact_followup_fact_id);

CREATE TRIGGER trg_memory_search_activity_logs_ai
AFTER INSERT ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(rowid, description)
    VALUES (new.rowid, new.description);
END;

CREATE TRIGGER trg_memory_search_activity_logs_ad
AFTER DELETE ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(
        memory_search_activity_logs_fts,
        rowid,
        description
    ) VALUES('delete', old.rowid, old.description);
END;

CREATE TRIGGER trg_memory_search_activity_logs_au
AFTER UPDATE ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(
        memory_search_activity_logs_fts,
        rowid,
        description
    ) VALUES('delete', old.rowid, old.description);
    INSERT INTO memory_search_activity_logs_fts(rowid, description)
    VALUES (new.rowid, new.description);
END;

CREATE TRIGGER trg_memory_search_activity_summaries_ai
AFTER INSERT ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(rowid, summary)
    VALUES (new.rowid, new.summary);
END;

CREATE TRIGGER trg_memory_search_activity_summaries_ad
AFTER DELETE ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(
        memory_search_activity_summaries_fts,
        rowid,
        summary
    ) VALUES('delete', old.rowid, old.summary);
END;

CREATE TRIGGER trg_memory_search_activity_summaries_au
AFTER UPDATE ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(
        memory_search_activity_summaries_fts,
        rowid,
        summary
    ) VALUES('delete', old.rowid, old.summary);
    INSERT INTO memory_search_activity_summaries_fts(rowid, summary)
    VALUES (new.rowid, new.summary);
END;

INSERT INTO memory_search_activity_logs_fts(memory_search_activity_logs_fts)
VALUES('rebuild');

INSERT INTO memory_search_activity_summaries_fts(memory_search_activity_summaries_fts)
VALUES('rebuild');
