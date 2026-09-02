import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { AsOfQuerySchema, JsonValueSchema, TimestampSchema, UuidSchema } from './shared.js';

const PositiveIntegerSchema = Type.Integer({ minimum: 1 });
const OntologyFactDecisionSchema = Type.Union([
  Type.Literal('accept'),
  Type.Literal('reject'),
  Type.Literal('needs_work')
]);
const OntologyFactStatusSchema = Type.Union([
  Type.Literal('accepted'),
  Type.Literal('candidate'),
  Type.Literal('rejected'),
  Type.Literal('needs_review')
]);
const OntologyFactStatusFilterSchema = Type.Union([
  Type.Literal('accepted'),
  Type.Literal('candidate'),
  Type.Literal('rejected'),
  Type.Literal('needs_review'),
  Type.Literal('all')
]);
const OntologyCaseStatusSchema = Type.Union([
  Type.Literal('open'),
  Type.Literal('in_review'),
  Type.Literal('resolved'),
  Type.Literal('dismissed')
]);
const OntologyCaseStatusFilterSchema = Type.Union([
  Type.Literal('open'),
  Type.Literal('in_review'),
  Type.Literal('resolved'),
  Type.Literal('dismissed'),
  Type.Literal('all')
]);
const OntologyCasePrioritySchema = Type.Union([
  Type.Literal('p1'),
  Type.Literal('p2'),
  Type.Literal('p3')
]);
const OntologyAlertSeveritySchema = Type.Union([
  Type.Literal('low'),
  Type.Literal('medium'),
  Type.Literal('high'),
  Type.Literal('critical')
]);
const OntologyAlertStatusSchema = Type.Union([
  Type.Literal('open'),
  Type.Literal('acked'),
  Type.Literal('closed')
]);
const OntologyAlertStatusFilterSchema = Type.Union([
  Type.Literal('open'),
  Type.Literal('acked'),
  Type.Literal('closed'),
  Type.Literal('all')
]);
const OntologyOpsRuleNameSchema = Type.Union([
  Type.Literal('default'),
  Type.Literal('stale_pending'),
  Type.Literal('conflict_predicate')
]);
const MethodologyStatusSchema = Type.Union([
  Type.Literal('draft'),
  Type.Literal('active'),
  Type.Literal('superseded'),
  Type.Literal('archived')
]);
const TaxonomySchemeTypeSchema = Type.Union([
  Type.Literal('classification'),
  Type.Literal('controlled_vocabulary'),
  Type.Literal('relation_taxonomy'),
  Type.Literal('other')
]);

export const RuleUpsertRequestSchema = Type.Object({
  rule_key: Type.String({ minLength: 1, maxLength: 200 }),
  rule_version: Type.Integer({ minimum: 1 }),
  severity: Type.String({ minLength: 1, maxLength: 50 }),
  expression: Type.String({ minLength: 1 }),
  effective_from: TimestampSchema,
  effective_to: Type.Optional(TimestampSchema),
  source_artifact_version_id: Type.Optional(UuidSchema)
});

export const RuleSchema = Type.Object({
  rule_id: UuidSchema,
  rule_key: Type.String(),
  rule_version: Type.Integer({ minimum: 1 }),
  severity: Type.String(),
  expression: Type.String(),
  effective_from: TimestampSchema,
  effective_to: Type.Optional(TimestampSchema),
  source_artifact_version_id: Type.Optional(UuidSchema),
  created_at: TimestampSchema
});

export const AuthorityGrantRequestSchema = Type.Object({
  grantee_id: UuidSchema,
  action_type: Type.String({ minLength: 1, maxLength: 100 }),
  scope: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: Type.Optional(TimestampSchema),
  mandate_artifact_version_id: Type.Optional(UuidSchema)
});

export const AuthorityGrantSchema = Type.Object({
  authority_grant_id: UuidSchema,
  grantee_id: UuidSchema,
  action_type: Type.String(),
  scope: Type.Record(Type.String(), JsonValueSchema),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  mandate_artifact_version_id: Type.Optional(UuidSchema),
  created_at: TimestampSchema
});

export const RuleOverrideRequestSchema = Type.Object({
  rule_key: Type.String({ minLength: 1, maxLength: 200 }),
  rule_version: Type.Integer({ minimum: 1 }),
  authority_grant_id: UuidSchema,
  justification_artifact_version_id: Type.Optional(UuidSchema),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: Type.Optional(TimestampSchema),
  case_id: Type.Optional(PositiveIntegerSchema),
  event_id: Type.Optional(UuidSchema)
});

export const RuleOverrideSchema = Type.Object({
  rule_override_id: UuidSchema,
  rule_key: Type.String(),
  rule_version: Type.Integer({ minimum: 1 }),
  authority_grant_id: UuidSchema,
  justification_artifact_version_id: Type.Optional(UuidSchema),
  valid_from: TimestampSchema,
  valid_to: Type.Optional(TimestampSchema),
  system_from: TimestampSchema,
  system_to: Type.Optional(TimestampSchema),
  case_id: Type.Optional(PositiveIntegerSchema),
  event_id: Type.Optional(UuidSchema),
  created_at: TimestampSchema
});

