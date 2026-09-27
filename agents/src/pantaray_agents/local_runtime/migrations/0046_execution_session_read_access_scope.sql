ALTER TABLE execution_sessions
ADD COLUMN read_access_scope TEXT NOT NULL DEFAULT 'workspace'
CHECK (read_access_scope IN ('workspace', 'full_access'));
