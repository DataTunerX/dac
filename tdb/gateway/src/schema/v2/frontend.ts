import { Type } from '@sinclair/typebox';

import { ErrorSchema } from './common.js';
import { JsonValueSchema, TimestampSchema } from './shared.js';

const ContractVersionSchema = Type.Literal('business_frontend_v1');
const ConfidenceSchema = Type.Number({ minimum: 0, maximum: 1 });
const PrioritySchema = Type.Integer({ minimum: 0, maximum: 100 });
const CountSchema = Type.Integer({ minimum: 0 });
const GenericIdSchema = Type.String({ minLength: 1, maxLength: 200 });
const GenericLabelSchema = Type.String({ minLength: 1, maxLength: 200 });
const GenericTextSchema = Type.String({ minLength: 1 });

export const EnterpriseRoleSchema = Type.Union([
  Type.Literal('operator'),
  Type.Literal('reviewer'),
  Type.Literal('approver'),
  Type.Literal('manager'),
  Type.Literal('analyst'),
  Type.Literal('executive'),
  Type.Literal('admin')
]);

export const EnterprisePageTypeSchema = Type.Union([
  Type.Literal('workbench'),
  Type.Literal('inbox'),
  Type.Literal('object_360'),
  Type.Literal('approval_review'),
  Type.Literal('investigation_workspace'),
  Type.Literal('form_surface'),
  Type.Literal('search')
]);

export const BlockTypeSchema = Type.Union([
  Type.Literal('summary_block'),
  Type.Literal('status_strip'),
  Type.Literal('metric_strip'),
  Type.Literal('risk_block'),
  Type.Literal('warning_block'),
  Type.Literal('recommendation_block'),
  Type.Literal('approval_brief_block'),
  Type.Literal('timeline_block'),
  Type.Literal('artifact_list_block'),
  Type.Literal('decision_trace_block'),
  Type.Literal('exception_block'),
  Type.Literal('field_suggestion_block'),
  Type.Literal('impact_preview_block')
]);

export const SeveritySchema = Type.Union([
  Type.Literal('info'),
  Type.Literal('low'),
  Type.Literal('medium'),
  Type.Literal('high'),
  Type.Literal('critical')
]);

export const HealthSchema = Type.Union([
  Type.Literal('healthy'),
  Type.Literal('watch'),
  Type.Literal('at_risk'),
  Type.Literal('blocked')
]);

export const ActionStyleSchema = Type.Union([
  Type.Literal('primary'),
  Type.Literal('secondary'),
  Type.Literal('danger'),
  Type.Literal('ghost')
]);

export const SimulationStatusSchema = Type.Union([
  Type.Literal('ready'),
  Type.Literal('needs_confirmation'),
  Type.Literal('blocked')
]);

export const BusinessObjectRefSchema = Type.Object({
  object_id: GenericIdSchema,
  object_type: GenericLabelSchema,
  display_name: Type.Optional(GenericTextSchema),
  source_system: Type.Optional(GenericLabelSchema),
  external_ref: Type.Optional(GenericLabelSchema)
});

export const FactItemSchema = Type.Object({
  key: GenericLabelSchema,
  label: GenericLabelSchema,
  value: JsonValueSchema,
  display_value: Type.Optional(GenericTextSchema),
  confidence: Type.Optional(ConfidenceSchema)
});

export const StatusItemSchema = Type.Object({
  key: GenericLabelSchema,
  label: GenericLabelSchema,
  value: GenericTextSchema,
  severity: Type.Optional(SeveritySchema)
});

export const MetricItemSchema = Type.Object({
  key: GenericLabelSchema,
  label: GenericLabelSchema,
  value: GenericTextSchema,
  trend: Type.Optional(
    Type.Union([Type.Literal('up'), Type.Literal('down'), Type.Literal('flat'), Type.Literal('mixed')])
  ),
  severity: Type.Optional(SeveritySchema)
});

export const BusinessObjectLinkSchema = Type.Object({
  relation: GenericLabelSchema,
  object: BusinessObjectRefSchema,
  status: Type.Optional(GenericTextSchema)
});

export const EvidenceRefSchema = Type.Object({
  evidence_id: GenericIdSchema,
  kind: Type.Union([
    Type.Literal('event'),
    Type.Literal('artifact_version'),
    Type.Literal('decision'),
    Type.Literal('policy'),
    Type.Literal('state'),
    Type.Literal('external_record')
  ]),
  label: GenericTextSchema,
  summary: Type.Optional(GenericTextSchema),
  freshness: Type.Optional(TimestampSchema),
  citation: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  object_ref: Type.Optional(BusinessObjectRefSchema)
});