export const AuthorityCheckQuerySchema = Type.Intersect([
  Type.Object({
    grantee_id: UuidSchema,
    action_type: Type.String({ minLength: 1, maxLength: 100 }),
    scope: Type.Optional(Type.String())
  }),
  AsOfQuerySchema
]);

export const RuleOverrideAsOfQuerySchema = Type.Intersect([
  Type.Object({
    rule_key: Type.String({ minLength: 1, maxLength: 200 }),
    rule_version: Type.Optional(Type.Integer({ minimum: 1 }))
  }),
  AsOfQuerySchema
]);

export const OntologyFactSchema = Type.Object({
  fact_id: PositiveIntegerSchema,
  statement_id: Type.Optional(Type.String({ minLength: 1 })),
  src_concept_id: Type.String(),
  src_concept_label: Type.Optional(Type.String()),
  predicate: Type.String(),
  dst_concept_id: Type.String(),
  dst_concept_label: Type.Optional(Type.String()),
  qualifier_json: Type.Record(Type.String(), JsonValueSchema),
  confidence: Type.Number(),
  extractor: Type.String(),
  status: OntologyFactStatusSchema,
  review_note: Type.String(),
  valid_from: Type.Optional(TimestampSchema),
  valid_to: Type.Optional(TimestampSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const OntologyFactReviewSchema = Type.Object({
  review_id: PositiveIntegerSchema,
  reviewer: Type.String(),
  decision: OntologyFactDecisionSchema,
  note: Type.String(),
  created_at: TimestampSchema
});

export const OntologyFactEvidenceSchema = Type.Object({
  stream_id: Type.String(),
  event_id: Type.String(),
  asset_id: Type.Optional(Type.String()),
  version_number: Type.Optional(PositiveIntegerSchema),
  source_span: Type.Optional(Type.String()),
  evidence_json: Type.Record(Type.String(), JsonValueSchema),
  sentence: Type.Optional(
    Type.Object({
      sent_index: Type.Integer({ minimum: 0 }),
      start_char: Type.Optional(Type.Integer({ minimum: 0 })),
      end_char: Type.Optional(Type.Integer({ minimum: 0 })),
      sentence_text: Type.String({ minLength: 1 })
    })
  ),
  confidence: Type.Number(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const OntologyFactReviewRequestSchema = Type.Object({
  fact_id: PositiveIntegerSchema,
  decision: OntologyFactDecisionSchema,
  reviewer: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  note: Type.Optional(Type.String())
});

export const OntologyFactReviewResultSchema = Type.Object({
  fact_id: PositiveIntegerSchema,
  decision: OntologyFactDecisionSchema,
  reviewer: Type.String(),
  note: Type.String(),
  updated_rows: Type.Integer({ minimum: 0 })
});

export const OntologyFactHistoryQuerySchema = Type.Object({
  fact_id: Type.Optional(Type.Integer({ minimum: 0 })),
  statement_id: Type.Optional(Type.String({ minLength: 1 })),
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 2000 })),
  stream_id: Type.Optional(Type.String({ minLength: 1 }))
});

export const OntologyFactProvenanceQuerySchema = OntologyFactHistoryQuerySchema;

export const OntologyFactHistoryResponseSchema = Type.Object({
  fact: OntologyFactSchema,
  reviews: Type.Array(OntologyFactReviewSchema),
  evidence: Type.Array(OntologyFactEvidenceSchema),
  evidence_count: Type.Integer({ minimum: 0 }),
  stream_id_filter: Type.Optional(Type.String())
});

export const OntologyFactProvenanceResponseSchema = Type.Composite([
  OntologyFactHistoryResponseSchema,
  Type.Object({
    linked_cases: Type.Array(
      Type.Object({
        case_id: PositiveIntegerSchema,
        stream_id: Type.String(),
        title: Type.String(),
        status: OntologyCaseStatusSchema,
        priority: OntologyCasePrioritySchema,
        owner: Type.String(),
        linked_at: TimestampSchema
      })
    ),
    linked_alerts: Type.Array(
      Type.Object({
        alert_id: PositiveIntegerSchema,
        case_id: Type.Optional(PositiveIntegerSchema),
        stream_id: Type.String(),
        severity: OntologyAlertSeveritySchema,
        status: OntologyAlertStatusSchema,
        message: Type.String(),
        rule_key: Type.Optional(Type.String()),
        linked_at: TimestampSchema
      })
    )
  })
]);

export const OntologyFactBulkReviewRequestSchema = Type.Object({
  decision: OntologyFactDecisionSchema,
  status: Type.Optional(OntologyFactStatusFilterSchema),
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  predicate: Type.Optional(Type.String({ minLength: 1 })),
  extractor: Type.Optional(Type.String({ minLength: 1 })),
  stale_days: Type.Optional(Type.Integer({ minimum: 1 })),
  min_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  max_confidence: Type.Optional(Type.Number({ minimum: 0, maximum: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 5000 })),
  reviewer: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  note: Type.Optional(Type.String()),
  dry_run: Type.Optional(Type.Boolean())
});

export const OntologyFactBulkSelectionSchema = Type.Object({
  fact_id: PositiveIntegerSchema,
  status: OntologyFactStatusSchema,
  confidence: Type.Number()
});

export const OntologyFactBulkReviewResponseSchema = Type.Object({
  decision: OntologyFactDecisionSchema,
  status_filter: OntologyFactStatusFilterSchema,
  stream_id_filter: Type.Optional(Type.String()),
  predicate_filter: Type.Optional(Type.String()),
  extractor_filter: Type.Optional(Type.String()),
  stale_days_filter: Type.Optional(PositiveIntegerSchema),
  min_confidence: Type.Number(),
  max_confidence: Type.Number(),
  limit: Type.Integer({ minimum: 1 }),
  dry_run: Type.Boolean(),
  reviewer: Type.String(),
  note: Type.String(),
  selected_count: Type.Integer({ minimum: 0 }),
  updated_rows: Type.Integer({ minimum: 0 }),
  selected_facts: Type.Array(OntologyFactBulkSelectionSchema)
});

export const OntologyCaseSchema = Type.Object({
  case_id: PositiveIntegerSchema,
  stream_id: Type.String(),
  title: Type.String(),
  description: Type.String(),
  status: OntologyCaseStatusSchema,
  priority: OntologyCasePrioritySchema,
  owner: Type.String(),
  created_by: Type.String(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
  closed_at: Type.Optional(TimestampSchema)
});

export const OntologyCaseOpenRequestSchema = Type.Object({
  stream_id: Type.String({ minLength: 1 }),
  title: Type.String({ minLength: 1 }),
  description: Type.Optional(Type.String()),
  priority: Type.Optional(OntologyCasePrioritySchema),
  owner: Type.Optional(Type.String()),
  fact_ids: Type.Optional(Type.Array(PositiveIntegerSchema)),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  note: Type.Optional(Type.String())
});

export const OntologyCaseOpenResponseSchema = Type.Object({
  case_id: PositiveIntegerSchema,
  stream_id: Type.String(),
  title: Type.String(),
  description: Type.String(),
  status: OntologyCaseStatusSchema,
  priority: OntologyCasePrioritySchema,
  owner: Type.String(),
  created_by: Type.String(),
  created_at: TimestampSchema,
  updated_at: TimestampSchema,
  linked_fact_ids: Type.Array(PositiveIntegerSchema),
  skipped_fact_ids: Type.Array(PositiveIntegerSchema)
});

export const OntologyCaseListQuerySchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(OntologyCaseStatusFilterSchema),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 }))
});

