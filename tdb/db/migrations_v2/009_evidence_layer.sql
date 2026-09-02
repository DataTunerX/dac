-- Evidence layer for first-class, ledger-native evidence units.
-- Goal:
-- 1) Lift evidence units above raw carrier objects like artifact_version / event_sentence.
-- 2) Make assertions, reviews, and governance point to explicit evidence objects.
-- 3) Separate evidence identity, location, derivation, and qualification.

CREATE TABLE IF NOT EXISTS evidence_record (
  evidence_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id                     UUID,
  event_seq                   BIGINT,
  source_kind                 TEXT NOT NULL,
  source_id                   TEXT NOT NULL,
  artifact_version_id         UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  evidence_type               TEXT NOT NULL,
  evidence_role               TEXT NOT NULL DEFAULT 'primary',
  methodology_framework_id    UUID REFERENCES methodology_framework (framework_id) ON DELETE SET NULL,
  evidence_payload            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by_type             TEXT NOT NULL,
  created_by_id               TEXT NOT NULL DEFAULT '',
  is_derived                  BOOLEAN NOT NULL DEFAULT FALSE,
  status                      TEXT NOT NULL DEFAULT 'active',
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (event_seq IS NULL OR event_seq > 0),
  CHECK (source_kind IN (
    'artifact_version',
    'event_sentence',
    'property_state',
    'edge_state',
    'external_report',
    'measurement',
    'image_region',
    'model_observation'
  )),
  CHECK (source_id <> ''),
  CHECK (evidence_type IN (
    'text_span',
    'image_region',
    'measurement',
    'lab_result',
    'provenance_record',
    'expert_note',
    'model_observation'
  )),
  CHECK (evidence_role IN ('primary', 'derived', 'summary', 'citation', 'contradiction_candidate')),
  CHECK (created_by_type IN ('human', 'model', 'rule_engine', 'import_pipeline', 'system')),
  CHECK (status IN ('active', 'superseded', 'retracted', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_record_case_event
  ON evidence_record (case_id, event_seq, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_record_source
  ON evidence_record (source_kind, source_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_record_artifact_version
  ON evidence_record (artifact_version_id)
  WHERE artifact_version_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_record_framework
  ON evidence_record (methodology_framework_id, evidence_type, evidence_role, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS evidence_locator (
  evidence_locator_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  evidence_id                 UUID NOT NULL REFERENCES evidence_record (evidence_id) ON DELETE CASCADE,
  locator_type                TEXT NOT NULL,
  page_span                   int4range,
  char_span                   int4range,
  sentence_ref                JSONB,
  bbox                        JSONB,
  polygon                     JSONB,
  time_range                  tstzrange,
  table_cell                  JSONB,
  measurement_field           TEXT,
  locator_payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
  normalized_text             TEXT,
  preview_text                TEXT,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (locator_type IN (
    'page_span',
    'char_span',
    'sentence_ref',
    'bbox',
    'polygon',
    'time_range',
    'table_cell',
    'measurement_field',
    'custom'
  ))
);

CREATE INDEX IF NOT EXISTS idx_evidence_locator_evidence
  ON evidence_locator (evidence_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_locator_page_span
  ON evidence_locator USING GIST (page_span)
  WHERE page_span IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_locator_char_span
  ON evidence_locator USING GIST (char_span)
  WHERE char_span IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_evidence_locator_time_range
  ON evidence_locator USING GIST (time_range)
  WHERE time_range IS NOT NULL;

CREATE TABLE IF NOT EXISTS evidence_derivation (
  evidence_derivation_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  child_evidence_id           UUID NOT NULL REFERENCES evidence_record (evidence_id) ON DELETE CASCADE,
  parent_evidence_id          UUID NOT NULL REFERENCES evidence_record (evidence_id) ON DELETE CASCADE,
  derivation_type             TEXT NOT NULL,
  method                      TEXT NOT NULL DEFAULT '',
  run_id                      TEXT NOT NULL DEFAULT '',
  artifact_version_id         UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  derivation_metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (derivation_type IN (
    'extracted_from',
    'summarized_from',
    'translated_from',
    'cropped_from',
    'interpreted_from',
    'normalized_from'
  )),
  CHECK (child_evidence_id <> parent_evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_derivation_child
  ON evidence_derivation (child_evidence_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_derivation_parent
  ON evidence_derivation (parent_evidence_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_derivation_artifact_version
  ON evidence_derivation (artifact_version_id)
  WHERE artifact_version_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS evidence_classification (
  evidence_id                  UUID PRIMARY KEY REFERENCES evidence_record (evidence_id) ON DELETE CASCADE,
  source_reliability_tier      TEXT NOT NULL DEFAULT '',
  evidence_strength_tier       TEXT NOT NULL DEFAULT '',
  evidence_modality            TEXT NOT NULL DEFAULT '',
  institutional_trust_class    TEXT NOT NULL DEFAULT '',
  is_primary_source            BOOLEAN NOT NULL DEFAULT FALSE,
  is_machine_generated         BOOLEAN NOT NULL DEFAULT FALSE,
  requires_human_validation    BOOLEAN NOT NULL DEFAULT FALSE,
  methodology_framework_id     UUID REFERENCES methodology_framework (framework_id) ON DELETE SET NULL,
  classification_status        TEXT NOT NULL DEFAULT 'draft',
  metadata                     JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (classification_status IN ('draft', 'reviewed', 'accepted', 'superseded'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_classification_framework
  ON evidence_classification (methodology_framework_id, classification_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_classification_qualification
  ON evidence_classification (
    source_reliability_tier,
    evidence_strength_tier,
    evidence_modality,
    institutional_trust_class
  );
