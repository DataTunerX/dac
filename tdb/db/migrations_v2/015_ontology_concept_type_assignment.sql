-- Domain-level concept typing assignments.
-- Keeps coarse ontology_concept.concept_type intact while allowing
-- domain-specific object typing such as ceramics ware/kiln/glaze.

CREATE TABLE IF NOT EXISTS ontology_concept_type_assignment (
  assignment_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain             TEXT NOT NULL,
  concept_id         TEXT NOT NULL REFERENCES ontology_concept (concept_id) ON DELETE CASCADE,
  object_type_id     TEXT NOT NULL REFERENCES ontology_object_type (type_id) ON DELETE CASCADE,
  assignment_status  TEXT NOT NULL DEFAULT 'auto',
  source_kind        TEXT NOT NULL DEFAULT '',
  confidence         DOUBLE PRECISION,
  metadata_json      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK (assignment_status IN ('auto', 'accepted', 'rejected', 'needs_review')),
  CHECK (confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
  UNIQUE (domain, concept_id, object_type_id)
);

CREATE INDEX IF NOT EXISTS idx_ontology_concept_type_assignment_concept
  ON ontology_concept_type_assignment (concept_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_concept_type_assignment_object_type
  ON ontology_concept_type_assignment (object_type_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_ontology_concept_type_assignment_status
  ON ontology_concept_type_assignment (domain, assignment_status, updated_at DESC);
