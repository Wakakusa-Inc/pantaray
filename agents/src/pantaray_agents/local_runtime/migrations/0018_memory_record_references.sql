CREATE TABLE IF NOT EXISTS memory_record_references (
    user_id TEXT NOT NULL,
    owner_memory_key TEXT NOT NULL,
    local_ref_id TEXT NOT NULL,
    target_memory_key TEXT NOT NULL,
    reference_note TEXT,
    anchor_text TEXT,
    anchor_order INTEGER NOT NULL CHECK (anchor_order >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    PRIMARY KEY (owner_memory_key, local_ref_id)
);

CREATE INDEX IF NOT EXISTS idx_memory_record_references_user_owner
ON memory_record_references(user_id, owner_memory_key, anchor_order ASC);

CREATE INDEX IF NOT EXISTS idx_memory_record_references_user_target
ON memory_record_references(user_id, target_memory_key, updated_at DESC);
