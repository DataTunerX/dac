ALTER TABLE evidence_record
  DROP CONSTRAINT IF EXISTS evidence_record_source_kind_check;

ALTER TABLE evidence_record
  ADD CONSTRAINT evidence_record_source_kind_check
  CHECK (
    source_kind = ANY (
      ARRAY[
        'artifact_version'::text,
        'event_sentence'::text,
        'open_layer_span'::text,
        'property_state'::text,
        'edge_state'::text,
        'external_report'::text,
        'measurement'::text,
        'image_region'::text,
        'model_observation'::text
      ]
    )
  );
