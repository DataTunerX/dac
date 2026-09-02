import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const EvidenceRefSchema = Type.Object({
  resource_id: Type.Optional(Type.String({ minLength: 1 })),
  artifact_id: Type.Optional(Type.String({ minLength: 1 })),
  artifact_version_id: Type.Optional(Type.String({ minLength: 1 })),
  decision_id: Type.Optional(Type.String({ minLength: 1 })),
  event_id: Type.Optional(Type.String({ minLength: 1 })),
  url: Type.Optional(Type.String({ minLength: 1 })),
});

const AuthorSchema = Type.Object({
  type: Type.String({ minLength: 1 }),
  id: Type.String({ minLength: 1 }),
});

const LegacyDecisionSchema = Type.Object({
  case_id: Type.String({ format: 'uuid' }),
  event_seq: Type.Integer({ minimum: 1 }),
  projection_version: Type.String({ minLength: 1 }),
  chosen_action: Type.String({ minLength: 1 }),
  candidates: Type.Optional(Type.Array(Type.Record(Type.String(), JsonValueSchema))),
  scores: Type.Optional(Type.Record(Type.String(), Type.Number())),
  constraints_hit: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  detail: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
});

const EntityRefSchema = Type.Object({
  type: Type.String({ minLength: 1 }),
  name: Type.String({ minLength: 1 }),
});

const EntityStateIncludeSchema = Type.Object({
  durable_state: Type.Optional(Type.Boolean()),
  last_observed_state: Type.Optional(Type.Boolean()),
  inferred_state: Type.Optional(Type.Boolean()),
  provenance: Type.Optional(Type.Boolean()),
});

const StateFieldSchema = Type.Object({
  value: JsonValueSchema,
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  observed_at: Type.Optional(TimestampSchema),
  source_evidence: Type.Optional(Type.Array(EvidenceRefSchema)),
  derived_from: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
});

const TaskContextIncludeSchema = Type.Object({
  facts: Type.Optional(Type.Boolean()),
  entities: Type.Optional(Type.Boolean()),
  decisions: Type.Optional(Type.Boolean()),
  episode_summaries: Type.Optional(Type.Boolean()),
  open_questions: Type.Optional(Type.Boolean()),
  supporting_evidence: Type.Optional(Type.Boolean()),
});

const TaskContextMaxItemsSchema = Type.Object({
  facts: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
  decisions: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
  open_questions: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
  supporting_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 100 })),
});

export const MemoryRecordDecisionRequestSchema = Type.Object({
  topic_id: Type.String({ minLength: 1 }),
  run_id: Type.Optional(Type.String({ minLength: 1 })),
  decision: Type.String({ minLength: 1 }),
  rationale: Type.String({ minLength: 1 }),
  alternatives_considered: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  source_evidence: Type.Array(EvidenceRefSchema, { minItems: 1 }),
  entity_ids: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  author: Type.Optional(AuthorSchema),
  timestamp: Type.Optional(TimestampSchema),
  consequences: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  idempotency_key: Type.Optional(Type.String({ minLength: 1 })),
  legacy_decision: Type.Optional(LegacyDecisionSchema),
});

export const MemoryGetEntityStateRequestSchema = Type.Object({
  entity_id: Type.Optional(UuidSchema),
  entity_ref: Type.Optional(EntityRefSchema),
  include: Type.Optional(EntityStateIncludeSchema),
  as_of: Type.Optional(TimestampSchema),
  field_filter: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  max_supporting_evidence: Type.Optional(Type.Integer({ minimum: 1, maximum: 100, default: 5 })),
});

export const MemoryUpsertEntityStateRequestSchema = Type.Object({
  entity_id: Type.Optional(UuidSchema),
  entity_ref: Type.Optional(EntityRefSchema),
  display_name: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(Type.Union([
    Type.Literal('active'),
    Type.Literal('inactive'),
    Type.Literal('deleted'),
  ])),
  durable_state: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema, { minProperties: 1 }),
});

export const MemoryGetTaskContextRequestSchema = Type.Object({
  topic_id: Type.String({ minLength: 1 }),
  run_id: Type.Optional(Type.String({ minLength: 1 })),
  include: Type.Optional(TaskContextIncludeSchema),
  max_items: Type.Optional(TaskContextMaxItemsSchema),
  as_of: Type.Optional(TimestampSchema),
});

