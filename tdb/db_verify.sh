#!/usr/bin/env bash
set -euo pipefail

DATABASE_URL="${DATABASE_URL:-postgres://tdb:tdb@localhost:5432/tdb}"
MIGRATION_PROFILE="${TDB_MIGRATION_PROFILE:-full}"

table_names=(
  case_seq
  case_event_ledger
  case_context
  entity
  artifact
  artifact_version
  rule_def
  authority_grant
  rule_override
  decision_record
  decision_evidence
  projection_version
  state_snapshot
  property_state
  edge_state
  search_document
  search_embedding
  event_sentence
  event_sentence_state
  memory_decision_record
  memory_episode_summary
  memory_answer_artifact
  memory_answer_validation
)

index_names=(
  idx_case_event_ledger_case_seq
  idx_case_event_ledger_case_valid_system
  idx_case_event_ledger_type
  idx_property_state_lookup
  idx_edge_state_lookup
  idx_rule_def_asof
  idx_authority_grant_asof
  idx_rule_override_asof
  idx_state_snapshot_latest
  idx_search_document_case_seq
  idx_search_document_stream_seq
  idx_search_document_tsv
  idx_search_embedding_updated
  idx_event_sentence_stream_event
  idx_event_sentence_stream_event_span
  idx_event_sentence_stream_event_hash
  idx_event_sentence_span_range_gist
  idx_event_sentence_span_gist
  idx_event_sentence_state_updated
  idx_event_sentence_state_hash
  idx_memory_decision_idempotency
  idx_memory_decision_task_created
  idx_memory_decision_run_created
  idx_memory_episode_summary_idempotency
  idx_memory_episode_summary_task_created
  idx_memory_episode_summary_run_created
  idx_memory_answer_artifact_idempotency
  idx_memory_answer_artifact_domain_intent_created
  idx_memory_answer_artifact_status_updated
  idx_memory_answer_artifact_question_fingerprint_gin
  idx_memory_answer_validation_artifact_validated
  idx_memory_answer_validation_pass_validated
)

case "$MIGRATION_PROFILE" in
  full)
    table_names+=(
      ontology_concept
      ontology_edge
      ontology_object_type
      ontology_relation_type
      ontology_fact
      ontology_fact_evidence
      ontology_fact_review
      ontology_registry_load
      ontology_case
      ontology_alert
      ontology_ops_rule_config
      ontology_ops_rule_run
      event_concept_link
      concept_alias
      semantic_entity
      semantic_term
      semantic_statement
      statement_qualifier
      statement_reference
      statement_revision
      semantic_profile
      profile_resource
      semantic_mapping
      ontology_axiom
      derived_statement
      validation_run
    )
    index_names+=(
      idx_fact_evidence_event_sentence
      idx_fact_evidence_hash_ver
      idx_ontology_fact_src_pred
      idx_ontology_fact_dst_pred
      idx_ontology_fact_status
      idx_ontology_registry_load_name_time
      idx_ort_registry_load
      idx_ontology_case_stream_status
      idx_ontology_alert_stream_status
      idx_ontology_concept_canonical
      idx_ontology_edge_src_pred
      idx_ontology_edge_dst_pred
      idx_event_concept_link_stream_event
      idx_event_concept_link_concept
      idx_concept_alias_alias_text
      idx_semantic_entity_kind_status
      idx_semantic_entity_namespace
      idx_semantic_term_entity_lang_type_term
      idx_semantic_term_normalized
      idx_semantic_statement_subject_property
      idx_semantic_statement_value_entity
      idx_semantic_statement_status_rank
      idx_statement_qualifier_statement
      idx_statement_reference_statement
      idx_statement_reference_evidence
      idx_statement_reference_legacy_event
      idx_statement_revision_statement
      idx_semantic_profile_namespace_version
      idx_semantic_profile_status
      idx_profile_resource_unique_name
      idx_profile_resource_kind
      idx_semantic_mapping_profiles
      idx_semantic_mapping_type
      idx_ontology_axiom_profile_status
      idx_ontology_axiom_source_statement
      idx_derived_statement_statement
      idx_derived_statement_profile
      idx_validation_run_target
      idx_validation_run_profile_status
    )
    ;;
  core)
    ;;
  *)
    echo "Unsupported TDB_MIGRATION_PROFILE: $MIGRATION_PROFILE"
    echo "Expected one of: full, core"
    exit 1
    ;;
esac

quoted_tables=$(printf "'%s'," "${table_names[@]}")
quoted_tables="${quoted_tables%,}"
quoted_indexes=$(printf "'%s'," "${index_names[@]}")
quoted_indexes="${quoted_indexes%,}"

echo "Checking connection..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c 'SELECT current_database() AS db, current_user AS usr;'

echo "Checking extension..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"

echo "Checking tables..."
table_rows=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "
SELECT tablename
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ($quoted_tables)
ORDER BY tablename;
")
printf '%s\n' "$table_rows"

missing_tables=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "
WITH expected(name) AS (
  SELECT unnest(ARRAY[$quoted_tables]::text[])
)
SELECT expected.name
FROM expected
LEFT JOIN pg_tables t
  ON t.schemaname = 'public'
 AND t.tablename = expected.name
WHERE t.tablename IS NULL
ORDER BY expected.name;
")

if [[ -n "$missing_tables" ]]; then
  echo "Missing tables:"
  printf '%s\n' "$missing_tables"
  exit 1
fi

echo "Checking key indexes..."
index_rows=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "
SELECT indexname
FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN ($quoted_indexes)
ORDER BY indexname;
")
printf '%s\n' "$index_rows"

missing_indexes=$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -Atqc "
WITH expected(name) AS (
  SELECT unnest(ARRAY[$quoted_indexes]::text[])
)
SELECT expected.name
FROM expected
LEFT JOIN pg_indexes i
  ON i.schemaname = 'public'
 AND i.indexname = expected.name
WHERE i.indexname IS NULL
ORDER BY expected.name;
")

if [[ -n "$missing_indexes" ]]; then
  echo "Missing indexes:"
  printf '%s\n' "$missing_indexes"
  exit 1
fi

echo "Database verification completed."
