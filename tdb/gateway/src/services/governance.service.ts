import type { Static } from '@sinclair/typebox';

import type {
  AssertionPolicyRuleRecord,
  AuthorityGrantRecord,
  EvidencePolicyRuleRecord,
  EvidenceLocatorRecord,
  EvidenceRecord,
  EventSentenceRecord,
  GatewayBackendClient,
  GetMethodologyFrameworkBundleResponse,
  MethodologyFrameworkRecord,
  OntologyAlertDetailRecord,
  OntologyAlertRecord,
  OntologyAlertSummaryRecord,
  OntologyCaseDecisionRecord,
  OntologyCaseEventRecord,
  OntologyCaseFactRecord,
  OntologyCaseRecord,
  OntologyCaseSummaryRecord,
  OntologyFactBulkSelectionRecord,
  OntologyFactEvidenceRecord,
  OntologyFactLinkedAlertRecord,
  OntologyFactLinkedCaseRecord,
  OntologyFactReviewRecord,
  OntologyFactRecord,
  OntologyOpsRuleConfigRecord,
  OntologyOpsRuleRunRecord,
  ReviewPolicyRecord,
  RuleOverrideRecord,
  RuleRecord,
  SemanticStatementReferenceRecord,
  TaxonomySchemeRecord
} from '../clients/gateway_backend.types.js';
import { TdbError } from '../errors/tdb_error.js';
import {
  AssertionPolicyRuleGetQuerySchema,
  AssertionPolicyRuleListQuerySchema,
  AssertionPolicyRuleUpsertRequestSchema,
  AuthorityCheckQuerySchema,
  AuthorityGrantRequestSchema,
  EvidencePolicyRuleGetQuerySchema,
  EvidencePolicyRuleListQuerySchema,
  EvidencePolicyRuleUpsertRequestSchema,
  MethodologyFrameworkGetQuerySchema,
  MethodologyFrameworkListQuerySchema,
  MethodologyFrameworkUpsertRequestSchema,
  OntologyAlertExplainQuerySchema,
  OntologyAlertListQuerySchema,
  OntologyAlertOpenRequestSchema,
  OntologyAlertUpdateRequestSchema,
  OntologyCaseDecisionListQuerySchema,
  OntologyCaseConflictDraftRequestSchema,
  OntologyCaseDecisionRecordRequestSchema,
  OntologyCaseDetailQuerySchema,
  OntologyCaseExplainQuerySchema,
  OntologyCaseListQuerySchema,
  OntologyCaseOpenRequestSchema,
  OntologyCaseUpdateRequestSchema,
  OntologyFactBulkReviewRequestSchema,
  OntologyFactHistoryQuerySchema,
  OntologyFactProvenanceQuerySchema,
  OntologyFactReviewRequestSchema,
  OntologyOpsRuleConfigListQuerySchema,
  OntologyOpsRuleConfigUpsertRequestSchema,
  OntologyOpsRuleRunExplainQuerySchema,
  OntologyOpsRuleRunListQuerySchema,
  OntologyOpsRuleRunRequestSchema,
  ReviewPolicyGetQuerySchema,
  ReviewPolicyListQuerySchema,
  ReviewPolicyUpsertRequestSchema,
  RuleOverrideAsOfQuerySchema,
  RuleOverrideRequestSchema,
  RuleUpsertRequestSchema,
  TaxonomySchemeGetQuerySchema,
  TaxonomySchemeListQuerySchema,
  TaxonomySchemeUpsertRequestSchema
} from '../schema/v2/governance.js';

export type RuleUpsertRequest = Static<typeof RuleUpsertRequestSchema>;
export type MethodologyFrameworkUpsertRequest = Static<typeof MethodologyFrameworkUpsertRequestSchema>;
export type MethodologyFrameworkGetQuery = Static<typeof MethodologyFrameworkGetQuerySchema>;
export type MethodologyFrameworkListQuery = Static<typeof MethodologyFrameworkListQuerySchema>;
export type TaxonomySchemeUpsertRequest = Static<typeof TaxonomySchemeUpsertRequestSchema>;
export type TaxonomySchemeGetQuery = Static<typeof TaxonomySchemeGetQuerySchema>;
export type TaxonomySchemeListQuery = Static<typeof TaxonomySchemeListQuerySchema>;
export type EvidencePolicyRuleUpsertRequest = Static<typeof EvidencePolicyRuleUpsertRequestSchema>;
export type EvidencePolicyRuleGetQuery = Static<typeof EvidencePolicyRuleGetQuerySchema>;
export type EvidencePolicyRuleListQuery = Static<typeof EvidencePolicyRuleListQuerySchema>;
export type AssertionPolicyRuleUpsertRequest = Static<typeof AssertionPolicyRuleUpsertRequestSchema>;
export type AssertionPolicyRuleGetQuery = Static<typeof AssertionPolicyRuleGetQuerySchema>;
export type AssertionPolicyRuleListQuery = Static<typeof AssertionPolicyRuleListQuerySchema>;
export type ReviewPolicyUpsertRequest = Static<typeof ReviewPolicyUpsertRequestSchema>;
export type ReviewPolicyGetQuery = Static<typeof ReviewPolicyGetQuerySchema>;
export type ReviewPolicyListQuery = Static<typeof ReviewPolicyListQuerySchema>;
export type AuthorityGrantRequest = Static<typeof AuthorityGrantRequestSchema>;
export type RuleOverrideRequest = Static<typeof RuleOverrideRequestSchema>;
export type AuthorityCheckQuery = Static<typeof AuthorityCheckQuerySchema>;
export type RuleOverrideAsOfQuery = Static<typeof RuleOverrideAsOfQuerySchema>;
export type OntologyFactReviewRequest = Static<typeof OntologyFactReviewRequestSchema>;
export type OntologyFactHistoryQuery = Static<typeof OntologyFactHistoryQuerySchema>;
export type OntologyFactProvenanceQuery = Static<typeof OntologyFactProvenanceQuerySchema>;
export type OntologyFactBulkReviewRequest = Static<typeof OntologyFactBulkReviewRequestSchema>;
export type OntologyCaseOpenRequest = Static<typeof OntologyCaseOpenRequestSchema>;
export type OntologyCaseListQuery = Static<typeof OntologyCaseListQuerySchema>;
export type OntologyCaseDetailQuery = Static<typeof OntologyCaseDetailQuerySchema>;
export type OntologyCaseExplainQuery = Static<typeof OntologyCaseExplainQuerySchema>;
export type OntologyCaseDecisionRecordRequest = Static<typeof OntologyCaseDecisionRecordRequestSchema>;
export type OntologyCaseDecisionListQuery = Static<typeof OntologyCaseDecisionListQuerySchema>;
export type OntologyCaseConflictDraftRequest = Static<typeof OntologyCaseConflictDraftRequestSchema>;
export type OntologyCaseUpdateRequest = Static<typeof OntologyCaseUpdateRequestSchema>;
export type OntologyAlertOpenRequest = Static<typeof OntologyAlertOpenRequestSchema>;
export type OntologyAlertListQuery = Static<typeof OntologyAlertListQuerySchema>;
export type OntologyAlertExplainQuery = Static<typeof OntologyAlertExplainQuerySchema>;
export type OntologyAlertUpdateRequest = Static<typeof OntologyAlertUpdateRequestSchema>;
export type OntologyOpsRuleConfigListQuery = Static<typeof OntologyOpsRuleConfigListQuerySchema>;
export type OntologyOpsRuleConfigUpsertRequest = Static<typeof OntologyOpsRuleConfigUpsertRequestSchema>;
export type OntologyOpsRuleRunRequest = Static<typeof OntologyOpsRuleRunRequestSchema>;
export type OntologyOpsRuleRunListQuery = Static<typeof OntologyOpsRuleRunListQuerySchema>;
export type OntologyOpsRuleRunExplainQuery = Static<typeof OntologyOpsRuleRunExplainQuerySchema>;

export type RuleDto = {
  rule_key: string;
  rule_version: number;
  severity: 'low' | 'medium' | 'high' | 'critical';
  expression: string;
  effective_from: string;
  effective_to: string;
  system_from: string;
  system_to: string;
  source_artifact_version_id: string;
};

export type AuthorityGrantDto = {
  authority_grant_id: number;
  grantee_id: string;
  action_type: string;
  scope: Record<string, unknown>;
  valid_from: string;
  valid_to: string;
  system_from: string;
  system_to: string;
  mandate_artifact_version_id?: string;
};

export type RuleOverrideDto = {
  rule_override_id: number;
  rule_key: string;
  rule_version: number;
  authority_grant_id: number;
  justification_artifact_version_id?: string;
  valid_from: string;
  valid_to: string;
  system_from: string;
  system_to: string;
  case_id?: number;
  event_id?: number;
};

