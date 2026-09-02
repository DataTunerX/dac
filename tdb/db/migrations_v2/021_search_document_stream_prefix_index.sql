-- Accelerate hierarchical (namespaced) stream search.
--
-- Hierarchical stream search matches a stream id and all dot-delimited
-- descendants via starts_with(stream_id, prefix || '.') (equivalent to the
-- prefix `^@` operator). The default-collation btree on search_document
-- (stream_id, event_seq) does not serve prefix range scans; a text_pattern_ops
-- index does.

CREATE INDEX IF NOT EXISTS idx_search_document_stream_prefix
  ON search_document (stream_id text_pattern_ops);
