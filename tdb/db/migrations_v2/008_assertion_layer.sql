-- Assertion layer for evidence-backed, non-ontology-stable claims.
-- Goal:
-- 1) Add a first-class ledger-layer assertion object.
-- 2) Keep evidence-bearing assertions separate from ontology_fact.
-- 3) Support assertion-to-evidence and assertion-to-assertion lineage.

CREATE TABLE IF NOT EXISTS assertion (
  assertion_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id                    UUID,
  subject_type               TEXT NOT NULL,
  subject_id                 UUID NOT NULL,
  predicate                  TEXT NOT NULL,
  object_type                TEXT NOT NULL,
  object_id                  UUID,
  object_literal             JSONB,
  assertion_type             TEXT NOT NULL,
  asserted_by_type           TEXT NOT NULL,
  asserted_by_id             TEXT NOT NULL DEFAULT '',
  confidence                 DOUBLE PRECISION,
  status                     TEXT NOT NULL DEFAULT 'active',
  methodology_framework_id   UUID REFERENCES methodology_framework (framework_id) ON DELETE SET NULL,
  source_event_id            UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  metadata                   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (subject_type IN ('artifact', 'component', 'inscription', 'provenance_event', 'test_report')),
  CHECK (predicate <> ''),
  CHECK (object_type IN ('vocabulary_term', 'entity', 'literal', 'range', 'probability_distribution')),
  CHECK (assertion_type IN ('observation', 'classification', 'hypothesis', 'dispute', 'correction', 'consensus')),
  CHECK (asserted_by_type IN ('human', 'model', 'rule_engine', 'import_pipeline')),
  CHECK (status IN ('active', 'disputed', 'superseded', 'retracted', 'archived')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  CHECK (
    (object_type = 'entity' AND object_id IS NOT NULL)
    OR
    (object_type IN ('vocabulary_term', 'literal', 'range', 'probability_distribution') AND object_literal IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_assertion_subject
  ON assertion (subject_type, subject_id, predicate, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_assertion_framework
  ON assertion (methodology_framework_id, assertion_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_assertion_case
  ON assertion (case_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assertion_source_event
  ON assertion (source_event_id, created_at DESC)
  WHERE source_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS assertion_evidence_link (
  assertion_evidence_link_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assertion_id                UUID NOT NULL REFERENCES assertion (assertion_id) ON DELETE CASCADE,
  artifact_version_id         UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  event_id                    UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  memory_decision_id          UUID REFERENCES memory_decision_record (memory_decision_id) ON DELETE SET NULL,
  support_type                TEXT NOT NULL DEFAULT 'supports',
  weight                      DOUBLE PRECISION,
  note                        TEXT NOT NULL DEFAULT '',
  evidence_json               JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (support_type IN ('supports', 'contradicts', 'weakly_supports', 'context_only')),
  CHECK (weight IS NULL OR (weight >= 0.0 AND weight <= 1.0)),
  CHECK (
    artifact_version_id IS NOT NULL
    OR event_id IS NOT NULL
    OR memory_decision_id IS NOT NULL
  )
);

CREATE INDEX IF NOT EXISTS idx_assertion_evidence_assertion
  ON assertion_evidence_link (assertion_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assertion_evidence_artifact
  ON assertion_evidence_link (artifact_version_id)
  WHERE artifact_version_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assertion_evidence_event
  ON assertion_evidence_link (event_id)
  WHERE event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_assertion_evidence_memory_decision
  ON assertion_evidence_link (memory_decision_id)
  WHERE memory_decision_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS assertion_relation (
  assertion_relation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_assertion_id           UUID NOT NULL REFERENCES assertion (assertion_id) ON DELETE CASCADE,
  to_assertion_id             UUID NOT NULL REFERENCES assertion (assertion_id) ON DELETE CASCADE,
  relation_type               TEXT NOT NULL,
  metadata                    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (relation_type IN ('contradicts', 'supersedes', 'refines', 'aggregates', 'consensus_of')),
  CHECK (from_assertion_id <> to_assertion_id)
);

CREATE INDEX IF NOT EXISTS idx_assertion_relation_from
  ON assertion_relation (from_assertion_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_assertion_relation_to
  ON assertion_relation (to_assertion_id, created_at DESC);