export type MethodologyFrameworkDto = {
  framework_id: string;
  domain: string;
  framework_name: string;
  version_label: string;
  status: 'draft' | 'active' | 'superseded' | 'archived';
  description: string;
  owner: string;
  question_types: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type TaxonomySchemeDto = {
  scheme_id: string;
  framework_id: string;
  scheme_name: string;
  scheme_type: 'classification' | 'controlled_vocabulary' | 'relation_taxonomy' | 'other';
  status: 'draft' | 'active' | 'superseded' | 'archived';
  description: string;
  canonical_source: string;
  scheme: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvidencePolicyRuleDto = {
  evidence_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  question_type: string;
  evidence_kind: string;
  source_tier: string;
  status: 'draft' | 'active' | 'superseded' | 'archived';
  priority: number;
  review_required: boolean;
  applicability: Record<string, unknown>;
  effect: Record<string, unknown>;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AssertionPolicyRuleDto = {
  assertion_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  assertion_type: string;
  question_type: string;
  status: 'draft' | 'active' | 'superseded' | 'archived';
  priority: number;
  review_required: boolean;
  required_evidence: Record<string, unknown>;
  outcome: Record<string, unknown>;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ReviewPolicyDto = {
  review_policy_id: string;
  framework_id: string;
  policy_key: string;
  question_type: string;
  trigger_kind: string;
  action: string;
  status: 'draft' | 'active' | 'superseded' | 'archived';
  priority: number;
  trigger: Record<string, unknown>;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MethodologyFrameworkBundleDto = {
  framework?: MethodologyFrameworkDto;
  taxonomy_schemes: TaxonomySchemeDto[];
  evidence_policy_rules: EvidencePolicyRuleDto[];
  assertion_policy_rules: AssertionPolicyRuleDto[];
  review_policies: ReviewPolicyDto[];
};

export type OntologyFactDto = {
  fact_id: number;
  statement_id?: string;
  src_concept_id: string;
  src_concept_label?: string;
  predicate: string;
  dst_concept_id: string;
  dst_concept_label?: string;
  qualifier_json: Record<string, unknown>;
  confidence: number;
  extractor: string;
  status: 'accepted' | 'candidate' | 'rejected' | 'needs_review';
  review_note: string;
  valid_from?: string;
  valid_to?: string;
  created_at: string;
  updated_at: string;
};

export type OntologyFactReviewDto = {
  review_id: number;
  fact_id: number;
  decision: 'verified' | 'refuted';
  reviewer: string;
  note: string;
  created_at: string;
};

export type OntologyFactEvidenceDto = {
  stream_id: string;
  event_id: string;
  asset_id?: string;
  version_number?: number;
  source_span?: string;
  evidence_json: Record<string, unknown>;
  sentence?: {
    sent_index: number;
    start_char?: number;
    end_char?: number;
    sentence_text: string;
  };
  confidence: number;
  created_at: string;
  updated_at: string;
};

export type OntologyFactHistoryDto = {
  fact: OntologyFactDto;
  reviews: OntologyFactReviewDto[];
  evidence: OntologyFactEvidenceDto[];
  evidence_count: number;
  stream_id_filter?: string;
};

export type OntologyFactProvenanceDto = OntologyFactHistoryDto & {
  linked_cases: OntologyFactLinkedCaseDto[];
  linked_alerts: OntologyFactLinkedAlertDto[];
};

export type OntologyFactLinkedCaseDto = {
  case_id: number;
  stream_id: string;
  title: string;
  status: 'open' | 'investigating' | 'resolved' | 'closed';
  priority: 'p0' | 'p1' | 'p2' | 'p3';
  owner: string;
  linked_at: string;
};

export type OntologyFactLinkedAlertDto = {
  alert_id: number;
  case_id?: number;
  stream_id: string;
  severity: 'info' | 'warning' | 'critical';
  status: 'open' | 'acknowledged' | 'closed';
  message: string;
  rule_key?: string;
  linked_at: string;
};

export type OntologyFactBulkSelectionDto = {
  fact_id: number;
  predicate: string;
  confidence: number;
  extractor: string;
  updated_at: string;
};

export type OntologyFactBulkReviewResultDto = {
  decision: 'accept' | 'reject' | 'needs_work';
  status_filter: 'accepted' | 'candidate' | 'rejected' | 'needs_review' | 'all';
  stream_id_filter?: string;
  predicate_filter?: string;
  extractor_filter?: string;
  stale_days_filter?: number;
  min_confidence: number;
  max_confidence: number;
  limit: number;
  dry_run: boolean;
  reviewer: string;
  note: string;
  selected_count: number;
  updated_rows: number;
  selected_facts: OntologyFactBulkSelectionDto[];
};

export type OntologyCaseDto = {
  case_id: number;
  stream_id: string;
  title: string;
  description: string;
  status: 'open' | 'in_review' | 'resolved' | 'dismissed';
  priority: 'p1' | 'p2' | 'p3';
  owner: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  closed_at?: string;
};

export type OntologyCaseSummaryDto = OntologyCaseDto & {
  fact_count: number;
  active_alert_count: number;
};

export type OntologyCaseOpenResultDto = OntologyCaseDto & {
  linked_fact_ids: number[];
  skipped_fact_ids: number[];
};

export type OntologyCaseDecisionDto = {
  case_decision_id: number;
  case_id: number;
  decision_kind: string;
  verdict: string;
  summary: string;
  rationale: string;
  as_of_system_time: string;
  as_of_effective_time: string;
  snapshot_id: string;
  source_evidence_json: unknown[];
  supersedes_case_decision_id?: number;
  created_by: string;
  created_at: string;
};

export type OntologyCaseConflictDraftCandidateDto = {
  stream_id: string;
  src_concept_id: string;
  predicate: string;
  dst_values: string[];
  dst_count: number;
  fact_count: number;
  fact_ids: number[];
  draft_key: string;
};

export type OntologyCaseConflictDraftResponse = {
  case?: OntologyCaseDto;
  decision?: OntologyCaseDecisionDto;
  created_case: boolean;
  deduped: boolean;
  candidate: OntologyCaseConflictDraftCandidateDto;
};

export type OntologyCaseFactDto = {
  fact_id: number;
  predicate: string;
  subject_entity_id: string;
  object_entity_id: string;
  object_value_json: Record<string, unknown>;
  confidence: number;
  extractor: string;
  status: 'accepted' | 'candidate' | 'rejected' | 'needs_review';
  decision?: 'verified' | 'refuted';
  evidence_sample: OntologyFactEvidenceDto[];
  added_by: string;
  added_at: string;
};

export type OntologyCaseEventDto = {
  event_id: number;
  action: string;
  actor: string;
  note: string;
  payload_json: Record<string, unknown>;
  created_at: string;
};

export type OntologyAlertDto = {
  alert_id: number;
  case_id?: number;
  stream_id: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: 'open' | 'acked' | 'closed';
  message: string;
  detail_json: Record<string, unknown>;
  rule_key?: string;
  trigger_count: number;
  first_triggered_at: string;
  last_triggered_at: string;
  acked_by?: string;
  acked_at?: string;
  closed_at?: string;
  created_at: string;
  updated_at: string;
};

export type OntologyAlertSummaryDto = OntologyAlertDto & {
  case_title?: string;
  linked_fact_count: number;
};

export type OntologyCaseDetailDto = {
  case: OntologyCaseDto;
  facts: OntologyCaseFactDto[];
  decisions: OntologyCaseDecisionDto[];
  events: OntologyCaseEventDto[];
  alerts: Array<OntologyAlertDto & { linked_fact_ids: number[] }>;
  evidence_limit: number;
};

export type OntologyCaseExplainDto = OntologyCaseDetailDto & {
  explanation: {
    summary: string;
    fact_count: number;
    event_count: number;
    alert_count: number;
    active_alert_count: number;
    latest_event_action?: string;
    reasoning_steps: string[];
    flags: string[];
  };
};

export type OntologyAlertExplainDto = {
  alert: OntologyAlertDto & {
    case_title?: string;
    linked_fact_count: number;
    linked_fact_ids: number[];
  };
  case?: OntologyCaseDto;
  explanation: {
    summary: string;
    source: 'manual' | 'rule';
    active: boolean;
    case_bound: boolean;
    linked_fact_count: number;
    reasoning_steps: string[];
    flags: string[];
  };
};

export type OntologyOpsRuleConfigDto = {
  config_id: number;
  stream_id?: string;
  rule_name: 'default' | 'stale_pending' | 'conflict_predicate';
  enabled: boolean;
  stale_days?: number;
  conflict_predicate?: string;
  severity?: 'low' | 'medium' | 'high' | 'critical';
  note: string;
  updated_by: string;
  updated_at: string;
};

export type OntologyOpsRuleRunDto = {
  run_id: number;
  stream_id_filter?: string;
  stale_days: number;
  conflict_predicate: string;
  dry_run: boolean;
  candidate_count: number;
  created_case_count: number;
  existing_case_count: number;
  created_alert_count: number;
  existing_alert_count: number;
  duration_ms: number;
  started_at: string;
  finished_at: string;
};

export type OntologyOpsRuleRunExplainDto = {
  run: OntologyOpsRuleRunDto;
  payload: OntologyOpsRuleRunResultDto;
  explanation: {
    summary: string;
    triggered_rules: string[];
    candidate_count: number;
    action_count: number;
    dry_run: boolean;
    reasoning_steps: string[];
    flags: string[];
  };
};

export type OntologyOpsRuleRunResultDto = {
  stream_id_filter?: string;
  stale_days: number;
  conflict_predicate: string;
  rules_enabled: {
    stale_pending: boolean;
    conflict_predicate: boolean;
  };
  rule_severity: {
    stale_pending: 'low' | 'medium' | 'high' | 'critical';
    conflict_predicate: 'low' | 'medium' | 'high' | 'critical';
  };
  dry_run: boolean;
  candidate_count: number;
  candidates: Record<string, unknown>[];
  created_cases: Record<string, unknown>[];
  existing_cases: Record<string, unknown>[];
  created_alerts: Record<string, unknown>[];
  existing_alerts: Record<string, unknown>[];
};

export class GovernanceService {
  constructor(private readonly client: GatewayBackendClient) {}

  async upsertRule(request: RuleUpsertRequest): Promise<RuleDto> {
    const record = await this.client.upsertRule({
      rule_key: request.rule_key,
      rule_version: request.rule_version,
      severity: request.severity,
      expression: request.expression,
      effective_from: request.effective_from,
      effective_to: request.effective_to,
      source_artifact_version_id: request.source_artifact_version_id
    });
    return mapRule(record);
  }

  async grantAuthority(request: AuthorityGrantRequest): Promise<AuthorityGrantDto> {
    const record = await this.client.insertAuthorityGrant({
      grantee_id: request.grantee_id,
      action_type: request.action_type,
      scope_json: JSON.stringify(request.scope ?? {}),
      valid_from: request.valid_from,
      valid_to: request.valid_to,
      system_from: request.system_from,
      mandate_artifact_version_id: request.mandate_artifact_version_id
    });
    return mapAuthority(record);
  }

  async overrideRule(request: RuleOverrideRequest): Promise<RuleOverrideDto> {
    const record = await this.client.insertRuleOverride({
      rule_key: request.rule_key,
      rule_version: request.rule_version,
      authority_grant_id: request.authority_grant_id,
      justification_artifact_version_id: request.justification_artifact_version_id,
      valid_from: request.valid_from,
      valid_to: request.valid_to,
      system_from: request.system_from,
      case_id: request.case_id,
      event_id: request.event_id
    });
    return mapOverride(record);
  }

  async checkAuthority(query: AuthorityCheckQuery): Promise<{ allowed: boolean; authorityGrant?: AuthorityGrantDto }> {
    const asOfSystem = query.as_of_system_time ?? nowIso();
    const requestedScope = query.scope ? parseScopeQuery(query.scope) : {};
    const record = await this.client.findAuthorityAsOf({
      grantee_id: query.grantee_id,
      action_type: query.action_type,
      scope_json: JSON.stringify(requestedScope),
      as_of_valid_time: query.as_of_valid_time,
      as_of_system_time: asOfSystem
    });

    if (!record) {
      return { allowed: false };
    }

    return { allowed: true, authorityGrant: mapAuthority(record) };
  }

  async listOverridesAsOf(query: RuleOverrideAsOfQuery): Promise<RuleOverrideDto[]> {
    const asOfSystem = query.as_of_system_time ?? nowIso();
    const records = await this.client.listRuleOverridesAsOf({
      rule_key: query.rule_key,
      rule_version: query.rule_version,
      as_of_valid_time: query.as_of_valid_time,
      as_of_system_time: asOfSystem
    });

    return records.map(mapOverride);
  }

  async upsertMethodologyFramework(request: MethodologyFrameworkUpsertRequest): Promise<MethodologyFrameworkDto> {
    const record = await this.client.upsertMethodologyFramework({
      framework_id: request.framework_id ?? '',
      domain: request.domain,
      framework_name: request.framework_name,
      version_label: request.version_label,
      status: request.status ?? 'draft',
      description: request.description ?? '',
      owner: request.owner ?? '',
      question_types_json: JSON.stringify(request.question_types ?? []),
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapMethodologyFramework(record);
  }

  async getMethodologyFramework(query: MethodologyFrameworkGetQuery): Promise<MethodologyFrameworkDto | undefined> {
    const record = await this.client.getMethodologyFramework({ framework_id: query.framework_id });
    return record ? mapMethodologyFramework(record) : undefined;
  }

  async listMethodologyFrameworks(query: MethodologyFrameworkListQuery): Promise<MethodologyFrameworkDto[]> {
    const records = await this.client.listMethodologyFrameworks({
      domain: query.domain,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapMethodologyFramework);
  }

  async getMethodologyFrameworkBundle(query: MethodologyFrameworkGetQuery): Promise<MethodologyFrameworkBundleDto> {
    return mapMethodologyFrameworkBundle(
      await this.client.getMethodologyFrameworkBundle({ framework_id: query.framework_id })
    );
  }

  async upsertTaxonomyScheme(request: TaxonomySchemeUpsertRequest): Promise<TaxonomySchemeDto> {
    const record = await this.client.upsertTaxonomyScheme({
      scheme_id: request.scheme_id ?? '',
      framework_id: request.framework_id,
      scheme_name: request.scheme_name,
      scheme_type: request.scheme_type,
      status: request.status ?? 'draft',
      description: request.description ?? '',
      canonical_source: request.canonical_source ?? '',
      scheme_json: JSON.stringify(request.scheme ?? {}),
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapTaxonomyScheme(record);
  }

  async getTaxonomyScheme(query: TaxonomySchemeGetQuery): Promise<TaxonomySchemeDto | undefined> {
    const record = await this.client.getTaxonomyScheme({ scheme_id: query.scheme_id });
    return record ? mapTaxonomyScheme(record) : undefined;
  }

  async listTaxonomySchemes(query: TaxonomySchemeListQuery): Promise<TaxonomySchemeDto[]> {
    const records = await this.client.listTaxonomySchemes({
      framework_id: query.framework_id,
      scheme_type: query.scheme_type,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapTaxonomyScheme);
  }

  async upsertEvidencePolicyRule(request: EvidencePolicyRuleUpsertRequest): Promise<EvidencePolicyRuleDto> {
    const record = await this.client.upsertEvidencePolicyRule({
      evidence_policy_rule_id: request.evidence_policy_rule_id ?? '',
      framework_id: request.framework_id,
      rule_key: request.rule_key,
      question_type: request.question_type ?? '',
      evidence_kind: request.evidence_kind ?? '',
      source_tier: request.source_tier ?? '',
      status: request.status ?? 'draft',
      priority: request.priority ?? 100,
      review_required: request.review_required ?? false,
      applicability_json: JSON.stringify(request.applicability ?? {}),
      effect_json: JSON.stringify(request.effect ?? {}),
      description: request.description ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapEvidencePolicyRule(record);
  }

  async getEvidencePolicyRule(query: EvidencePolicyRuleGetQuery): Promise<EvidencePolicyRuleDto | undefined> {
    const record = await this.client.getEvidencePolicyRule({
      evidence_policy_rule_id: query.evidence_policy_rule_id
    });
    return record ? mapEvidencePolicyRule(record) : undefined;
  }

  async listEvidencePolicyRules(query: EvidencePolicyRuleListQuery): Promise<EvidencePolicyRuleDto[]> {
    const records = await this.client.listEvidencePolicyRules({
      framework_id: query.framework_id,
      question_type: query.question_type,
      evidence_kind: query.evidence_kind,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapEvidencePolicyRule);
  }

  async upsertAssertionPolicyRule(request: AssertionPolicyRuleUpsertRequest): Promise<AssertionPolicyRuleDto> {
    const record = await this.client.upsertAssertionPolicyRule({
      assertion_policy_rule_id: request.assertion_policy_rule_id ?? '',
      framework_id: request.framework_id,
      rule_key: request.rule_key,
      assertion_type: request.assertion_type,
      question_type: request.question_type ?? '',
      status: request.status ?? 'draft',
      priority: request.priority ?? 100,
      review_required: request.review_required ?? false,
      required_evidence_json: JSON.stringify(request.required_evidence ?? {}),
      outcome_json: JSON.stringify(request.outcome ?? {}),
      description: request.description ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapAssertionPolicyRule(record);
  }

  async getAssertionPolicyRule(query: AssertionPolicyRuleGetQuery): Promise<AssertionPolicyRuleDto | undefined> {
    const record = await this.client.getAssertionPolicyRule({
      assertion_policy_rule_id: query.assertion_policy_rule_id
    });
    return record ? mapAssertionPolicyRule(record) : undefined;
  }

  async listAssertionPolicyRules(query: AssertionPolicyRuleListQuery): Promise<AssertionPolicyRuleDto[]> {
    const records = await this.client.listAssertionPolicyRules({
      framework_id: query.framework_id,
      assertion_type: query.assertion_type,
      question_type: query.question_type,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapAssertionPolicyRule);
  }

  async upsertReviewPolicy(request: ReviewPolicyUpsertRequest): Promise<ReviewPolicyDto> {
    const record = await this.client.upsertReviewPolicy({
      review_policy_id: request.review_policy_id ?? '',
      framework_id: request.framework_id,
      policy_key: request.policy_key,
      question_type: request.question_type ?? '',
      trigger_kind: request.trigger_kind,
      action: request.action ?? 'human_review',
      status: request.status ?? 'draft',
      priority: request.priority ?? 100,
      trigger_json: JSON.stringify(request.trigger ?? {}),
      description: request.description ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapReviewPolicy(record);
  }

  async getReviewPolicy(query: ReviewPolicyGetQuery): Promise<ReviewPolicyDto | undefined> {
    const record = await this.client.getReviewPolicy({ review_policy_id: query.review_policy_id });
    return record ? mapReviewPolicy(record) : undefined;
  }

  async listReviewPolicies(query: ReviewPolicyListQuery): Promise<ReviewPolicyDto[]> {
    const records = await this.client.listReviewPolicies({
      framework_id: query.framework_id,
      question_type: query.question_type,
      trigger_kind: query.trigger_kind,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapReviewPolicy);
  }

  async reviewOntologyFact(request: OntologyFactReviewRequest): Promise<{
    fact_id: number;
    decision: 'accept' | 'reject' | 'needs_work';
    reviewer: string;
    note: string;
    updated_rows: number;
  }> {
    const reviewer = request.reviewer?.trim() || 'system';
    const note = request.note?.trim() ?? '';

    const updatedRows = await this.client.reviewOntologyFact({
      fact_id: request.fact_id,
      decision: request.decision,
      reviewer,
      note
    });

    if (updatedRows === 0) {
      throw new TdbError('ONTOLOGY_FACT_NOT_FOUND', 404, `ontology fact not found: ${request.fact_id}`);
    }

    return {
      fact_id: request.fact_id,
      decision: request.decision,
      reviewer,
      note,
      updated_rows: updatedRows
    };
  }

  async getOntologyFactHistory(query: OntologyFactHistoryQuery): Promise<OntologyFactHistoryDto> {
    if ((query.fact_id ?? 0) <= 0 && query.statement_id) {
      return this.getSemanticStatementHistory(query.statement_id, query.evidence_limit, query.stream_id);
    }

    const factId = query.fact_id;
    if (!factId || factId <= 0) {
      throw new TdbError('ONTOLOGY_FACT_ID_REQUIRED', 400, 'fact_id or statement_id is required');
    }

    const fact = await this.client.getOntologyFact({ fact_id: factId });
    if (!fact) {
      throw new TdbError('ONTOLOGY_FACT_NOT_FOUND', 404, `ontology fact not found: ${factId}`);
    }

    if (Number(fact.fact_id) <= 0 && fact.statement_id) {
      return this.getSemanticStatementHistory(fact.statement_id, query.evidence_limit, query.stream_id, fact);
    }

    const evidenceLimit = query.evidence_limit ?? 200;
    const [reviews, evidence] = await Promise.all([
      this.client.listOntologyFactReviews({ fact_id: factId }),
      this.client.listOntologyFactEvidence({
        fact_id: factId,
        limit: evidenceLimit,
        stream_id: query.stream_id
      })
    ]);

    const factDto = mapOntologyFact(fact);
    const enrichedEvidence = await this.enrichFactEvidence(
      evidence.map(mapOntologyFactEvidence),
      factDto
    );

    return {
      fact: factDto,
      reviews: reviews.map(mapOntologyFactReview),
      evidence: enrichedEvidence,
      evidence_count: enrichedEvidence.length,
      stream_id_filter: query.stream_id
    };
  }

  async getOntologyFactProvenance(query: OntologyFactProvenanceQuery): Promise<OntologyFactProvenanceDto> {
    if ((query.fact_id ?? 0) <= 0 && query.statement_id) {
      const history = await this.getSemanticStatementHistory(
        query.statement_id,
        query.evidence_limit,
        query.stream_id
      );
      return {
        ...history,
        linked_cases: [],
        linked_alerts: []
      };
    }

    const history = await this.getOntologyFactHistory(query);
    const factId = query.fact_id;
    if (!factId || factId <= 0) {
      throw new TdbError('ONTOLOGY_FACT_ID_REQUIRED', 400, 'fact_id or statement_id is required');
    }
    const [linkedCases, linkedAlerts] = await Promise.all([
      this.client.listOntologyFactLinkedCases({ fact_id: factId }),
      this.client.listOntologyFactLinkedAlerts({ fact_id: factId })
    ]);

    return {
      ...history,
      linked_cases: linkedCases.map(mapOntologyFactLinkedCase),
      linked_alerts: linkedAlerts.map(mapOntologyFactLinkedAlert)
    };
  }

  private async getSemanticStatementHistory(
    statementId: string,
    evidenceLimit = 200,
    streamId?: string,
    factRecord?: OntologyFactRecord
  ): Promise<OntologyFactHistoryDto> {
    const [statementResponse, provenanceResponse] = await Promise.all([
      this.client.getSemanticStatement({ statement_id: statementId }),
      this.client.getSemanticStatementProvenance({
        statement_id: statementId,
        include_locators: true,
        evidence_limit: evidenceLimit
      })
    ]);

    const statement = statementResponse.statement;
    if (!statement) {
      throw new TdbError('ONTOLOGY_STATEMENT_NOT_FOUND', 404, `semantic statement not found: ${statementId}`);
    }

    const fact = factRecord ?? {
      fact_id: 0,
      statement_id: statementId,
      src_concept_id: statement.subject_concept_id,
      src_concept_label: statement.subject_name,
      predicate: statement.predicate,
      dst_concept_id: statement.object_concept_id,
      dst_concept_label: statement.object_name,
      qualifier_json: '{}',
      confidence: statement.confidence,
      extractor: statement.created_by,
      status: statement.status,
      review_note: '',
      valid_from: '',
      valid_to: '',
      created_at: statement.created_at,
      updated_at: statement.updated_at
    } as OntologyFactRecord;

    const factDto = mapOntologyFact(fact);
    const evidence = provenanceResponse.references
      .map(mapSemanticReferenceToFactEvidence)
      .filter((item) => !streamId || item.stream_id === streamId);
    const enrichedEvidence = await this.enrichFactEvidence(evidence, factDto);

    return {
      fact: factDto,
      reviews: [],
      evidence: enrichedEvidence,
      evidence_count: enrichedEvidence.length,
      stream_id_filter: streamId
    };
  }

  private async enrichFactEvidence(
    evidence: OntologyFactEvidenceDto[],
    fact?: OntologyFactDto
  ): Promise<OntologyFactEvidenceDto[]> {
    const streamIds = [...new Set(evidence.map((item) => item.stream_id).filter(Boolean))];
    if (streamIds.length === 0) {
      return evidence;
    }

    const sentenceIndex = new Map<string, EventSentenceRecord>();
    const eventSentenceIndex = new Map<string, EventSentenceRecord[]>();
    await Promise.all(
      streamIds.map(async (streamId) => {
        const sentences = await this.client.getEventSentences({ stream_id: streamId, limit: 2000 });
        for (const sentence of sentences) {
          sentenceIndex.set(
            `${sentence.stream_id}::${sentence.event_id}::${sentence.sent_index}`,
            sentence
          );
          const eventKey = `${sentence.stream_id}::${sentence.event_id}`;
          const bucket = eventSentenceIndex.get(eventKey) ?? [];
          bucket.push(sentence);
          eventSentenceIndex.set(eventKey, bucket);
        }
      })
    );

    return evidence.map((item) => {
      const sentIndex = asNonNegativeInteger(item.evidence_json.sent_index);
      let sentence: EventSentenceRecord | undefined;
      let fallbackEventSentences: EventSentenceRecord[] | undefined;
      if (sentIndex !== undefined) {
        sentence = sentenceIndex.get(`${item.stream_id}::${item.event_id}::${sentIndex}`);
      } else {
        fallbackEventSentences = eventSentenceIndex.get(`${item.stream_id}::${item.event_id}`);
      }
      if (!sentence && (!fallbackEventSentences || fallbackEventSentences.length === 0)) {
        return item;
      }
      if (sentence && sentence.sentence_text) {
        return {
          ...item,
          sentence: {
            sent_index: sentence.sent_index,
            start_char: sentence.start_char >= 0 ? sentence.start_char : undefined,
            end_char: sentence.end_char >= 0 ? sentence.end_char : undefined,
            sentence_text: sentence.sentence_text
          }
        };
      }
      const combined = selectRelevantEventSentenceWindow(
        fallbackEventSentences ?? [],
        fact?.src_concept_label,
        fact?.dst_concept_label
      );
      if (!combined) {
        return item;
      }
      return {
        ...item,
        evidence_json: {
          ...item.evidence_json,
          sentence_selection: 'event_fallback'
        },
        sentence: {
          sent_index: combined.sent_index,
          start_char: combined.start_char,
          end_char: combined.end_char,
          sentence_text: combined.sentence_text
        }
      };
    });
  }

  async bulkReviewOntologyFacts(
    request: OntologyFactBulkReviewRequest
  ): Promise<OntologyFactBulkReviewResultDto> {
    const minConfidence = request.min_confidence ?? 0;
    const maxConfidence = request.max_confidence ?? 1;
    if (minConfidence > maxConfidence) {
      throw new TdbError(
        'INVALID_CONFIDENCE_RANGE',
        400,
        'min_confidence must be less than or equal to max_confidence'
      );
    }

    const reviewer = request.reviewer?.trim() || 'system';
    const note = request.note?.trim() ?? '';
    const status = request.status ?? 'candidate';
    const limit = request.limit ?? 100;
    const dryRun = request.dry_run ?? false;

    const selected = await this.client.selectOntologyFactsForBulkReview({
      status,
      stream_id: request.stream_id,
      predicate: request.predicate?.trim(),
      extractor: request.extractor?.trim(),
      stale_days: request.stale_days,
      min_confidence: minConfidence,
      max_confidence: maxConfidence,
      limit
    });

    let updatedRows = 0;
    if (!dryRun) {
      let total = 0;
      for (const record of selected) {
        total += await this.client.reviewOntologyFact({
          fact_id: record.fact_id,
          decision: request.decision,
          reviewer,
          note
        });
      }
      updatedRows = total;
    }

    return {
      decision: request.decision,
      status_filter: status,
      stream_id_filter: request.stream_id,
      predicate_filter: request.predicate?.trim() || undefined,
      extractor_filter: request.extractor?.trim() || undefined,
      stale_days_filter: request.stale_days,
      min_confidence: minConfidence,
      max_confidence: maxConfidence,
      limit,
      dry_run: dryRun,
      reviewer,
      note,
      selected_count: selected.length,
      updated_rows: updatedRows,
      selected_facts: selected.map(mapOntologyFactBulkSelection)
    };
  }

  async openOntologyCase(request: OntologyCaseOpenRequest): Promise<OntologyCaseOpenResultDto> {
    const actor = request.actor?.trim() || 'system';
    const factIds = Array.from(new Set((request.fact_ids ?? []).filter((value) => value > 0))).sort(
      (a, b) => a - b
    );

    const created = await this.client.insertOntologyCase({
      stream_id: request.stream_id,
      title: request.title.trim(),
      description: request.description?.trim() ?? '',
      priority: request.priority ?? 'p2',
      owner: request.owner?.trim() ?? '',
      created_by: actor
    });
    const caseId = Number(created.case_id);
    const note = request.note?.trim() ?? '';

    await this.client.insertOntologyCaseEvent({
      case_id: caseId,
      action: 'open',
      actor,
      note,
      payload_json: JSON.stringify({
        title: request.title.trim(),
        priority: request.priority ?? 'p2',
        owner: request.owner?.trim() ?? ''
      })
    });

    const linkedFactIds: number[] = [];
    const skippedFactIds: number[] = [];
    for (const factId of factIds) {
      const linked = await this.client.linkOntologyCaseFact({
        case_id: caseId,
        fact_id: factId,
        added_by: actor,
        added_note: note,
        stream_id: request.stream_id
      });
      if (linked) {
        linkedFactIds.push(factId);
        await this.client.insertOntologyCaseEvent({
          case_id: caseId,
          action: 'fact_link',
          actor,
          note,
          payload_json: JSON.stringify({ fact_id: factId })
        });
      } else {
        skippedFactIds.push(factId);
      }
    }

    return {
      ...mapOntologyCase(created),
      linked_fact_ids: linkedFactIds,
      skipped_fact_ids: skippedFactIds
    };
  }

  async listOntologyCases(query: OntologyCaseListQuery): Promise<{
    stream_id_filter?: string;
    status_filter: 'open' | 'in_review' | 'resolved' | 'dismissed' | 'all';
    limit: number;
    count: number;
    cases: OntologyCaseSummaryDto[];
  }> {
    const status = query.status ?? 'open';
    const limit = query.limit ?? 100;
    const records = await this.client.listOntologyCases({
      stream_id: query.stream_id,
      status,
      limit
    });

    return {
      stream_id_filter: query.stream_id,
      status_filter: status,
      limit,
      count: records.length,
      cases: records.map(mapOntologyCaseSummary)
    };
  }

  async getOntologyCaseDetail(query: OntologyCaseDetailQuery): Promise<OntologyCaseDetailDto> {
    const caseRecord = await this.client.getOntologyCase({ case_id: query.case_id });
    if (!caseRecord) {
      throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${query.case_id}`);
    }

    const evidenceLimit = query.evidence_limit ?? 50;
    const [facts, decisions, events, alerts] = await Promise.all([
      this.client.listOntologyCaseFacts({
        case_id: query.case_id,
        evidence_limit: evidenceLimit
      }),
      this.client.listOntologyCaseDecisions({ case_id: query.case_id }),
      this.client.listOntologyCaseEvents({ case_id: query.case_id }),
      this.client.listOntologyAlerts({
        case_id: query.case_id,
        status: 'all',
        limit: 1000
      })
    ]);

    return {
      case: mapOntologyCase(caseRecord),
      facts: facts.map(mapOntologyCaseFact),
      decisions: decisions.map(mapOntologyCaseDecision),
      events: events.map(mapOntologyCaseEvent),
      alerts: alerts.map(mapOntologyAlertWithFactIds),
      evidence_limit: evidenceLimit
    };
  }

  async recordOntologyCaseDecision(request: OntologyCaseDecisionRecordRequest): Promise<OntologyCaseDecisionDto> {
    const caseRecord = await this.client.getOntologyCase({ case_id: request.case_id });
    if (!caseRecord) {
      throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${request.case_id}`);
    }

    const decision = await this.client.insertOntologyCaseDecision({
      case_id: request.case_id,
      decision_kind: request.decision_kind.trim(),
      verdict: request.verdict.trim(),
      summary: request.summary.trim(),
      rationale: request.rationale?.trim() ?? '',
      as_of_system_time: request.as_of_system_time,
      as_of_effective_time: request.as_of_effective_time ?? request.as_of_system_time,
      snapshot_id: request.snapshot_id?.trim() ?? '',
      source_evidence_json: JSON.stringify(request.source_evidence ?? []),
      supersedes_case_decision_id: request.supersedes_case_decision_id ?? 0,
      created_by: request.created_by?.trim() || 'system'
    });

    await this.client.insertOntologyCaseEvent({
      case_id: request.case_id,
      action: 'note',
      actor: request.created_by?.trim() || 'system',
      note: `decision recorded: ${request.decision_kind.trim()} -> ${request.verdict.trim()}`,
      payload_json: JSON.stringify({
        event_type: 'decision_recorded',
        case_decision_id: decision.case_decision_id,
        decision_kind: decision.decision_kind,
        verdict: decision.verdict,
        snapshot_id: decision.snapshot_id
      })
    });

    return mapOntologyCaseDecision(decision);
  }

  async createConflictDraftDecision(
    request: OntologyCaseConflictDraftRequest
  ): Promise<OntologyCaseConflictDraftResponse> {
    const predicate = request.predicate.trim();
    const srcConceptId = request.src_concept_id.trim();
    const actor = request.actor?.trim() || 'system';

    if (!predicate) {
      throw new TdbError('EMPTY_CONFLICT_PREDICATE', 400, 'predicate must not be blank');
    }
    if (!srcConceptId) {
      throw new TdbError('EMPTY_SRC_CONCEPT_ID', 400, 'src_concept_id must not be blank');
    }

    let caseRecord: OntologyCaseRecord | undefined;
    let requestedStreamId = request.stream_id?.trim();
    if (request.case_id) {
      caseRecord = await this.client.getOntologyCase({ case_id: request.case_id });
      if (!caseRecord) {
        throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${request.case_id}`);
      }
      if (requestedStreamId && requestedStreamId !== caseRecord.stream_id) {
        throw new TdbError(
          'CASE_STREAM_MISMATCH',
          409,
          'stream_id does not match the stream bound to case_id'
        );
      }
      requestedStreamId = requestedStreamId ?? caseRecord.stream_id;
    }

    const candidates = await this.client.listConflictPredicateOntologyCandidates({
      stream_id: requestedStreamId,
      predicate
    });
    const candidateRecord = candidates.find(
      (row) => row.src_concept_id === srcConceptId && (!requestedStreamId || row.stream_id === requestedStreamId)
    );
    if (!candidateRecord?.stream_id) {
      throw new TdbError(
        'ONTOLOGY_CONFLICT_CANDIDATE_NOT_FOUND',
        404,
        `conflict candidate not found for ${predicate} on ${srcConceptId}`
      );
    }

    const dstValues = (candidateRecord.dst_values ?? []).map((value) => String(value));
    const candidate: OntologyCaseConflictDraftCandidateDto = {
      stream_id: candidateRecord.stream_id,
      src_concept_id: candidateRecord.src_concept_id || srcConceptId,
      predicate,
      dst_values: dstValues,
      dst_count: Number(candidateRecord.dst_count ?? 0),
      fact_count: Number(candidateRecord.fact_count ?? 0),
      fact_ids: normalizeNumberArray(candidateRecord.fact_ids),
      draft_key: buildConflictDraftKey({
        stream_id: candidateRecord.stream_id,
        src_concept_id: candidateRecord.src_concept_id || srcConceptId,
        predicate,
        dst_values: dstValues
      })
    };

    if (request.dry_run) {
      return {
        created_case: false,
        deduped: false,
        candidate
      };
    }

    const title = `Capability conflict ${predicate} for ${candidate.src_concept_id}`;
    let createdCase = false;
    if (!caseRecord) {
      const activeCase = await this.client.getActiveOntologyCaseByTitle({ title });
      if (activeCase?.stream_id === candidate.stream_id) {
        caseRecord = activeCase;
      }
    }
    if (!caseRecord) {
      caseRecord = await this.client.insertOntologyCase({
        stream_id: candidate.stream_id,
        title,
        description: `Detected conflicting ${predicate} values for ${candidate.src_concept_id} in ${candidate.stream_id}.`,
        priority: 'p1',
        owner: 'storage_expert',
        created_by: actor
      });
      createdCase = true;
      await this.client.insertOntologyCaseEvent({
        case_id: Number(caseRecord.case_id),
        action: 'open',
        actor,
        note: 'auto-opened for conflict draft',
        payload_json: JSON.stringify({
          title,
          priority: 'p1',
          owner: 'storage_expert'
        })
      });
    }

    if (!caseRecord.stream_id || caseRecord.stream_id !== candidate.stream_id) {
      throw new TdbError(
        'CASE_STREAM_MISMATCH',
        409,
        'stream_id does not match the stream bound to case_id'
      );
    }

    const existingDecisions = await this.client.listOntologyCaseDecisions({
      case_id: Number(caseRecord.case_id)
    });
    const matchingDecision = existingDecisions.find((decision) => {
      if (decision.decision_kind !== 'capability_resolution_draft' || decision.verdict !== 'needs_review') {
        return false;
      }
      return parseDecisionEvidenceJson(decision.source_evidence_json).some(
        (item) => item.draft_key === candidate.draft_key
      );
    });

    if (matchingDecision) {
      return {
        case: mapOntologyCase(caseRecord),
        decision: mapOntologyCaseDecision(matchingDecision),
        created_case: createdCase,
        deduped: true,
        candidate
      };
    }

    const evidence = [
      {
        draft_type: 'conflict_predicate',
        stream_id: candidate.stream_id,
        src_concept_id: candidate.src_concept_id,
        predicate: candidate.predicate,
        fact_ids: candidate.fact_ids,
        dst_values: [...candidate.dst_values].sort(),
        fact_count: candidate.fact_count,
        dst_count: candidate.dst_count,
        draft_key: candidate.draft_key
      }
    ];
    const decisionNow = nowIso();
    const decision = await this.recordOntologyCaseDecision({
      case_id: Number(caseRecord.case_id),
      decision_kind: 'capability_resolution_draft',
      verdict: 'needs_review',
      summary: `${candidate.src_concept_id} has conflicting ${candidate.predicate} values and requires review`,
      rationale: `Detected ${candidate.dst_count} distinct ${candidate.predicate} values across ${candidate.fact_count} facts for ${candidate.src_concept_id} in ${candidate.stream_id}; no automatic resolution rule selected a working truth.`,
      as_of_system_time: decisionNow,
      as_of_effective_time: decisionNow,
      snapshot_id: '',
      source_evidence: evidence,
      supersedes_case_decision_id: undefined,
      created_by: actor
    });

    return {
      case: mapOntologyCase(caseRecord),
      decision,
      created_case: createdCase,
      deduped: false,
      candidate
    };
  }

  async listOntologyCaseDecisions(query: OntologyCaseDecisionListQuery): Promise<{
    case_id: number;
    count: number;
    decisions: OntologyCaseDecisionDto[];
  }> {
    const caseRecord = await this.client.getOntologyCase({ case_id: query.case_id });
    if (!caseRecord) {
      throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${query.case_id}`);
    }

    const decisions = await this.client.listOntologyCaseDecisions({ case_id: query.case_id });
    return {
      case_id: query.case_id,
      count: decisions.length,
      decisions: decisions.map(mapOntologyCaseDecision)
    };
  }

  async explainOntologyCase(query: OntologyCaseExplainQuery): Promise<OntologyCaseExplainDto> {
    const detail = await this.getOntologyCaseDetail(query);
    const activeAlertCount = detail.alerts.filter((item) => item.status !== 'closed').length;
    const latestEventAction = detail.events[0]?.action;
    const flags: string[] = [];

    if (detail.facts.length === 0) {
      flags.push('no_facts_linked');
    }
    if (activeAlertCount > 0) {
      flags.push('has_active_alerts');
    }
    if (!detail.case.owner) {
      flags.push('owner_unassigned');
    }
    if (detail.case.status === 'resolved' || detail.case.status === 'dismissed') {
      flags.push('case_closed');
    }

    const reasoningSteps = [
      `Case ${detail.case.case_id} is currently ${detail.case.status}.`,
      `Case links ${detail.facts.length} fact(s), ${detail.alerts.length} alert(s), and ${detail.events.length} case event(s).`
    ];
    if (latestEventAction) {
      reasoningSteps.push(`Latest case event action is ${latestEventAction}.`);
    }
    if (activeAlertCount > 0) {
      reasoningSteps.push(`${activeAlertCount} alert(s) remain active on this case.`);
    }

    return {
      ...detail,
      explanation: {
        summary: `Case ${detail.case.title} is ${detail.case.status} with ${detail.facts.length} linked fact(s) and ${activeAlertCount} active alert(s).`,
        fact_count: detail.facts.length,
        event_count: detail.events.length,
        alert_count: detail.alerts.length,
        active_alert_count: activeAlertCount,
        latest_event_action: latestEventAction,
        reasoning_steps: reasoningSteps,
        flags
      }
    };
  }

  async updateOntologyCase(request: OntologyCaseUpdateRequest): Promise<OntologyCaseDto> {
    const actor = request.actor?.trim() || 'system';
    const note = request.note?.trim() ?? '';
    const owner = request.owner?.trim();
    if (!request.status && !owner && note === '') {
      throw new TdbError(
        'EMPTY_CASE_UPDATE',
        400,
        'At least one of status, owner, or note must be provided'
      );
    }

    const updatedRows = await this.client.updateOntologyCase({
      case_id: request.case_id,
      status: request.status,
      owner
    });
    if (updatedRows === 0) {
      throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${request.case_id}`);
    }

    if (request.status) {
      await this.client.insertOntologyCaseEvent({
        case_id: request.case_id,
        action: 'status_change',
        actor,
        note,
        payload_json: JSON.stringify({ status: request.status })
      });
    }
    if (owner !== undefined) {
      await this.client.insertOntologyCaseEvent({
        case_id: request.case_id,
        action: 'owner_change',
        actor,
        note,
        payload_json: JSON.stringify({ owner })
      });
    }
    if (note !== '') {
      await this.client.insertOntologyCaseEvent({
        case_id: request.case_id,
        action: 'note',
        actor,
        note,
        payload_json: '{}'
      });
    }

    const updatedRecord = await this.client.getOntologyCase({ case_id: request.case_id });
    if (!updatedRecord) {
      throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${request.case_id}`);
    }
    return mapOntologyCase(updatedRecord);
  }

  async openOntologyAlert(request: OntologyAlertOpenRequest): Promise<OntologyAlertDto> {
    const actor = request.actor?.trim() || 'system';
    let caseStreamId: string | undefined;
    if (request.case_id) {
      const caseRecord = await this.client.getOntologyCase({ case_id: request.case_id });
      caseStreamId = caseRecord?.stream_id;
      if (!caseStreamId) {
        throw new TdbError('ONTOLOGY_CASE_NOT_FOUND', 404, `ontology case not found: ${request.case_id}`);
      }
    }

    const streamId = request.stream_id?.trim() || caseStreamId;
    if (!streamId) {
      throw new TdbError(
        'MISSING_STREAM_OR_CASE',
        400,
        'Either stream_id or case_id must be provided'
      );
    }
    if (request.case_id && request.stream_id && caseStreamId && request.stream_id.trim() !== caseStreamId) {
      throw new TdbError(
        'CASE_STREAM_MISMATCH',
        409,
        'stream_id does not match the stream bound to case_id'
      );
    }

    const alert = await this.client.insertOntologyAlert({
      case_id: request.case_id,
      stream_id: streamId,
      severity: request.severity ?? 'medium',
      message: request.message.trim(),
      detail_json: JSON.stringify({
        source: 'manual',
        actor
      })
    });

    if (request.case_id) {
      await this.client.insertOntologyCaseEvent({
        case_id: request.case_id,
        action: 'alert_link',
        actor,
        note: request.message.trim(),
        payload_json: JSON.stringify({
          alert_id: Number(alert.alert_id),
          severity: request.severity ?? 'medium'
        })
      });
    }

    return mapOntologyAlert(alert);
  }

  async listOntologyAlerts(query: OntologyAlertListQuery): Promise<{
    stream_id_filter?: string;
    status_filter: 'open' | 'acked' | 'closed' | 'all';
    limit: number;
    count: number;
    alerts: OntologyAlertSummaryDto[];
  }> {
    const status = query.status ?? 'open';
    const limit = query.limit ?? 100;
    const records = await this.client.listOntologyAlerts({
      stream_id: query.stream_id,
      status,
      limit
    });

    return {
      stream_id_filter: query.stream_id,
      status_filter: status,
      limit,
      count: records.length,
      alerts: records.map(mapOntologyAlertSummary)
    };
  }

  async explainOntologyAlert(query: OntologyAlertExplainQuery): Promise<OntologyAlertExplainDto> {
    const alertRecord = await this.client.getOntologyAlertDetail({ alert_id: query.alert_id });
    if (!alertRecord) {
      throw new TdbError('ONTOLOGY_ALERT_NOT_FOUND', 404, `ontology alert not found: ${query.alert_id}`);
    }

    const mappedAlert = {
      ...mapOntologyAlert(alertRecord),
      case_title: alertRecord.case_title ?? undefined,
      linked_fact_count: Number(alertRecord.linked_fact_count ?? 0),
      linked_fact_ids: normalizeNumberArray(alertRecord.linked_fact_ids)
    };
    const caseRecord = mappedAlert.case_id ? await this.client.getOntologyCase({ case_id: mappedAlert.case_id }) : undefined;
    const source: 'manual' | 'rule' = mappedAlert.rule_key ? 'rule' : 'manual';
    const active = mappedAlert.status !== 'closed';
    const flags: string[] = [];

    if (source === 'rule') {
      flags.push('rule_generated');
    }
    if (active) {
      flags.push('active_alert');
    }
    if (!mappedAlert.case_id) {
      flags.push('case_unbound');
    }
    if (mappedAlert.linked_fact_count === 0) {
      flags.push('no_linked_facts');
    }

    const reasoningSteps = [
      `Alert ${mappedAlert.alert_id} is ${mappedAlert.status} with severity ${mappedAlert.severity}.`,
      `Alert source is ${source}${mappedAlert.rule_key ? ` via rule ${mappedAlert.rule_key}` : ''}.`,
      `Alert links ${mappedAlert.linked_fact_count} fact(s).`
    ];
    if (mappedAlert.case_id) {
      reasoningSteps.push(`Alert is attached to case ${mappedAlert.case_id}.`);
    }

    return {
      alert: mappedAlert,
      case: caseRecord ? mapOntologyCase(caseRecord) : undefined,
      explanation: {
        summary: `Alert ${mappedAlert.alert_id} is ${mappedAlert.status} (${mappedAlert.severity}) and links ${mappedAlert.linked_fact_count} fact(s).`,
        source,
        active,
        case_bound: Boolean(mappedAlert.case_id),
        linked_fact_count: mappedAlert.linked_fact_count,
        reasoning_steps: reasoningSteps,
        flags
      }
    };
  }

  async updateOntologyAlert(request: OntologyAlertUpdateRequest): Promise<OntologyAlertDto> {
    const actor = request.actor?.trim() || 'system';
    const note = request.note?.trim() ?? '';

    const updatedRows = await this.client.updateOntologyAlert({
      alert_id: request.alert_id,
      status: request.status,
      actor
    });
    if (updatedRows === 0) {
      throw new TdbError('ONTOLOGY_ALERT_NOT_FOUND', 404, `ontology alert not found: ${request.alert_id}`);
    }

    const updated = await this.client.getOntologyAlertDetail({ alert_id: request.alert_id });
    if (!updated) {
      throw new TdbError('ONTOLOGY_ALERT_NOT_FOUND', 404, `ontology alert not found: ${request.alert_id}`);
    }

    if (updated.case_id) {
      await this.client.insertOntologyCaseEvent({
        case_id: Number(updated.case_id),
        action: 'alert_link',
        actor,
        note,
        payload_json: JSON.stringify({
          alert_id: request.alert_id,
          status: request.status
        })
      });
    }

    return mapOntologyAlert(updated);
  }



  async listOntologyOpsRuleConfig(query: OntologyOpsRuleConfigListQuery): Promise<{
    stream_id_filter?: string;
    count: number;
    configs: OntologyOpsRuleConfigDto[];
  }> {
    const records = await this.client.listOntologyOpsRuleConfig({
      stream_id: query.stream_id
    });

    const configs = records.map(mapOntologyOpsRuleConfig);
    return {
      stream_id_filter: query.stream_id,
      count: configs.length,
      configs
    };
  }

  async upsertOntologyOpsRuleConfig(
    request: OntologyOpsRuleConfigUpsertRequest
  ): Promise<OntologyOpsRuleConfigDto> {
    const record = await this.client.upsertOntologyOpsRuleConfig({
      stream_id: request.stream_id,
      rule_name: request.rule_name,
      enabled: request.enabled ?? false,
      stale_days: request.stale_days ?? 0,
      conflict_predicate: request.conflict_predicate ?? '',
      severity: request.severity ?? 'medium',
      note: request.note?.trim() ?? '',
      updated_by: request.updated_by?.trim() || 'system'
    });

    return mapOntologyOpsRuleConfig(record);
  }

  async runOntologyOpsRules(request: OntologyOpsRuleRunRequest): Promise<OntologyOpsRuleRunDto> {
    const runStarted = nowIso();
    const dryRun = request.dry_run ?? false;
    const streamId = request.stream_id;

    const applicableConfigs = await this.client.listApplicableOntologyOpsRuleConfig({
      stream_id: streamId
    });

    let staleEnabled = false;
    let conflictEnabled = false;
    let effectiveStaleDays = 30;
    let effectiveConflictPredicate = '';
    let staleSeverity: OntologyAlertDto['severity'] = 'medium';
    let conflictSeverity: OntologyAlertDto['severity'] = 'high';

    for (const config of applicableConfigs) {
      const configStaleDays = config.stale_days ? Number(config.stale_days) : undefined;
      const configPredicate = config.conflict_predicate?.trim() || undefined;
      const configSeverity = (config.severity ?? undefined) as OntologyAlertDto['severity'] | undefined;
      switch (config.rule_name) {
        case 'default':
          staleEnabled = config.enabled;
          conflictEnabled = config.enabled;
          if (configStaleDays && configStaleDays > 0) {
            effectiveStaleDays = configStaleDays;
          }
          if (configPredicate) {
            effectiveConflictPredicate = configPredicate;
          }
          if (configSeverity) {
            staleSeverity = configSeverity;
            conflictSeverity = configSeverity;
          }
          break;
        case 'stale_pending':
          staleEnabled = config.enabled;
          if (configStaleDays && configStaleDays > 0) {
            effectiveStaleDays = configStaleDays;
          }
          if (configSeverity) {
            staleSeverity = configSeverity;
          }
          break;
        case 'conflict_predicate':
          conflictEnabled = config.enabled;
          if (configPredicate) {
            effectiveConflictPredicate = configPredicate;
          }
          if (configSeverity) {
            conflictSeverity = configSeverity;
          }
          break;
      }
    }

    const [staleRows, conflictRows] = await Promise.all([
      staleEnabled
        ? this.client.listStalePendingOntologyCandidates({
            stream_id: streamId,
            stale_days: effectiveStaleDays
          })
        : Promise.resolve([]),
      conflictEnabled
        ? this.client.listConflictPredicateOntologyCandidates({
            stream_id: streamId,
            predicate: effectiveConflictPredicate
          })
        : Promise.resolve([])
    ]);

    const candidates: Record<string, unknown>[] = [];
    for (const record of staleRows) {
      const staleFactCount = Number(record.stale_fact_count);
      if (!record.stream_id || staleFactCount <= 0) {
        continue;
      }
      const ruleKey = `stale_pending:${record.stream_id}:${effectiveStaleDays}`;
      const title = `Rule stale_pending for ${record.stream_id} (> ${effectiveStaleDays}d)`;
      const message = `Detected ${staleFactCount} stale pending ontology facts in ${record.stream_id}`;
      candidates.push({
        rule: 'stale_pending',
        rule_key: ruleKey,
        stream_id: record.stream_id,
        stale_fact_count: staleFactCount,
        severity: staleSeverity,
        fact_ids: normalizeNumberArray(record.fact_ids),
        title,
        message
      });
    }
    for (const record of conflictRows) {
      const dstCount = Number(record.dst_count);
      const factCount = Number(record.fact_count);
      if (!record.stream_id || !record.src_concept_id || dstCount <= 1) {
        continue;
      }
      const ruleKey = `conflict:${effectiveConflictPredicate}:${record.stream_id}:${record.src_concept_id}`;
      const title = `Rule conflict ${effectiveConflictPredicate} for ${record.src_concept_id}`;
      const message = `Detected conflicting ${effectiveConflictPredicate} values for ${record.src_concept_id} (${dstCount} distinct values, ${factCount} facts)`;
      candidates.push({
        rule: 'conflict_predicate',
        rule_key: ruleKey,
        stream_id: record.stream_id,
        src_concept_id: record.src_concept_id,
        predicate: effectiveConflictPredicate,
        severity: conflictSeverity,
        dst_values: record.dst_values,
        dst_count: dstCount,
        fact_count: factCount,
        fact_ids: normalizeNumberArray(record.fact_ids),
        title,
        message
      });
    }

    const createdCases: Record<string, unknown>[] = [];
    const existingCases: Record<string, unknown>[] = [];
    const createdAlerts: Record<string, unknown>[] = [];
    const existingAlerts: Record<string, unknown>[] = [];

    const actor = 'system';
    if (!dryRun) {
      for (const candidate of candidates) {
        const streamIdValue = String(candidate.stream_id ?? '');
        const title = String(candidate.title ?? '');
        const message = String(candidate.message ?? '');
        const ruleKey = String(candidate.rule_key ?? '');
        if (!streamIdValue || !title || !ruleKey) {
          continue;
        }

        let caseRecord = await this.client.getActiveOntologyCaseByTitle({
          title
        });
        if (caseRecord) {
          existingCases.push({
            case_id: Number(caseRecord.case_id),
            stream_id: streamIdValue,
            title
          });
        } else {
          caseRecord = await this.client.insertOntologyCase({
            stream_id: streamIdValue,
            title,
            description: message,
            priority: 'p2',
            owner: '',
            created_by: actor
          });
          createdCases.push({
            case_id: Number(caseRecord.case_id),
            stream_id: streamIdValue,
            title
          });
          await this.client.insertOntologyCaseEvent({
            case_id: Number(caseRecord.case_id),
            action: 'open',
            actor,
            note: message,
            payload_json: JSON.stringify(candidate)
          });
        }

        const caseId = Number(caseRecord.case_id);
        const ruleSeverity = normalizeSeverity(
          typeof candidate.severity === 'string' ? candidate.severity : undefined,
          candidate.rule === 'conflict_predicate' ? 'high' : 'medium'
        );
        const factIds = normalizeNumberArray(candidate.fact_ids);

        const existingAlert = await this.client.getActiveOntologyAlertByRuleKey({
          rule_key: ruleKey
        });
        let alertId: number;
        if (existingAlert) {
          const nextSeverity = maxSeverity(existingAlert.severity, ruleSeverity);
          await this.client.refreshTriggeredOntologyAlert({
            alert_id: Number(existingAlert.alert_id),
            case_id: caseId,
            severity: nextSeverity,
            message,
            detail_json: JSON.stringify(candidate)
          });
          existingAlerts.push({
            alert_id: Number(existingAlert.alert_id),
            stream_id: streamIdValue,
            rule_key: ruleKey,
            severity_before: existingAlert.severity,
            severity_after: nextSeverity,
            trigger_count_before: existingAlert.trigger_count,
            trigger_count_after: existingAlert.trigger_count + 1
          });
          alertId = Number(existingAlert.alert_id);
        } else {
          const createdAlert = await this.client.insertOntologyAlert({
            case_id: caseId,
            stream_id: streamIdValue,
            severity: ruleSeverity,
            message,
            detail_json: JSON.stringify({
              ...candidate,
              rule_key: ruleKey
            }),
            rule_key: ruleKey
          });
          alertId = Number(createdAlert.alert_id);
          createdAlerts.push({
            alert_id: alertId,
            case_id: caseId,
            stream_id: streamIdValue,
            rule_key: ruleKey,
            severity: ruleSeverity,
            trigger_count: 1
          });
          await this.client.insertOntologyCaseEvent({
            case_id: caseId,
            action: 'alert_link',
            actor,
            note: message,
            payload_json: JSON.stringify({
              alert_id: alertId,
              rule_key: ruleKey,
              severity: ruleSeverity
            })
          });
        }

        for (const factId of factIds) {
          await this.client.linkOntologyAlertFact({
            alert_id: alertId,
            fact_id: factId
          });
        }
      }
    }

    const result: OntologyOpsRuleRunResultDto = {
      stream_id_filter: streamId,
      stale_days: effectiveStaleDays,
      conflict_predicate: effectiveConflictPredicate,
      rules_enabled: {
        stale_pending: staleEnabled,
        conflict_predicate: conflictEnabled
      },
      rule_severity: {
        stale_pending: staleSeverity,
        conflict_predicate: conflictSeverity
      },
      dry_run: dryRun,
      candidate_count: candidates.length,
      candidates,
      created_cases: createdCases,
      existing_cases: existingCases,
      created_alerts: createdAlerts,
      existing_alerts: existingAlerts
    };

    const runRecord = await this.client.insertOntologyOpsRuleRun({
      stream_id_filter: streamId,
      stale_days: effectiveStaleDays,
      conflict_predicate: effectiveConflictPredicate,
      dry_run: dryRun,
      candidate_count: candidates.length,
      created_case_count: createdCases.length,
      existing_case_count: existingCases.length,
      created_alert_count: createdAlerts.length,
      existing_alert_count: existingAlerts.length,
      payload_json: JSON.stringify(result),
      duration_ms: Date.now() - new Date(runStarted).getTime()
    });

    return mapOntologyOpsRuleRun(runRecord);
  }

  async listOntologyOpsRuns(query: OntologyOpsRuleRunListQuery): Promise<{
    stream_id_filter?: string;
    limit: number;
    count: number;
    runs: OntologyOpsRuleRunDto[];
  }> {
    const limit = query.limit ?? 50;
    const records = await this.client.listOntologyOpsRuns({
      stream_id: query.stream_id,
      limit
    });
    return {
      stream_id_filter: query.stream_id,
      limit,
      count: records.length,
      runs: records.map(mapOntologyOpsRuleRun)
    };
  }

  async explainOntologyOpsRun(query: OntologyOpsRuleRunExplainQuery): Promise<OntologyOpsRuleRunExplainDto> {
    const record = await this.client.getOntologyOpsRun({ run_id: query.run_id });
    if (!record) {
      throw new TdbError('ONTOLOGY_OPS_RUN_NOT_FOUND', 404, `ontology ops rule run not found: ${query.run_id}`);
    }

    const run = mapOntologyOpsRuleRun(record);
    const payload = mapOntologyOpsRuleRunPayload(JSON.parse(record.payload_json || '{}'));
    const triggeredRules = Array.from(
      new Set(
        payload.candidates
          .map((candidate) => String(candidate.rule ?? ''))
          .filter((value) => value.length > 0)
      )
    );
    const actionCount =
      payload.created_cases.length +
      payload.existing_cases.length +
      payload.created_alerts.length +
      payload.existing_alerts.length;
    const flags: string[] = [];
    if (run.dry_run) {
      flags.push('dry_run');
    }
    if (payload.created_cases.length > 0 || payload.created_alerts.length > 0) {
      flags.push('created_actions');
    }
    if (payload.existing_cases.length > 0 || payload.existing_alerts.length > 0) {
      flags.push('deduped_existing_actions');
    }
    if (payload.candidate_count === 0) {
      flags.push('no_candidates');
    }

    const reasoningSteps = [
      `Run ${run.run_id} evaluated ${payload.candidate_count} candidate(s) for stream ${payload.stream_id_filter ?? 'all'}.`,
      `Triggered rule set: ${triggeredRules.length > 0 ? triggeredRules.join(', ') : 'none'}.`,
      run.dry_run
        ? 'Run was executed in dry-run mode, so no new cases or alerts were persisted.'
        : `Run produced ${payload.created_cases.length} new case(s), ${payload.created_alerts.length} new alert(s), and reused ${payload.existing_cases.length + payload.existing_alerts.length} existing record(s).`
    ];

    return {
      run,
      payload,
      explanation: {
        summary: `Ops run ${run.run_id} processed ${payload.candidate_count} candidate(s) and generated ${actionCount} action outcome(s).`,
        triggered_rules: triggeredRules,
        candidate_count: payload.candidate_count,
        action_count: actionCount,
        dry_run: run.dry_run,
        reasoning_steps: reasoningSteps,
        flags
      }
    };
  }
}

function mapMethodologyFramework(record: MethodologyFrameworkRecord): MethodologyFrameworkDto {
  return {
    framework_id: record.framework_id,
    domain: record.domain,
    framework_name: record.framework_name,
    version_label: record.version_label,
    status: record.status as MethodologyFrameworkDto['status'],
    description: record.description,
    owner: record.owner,
    question_types: safeParseJson<string[]>(record.question_types_json, []),
    metadata: safeParseJson<Record<string, unknown>>(record.metadata_json, {}),
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapTaxonomyScheme(record: TaxonomySchemeRecord): TaxonomySchemeDto {
  return {
    scheme_id: record.scheme_id,
    framework_id: record.framework_id,
    scheme_name: record.scheme_name,
    scheme_type: record.scheme_type as TaxonomySchemeDto['scheme_type'],
    status: record.status as TaxonomySchemeDto['status'],
    description: record.description,
    canonical_source: record.canonical_source,
    scheme: safeParseJson<Record<string, unknown>>(record.scheme_json, {}),
    metadata: safeParseJson<Record<string, unknown>>(record.metadata_json, {}),
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapEvidencePolicyRule(record: EvidencePolicyRuleRecord): EvidencePolicyRuleDto {
  return {
    evidence_policy_rule_id: record.evidence_policy_rule_id,
    framework_id: record.framework_id,
    rule_key: record.rule_key,
    question_type: record.question_type,
    evidence_kind: record.evidence_kind,
    source_tier: record.source_tier,
    status: record.status as EvidencePolicyRuleDto['status'],
    priority: record.priority,
    review_required: record.review_required,
    applicability: safeParseJson<Record<string, unknown>>(record.applicability_json, {}),
    effect: safeParseJson<Record<string, unknown>>(record.effect_json, {}),
    description: record.description,
    metadata: safeParseJson<Record<string, unknown>>(record.metadata_json, {}),
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapAssertionPolicyRule(record: AssertionPolicyRuleRecord): AssertionPolicyRuleDto {
  return {
    assertion_policy_rule_id: record.assertion_policy_rule_id,
    framework_id: record.framework_id,
    rule_key: record.rule_key,
    assertion_type: record.assertion_type,
    question_type: record.question_type,
    status: record.status as AssertionPolicyRuleDto['status'],
    priority: record.priority,
    review_required: record.review_required,
    required_evidence: safeParseJson<Record<string, unknown>>(record.required_evidence_json, {}),
    outcome: safeParseJson<Record<string, unknown>>(record.outcome_json, {}),
    description: record.description,
    metadata: safeParseJson<Record<string, unknown>>(record.metadata_json, {}),
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapReviewPolicy(record: ReviewPolicyRecord): ReviewPolicyDto {
  return {
    review_policy_id: record.review_policy_id,
    framework_id: record.framework_id,
    policy_key: record.policy_key,
    question_type: record.question_type,
    trigger_kind: record.trigger_kind,
    action: record.action,
    status: record.status as ReviewPolicyDto['status'],
    priority: record.priority,
    trigger: safeParseJson<Record<string, unknown>>(record.trigger_json, {}),
    description: record.description,
    metadata: safeParseJson<Record<string, unknown>>(record.metadata_json, {}),
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapMethodologyFrameworkBundle(response: GetMethodologyFrameworkBundleResponse): MethodologyFrameworkBundleDto {
  return {
    framework: response.framework ? mapMethodologyFramework(response.framework) : undefined,
    taxonomy_schemes: (response.taxonomy_schemes ?? []).map(mapTaxonomyScheme),
    evidence_policy_rules: (response.evidence_policy_rules ?? []).map(mapEvidencePolicyRule),
    assertion_policy_rules: (response.assertion_policy_rules ?? []).map(mapAssertionPolicyRule),
    review_policies: (response.review_policies ?? []).map(mapReviewPolicy)
  };
}

function mapRule(record: RuleRecord): RuleDto {
  return {
    rule_key: record.rule_key,
    rule_version: record.rule_version,
    severity: (record.severity as RuleDto['severity']) ?? 'low',
    expression: record.expression,
    effective_from: toIso(record.effective_from),
    effective_to: record.effective_to ? toIso(record.effective_to) : '',
    system_from: toIso(record.system_from),
    system_to: toIso(record.system_to),
    source_artifact_version_id: record.source_artifact_version_id ?? ''
  };
}

function mapAuthority(record: AuthorityGrantRecord): AuthorityGrantDto {
  return {
    authority_grant_id: Number(record.authority_grant_id),
    grantee_id: record.grantee_id,
    action_type: record.action_type,
    scope: JSON.parse(record.scope_json || '{}'),
    valid_from: toIso(record.valid_from),
    valid_to: toIso(record.valid_to),
    system_from: toIso(record.system_from),
    system_to: toIso(record.system_to),
    mandate_artifact_version_id: record.mandate_artifact_version_id
  };
}

function mapOverride(record: RuleOverrideRecord): RuleOverrideDto {
  return {
    rule_override_id: Number(record.rule_override_id),
    rule_key: record.rule_key,
    rule_version: record.rule_version,
    authority_grant_id: Number(record.authority_grant_id),
    justification_artifact_version_id: record.justification_artifact_version_id,
    valid_from: toIso(record.valid_from),
    valid_to: toIso(record.valid_to),
    system_from: toIso(record.system_from),
    system_to: toIso(record.system_to),
    case_id: record.case_id ? Number(record.case_id) : undefined,
    event_id: record.event_id ? Number(record.event_id) : undefined
  };
}

function toIso(value: string): string {
  return new Date(value).toISOString();
}

function nowIso(): string {
  return new Date().toISOString();
}

function parseScopeQuery(scopeRaw?: string): Record<string, unknown> | undefined {
  if (!scopeRaw) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(scopeRaw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      throw new Error('scope must be a JSON object');
    }
    return parsed as Record<string, unknown>;
  } catch (_err) {
    throw new TdbError(
      'INVALID_SCOPE_JSON',
      400,
      'scope must be a valid JSON object string'
    );
  }
}

function mapOntologyFact(record: OntologyFactRecord): OntologyFactDto {
  return {
    fact_id: Number(record.fact_id),
    statement_id: record.statement_id || undefined,
    src_concept_id: record.src_concept_id,
    src_concept_label: record.src_concept_label || undefined,
    predicate: record.predicate,
    dst_concept_id: record.dst_concept_id,
    dst_concept_label: record.dst_concept_label || undefined,
    qualifier_json: safeParseJson<Record<string, unknown>>(record.qualifier_json, {}),
    confidence: Number(record.confidence),
    extractor: record.extractor,
    status: record.status as OntologyFactDto['status'],
    review_note: record.review_note,
    valid_from: record.valid_from ? toIso(record.valid_from) : undefined,
    valid_to: record.valid_to ? toIso(record.valid_to) : undefined,
    created_at: toIso(record.created_at),
    updated_at: toIso(record.updated_at)
  };
}

function mapOntologyFactReview(record: OntologyFactReviewRecord): OntologyFactReviewDto {
  return {
    review_id: Number(record.review_id),
    fact_id: Number(record.fact_id),
    decision: record.decision as OntologyFactReviewDto['decision'],
    reviewer: record.reviewer,
    note: record.note,
    created_at: toIso(record.created_at)
  };
}

function mapOntologyFactEvidence(record: OntologyFactEvidenceRecord): OntologyFactEvidenceDto {
  return {
    stream_id: record.stream_id,
    event_id: record.event_id,
    asset_id: record.asset_id || undefined,
    version_number: record.version_number > 0 ? Number(record.version_number) : undefined,
    source_span: record.source_span || undefined,
    evidence_json: safeParseJson<Record<string, unknown>>(record.evidence_json, {}),
    confidence: Number(record.confidence),
    created_at: toIso(record.created_at),
    updated_at: toIso(record.updated_at)
  };
}

function mapSemanticReferenceToFactEvidence(
  reference: SemanticStatementReferenceRecord
): OntologyFactEvidenceDto {
  const payload = safeParseJson<Record<string, unknown>>(reference.evidence?.evidence_payload_json, {});
  const primaryLocator = reference.locators?.[0];
  const sentenceRef = safeParseJson<Record<string, unknown>>(primaryLocator?.sentence_ref_json, {});
  return {
    stream_id: String(payload.stream_id ?? ''),
    event_id: String(payload.event_id ?? reference.evidence?.source_id ?? ''),
    asset_id: reference.evidence?.artifact_version_id || undefined,
    version_number: undefined,
    source_span: reference.source_span || undefined,
    evidence_json: payload,
    sentence:
      typeof sentenceRef.sentence_index === 'number' ||
      cleanOptionalText(primaryLocator?.normalized_text) ||
      cleanOptionalText(primaryLocator?.preview_text)
        ? {
            sent_index: Number(sentenceRef.sentence_index ?? 0),
            sentence_text:
              cleanOptionalText(primaryLocator?.normalized_text) ||
              cleanOptionalText(primaryLocator?.preview_text) ||
              ''
          }
        : undefined,
    confidence: 1,
    created_at: reference.evidence?.created_at || '',
    updated_at: reference.evidence?.updated_at || ''
  };
}

function cleanOptionalText(value: string | null | undefined): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function mapOntologyFactLinkedCase(record: OntologyFactLinkedCaseRecord): OntologyFactLinkedCaseDto {
  return {
    case_id: Number(record.case_id),
    stream_id: record.stream_id,
    title: record.title,
    status: record.status as OntologyFactLinkedCaseDto['status'],
    priority: record.priority as OntologyFactLinkedCaseDto['priority'],
    owner: record.owner,
    linked_at: toIso(record.linked_at)
  };
}

function mapOntologyFactLinkedAlert(record: OntologyFactLinkedAlertRecord): OntologyFactLinkedAlertDto {
  return {
    alert_id: Number(record.alert_id),
    case_id: record.case_id ? Number(record.case_id) : undefined,
    stream_id: record.stream_id,
    severity: record.severity as OntologyFactLinkedAlertDto['severity'],
    status: record.status as OntologyFactLinkedAlertDto['status'],
    message: record.message,
    rule_key: record.rule_key || undefined,
    linked_at: toIso(record.linked_at)
  };
}

function mapOntologyFactBulkSelection(record: OntologyFactBulkSelectionRecord): OntologyFactBulkSelectionDto {
  return {
    fact_id: Number(record.fact_id),
    predicate: (record as any).predicate ?? '',
    confidence: Number(record.confidence),
    extractor: (record as any).extractor ?? '',
    updated_at: toIso((record as any).updated_at)
  };
}

function mapOntologyCase(record: OntologyCaseRecord): OntologyCaseDto {
  return {
    case_id: Number(record.case_id),
    stream_id: record.stream_id,
    title: record.title,
    description: record.description,
    priority: record.priority as OntologyCaseDto['priority'],
    status: record.status as OntologyCaseDto['status'],
    owner: record.owner ?? undefined,
    created_by: record.created_by,
    created_at: toIso(record.created_at),
    updated_at: toIso(record.updated_at)
  };
}

function mapOntologyCaseSummary(record: OntologyCaseSummaryRecord): OntologyCaseSummaryDto {
  return {
    ...mapOntologyCase(record),
    fact_count: Number((record as any).linked_fact_count ?? 0),
    active_alert_count: Number(record.active_alert_count ?? 0)
  };
}

function mapOntologyCaseFact(record: OntologyCaseFactRecord): OntologyCaseFactDto {
  return {
    fact_id: Number(record.fact_id),
    predicate: record.predicate,
    subject_entity_id: (record as any).subject_entity_id ?? '',
    object_entity_id: (record as any).object_entity_id ?? '',
    object_value_json: JSON.parse((record as any).object_value_json || '{}'),
    confidence: Number(record.confidence),
    extractor: record.extractor,
    status: record.status as OntologyCaseFactDto['status'],
    decision: (record as any).decision as OntologyCaseFactDto['decision'],
    evidence_sample: [], // TODO: map evidence sample correctly
    added_by: record.added_by,
    added_at: toIso((record as any).added_at)
  };
}

function mapOntologyCaseEvent(record: OntologyCaseEventRecord): OntologyCaseEventDto {
  return {
    event_id: Number(record.event_id),
    action: record.action,
    actor: record.actor,
    note: record.note,
    payload_json: JSON.parse(record.payload_json || '{}'),
    created_at: toIso(record.created_at)
  };
}

function mapOntologyCaseDecision(record: any): OntologyCaseDecisionDto {
  return {
    case_decision_id: Number(record.case_decision_id),
    case_id: Number(record.case_id),
    decision_kind: String(record.decision_kind ?? ''),
    verdict: String(record.verdict ?? ''),
    summary: String(record.summary ?? ''),
    rationale: String(record.rationale ?? ''),
    as_of_system_time: toIso(String(record.as_of_system_time ?? '')),
    as_of_effective_time: toIso(String(record.as_of_effective_time ?? '')),
    snapshot_id: String(record.snapshot_id ?? ''),
    source_evidence_json: JSON.parse(String(record.source_evidence_json || '[]')),
    supersedes_case_decision_id: record.supersedes_case_decision_id
      ? Number(record.supersedes_case_decision_id)
      : undefined,
    created_by: String(record.created_by ?? ''),
    created_at: toIso(String(record.created_at ?? ''))
  };
}

function mapOntologyAlert(record: OntologyAlertRecord | OntologyAlertDetailRecord): OntologyAlertDto {
  return {
    alert_id: Number((record as any).alert_id),
    case_id: (record as any).case_id ? Number((record as any).case_id) : undefined,
    stream_id: (record as any).stream_id,
    severity: (record as any).severity as OntologyAlertDto['severity'],
    status: (record as any).status as OntologyAlertDto['status'],
    message: (record as any).message,
    detail_json: JSON.parse((record as any).detail_json || '{}'),
    rule_key: (record as any).rule_key ?? undefined,
    trigger_count: (record as any).trigger_count,
    first_triggered_at: toIso((record as any).first_triggered_at),
    last_triggered_at: toIso((record as any).last_triggered_at),
    acked_by: (record as any).acked_by ?? undefined,
    acked_at: (record as any).acked_at ? toIso((record as any).acked_at) : undefined,
    closed_at: (record as any).closed_at ? toIso((record as any).closed_at) : undefined,
    created_at: toIso((record as any).created_at),
    updated_at: toIso((record as any).updated_at)
  };
}

function mapOntologyAlertSummary(record: OntologyAlertSummaryRecord): OntologyAlertSummaryDto {
  return {
    ...mapOntologyAlert(record),
    case_title: record.case_title ?? undefined,
    linked_fact_count: Number(record.linked_fact_count ?? 0)
  };
}

function mapOntologyAlertWithFactIds(record: OntologyAlertSummaryRecord | OntologyAlertDetailRecord): OntologyAlertDto & { linked_fact_ids: number[] } {
  return {
    ...mapOntologyAlert(record),
    linked_fact_ids: 'linked_fact_ids' in record ? normalizeNumberArray((record as any).linked_fact_ids) : []
  };
}

function mapOntologyOpsRuleConfig(record: OntologyOpsRuleConfigRecord): OntologyOpsRuleConfigDto {
  return {
    config_id: Number(record.config_id),
    stream_id: record.stream_id ?? undefined,
    rule_name: record.rule_name as OntologyOpsRuleConfigDto['rule_name'],
    enabled: record.enabled ?? false,
    stale_days: record.stale_days ? Number(record.stale_days) : undefined,
    conflict_predicate: record.conflict_predicate ?? undefined,
    severity: (record.severity ?? undefined) as OntologyOpsRuleConfigDto['severity'],
    note: record.note ?? '',
    updated_by: record.updated_by ?? '',
    updated_at: toIso(record.updated_at)
  };
}

function mapOntologyOpsRuleRun(record: OntologyOpsRuleRunRecord): OntologyOpsRuleRunDto {
  return {
    run_id: Number(record.run_id),
    stream_id_filter: record.stream_id_filter ?? undefined,
    stale_days: Number(record.stale_days),
    conflict_predicate: record.conflict_predicate,
    dry_run: record.dry_run,
    candidate_count: Number(record.candidate_count),
    created_case_count: Number(record.created_case_count),
    existing_case_count: Number(record.existing_case_count),
    created_alert_count: Number(record.created_alert_count),
    existing_alert_count: Number(record.existing_alert_count),
    duration_ms: Number(record.duration_ms),
    started_at: toIso(record.started_at),
    finished_at: toIso(record.finished_at)
  };
}

function mapOntologyOpsRuleRunPayload(record: Record<string, any>): OntologyOpsRuleRunResultDto {
  const rulesEnabled = (record.rules_enabled ?? {}) as Record<string, unknown>;
  const ruleSeverity = (record.rule_severity ?? {}) as Record<string, unknown>;
  return {
    stream_id_filter: record.stream_id_filter ? String(record.stream_id_filter) : undefined,
    stale_days: Number(record.stale_days ?? 0),
    conflict_predicate: String(record.conflict_predicate ?? ''),
    rules_enabled: {
      stale_pending: Boolean(rulesEnabled.stale_pending),
      conflict_predicate: Boolean(rulesEnabled.conflict_predicate)
    },
    rule_severity: {
      stale_pending: normalizeSeverity(
        typeof ruleSeverity.stale_pending === 'string' ? ruleSeverity.stale_pending : undefined,
        'medium'
      ),
      conflict_predicate: normalizeSeverity(
        typeof ruleSeverity.conflict_predicate === 'string' ? ruleSeverity.conflict_predicate : undefined,
        'high'
      )
    },
    dry_run: Boolean(record.dry_run),
    candidate_count: Number(record.candidate_count ?? 0),
    candidates: normalizeJsonObjectArray(record.candidates),
    created_cases: normalizeJsonObjectArray(record.created_cases),
    existing_cases: normalizeJsonObjectArray(record.existing_cases),
    created_alerts: normalizeJsonObjectArray(record.created_alerts),
    existing_alerts: normalizeJsonObjectArray(record.existing_alerts)
  };
}

function safeParseJson<T>(raw: string | undefined, fallback: T): T {
  if (!raw || raw.trim() === '') {
    return fallback;
  }
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function asNonNegativeInteger(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isInteger(parsed) && parsed >= 0) {
      return parsed;
    }
  }
  return undefined;
}

function combineEventSentences(
  sentences: EventSentenceRecord[]
): { sent_index: number; start_char?: number; end_char?: number; sentence_text: string } | undefined {
  if (sentences.length === 0) {
    return undefined;
  }
  const ordered = [...sentences].sort((a, b) => a.sent_index - b.sent_index);
  const text = ordered
    .map((item) => item.sentence_text.trim())
    .filter(Boolean)
    .join(' ')
    .trim();
  if (!text) {
    return undefined;
  }
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  return {
    sent_index: first.sent_index,
    start_char: first.start_char >= 0 ? first.start_char : undefined,
    end_char: last.end_char >= 0 ? last.end_char : undefined,
    sentence_text: text
  };
}

function selectRelevantEventSentenceWindow(
  sentences: EventSentenceRecord[],
  srcLabel?: string,
  dstLabel?: string
): { sent_index: number; start_char?: number; end_char?: number; sentence_text: string } | undefined {
  if (sentences.length === 0) {
    return undefined;
  }
  const ordered = [...sentences].sort((a, b) => a.sent_index - b.sent_index);
  const src = (srcLabel ?? '').trim();
  const dst = (dstLabel ?? '').trim();

  if (src || dst) {
    for (const sentence of ordered) {
      const text = sentence.sentence_text.trim();
      if (!text) {
        continue;
      }
      const hasSrc = !src || text.includes(src);
      const hasDst = !dst || text.includes(dst);
      if (hasSrc && hasDst) {
        return {
          sent_index: sentence.sent_index,
          start_char: sentence.start_char >= 0 ? sentence.start_char : undefined,
          end_char: sentence.end_char >= 0 ? sentence.end_char : undefined,
          sentence_text: text
        };
      }
    }

    for (let i = 0; i < ordered.length - 1; i += 1) {
      const first = ordered[i];
      const second = ordered[i + 1];
      const joined = `${first.sentence_text.trim()} ${second.sentence_text.trim()}`.trim();
      if (!joined) {
        continue;
      }
      const hasSrc = !src || joined.includes(src);
      const hasDst = !dst || joined.includes(dst);
      if (hasSrc && hasDst) {
        return {
          sent_index: first.sent_index,
          start_char: first.start_char >= 0 ? first.start_char : undefined,
          end_char: second.end_char >= 0 ? second.end_char : undefined,
          sentence_text: joined
        };
      }
    }

    if (src) {
      for (const sentence of ordered) {
        const text = sentence.sentence_text.trim();
        if (!text || !text.includes(src)) {
          continue;
        }
        return {
          sent_index: sentence.sent_index,
          start_char: sentence.start_char >= 0 ? sentence.start_char : undefined,
          end_char: sentence.end_char >= 0 ? sentence.end_char : undefined,
          sentence_text: text
        };
      }
    }

    if (dst) {
      for (const sentence of ordered) {
        const text = sentence.sentence_text.trim();
        if (!text || !text.includes(dst)) {
          continue;
        }
        return {
          sent_index: sentence.sent_index,
          start_char: sentence.start_char >= 0 ? sentence.start_char : undefined,
          end_char: sentence.end_char >= 0 ? sentence.end_char : undefined,
          sentence_text: text
        };
      }
    }
  }

  return combineEventSentences(ordered);
}

function normalizeJsonObjectArray(raw: unknown): Record<string, unknown>[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((value) => ((value ?? {}) as Record<string, unknown>));
}

function buildConflictDraftKey(candidate: {
  stream_id: string;
  src_concept_id: string;
  predicate: string;
  dst_values: string[];
}): string {
  return [
    candidate.stream_id,
    candidate.src_concept_id,
    candidate.predicate,
    [...candidate.dst_values].map(String).sort().join(',')
  ].join('|');
}

function parseDecisionEvidenceJson(input: string): Record<string, unknown>[] {
  if (!input.trim()) {
    return [];
  }
  try {
    const parsed = JSON.parse(input);
    return Array.isArray(parsed) ? parsed.map((value) => ((value ?? {}) as Record<string, unknown>)) : [];
  } catch {
    return [];
  }
}

function mapEvidenceSample(
  raw: unknown
): Array<{
  stream_id: string;
  event_id: string;
  session_id: string;
  updated_at: string;
  source_span?: string;
  text_snippet: string;
}> {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw.map((item) => {
    const record = (item ?? {}) as Record<string, unknown>;
    return {
      stream_id: String(record.stream_id ?? ''),
      event_id: String(record.event_id ?? ''),
      session_id: String(record.session_id ?? ''),
      updated_at: toIso(String(record.updated_at ?? nowIso())),
      source_span: record.source_span ? String(record.source_span) : undefined,
      text_snippet: String(record.text_snippet ?? '')
    };
  });
}

function normalizeNumberArray(raw: unknown): number[] {
  if (!Array.isArray(raw)) {
    return [];
  }
  return raw
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value > 0);
}

function normalizeSeverity(
  severity: string | undefined,
  fallback: OntologyAlertDto['severity']
): OntologyAlertDto['severity'] {
  switch (severity) {
    case 'low':
    case 'medium':
    case 'high':
    case 'critical':
      return severity;
    default:
      return fallback;
  }
}

function maxSeverity(
  current: string,
  next: OntologyAlertDto['severity']
): OntologyAlertDto['severity'] {
  const rank: Record<OntologyAlertDto['severity'], number> = {
    low: 1,
    medium: 2,
    high: 3,
    critical: 4
  };
  const currentSeverity = normalizeSeverity(current, 'low');
  return rank[next] >= rank[currentSeverity] ? next : currentSeverity;
}
