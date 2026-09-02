-- TDB V2 core baseline schema
-- Generated from V2 core-required migrations (no ontology/ops extension tables).

-- ===== BEGIN db/migrations/011_create_event_sentence.sql =====
CREATE TABLE IF NOT EXISTS event_sentence (
  stream_id     TEXT NOT NULL,
  event_id      TEXT NOT NULL,
  sent_index    INTEGER NOT NULL,
  start_char    INTEGER NOT NULL,
  end_char      INTEGER NOT NULL,
  sentence_text TEXT NOT NULL,
  text_hash     TEXT NOT NULL,
  seg_version   TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (stream_id, event_id, sent_index),
  CHECK (sent_index >= 0),
  CHECK (start_char >= 0),
  CHECK (end_char >= start_char)
);

CREATE INDEX IF NOT EXISTS idx_event_sentence_stream_event
  ON event_sentence (stream_id, event_id, sent_index);

CREATE INDEX IF NOT EXISTS idx_event_sentence_stream_event_span
  ON event_sentence (stream_id, event_id, start_char, end_char);

CREATE INDEX IF NOT EXISTS idx_event_sentence_stream_event_hash
  ON event_sentence (stream_id, event_id, text_hash, seg_version);

-- ===== END db/migrations/011_create_event_sentence.sql =====

-- ===== BEGIN db/migrations/012_harden_event_sentence_state_and_range.sql =====
-- Harden event_sentence hash type and add state/range support for scalable incremental runs.

ALTER TABLE event_sentence
  ALTER COLUMN text_hash TYPE CHAR(32)
  USING LEFT(LOWER(COALESCE(text_hash, '')), 32)::CHAR(32);

ALTER TABLE event_sentence
  ADD COLUMN IF NOT EXISTS span_range int4range
  GENERATED ALWAYS AS (int4range(start_char, end_char, '[)')) STORED;

CREATE INDEX IF NOT EXISTS idx_event_sentence_span_range_gist
  ON event_sentence
  USING GIST (span_range);

CREATE TABLE IF NOT EXISTS event_sentence_state (
  stream_id      TEXT NOT NULL,
  event_id       TEXT NOT NULL,
  text_hash      CHAR(32) NOT NULL,
  seg_version    TEXT NOT NULL,
  sentence_count INTEGER NOT NULL DEFAULT 0,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (stream_id, event_id),
  CHECK (sentence_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_event_sentence_state_updated
  ON event_sentence_state (updated_at DESC);

-- ===== END db/migrations/012_harden_event_sentence_state_and_range.sql =====

-- ===== BEGIN db/migrations/013_tighten_event_sentence_hash_and_span.sql =====
-- Tighten hash type/constraints and span invariants.

ALTER TABLE event_sentence
  ALTER COLUMN text_hash TYPE VARCHAR(32)
  USING LOWER(TRIM(COALESCE(text_hash, '')));

ALTER TABLE event_sentence_state
  ALTER COLUMN text_hash TYPE VARCHAR(32)
  USING LOWER(TRIM(COALESCE(text_hash, '')));

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'event_sentence_end_char_ge_start_char_check'
      AND conrelid = 'event_sentence'::regclass
  ) THEN
    ALTER TABLE event_sentence
      DROP CONSTRAINT event_sentence_end_char_ge_start_char_check;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_event_sentence_positive_span'
      AND conrelid = 'event_sentence'::regclass
  ) THEN
    ALTER TABLE event_sentence
      ADD CONSTRAINT ck_event_sentence_positive_span
      CHECK (end_char > start_char);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_event_sentence_hash_hex32'
      AND conrelid = 'event_sentence'::regclass
  ) THEN
    ALTER TABLE event_sentence
      ADD CONSTRAINT ck_event_sentence_hash_hex32
      CHECK (text_hash ~ '^[0-9a-f]{32}$');
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ck_event_sentence_state_hash_hex32'
      AND conrelid = 'event_sentence_state'::regclass
  ) THEN
    ALTER TABLE event_sentence_state
      ADD CONSTRAINT ck_event_sentence_state_hash_hex32
      CHECK (text_hash ~ '^[0-9a-f]{32}$');
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_event_sentence_state_hash
  ON event_sentence_state (text_hash, seg_version);

ALTER TABLE event_sentence
  ADD COLUMN IF NOT EXISTS span int4range
  GENERATED ALWAYS AS (int4range(start_char, end_char, '[)')) STORED;

CREATE INDEX IF NOT EXISTS idx_event_sentence_span_gist
  ON event_sentence
  USING GIST (span);