const EpisodeFactSchema = Type.Object({
  text: Type.String({ minLength: 1 }),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
});

export const MemoryRecordEpisodeSummaryRequestSchema = Type.Object({
  episode_label: Type.Optional(Type.String({ minLength: 1 })),
  topic_id: Type.String({ minLength: 1 }),
  run_id: Type.Optional(Type.String({ minLength: 1 })),
  session_id: Type.Optional(Type.String({ minLength: 1 })),
  summary: Type.String({ minLength: 1 }),
  outcomes: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  key_facts: Type.Optional(Type.Array(EpisodeFactSchema)),
  decisions: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  unresolved_questions: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  source_evidence: Type.Array(EvidenceRefSchema, { minItems: 1 }),
  entity_ids: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  author: Type.Optional(AuthorSchema),
  timestamp: Type.Optional(TimestampSchema),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  idempotency_key: Type.Optional(Type.String({ minLength: 1 })),
});

export const MemoryRecordAnswerArtifactRequestSchema = Type.Object({
  domain_id: Type.String({ minLength: 1 }),
  intent: Type.String({ minLength: 1 }),
  normalized_question: Type.String({ minLength: 1 }),
  question_fingerprint: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  entity_ids: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  answer_text: Type.String({ minLength: 1 }),
  answer_payload: Type.Optional(Type.Record(Type.String({ minLength: 1 }), JsonValueSchema)),
  source_task_id: Type.Optional(Type.String({ minLength: 1 })),
  source_run_id: Type.Optional(Type.String({ minLength: 1 })),
  source_decision_id: Type.Optional(UuidSchema),
  source_episode_summary_id: Type.Optional(UuidSchema),
  evidence_refs: Type.Optional(Type.Array(EvidenceRefSchema)),
  provenance: Type.Optional(Type.Record(Type.String({ minLength: 1 }), JsonValueSchema)),
  freshness_policy: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  validation_contract: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  metadata: Type.Optional(Type.Record(Type.String({ minLength: 1 }), JsonValueSchema)),
  serving_status: Type.Optional(Type.Union([
    Type.Literal('active'),
    Type.Literal('stale'),
    Type.Literal('superseded'),
    Type.Literal('revoked'),
  ])),
  superseded_by: Type.Optional(UuidSchema),
  idempotency_key: Type.Optional(Type.String({ minLength: 1 })),
});

export const MemoryRecallAnswerArtifactsRequestSchema = Type.Object({
  domain_id: Type.String({ minLength: 1 }),
  intent: Type.String({ minLength: 1 }),
  question_fingerprint: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  entity_ids: Type.Optional(Type.Array(Type.String({ minLength: 1 }))),
  serving_statuses: Type.Optional(Type.Array(Type.Union([
    Type.Literal('active'),
    Type.Literal('stale'),
    Type.Literal('superseded'),
    Type.Literal('revoked'),
  ]))),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50, default: 5 })),
});

export const MemoryRecordAnswerValidationRequestSchema = Type.Object({
  answer_artifact_id: UuidSchema,
  validator_type: Type.Optional(Type.String({ minLength: 1 })),
  check_spec: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  observed_values: Type.Record(Type.String({ minLength: 1 }), JsonValueSchema),
  pass: Type.Boolean(),
  failure_reason: Type.Optional(Type.String({ minLength: 1 })),
  latency_ms: Type.Optional(Type.Integer({ minimum: 0 })),
  metadata: Type.Optional(Type.Record(Type.String({ minLength: 1 }), JsonValueSchema)),
  validated_at: Type.Optional(TimestampSchema),
});

export const MemoryRecordRelationRequestSchema = Type.Object({
  source_entity_id: Type.Optional(UuidSchema),
  source_entity_ref: Type.Optional(EntityRefSchema),
  target_entity_id: Type.Optional(UuidSchema),
  target_entity_ref: Type.Optional(EntityRefSchema),
  predicate: Type.String({ minLength: 1 }),
  valid_from: TimestampSchema,
  system_from: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
});

export const MemoryGetRelationsRequestSchema = Type.Object({
  source_entity_id: Type.Optional(UuidSchema),
  source_entity_ref: Type.Optional(EntityRefSchema),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  as_of_valid_time: TimestampSchema,
  as_of_system_time: Type.Optional(TimestampSchema),
});

