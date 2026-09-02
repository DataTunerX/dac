-- TDB V2 ontology/ops extension schema
-- Apply after 001_v2_baseline.sql when ontology governance workflows are required.

-- ===== BEGIN db/migrations/005_create_ontology.sql =====
-- Ontology layer for semantic normalization across sessions.
-- NOTE:
-- ontology_edge predicate validation must remain replay-safe for existing
-- databases that already contain domain-specific predicates. The final desired
-- invariant is a sane snake_case predicate shape, not a tiny hard-coded enum.

CREATE TABLE IF NOT EXISTS ontology_concept (
  concept_id       TEXT PRIMARY KEY,
  canonical_name   TEXT NOT NULL,
  concept_type     TEXT NOT NULL,
  aliases          JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (concept_type IN ('entity', 'event', 'session', 'time', 'topic', 'phrase'))
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ontology_concept_concept_type_check'
      AND conrelid = 'ontology_concept'::regclass
  ) THEN
    ALTER TABLE ontology_concept
      DROP CONSTRAINT ontology_concept_concept_type_check;
  END IF;
  BEGIN
    ALTER TABLE ontology_concept
      ADD CONSTRAINT ontology_concept_concept_type_check
      CHECK (
        concept_type IN (
          'entity', 'event', 'session', 'time', 'topic', 'phrase', 'location', 'activity'
        )
      );
  EXCEPTION
    WHEN duplicate_object THEN
      NULL;
  END;
END $$;

CREATE INDEX IF NOT EXISTS idx_ontology_concept_canonical
  ON ontology_concept (canonical_name);

