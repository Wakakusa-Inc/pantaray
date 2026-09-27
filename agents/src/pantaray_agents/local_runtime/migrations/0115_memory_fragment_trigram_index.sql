-- Re-tokenize the memory fragment index so the lexical search lane works for
-- Japanese. The default unicode61 tokenizer splits on word boundaries, which
-- Japanese text does not have, so a whole sentence became one token and no
-- Japanese query term ever matched. The trigram tokenizer indexes every
-- three-character window instead, which turns MATCH into a substring search in
-- any script. A term shorter than three characters cannot be matched through
-- this index; the search lane decides which of those are worth a scan.
DROP TRIGGER memory_fragments_fts_ai;
DROP TRIGGER memory_fragments_fts_ad;
DROP TABLE memory_fragments_fts;

CREATE VIRTUAL TABLE memory_fragments_fts USING fts5(
    content_text,
    content='memory_fragments',
    content_rowid='rowid',
    tokenize='trigram'
);

-- Index the fragments this store already holds.
INSERT INTO memory_fragments_fts(memory_fragments_fts) VALUES('rebuild');

CREATE TRIGGER memory_fragments_fts_ai AFTER INSERT ON memory_fragments BEGIN
    INSERT INTO memory_fragments_fts(rowid, content_text)
    VALUES (new.rowid, new.content_text);
END;

CREATE TRIGGER memory_fragments_fts_ad AFTER DELETE ON memory_fragments BEGIN
    INSERT INTO memory_fragments_fts(memory_fragments_fts, rowid, content_text)
    VALUES ('delete', old.rowid, old.content_text);
END;
