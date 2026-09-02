import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { SemanticStatementReferenceSchema } from './ontology.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const EvidenceSourceKindSchema = Type.Union([
  Type.Literal('artifact_version'),
  Type.Literal('event_sentence'),
  Type.Literal('open_layer_span'),
  Type.Literal('property_state'),
  Type.Literal('edge_state'),
  Type.Literal('external_report'),
  Type.Literal('measurement'),
  Type.Literal('image_region'),
  Type.Literal('model_observation')
]);

const EvidenceTypeSchema = Type.Union([
  Type.Literal('text_span'),
  Type.Literal('image_region'),
  Type.Literal('measurement'),
  Type.Literal('lab_result'),
  Type.Literal('provenance_record'),
  Type.Literal('expert_note'),
  Type.Literal('model_observation')
]);

const EvidenceRoleSchema = Type.Union([
  Type.Literal('primary'),
  Type.Literal('derived'),
  Type.Literal('summary'),
  Type.Literal('citation'),
  Type.Literal('contradiction_candidate')
]);

const EvidenceCreatedByTypeSchema = Type.Union([
  Type.Literal('human'),
  Type.Literal('model'),
  Type.Literal('rule_engine'),
  Type.Literal('import_pipeline'),
  Type.Literal('system')
]);

const EvidenceStatusSchema = Type.Union([
  Type.Literal('active'),
  Type.Literal('superseded'),
  Type.Literal('retracted'),
  Type.Literal('archived')
]);

const EvidenceLocatorTypeSchema = Type.Union([
  Type.Literal('page_span'),
  Type.Literal('char_span'),
  Type.Literal('sentence_ref'),
  Type.Literal('bbox'),
  Type.Literal('polygon'),
  Type.Literal('time_range'),
  Type.Literal('table_cell'),
  Type.Literal('measurement_field'),
  Type.Literal('custom')
]);

const EvidenceDerivationTypeSchema = Type.Union([
  Type.Literal('extracted_from'),
  Type.Literal('summarized_from'),
  Type.Literal('translated_from'),
  Type.Literal('cropped_from'),
  Type.Literal('interpreted_from'),
  Type.Literal('normalized_from')
]);

const EvidenceClassificationStatusSchema = Type.Union([
  Type.Literal('draft'),
  Type.Literal('reviewed'),
  Type.Literal('accepted'),
  Type.Literal('superseded')
]);

export const EvidenceUpsertRequestSchema = Type.Object({
  evidence_id: Type.Optional(UuidSchema),
  case_id: Type.Optional(UuidSchema),
  event_seq: Type.Optional(Type.Integer({ minimum: 1 })),
  source_kind: EvidenceSourceKindSchema,
  source_id: Type.String({ minLength: 1 }),
  artifact_version_id: Type.Optional(UuidSchema),
  evidence_type: EvidenceTypeSchema,
  evidence_role: Type.Optional(EvidenceRoleSchema),
  methodology_framework_id: Type.Optional(UuidSchema),
  evidence_payload: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  created_by_type: EvidenceCreatedByTypeSchema,
  created_by_id: Type.Optional(Type.String()),
  is_derived: Type.Optional(Type.Boolean()),
  status: Type.Optional(EvidenceStatusSchema)
});