CREATE TABLE IF NOT EXISTS ontology_edge (
  src_concept_id   TEXT NOT NULL,
  predicate        TEXT NOT NULL,
  dst_concept_id   TEXT NOT NULL,
  weight           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (src_concept_id, predicate, dst_concept_id),
  FOREIGN KEY (src_concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  FOREIGN KEY (dst_concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  CHECK (weight > 0.0),
  CHECK (predicate IN ('same_as', 'is_a', 'part_of', 'related_to', 'broader_than', 'narrower_than'))
);

DO $$
DECLARE rec RECORD;
BEGIN
  FOR rec IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'ontology_edge'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%predicate%'
  LOOP
    EXECUTE format('ALTER TABLE ontology_edge DROP CONSTRAINT IF EXISTS %I', rec.conname);
  END LOOP;
  BEGIN
    ALTER TABLE ontology_edge
      ADD CONSTRAINT ck_ontology_edge_predicate
      CHECK (predicate ~ '^[a-z][a-z0-9_]*$');
  EXCEPTION
    WHEN duplicate_object THEN
      NULL;
  END;
END $$;

CREATE INDEX IF NOT EXISTS idx_ontology_edge_src_pred
  ON ontology_edge (src_concept_id, predicate);

CREATE INDEX IF NOT EXISTS idx_ontology_edge_dst_pred
  ON ontology_edge (dst_concept_id, predicate);

CREATE TABLE IF NOT EXISTS event_concept_link (
  stream_id        TEXT NOT NULL,
  event_id         TEXT NOT NULL,
  concept_id       TEXT NOT NULL,
  role             TEXT NOT NULL,
  confidence       DOUBLE PRECISION NOT NULL,
  asset_id         TEXT,
  version_number   BIGINT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (stream_id, event_id, concept_id, role),
  FOREIGN KEY (concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  CHECK (confidence >= 0.0 AND confidence <= 1.0),
  CHECK (role IN ('subject', 'predicate', 'object', 'topic', 'session', 'time', 'other')),
  CHECK (
    (asset_id IS NULL AND version_number IS NULL)
    OR
    (asset_id IS NOT NULL AND version_number IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_event_concept_link_stream_event
  ON event_concept_link (stream_id, event_id);

CREATE INDEX IF NOT EXISTS idx_event_concept_link_concept
  ON event_concept_link (concept_id);

-- ===== END db/migrations/005_create_ontology.sql =====

-- ===== BEGIN db/migrations/006_extend_ontology_extraction_schema.sql =====
-- Extend ontology extraction protocol to support rule/LLM provenance.

ALTER TABLE event_concept_link
  ADD COLUMN IF NOT EXISTS extractor TEXT NOT NULL DEFAULT 'rule_v1',
  ADD COLUMN IF NOT EXISTS source_span TEXT,
  ADD COLUMN IF NOT EXISTS evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE event_concept_link
  DROP CONSTRAINT IF EXISTS ck_event_concept_link_extractor;

ALTER TABLE event_concept_link
  ADD CONSTRAINT ck_event_concept_link_extractor
  CHECK (extractor IN ('rule_v1', 'rule_v2', 'llm_v1', 'llm_v2', 'hybrid', 'controlled_v1'));

CREATE TABLE IF NOT EXISTS concept_alias (
  concept_id       TEXT NOT NULL,
  alias_text       TEXT NOT NULL,
  confidence       DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  extractor        TEXT NOT NULL DEFAULT 'rule_v1',
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (concept_id, alias_text),
  FOREIGN KEY (concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  CHECK (confidence >= 0.0 AND confidence <= 1.0),
  CHECK (extractor IN ('rule_v1', 'rule_v2', 'llm_v1', 'llm_v2', 'hybrid', 'controlled_v1'))
);

ALTER TABLE concept_alias
  DROP CONSTRAINT IF EXISTS concept_alias_extractor_check;

ALTER TABLE concept_alias
  ADD CONSTRAINT concept_alias_extractor_check
  CHECK (extractor IN ('rule_v1', 'rule_v2', 'llm_v1', 'llm_v2', 'hybrid', 'controlled_v1'));

CREATE INDEX IF NOT EXISTS idx_concept_alias_alias_text
  ON concept_alias (alias_text);

-- ===== END db/migrations/006_extend_ontology_extraction_schema.sql =====

-- ===== BEGIN db/migrations/007_create_ontology_v2_schema.sql =====
-- Ontology Schema V2 (Palantir-like foundation)
-- Goal:
-- 1) Add explicit type registries for objects/relations.
-- 2) Add normalized fact table with lifecycle/review fields.
-- 3) Add fact-evidence links for provenance.
-- 4) Keep existing ontology_concept / ontology_edge / event_concept_link untouched.

CREATE TABLE IF NOT EXISTS ontology_object_type (
  type_id          TEXT PRIMARY KEY,
  display_name     TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  enabled          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ontology_relation_type (
  predicate        TEXT PRIMARY KEY,
  src_type_id      TEXT NOT NULL,
  dst_type_id      TEXT NOT NULL,
  display_name     TEXT NOT NULL,
  description      TEXT NOT NULL DEFAULT '',
  is_symmetric     BOOLEAN NOT NULL DEFAULT FALSE,
  is_transitive    BOOLEAN NOT NULL DEFAULT FALSE,
  enabled          BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (src_type_id) REFERENCES ontology_object_type (type_id),
  FOREIGN KEY (dst_type_id) REFERENCES ontology_object_type (type_id)
);

CREATE TABLE IF NOT EXISTS ontology_fact (
  fact_id              BIGSERIAL PRIMARY KEY,
  src_concept_id       TEXT NOT NULL,
  predicate            TEXT NOT NULL,
  dst_concept_id       TEXT NOT NULL,
  qualifier_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence           DOUBLE PRECISION NOT NULL DEFAULT 0.0,
  extractor            TEXT NOT NULL DEFAULT 'rule_v1',
  status               TEXT NOT NULL DEFAULT 'accepted',
  review_note          TEXT NOT NULL DEFAULT '',
  valid_from           TIMESTAMPTZ,
  valid_to             TIMESTAMPTZ,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (src_concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  FOREIGN KEY (dst_concept_id) REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  FOREIGN KEY (predicate) REFERENCES ontology_relation_type (predicate),
  CHECK (confidence >= 0.0 AND confidence <= 1.0),
  CHECK (status IN ('accepted', 'candidate', 'rejected', 'needs_review')),
  CHECK (
    valid_to IS NULL
    OR valid_from IS NULL
    OR valid_to > valid_from
  )
);

CREATE INDEX IF NOT EXISTS idx_ontology_fact_src_pred
  ON ontology_fact (src_concept_id, predicate);

CREATE INDEX IF NOT EXISTS idx_ontology_fact_dst_pred
  ON ontology_fact (dst_concept_id, predicate);

CREATE INDEX IF NOT EXISTS idx_ontology_fact_status
  ON ontology_fact (status, confidence DESC, updated_at DESC);

CREATE TABLE IF NOT EXISTS ontology_fact_evidence (
  fact_id              BIGINT NOT NULL,
  stream_id            TEXT NOT NULL,
  event_id             TEXT NOT NULL,
  asset_id             TEXT,
  version_number       BIGINT,
  source_span          TEXT,
  evidence_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
  confidence           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (fact_id, stream_id, event_id),
  FOREIGN KEY (fact_id) REFERENCES ontology_fact (fact_id) ON DELETE CASCADE,
  CHECK (confidence >= 0.0 AND confidence <= 1.0),
  CHECK (
    (asset_id IS NULL AND version_number IS NULL)
    OR
    (asset_id IS NOT NULL AND version_number IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_fact_evidence_stream_event
  ON ontology_fact_evidence (stream_id, event_id);

CREATE INDEX IF NOT EXISTS idx_fact_evidence_fact
  ON ontology_fact_evidence (fact_id);

CREATE TABLE IF NOT EXISTS ontology_fact_review (
  review_id             BIGSERIAL PRIMARY KEY,
  fact_id               BIGINT NOT NULL,
  reviewer              TEXT NOT NULL,
  decision              TEXT NOT NULL,
  note                  TEXT NOT NULL DEFAULT '',
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (fact_id) REFERENCES ontology_fact (fact_id) ON DELETE CASCADE,
  CHECK (decision IN ('accept', 'reject', 'needs_work'))
);

CREATE INDEX IF NOT EXISTS idx_fact_review_fact
  ON ontology_fact_review (fact_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ontology_registry_load (
  load_id               BIGSERIAL PRIMARY KEY,
  registry_name         TEXT NOT NULL,
  registry_version      INTEGER,
  source_path           TEXT NOT NULL,
  predicate_count       INTEGER NOT NULL,
  payload_hash          TEXT NOT NULL,
  payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  loaded_by             TEXT NOT NULL DEFAULT '',
  loaded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (predicate_count >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ontology_registry_load_name_time
  ON ontology_registry_load (registry_name, loaded_at DESC);

INSERT INTO ontology_object_type (type_id, display_name, description)
VALUES
  ('entity', 'Entity', 'People, places, organizations, and concrete entities'),
  ('location', 'Location', 'Geographic or place concepts'),
  ('activity', 'Activity', 'Action/activity concepts'),
  ('event', 'Event', 'Happened or planned events'),
  ('session', 'Session', 'Conversation/session scope anchor'),
  ('time', 'Time', 'Temporal concepts and normalized time expressions'),
  ('topic', 'Topic', 'Abstract topical concepts'),
  ('phrase', 'Phrase', 'Phrase-level textual concepts')
ON CONFLICT (type_id) DO NOTHING;

INSERT INTO ontology_relation_type (
  predicate, src_type_id, dst_type_id, display_name, description, is_symmetric, is_transitive
)
VALUES
  ('same_as', 'phrase', 'topic', 'Same As', 'Canonical equivalence / normalization link', TRUE, TRUE),
  ('is_a', 'entity', 'topic', 'Is A', 'Type/hypernym relationship', FALSE, TRUE),
  ('part_of', 'entity', 'entity', 'Part Of', 'Part-whole relationship', FALSE, TRUE),
  ('broader_than', 'entity', 'entity', 'Broader Than', 'Taxonomy broader-parent relationship', FALSE, TRUE),
  ('narrower_than', 'entity', 'entity', 'Narrower Than', 'Taxonomy narrower-child relationship', FALSE, TRUE),
  ('related_to', 'topic', 'topic', 'Related To', 'General semantic association', TRUE, FALSE),
  ('participates_in', 'entity', 'activity', 'Participates In', 'Entity participates in an activity', FALSE, FALSE),
  ('occurs_at', 'activity', 'location', 'Occurs At', 'Activity occurs at a location', FALSE, FALSE),
  ('happens_when', 'activity', 'time', 'Happens When', 'Activity occurs at a time', FALSE, FALSE),
  ('associated_with_place', 'entity', 'location', 'Associated With Place', 'Entity associated with a place', FALSE, FALSE),
  ('has_birthday_on', 'entity', 'time', 'Has Birthday On', 'Entity birthday date (month/day) fact', FALSE, FALSE),
  ('has_home_country', 'entity', 'location', 'Has Home Country', 'Entity home country fact', FALSE, FALSE),
  ('has_hometown', 'entity', 'location', 'Has Hometown', 'Entity hometown fact', FALSE, FALSE),
  ('born_in', 'entity', 'location', 'Born In', 'Entity birthplace fact', FALSE, FALSE)
ON CONFLICT (predicate) DO NOTHING;

-- ===== END db/migrations/007_create_ontology_v2_schema.sql =====

-- ===== BEGIN db/migrations/008_create_ontology_ops_schema.sql =====
-- PR-F: operation layer for ontology governance (case + alert workflow).

CREATE TABLE IF NOT EXISTS ontology_case (
  case_id            BIGSERIAL PRIMARY KEY,
  stream_id          TEXT NOT NULL,
  title              TEXT NOT NULL,
  description        TEXT NOT NULL DEFAULT '',
  status             TEXT NOT NULL DEFAULT 'open',
  priority           TEXT NOT NULL DEFAULT 'p2',
  owner              TEXT NOT NULL DEFAULT '',
  created_by         TEXT NOT NULL DEFAULT '',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at          TIMESTAMPTZ,
  CHECK (status IN ('open', 'in_review', 'resolved', 'dismissed')),
  CHECK (priority IN ('p1', 'p2', 'p3'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_case_stream_status
  ON ontology_case (stream_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS ontology_case_fact (
  case_id            BIGINT NOT NULL,
  fact_id            BIGINT NOT NULL,
  added_by           TEXT NOT NULL DEFAULT '',
  added_note         TEXT NOT NULL DEFAULT '',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (case_id, fact_id),
  FOREIGN KEY (case_id) REFERENCES ontology_case (case_id) ON DELETE CASCADE,
  FOREIGN KEY (fact_id) REFERENCES ontology_fact (fact_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ontology_case_fact_fact
  ON ontology_case_fact (fact_id);

CREATE TABLE IF NOT EXISTS ontology_case_event (
  event_id           BIGSERIAL PRIMARY KEY,
  case_id            BIGINT NOT NULL,
  action             TEXT NOT NULL,
  actor              TEXT NOT NULL DEFAULT '',
  note               TEXT NOT NULL DEFAULT '',
  payload_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  FOREIGN KEY (case_id) REFERENCES ontology_case (case_id) ON DELETE CASCADE,
  CHECK (action IN ('open', 'status_change', 'owner_change', 'fact_link', 'note', 'alert_link'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_case_event_case
  ON ontology_case_event (case_id, created_at DESC);

CREATE TABLE IF NOT EXISTS ontology_alert (
  alert_id           BIGSERIAL PRIMARY KEY,
  case_id            BIGINT,
  stream_id          TEXT NOT NULL,
  severity           TEXT NOT NULL DEFAULT 'medium',
  status             TEXT NOT NULL DEFAULT 'open',
  message            TEXT NOT NULL,
  detail_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  acked_by           TEXT,
  acked_at           TIMESTAMPTZ,
  closed_at          TIMESTAMPTZ,
  FOREIGN KEY (case_id) REFERENCES ontology_case (case_id) ON DELETE SET NULL,
  CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  CHECK (status IN ('open', 'acked', 'closed'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_alert_stream_status
  ON ontology_alert (stream_id, status, severity, updated_at DESC);

-- ===== END db/migrations/008_create_ontology_ops_schema.sql =====

-- ===== BEGIN db/migrations/009_extend_ontology_alert_ops.sql =====
-- PR-F enhancement: alert<->fact linkage and rule-trigger state.

ALTER TABLE ontology_alert
  ADD COLUMN IF NOT EXISTS rule_key TEXT,
  ADD COLUMN IF NOT EXISTS trigger_count INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS first_triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS last_triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

UPDATE ontology_alert
SET rule_key = NULLIF(detail_json->>'rule_key', '')
WHERE (rule_key IS NULL OR rule_key = '')
  AND detail_json ? 'rule_key';

CREATE INDEX IF NOT EXISTS idx_ontology_alert_rule_key
  ON ontology_alert (rule_key);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_alert_active_rule
  ON ontology_alert (stream_id, rule_key)
  WHERE rule_key IS NOT NULL
    AND status IN ('open', 'acked');

CREATE TABLE IF NOT EXISTS ontology_alert_fact (
  alert_id           BIGINT NOT NULL,
  fact_id            BIGINT NOT NULL,
  linked_by          TEXT NOT NULL DEFAULT '',
  linked_note        TEXT NOT NULL DEFAULT '',
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (alert_id, fact_id),
  FOREIGN KEY (alert_id) REFERENCES ontology_alert (alert_id) ON DELETE CASCADE,
  FOREIGN KEY (fact_id) REFERENCES ontology_fact (fact_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ontology_alert_fact_fact
  ON ontology_alert_fact (fact_id);

-- ===== END db/migrations/009_extend_ontology_alert_ops.sql =====

-- ===== BEGIN db/migrations/010_create_ontology_ops_run_ledger.sql =====
-- PR-F++: operation-rule run ledger and configuration table.

CREATE TABLE IF NOT EXISTS ontology_ops_rule_config (
  config_id          BIGSERIAL PRIMARY KEY,
  stream_id          TEXT,
  rule_name          TEXT NOT NULL,
  enabled            BOOLEAN NOT NULL DEFAULT TRUE,
  stale_days         INTEGER,
  conflict_predicate TEXT,
  severity           TEXT,
  note               TEXT NOT NULL DEFAULT '',
  updated_by         TEXT NOT NULL DEFAULT '',
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (rule_name IN ('default', 'stale_pending', 'conflict_predicate')),
  CHECK (severity IS NULL OR severity IN ('low', 'medium', 'high', 'critical')),
  CHECK (stale_days IS NULL OR stale_days > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ontology_ops_rule_config_scope
  ON ontology_ops_rule_config (COALESCE(stream_id, ''), rule_name);

CREATE TABLE IF NOT EXISTS ontology_ops_rule_run (
  run_id                BIGSERIAL PRIMARY KEY,
  stream_id_filter      TEXT,
  stale_days            INTEGER NOT NULL,
  conflict_predicate    TEXT NOT NULL,
  dry_run               BOOLEAN NOT NULL DEFAULT TRUE,
  candidate_count       INTEGER NOT NULL DEFAULT 0,
  created_case_count    INTEGER NOT NULL DEFAULT 0,
  existing_case_count   INTEGER NOT NULL DEFAULT 0,
  created_alert_count   INTEGER NOT NULL DEFAULT 0,
  existing_alert_count  INTEGER NOT NULL DEFAULT 0,
  payload_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  duration_ms           BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ontology_ops_rule_run_started
  ON ontology_ops_rule_run (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_ops_rule_run_stream
  ON ontology_ops_rule_run (stream_id_filter, started_at DESC);

-- ===== END db/migrations/010_create_ontology_ops_run_ledger.sql =====

-- ===== BEGIN db/migrations/014_index_fact_evidence_span_contract.sql =====
-- Optional governance/ops indexes for evidence_json span contract fields.

DROP INDEX IF EXISTS idx_fact_evidence_event_sentence;
CREATE INDEX IF NOT EXISTS idx_fact_evidence_event_sentence
ON ontology_fact_evidence (
  stream_id,
  event_id,
  ((evidence_json->>'sent_index')::int)
)
WHERE evidence_json ? 'sent_index'
  AND (evidence_json->>'sent_index') ~ '^-?[0-9]+$';

DROP INDEX IF EXISTS idx_fact_evidence_hash_ver;
CREATE INDEX IF NOT EXISTS idx_fact_evidence_hash_ver
ON ontology_fact_evidence (
  (evidence_json->>'text_hash'),
  (evidence_json->>'seg_version')
)
WHERE evidence_json ? 'text_hash'
  AND evidence_json ? 'seg_version';

-- ===== END db/migrations/014_index_fact_evidence_span_contract.sql =====

-- ===== BEGIN db/migrations/015_extend_ontology_relation_type_registry.sql =====
BEGIN;

ALTER TABLE ontology_relation_type
  ADD COLUMN IF NOT EXISTS min_confidence DOUBLE PRECISION,
  ADD COLUMN IF NOT EXISTS registry_load_id BIGINT,
  ADD COLUMN IF NOT EXISTS managed_by_registry BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS auto_promote BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS min_evidence_count INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS min_distinct_event_count INTEGER NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS allow_cross_sentence BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS require_span_contract BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS require_located BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS min_overlap_chars INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS max_covered_sentence_count INTEGER NOT NULL DEFAULT 999999,
  ADD COLUMN IF NOT EXISTS conflict_key TEXT NOT NULL DEFAULT 'src_predicate',
  ADD COLUMN IF NOT EXISTS conflict_policy TEXT NOT NULL DEFAULT 'block_promotion',
  ADD COLUMN IF NOT EXISTS conflict_create_case BOOLEAN NOT NULL DEFAULT true,
  ADD COLUMN IF NOT EXISTS conflict_case_priority TEXT NOT NULL DEFAULT 'p2',
  ADD COLUMN IF NOT EXISTS conflict_alert_severity TEXT NOT NULL DEFAULT 'medium';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'fk_ort_registry_load_id'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT fk_ort_registry_load_id
      FOREIGN KEY (registry_load_id) REFERENCES ontology_registry_load (load_id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_min_confidence'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_min_confidence
      CHECK (min_confidence IS NULL OR (min_confidence >= 0.0 AND min_confidence <= 1.0));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_min_evidence_count'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_min_evidence_count
      CHECK (min_evidence_count >= 1);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_min_distinct_event_count'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_min_distinct_event_count
      CHECK (min_distinct_event_count >= 1);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_min_overlap_chars'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_min_overlap_chars
      CHECK (min_overlap_chars >= 0);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_max_covered_sentence_count'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_max_covered_sentence_count
      CHECK (max_covered_sentence_count >= 1);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_conflict_key'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_conflict_key
      CHECK (conflict_key IN ('src_predicate', 'src_predicate_dst'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_conflict_policy'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_conflict_policy
      CHECK (conflict_policy IN ('block_promotion', 'allow_multi', 'latest_wins'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_case_priority'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_case_priority
      CHECK (conflict_case_priority IN ('p1', 'p2', 'p3'));
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'ck_ort_alert_severity'
  ) THEN
    ALTER TABLE ontology_relation_type
      ADD CONSTRAINT ck_ort_alert_severity
      CHECK (conflict_alert_severity IN ('low', 'medium', 'high', 'critical'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ort_enabled_auto_promote
  ON ontology_relation_type (enabled, auto_promote);

CREATE INDEX IF NOT EXISTS idx_ort_predicate_rules
  ON ontology_relation_type (predicate, enabled, auto_promote);

CREATE INDEX IF NOT EXISTS idx_ort_registry_load
  ON ontology_relation_type (registry_load_id, managed_by_registry);

COMMIT;

-- ===== END db/migrations/015_extend_ontology_relation_type_registry.sql =====
