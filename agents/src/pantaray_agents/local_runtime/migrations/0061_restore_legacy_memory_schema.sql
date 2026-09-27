-- Restore the pre-0057 legacy prose-memory schema surface for context-v2 reset.
-- Databases that already ran 0057 lost legacy agent_facts rows, fact run rows,
-- insight update run rows, and long-term insight columns on agent_insights.
-- That pre-0057 data is unrecoverable from this migration. If an incompatible
-- 0057-era agent_insights table exists, the Python migration guard renames it to
-- agent_insights_v2_retired before recreating the legacy shape.
SELECT 1;
