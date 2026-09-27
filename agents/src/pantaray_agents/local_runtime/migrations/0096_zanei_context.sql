CREATE TABLE context_sources (
    user_id TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    state_json TEXT NOT NULL CHECK (json_valid(state_json))
);
CREATE TABLE context_source_receipts (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    PRIMARY KEY (user_id, request_id)
);
CREATE TABLE context_streams (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    binding_json TEXT NOT NULL CHECK (json_valid(binding_json)),
    cursor TEXT NOT NULL CHECK (length(cursor) > 0),
    PRIMARY KEY (user_id, binding_json),
    CHECK (json_extract(binding_json, '$.user_id') = user_id)
);
CREATE TABLE context_batches (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    binding_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL CHECK (json_valid(outcome_json)),
    PRIMARY KEY (user_id, batch_id),
    FOREIGN KEY (user_id, binding_json)
        REFERENCES context_streams(user_id, binding_json)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CHECK (json_extract(outcome_json, '$.coverage.batch_id') = batch_id),
    CHECK (json_extract(outcome_json, '$.coverage.binding.user_id') = user_id)
);
CREATE TABLE context_batch_activities (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    node_id TEXT NOT NULL,
    revision_id TEXT NOT NULL,
    reference_json TEXT NOT NULL CHECK (json_valid(reference_json)),
    PRIMARY KEY (user_id, batch_id, revision_id),
    FOREIGN KEY (user_id, batch_id) REFERENCES context_batches(user_id, batch_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (user_id, node_id, revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE context_work_heads (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    PRIMARY KEY (user_id, work_id),
    FOREIGN KEY (user_id, work_id, revision)
        REFERENCES context_work_revisions(user_id, work_id, revision)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE context_work_revisions (
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    batch_id TEXT NOT NULL,
    insight_node_id TEXT NOT NULL,
    insight_revision_id TEXT NOT NULL,
    record_json TEXT NOT NULL CHECK (json_valid(record_json)),
    PRIMARY KEY (user_id, work_id, revision),
    FOREIGN KEY (user_id, batch_id) REFERENCES context_batches(user_id, batch_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (user_id, insight_node_id, insight_revision_id)
        REFERENCES memory_revisions(user_id, node_id, revision_id)
        ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CHECK (json_extract(record_json, '$.context.user_id') = user_id),
    CHECK (json_extract(record_json, '$.context.work.work_id') = work_id),
    CHECK (json_extract(record_json, '$.context.work.revision') = revision)
);
CREATE INDEX context_batch_activities_catalog_parent
    ON context_batch_activities(user_id, node_id, revision_id);
CREATE INDEX context_work_revisions_catalog_parent
    ON context_work_revisions(user_id, insight_node_id, insight_revision_id);