export const EvidenceSchema = Type.Object({
  evidence_id: UuidSchema,
  case_id: Type.Optional(UuidSchema),
  event_seq: Type.Optional(Type.Integer()),
  source_kind: EvidenceSourceKindSchema,
  source_id: Type.String(),
  artifact_version_id: Type.Optional(UuidSchema),
  evidence_type: EvidenceTypeSchema,
  evidence_role: EvidenceRoleSchema,
  methodology_framework_id: Type.Optional(UuidSchema),
  evidence_payload: Type.Record(Type.String(), JsonValueSchema),
  created_by_type: EvidenceCreatedByTypeSchema,
  created_by_id: Type.String(),
  is_derived: Type.Boolean(),
  status: EvidenceStatusSchema,
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const EvidenceGetQuerySchema = Type.Object({
  evidence_id: UuidSchema
});

export const EvidenceSearchQuerySchema = Type.Object({
  case_id: Type.Optional(UuidSchema),
  source_kind: Type.Optional(EvidenceSourceKindSchema),
  evidence_type: Type.Optional(EvidenceTypeSchema),
  evidence_role: Type.Optional(EvidenceRoleSchema),
  status: Type.Optional(EvidenceStatusSchema),
  methodology_framework_id: Type.Optional(UuidSchema),
  q: Type.Optional(Type.String()),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const EvidenceLocatorUpsertRequestSchema = Type.Object({
  evidence_locator_id: Type.Optional(UuidSchema),
  evidence_id: UuidSchema,
  locator_type: EvidenceLocatorTypeSchema,
  page_span: Type.Optional(Type.String()),
  char_span: Type.Optional(Type.String()),
  sentence_ref: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  bbox: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  polygon: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  time_range: Type.Optional(Type.String()),
  table_cell: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  measurement_field: Type.Optional(Type.String()),
  locator_payload: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  normalized_text: Type.Optional(Type.String()),
  preview_text: Type.Optional(Type.String())
});

export const EvidenceLocatorSchema = Type.Object({
  evidence_locator_id: UuidSchema,
  evidence_id: UuidSchema,
  locator_type: EvidenceLocatorTypeSchema,
  page_span: Type.Optional(Type.String()),
  char_span: Type.Optional(Type.String()),
  sentence_ref: Type.Record(Type.String(), JsonValueSchema),
  bbox: Type.Record(Type.String(), JsonValueSchema),
  polygon: Type.Record(Type.String(), JsonValueSchema),
  time_range: Type.Optional(Type.String()),
  table_cell: Type.Record(Type.String(), JsonValueSchema),
  measurement_field: Type.Optional(Type.String()),
  locator_payload: Type.Record(Type.String(), JsonValueSchema),
  normalized_text: Type.Optional(Type.String()),
  preview_text: Type.Optional(Type.String()),
  created_at: TimestampSchema
});

export const EvidenceLocatorListQuerySchema = Type.Object({
  evidence_id: UuidSchema,
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const EvidenceDerivationUpsertRequestSchema = Type.Object({
  evidence_derivation_id: Type.Optional(UuidSchema),
  child_evidence_id: UuidSchema,
  parent_evidence_id: UuidSchema,
  derivation_type: EvidenceDerivationTypeSchema,
  method: Type.Optional(Type.String()),
  run_id: Type.Optional(Type.String()),
  artifact_version_id: Type.Optional(UuidSchema),
  derivation_metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const EvidenceDerivationSchema = Type.Object({
  evidence_derivation_id: UuidSchema,
  child_evidence_id: UuidSchema,
  parent_evidence_id: UuidSchema,
  derivation_type: EvidenceDerivationTypeSchema,
  method: Type.String(),
  run_id: Type.String(),
  artifact_version_id: Type.Optional(UuidSchema),
  derivation_metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const EvidenceDerivationListQuerySchema = Type.Object({
  evidence_id: UuidSchema,
  direction: Type.Optional(
    Type.Union([Type.Literal('parents'), Type.Literal('children'), Type.Literal('both')])
  ),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const EvidenceClassificationUpsertRequestSchema = Type.Object({
  evidence_id: UuidSchema,
  source_reliability_tier: Type.Optional(Type.String()),
  evidence_strength_tier: Type.Optional(Type.String()),
  evidence_modality: Type.Optional(Type.String()),
  institutional_trust_class: Type.Optional(Type.String()),
  is_primary_source: Type.Optional(Type.Boolean()),
  is_machine_generated: Type.Optional(Type.Boolean()),
  requires_human_validation: Type.Optional(Type.Boolean()),
  methodology_framework_id: Type.Optional(UuidSchema),
  classification_status: Type.Optional(EvidenceClassificationStatusSchema),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const EvidenceClassificationSchema = Type.Object({
  evidence_id: UuidSchema,
  source_reliability_tier: Type.String(),
  evidence_strength_tier: Type.String(),
  evidence_modality: Type.String(),
  institutional_trust_class: Type.String(),
  is_primary_source: Type.Boolean(),
  is_machine_generated: Type.Boolean(),
  requires_human_validation: Type.Boolean(),
  methodology_framework_id: Type.Optional(UuidSchema),
  classification_status: EvidenceClassificationStatusSchema,
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const EvidenceClassificationGetQuerySchema = Type.Object({
  evidence_id: UuidSchema
});

export const EvidenceStatementsQuerySchema = Type.Object({
  evidence_id: UuidSchema,
  include_locators: Type.Optional(Type.Boolean({ default: true })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 }))
});

export const EvidenceUpsertRouteSchema = {
  tags: ['ledger'],
  body: EvidenceUpsertRequestSchema,
  response: { 201: EvidenceSchema, 400: ErrorSchema, 500: ErrorSchema }
};

export const EvidenceGetRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceGetQuerySchema,
  response: {
    200: Type.Object({ evidence: Type.Optional(EvidenceSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};

export const EvidenceSearchRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceSearchQuerySchema,
  response: {
    200: Type.Object({ evidence: Type.Array(EvidenceSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};

export const EvidenceLocatorUpsertRouteSchema = {
  tags: ['ledger'],
  body: EvidenceLocatorUpsertRequestSchema,
  response: { 201: EvidenceLocatorSchema, 400: ErrorSchema, 500: ErrorSchema }
};

export const EvidenceLocatorListRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceLocatorListQuerySchema,
  response: {
    200: Type.Object({ locators: Type.Array(EvidenceLocatorSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};

export const EvidenceDerivationUpsertRouteSchema = {
  tags: ['ledger'],
  body: EvidenceDerivationUpsertRequestSchema,
  response: { 201: EvidenceDerivationSchema, 400: ErrorSchema, 500: ErrorSchema }
};

export const EvidenceDerivationListRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceDerivationListQuerySchema,
  response: {
    200: Type.Object({ derivations: Type.Array(EvidenceDerivationSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};

export const EvidenceClassificationUpsertRouteSchema = {
  tags: ['ledger'],
  body: EvidenceClassificationUpsertRequestSchema,
  response: { 201: EvidenceClassificationSchema, 400: ErrorSchema, 500: ErrorSchema }
};

export const EvidenceClassificationGetRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceClassificationGetQuerySchema,
  response: {
    200: Type.Object({ classification: Type.Optional(EvidenceClassificationSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};

export const EvidenceStatementsRouteSchema = {
  tags: ['ledger'],
  querystring: EvidenceStatementsQuerySchema,
  response: {
    200: Type.Object({ references: Type.Array(SemanticStatementReferenceSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
};