export const OntologyCaseSummarySchema = Type.Composite([
  OntologyCaseSchema,
  Type.Object({
    fact_count: Type.Integer({ minimum: 0 }),
    active_alert_count: Type.Integer({ minimum: 0 })
  })
]);

export const OntologyCaseListResponseSchema = Type.Object({
  stream_id_filter: Type.Optional(Type.String()),
  status_filter: OntologyCaseStatusFilterSchema,
  limit: Type.Integer({ minimum: 1 }),
  count: Type.Integer({ minimum: 0 }),
  cases: Type.Array(OntologyCaseSummarySchema)
});

export const OntologyCaseDetailQuerySchema = Type.Object({
  case_id: PositiveIntegerSchema,
  evidence_limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500 }))
});

export const OntologyCaseExplainQuerySchema = OntologyCaseDetailQuerySchema;

export const OntologyCaseDecisionSchema = Type.Object({
  case_decision_id: PositiveIntegerSchema,
  case_id: PositiveIntegerSchema,
  decision_kind: Type.String(),
  verdict: Type.String(),
  summary: Type.String(),
  rationale: Type.String(),
  as_of_system_time: TimestampSchema,
  as_of_effective_time: TimestampSchema,
  snapshot_id: Type.String(),
  source_evidence_json: Type.Array(JsonValueSchema),
  supersedes_case_decision_id: Type.Optional(PositiveIntegerSchema),
  created_by: Type.String(),
  created_at: TimestampSchema
});

export const OntologyCaseDecisionRecordRequestSchema = Type.Object({
  case_id: PositiveIntegerSchema,
  decision_kind: Type.String({ minLength: 1 }),
  verdict: Type.String({ minLength: 1 }),
  summary: Type.String({ minLength: 1 }),
  rationale: Type.Optional(Type.String()),
  as_of_system_time: TimestampSchema,
  as_of_effective_time: Type.Optional(TimestampSchema),
  snapshot_id: Type.Optional(Type.String()),
  source_evidence: Type.Optional(Type.Array(JsonValueSchema)),
  supersedes_case_decision_id: Type.Optional(PositiveIntegerSchema),
  created_by: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

export const OntologyCaseDecisionListQuerySchema = Type.Object({
  case_id: PositiveIntegerSchema
});

export const OntologyCaseDecisionListResponseSchema = Type.Object({
  case_id: PositiveIntegerSchema,
  count: Type.Integer({ minimum: 0 }),
  decisions: Type.Array(OntologyCaseDecisionSchema)
});

export const OntologyCaseConflictDraftRequestSchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  predicate: Type.String({ minLength: 1 }),
  src_concept_id: Type.String({ minLength: 1 }),
  case_id: Type.Optional(PositiveIntegerSchema),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 })),
  dry_run: Type.Optional(Type.Boolean())
});

