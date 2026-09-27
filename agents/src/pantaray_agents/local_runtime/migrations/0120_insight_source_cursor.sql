-- The context-read cursor the short Insight committed with this row, so the
-- Suggestion it queues reads the activity recorded after exactly this Insight.
-- Rows written before this column have no cursor.
ALTER TABLE agent_insights ADD COLUMN source_cursor TEXT;
