import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { OntologyFactHistoryResponseSchema } from './governance.js';

const TimestampString = Type.String({ minLength: 1 });

export const OntologyConceptSchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  canonical_name: Type.String({ minLength: 1 }),
  concept_type: Type.String({ minLength: 1 }),
  aliases: Type.Array(Type.String()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyConceptUpsertRequestSchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  canonical_name: Type.String({ minLength: 1 }),
  concept_type: Type.String({ minLength: 1 }),
  aliases: Type.Optional(Type.Array(Type.String()))
});

export const OntologyConceptGetQuerySchema = Type.Object({
  concept_id: Type.String({ minLength: 1 })
});

export const OntologyConceptEvidenceQuerySchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  fact_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, default: 20 })),
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, default: 5 })),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
});

export const OntologyConceptListQuerySchema = Type.Object({
  concept_type: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyConceptEvidenceRouteSchema = {
  tags: ['ontology'],
  querystring: OntologyConceptEvidenceQuerySchema,
  response: {
    200: Type.Object({
      concept: OntologyConceptSchema,
      facts: Type.Array(OntologyFactHistoryResponseSchema),
    }),
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  }
} as const;

export const ConceptAliasSchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  alias_text: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  extractor: Type.String({ minLength: 1 }),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const ConceptAliasUpsertRequestSchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  alias_text: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  extractor: Type.String({ minLength: 1 })
});

export const ConceptAliasListQuerySchema = Type.Object({
  concept_id: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyEdgeSchema = Type.Object({
  src_concept_id: Type.String({ minLength: 1 }),
  predicate: Type.String({ minLength: 1 }),
  dst_concept_id: Type.String({ minLength: 1 }),
  weight: Type.Number({ exclusiveMinimum: 0 }),
  created_at: TimestampString
});

export const OntologyEdgeUpsertRequestSchema = Type.Object({
  src_concept_id: Type.String({ minLength: 1 }),
  predicate: Type.String({ minLength: 1 }),
  dst_concept_id: Type.String({ minLength: 1 }),
  weight: Type.Number({ exclusiveMinimum: 0 })
});

export const OntologyEdgeListQuerySchema = Type.Object({
  src_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  dst_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 }))
});

export const EventConceptLinkSchema = Type.Object({
  stream_id: Type.String({ minLength: 1 }),
  event_id: Type.String({ minLength: 1 }),
  concept_id: Type.String({ minLength: 1 }),
  role: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  asset_id: Type.String(),
  version_number: Type.Integer({ minimum: 0 }),
  extractor: Type.String({ minLength: 1 }),
  source_span: Type.String(),
  evidence: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const EventConceptLinkUpsertRequestSchema = Type.Object({
  stream_id: Type.String({ minLength: 1 }),
  event_id: Type.String({ minLength: 1 }),
  concept_id: Type.String({ minLength: 1 }),
  role: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  asset_id: Type.Optional(Type.String({ minLength: 1 })),
  version_number: Type.Optional(Type.Integer({ minimum: 1 })),
  extractor: Type.String({ minLength: 1 }),
  source_span: Type.Optional(Type.String({ minLength: 1 })),
  evidence: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const EventConceptLinkListQuerySchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  event_id: Type.Optional(Type.String({ minLength: 1 })),
  concept_id: Type.Optional(Type.String({ minLength: 1 })),
  role: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 }))
});

