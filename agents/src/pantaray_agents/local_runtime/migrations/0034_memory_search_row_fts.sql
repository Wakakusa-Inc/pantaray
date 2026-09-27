CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_agent_suggestions_fts USING fts5(
    answer,
    content='agent_suggestions',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_agent_actions_fts USING fts5(
    final_output,
    content='agent_actions',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_agent_insights_fts USING fts5(
    short_term_insight_data,
    content='agent_insights',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_activity_logs_fts USING fts5(
    description,
    content='activity_logs',
    content_rowid='rowid'
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_search_activity_summaries_fts USING fts5(
    summary,
    content='activity_summaries',
    content_rowid='rowid'
);

INSERT INTO memory_search_agent_suggestions_fts(memory_search_agent_suggestions_fts)
VALUES('rebuild');

INSERT INTO memory_search_agent_actions_fts(memory_search_agent_actions_fts)
VALUES('rebuild');

INSERT INTO memory_search_agent_insights_fts(memory_search_agent_insights_fts)
VALUES('rebuild');

INSERT INTO memory_search_activity_logs_fts(memory_search_activity_logs_fts)
VALUES('rebuild');

INSERT INTO memory_search_activity_summaries_fts(memory_search_activity_summaries_fts)
VALUES('rebuild');

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_suggestions_ai
AFTER INSERT ON agent_suggestions BEGIN
    INSERT INTO memory_search_agent_suggestions_fts(rowid, answer)
    VALUES (new.rowid, new.answer);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_suggestions_ad
AFTER DELETE ON agent_suggestions BEGIN
    INSERT INTO memory_search_agent_suggestions_fts(
        memory_search_agent_suggestions_fts,
        rowid,
        answer
    ) VALUES('delete', old.rowid, old.answer);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_suggestions_au
AFTER UPDATE ON agent_suggestions BEGIN
    INSERT INTO memory_search_agent_suggestions_fts(
        memory_search_agent_suggestions_fts,
        rowid,
        answer
    ) VALUES('delete', old.rowid, old.answer);
    INSERT INTO memory_search_agent_suggestions_fts(rowid, answer)
    VALUES (new.rowid, new.answer);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_actions_ai
AFTER INSERT ON agent_actions BEGIN
    INSERT INTO memory_search_agent_actions_fts(rowid, final_output)
    VALUES (new.rowid, new.final_output);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_actions_ad
AFTER DELETE ON agent_actions BEGIN
    INSERT INTO memory_search_agent_actions_fts(
        memory_search_agent_actions_fts,
        rowid,
        final_output
    ) VALUES('delete', old.rowid, old.final_output);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_actions_au
AFTER UPDATE ON agent_actions BEGIN
    INSERT INTO memory_search_agent_actions_fts(
        memory_search_agent_actions_fts,
        rowid,
        final_output
    ) VALUES('delete', old.rowid, old.final_output);
    INSERT INTO memory_search_agent_actions_fts(rowid, final_output)
    VALUES (new.rowid, new.final_output);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_ai
AFTER INSERT ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_ad
AFTER DELETE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_agent_insights_au
AFTER UPDATE ON agent_insights BEGIN
    INSERT INTO memory_search_agent_insights_fts(
        memory_search_agent_insights_fts,
        rowid,
        short_term_insight_data
    ) VALUES('delete', old.rowid, old.short_term_insight_data);
    INSERT INTO memory_search_agent_insights_fts(rowid, short_term_insight_data)
    VALUES (new.rowid, new.short_term_insight_data);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_logs_ai
AFTER INSERT ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(rowid, description)
    VALUES (new.rowid, new.description);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_logs_ad
AFTER DELETE ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(
        memory_search_activity_logs_fts,
        rowid,
        description
    ) VALUES('delete', old.rowid, old.description);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_logs_au
AFTER UPDATE ON activity_logs BEGIN
    INSERT INTO memory_search_activity_logs_fts(
        memory_search_activity_logs_fts,
        rowid,
        description
    ) VALUES('delete', old.rowid, old.description);
    INSERT INTO memory_search_activity_logs_fts(rowid, description)
    VALUES (new.rowid, new.description);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_summaries_ai
AFTER INSERT ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(rowid, summary)
    VALUES (new.rowid, new.summary);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_summaries_ad
AFTER DELETE ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(
        memory_search_activity_summaries_fts,
        rowid,
        summary
    ) VALUES('delete', old.rowid, old.summary);
END;

CREATE TRIGGER IF NOT EXISTS trg_memory_search_activity_summaries_au
AFTER UPDATE ON activity_summaries BEGIN
    INSERT INTO memory_search_activity_summaries_fts(
        memory_search_activity_summaries_fts,
        rowid,
        summary
    ) VALUES('delete', old.rowid, old.summary);
    INSERT INTO memory_search_activity_summaries_fts(rowid, summary)
    VALUES (new.rowid, new.summary);
END;
