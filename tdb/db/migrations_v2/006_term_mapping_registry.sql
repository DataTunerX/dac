-- Term mapping registry schema
-- Goal:
-- 1) Add a first-class registry for query-term interpretation rules.
-- 2) Keep term interpretation separate from core ontology concepts and aliases.
-- 3) Attach registry rules to ontology concepts, artifacts, events, and memory decisions.

CREATE TABLE IF NOT EXISTS term_mapping_registry (
  registry_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain             TEXT NOT NULL,
  registry_name      TEXT NOT NULL,
  version_label      TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'draft',
  description        TEXT NOT NULL DEFAULT '',
  owner              TEXT NOT NULL DEFAULT '',
  metadata           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (domain <> ''),
  CHECK (registry_name <> ''),
  CHECK (version_label <> ''),
  CHECK (status IN ('draft', 'active', 'superseded', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_term_mapping_registry_domain_name_version
  ON term_mapping_registry (domain, registry_name, version_label);

CREATE INDEX IF NOT EXISTS idx_term_mapping_registry_status
  ON term_mapping_registry (domain, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS term_mapping_rule (
  rule_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  registry_id           UUID NOT NULL REFERENCES term_mapping_registry (registry_id) ON DELETE CASCADE,
  raw_term              TEXT NOT NULL,
  language              TEXT NOT NULL DEFAULT 'zh',
  context_hint          TEXT NOT NULL DEFAULT '',
  term_type             TEXT NOT NULL,
  normalization_status  TEXT NOT NULL DEFAULT 'candidate',
  canonical_term        TEXT NOT NULL DEFAULT '',
  canonical_concept_id  TEXT REFERENCES ontology_concept (concept_id) ON DELETE SET NULL,
  is_compound           BOOLEAN NOT NULL DEFAULT FALSE,
  split_rule_json       JSONB NOT NULL DEFAULT '{}'::jsonb,
  semantic_slot         TEXT NOT NULL DEFAULT '',
  json_targets_json     JSONB NOT NULL DEFAULT '[]'::jsonb,
  ontology_target_kind  TEXT NOT NULL DEFAULT 'concept',
  ambiguity_flag        BOOLEAN NOT NULL DEFAULT FALSE,
  ambiguity_note        TEXT NOT NULL DEFAULT '',
  review_status         TEXT NOT NULL DEFAULT 'pending',
  confidence            DOUBLE PRECISION,
  metadata              JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (raw_term <> ''),
  CHECK (language <> ''),
  CHECK (
    term_type IN (
      'object_type',
      'period',
      'kiln',
      'ware',
      'glaze',
      'decoration_technique',
      'motif',
      'vessel_part',
      'shape_feature',
      'condition',
      'provenance_term',
      'material_term',
      'compound',
      'unknown'
    )
  ),
  CHECK (
    normalization_status IN (
      'canonical',
      'alias',
      'ambiguous',
      'compound',
      'candidate',
      'rejected'
    )
  ),
  CHECK (
    ontology_target_kind IN (
      'concept',
      'relation',
      'fact',
      'none'
    )
  ),
  CHECK (
    review_status IN (
      'pending',
      'reviewed',
      'accepted',
      'rejected',
      'superseded'
    )
  ),
  CHECK (
    confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_term_mapping_rule_registry_term_lang
  ON term_mapping_rule (registry_id, raw_term, language);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_raw_term
  ON term_mapping_rule (raw_term);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_term_type
  ON term_mapping_rule (term_type, review_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_semantic_slot
  ON term_mapping_rule (semantic_slot, review_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_canonical_concept
  ON term_mapping_rule (canonical_concept_id)
  WHERE canonical_concept_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_ambiguity
  ON term_mapping_rule (ambiguity_flag, review_status, updated_at DESC);

CREATE TABLE IF NOT EXISTS term_mapping_rule_evidence (
  rule_evidence_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_id                UUID NOT NULL REFERENCES term_mapping_rule (rule_id) ON DELETE CASCADE,
  artifact_id            UUID REFERENCES artifact (artifact_id) ON DELETE SET NULL,
  artifact_version_id    UUID REFERENCES artifact_version (artifact_version_id) ON DELETE SET NULL,
  event_id               UUID REFERENCES case_event_ledger (event_id) ON DELETE SET NULL,
  memory_decision_id     UUID REFERENCES memory_decision_record (memory_decision_id) ON DELETE SET NULL,
  source_span            TEXT,
  note                   TEXT NOT NULL DEFAULT '',
  confidence             DOUBLE PRECISION,
  evidence_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    artifact_id IS NOT NULL
    OR artifact_version_id IS NOT NULL
    OR event_id IS NOT NULL
    OR memory_decision_id IS NOT NULL
  ),
  CHECK (
    confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
  )
);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_evidence_rule
  ON term_mapping_rule_evidence (rule_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_evidence_event
  ON term_mapping_rule_evidence (event_id)
  WHERE event_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_evidence_artifact_version
  ON term_mapping_rule_evidence (artifact_version_id)
  WHERE artifact_version_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_term_mapping_rule_evidence_memory_decision
  ON term_mapping_rule_evidence (memory_decision_id)
  WHERE memory_decision_id IS NOT NULL;
