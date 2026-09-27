ALTER TABLE memory_embedding_generations
ADD COLUMN max_text_chars INTEGER NOT NULL DEFAULT 50000
    CHECK (max_text_chars > 0);

-- Scoped generations retain migration 0071's 50,000-character identity.
-- An unused bootstrap generation has no chunks and can adopt the current limit.
UPDATE memory_embedding_generations AS generations
SET max_text_chars = 4000
WHERE NOT EXISTS (
    SELECT 1
    FROM memory_embedding_user_generations AS scopes
    WHERE scopes.generation_id = generations.generation_id
);

DROP TRIGGER memory_fragments_embedding_work_ai;

CREATE TRIGGER memory_fragments_embedding_work_ai
AFTER INSERT ON memory_fragments
WHEN new.block_kind NOT IN ('record_root', 'document_root')
BEGIN
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
        WITH RECURSIVE chunk_indices(
            generation_id, chunk_index, max_text_chars
        ) AS (
            SELECT generation_id, 0, max_text_chars
            FROM memory_embedding_generations
            WHERE length(new.content_text) > 0
            UNION ALL
            SELECT generation_id, chunk_index + 1, max_text_chars
            FROM chunk_indices
            WHERE (chunk_index + 1) * max_text_chars
                < length(new.content_text)
        )
        SELECT generation_id, chunk_index FROM chunk_indices
    ) AS chunks ON chunks.generation_id = scopes.generation_id
    WHERE scopes.user_id = new.user_id
      AND scopes.state IN ('active', 'building');
END;
