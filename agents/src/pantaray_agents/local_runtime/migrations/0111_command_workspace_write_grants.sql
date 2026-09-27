CREATE TABLE command_workspace_write_grants (
    invocation_id TEXT NOT NULL REFERENCES tool_invocations(invocation_id) ON DELETE CASCADE,
    actor_process_id TEXT NOT NULL REFERENCES processes(process_id) ON DELETE NO ACTION,
    normalized_key TEXT NOT NULL CHECK (LENGTH(TRIM(normalized_key)) > 0),
    PRIMARY KEY (invocation_id, normalized_key)
);