-- ===== END db/migrations/013_tighten_event_sentence_hash_and_span.sql =====

-- ===== BEGIN db/migrations/016_create_tdb_v2_gateway_core.sql =====
-- TDB V2 Gateway core bootstrap (PR1 scope): event append/read foundation.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS case_seq (
  case_id          UUID PRIMARY KEY,
  next_event_seq   BIGINT NOT NULL,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (next_event_seq > 0)
);

CREATE TABLE IF NOT EXISTS case_event_ledger (
  event_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id          UUID NOT NULL,
  event_seq        BIGINT NOT NULL,
  event_type       TEXT NOT NULL,
  actor_id         UUID,
  subject_id       UUID,
  object_id        UUID,
  payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_time       TIMESTAMPTZ NOT NULL,
  system_time      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (case_id, event_seq)
);

CREATE OR REPLACE FUNCTION tdb_forbid_event_ledger_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'case_event_ledger is append-only: % is not allowed', TG_OP
    USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_case_event_ledger_no_update ON case_event_ledger;
CREATE TRIGGER trg_case_event_ledger_no_update
  BEFORE UPDATE ON case_event_ledger
  FOR EACH ROW
  EXECUTE FUNCTION tdb_forbid_event_ledger_mutation();

DROP TRIGGER IF EXISTS trg_case_event_ledger_no_delete ON case_event_ledger;
CREATE TRIGGER trg_case_event_ledger_no_delete
  BEFORE DELETE ON case_event_ledger
  FOR EACH ROW
  EXECUTE FUNCTION tdb_forbid_event_ledger_mutation();

CREATE INDEX IF NOT EXISTS idx_case_event_ledger_case_seq
  ON case_event_ledger (case_id, event_seq);

CREATE INDEX IF NOT EXISTS idx_case_event_ledger_case_valid_system
  ON case_event_ledger (case_id, valid_time, system_time);

CREATE INDEX IF NOT EXISTS idx_case_event_ledger_type
  ON case_event_ledger (event_type, system_time DESC);

CREATE TABLE IF NOT EXISTS property_state (
  property_state_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  object_id         UUID NOT NULL,
  prop_key          TEXT NOT NULL,
  prop_value        JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_from        TIMESTAMPTZ NOT NULL,
  valid_to          TIMESTAMPTZ,
  system_from       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  system_to         TIMESTAMPTZ,
  source_event_id   UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  confidence        DOUBLE PRECISION,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  CHECK (system_to IS NULL OR system_to > system_from),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

ALTER TABLE property_state
  ADD COLUMN IF NOT EXISTS valid_range tstzrange
  GENERATED ALWAYS AS (
    tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)')
  ) STORED;

ALTER TABLE property_state
  ADD COLUMN IF NOT EXISTS system_range tstzrange
  GENERATED ALWAYS AS (
    tstzrange(system_from, COALESCE(system_to, 'infinity'::timestamptz), '[)')
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_property_state_lookup
  ON property_state (object_id, prop_key, valid_from DESC, system_from DESC);

CREATE INDEX IF NOT EXISTS idx_property_state_open_intervals
  ON property_state (object_id, prop_key)
  WHERE valid_to IS NULL AND system_to IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ex_property_state_bitemporal_overlap'
  ) THEN
    ALTER TABLE property_state
      ADD CONSTRAINT ex_property_state_bitemporal_overlap
      EXCLUDE USING gist (
        object_id WITH =,
        prop_key WITH =,
        valid_range WITH &&,
        system_range WITH &&
      );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS edge_state (
  edge_state_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  src_id            UUID NOT NULL,
  predicate         TEXT NOT NULL,
  dst_id            UUID NOT NULL,
  valid_from        TIMESTAMPTZ NOT NULL,
  valid_to          TIMESTAMPTZ,
  system_from       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  system_to         TIMESTAMPTZ,
  source_event_id   UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  confidence        DOUBLE PRECISION,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  CHECK (system_to IS NULL OR system_to > system_from),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

ALTER TABLE edge_state
  ADD COLUMN IF NOT EXISTS valid_range tstzrange
  GENERATED ALWAYS AS (
    tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)')
  ) STORED;

ALTER TABLE edge_state
  ADD COLUMN IF NOT EXISTS system_range tstzrange
  GENERATED ALWAYS AS (
    tstzrange(system_from, COALESCE(system_to, 'infinity'::timestamptz), '[)')
  ) STORED;

CREATE INDEX IF NOT EXISTS idx_edge_state_lookup
  ON edge_state (src_id, predicate, dst_id, valid_from DESC, system_from DESC);

