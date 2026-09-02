-- Ontology relation-candidate layer.
-- Stores low-risk candidate relations prior to formal ontology_edge / ontology_fact promotion.

CREATE TABLE IF NOT EXISTS ontology_relation_candidate (
  relation_candidate_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain                         TEXT NOT NULL,
  subject_label                  TEXT NOT NULL,
  relation_type                  TEXT NOT NULL,
  object_label                   TEXT NOT NULL,
  subject_concept_id             TEXT REFERENCES ontology_concept (concept_id) ON DELETE SET NULL,
  object_concept_id              TEXT REFERENCES ontology_concept (concept_id) ON DELETE SET NULL,
  candidate_status               TEXT NOT NULL DEFAULT 'auto',
  source_kind                    TEXT NOT NULL DEFAULT '',
  source_cluster_id              UUID REFERENCES ontology_term_cluster (cluster_id) ON DELETE SET NULL,
  confidence                     DOUBLE PRECISION,
  metadata_json                  JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (btrim(domain) <> ''),
  CHECK (btrim(subject_label) <> ''),
  CHECK (btrim(relation_type) <> ''),
  CHECK (btrim(object_label) <> ''),
  CHECK (candidate_status IN ('auto', 'accepted', 'rejected', 'needs_review')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  UNIQUE (domain, subject_label, relation_type, object_label)
);

CREATE INDEX IF NOT EXISTS idx_ontology_relation_candidate_domain_status
  ON ontology_relation_candidate (domain, candidate_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_relation_candidate_relation_type
  ON ontology_relation_candidate (relation_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_relation_candidate_subject_concept
  ON ontology_relation_candidate (subject_concept_id, updated_at DESC)
  WHERE subject_concept_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_relation_candidate_object_concept
  ON ontology_relation_candidate (object_concept_id, updated_at DESC)
  WHERE object_concept_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ontology_relation_candidate_source_cluster
  ON ontology_relation_candidate (source_cluster_id, updated_at DESC)
  WHERE source_cluster_id IS NOT NULL;
