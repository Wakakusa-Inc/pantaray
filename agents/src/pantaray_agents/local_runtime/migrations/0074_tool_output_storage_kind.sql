ALTER TABLE tool_outputs
ADD COLUMN output_storage_kind TEXT CHECK (
    output_storage_kind IS NULL
    OR output_storage_kind IN ('inline_json', 'action_file')
);
