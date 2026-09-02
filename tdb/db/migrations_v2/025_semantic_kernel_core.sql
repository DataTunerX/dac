-- Semantic kernel core schema.
-- Goal:
-- 1) Introduce a Wikibase-style semantic kernel beside the current ontology layer.
-- 2) Keep the migration additive so existing ontology_* callers remain compatible.
-- 3) Create first-class storage for statements, qualifiers, references, profiles,
--    mappings, axiom promotion, derived statements, and validation runs.

CREATE TABLE IF NOT EXISTS semantic_entity (
  entity_id              TEXT PRIMARY KEY,
  entity_kind            TEXT NOT NULL,
  semantic_role          TEXT NOT NULL DEFAULT 'concept',
  property_datatype      TEXT,
  namespace              TEXT NOT NULL DEFAULT 'tdb',
  status                 TEXT NOT NULL DEFAULT 'active',
  metadata_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(entity_id) <> ''),
  CHECK (entity_kind IN ('item', 'property')),
  CHECK (
    semantic_role IN (
      'concept',
      'class',
      'individual',
      'object_property',
      'datatype_property',
      'annotation_property',
      'ontology',
      'axiom',
      'datatype'
    )
  ),
  CHECK (
    property_datatype IS NULL
    OR property_datatype IN (
      'entity',
      'string',
      'text',
      'number',
      'integer',
      'boolean',
      'time',
      'json'
    )
  ),
  CHECK (btrim(namespace) <> ''),
  CHECK (status IN ('draft', 'active', 'deprecated', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_semantic_entity_kind_status
  ON semantic_entity (entity_kind, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_entity_namespace
  ON semantic_entity (namespace, entity_kind, updated_at DESC);

CREATE TABLE IF NOT EXISTS semantic_term (
  term_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id               TEXT NOT NULL REFERENCES semantic_entity (entity_id) ON DELETE CASCADE,
  language                TEXT NOT NULL DEFAULT 'und',
  term_type               TEXT NOT NULL,
  term                    TEXT NOT NULL,
  normalized_term         TEXT NOT NULL DEFAULT '',
  status                  TEXT NOT NULL DEFAULT 'active',
  metadata_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(language) <> ''),
  CHECK (term_type IN ('label', 'description', 'alias')),
  CHECK (btrim(term) <> ''),
  CHECK (status IN ('active', 'deprecated', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_term_entity_lang_type_term
  ON semantic_term (entity_id, language, term_type, term);

CREATE INDEX IF NOT EXISTS idx_semantic_term_normalized
  ON semantic_term (normalized_term, language, term_type, updated_at DESC);

CREATE TABLE IF NOT EXISTS semantic_statement (
  statement_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_id              TEXT NOT NULL REFERENCES semantic_entity (entity_id) ON DELETE CASCADE,
  property_id             TEXT NOT NULL REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_type              TEXT NOT NULL,
  value_entity_id         TEXT REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
  rank                    TEXT NOT NULL DEFAULT 'normal',
  status                  TEXT NOT NULL DEFAULT 'proposed',
  confidence              DOUBLE PRECISION,
  valid_from              TIMESTAMPTZ,
  valid_to                TIMESTAMPTZ,
  created_by              TEXT NOT NULL DEFAULT '',
  metadata_json           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    value_type IN (
      'entity',
      'string',
      'text',
      'number',
      'integer',
      'boolean',
      'time',
      'json'
    )
  ),
  CHECK (
    (value_type = 'entity' AND value_entity_id IS NOT NULL)
    OR
    (value_type <> 'entity' AND value_entity_id IS NULL)
  ),
  CHECK (rank IN ('preferred', 'normal', 'deprecated')),
  CHECK (status IN ('proposed', 'extracted', 'reviewed', 'accepted', 'deprecated', 'rejected')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);

CREATE INDEX IF NOT EXISTS idx_semantic_statement_subject_property
  ON semantic_statement (subject_id, property_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_statement_value_entity
  ON semantic_statement (value_entity_id, property_id, updated_at DESC)
  WHERE value_entity_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_semantic_statement_status_rank
  ON semantic_statement (status, rank, updated_at DESC);

CREATE TABLE IF NOT EXISTS statement_qualifier (
  qualifier_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  statement_id             UUID NOT NULL REFERENCES semantic_statement (statement_id) ON DELETE CASCADE,
  property_id              TEXT NOT NULL REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_type               TEXT NOT NULL,
  value_entity_id          TEXT REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_json               JSONB NOT NULL DEFAULT '{}'::jsonb,
  ordinal                  INTEGER NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    value_type IN (
      'entity',
      'string',
      'text',
      'number',
      'integer',
      'boolean',
      'time',
      'json'
    )
  ),
  CHECK (
    (value_type = 'entity' AND value_entity_id IS NOT NULL)
    OR
    (value_type <> 'entity' AND value_entity_id IS NULL)
  ),
  CHECK (ordinal >= 0)
);

CREATE INDEX IF NOT EXISTS idx_statement_qualifier_statement
  ON statement_qualifier (statement_id, property_id, ordinal);

CREATE TABLE IF NOT EXISTS statement_reference (
  reference_claim_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  reference_id             UUID NOT NULL,
  statement_id             UUID NOT NULL REFERENCES semantic_statement (statement_id) ON DELETE CASCADE,
  property_id              TEXT NOT NULL REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_type               TEXT NOT NULL,
  value_entity_id          TEXT REFERENCES semantic_entity (entity_id) ON DELETE RESTRICT,
  value_json               JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence_id              UUID REFERENCES evidence_record (evidence_id) ON DELETE SET NULL,
  legacy_stream_id         TEXT,
  legacy_event_id          TEXT,
  source_span              TEXT,
  ordinal                  INTEGER NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    value_type IN (
      'entity',
      'string',
      'text',
      'number',
      'integer',
      'boolean',
      'time',
      'json'
    )
  ),
  CHECK (
    (value_type = 'entity' AND value_entity_id IS NOT NULL)
    OR
    (value_type <> 'entity' AND value_entity_id IS NULL)
  ),
  CHECK (ordinal >= 0),
  CHECK (
    evidence_id IS NOT NULL
    OR legacy_stream_id IS NOT NULL
    OR legacy_event_id IS NOT NULL
    OR btrim(COALESCE(source_span, '')) <> ''
  )
);

CREATE INDEX IF NOT EXISTS idx_statement_reference_statement
  ON statement_reference (statement_id, reference_id, ordinal);

CREATE INDEX IF NOT EXISTS idx_statement_reference_evidence
  ON statement_reference (evidence_id, created_at DESC)
  WHERE evidence_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_statement_reference_legacy_event
  ON statement_reference (legacy_stream_id, legacy_event_id, created_at DESC)
  WHERE legacy_stream_id IS NOT NULL OR legacy_event_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS statement_revision (
  revision_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  statement_id             UUID NOT NULL REFERENCES semantic_statement (statement_id) ON DELETE CASCADE,
  revision_number          INTEGER NOT NULL,
  revision_kind            TEXT NOT NULL DEFAULT 'update',
  editor                   TEXT NOT NULL DEFAULT '',
  summary                  TEXT NOT NULL DEFAULT '',
  statement_snapshot_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (revision_number > 0),
  CHECK (revision_kind IN ('create', 'update', 'status_change', 'rank_change', 'reference_update', 'qualifier_update')),
  UNIQUE (statement_id, revision_number)
);

CREATE INDEX IF NOT EXISTS idx_statement_revision_statement
  ON statement_revision (statement_id, revision_number DESC);

CREATE TABLE IF NOT EXISTS semantic_profile (
  profile_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_name             TEXT NOT NULL,
  profile_type             TEXT NOT NULL,
  version                  TEXT NOT NULL,
  namespace                TEXT NOT NULL,
  status                   TEXT NOT NULL DEFAULT 'draft',
  reasoning_profile        TEXT NOT NULL DEFAULT 'R0',
  parent_profile_id        UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  compatibility_policy     JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(profile_name) <> ''),
  CHECK (
    profile_type IN (
      'external_standard',
      'industry_extension',
      'enterprise_extension',
      'tenant_extension',
      'task_profile'
    )
  ),
  CHECK (btrim(version) <> ''),
  CHECK (btrim(namespace) <> ''),
  CHECK (status IN ('draft', 'active', 'superseded', 'deprecated', 'archived')),
  CHECK (reasoning_profile IN ('R0', 'R1', 'R2_RL', 'R3_EL', 'R4_QL'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_profile_namespace_version
  ON semantic_profile (namespace, version);

CREATE INDEX IF NOT EXISTS idx_semantic_profile_status
  ON semantic_profile (status, updated_at DESC);

CREATE TABLE IF NOT EXISTS profile_resource (
  resource_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id               UUID NOT NULL REFERENCES semantic_profile (profile_id) ON DELETE CASCADE,
  resource_kind            TEXT NOT NULL,
  resource_name            TEXT NOT NULL,
  content_format           TEXT NOT NULL DEFAULT 'json',
  content_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  content_text             TEXT NOT NULL DEFAULT '',
  metadata_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    resource_kind IN (
      'classes',
      'properties',
      'constraints',
      'mapping_rules',
      'validation_rules',
      'import_rules',
      'export_rules',
      'reasoning_profile',
      'compatibility_policy'
    )
  ),
  CHECK (btrim(resource_name) <> ''),
  CHECK (content_format IN ('json', 'yaml', 'text'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_profile_resource_unique_name
  ON profile_resource (profile_id, resource_kind, resource_name);

CREATE INDEX IF NOT EXISTS idx_profile_resource_kind
  ON profile_resource (resource_kind, updated_at DESC);

CREATE TABLE IF NOT EXISTS semantic_mapping (
  mapping_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_profile_id        UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  target_profile_id        UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  source_version           TEXT NOT NULL DEFAULT '',
  target_version           TEXT NOT NULL DEFAULT '',
  source_pattern_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  target_pattern_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  mapping_type             TEXT NOT NULL,
  transformation_rule_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  lossiness                TEXT NOT NULL DEFAULT 'lossy',
  validation_suite_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                   TEXT NOT NULL DEFAULT 'draft',
  evidence_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
  approved_by              TEXT NOT NULL DEFAULT '',
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    mapping_type IN (
      'identifier_match',
      'lexical_match',
      'translation_match',
      'exact_match',
      'close_match',
      'broad_match',
      'narrow_match',
      'class_equivalence',
      'property_equivalence',
      'structural_transformation',
      'event_reification',
      'value_conversion'
    )
  ),
  CHECK (lossiness IN ('lossless', 'conditionally_lossless', 'lossy', 'non_invertible')),
  CHECK (status IN ('draft', 'active', 'superseded', 'rejected', 'archived'))
);

CREATE INDEX IF NOT EXISTS idx_semantic_mapping_profiles
  ON semantic_mapping (source_profile_id, target_profile_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_mapping_type
  ON semantic_mapping (mapping_type, lossiness, updated_at DESC);

CREATE TABLE IF NOT EXISTS ontology_axiom (
  axiom_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id               UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  source_statement_id      UUID REFERENCES semantic_statement (statement_id) ON DELETE SET NULL,
  axiom_type               TEXT NOT NULL,
  subject_entity_id        TEXT REFERENCES semantic_entity (entity_id) ON DELETE SET NULL,
  predicate_entity_id      TEXT REFERENCES semantic_entity (entity_id) ON DELETE SET NULL,
  object_entity_id         TEXT REFERENCES semantic_entity (entity_id) ON DELETE SET NULL,
  object_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
  status                   TEXT NOT NULL DEFAULT 'candidate',
  promotion_run_id         UUID,
  metadata_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    axiom_type IN (
      'subclass_of',
      'instance_of',
      'subproperty_of',
      'domain',
      'range',
      'inverse_of',
      'transitive_property',
      'disjoint_with',
      'equivalent_class'
    )
  ),
  CHECK (status IN ('candidate', 'approved', 'deprecated', 'rejected'))
);

CREATE INDEX IF NOT EXISTS idx_ontology_axiom_profile_status
  ON ontology_axiom (profile_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_axiom_source_statement
  ON ontology_axiom (source_statement_id, updated_at DESC)
  WHERE source_statement_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS derived_statement (
  derived_statement_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  statement_id              UUID NOT NULL REFERENCES semantic_statement (statement_id) ON DELETE CASCADE,
  reasoning_profile         TEXT NOT NULL,
  ontology_profile_id       UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  input_statement_ids_json  JSONB NOT NULL DEFAULT '[]'::jsonb,
  rule_or_axiom_ids_json    JSONB NOT NULL DEFAULT '[]'::jsonb,
  reasoner_version          TEXT NOT NULL DEFAULT '',
  derived_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  confidence                DOUBLE PRECISION,
  explanation_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
  CHECK (reasoning_profile IN ('R0', 'R1', 'R2_RL', 'R3_EL', 'R4_QL')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_derived_statement_statement
  ON derived_statement (statement_id, derived_at DESC);

CREATE INDEX IF NOT EXISTS idx_derived_statement_profile
  ON derived_statement (ontology_profile_id, reasoning_profile, derived_at DESC);

CREATE TABLE IF NOT EXISTS validation_run (
  validation_run_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_id                UUID REFERENCES semantic_profile (profile_id) ON DELETE SET NULL,
  target_kind               TEXT NOT NULL,
  target_id                 TEXT NOT NULL,
  run_status                TEXT NOT NULL DEFAULT 'running',
  validator                 TEXT NOT NULL DEFAULT '',
  findings_json             JSONB NOT NULL DEFAULT '[]'::jsonb,
  metrics_json              JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  finished_at               TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (
    target_kind IN (
      'statement',
      'profile',
      'mapping',
      'axiom',
      'reasoning_batch'
    )
  ),
  CHECK (btrim(target_id) <> ''),
  CHECK (run_status IN ('running', 'passed', 'failed', 'aborted')),
  CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_validation_run_target
  ON validation_run (target_kind, target_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_validation_run_profile_status
  ON validation_run (profile_id, run_status, started_at DESC);
