import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const SubjectTypeSchema = Type.Union([
  Type.Literal('artifact'),
  Type.Literal('component'),
  Type.Literal('inscription'),
  Type.Literal('provenance_event'),
  Type.Literal('test_report')
]);

const ObjectTypeSchema = Type.Union([
  Type.Literal('vocabulary_term'),
  Type.Literal('entity'),
  Type.Literal('literal'),
  Type.Literal('range'),
  Type.Literal('probability_distribution')
]);

const AssertionTypeSchema = Type.Union([
  Type.Literal('observation'),
  Type.Literal('classification'),
  Type.Literal('hypothesis'),
  Type.Literal('dispute'),
  Type.Literal('correction'),
  Type.Literal('consensus')
]);

const AssertedByTypeSchema = Type.Union([
  Type.Literal('human'),
  Type.Literal('model'),
  Type.Literal('rule_engine'),
  Type.Literal('import_pipeline')
]);

const AssertionStatusSchema = Type.Union([
  Type.Literal('active'),
  Type.Literal('disputed'),
  Type.Literal('superseded'),
  Type.Literal('retracted'),
  Type.Literal('archived')
]);

const SupportTypeSchema = Type.Union([
  Type.Literal('supports'),
  Type.Literal('contradicts'),
  Type.Literal('weakly_supports'),
  Type.Literal('context_only')
]);

const RelationTypeSchema = Type.Union([
  Type.Literal('contradicts'),
  Type.Literal('supersedes'),
  Type.Literal('refines'),
  Type.Literal('aggregates'),
  Type.Literal('consensus_of')
]);

export const AssertionUpsertRequestSchema = Type.Object({
  assertion_id: Type.Optional(UuidSchema),
  case_id: Type.Optional(UuidSchema),
  subject_type: SubjectTypeSchema,
  subject_id: UuidSchema,
  predicate: Type.String({ minLength: 1 }),
  object_type: ObjectTypeSchema,
  object_id: Type.Optional(UuidSchema),
  object_literal: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  assertion_type: AssertionTypeSchema,
  asserted_by_type: AssertedByTypeSchema,
  asserted_by_id: Type.Optional(Type.String()),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  status: Type.Optional(AssertionStatusSchema),
  methodology_framework_id: Type.Optional(UuidSchema),
  source_event_id: Type.Optional(UuidSchema),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const AssertionSchema = Type.Object({
  assertion_id: UuidSchema,
  case_id: Type.Optional(UuidSchema),
  subject_type: SubjectTypeSchema,
  subject_id: UuidSchema,
  predicate: Type.String(),
  object_type: ObjectTypeSchema,
  object_id: Type.Optional(UuidSchema),
  object_literal: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  assertion_type: AssertionTypeSchema,
  asserted_by_type: AssertedByTypeSchema,
  asserted_by_id: Type.Optional(Type.String()),
  confidence: Type.Number(),
  status: AssertionStatusSchema,
  methodology_framework_id: Type.Optional(UuidSchema),
  source_event_id: Type.Optional(UuidSchema),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const AssertionGetQuerySchema = Type.Object({
  assertion_id: UuidSchema
});

export const AssertionSearchQuerySchema = Type.Object({
  case_id: Type.Optional(UuidSchema),
  subject_type: Type.Optional(SubjectTypeSchema),
  subject_id: Type.Optional(UuidSchema),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  assertion_type: Type.Optional(AssertionTypeSchema),
  status: Type.Optional(AssertionStatusSchema),
  methodology_framework_id: Type.Optional(UuidSchema),
  q: Type.Optional(Type.String()),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const AssertionEvidenceLinkUpsertRequestSchema = Type.Object({
  assertion_evidence_link_id: Type.Optional(UuidSchema),
  assertion_id: UuidSchema,
  evidence_id: Type.Optional(UuidSchema),
  artifact_version_id: Type.Optional(UuidSchema),
  event_id: Type.Optional(UuidSchema),
  memory_decision_id: Type.Optional(UuidSchema),
  support_type: Type.Optional(SupportTypeSchema),
  weight: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  note: Type.Optional(Type.String()),
  evidence: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const AssertionEvidenceLinkSchema = Type.Object({
  assertion_evidence_link_id: UuidSchema,
  assertion_id: UuidSchema,
  evidence_id: Type.Optional(UuidSchema),
  artifact_version_id: Type.Optional(UuidSchema),
  event_id: Type.Optional(UuidSchema),
  memory_decision_id: Type.Optional(UuidSchema),
  support_type: SupportTypeSchema,
  weight: Type.Number(),
  note: Type.String(),
  evidence: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const AssertionEvidenceLinkListQuerySchema = Type.Object({
  assertion_id: UuidSchema,
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const AssertionRelationUpsertRequestSchema = Type.Object({
  assertion_relation_id: Type.Optional(UuidSchema),
  from_assertion_id: UuidSchema,
  to_assertion_id: UuidSchema,
  relation_type: RelationTypeSchema,
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const AssertionRelationSchema = Type.Object({
  assertion_relation_id: UuidSchema,
  from_assertion_id: UuidSchema,
  to_assertion_id: UuidSchema,
  relation_type: RelationTypeSchema,
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const AssertionRelationListQuerySchema = Type.Object({
  assertion_id: UuidSchema,
  direction: Type.Optional(
    Type.Union([Type.Literal('incoming'), Type.Literal('outgoing'), Type.Literal('both')])
  ),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  offset: Type.Optional(Type.Integer({ minimum: 0 }))
});

export const AssertionUpsertRouteSchema = {
  tags: ['ledger'],
  body: AssertionUpsertRequestSchema,
  response: { 201: AssertionSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionGetRouteSchema = {
  tags: ['ledger'],
  querystring: AssertionGetQuerySchema,
  response: {
    200: Type.Object({ assertion: Type.Optional(AssertionSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const AssertionSearchRouteSchema = {
  tags: ['ledger'],
  querystring: AssertionSearchQuerySchema,
  response: {
    200: Type.Object({ assertions: Type.Array(AssertionSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const AssertionEvidenceLinkUpsertRouteSchema = {
  tags: ['ledger'],
  body: AssertionEvidenceLinkUpsertRequestSchema,
  response: { 201: AssertionEvidenceLinkSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionEvidenceLinkListRouteSchema = {
  tags: ['ledger'],
  querystring: AssertionEvidenceLinkListQuerySchema,
  response: {
    200: Type.Object({ evidence_links: Type.Array(AssertionEvidenceLinkSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const AssertionRelationUpsertRouteSchema = {
  tags: ['ledger'],
  body: AssertionRelationUpsertRequestSchema,
  response: { 201: AssertionRelationSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionRelationListRouteSchema = {
  tags: ['ledger'],
  querystring: AssertionRelationListQuerySchema,
  response: {
    200: Type.Object({ relations: Type.Array(AssertionRelationSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;
