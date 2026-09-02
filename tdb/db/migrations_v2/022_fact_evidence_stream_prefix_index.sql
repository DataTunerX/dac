-- Accelerate hierarchical stream filtering for ontology facts.
--
-- Fact list/search prefix mode filters through ontology_fact_evidence.stream_id
-- using the dot-boundary predicate:
--   stream_id = prefix OR starts_with(stream_id, prefix || '.')
-- A text_pattern_ops index gives PostgreSQL an index path for the prefix side,
-- while fact_id keeps the EXISTS join back to ontology_fact cheap.

CREATE INDEX IF NOT EXISTS idx_fact_evidence_stream_prefix
  ON ontology_fact_evidence (stream_id text_pattern_ops, fact_id);
