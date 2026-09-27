-- The logged-out owner of this installation's local store. One row per store;
-- Pantaray accounts keep their own users rows and never replace this one.
CREATE TABLE local_owner (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);