export const RecommendedActionSchema = Type.Object({
  action_key: GenericLabelSchema,
  label: GenericTextSchema,
  style: Type.Optional(ActionStyleSchema),
  reason: Type.Optional(GenericTextSchema),
  confidence: Type.Optional(ConfidenceSchema),
  requires_confirmation: Type.Optional(Type.Boolean()),
  required_permissions: Type.Optional(Type.Array(GenericLabelSchema)),
  args_hint: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const TimelineItemSchema = Type.Object({
  item_id: GenericIdSchema,
  timestamp: TimestampSchema,
  kind: Type.Union([
    Type.Literal('state_change'),
    Type.Literal('approval'),
    Type.Literal('exception'),
    Type.Literal('artifact'),
    Type.Literal('external_update'),
    Type.Literal('user_action')
  ]),
  title: GenericTextSchema,
  summary: Type.Optional(GenericTextSchema),
  actor: Type.Optional(GenericLabelSchema),
  severity: Type.Optional(SeveritySchema),
  evidence_refs: Type.Optional(Type.Array(EvidenceRefSchema))
});

export const ArtifactItemSchema = Type.Object({
  artifact_id: GenericIdSchema,
  artifact_type: GenericLabelSchema,
  name: GenericTextSchema,
  status: Type.Optional(GenericTextSchema),
  freshness: Type.Optional(TimestampSchema),
  summary: Type.Optional(GenericTextSchema),
  evidence_ref: Type.Optional(EvidenceRefSchema)
});

export const DecisionTraceItemSchema = Type.Object({
  decision_id: GenericIdSchema,
  title: GenericTextSchema,
  chosen_action: GenericTextSchema,
  summary: Type.Optional(GenericTextSchema),
  confidence: Type.Optional(ConfidenceSchema),
  created_at: TimestampSchema
});

export const ExceptionItemSchema = Type.Object({
  exception_id: GenericIdSchema,
  code: GenericLabelSchema,
  title: GenericTextSchema,
  severity: SeveritySchema,
  status: Type.Union([
    Type.Literal('open'),
    Type.Literal('acked'),
    Type.Literal('resolved'),
    Type.Literal('dismissed')
  ]),
  summary: Type.Optional(GenericTextSchema),
  due_at: Type.Optional(TimestampSchema),
  owner: Type.Optional(GenericLabelSchema),
  recommended_action: Type.Optional(RecommendedActionSchema),
  evidence_refs: Type.Optional(Type.Array(EvidenceRefSchema))
});

export const MissingInfoItemSchema = Type.Object({
  key: GenericLabelSchema,
  label: GenericTextSchema,
  reason: Type.Optional(GenericTextSchema),
  required_for: Type.Optional(GenericTextSchema)
});

export const ImpactChangeSchema = Type.Object({
  object: BusinessObjectRefSchema,
  field: GenericLabelSchema,
  before: JsonValueSchema,
  after: JsonValueSchema,
  summary: Type.Optional(GenericTextSchema)
});

export const FieldSuggestionSchema = Type.Object({
  field_key: GenericLabelSchema,
  label: GenericTextSchema,
  suggested_value: JsonValueSchema,
  display_value: Type.Optional(GenericTextSchema),
  reason: Type.Optional(GenericTextSchema),
  confidence: Type.Optional(ConfidenceSchema)
});

export const PageSummarySchema = Type.Object({
  title: GenericTextSchema,
  subtitle: Type.Optional(GenericTextSchema),
  status: Type.Optional(GenericTextSchema),
  health: Type.Optional(HealthSchema),
  confidence: Type.Optional(ConfidenceSchema),
  freshness: Type.Optional(TimestampSchema),
  why_it_matters: Type.Optional(GenericTextSchema)
});

const UiBlockBaseSchema = Type.Object({
  block_id: GenericIdSchema,
  title: GenericTextSchema,
  priority: Type.Optional(PrioritySchema),
  confidence: Type.Optional(ConfidenceSchema),
  freshness: Type.Optional(TimestampSchema),
  actions: Type.Optional(Type.Array(RecommendedActionSchema)),
  evidence_refs: Type.Optional(Type.Array(EvidenceRefSchema))
});

export const SummaryBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('summary_block'),
    summary: GenericTextSchema,
    supporting_points: Type.Optional(Type.Array(GenericTextSchema))
  })
]);

export const StatusStripBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('status_strip'),
    items: Type.Array(StatusItemSchema, { minItems: 1 })
  })
]);

export const MetricStripBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('metric_strip'),
    items: Type.Array(MetricItemSchema, { minItems: 1 })
  })
]);

export const RiskBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('risk_block'),
    severity: SeveritySchema,
    summary: GenericTextSchema,
    risk_items: Type.Array(GenericTextSchema, { minItems: 1 })
  })
]);