CREATE INDEX IF NOT EXISTS idx_edge_state_src_asof
  ON edge_state (src_id, valid_from DESC, system_from DESC);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ex_edge_state_bitemporal_overlap'
  ) THEN
    ALTER TABLE edge_state
      ADD CONSTRAINT ex_edge_state_bitemporal_overlap
      EXCLUDE USING gist (
        src_id WITH =,
        predicate WITH =,
        dst_id WITH =,
        valid_range WITH &&,
        system_range WITH &&
      );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS artifact (
  artifact_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_type     TEXT NOT NULL,
  name              TEXT NOT NULL,
  description       TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_artifact_type_created
  ON artifact (artifact_type, created_at DESC);

CREATE TABLE IF NOT EXISTS artifact_version (
  artifact_version_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id         UUID NOT NULL REFERENCES artifact (artifact_id) ON DELETE CASCADE,
  version_number      BIGINT NOT NULL,
  status              TEXT NOT NULL,
  valid_from          TIMESTAMPTZ NOT NULL,
  valid_to            TIMESTAMPTZ,
  system_from         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  system_to           TIMESTAMPTZ,
  content_ref         TEXT NOT NULL,
  content_hash        TEXT,
  author_id           UUID,
  approver_id         UUID,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (artifact_id, version_number),
  CHECK (version_number > 0),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  CHECK (system_to IS NULL OR system_to > system_from)
);

CREATE INDEX IF NOT EXISTS idx_artifact_version_asof_valid
  ON artifact_version (artifact_id, valid_from DESC, version_number DESC);

CREATE INDEX IF NOT EXISTS idx_artifact_version_asof_system
  ON artifact_version (artifact_id, system_from DESC);

CREATE TABLE IF NOT EXISTS rule_def (
  rule_id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key                      TEXT NOT NULL,
  rule_version                  BIGINT NOT NULL,
  severity                      TEXT NOT NULL,
  expression                    TEXT NOT NULL,
  effective_from                TIMESTAMPTZ NOT NULL,
  effective_to                  TIMESTAMPTZ,
  source_artifact_version_id    UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (rule_key, rule_version),
  CHECK (rule_version > 0),
  CHECK (effective_to IS NULL OR effective_to > effective_from)
);

CREATE TABLE IF NOT EXISTS authority_grant (
  authority_grant_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  grantee_id                    UUID NOT NULL,
  action_type                   TEXT NOT NULL,
  scope                         JSONB NOT NULL DEFAULT '{}'::jsonb,
  valid_from                    TIMESTAMPTZ NOT NULL,
  valid_to                      TIMESTAMPTZ,
  system_from                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  system_to                     TIMESTAMPTZ,
  mandate_artifact_version_id   UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  CHECK (system_to IS NULL OR system_to > system_from)
);

CREATE INDEX IF NOT EXISTS idx_authority_grant_asof
  ON authority_grant (grantee_id, action_type, valid_from DESC, system_from DESC);

CREATE TABLE IF NOT EXISTS rule_override (
  rule_override_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_key                          TEXT NOT NULL,
  rule_version                      BIGINT NOT NULL,
  authority_grant_id                UUID NOT NULL REFERENCES authority_grant (authority_grant_id) ON DELETE RESTRICT,
  justification_artifact_version_id UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  valid_from                        TIMESTAMPTZ NOT NULL,
  valid_to                          TIMESTAMPTZ,
  system_from                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  system_to                         TIMESTAMPTZ,
  case_id                           UUID,
  event_id                          UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  created_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (rule_version > 0),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  CHECK (system_to IS NULL OR system_to > system_from)
);

CREATE INDEX IF NOT EXISTS idx_rule_override_asof
  ON rule_override (rule_key, rule_version, valid_from DESC, system_from DESC);

CREATE TABLE IF NOT EXISTS decision_record (
  decision_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id                         UUID NOT NULL,
  event_seq                       BIGINT NOT NULL,
  projection_version              TEXT NOT NULL,
  chosen_action                   TEXT NOT NULL,
  candidates                      JSONB NOT NULL DEFAULT '[]'::jsonb,
  scores                          JSONB NOT NULL DEFAULT '{}'::jsonb,
  constraints_hit                 JSONB NOT NULL DEFAULT '[]'::jsonb,
  detail                          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (case_id, event_seq, projection_version)
);

CREATE TABLE IF NOT EXISTS decision_evidence (
  decision_evidence_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  decision_id                     UUID NOT NULL REFERENCES decision_record (decision_id) ON DELETE CASCADE,
  artifact_version_id             UUID NOT NULL REFERENCES artifact_version (artifact_version_id) ON DELETE RESTRICT,
  citation                        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decision_evidence_decision
  ON decision_evidence (decision_id, created_at DESC);

CREATE TABLE IF NOT EXISTS projection_version (
  projection_version_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  projection_version              TEXT NOT NULL UNIQUE,
  description                     TEXT,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS state_snapshot (
  snapshot_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id                         UUID NOT NULL,
  event_seq                       BIGINT NOT NULL,
  projection_version              TEXT NOT NULL,
  state_blob                      JSONB NOT NULL,
  state_hash                      TEXT,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (case_id, event_seq, projection_version)
);

CREATE INDEX IF NOT EXISTS idx_state_snapshot_latest
  ON state_snapshot (case_id, projection_version, event_seq DESC);

-- ===== END db/migrations/016_create_tdb_v2_gateway_core.sql =====

-- ===== BEGIN db/migrations/017_tdb_v2_p1_indexes.sql =====
-- TDB V2 P1: query/index hardening for governance and state as-of paths.

CREATE INDEX IF NOT EXISTS idx_rule_def_asof
  ON rule_def (rule_key, rule_version, effective_from DESC, effective_to);

CREATE INDEX IF NOT EXISTS idx_authority_grant_scope_gin
  ON authority_grant
  USING GIN (scope);

CREATE INDEX IF NOT EXISTS idx_edge_state_src_pred_asof
  ON edge_state (src_id, predicate, valid_from DESC, system_from DESC);

-- ===== END db/migrations/017_tdb_v2_p1_indexes.sql =====

-- ===== BEGIN db/migrations/018_add_case_context_and_stream_mapping.sql =====
-- V2: stream -> case mapping for event append and replay boundaries.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS case_context (
  case_id       UUID PRIMARY KEY,
  stream_id     TEXT NOT NULL,
  title         TEXT NOT NULL DEFAULT '',
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (stream_id, case_id)
);

CREATE INDEX IF NOT EXISTS idx_case_context_stream
  ON case_context (stream_id, updated_at DESC);

-- ===== END db/migrations/018_add_case_context_and_stream_mapping.sql =====

-- ===== BEGIN db/migrations/019_add_v2_search_projection.sql =====
-- V2 search projection tables (no V1 table dependency)
-- Fact tables remain source-of-truth; search tables are rebuildable projections.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS search_document (
  doc_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id         UUID NOT NULL,
  stream_id       TEXT,
  event_id        UUID NOT NULL REFERENCES case_event_ledger (event_id) ON DELETE CASCADE,
  event_seq       BIGINT NOT NULL,
  content         TEXT NOT NULL,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS idx_search_document_case_seq
  ON search_document (case_id, event_seq DESC);

CREATE INDEX IF NOT EXISTS idx_search_document_stream_seq
  ON search_document (stream_id, event_seq DESC)
  WHERE stream_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_search_document_tsv
  ON search_document USING GIN (to_tsvector('simple', content));

CREATE INDEX IF NOT EXISTS idx_search_document_trgm
  ON search_document USING GIN (content gin_trgm_ops);

CREATE TABLE IF NOT EXISTS search_embedding (
  doc_id            UUID PRIMARY KEY REFERENCES search_document (doc_id) ON DELETE CASCADE,
  embedding         vector NOT NULL,
  embedding_model   TEXT,
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_search_embedding_updated
  ON search_embedding (updated_at DESC);

-- ===== END db/migrations/019_add_v2_search_projection.sql =====

-- ===== BEGIN db/migrations/020_add_entity_catalog.sql =====
-- Minimal enterprise entity catalog for V2 governance/explainability.
-- This table is intentionally weakly-coupled (no mandatory FK from fact/state tables).

CREATE TABLE IF NOT EXISTS entity (
  entity_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type     TEXT NOT NULL,
  display_name    TEXT NOT NULL,
  external_refs   JSONB NOT NULL DEFAULT '{}'::jsonb,
  status          TEXT NOT NULL DEFAULT 'active',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (status IN ('active', 'inactive', 'deleted'))
);

CREATE INDEX IF NOT EXISTS idx_entity_type_status_updated
  ON entity (entity_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_entity_display_name
  ON entity (display_name);

CREATE INDEX IF NOT EXISTS idx_entity_external_refs_gin
  ON entity USING GIN (external_refs);

-- ===== END db/migrations/020_add_entity_catalog.sql =====
