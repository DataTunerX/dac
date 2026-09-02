import type { Static } from '@sinclair/typebox';

import type {
  AssertionEvidenceLinkRecord,
  AssertionRecord,
  AssertionRelationRecord,
  GatewayBackendClient
} from '../clients/gateway_backend.types.js';
import {
  AssertionEvidenceLinkListQuerySchema,
  AssertionEvidenceLinkUpsertRequestSchema,
  AssertionGetQuerySchema,
  AssertionRelationListQuerySchema,
  AssertionRelationUpsertRequestSchema,
  AssertionSearchQuerySchema,
  AssertionUpsertRequestSchema
} from '../schema/v2/assertion.js';

export type AssertionUpsertRequest = Static<typeof AssertionUpsertRequestSchema>;
export type AssertionGetQuery = Static<typeof AssertionGetQuerySchema>;
export type AssertionSearchQuery = Static<typeof AssertionSearchQuerySchema>;
export type AssertionEvidenceLinkUpsertRequest = Static<typeof AssertionEvidenceLinkUpsertRequestSchema>;
export type AssertionEvidenceLinkListQuery = Static<typeof AssertionEvidenceLinkListQuerySchema>;
export type AssertionRelationUpsertRequest = Static<typeof AssertionRelationUpsertRequestSchema>;
export type AssertionRelationListQuery = Static<typeof AssertionRelationListQuerySchema>;

export type AssertionDto = {
  assertion_id: string;
  case_id?: string;
  subject_type: string;
  subject_id: string;
  predicate: string;
  object_type: string;
  object_id?: string;
  object_literal?: Record<string, unknown>;
  assertion_type: string;
  asserted_by_type: string;
  asserted_by_id?: string;
  confidence: number;
  status: string;
  methodology_framework_id?: string;
  source_event_id?: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AssertionEvidenceLinkDto = {
  assertion_evidence_link_id: string;
  assertion_id: string;
  evidence_id?: string;
  artifact_version_id?: string;
  event_id?: string;
  memory_decision_id?: string;
  support_type: string;
  weight: number;
  note: string;
  evidence: Record<string, unknown>;
  created_at: string;
};

export type AssertionRelationDto = {
  assertion_relation_id: string;
  from_assertion_id: string;
  to_assertion_id: string;
  relation_type: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export class AssertionService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async upsertAssertion(request: AssertionUpsertRequest): Promise<AssertionDto> {
    const record = await this.backend.upsertAssertion({
      assertion_id: request.assertion_id ?? '',
      case_id: request.case_id ?? '',
      subject_type: request.subject_type,
      subject_id: request.subject_id,
      predicate: request.predicate,
      object_type: request.object_type,
      object_id: request.object_id ?? '',
      object_literal_json: JSON.stringify(request.object_literal ?? {}),
      assertion_type: request.assertion_type,
      asserted_by_type: request.asserted_by_type,
      asserted_by_id: request.asserted_by_id ?? '',
      confidence: request.confidence ?? -1,
      status: request.status ?? 'active',
      methodology_framework_id: request.methodology_framework_id ?? '',
      source_event_id: request.source_event_id ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapAssertion(record);
  }

  async getAssertion(query: AssertionGetQuery): Promise<AssertionDto | undefined> {
    const record = await this.backend.getAssertion({ assertion_id: query.assertion_id });
    return record ? mapAssertion(record) : undefined;
  }

  async searchAssertions(query: AssertionSearchQuery): Promise<AssertionDto[]> {
    const records = await this.backend.searchAssertions({
      case_id: query.case_id,
      subject_type: query.subject_type,
      subject_id: query.subject_id,
      predicate: query.predicate,
      assertion_type: query.assertion_type,
      status: query.status,
      methodology_framework_id: query.methodology_framework_id,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapAssertion);
  }

  async upsertAssertionEvidenceLink(
    request: AssertionEvidenceLinkUpsertRequest
  ): Promise<AssertionEvidenceLinkDto> {
    const record = await this.backend.upsertAssertionEvidenceLink({
      assertion_evidence_link_id: request.assertion_evidence_link_id ?? '',
      assertion_id: request.assertion_id,
      evidence_id: request.evidence_id ?? '',
      artifact_version_id: request.artifact_version_id ?? '',
      event_id: request.event_id ?? '',
      memory_decision_id: request.memory_decision_id ?? '',
      support_type: request.support_type ?? 'supports',
      weight: request.weight ?? -1,
      note: request.note ?? '',
      evidence_json: JSON.stringify(request.evidence ?? {})
    });
    return mapAssertionEvidenceLink(record);
  }

  async listAssertionEvidenceLinks(
    query: AssertionEvidenceLinkListQuery
  ): Promise<AssertionEvidenceLinkDto[]> {
    const records = await this.backend.listAssertionEvidenceLinks({
      assertion_id: query.assertion_id,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapAssertionEvidenceLink);
  }

  async upsertAssertionRelation(
    request: AssertionRelationUpsertRequest
  ): Promise<AssertionRelationDto> {
    const record = await this.backend.upsertAssertionRelation({
      assertion_relation_id: request.assertion_relation_id ?? '',
      from_assertion_id: request.from_assertion_id,
      to_assertion_id: request.to_assertion_id,
      relation_type: request.relation_type,
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapAssertionRelation(record);
  }

  async listAssertionRelations(query: AssertionRelationListQuery): Promise<AssertionRelationDto[]> {
    const records = await this.backend.listAssertionRelations({
      assertion_id: query.assertion_id,
      direction: query.direction ?? 'both',
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapAssertionRelation);
  }
}

function mapAssertion(record: AssertionRecord): AssertionDto {
  return {
    assertion_id: record.assertion_id,
    case_id: record.case_id || undefined,
    subject_type: record.subject_type,
    subject_id: record.subject_id,
    predicate: record.predicate,
    object_type: record.object_type,
    object_id: record.object_id || undefined,
    object_literal: record.object_literal_json ? JSON.parse(record.object_literal_json) : undefined,
    assertion_type: record.assertion_type,
    asserted_by_type: record.asserted_by_type,
    asserted_by_id: record.asserted_by_id || undefined,
    confidence: record.confidence,
    status: record.status,
    methodology_framework_id: record.methodology_framework_id || undefined,
    source_event_id: record.source_event_id || undefined,
    metadata: record.metadata_json ? JSON.parse(record.metadata_json) : {},
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapAssertionEvidenceLink(record: AssertionEvidenceLinkRecord): AssertionEvidenceLinkDto {
  return {
    assertion_evidence_link_id: record.assertion_evidence_link_id,
    assertion_id: record.assertion_id,
    evidence_id: record.evidence_id || undefined,
    artifact_version_id: record.artifact_version_id || undefined,
    event_id: record.event_id || undefined,
    memory_decision_id: record.memory_decision_id || undefined,
    support_type: record.support_type,
    weight: record.weight,
    note: record.note,
    evidence: record.evidence_json ? JSON.parse(record.evidence_json) : {},
    created_at: record.created_at
  };
}

function mapAssertionRelation(record: AssertionRelationRecord): AssertionRelationDto {
  return {
    assertion_relation_id: record.assertion_relation_id,
    from_assertion_id: record.from_assertion_id,
    to_assertion_id: record.to_assertion_id,
    relation_type: record.relation_type,
    metadata: record.metadata_json ? JSON.parse(record.metadata_json) : {},
    created_at: record.created_at
  };
}