export const WarningBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('warning_block'),
    severity: SeveritySchema,
    summary: GenericTextSchema,
    warning_items: Type.Array(GenericTextSchema, { minItems: 1 })
  })
]);

export const RecommendationBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('recommendation_block'),
    summary: GenericTextSchema,
    recommended_action: RecommendedActionSchema,
    rationale: Type.Optional(Type.Array(GenericTextSchema))
  })
]);

export const ApprovalBriefBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('approval_brief_block'),
    recommendation: Type.Union([
      Type.Literal('approve'),
      Type.Literal('reject'),
      Type.Literal('request_info'),
      Type.Literal('investigate_more')
    ]),
    summary: GenericTextSchema,
    missing_prerequisites: Type.Optional(Type.Array(MissingInfoItemSchema)),
    impact_preview: Type.Optional(Type.Array(ImpactChangeSchema))
  })
]);

export const TimelineBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('timeline_block'),
    items: Type.Array(TimelineItemSchema, { minItems: 1 })
  })
]);

export const ArtifactListBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('artifact_list_block'),
    items: Type.Array(ArtifactItemSchema, { minItems: 1 })
  })
]);

export const DecisionTraceBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('decision_trace_block'),
    items: Type.Array(DecisionTraceItemSchema, { minItems: 1 })
  })
]);

export const ExceptionBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('exception_block'),
    items: Type.Array(ExceptionItemSchema, { minItems: 1 })
  })
]);

export const FieldSuggestionBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('field_suggestion_block'),
    fields: Type.Array(FieldSuggestionSchema, { minItems: 1 })
  })
]);

export const ImpactPreviewBlockSchema = Type.Composite([
  UiBlockBaseSchema,
  Type.Object({
    type: Type.Literal('impact_preview_block'),
    changes: Type.Array(ImpactChangeSchema, { minItems: 1 })
  })
]);

export const FrontendUiBlockSchema = Type.Union([
  SummaryBlockSchema,
  StatusStripBlockSchema,
  MetricStripBlockSchema,
  RiskBlockSchema,
  WarningBlockSchema,
  RecommendationBlockSchema,
  ApprovalBriefBlockSchema,
  TimelineBlockSchema,
  ArtifactListBlockSchema,
  DecisionTraceBlockSchema,
  ExceptionBlockSchema,
  FieldSuggestionBlockSchema,
  ImpactPreviewBlockSchema
]);

export const ContextPackRequestSchema = Type.Object({
  user_id: GenericIdSchema,
  role: EnterpriseRoleSchema,
  page_type: EnterprisePageTypeSchema,
  object_ref: Type.Optional(BusinessObjectRefSchema),
  selection: Type.Optional(Type.Array(BusinessObjectRefSchema)),
  goal: Type.Optional(GenericTextSchema),
  queue_context: Type.Optional(GenericLabelSchema),
  include_sections: Type.Optional(Type.Array(GenericLabelSchema))
});

export const ContextPackResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  page_type: EnterprisePageTypeSchema,
  object_ref: Type.Optional(BusinessObjectRefSchema),
  summary: PageSummarySchema,
  current_state: Type.Record(Type.String(), JsonValueSchema),
  key_facts: Type.Array(FactItemSchema),
  recent_changes: Type.Array(TimelineItemSchema),
  exceptions: Type.Array(ExceptionItemSchema),
  recommended_actions: Type.Array(RecommendedActionSchema),
  ui_blocks: Type.Array(FrontendUiBlockSchema),
  evidence: Type.Array(EvidenceRefSchema)
});

export const Object360RequestSchema = Type.Object({
  user_id: Type.Optional(GenericIdSchema),
  role: Type.Optional(EnterpriseRoleSchema),
  object_ref: BusinessObjectRefSchema,
  perspective: Type.Optional(GenericLabelSchema),
  include_sections: Type.Optional(Type.Array(GenericLabelSchema))
});

export const Object360ResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  object: Type.Object({
    ref: BusinessObjectRefSchema,
    status: GenericTextSchema,
    health: HealthSchema,
    stage: Type.Optional(GenericTextSchema),
    owner: Type.Optional(GenericLabelSchema),
    freshness: Type.Optional(TimestampSchema)
  }),
  summary: PageSummarySchema,
  key_facts: Type.Array(FactItemSchema),
  metrics: Type.Array(MetricItemSchema),
  linked_objects: Type.Array(BusinessObjectLinkSchema),
  timeline: Type.Array(TimelineItemSchema),
  artifacts: Type.Array(ArtifactItemSchema),
  decisions: Type.Array(DecisionTraceItemSchema),
  exceptions: Type.Array(ExceptionItemSchema),
  recommended_actions: Type.Array(RecommendedActionSchema),
  ui_blocks: Type.Array(FrontendUiBlockSchema),
  evidence: Type.Array(EvidenceRefSchema)
});

