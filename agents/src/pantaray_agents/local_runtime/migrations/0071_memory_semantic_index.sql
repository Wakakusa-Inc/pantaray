CREATE TABLE memory_embedding_generations (
    generation_id INTEGER PRIMARY KEY CHECK (generation_id > 0),
    profile_id TEXT NOT NULL CHECK (
        profile_id IN (
            'memory.titan-text-v2-512.v1',
            'memory.titan-text-v2-1024.v1'
        )
    ),
    model_id TEXT NOT NULL CHECK (length(trim(model_id)) > 0),
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    distance_metric TEXT NOT NULL CHECK (distance_metric = 'cosine'),
    created_at TEXT NOT NULL
);

CREATE TABLE memory_embedding_user_generations (
    user_id TEXT NOT NULL,
    generation_id INTEGER NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('building', 'active')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    activated_at TEXT,
    PRIMARY KEY (user_id, generation_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (generation_id)
        REFERENCES memory_embedding_generations(generation_id) ON DELETE RESTRICT,
    CHECK (
        (state = 'building' AND activated_at IS NULL)
        OR (state = 'active' AND activated_at IS NOT NULL)
    )
);

CREATE UNIQUE INDEX idx_memory_embedding_user_generation_active
    ON memory_embedding_user_generations(user_id)
    WHERE state = 'active';

CREATE UNIQUE INDEX idx_memory_embedding_user_generation_building
    ON memory_embedding_user_generations(user_id)
    WHERE state = 'building';

CREATE TABLE memory_embedding_work (
    user_id TEXT NOT NULL,
    generation_id INTEGER NOT NULL,
    fragment_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    state TEXT NOT NULL CHECK (state IN ('pending', 'retry_wait', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    next_attempt_at TEXT,
    last_error_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, generation_id, fragment_id, chunk_index),
    FOREIGN KEY (user_id, generation_id)
        REFERENCES memory_embedding_user_generations(user_id, generation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_id, fragment_id)
        REFERENCES memory_fragments(user_id, fragment_id) ON DELETE CASCADE,
    CHECK (
        (state = 'pending' AND next_attempt_at IS NULL AND last_error_code IS NULL)
        OR (
            state = 'retry_wait'
            AND next_attempt_at IS NOT NULL
            AND length(trim(last_error_code)) > 0
        )
        OR (
            state = 'failed'
            AND next_attempt_at IS NULL
            AND length(trim(last_error_code)) > 0
        )
    )
);

CREATE INDEX idx_memory_embedding_work_due
    ON memory_embedding_work(
        user_id, state, next_attempt_at, created_at, generation_id,
        fragment_id, chunk_index
    );

CREATE TABLE memory_embedding_entries_g1 (
    embedding_id INTEGER PRIMARY KEY,
    user_id TEXT NOT NULL,
    generation_id INTEGER NOT NULL CHECK (generation_id = 1),
    fragment_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    revision_id TEXT NOT NULL,
    fragment_content_sha256 TEXT NOT NULL
        CHECK (length(fragment_content_sha256) = 64),
    chunk_content_sha256 TEXT NOT NULL CHECK (length(chunk_content_sha256) = 64),
    created_at TEXT NOT NULL,
    UNIQUE (user_id, fragment_id, chunk_index),
    FOREIGN KEY (user_id, generation_id)
        REFERENCES memory_embedding_user_generations(user_id, generation_id)
        ON DELETE CASCADE,
    FOREIGN KEY (user_id, revision_id, fragment_id)
        REFERENCES memory_fragments(user_id, revision_id, fragment_id)
        ON DELETE CASCADE
);

CREATE VIRTUAL TABLE memory_embedding_vectors_g1 USING vec0(
    embedding_id INTEGER PRIMARY KEY,
    embedding FLOAT[512] distance_metric=cosine,
    user_id TEXT PARTITION KEY,
    revision_id TEXT
);

CREATE TRIGGER memory_embedding_entries_g1_ad
AFTER DELETE ON memory_embedding_entries_g1
BEGIN
    DELETE FROM memory_embedding_vectors_g1
    WHERE embedding_id = old.embedding_id;
END;

INSERT INTO memory_embedding_generations(
    generation_id, profile_id, model_id, dimensions, normalized,
    distance_metric, created_at
) VALUES (
    1, 'memory.titan-text-v2-512.v1',
    'amazon.titan-embed-text-v2:0', 512, 1, 'cosine',
    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
);

INSERT INTO memory_embedding_user_generations(
    user_id, generation_id, state, created_at, updated_at, activated_at
)
SELECT user_id, 1, 'building',
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       NULL
FROM users;

CREATE TRIGGER memory_fragments_embedding_work_ai
AFTER INSERT ON memory_fragments
WHEN new.block_kind NOT IN ('record_root', 'document_root')
BEGIN
    -- 50000 is the immutable v1 embedding-profile character limit.
    INSERT INTO memory_embedding_work(
        user_id, generation_id, fragment_id, chunk_index, state, attempt_count,
        next_attempt_at, last_error_code, created_at, updated_at
    )
    SELECT new.user_id, scopes.generation_id, new.fragment_id,
           chunks.chunk_index, 'pending', 0,
           NULL, NULL,
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    FROM memory_embedding_user_generations AS scopes
    JOIN (
        WITH RECURSIVE chunk_indices(chunk_index) AS (
            SELECT 0 WHERE length(new.content_text) > 0
            UNION ALL
            SELECT chunk_index + 1
            FROM chunk_indices
            WHERE (chunk_index + 1) * 50000 < length(new.content_text)
        )
        SELECT chunk_index FROM chunk_indices
    ) AS chunks
    WHERE scopes.user_id = new.user_id
      AND scopes.state IN ('active', 'building');
END;

-- 50000 is the immutable v1 embedding-profile character limit.
WITH RECURSIVE fragment_chunks(
    user_id, generation_id, fragment_id, chunk_index, content_length
) AS (
    SELECT fragments.user_id, scopes.generation_id, fragments.fragment_id,
           0, length(fragments.content_text)
    FROM memory_fragments AS fragments
    JOIN memory_embedding_user_generations AS scopes
      ON scopes.user_id = fragments.user_id
    WHERE fragments.block_kind NOT IN ('record_root', 'document_root')
      AND length(fragments.content_text) > 0
    UNION ALL
    SELECT user_id, generation_id, fragment_id, chunk_index + 1, content_length
    FROM fragment_chunks
    WHERE (chunk_index + 1) * 50000 < content_length
)
INSERT INTO memory_embedding_work(
    user_id, generation_id, fragment_id, chunk_index, state, attempt_count,
    next_attempt_at, last_error_code, created_at, updated_at
)
SELECT user_id, generation_id, fragment_id, chunk_index,
       'pending', 0, NULL, NULL,
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
       strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
FROM fragment_chunks;