export const MemoryRecordDecisionResponseSchema = Type.Object({
  decision_id: Type.String({ minLength: 1 }),
  status: Type.Union([
    Type.Literal('recorded'),
    Type.Literal('deduplicated'),
    Type.Literal('rejected'),
  ]),
  stored_at: TimestampSchema,
  topic_id: Type.String(),
  run_id: Type.Optional(Type.String()),
  deduplicated: Type.Boolean(),
  provenance_summary: Type.Optional(
    Type.Object({
      evidence_count: Type.Integer({ minimum: 0 }),
      entity_count: Type.Integer({ minimum: 0 }),
    }),
  ),
});

export const MemoryGetEntityStateResponseSchema = Type.Object({
  entity: Type.Object({
    entity_id: UuidSchema,
    canonical_ref: Type.String({ minLength: 1 }),
    resolved_from: Type.Optional(EntityRefSchema),
    entity_type: Type.String({ minLength: 1 }),
    display_name: Type.String({ minLength: 1 }),
  }),
  durable_state: Type.Record(Type.String(), StateFieldSchema),
  last_observed_state: Type.Record(Type.String(), StateFieldSchema),
  inferred_state: Type.Record(Type.String(), StateFieldSchema),
  freshness: Type.Object({
    as_of: TimestampSchema,
    staleness_seconds: Type.Integer({ minimum: 0 }),
  }),
  conflicts: Type.Array(Type.Record(Type.String(), JsonValueSchema)),
  supporting_evidence: Type.Array(EvidenceRefSchema),
});

export const MemoryUpsertEntityStateResponseSchema = Type.Object({
  entity_id: UuidSchema,
  canonical_ref: Type.String({ minLength: 1 }),
  status: Type.Union([
    Type.Literal('created'),
    Type.Literal('updated'),
  ]),
  stored_at: TimestampSchema,
});

export const MemoryGetTaskContextResponseSchema = Type.Object({
  task: Type.Object({
    topic_id: Type.String({ minLength: 1 }),
    run_id: Type.Optional(Type.String({ minLength: 1 })),
    title: Type.Optional(Type.String({ minLength: 1 })),
    description: Type.Optional(Type.String({ minLength: 1 })),
  }),
  facts: Type.Array(Type.Record(Type.String(), JsonValueSchema)),
  entities: Type.Array(Type.Object({
    entity_id: Type.String({ minLength: 1 }),
    canonical_ref: Type.Optional(Type.String({ minLength: 1 })),
    entity_type: Type.Optional(Type.String({ minLength: 1 })),
    display_name: Type.Optional(Type.String({ minLength: 1 })),
    durable_state: Type.Optional(Type.Record(Type.String(), StateFieldSchema)),
    inferred_state: Type.Optional(Type.Record(Type.String(), StateFieldSchema)),
  })),
  decisions: Type.Array(Type.Object({
    decision_id: Type.String({ minLength: 1 }),
    decision: Type.String({ minLength: 1 }),
    confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
    timestamp: TimestampSchema,
  })),
  episode_summaries: Type.Array(Type.Record(Type.String(), JsonValueSchema)),
  open_questions: Type.Array(Type.Record(Type.String(), JsonValueSchema)),
  supporting_evidence: Type.Array(EvidenceRefSchema),
  freshness: Type.Object({
    as_of: TimestampSchema,
    latest_evidence_at: Type.Optional(TimestampSchema),
  }),
});

export const MemoryRecordEpisodeSummaryResponseSchema = Type.Object({
  episode_summary_id: Type.String({ minLength: 1 }),
  status: Type.Union([
    Type.Literal('recorded'),
    Type.Literal('deduplicated'),
    Type.Literal('rejected'),
  ]),
  stored_at: TimestampSchema,
  topic_id: Type.String(),
  run_id: Type.Optional(Type.String()),
  deduplicated: Type.Boolean(),
  provenance_summary: Type.Optional(
    Type.Object({
      evidence_count: Type.Integer({ minimum: 0 }),
      entity_count: Type.Integer({ minimum: 0 }),
    }),
  ),
});