export const ExceptionFeedRequestSchema = Type.Object({
  user_id: GenericIdSchema,
  role: EnterpriseRoleSchema,
  queue_context: Type.Optional(GenericLabelSchema),
  scope: Type.Optional(Type.Record(Type.String(), JsonValueSchema)),
  limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 }))
});

export const ExceptionFeedResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  summary: PageSummarySchema,
  total_open: CountSchema,
  items: Type.Array(ExceptionItemSchema),
  recommended_actions: Type.Array(RecommendedActionSchema)
});

export const DecisionBriefRequestSchema = Type.Object({
  user_id: GenericIdSchema,
  role: EnterpriseRoleSchema,
  object_ref: Type.Optional(BusinessObjectRefSchema),
  approval_ref: GenericIdSchema,
  goal: Type.Optional(GenericTextSchema),
  candidate_actions: Type.Optional(Type.Array(GenericLabelSchema))
});

export const DecisionBriefResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  summary: PageSummarySchema,
  recommendation: Type.Object({
    disposition: Type.Union([
      Type.Literal('approve'),
      Type.Literal('reject'),
      Type.Literal('request_info'),
      Type.Literal('investigate_more')
    ]),
    reason: GenericTextSchema,
    confidence: Type.Optional(ConfidenceSchema)
  }),
  missing_prerequisites: Type.Array(MissingInfoItemSchema),
  impact_preview: Type.Array(ImpactChangeSchema),
  evidence: Type.Array(EvidenceRefSchema),
  ui_blocks: Type.Array(FrontendUiBlockSchema)
});

export const ActionProposeRequestSchema = Type.Object({
  user_id: GenericIdSchema,
  role: EnterpriseRoleSchema,
  page_type: EnterprisePageTypeSchema,
  intent: GenericTextSchema,
  object_ref: Type.Optional(BusinessObjectRefSchema),
  available_actions: Type.Optional(Type.Array(GenericLabelSchema)),
  draft_args: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const ActionProposeResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  summary: PageSummarySchema,
  proposed_actions: Type.Array(RecommendedActionSchema),
  missing_inputs: Type.Array(MissingInfoItemSchema),
  constraints: Type.Array(GenericTextSchema),
  evidence: Type.Array(EvidenceRefSchema),
  ui_blocks: Type.Array(FrontendUiBlockSchema)
});

export const ActionSimulateRequestSchema = Type.Object({
  user_id: GenericIdSchema,
  role: EnterpriseRoleSchema,
  page_type: Type.Optional(EnterprisePageTypeSchema),
  action_key: GenericLabelSchema,
  object_ref: Type.Optional(BusinessObjectRefSchema),
  args: Type.Optional(Type.Record(Type.String(), JsonValueSchema))
});

export const ActionSimulateResponseSchema = Type.Object({
  contract_version: ContractVersionSchema,
  generated_at: TimestampSchema,
  summary: PageSummarySchema,
  simulation_status: SimulationStatusSchema,
  selected_action: RecommendedActionSchema,
  affected_objects: Type.Array(BusinessObjectRefSchema),
  changes: Type.Array(ImpactChangeSchema),
  follow_up_actions: Type.Array(RecommendedActionSchema),
  blockers: Type.Array(MissingInfoItemSchema),
  evidence: Type.Array(EvidenceRefSchema),
  ui_blocks: Type.Array(FrontendUiBlockSchema)
});

export const ContextPackRouteSchema = {
  tags: ['frontend-intelligence'],
  body: ContextPackRequestSchema,
  response: {
    200: ContextPackResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const Object360RouteSchema = {
  tags: ['frontend-intelligence'],
  body: Object360RequestSchema,
  response: {
    200: Object360ResponseSchema,
    400: ErrorSchema,
    404: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const ExceptionFeedRouteSchema = {
  tags: ['frontend-intelligence'],
  body: ExceptionFeedRequestSchema,
  response: {
    200: ExceptionFeedResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const DecisionBriefRouteSchema = {
  tags: ['frontend-intelligence'],
  body: DecisionBriefRequestSchema,
  response: {
    200: DecisionBriefResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const ActionProposeRouteSchema = {
  tags: ['frontend-intelligence'],
  body: ActionProposeRequestSchema,
  response: {
    200: ActionProposeResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;

export const ActionSimulateRouteSchema = {
  tags: ['frontend-intelligence'],
  body: ActionSimulateRequestSchema,
  response: {
    200: ActionSimulateResponseSchema,
    400: ErrorSchema,
    500: ErrorSchema
  }
} as const;
