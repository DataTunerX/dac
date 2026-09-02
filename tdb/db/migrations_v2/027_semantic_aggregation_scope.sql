-- Add semantic-kernel support for aggregation units and scoped aggregation statements.
-- This keeps layered aggregation inside the Wikibase-style statement graph
-- while preventing legacy ontology projections from treating aggregate units
-- as ordinary concepts.

DO $$
DECLARE
  rec RECORD;
BEGIN
  IF to_regclass('semantic_entity') IS NULL THEN
    RAISE NOTICE 'semantic_entity not present; skipping aggregation semantic-role migration';
    RETURN;
  END IF;

  FOR rec IN
    SELECT conname
    FROM pg_constraint
    WHERE conrelid = 'semantic_entity'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%semantic_role%'
  LOOP
    EXECUTE format('ALTER TABLE semantic_entity DROP CONSTRAINT IF EXISTS %I', rec.conname);
  END LOOP;

  ALTER TABLE semantic_entity
    ADD CONSTRAINT semantic_entity_semantic_role_check
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
        'datatype',
        'evidence_unit',
        'aggregate_unit',
        'higher_order_aggregate_unit'
      )
    );
END $$;

INSERT INTO semantic_entity (
  entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
)
VALUES
  (
    'tdb.aggregation.has_member',
    'property',
    'object_property',
    'entity',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Has Member","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.derived_from_structure',
    'property',
    'object_property',
    'entity',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Derived From Structure","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.profile_overlap',
    'property',
    'annotation_property',
    'json',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Profile Overlap","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.graph_support',
    'property',
    'annotation_property',
    'json',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Graph Support","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.llm_synthesis',
    'property',
    'annotation_property',
    'json',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation LLM Synthesis","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.llm_critic',
    'property',
    'annotation_property',
    'json',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation LLM Critic","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.input_relation_count',
    'property',
    'annotation_property',
    'integer',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Input Relation Count","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.aggregation.generation_stage',
    'property',
    'annotation_property',
    'string',
    'tdb.aggregation',
    'active',
    '{"display_name":"Aggregation Generation Stage","statement_scope":"aggregation"}'::jsonb
  ),
  (
    'tdb.ref.evidence',
    'property',
    'annotation_property',
    'json',
    'tdb.system',
    'active',
    '{"display_name":"Evidence Reference","statement_scope":"reference"}'::jsonb
  )
ON CONFLICT (entity_id) DO UPDATE SET
  entity_kind = EXCLUDED.entity_kind,
  semantic_role = EXCLUDED.semantic_role,
  property_datatype = EXCLUDED.property_datatype,
  namespace = EXCLUDED.namespace,
  status = EXCLUDED.status,
  metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
  updated_at = NOW();