export const OntologyCaseConflictDraftCandidateSchema = Type.Object({
  stream_id: Type.String(),
  src_concept_id: Type.String(),
  predicate: Type.String(),
  dst_values: Type.Array(Type.String()),
  dst_count: Type.Integer(),
  fact_count: Type.Integer(),
  fact_ids: Type.Array(PositiveIntegerSchema)
});

export const OntologyCaseConflictDraftResponseSchema = Type.Object({
  case: Type.Optional(OntologyCaseSchema),
  decision: Type.Optional(OntologyCaseDecisionSchema),
  created_case: Type.Boolean(),
  deduped: Type.Boolean(),
  candidate: OntologyCaseConflictDraftCandidateSchema
});

export const OntologyCaseFactSchema = Type.Object({
  fact_id: PositiveIntegerSchema,
  src_concept_id: Type.String(),
  predicate: Type.String(),
  dst_concept_id: Type.String(),
  confidence: Type.Number(),
  status: OntologyFactStatusSchema,
  extractor: Type.String(),
  updated_at: TimestampSchema,
  linked_at: TimestampSchema,
  added_by: Type.String(),
  added_note: Type.String(),
  evidence_count: Type.Integer({ minimum: 0 }),
  evidence_sample: Type.Array(
    Type.Object({
      stream_id: Type.String(),
      event_id: Type.String(),
      session_id: Type.String(),
      updated_at: TimestampSchema,
      source_span: Type.Optional(Type.String()),
      text_snippet: Type.String()
    })
  )
});

export const OntologyCaseEventSchema = Type.Object({
  event_id: PositiveIntegerSchema,
  action: Type.String(),
  actor: Type.String(),
  note: Type.String(),
  payload_json: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema
});

export const OntologyAlertSchema = Type.Object({
  alert_id: PositiveIntegerSchema,
  case_id: Type.Optional(PositiveIntegerSchema),
  stream_id: Type.String(),
  severity: OntologyAlertSeveritySchema,
  status: OntologyAlertStatusSchema,
  message: Type.String(),
  detail_json: Type.Record(Type.String(), JsonValueSchema),
  rule_key: Type.Optional(Type.String()),
  trigger_count: Type.Integer({ minimum: 1 }),
  first_triggered_at: TimestampSchema,
  last_triggered_at: TimestampSchema,
  acked_by: Type.Optional(Type.String()),
  acked_at: Type.Optional(TimestampSchema),
  closed_at: Type.Optional(TimestampSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const OntologyCaseDetailResponseSchema = Type.Object({
  case: OntologyCaseSchema,
  facts: Type.Array(OntologyCaseFactSchema),
  decisions: Type.Array(OntologyCaseDecisionSchema),
  events: Type.Array(OntologyCaseEventSchema),
  alerts: Type.Array(
    Type.Composite([
      OntologyAlertSchema,
      Type.Object({
        linked_fact_ids: Type.Array(PositiveIntegerSchema)
      })
    ])
  ),
  evidence_limit: Type.Integer({ minimum: 1 })
});

export const OntologyCaseExplainResponseSchema = Type.Composite([
  OntologyCaseDetailResponseSchema,
  Type.Object({
    explanation: Type.Object({
      summary: Type.String(),
      fact_count: Type.Integer({ minimum: 0 }),
      event_count: Type.Integer({ minimum: 0 }),
      alert_count: Type.Integer({ minimum: 0 }),
      active_alert_count: Type.Integer({ minimum: 0 }),
      latest_event_action: Type.Optional(Type.String()),
      reasoning_steps: Type.Array(Type.String()),
      flags: Type.Array(Type.String())
    })
  })
]);

export const OntologyCaseUpdateRequestSchema = Type.Object({
  case_id: PositiveIntegerSchema,
  status: Type.Optional(OntologyCaseStatusSchema),
  owner: Type.Optional(Type.String()),
  note: Type.Optional(Type.String()),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

export const OntologyAlertOpenRequestSchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  case_id: Type.Optional(PositiveIntegerSchema),
  message: Type.String({ minLength: 1 }),
  severity: Type.Optional(OntologyAlertSeveritySchema),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

export const OntologyAlertListQuerySchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(OntologyAlertStatusFilterSchema),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 }))
});

export const OntologyAlertExplainQuerySchema = Type.Object({
  alert_id: PositiveIntegerSchema
});

export const OntologyAlertSummarySchema = Type.Composite([
  OntologyAlertSchema,
  Type.Object({
    case_title: Type.Optional(Type.String()),
    linked_fact_count: Type.Integer({ minimum: 0 })
  })
]);

export const OntologyAlertListResponseSchema = Type.Object({
  stream_id_filter: Type.Optional(Type.String()),
  status_filter: OntologyAlertStatusFilterSchema,
  limit: Type.Integer({ minimum: 1 }),
  count: Type.Integer({ minimum: 0 }),
  alerts: Type.Array(OntologyAlertSummarySchema)
});

export const OntologyAlertExplainResponseSchema = Type.Object({
  alert: Type.Composite([
    OntologyAlertSchema,
    Type.Object({
      case_title: Type.Optional(Type.String()),
      linked_fact_count: Type.Integer({ minimum: 0 }),
      linked_fact_ids: Type.Array(PositiveIntegerSchema)
    })
  ]),
  case: Type.Optional(OntologyCaseSchema),
  explanation: Type.Object({
    summary: Type.String(),
    source: Type.Union([Type.Literal('manual'), Type.Literal('rule')]),
    active: Type.Boolean(),
    case_bound: Type.Boolean(),
    linked_fact_count: Type.Integer({ minimum: 0 }),
    reasoning_steps: Type.Array(Type.String()),
    flags: Type.Array(Type.String())
  })
});

