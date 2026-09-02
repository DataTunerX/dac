-- Ontology raw-term ingestion layer.
-- Provides a first-class ingestion inbox between evidence/dossiers and ontology_concept.

CREATE TABLE IF NOT EXISTS ontology_raw_term (
  raw_term_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain                    TEXT NOT NULL,
  raw_term                  TEXT NOT NULL,
  language                  TEXT NOT NULL DEFAULT 'zh',
  normalized_hint           TEXT NOT NULL DEFAULT '',
  term_type_hint            TEXT NOT NULL DEFAULT '',
  source_kind               TEXT NOT NULL,
  source_ref                TEXT NOT NULL DEFAULT '',
  artifact_version_id       UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  evidence_id               UUID REFERENCES evidence_record (evidence_id) ON DELETE SET NULL,
  context_text              TEXT NOT NULL DEFAULT '',
  context_locator_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  extracted_by_type         TEXT NOT NULL,
  extracted_by_id           TEXT NOT NULL DEFAULT '',
  status                    TEXT NOT NULL DEFAULT 'new',
  metadata_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(domain) <> ''),
  CHECK (btrim(raw_term) <> ''),
  CHECK (btrim(language) <> ''),
  CHECK (btrim(source_kind) <> ''),
  CHECK (extracted_by_type IN ('human', 'model', 'rule_engine', 'import_pipeline', 'system')),
  CHECK (status IN ('new', 'reviewed', 'promoted', 'rejected', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_domain_term
  ON ontology_raw_term (domain, raw_term, language);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_status_updated
  ON ontology_raw_term (status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_artifact_version
  ON ontology_raw_term (artifact_version_id)
  WHERE artifact_version_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_evidence
  ON ontology_raw_term (evidence_id)
  WHERE evidence_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS ontology_raw_term_candidate (
  candidate_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_term_id                UUID NOT NULL REFERENCES ontology_raw_term (raw_term_id) ON DELETE CASCADE,
  candidate_label            TEXT NOT NULL DEFAULT '',
  candidate_concept_id       TEXT REFERENCES ontology_concept (concept_id) ON DELETE SET NULL,
  candidate_object_type      TEXT NOT NULL DEFAULT '',
  candidate_relation_type    TEXT NOT NULL DEFAULT '',
  confidence                 DOUBLE PRECISION,
  candidate_status           TEXT NOT NULL DEFAULT 'proposed',
  review_note                TEXT NOT NULL DEFAULT '',
  metadata_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    btrim(candidate_label) <> ''
    OR candidate_concept_id IS NOT NULL
  ),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  CHECK (candidate_status IN ('proposed', 'accepted', 'rejected', 'merged'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_candidate_raw_term
  ON ontology_raw_term_candidate (raw_term_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_candidate_concept
  ON ontology_raw_term_candidate (candidate_concept_id)
  WHERE candidate_concept_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_candidate_status_updated
  ON ontology_raw_term_candidate (candidate_status, updated_at DESC);