const MemoryAnswerArtifactSchema = Type.Object({
  answer_artifact_id: UuidSchema,
  domain_id: Type.String({ minLength: 1 }),
  intent: Type.String({ minLength: 1 }),
  normalized_question: Type.String({ minLength: 1 }),
  question_fingerprint: Type.Record(Type.String(), JsonValueSchema),
  entity_ids: Type.Array(Type.String({ minLength: 1 })),
  answer_text: Type.String({ minLength: 1 }),
  answer_payload: Type.Record(Type.String(), JsonValueSchema),
  source_task_id: Type.Optional(Type.String({ minLength: 1 })),
  source_run_id: Type.Optional(Type.String({ minLength: 1 })),
  source_decision_id: Type.Optional(UuidSchema),
  source_episode_summary_id: Type.Optional(UuidSchema),
  evidence_refs: Type.Array(EvidenceRefSchema),
  provenance: Type.Record(Type.String(), JsonValueSchema),
  freshness_policy: Type.Record(Type.String(), JsonValueSchema),
  validation_contract: Type.Record(Type.String(), JsonValueSchema),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  serving_status: Type.String({ minLength: 1 }),
  superseded_by: Type.Optional(UuidSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
});

export const MemoryRecordAnswerArtifactResponseSchema = Type.Object({
  answer_artifact_id: UuidSchema,
  status: Type.Union([Type.Literal('recorded')]),
  stored_at: TimestampSchema,
});

export const MemoryRecallAnswerArtifactsResponseSchema = Type.Object({
  candidates: Type.Array(MemoryAnswerArtifactSchema),
});

export const MemoryRecordAnswerValidationResponseSchema = Type.Object({
  answer_validation_id: UuidSchema,
  answer_artifact_id: UuidSchema,
  status: Type.Union([Type.Literal('recorded')]),
  stored_at: TimestampSchema,
});

const MemoryRelationSchema = Type.Object({
  edge_state_id: Type.String({ minLength: 1 }),
  source_entity_id: UuidSchema,
  predicate: Type.String({ minLength: 1 }),
  target_entity_id: UuidSchema,
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  source_event_id: Type.Optional(UuidSchema),
  confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
});

export const MemoryRecordRelationResponseSchema = MemoryRelationSchema;

export const MemoryGetRelationsResponseSchema = Type.Object({
  relations: Type.Array(MemoryRelationSchema),
});

export const MemoryRecordDecisionRouteSchema = {
  tags: ['memory'],
  body: MemoryRecordDecisionRequestSchema,
  response: {
    201: MemoryRecordDecisionResponseSchema,
    400: ErrorSchema,
    501: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryGetEntityStateRouteSchema = {
  tags: ['memory'],
  body: MemoryGetEntityStateRequestSchema,
  response: {
    200: MemoryGetEntityStateResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryRecordRelationRouteSchema = {
  tags: ['memory'],
  body: MemoryRecordRelationRequestSchema,
  response: {
    201: MemoryRecordRelationResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryGetRelationsRouteSchema = {
  tags: ['memory'],
  body: MemoryGetRelationsRequestSchema,
  response: {
    200: MemoryGetRelationsResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryUpsertEntityStateRouteSchema = {
  tags: ['memory'],
  body: MemoryUpsertEntityStateRequestSchema,
  response: {
    201: MemoryUpsertEntityStateResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryGetTaskContextRouteSchema = {
  tags: ['memory'],
  body: MemoryGetTaskContextRequestSchema,
  response: {
    200: MemoryGetTaskContextResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryRecordEpisodeSummaryRouteSchema = {
  tags: ['memory'],
  body: MemoryRecordEpisodeSummaryRequestSchema,
  response: {
    201: MemoryRecordEpisodeSummaryResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryRecordAnswerArtifactRouteSchema = {
  tags: ['memory'],
  body: MemoryRecordAnswerArtifactRequestSchema,
  response: {
    201: MemoryRecordAnswerArtifactResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryRecallAnswerArtifactsRouteSchema = {
  tags: ['memory'],
  body: MemoryRecallAnswerArtifactsRequestSchema,
  response: {
    200: MemoryRecallAnswerArtifactsResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
} as const;

export const MemoryRecordAnswerValidationRouteSchema = {
  tags: ['memory'],
  body: MemoryRecordAnswerValidationRequestSchema,
  response: {
    201: MemoryRecordAnswerValidationResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema,
  },
} as const;