export const OntologyAlertUpdateRequestSchema = Type.Object({
  alert_id: PositiveIntegerSchema,
  status: OntologyAlertStatusSchema,
  note: Type.Optional(Type.String()),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

export const OntologyOpsRuleConfigSchema = Type.Object({
  config_id: PositiveIntegerSchema,
  stream_id: Type.Optional(Type.String()),
  rule_name: OntologyOpsRuleNameSchema,
  enabled: Type.Boolean(),
  stale_days: Type.Optional(PositiveIntegerSchema),
  conflict_predicate: Type.Optional(Type.String()),
  severity: Type.Optional(OntologyAlertSeveritySchema),
  note: Type.String(),
  updated_by: Type.String(),
  updated_at: TimestampSchema
});

export const OntologyOpsRuleConfigListQuerySchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 }))
});

export const OntologyOpsRuleConfigListResponseSchema = Type.Object({
  stream_id_filter: Type.Optional(Type.String()),
  count: Type.Integer({ minimum: 0 }),
  configs: Type.Array(OntologyOpsRuleConfigSchema)
});

export const OntologyOpsRuleConfigUpsertRequestSchema = Type.Object({
  rule_name: OntologyOpsRuleNameSchema,
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  enabled: Type.Optional(Type.Boolean()),
  stale_days: Type.Optional(PositiveIntegerSchema),
  conflict_predicate: Type.Optional(Type.String({ minLength: 1 })),
  severity: Type.Optional(OntologyAlertSeveritySchema),
  note: Type.Optional(Type.String()),
  updated_by: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

export const OntologyOpsRuleRunRequestSchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  stale_days: Type.Optional(PositiveIntegerSchema),
  conflict_predicate: Type.Optional(Type.String({ minLength: 1 })),
  dry_run: Type.Optional(Type.Boolean()),
  actor: Type.Optional(Type.String({ minLength: 1, maxLength: 200 }))
});

const JsonObjectArraySchema = Type.Array(Type.Record(Type.String(), JsonValueSchema));

export const OntologyOpsRuleRunResultSchema = Type.Object({
  stream_id_filter: Type.Optional(Type.String()),
  stale_days: PositiveIntegerSchema,
  conflict_predicate: Type.String(),
  rules_enabled: Type.Object({
    stale_pending: Type.Boolean(),
    conflict_predicate: Type.Boolean()
  }),
  rule_severity: Type.Object({
    stale_pending: OntologyAlertSeveritySchema,
    conflict_predicate: OntologyAlertSeveritySchema
  }),
  dry_run: Type.Boolean(),
  candidate_count: Type.Integer({ minimum: 0 }),
  candidates: JsonObjectArraySchema,
  created_cases: JsonObjectArraySchema,
  existing_cases: JsonObjectArraySchema,
  created_alerts: JsonObjectArraySchema,
  existing_alerts: JsonObjectArraySchema
});

export const OntologyOpsRuleRunRecordSchema = Type.Object({
  run_id: PositiveIntegerSchema,
  stream_id_filter: Type.Optional(Type.String()),
  stale_days: PositiveIntegerSchema,
  conflict_predicate: Type.String(),
  dry_run: Type.Boolean(),
  candidate_count: Type.Integer({ minimum: 0 }),
  created_case_count: Type.Integer({ minimum: 0 }),
  existing_case_count: Type.Integer({ minimum: 0 }),
  created_alert_count: Type.Integer({ minimum: 0 }),
  existing_alert_count: Type.Integer({ minimum: 0 }),
  duration_ms: Type.Integer({ minimum: 0 }),
  started_at: TimestampSchema,
  finished_at: TimestampSchema
});

export const OntologyOpsRuleRunListQuerySchema = Type.Object({
  stream_id: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 1000 }))
});

export const OntologyOpsRuleRunExplainQuerySchema = Type.Object({
  run_id: PositiveIntegerSchema
});

export const OntologyOpsRuleRunListResponseSchema = Type.Object({
  stream_id_filter: Type.Optional(Type.String()),
  limit: Type.Integer({ minimum: 1 }),
  count: Type.Integer({ minimum: 0 }),
  runs: Type.Array(OntologyOpsRuleRunRecordSchema)
});

export const OntologyOpsRuleRunExplainResponseSchema = Type.Object({
  run: OntologyOpsRuleRunRecordSchema,
  payload: OntologyOpsRuleRunResultSchema,
  explanation: Type.Object({
    summary: Type.String(),
    triggered_rules: Type.Array(Type.String()),
    candidate_count: Type.Integer({ minimum: 0 }),
    action_count: Type.Integer({ minimum: 0 }),
    dry_run: Type.Boolean(),
    reasoning_steps: Type.Array(Type.String()),
    flags: Type.Array(Type.String())
  })
});