export const OntologyObjectTypeSchema = Type.Object({
  type_id: Type.String({ minLength: 1 }),
  display_name: Type.String({ minLength: 1 }),
  description: Type.String(),
  enabled: Type.Boolean(),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyObjectTypeUpsertRequestSchema = Type.Object({
  type_id: Type.String({ minLength: 1 }),
  display_name: Type.String({ minLength: 1 }),
  description: Type.Optional(Type.String()),
  enabled: Type.Optional(Type.Boolean())
});

export const OntologyObjectTypeGetQuerySchema = Type.Object({
  type_id: Type.String({ minLength: 1 })
});

export const OntologyObjectTypeListQuerySchema = Type.Object({
  enabled_only: Type.Optional(Type.Boolean()),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyConceptTypeAssignmentSchema = Type.Object({
  assignment_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  concept_id: Type.String({ minLength: 1 }),
  object_type_id: Type.String({ minLength: 1 }),
  assignment_status: Type.String({ minLength: 1 }),
  source_kind: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyConceptTypeAssignmentUpsertRequestSchema = Type.Object({
  assignment_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.String({ minLength: 1 }),
  concept_id: Type.String({ minLength: 1 }),
  object_type_id: Type.String({ minLength: 1 }),
  assignment_status: Type.Optional(Type.String({ minLength: 1 })),
  source_kind: Type.String({ minLength: 1 }),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyConceptTypeAssignmentListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  concept_id: Type.Optional(Type.String({ minLength: 1 })),
  object_type_id: Type.Optional(Type.String({ minLength: 1 })),
  assignment_status: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyRelationTypeSchema = Type.Object({
  predicate: Type.String({ minLength: 1 }),
  src_type_id: Type.String({ minLength: 1 }),
  dst_type_id: Type.String({ minLength: 1 }),
  display_name: Type.String({ minLength: 1 }),
  description: Type.String(),
  is_symmetric: Type.Boolean(),
  is_transitive: Type.Boolean(),
  enabled: Type.Boolean(),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyRelationTypeUpsertRequestSchema = Type.Object({
  predicate: Type.String({ minLength: 1 }),
  src_type_id: Type.String({ minLength: 1 }),
  dst_type_id: Type.String({ minLength: 1 }),
  display_name: Type.String({ minLength: 1 }),
  description: Type.Optional(Type.String()),
  is_symmetric: Type.Optional(Type.Boolean()),
  is_transitive: Type.Optional(Type.Boolean()),
  enabled: Type.Optional(Type.Boolean())
});

export const OntologyRelationTypeGetQuerySchema = Type.Object({
  predicate: Type.String({ minLength: 1 })
});

export const OntologyRelationTypeListQuerySchema = Type.Object({
  src_type_id: Type.Optional(Type.String({ minLength: 1 })),
  dst_type_id: Type.Optional(Type.String({ minLength: 1 })),
  enabled_only: Type.Optional(Type.Boolean()),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyFactSchema = Type.Object({
  fact_id: Type.Integer({ minimum: 1 }),
  statement_id: Type.Optional(Type.String({ minLength: 1 })),
  src_concept_id: Type.String({ minLength: 1 }),
  src_concept_label: Type.Optional(Type.String()),
  predicate: Type.String({ minLength: 1 }),
  dst_concept_id: Type.String({ minLength: 1 }),
  dst_concept_label: Type.Optional(Type.String()),
  qualifier: Type.Record(Type.String(), Type.Unknown()),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  extractor: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  review_note: Type.String(),
  valid_from: Type.Optional(TimestampString),
  valid_to: Type.Optional(TimestampString),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyFactEvidenceSchema = Type.Object({
  stream_id: Type.String({ minLength: 1 }),
  event_id: Type.String({ minLength: 1 }),
  source_span: Type.Optional(Type.String({ minLength: 1 })),
  evidence: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 }))
});

export const OntologyFactUpsertWithEvidenceRequestSchema = Type.Object({
  src_concept_id: Type.String({ minLength: 1 }),
  predicate: Type.String({ minLength: 1 }),
  dst_concept_id: Type.String({ minLength: 1 }),
  qualifier: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  extractor: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  review_note: Type.Optional(Type.String()),
  valid_from: Type.Optional(TimestampString),
  valid_to: Type.Optional(TimestampString),
  evidence: Type.Array(OntologyFactEvidenceSchema, { minItems: 1 })
});

export const SemanticEntityWriteSchema = Type.Object({
  entity_id: Type.String({ minLength: 1 }),
  entity_kind: Type.String({ minLength: 1 }),
  semantic_role: Type.String({ minLength: 1 }),
  namespace: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  property_datatype: Type.Optional(Type.String({ minLength: 1 })),
  metadata_json: Type.Unknown()
});

export const SemanticStatementWriteSchema = Type.Object({
  statement_key: Type.String({ minLength: 1 }),
  subject_id: Type.String({ minLength: 1 }),
  property_id: Type.String({ minLength: 1 }),
  value_type: Type.String({ minLength: 1 }),
  value_entity_id: Type.Optional(Type.String({ minLength: 1 })),
  value_json: Type.Unknown(),
  status: Type.String({ minLength: 1 }),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  created_by: Type.String({ minLength: 1 }),
  metadata_json: Type.Unknown()
});

export const StatementQualifierWriteSchema = Type.Object({
  statement_key: Type.String({ minLength: 1 }),
  property_id: Type.String({ minLength: 1 }),
  value_type: Type.String({ minLength: 1 }),
  value_json: Type.Unknown(),
  value_entity_id: Type.Optional(Type.String({ minLength: 1 })),
  ordinal: Type.Integer({ minimum: 0 })
});

export const StatementReferenceWriteSchema = Type.Object({
  statement_key: Type.String({ minLength: 1 }),
  property_id: Type.String({ minLength: 1 }),
  value_type: Type.String({ minLength: 1 }),
  value_json: Type.Unknown(),
  evidence_id: Type.Optional(Type.String({ minLength: 1 })),
  source_span: Type.Optional(Type.String({ minLength: 1 })),
  ordinal: Type.Integer({ minimum: 0 })
});

export const SemanticBatchUpsertRequestSchema = Type.Object({
  entities: Type.Array(SemanticEntityWriteSchema),
  statements: Type.Array(SemanticStatementWriteSchema),
  qualifiers: Type.Array(StatementQualifierWriteSchema),
  references: Type.Array(StatementReferenceWriteSchema)
});

export const SemanticBatchUpsertResponseSchema = Type.Object({
  semantic_entity_count: Type.Integer({ minimum: 0 }),
  semantic_statement_count: Type.Integer({ minimum: 0 }),
  statement_qualifier_count: Type.Integer({ minimum: 0 }),
  statement_reference_count: Type.Integer({ minimum: 0 })
});

export const SemanticStatementSchema = Type.Object({
  statement_id: Type.String({ minLength: 1 }),
  subject_concept_id: Type.String({ minLength: 1 }),
  subject_name: Type.String(),
  predicate: Type.String({ minLength: 1 }),
  object_concept_id: Type.String(),
  object_name: Type.String(),
  value_type: Type.String({ minLength: 1 }),
  value_json: Type.Unknown(),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  status: Type.String({ minLength: 1 }),
  created_by: Type.String(),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  provenance: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const SemanticStatementListQuerySchema = Type.Object({
  subject_id: Type.Optional(Type.String({ minLength: 1 })),
  property_id: Type.Optional(Type.String({ minLength: 1 })),
  value_entity_id: Type.Optional(Type.String({ minLength: 1 })),
  // 'all' includes retracted statements; default hides them
  status: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const SemanticStatementStatusRequestSchema = Type.Object({
  statement_id: Type.String({ minLength: 1 }),
  status: Type.Union([
    Type.Literal('proposed'), Type.Literal('extracted'), Type.Literal('reviewed'),
    Type.Literal('accepted'), Type.Literal('deprecated'), Type.Literal('rejected')
  ]),
  note: Type.Optional(Type.String())
});

export const SemanticStatementQualifierSchema = Type.Object({
  statement_id: Type.String({ minLength: 1 }),
  property_id: Type.String({ minLength: 1 }),
  value_type: Type.String({ minLength: 1 }),
  value_entity_id: Type.Optional(Type.String({ minLength: 1 })),
  value: Type.Unknown(),
  ordinal: Type.Integer({ minimum: 0 })
});

export const SemanticStatementEvidenceSchema = Type.Object({
  evidence_id: Type.String({ minLength: 1 }),
  case_id: Type.Optional(Type.String({ minLength: 1 })),
  event_seq: Type.Optional(Type.Integer({ minimum: 1 })),
  source_kind: Type.String({ minLength: 1 }),
  source_id: Type.String({ minLength: 1 }),
  artifact_version_id: Type.Optional(Type.String({ minLength: 1 })),
  evidence_type: Type.String({ minLength: 1 }),
  evidence_role: Type.String({ minLength: 1 }),
  methodology_framework_id: Type.Optional(Type.String({ minLength: 1 })),
  evidence_payload: Type.Record(Type.String(), Type.Unknown()),
  created_by_type: Type.String({ minLength: 1 }),
  created_by_id: Type.String(),
  is_derived: Type.Boolean(),
  status: Type.String({ minLength: 1 }),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const SemanticStatementEvidenceLocatorSchema = Type.Object({
  evidence_locator_id: Type.String({ minLength: 1 }),
  evidence_id: Type.String({ minLength: 1 }),
  locator_type: Type.String({ minLength: 1 }),
  page_span: Type.Optional(Type.String({ minLength: 1 })),
  char_span: Type.Optional(Type.String({ minLength: 1 })),
  sentence_ref: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  bbox: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  polygon: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  time_range: Type.Optional(Type.String({ minLength: 1 })),
  table_cell: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  measurement_field: Type.Optional(Type.String({ minLength: 1 })),
  locator_payload: Type.Record(Type.String(), Type.Unknown()),
  normalized_text: Type.Optional(Type.String({ minLength: 1 })),
  preview_text: Type.Optional(Type.String({ minLength: 1 })),
  created_at: TimestampString
});

export const SemanticStatementReferenceSchema = Type.Object({
  statement_id: Type.String({ minLength: 1 }),
  property_id: Type.String({ minLength: 1 }),
  value_type: Type.String({ minLength: 1 }),
  value: Type.Unknown(),
  evidence_id: Type.Optional(Type.String({ minLength: 1 })),
  source_span: Type.Optional(Type.String({ minLength: 1 })),
  ordinal: Type.Integer({ minimum: 0 }),
  evidence: Type.Optional(SemanticStatementEvidenceSchema),
  locators: Type.Array(SemanticStatementEvidenceLocatorSchema)
});

export const SemanticStatementGetQuerySchema = Type.Object({
  statement_id: Type.String({ minLength: 1 })
});

export const SemanticStatementProvenanceQuerySchema = Type.Object({
  statement_id: Type.String({ minLength: 1 }),
  include_locators: Type.Optional(Type.Boolean({ default: true })),
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 }))
});

export const OntologyFactListQuerySchema = Type.Object({
  status: Type.Optional(Type.String({ minLength: 1 })),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  stream_prefix: Type.Optional(Type.Boolean({ default: false })),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  extractor: Type.Optional(Type.String({ minLength: 1 })),
  src_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  dst_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyFactSearchQuerySchema = Type.Object({
  q: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(Type.String({ minLength: 1 })),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  stream_prefix: Type.Optional(Type.Boolean({ default: false })),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  extractor: Type.Optional(Type.String({ minLength: 1 })),
  src_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  dst_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyConceptSearchQuerySchema = Type.Object({
  q: Type.Optional(Type.String({ minLength: 1 })),
  concept_type: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const ConceptAliasSearchQuerySchema = Type.Object({
  q: Type.Optional(Type.String({ minLength: 1 })),
  concept_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyConceptNeighborsQuerySchema = Type.Object({
  concept_id: Type.String({ minLength: 1 }),
  direction: Type.String({ minLength: 1 }),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 }))
});

export const OntologyNeighborSchema = Type.Object({
  fact_id: Type.Integer({ minimum: 1 }),
  predicate: Type.String({ minLength: 1 }),
  direction: Type.String({ minLength: 1 }),
  neighbor_concept_id: Type.String({ minLength: 1 }),
  neighbor_canonical_name: Type.String({ minLength: 1 }),
  neighbor_concept_type: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 })
});

export const OntologyFactArchiveRequestSchema = Type.Object({
  fact_id: Type.Integer({ minimum: 1 }),
  reviewer: Type.String({ minLength: 1 }),
  note: Type.String({ minLength: 1 })
});

export const TermMappingRegistrySchema = Type.Object({
  registry_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  registry_name: Type.String({ minLength: 1 }),
  version_label: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  description: Type.String(),
  owner: Type.String(),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const TermMappingRegistryUpsertRequestSchema = Type.Object({
  domain: Type.String({ minLength: 1 }),
  registry_name: Type.String({ minLength: 1 }),
  version_label: Type.String({ minLength: 1 }),
  status: Type.String({ minLength: 1 }),
  description: Type.Optional(Type.String()),
  owner: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const TermMappingRegistryGetQuerySchema = Type.Object({
  registry_id: Type.String({ minLength: 1 })
});

export const TermMappingRegistryListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const TermMappingRuleSchema = Type.Object({
  rule_id: Type.String({ minLength: 1 }),
  registry_id: Type.String({ minLength: 1 }),
  raw_term: Type.String({ minLength: 1 }),
  language: Type.String({ minLength: 1 }),
  context_hint: Type.String(),
  term_type: Type.String({ minLength: 1 }),
  normalization_status: Type.String({ minLength: 1 }),
  canonical_term: Type.String(),
  canonical_concept_id: Type.String(),
  is_compound: Type.Boolean(),
  split_rule: Type.Record(Type.String(), Type.Unknown()),
  semantic_slot: Type.String(),
  json_targets: Type.Array(Type.String()),
  ontology_target_kind: Type.String({ minLength: 1 }),
  ambiguity_flag: Type.Boolean(),
  ambiguity_note: Type.String(),
  review_status: Type.String({ minLength: 1 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const TermMappingRuleUpsertRequestSchema = Type.Object({
  rule_id: Type.Optional(Type.String({ minLength: 1 })),
  registry_id: Type.String({ minLength: 1 }),
  raw_term: Type.String({ minLength: 1 }),
  language: Type.Optional(Type.String({ minLength: 1 })),
  context_hint: Type.Optional(Type.String()),
  term_type: Type.String({ minLength: 1 }),
  normalization_status: Type.String({ minLength: 1 }),
  canonical_term: Type.Optional(Type.String()),
  canonical_concept_id: Type.Optional(Type.String()),
  is_compound: Type.Optional(Type.Boolean()),
  split_rule: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  semantic_slot: Type.Optional(Type.String()),
  json_targets: Type.Optional(Type.Array(Type.String())),
  ontology_target_kind: Type.Optional(Type.String({ minLength: 1 })),
  ambiguity_flag: Type.Optional(Type.Boolean()),
  ambiguity_note: Type.Optional(Type.String()),
  review_status: Type.Optional(Type.String({ minLength: 1 })),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const TermMappingRuleGetQuerySchema = Type.Object({
  rule_id: Type.String({ minLength: 1 })
});

export const TermMappingRuleSearchQuerySchema = Type.Object({
  registry_id: Type.Optional(Type.String({ minLength: 1 })),
  raw_term: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  language: Type.Optional(Type.String({ minLength: 1 })),
  term_type: Type.Optional(Type.String({ minLength: 1 })),
  semantic_slot: Type.Optional(Type.String({ minLength: 1 })),
  review_status: Type.Optional(Type.String({ minLength: 1 })),
  ambiguity_only: Type.Optional(Type.Boolean()),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const TermMappingRuleEvidenceSchema = Type.Object({
  rule_evidence_id: Type.String({ minLength: 1 }),
  rule_id: Type.String({ minLength: 1 }),
  artifact_id: Type.String(),
  artifact_version_id: Type.String(),
  event_id: Type.String(),
  memory_decision_id: Type.String(),
  source_span: Type.String(),
  note: Type.String(),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  evidence: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const TermMappingRuleEvidenceUpsertRequestSchema = Type.Object({
  rule_evidence_id: Type.Optional(Type.String({ minLength: 1 })),
  rule_id: Type.String({ minLength: 1 }),
  artifact_id: Type.Optional(Type.String({ minLength: 1 })),
  artifact_version_id: Type.Optional(Type.String({ minLength: 1 })),
  event_id: Type.Optional(Type.String({ minLength: 1 })),
  memory_decision_id: Type.Optional(Type.String({ minLength: 1 })),
  source_span: Type.Optional(Type.String()),
  note: Type.Optional(Type.String()),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  evidence: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const TermMappingRuleEvidenceListQuerySchema = Type.Object({
  rule_id: Type.String({ minLength: 1 }),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 }))
});

export const TermMappingInterpretationSchema = Type.Object({
  found: Type.Boolean(),
  raw_term: Type.String({ minLength: 1 }),
  matched_rule_id: Type.Optional(Type.String({ minLength: 1 })),
  registry_id: Type.String(),
  language: Type.String(),
  term_type: Type.String(),
  normalization_status: Type.String(),
  canonical_term: Type.String(),
  canonical_concept_id: Type.String(),
  is_compound: Type.Boolean(),
  split_rule: Type.Record(Type.String(), Type.Unknown()),
  semantic_slot: Type.String(),
  json_targets: Type.Array(Type.String()),
  ontology_target_kind: Type.String(),
  ambiguity_flag: Type.Boolean(),
  ambiguity_note: Type.String(),
  review_status: Type.String(),
  confidence: Type.Number({ minimum: 0, maximum: 1 })
});

export const OntologyRawTermSchema = Type.Object({
  raw_term_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  raw_term: Type.String({ minLength: 1 }),
  language: Type.String({ minLength: 1 }),
  normalized_hint: Type.String(),
  term_type_hint: Type.String(),
  source_kind: Type.String({ minLength: 1 }),
  source_ref: Type.String(),
  artifact_version_id: Type.Optional(Type.String({ minLength: 1 })),
  evidence_id: Type.Optional(Type.String({ minLength: 1 })),
  context_text: Type.String(),
  context_locator: Type.Record(Type.String(), Type.Unknown()),
  extracted_by_type: Type.String({ minLength: 1 }),
  extracted_by_id: Type.String(),
  status: Type.String({ minLength: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyRawTermUpsertRequestSchema = Type.Object({
  raw_term_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.String({ minLength: 1 }),
  raw_term: Type.String({ minLength: 1 }),
  language: Type.Optional(Type.String({ minLength: 1 })),
  normalized_hint: Type.Optional(Type.String()),
  term_type_hint: Type.Optional(Type.String()),
  source_kind: Type.String({ minLength: 1 }),
  source_ref: Type.Optional(Type.String()),
  artifact_version_id: Type.Optional(Type.String({ minLength: 1 })),
  evidence_id: Type.Optional(Type.String({ minLength: 1 })),
  context_text: Type.Optional(Type.String()),
  context_locator: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
  extracted_by_type: Type.String({ minLength: 1 }),
  extracted_by_id: Type.Optional(Type.String()),
  status: Type.Optional(Type.String({ minLength: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyRawTermGetQuerySchema = Type.Object({
  raw_term_id: Type.String({ minLength: 1 })
});

export const OntologyRawTermSearchQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  raw_term: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  language: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(Type.String({ minLength: 1 })),
  term_type_hint: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyRawTermCandidateSchema = Type.Object({
  candidate_id: Type.String({ minLength: 1 }),
  raw_term_id: Type.String({ minLength: 1 }),
  candidate_label: Type.String(),
  candidate_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  candidate_object_type: Type.String(),
  candidate_relation_type: Type.String(),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  candidate_status: Type.String({ minLength: 1 }),
  review_note: Type.String(),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyRawTermCandidateUpsertRequestSchema = Type.Object({
  candidate_id: Type.Optional(Type.String({ minLength: 1 })),
  raw_term_id: Type.String({ minLength: 1 }),
  candidate_label: Type.Optional(Type.String()),
  candidate_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  candidate_object_type: Type.Optional(Type.String()),
  candidate_relation_type: Type.Optional(Type.String()),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  candidate_status: Type.Optional(Type.String({ minLength: 1 })),
  review_note: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyRawTermCandidateListQuerySchema = Type.Object({
  raw_term_id: Type.String({ minLength: 1 }),
  candidate_status: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyNormalizedTermSchema = Type.Object({
  normalized_term_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  normalized_surface: Type.String({ minLength: 1 }),
  normalized_type: Type.String(),
  merge_key: Type.String(),
  type_confidence: Type.Number({ minimum: 0, maximum: 1 }),
  head_term: Type.String(),
  modifier_terms: Type.Array(Type.String()),
  canonical_candidate_label: Type.String(),
  canonical_candidate_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  primary_cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  source_support_count: Type.Integer({ minimum: 0 }),
  is_promotable: Type.Boolean(),
  normalization_status: Type.String({ minLength: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyNormalizedTermUpsertRequestSchema = Type.Object({
  normalized_term_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.String({ minLength: 1 }),
  normalized_surface: Type.String({ minLength: 1 }),
  normalized_type: Type.Optional(Type.String()),
  merge_key: Type.Optional(Type.String()),
  type_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  head_term: Type.Optional(Type.String()),
  modifier_terms: Type.Optional(Type.Array(Type.String())),
  canonical_candidate_label: Type.Optional(Type.String()),
  canonical_candidate_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  primary_cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  source_support_count: Type.Optional(Type.Integer({ minimum: 0 })),
  is_promotable: Type.Optional(Type.Boolean()),
  normalization_status: Type.Optional(Type.String({ minLength: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyNormalizedTermGetQuerySchema = Type.Object({
  normalized_term_id: Type.String({ minLength: 1 })
});

export const OntologyNormalizedTermSearchQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  normalized_surface: Type.Optional(Type.String({ minLength: 1 })),
  q: Type.Optional(Type.String({ minLength: 1 })),
  normalized_type: Type.Optional(Type.String({ minLength: 1 })),
  normalization_status: Type.Optional(Type.String({ minLength: 1 })),
  primary_cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  promotable_only: Type.Optional(Type.Boolean()),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyTermClusterSchema = Type.Object({
  cluster_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  cluster_type: Type.String({ minLength: 1 }),
  proposed_canonical: Type.String(),
  proposed_type: Type.String(),
  cluster_status: Type.String({ minLength: 1 }),
  member_count: Type.Integer({ minimum: 0 }),
  source_support_count: Type.Integer({ minimum: 0 }),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyTermClusterUpsertRequestSchema = Type.Object({
  cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.String({ minLength: 1 }),
  cluster_type: Type.Optional(Type.String({ minLength: 1 })),
  proposed_canonical: Type.Optional(Type.String()),
  proposed_type: Type.Optional(Type.String()),
  cluster_status: Type.Optional(Type.String({ minLength: 1 })),
  member_count: Type.Optional(Type.Integer({ minimum: 0 })),
  source_support_count: Type.Optional(Type.Integer({ minimum: 0 })),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyTermClusterGetQuerySchema = Type.Object({
  cluster_id: Type.String({ minLength: 1 })
});

export const OntologyTermClusterListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  cluster_type: Type.Optional(Type.String({ minLength: 1 })),
  cluster_status: Type.Optional(Type.String({ minLength: 1 })),
  proposed_type: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyClusterMemberSchema = Type.Object({
  cluster_member_id: Type.String({ minLength: 1 }),
  cluster_id: Type.String({ minLength: 1 }),
  normalized_term_id: Type.String({ minLength: 1 }),
  member_role: Type.String({ minLength: 1 }),
  membership_confidence: Type.Number({ minimum: 0, maximum: 1 }),
  added_by: Type.String({ minLength: 1 }),
  note: Type.String(),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyClusterMemberUpsertRequestSchema = Type.Object({
  cluster_member_id: Type.Optional(Type.String({ minLength: 1 })),
  cluster_id: Type.String({ minLength: 1 }),
  normalized_term_id: Type.String({ minLength: 1 }),
  member_role: Type.Optional(Type.String({ minLength: 1 })),
  membership_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  added_by: Type.Optional(Type.String({ minLength: 1 })),
  note: Type.Optional(Type.String())
});

export const OntologyClusterMemberListQuerySchema = Type.Object({
  cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  normalized_term_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyRawTermNormalizationSchema = Type.Object({
  mapping_id: Type.String({ minLength: 1 }),
  raw_term_id: Type.String({ minLength: 1 }),
  normalized_term_id: Type.String({ minLength: 1 }),
  mapping_confidence: Type.Number({ minimum: 0, maximum: 1 }),
  mapping_type: Type.String({ minLength: 1 }),
  mapping_status: Type.String({ minLength: 1 }),
  component_role: Type.String(),
  normalization_rule: Type.String(),
  note: Type.String(),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyRawTermNormalizationUpsertRequestSchema = Type.Object({
  mapping_id: Type.Optional(Type.String({ minLength: 1 })),
  raw_term_id: Type.String({ minLength: 1 }),
  normalized_term_id: Type.String({ minLength: 1 }),
  mapping_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  mapping_type: Type.Optional(Type.String({ minLength: 1 })),
  mapping_status: Type.Optional(Type.String({ minLength: 1 })),
  component_role: Type.Optional(Type.String()),
  normalization_rule: Type.Optional(Type.String()),
  note: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyRawTermNormalizationListQuerySchema = Type.Object({
  raw_term_id: Type.Optional(Type.String({ minLength: 1 })),
  normalized_term_id: Type.Optional(Type.String({ minLength: 1 })),
  mapping_status: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const OntologyRelationCandidateSchema = Type.Object({
  relation_candidate_id: Type.String({ minLength: 1 }),
  domain: Type.String({ minLength: 1 }),
  subject_label: Type.String({ minLength: 1 }),
  relation_type: Type.String({ minLength: 1 }),
  object_label: Type.String({ minLength: 1 }),
  subject_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  object_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  candidate_status: Type.String({ minLength: 1 }),
  source_kind: Type.String({ minLength: 1 }),
  source_cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  confidence: Type.Number({ minimum: 0, maximum: 1 }),
  metadata: Type.Record(Type.String(), Type.Unknown()),
  created_at: TimestampString,
  updated_at: TimestampString
});

export const OntologyRelationCandidateUpsertRequestSchema = Type.Object({
  relation_candidate_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.String({ minLength: 1 }),
  subject_label: Type.String({ minLength: 1 }),
  relation_type: Type.String({ minLength: 1 }),
  object_label: Type.String({ minLength: 1 }),
  subject_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  object_concept_id: Type.Optional(Type.String({ minLength: 1 })),
  candidate_status: Type.Optional(Type.String({ minLength: 1 })),
  source_kind: Type.String({ minLength: 1 }),
  source_cluster_id: Type.Optional(Type.String({ minLength: 1 })),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown()))
});

export const OntologyRelationCandidateListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  relation_type: Type.Optional(Type.String({ minLength: 1 })),
  candidate_status: Type.Optional(Type.String({ minLength: 1 })),
  subject_label: Type.Optional(Type.String({ minLength: 1 })),
  object_label: Type.Optional(Type.String({ minLength: 1 })),
  source_kind: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, default: 0 }))
});

export const TermMappingInterpretQuerySchema = Type.Object({
  registry_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.Optional(Type.String({ minLength: 1 })),
  registry_name: Type.Optional(Type.String({ minLength: 1 })),
  version_label: Type.Optional(Type.String({ minLength: 1 })),
  raw_term: Type.String({ minLength: 1 }),
  language: Type.Optional(Type.String({ minLength: 1 })),
  context_hint: Type.Optional(Type.String())
});

export const TermMappingInterpretBatchRequestSchema = Type.Object({
  registry_id: Type.Optional(Type.String({ minLength: 1 })),
  domain: Type.Optional(Type.String({ minLength: 1 })),
  registry_name: Type.Optional(Type.String({ minLength: 1 })),
  version_label: Type.Optional(Type.String({ minLength: 1 })),
  raw_terms: Type.Array(Type.String({ minLength: 1 }), { minItems: 1 }),
  language: Type.Optional(Type.String({ minLength: 1 })),
  context_hint: Type.Optional(Type.String())
});

export const OntologyConceptUpsertRouteSchema = { tags: ['ontology'], body: OntologyConceptUpsertRequestSchema, response: { 201: OntologyConceptSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptGetRouteSchema = { tags: ['ontology'], querystring: OntologyConceptGetQuerySchema, response: { 200: Type.Object({ concept: Type.Optional(OntologyConceptSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptListRouteSchema = { tags: ['ontology'], querystring: OntologyConceptListQuerySchema, response: { 200: Type.Object({ concepts: Type.Array(OntologyConceptSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptSearchRouteSchema = { tags: ['ontology'], querystring: OntologyConceptSearchQuerySchema, response: { 200: Type.Object({ concepts: Type.Array(OntologyConceptSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const ConceptAliasUpsertRouteSchema = { tags: ['ontology'], body: ConceptAliasUpsertRequestSchema, response: { 201: ConceptAliasSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const ConceptAliasListRouteSchema = { tags: ['ontology'], querystring: ConceptAliasListQuerySchema, response: { 200: Type.Object({ aliases: Type.Array(ConceptAliasSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const ConceptAliasSearchRouteSchema = { tags: ['ontology'], querystring: ConceptAliasSearchQuerySchema, response: { 200: Type.Object({ aliases: Type.Array(ConceptAliasSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyEdgeUpsertRouteSchema = { tags: ['ontology'], body: OntologyEdgeUpsertRequestSchema, response: { 201: OntologyEdgeSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyEdgeListRouteSchema = { tags: ['ontology'], querystring: OntologyEdgeListQuerySchema, response: { 200: Type.Object({ edges: Type.Array(OntologyEdgeSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const EventConceptLinkUpsertRouteSchema = { tags: ['ontology'], body: EventConceptLinkUpsertRequestSchema, response: { 201: EventConceptLinkSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const EventConceptLinkListRouteSchema = { tags: ['ontology'], querystring: EventConceptLinkListQuerySchema, response: { 200: Type.Object({ links: Type.Array(EventConceptLinkSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyObjectTypeUpsertRouteSchema = { tags: ['ontology'], body: OntologyObjectTypeUpsertRequestSchema, response: { 201: OntologyObjectTypeSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyObjectTypeGetRouteSchema = { tags: ['ontology'], querystring: OntologyObjectTypeGetQuerySchema, response: { 200: Type.Object({ object_type: Type.Optional(OntologyObjectTypeSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyObjectTypeListRouteSchema = { tags: ['ontology'], querystring: OntologyObjectTypeListQuerySchema, response: { 200: Type.Object({ object_types: Type.Array(OntologyObjectTypeSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptTypeAssignmentUpsertRouteSchema = { tags: ['ontology'], body: OntologyConceptTypeAssignmentUpsertRequestSchema, response: { 201: OntologyConceptTypeAssignmentSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptTypeAssignmentListRouteSchema = { tags: ['ontology'], querystring: OntologyConceptTypeAssignmentListQuerySchema, response: { 200: Type.Object({ assignments: Type.Array(OntologyConceptTypeAssignmentSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRelationTypeUpsertRouteSchema = { tags: ['ontology'], body: OntologyRelationTypeUpsertRequestSchema, response: { 201: OntologyRelationTypeSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRelationTypeGetRouteSchema = { tags: ['ontology'], querystring: OntologyRelationTypeGetQuerySchema, response: { 200: Type.Object({ relation_type: Type.Optional(OntologyRelationTypeSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRelationTypeListRouteSchema = { tags: ['ontology'], querystring: OntologyRelationTypeListQuerySchema, response: { 200: Type.Object({ relation_types: Type.Array(OntologyRelationTypeSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyFactGetRouteSchema = { tags: ['ontology'], querystring: Type.Object({ fact_id: Type.Integer({ minimum: 1 }) }), response: { 200: Type.Object({ fact: Type.Optional(OntologyFactSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyFactListRouteSchema = { tags: ['ontology'], querystring: OntologyFactListQuerySchema, response: { 200: Type.Object({ facts: Type.Array(OntologyFactSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyFactUpsertWithEvidenceRouteSchema = { tags: ['ontology'], body: OntologyFactUpsertWithEvidenceRequestSchema, response: { 201: Type.Object({ fact: OntologyFactSchema, evidence_count: Type.Integer({ minimum: 1 }) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const SemanticBatchUpsertRouteSchema = { tags: ['ontology'], body: SemanticBatchUpsertRequestSchema, response: { 201: SemanticBatchUpsertResponseSchema, 400: ErrorSchema, 413: ErrorSchema, 500: ErrorSchema } } as const;
export const SemanticStatementWithQualifiersSchema = Type.Object({
  statement: SemanticStatementSchema,
  qualifiers: Type.Array(SemanticStatementQualifierSchema)
});

export const SemanticStatementListRouteSchema = { tags: ['ontology'], querystring: SemanticStatementListQuerySchema, response: { 200: Type.Object({ statements: Type.Array(SemanticStatementWithQualifiersSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;

export const SemanticStatementStatusRouteSchema = { tags: ['ontology'], body: SemanticStatementStatusRequestSchema, response: { 200: Type.Object({ updated_rows: Type.Integer({ minimum: 0 }) }), 400: ErrorSchema, 500: ErrorSchema } } as const;

export const SemanticStatementGetRouteSchema = { tags: ['ontology'], querystring: SemanticStatementGetQuerySchema, response: { 200: Type.Object({ statement: Type.Optional(SemanticStatementSchema), qualifiers: Type.Array(SemanticStatementQualifierSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const SemanticStatementProvenanceRouteSchema = { tags: ['ontology'], querystring: SemanticStatementProvenanceQuerySchema, response: { 200: Type.Object({ references: Type.Array(SemanticStatementReferenceSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyFactSearchRouteSchema = { tags: ['ontology'], querystring: OntologyFactSearchQuerySchema, response: { 200: Type.Object({ facts: Type.Array(OntologyFactSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyConceptNeighborsRouteSchema = { tags: ['ontology'], querystring: OntologyConceptNeighborsQuerySchema, response: { 200: Type.Object({ neighbors: Type.Array(OntologyNeighborSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyFactArchiveRouteSchema = { tags: ['ontology'], body: OntologyFactArchiveRequestSchema, response: { 200: Type.Object({ fact_id: Type.Integer({ minimum: 1 }) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRegistryUpsertRouteSchema = { tags: ['ontology'], body: TermMappingRegistryUpsertRequestSchema, response: { 201: TermMappingRegistrySchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRegistryGetRouteSchema = { tags: ['ontology'], querystring: TermMappingRegistryGetQuerySchema, response: { 200: Type.Object({ registry: Type.Optional(TermMappingRegistrySchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRegistryListRouteSchema = { tags: ['ontology'], querystring: TermMappingRegistryListQuerySchema, response: { 200: Type.Object({ registries: Type.Array(TermMappingRegistrySchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRuleUpsertRouteSchema = { tags: ['ontology'], body: TermMappingRuleUpsertRequestSchema, response: { 201: TermMappingRuleSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRuleGetRouteSchema = { tags: ['ontology'], querystring: TermMappingRuleGetQuerySchema, response: { 200: Type.Object({ rule: Type.Optional(TermMappingRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRuleSearchRouteSchema = { tags: ['ontology'], querystring: TermMappingRuleSearchQuerySchema, response: { 200: Type.Object({ rules: Type.Array(TermMappingRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRuleEvidenceUpsertRouteSchema = { tags: ['ontology'], body: TermMappingRuleEvidenceUpsertRequestSchema, response: { 201: TermMappingRuleEvidenceSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingRuleEvidenceListRouteSchema = { tags: ['ontology'], querystring: TermMappingRuleEvidenceListQuerySchema, response: { 200: Type.Object({ evidence: Type.Array(TermMappingRuleEvidenceSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingInterpretRouteSchema = { tags: ['ontology'], querystring: TermMappingInterpretQuerySchema, response: { 200: Type.Object({ interpretation: Type.Optional(TermMappingInterpretationSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const TermMappingInterpretBatchRouteSchema = { tags: ['ontology'], body: TermMappingInterpretBatchRequestSchema, response: { 200: Type.Object({ interpretations: Type.Array(TermMappingInterpretationSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermUpsertRouteSchema = { tags: ['ontology'], body: OntologyRawTermUpsertRequestSchema, response: { 201: OntologyRawTermSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermGetRouteSchema = { tags: ['ontology'], querystring: OntologyRawTermGetQuerySchema, response: { 200: Type.Object({ raw_term: Type.Optional(OntologyRawTermSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermSearchRouteSchema = { tags: ['ontology'], querystring: OntologyRawTermSearchQuerySchema, response: { 200: Type.Object({ raw_terms: Type.Array(OntologyRawTermSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermCandidateUpsertRouteSchema = { tags: ['ontology'], body: OntologyRawTermCandidateUpsertRequestSchema, response: { 201: OntologyRawTermCandidateSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermCandidateListRouteSchema = { tags: ['ontology'], querystring: OntologyRawTermCandidateListQuerySchema, response: { 200: Type.Object({ candidates: Type.Array(OntologyRawTermCandidateSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyNormalizedTermUpsertRouteSchema = { tags: ['ontology'], body: OntologyNormalizedTermUpsertRequestSchema, response: { 201: OntologyNormalizedTermSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyNormalizedTermGetRouteSchema = { tags: ['ontology'], querystring: OntologyNormalizedTermGetQuerySchema, response: { 200: Type.Object({ normalized_term: Type.Optional(OntologyNormalizedTermSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyNormalizedTermSearchRouteSchema = { tags: ['ontology'], querystring: OntologyNormalizedTermSearchQuerySchema, response: { 200: Type.Object({ normalized_terms: Type.Array(OntologyNormalizedTermSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyTermClusterUpsertRouteSchema = { tags: ['ontology'], body: OntologyTermClusterUpsertRequestSchema, response: { 201: OntologyTermClusterSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyTermClusterGetRouteSchema = { tags: ['ontology'], querystring: OntologyTermClusterGetQuerySchema, response: { 200: Type.Object({ cluster: Type.Optional(OntologyTermClusterSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyTermClusterListRouteSchema = { tags: ['ontology'], querystring: OntologyTermClusterListQuerySchema, response: { 200: Type.Object({ clusters: Type.Array(OntologyTermClusterSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyClusterMemberUpsertRouteSchema = { tags: ['ontology'], body: OntologyClusterMemberUpsertRequestSchema, response: { 201: OntologyClusterMemberSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyClusterMemberListRouteSchema = { tags: ['ontology'], querystring: OntologyClusterMemberListQuerySchema, response: { 200: Type.Object({ members: Type.Array(OntologyClusterMemberSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRelationCandidateUpsertRouteSchema = { tags: ['ontology'], body: OntologyRelationCandidateUpsertRequestSchema, response: { 201: OntologyRelationCandidateSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRelationCandidateListRouteSchema = { tags: ['ontology'], querystring: OntologyRelationCandidateListQuerySchema, response: { 200: Type.Object({ relation_candidates: Type.Array(OntologyRelationCandidateSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermNormalizationUpsertRouteSchema = { tags: ['ontology'], body: OntologyRawTermNormalizationUpsertRequestSchema, response: { 201: OntologyRawTermNormalizationSchema, 400: ErrorSchema, 500: ErrorSchema } } as const;
export const OntologyRawTermNormalizationListRouteSchema = { tags: ['ontology'], querystring: OntologyRawTermNormalizationListQuerySchema, response: { 200: Type.Object({ mappings: Type.Array(OntologyRawTermNormalizationSchema) }), 400: ErrorSchema, 500: ErrorSchema } } as const;
