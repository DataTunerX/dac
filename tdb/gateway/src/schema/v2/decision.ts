import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

export const DecisionCreateRequestSchema = Type.Object({
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String({ minLength: 1, maxLength: 100 }),
  chosen_action: Type.String({ minLength: 1 }),
  candidates: Type.Optional(Type.Array(Type.Record(Type.String(), JsonValueSchema))),
  scores: Type.Optional(Type.Record(Type.String(), Type.Number())),
  constraints_hit: Type.Optional(Type.Array(Type.String())),
  detail: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const DecisionSchema = Type.Object({
  decision_id: UuidSchema,
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String(),
  chosen_action: Type.String(),
  candidates: Type.Array(Type.Record(Type.String(), JsonValueSchema)),
  scores: Type.Record(Type.String(), Type.Number()),
  constraints_hit: Type.Array(Type.String()),
  detail: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const DecisionEvidenceAttachRequestSchema = Type.Object({
  decision_id: UuidSchema,
  artifact_version_id: UuidSchema,
  citation: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const DecisionEvidenceSchema = Type.Object({
  decision_evidence_id: UuidSchema,
  decision_id: UuidSchema,
  artifact_version_id: UuidSchema,
  citation: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const DecisionGetQuerySchema = Type.Object({
  case_id: UuidSchema,
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String({ minLength: 1, maxLength: 100 })
});

export const DecisionTraceQuerySchema = DecisionGetQuerySchema;
export const DecisionExplainQuerySchema = DecisionGetQuerySchema;

export const DecisionGetResponseSchema = Type.Object({
  decision: Type.Optional(DecisionSchema),
  evidence: Type.Array(DecisionEvidenceSchema)
});

export const DecisionTraceResponseSchema = Type.Object({
  decision: Type.Optional(DecisionSchema),
  evidence: Type.Array(DecisionEvidenceSchema),
  event: Type.Optional(
    Type.Object({
      event_id: UuidSchema,
      case_id: UuidSchema,
      event_seq: Type.Integer({ minimum: 1 }),
      event_type: Type.String(),
      actor_id: Type.Optional(UuidSchema),
      subject_id: Type.Optional(UuidSchema),
      object_id: Type.Optional(UuidSchema),
      payload: Type.Record(Type.String(), JsonValueSchema),
      valid_time: TimestampSchema,
      system_time: TimestampSchema
    })
  ),
  snapshot_anchor: Type.Optional(
    Type.Object({
      snapshot_id: UuidSchema,
      case_id: UuidSchema,
      event_seq: Type.Integer({ minimum: 1 }),
      projection_version: Type.String(),
      state_blob: Type.Record(Type.String(), JsonValueSchema),
      state_hash: Type.Optional(Type.String()),
      created_at: TimestampSchema
    })
  ),
  artifact_versions: Type.Array(
    Type.Object({
      artifact_version_id: UuidSchema,
      artifact_id: UuidSchema,
      version_number: Type.Integer({ minimum: 1 }),
      status: Type.String(),
      valid_from: TimestampSchema,
      valid_to: Type.Optional(TimestampSchema),
      system_from: TimestampSchema,
      system_to: Type.Optional(TimestampSchema),
      content_ref: Type.String(),
      content_hash: Type.Optional(Type.String()),
      author_id: Type.Optional(UuidSchema),
      approver_id: Type.Optional(UuidSchema),
      created_at: TimestampSchema
    })
  ),
  explanation: Type.Object({
    status: Type.Union([
      Type.Literal('resolved'),
      Type.Literal('partial'),
      Type.Literal('missing_decision')
    ]),
    summary: Type.String(),
    decision_found: Type.Boolean(),
    event_found: Type.Boolean(),
    snapshot_anchor_found: Type.Boolean(),
    evidence_count: Type.Integer({ minimum: 0 }),
    artifact_version_count: Type.Integer({ minimum: 0 }),
    missing_artifact_version_ids: Type.Array(UuidSchema),
    missing_components: Type.Array(Type.String()),
    reasoning_steps: Type.Array(Type.String())
  })
});

export const DecisionExplainResponseSchema = DecisionTraceResponseSchema;

export const DecisionCreateRouteSchema = {
  tags: ['decision'],
  body: DecisionCreateRequestSchema,
  response: { 201: DecisionSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const DecisionEvidenceAttachRouteSchema = {
  tags: ['decision'],
  body: DecisionEvidenceAttachRequestSchema,
  response: { 201: DecisionEvidenceSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const DecisionGetRouteSchema = {
  tags: ['decision'],
  querystring: DecisionGetQuerySchema,
  response: { 200: DecisionGetResponseSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const DecisionTraceRouteSchema = {
  tags: ['decision'],
  querystring: DecisionTraceQuerySchema,
  response: { 200: DecisionTraceResponseSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const DecisionExplainRouteSchema = {
  tags: ['decision'],
  querystring: DecisionExplainQuerySchema,
  response: { 200: DecisionExplainResponseSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;