export const MethodologyFrameworkSchema = Type.Object({
  framework_id: UuidSchema,
  domain: Type.String(),
  framework_name: Type.String(),
  version_label: Type.String(),
  status: MethodologyStatusSchema,
  description: Type.String(),
  owner: Type.String(),
  question_types: Type.Array(Type.String()),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const MethodologyFrameworkUpsertRequestSchema = Type.Object({
  framework_id: Type.Optional(UuidSchema),
  domain: Type.String({ minLength: 1 }),
  framework_name: Type.String({ minLength: 1 }),
  version_label: Type.String({ minLength: 1 }),
  status: Type.Optional(MethodologyStatusSchema),
  description: Type.Optional(Type.String()),
  owner: Type.Optional(Type.String()),
  question_types: Type.Optional(Type.Array(Type.String())),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const MethodologyFrameworkGetQuerySchema = Type.Object({
  framework_id: UuidSchema
});

export const MethodologyFrameworkListQuerySchema = Type.Object({
  domain: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(MethodologyStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200, default: 50 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const TaxonomySchemeSchema = Type.Object({
  scheme_id: UuidSchema,
  framework_id: UuidSchema,
  scheme_name: Type.String(),
  scheme_type: TaxonomySchemeTypeSchema,
  status: MethodologyStatusSchema,
  description: Type.String(),
  canonical_source: Type.String(),
  scheme: Type.Record(Type.String(), JsonValueSchema),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const TaxonomySchemeUpsertRequestSchema = Type.Object({
  scheme_id: Type.Optional(UuidSchema),
  framework_id: UuidSchema,
  scheme_name: Type.String({ minLength: 1 }),
  scheme_type: TaxonomySchemeTypeSchema,
  status: Type.Optional(MethodologyStatusSchema),
  description: Type.Optional(Type.String()),
  canonical_source: Type.Optional(Type.String()),
  scheme: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const TaxonomySchemeGetQuerySchema = Type.Object({
  scheme_id: UuidSchema
});

export const TaxonomySchemeListQuerySchema = Type.Object({
  framework_id: Type.Optional(UuidSchema),
  scheme_type: Type.Optional(TaxonomySchemeTypeSchema),
  status: Type.Optional(MethodologyStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const EvidencePolicyRuleSchema = Type.Object({
  evidence_policy_rule_id: UuidSchema,
  framework_id: UuidSchema,
  rule_key: Type.String(),
  question_type: Type.String(),
  evidence_kind: Type.String(),
  source_tier: Type.String(),
  status: MethodologyStatusSchema,
  priority: Type.Integer({ minimum: 0 }),
  review_required: Type.Boolean(),
  applicability: Type.Record(Type.String(), JsonValueSchema),
  effect: Type.Record(Type.String(), JsonValueSchema),
  description: Type.String(),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const EvidencePolicyRuleUpsertRequestSchema = Type.Object({
  evidence_policy_rule_id: Type.Optional(UuidSchema),
  framework_id: UuidSchema,
  rule_key: Type.String({ minLength: 1 }),
  question_type: Type.Optional(Type.String()),
  evidence_kind: Type.Optional(Type.String()),
  source_tier: Type.Optional(Type.String()),
  status: Type.Optional(MethodologyStatusSchema),
  priority: Type.Optional(Type.Integer({ minimum: 0 })),
  review_required: Type.Optional(Type.Boolean()),
  applicability: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  effect: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  description: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const EvidencePolicyRuleGetQuerySchema = Type.Object({
  evidence_policy_rule_id: UuidSchema
});

export const EvidencePolicyRuleListQuerySchema = Type.Object({
  framework_id: Type.Optional(UuidSchema),
  question_type: Type.Optional(Type.String()),
  evidence_kind: Type.Optional(Type.String()),
  status: Type.Optional(MethodologyStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const AssertionPolicyRuleSchema = Type.Object({
  assertion_policy_rule_id: UuidSchema,
  framework_id: UuidSchema,
  rule_key: Type.String(),
  assertion_type: Type.String(),
  question_type: Type.String(),
  status: MethodologyStatusSchema,
  priority: Type.Integer({ minimum: 0 }),
  review_required: Type.Boolean(),
  required_evidence: Type.Record(Type.String(), JsonValueSchema),
  outcome: Type.Record(Type.String(), JsonValueSchema),
  description: Type.String(),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const AssertionPolicyRuleUpsertRequestSchema = Type.Object({
  assertion_policy_rule_id: Type.Optional(UuidSchema),
  framework_id: UuidSchema,
  rule_key: Type.String({ minLength: 1 }),
  assertion_type: Type.String({ minLength: 1 }),
  question_type: Type.Optional(Type.String()),
  status: Type.Optional(MethodologyStatusSchema),
  priority: Type.Optional(Type.Integer({ minimum: 0 })),
  review_required: Type.Optional(Type.Boolean()),
  required_evidence: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  outcome: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  description: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const AssertionPolicyRuleGetQuerySchema = Type.Object({
  assertion_policy_rule_id: UuidSchema
});

export const AssertionPolicyRuleListQuerySchema = Type.Object({
  framework_id: Type.Optional(UuidSchema),
  assertion_type: Type.Optional(Type.String({ minLength: 1 })),
  question_type: Type.Optional(Type.String()),
  status: Type.Optional(MethodologyStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const ReviewPolicySchema = Type.Object({
  review_policy_id: UuidSchema,
  framework_id: UuidSchema,
  policy_key: Type.String(),
  question_type: Type.String(),
  trigger_kind: Type.String(),
  action: Type.String(),
  status: MethodologyStatusSchema,
  priority: Type.Integer({ minimum: 0 }),
  trigger: Type.Record(Type.String(), JsonValueSchema),
  description: Type.String(),
  metadata: Type.Record(Type.String(), JsonValueSchema),
  created_at: TimestampSchema,
  updated_at: TimestampSchema
});

export const ReviewPolicyUpsertRequestSchema = Type.Object({
  review_policy_id: Type.Optional(UuidSchema),
  framework_id: UuidSchema,
  policy_key: Type.String({ minLength: 1 }),
  question_type: Type.Optional(Type.String()),
  trigger_kind: Type.String({ minLength: 1 }),
  action: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(MethodologyStatusSchema),
  priority: Type.Optional(Type.Integer({ minimum: 0 })),
  trigger: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  description: Type.Optional(Type.String()),
  metadata: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const ReviewPolicyGetQuerySchema = Type.Object({
  review_policy_id: UuidSchema
});

export const ReviewPolicyListQuerySchema = Type.Object({
  framework_id: Type.Optional(UuidSchema),
  question_type: Type.Optional(Type.String()),
  trigger_kind: Type.Optional(Type.String({ minLength: 1 })),
  status: Type.Optional(MethodologyStatusSchema),
  q: Type.Optional(Type.String({ minLength: 1 })),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 500, default: 100 })),
  offset: Type.Optional(Type.Integer({ minimum: 0, maximum: 10000, default: 0 }))
});

export const MethodologyFrameworkBundleSchema = Type.Object({
  framework: Type.Optional(MethodologyFrameworkSchema),
  taxonomy_schemes: Type.Array(TaxonomySchemeSchema),
  evidence_policy_rules: Type.Array(EvidencePolicyRuleSchema),
  assertion_policy_rules: Type.Array(AssertionPolicyRuleSchema),
  review_policies: Type.Array(ReviewPolicySchema)
});

export const RuleUpsertRouteSchema = {
  tags: ['governance'],
  body: RuleUpsertRequestSchema,
  response: { 201: RuleSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const MethodologyFrameworkUpsertRouteSchema = {
  tags: ['governance'],
  body: MethodologyFrameworkUpsertRequestSchema,
  response: { 201: MethodologyFrameworkSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const MethodologyFrameworkGetRouteSchema = {
  tags: ['governance'],
  querystring: MethodologyFrameworkGetQuerySchema,
  response: { 200: Type.Object({ framework: Type.Optional(MethodologyFrameworkSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const MethodologyFrameworkListRouteSchema = {
  tags: ['governance'],
  querystring: MethodologyFrameworkListQuerySchema,
  response: { 200: Type.Object({ frameworks: Type.Array(MethodologyFrameworkSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const MethodologyFrameworkBundleRouteSchema = {
  tags: ['governance'],
  querystring: MethodologyFrameworkGetQuerySchema,
  response: { 200: MethodologyFrameworkBundleSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const TaxonomySchemeUpsertRouteSchema = {
  tags: ['governance'],
  body: TaxonomySchemeUpsertRequestSchema,
  response: { 201: TaxonomySchemeSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const TaxonomySchemeGetRouteSchema = {
  tags: ['governance'],
  querystring: TaxonomySchemeGetQuerySchema,
  response: { 200: Type.Object({ scheme: Type.Optional(TaxonomySchemeSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const TaxonomySchemeListRouteSchema = {
  tags: ['governance'],
  querystring: TaxonomySchemeListQuerySchema,
  response: { 200: Type.Object({ schemes: Type.Array(TaxonomySchemeSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const EvidencePolicyRuleUpsertRouteSchema = {
  tags: ['governance'],
  body: EvidencePolicyRuleUpsertRequestSchema,
  response: { 201: EvidencePolicyRuleSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const EvidencePolicyRuleGetRouteSchema = {
  tags: ['governance'],
  querystring: EvidencePolicyRuleGetQuerySchema,
  response: { 200: Type.Object({ rule: Type.Optional(EvidencePolicyRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const EvidencePolicyRuleListRouteSchema = {
  tags: ['governance'],
  querystring: EvidencePolicyRuleListQuerySchema,
  response: { 200: Type.Object({ rules: Type.Array(EvidencePolicyRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionPolicyRuleUpsertRouteSchema = {
  tags: ['governance'],
  body: AssertionPolicyRuleUpsertRequestSchema,
  response: { 201: AssertionPolicyRuleSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionPolicyRuleGetRouteSchema = {
  tags: ['governance'],
  querystring: AssertionPolicyRuleGetQuerySchema,
  response: { 200: Type.Object({ rule: Type.Optional(AssertionPolicyRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AssertionPolicyRuleListRouteSchema = {
  tags: ['governance'],
  querystring: AssertionPolicyRuleListQuerySchema,
  response: { 200: Type.Object({ rules: Type.Array(AssertionPolicyRuleSchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const ReviewPolicyUpsertRouteSchema = {
  tags: ['governance'],
  body: ReviewPolicyUpsertRequestSchema,
  response: { 201: ReviewPolicySchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const ReviewPolicyGetRouteSchema = {
  tags: ['governance'],
  querystring: ReviewPolicyGetQuerySchema,
  response: { 200: Type.Object({ policy: Type.Optional(ReviewPolicySchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const ReviewPolicyListRouteSchema = {
  tags: ['governance'],
  querystring: ReviewPolicyListQuerySchema,
  response: { 200: Type.Object({ policies: Type.Array(ReviewPolicySchema) }), 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AuthorityGrantRouteSchema = {
  tags: ['governance'],
  body: AuthorityGrantRequestSchema,
  response: { 201: AuthorityGrantSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const RuleOverrideRouteSchema = {
  tags: ['governance'],
  body: RuleOverrideRequestSchema,
  response: { 201: RuleOverrideSchema, 400: ErrorSchema, 500: ErrorSchema }
} as const;

export const AuthorityCheckRouteSchema = {
  tags: ['governance'],
  querystring: AuthorityCheckQuerySchema,
  response: {
    200: Type.Object({ allowed: Type.Boolean(), authority_grant: Type.Optional(AuthorityGrantSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const RuleOverrideAsOfRouteSchema = {
  tags: ['governance'],
  querystring: RuleOverrideAsOfQuerySchema,
  response: {
    200: Type.Object({ overrides: Type.Array(RuleOverrideSchema) }),
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyFactReviewRouteSchema = {
  tags: ['governance'],
  body: OntologyFactReviewRequestSchema,
  response: {
    200: OntologyFactReviewResultSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyFactHistoryRouteSchema = {
  tags: ['governance'],
  querystring: OntologyFactHistoryQuerySchema,
  response: {
    200: OntologyFactHistoryResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyFactProvenanceRouteSchema = {
  tags: ['governance'],
  querystring: OntologyFactProvenanceQuerySchema,
  response: {
    200: OntologyFactProvenanceResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyFactBulkReviewRouteSchema = {
  tags: ['governance'],
  body: OntologyFactBulkReviewRequestSchema,
  response: {
    200: OntologyFactBulkReviewResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseOpenRouteSchema = {
  tags: ['governance'],
  body: OntologyCaseOpenRequestSchema,
  response: {
    201: OntologyCaseOpenResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseListRouteSchema = {
  tags: ['governance'],
  querystring: OntologyCaseListQuerySchema,
  response: {
    200: OntologyCaseListResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseDecisionRecordRouteSchema = {
  tags: ['governance'],
  body: OntologyCaseDecisionRecordRequestSchema,
  response: {
    201: OntologyCaseDecisionSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseDecisionListRouteSchema = {
  tags: ['governance'],
  querystring: OntologyCaseDecisionListQuerySchema,
  response: {
    200: OntologyCaseDecisionListResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseConflictDraftRouteSchema = {
  tags: ['governance'],
  body: OntologyCaseConflictDraftRequestSchema,
  response: {
    200: OntologyCaseConflictDraftResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseDetailRouteSchema = {
  tags: ['governance'],
  querystring: OntologyCaseDetailQuerySchema,
  response: {
    200: OntologyCaseDetailResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseExplainRouteSchema = {
  tags: ['governance'],
  querystring: OntologyCaseExplainQuerySchema,
  response: {
    200: OntologyCaseExplainResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyCaseUpdateRouteSchema = {
  tags: ['governance'],
  body: OntologyCaseUpdateRequestSchema,
  response: {
    200: OntologyCaseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyAlertOpenRouteSchema = {
  tags: ['governance'],
  body: OntologyAlertOpenRequestSchema,
  response: {
    201: OntologyAlertSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    409: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyAlertListRouteSchema = {
  tags: ['governance'],
  querystring: OntologyAlertListQuerySchema,
  response: {
    200: OntologyAlertListResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyAlertExplainRouteSchema = {
  tags: ['governance'],
  querystring: OntologyAlertExplainQuerySchema,
  response: {
    200: OntologyAlertExplainResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyAlertUpdateRouteSchema = {
  tags: ['governance'],
  body: OntologyAlertUpdateRequestSchema,
  response: {
    200: OntologyAlertSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyOpsRuleConfigListRouteSchema = {
  tags: ['governance'],
  querystring: OntologyOpsRuleConfigListQuerySchema,
  response: {
    200: OntologyOpsRuleConfigListResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyOpsRuleConfigUpsertRouteSchema = {
  tags: ['governance'],
  body: OntologyOpsRuleConfigUpsertRequestSchema,
  response: {
    200: OntologyOpsRuleConfigSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyOpsRuleRunRouteSchema = {
  tags: ['governance'],
  body: OntologyOpsRuleRunRequestSchema,
  response: {
    200: OntologyOpsRuleRunResultSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    409: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyOpsRuleRunListRouteSchema = {
  tags: ['governance'],
  querystring: OntologyOpsRuleRunListQuerySchema,
  response: {
    200: OntologyOpsRuleRunListResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const OntologyOpsRuleRunExplainRouteSchema = {
  tags: ['governance'],
  querystring: OntologyOpsRuleRunExplainQuerySchema,
  response: {
    200: OntologyOpsRuleRunExplainResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;
