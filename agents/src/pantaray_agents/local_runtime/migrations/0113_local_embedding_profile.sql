PRAGMA foreign_keys = OFF;

-- The embedding profile id is now built from the bundled model's manifest, so
-- the column can no longer be restricted to the two Amazon Titan profiles.
--
-- Nothing is deleted here. Generations produced by the previous model keep
-- their scopes, their work and their projected rows, so referential integrity
-- holds across this migration. The runtime replaces them the way it replaces
-- any superseded generation: it builds a generation for the installed model,
-- and activating it deletes the old scope, cascades its rows away and drops its
-- storage.

CREATE TABLE memory_embedding_generations_local_profile (
    generation_id INTEGER PRIMARY KEY CHECK (generation_id > 0),
    profile_id TEXT NOT NULL CHECK (length(trim(profile_id)) > 0),
    model_id TEXT NOT NULL CHECK (length(trim(model_id)) > 0),
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    normalized INTEGER NOT NULL CHECK (normalized IN (0, 1)),
    distance_metric TEXT NOT NULL CHECK (distance_metric = 'cosine'),
    max_text_chars INTEGER NOT NULL CHECK (max_text_chars > 0),
    created_at TEXT NOT NULL
);

INSERT INTO memory_embedding_generations_local_profile(
    generation_id, profile_id, model_id, dimensions, normalized,
    distance_metric, max_text_chars, created_at
)
SELECT generation_id, profile_id, model_id, dimensions, normalized,
       distance_metric, max_text_chars, created_at
FROM memory_embedding_generations;

-- The work-enqueue triggers name this table, so the rename has to skip SQLite's
-- reference-rewriting pass: it re-parses those triggers while the old table is
-- already gone and refuses the rename.
PRAGMA legacy_alter_table = ON;

DROP TABLE memory_embedding_generations;

ALTER TABLE memory_embedding_generations_local_profile
RENAME TO memory_embedding_generations;

PRAGMA legacy_alter_table = OFF;

PRAGMA foreign_keys = ON;
