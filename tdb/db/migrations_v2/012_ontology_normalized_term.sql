-- Ontology normalized-term layer.
-- Sits between ontology_raw_term and ontology_concept to support
-- normalization, weak typing, decomposition, clustering, and later promotion.

CREATE TABLE IF NOT EXISTS ontology_term_cluster (
  cluster_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain                          TEXT NOT NULL,
  cluster_type                    TEXT NOT NULL DEFAULT 'same_family',
  proposed_canonical              TEXT NOT NULL DEFAULT '',
  proposed_type                   TEXT NOT NULL DEFAULT '',
  cluster_status                  TEXT NOT NULL DEFAULT 'auto',
  member_count                    INTEGER NOT NULL DEFAULT 0,
  source_support_count            INTEGER NOT NULL DEFAULT 0,
  confidence                      DOUBLE PRECISION,
  metadata_json                   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(domain) <> ''),
  CHECK (cluster_type IN ('alias_like', 'same_family', 'mixed_candidate')),
  CHECK (cluster_status IN ('auto', 'reviewed', 'ambiguous', 'split_needed', 'merged_to_concept', 'archived')),
  CHECK (member_count >= 0),
  CHECK (source_support_count >= 0),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_ontology_term_cluster_domain_status
  ON ontology_term_cluster (domain, cluster_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_term_cluster_proposed_type
  ON ontology_term_cluster (proposed_type, updated_at DESC)
  WHERE btrim(proposed_type) <> '';

CREATE TABLE IF NOT EXISTS ontology_normalized_term (
  normalized_term_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain                          TEXT NOT NULL,
  normalized_surface              TEXT NOT NULL,
  normalized_type                 TEXT NOT NULL DEFAULT '',
  merge_key                       TEXT NOT NULL DEFAULT '',
  type_confidence                 DOUBLE PRECISION,
  head_term                       TEXT NOT NULL DEFAULT '',
  modifier_terms_json             JSONB NOT NULL DEFAULT '[]'::jsonb,
  canonical_candidate_label       TEXT NOT NULL DEFAULT '',
  canonical_candidate_concept_id  TEXT REFERENCES ontology_concept (concept_id) ON DELETE SET NULL,
  primary_cluster_id              UUID REFERENCES ontology_term_cluster (cluster_id) ON DELETE SET NULL,
  source_support_count            INTEGER NOT NULL DEFAULT 0,
  is_promotable                   BOOLEAN NOT NULL DEFAULT FALSE,
  normalization_status            TEXT NOT NULL DEFAULT 'auto',
  metadata_json                   JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(domain) <> ''),
  CHECK (btrim(normalized_surface) <> ''),
  CHECK (type_confidence IS NULL OR (type_confidence >= 0.0 AND type_confidence <= 1.0)),
  CHECK (source_support_count >= 0),
  CHECK (normalization_status IN ('auto', 'reviewed', 'ambiguous', 'rejected', 'archived'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ontology_normalized_term_domain_surface_type
  ON ontology_normalized_term (domain, normalized_surface, normalized_type);

CREATE INDEX IF NOT EXISTS idx_ontology_normalized_term_merge_key
  ON ontology_normalized_term (domain, merge_key)
  WHERE btrim(merge_key) <> '';

CREATE INDEX IF NOT EXISTS idx_ontology_normalized_term_primary_cluster
  ON ontology_normalized_term (primary_cluster_id)
  WHERE primary_cluster_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_normalized_term_status_updated
  ON ontology_normalized_term (normalization_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_normalized_term_canonical_concept
  ON ontology_normalized_term (canonical_candidate_concept_id)
  WHERE canonical_candidate_concept_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_normalized_term_promotable
  ON ontology_normalized_term (is_promotable, updated_at DESC);


CREATE TABLE IF NOT EXISTS ontology_cluster_member (
  cluster_member_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  cluster_id                      UUID NOT NULL REFERENCES ontology_term_cluster (cluster_id) ON DELETE CASCADE,
  normalized_term_id              UUID NOT NULL REFERENCES ontology_normalized_term (normalized_term_id) ON DELETE CASCADE,
  member_role                     TEXT NOT NULL DEFAULT 'core',
  membership_confidence           DOUBLE PRECISION,
  added_by                        TEXT NOT NULL DEFAULT 'system',
  note                            TEXT NOT NULL DEFAULT '',
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (member_role IN ('core', 'peripheral', 'candidate_canonical')),
  CHECK (membership_confidence IS NULL OR (membership_confidence >= 0.0 AND membership_confidence <= 1.0)),
  UNIQUE (cluster_id, normalized_term_id)
);

CREATE INDEX IF NOT EXISTS idx_ontology_cluster_member_cluster
  ON ontology_cluster_member (cluster_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_cluster_member_normalized_term
  ON ontology_cluster_member (normalized_term_id, created_at DESC);


CREATE TABLE IF NOT EXISTS ontology_raw_term_normalization (
  mapping_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  raw_term_id               UUID NOT NULL REFERENCES ontology_raw_term (raw_term_id) ON DELETE CASCADE,
  normalized_term_id        UUID NOT NULL REFERENCES ontology_normalized_term (normalized_term_id) ON DELETE CASCADE,
  mapping_confidence        DOUBLE PRECISION,
  mapping_type              TEXT NOT NULL DEFAULT 'surface_normalized',
  mapping_status            TEXT NOT NULL DEFAULT 'auto',
  component_role            TEXT NOT NULL DEFAULT '',
  normalization_rule        TEXT NOT NULL DEFAULT '',
  note                      TEXT NOT NULL DEFAULT '',
  metadata_json             JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (mapping_confidence IS NULL OR (mapping_confidence >= 0.0 AND mapping_confidence <= 1.0)),
  CHECK (mapping_type IN ('exact_surface', 'surface_normalized', 'decomposed', 'alias_candidate', 'cluster_member')),
  CHECK (mapping_status IN ('auto', 'reviewed', 'ambiguous', 'rejected')),
  CHECK (component_role IN ('', 'head', 'modifier', 'component')),
  UNIQUE (raw_term_id, normalized_term_id, mapping_type)
);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_normalization_raw_term
  ON ontology_raw_term_normalization (raw_term_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_normalization_normalized_term
  ON ontology_raw_term_normalization (normalized_term_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_normalization_mapping_type
  ON ontology_raw_term_normalization (mapping_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_normalization_mapping_status
  ON ontology_raw_term_normalization (mapping_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_raw_term_normalization_rule
  ON ontology_raw_term_normalization (normalization_rule, updated_at DESC)
  WHERE btrim(normalization_rule) <> '';
