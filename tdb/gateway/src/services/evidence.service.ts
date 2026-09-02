import type { Static } from '@sinclair/typebox';

import type {
  EvidenceClassificationRecord,
  EvidenceDerivationRecord,
  EvidenceLocatorRecord,
  EvidenceRecord,
  GatewayBackendClient,
  SemanticStatementReferenceRecord,
  EvidenceLocatorRecord as SemanticEvidenceLocatorRecord,
  EvidenceRecord as SemanticEvidenceRecord
} from '../clients/gateway_backend.types.js';
import {
  EvidenceClassificationGetQuerySchema,
  EvidenceClassificationUpsertRequestSchema,
  EvidenceDerivationListQuerySchema,
  EvidenceDerivationUpsertRequestSchema,
  EvidenceGetQuerySchema,
  EvidenceLocatorListQuerySchema,
  EvidenceLocatorUpsertRequestSchema,
  EvidenceStatementsQuerySchema,
  EvidenceSearchQuerySchema,
  EvidenceUpsertRequestSchema
} from '../schema/v2/evidence.js';

export type EvidenceUpsertRequest = Static<typeof EvidenceUpsertRequestSchema>;
export type EvidenceGetQuery = Static<typeof EvidenceGetQuerySchema>;
export type EvidenceSearchQuery = Static<typeof EvidenceSearchQuerySchema>;
export type EvidenceLocatorUpsertRequest = Static<typeof EvidenceLocatorUpsertRequestSchema>;
export type EvidenceLocatorListQuery = Static<typeof EvidenceLocatorListQuerySchema>;
export type EvidenceDerivationUpsertRequest = Static<typeof EvidenceDerivationUpsertRequestSchema>;
export type EvidenceDerivationListQuery = Static<typeof EvidenceDerivationListQuerySchema>;
export type EvidenceClassificationUpsertRequest = Static<typeof EvidenceClassificationUpsertRequestSchema>;
export type EvidenceClassificationGetQuery = Static<typeof EvidenceClassificationGetQuerySchema>;
export type EvidenceStatementsQuery = Static<typeof EvidenceStatementsQuerySchema>;

export type EvidenceDto = {
  evidence_id: string;
  case_id?: string;
  event_seq?: number;
  source_kind: string;
  source_id: string;
  artifact_version_id?: string;
  evidence_type: string;
  evidence_role: string;
  methodology_framework_id?: string;
  evidence_payload: Record<string, unknown>;
  created_by_type: string;
  created_by_id: string;
  is_derived: boolean;
  status: string;
  created_at: string;
  updated_at: string;
};

export type EvidenceLocatorDto = {
  evidence_locator_id: string;
  evidence_id: string;
  locator_type: string;
  page_span?: string;
  char_span?: string;
  sentence_ref: Record<string, unknown>;
  bbox: Record<string, unknown>;
  polygon: Record<string, unknown>;
  time_range?: string;
  table_cell: Record<string, unknown>;
  measurement_field?: string;
  locator_payload: Record<string, unknown>;
  normalized_text?: string;
  preview_text?: string;
  created_at: string;
};

export type EvidenceDerivationDto = {
  evidence_derivation_id: string;
  child_evidence_id: string;
  parent_evidence_id: string;
  derivation_type: string;
  method: string;
  run_id: string;
  artifact_version_id?: string;
  derivation_metadata: Record<string, unknown>;
  created_at: string;
};

export type EvidenceClassificationDto = {
  evidence_id: string;
  source_reliability_tier: string;
  evidence_strength_tier: string;
  evidence_modality: string;
  institutional_trust_class: string;
  is_primary_source: boolean;
  is_machine_generated: boolean;
  requires_human_validation: boolean;
  methodology_framework_id?: string;
  classification_status: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type EvidenceStatementReferenceDto = {
  statement_id: string;
  property_id: string;
  value_type: string;
  value: unknown;
  evidence_id?: string;
  source_span?: string;
  ordinal: number;
  evidence?: EvidenceDto;
  locators: EvidenceLocatorDto[];
};

export class EvidenceService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async upsertEvidence(request: EvidenceUpsertRequest): Promise<EvidenceDto> {
    const record = await this.backend.upsertEvidence({
      evidence_id: request.evidence_id ?? '',
      case_id: request.case_id ?? '',
      event_seq: request.event_seq ?? 0,
      source_kind: request.source_kind,
      source_id: request.source_id,
      artifact_version_id: request.artifact_version_id ?? '',
      evidence_type: request.evidence_type,
      evidence_role: request.evidence_role ?? 'primary',
      methodology_framework_id: request.methodology_framework_id ?? '',
      evidence_payload_json: JSON.stringify(request.evidence_payload ?? {}),
      created_by_type: request.created_by_type,
      created_by_id: request.created_by_id ?? '',
      is_derived: request.is_derived ?? false,
      status: request.status ?? 'active'
    });
    if (!record) {
      throw new Error('upsertEvidence returned empty record');
    }
    return mapEvidence(record);
  }

  async getEvidence(query: EvidenceGetQuery): Promise<EvidenceDto | undefined> {
    const record = await this.backend.getEvidence({ evidence_id: query.evidence_id });
    return record ? mapEvidence(record) : undefined;
  }

  async searchEvidence(query: EvidenceSearchQuery): Promise<EvidenceDto[]> {
    const records = await this.backend.searchEvidence({
      case_id: query.case_id ?? '',
      source_kind: query.source_kind ?? '',
      evidence_type: query.evidence_type ?? '',
      evidence_role: query.evidence_role ?? '',
      status: query.status ?? '',
      methodology_framework_id: query.methodology_framework_id ?? '',
      query: query.q ?? '',
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapEvidence);
  }

  async upsertEvidenceLocator(request: EvidenceLocatorUpsertRequest): Promise<EvidenceLocatorDto> {
    const record = await this.backend.upsertEvidenceLocator({
      evidence_locator_id: request.evidence_locator_id ?? '',
      evidence_id: request.evidence_id,
      locator_type: request.locator_type,
      page_span: request.page_span ?? '',
      char_span: request.char_span ?? '',
      sentence_ref_json: JSON.stringify(request.sentence_ref ?? {}),
      bbox_json: JSON.stringify(request.bbox ?? {}),
      polygon_json: JSON.stringify(request.polygon ?? {}),
      time_range: request.time_range ?? '',
      table_cell_json: JSON.stringify(request.table_cell ?? {}),
      measurement_field: request.measurement_field ?? '',
      locator_payload_json: JSON.stringify(request.locator_payload ?? {}),
      normalized_text: request.normalized_text ?? '',
      preview_text: request.preview_text ?? ''
    });
    return mapEvidenceLocator(record);
  }

  async listEvidenceLocators(query: EvidenceLocatorListQuery): Promise<EvidenceLocatorDto[]> {
    const records = await this.backend.listEvidenceLocators({
      evidence_id: query.evidence_id,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapEvidenceLocator);
  }

  async upsertEvidenceDerivation(
    request: EvidenceDerivationUpsertRequest
  ): Promise<EvidenceDerivationDto> {
    const record = await this.backend.upsertEvidenceDerivation({
      evidence_derivation_id: request.evidence_derivation_id ?? '',
      child_evidence_id: request.child_evidence_id,
      parent_evidence_id: request.parent_evidence_id,
      derivation_type: request.derivation_type,
      method: request.method ?? '',
      run_id: request.run_id ?? '',
      artifact_version_id: request.artifact_version_id ?? '',
      derivation_metadata_json: JSON.stringify(request.derivation_metadata ?? {})
    });
    return mapEvidenceDerivation(record);
  }

  async listEvidenceDerivations(
    query: EvidenceDerivationListQuery
  ): Promise<EvidenceDerivationDto[]> {
    const records = await this.backend.listEvidenceDerivations({
      evidence_id: query.evidence_id,
      direction: query.direction ?? 'both',
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapEvidenceDerivation);
  }

  async upsertEvidenceClassification(
    request: EvidenceClassificationUpsertRequest
  ): Promise<EvidenceClassificationDto> {
    const record = await this.backend.upsertEvidenceClassification({
      evidence_id: request.evidence_id,
      source_reliability_tier: request.source_reliability_tier ?? '',
      evidence_strength_tier: request.evidence_strength_tier ?? '',
      evidence_modality: request.evidence_modality ?? '',
      institutional_trust_class: request.institutional_trust_class ?? '',
      is_primary_source: request.is_primary_source ?? false,
      is_machine_generated: request.is_machine_generated ?? false,
      requires_human_validation: request.requires_human_validation ?? false,
      methodology_framework_id: request.methodology_framework_id ?? '',
      classification_status: request.classification_status ?? 'draft',
      metadata_json: JSON.stringify(request.metadata ?? {})
    });
    return mapEvidenceClassification(record);
  }

  async getEvidenceClassification(
    query: EvidenceClassificationGetQuery
  ): Promise<EvidenceClassificationDto | undefined> {
    const record = await this.backend.getEvidenceClassification({ evidence_id: query.evidence_id });
    return record ? mapEvidenceClassification(record) : undefined;
  }

  async getEvidenceStatements(
    query: EvidenceStatementsQuery
  ): Promise<EvidenceStatementReferenceDto[]> {
    const response = await this.backend.getSemanticStatementsByEvidence({
      evidence_id: query.evidence_id,
      include_locators: query.include_locators ?? true,
      limit: query.limit ?? 50
    });
    return response.references.map(mapStatementReference);
  }
}

function mapEvidence(record: EvidenceRecord): EvidenceDto {
  return {
    evidence_id: record.evidence_id,
    case_id: record.case_id || undefined,
    event_seq: record.event_seq > 0 ? record.event_seq : undefined,
    source_kind: record.source_kind,
    source_id: record.source_id,
    artifact_version_id: record.artifact_version_id || undefined,
    evidence_type: record.evidence_type,
    evidence_role: record.evidence_role,
    methodology_framework_id: record.methodology_framework_id || undefined,
    evidence_payload: record.evidence_payload_json ? JSON.parse(record.evidence_payload_json) : {},
    created_by_type: record.created_by_type,
    created_by_id: record.created_by_id,
    is_derived: record.is_derived,
    status: record.status,
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapEvidenceLocator(record: EvidenceLocatorRecord): EvidenceLocatorDto {
  return {
    evidence_locator_id: record.evidence_locator_id,
    evidence_id: record.evidence_id,
    locator_type: record.locator_type,
    page_span: record.page_span || undefined,
    char_span: record.char_span || undefined,
    sentence_ref: record.sentence_ref_json ? JSON.parse(record.sentence_ref_json) : {},
    bbox: record.bbox_json ? JSON.parse(record.bbox_json) : {},
    polygon: record.polygon_json ? JSON.parse(record.polygon_json) : {},
    time_range: record.time_range || undefined,
    table_cell: record.table_cell_json ? JSON.parse(record.table_cell_json) : {},
    measurement_field: record.measurement_field || undefined,
    locator_payload: record.locator_payload_json ? JSON.parse(record.locator_payload_json) : {},
    normalized_text: record.normalized_text || undefined,
    preview_text: record.preview_text || undefined,
    created_at: record.created_at
  };
}

function mapEvidenceDerivation(record: EvidenceDerivationRecord): EvidenceDerivationDto {
  return {
    evidence_derivation_id: record.evidence_derivation_id,
    child_evidence_id: record.child_evidence_id,
    parent_evidence_id: record.parent_evidence_id,
    derivation_type: record.derivation_type,
    method: record.method,
    run_id: record.run_id,
    artifact_version_id: record.artifact_version_id || undefined,
    derivation_metadata: record.derivation_metadata_json
      ? JSON.parse(record.derivation_metadata_json)
      : {},
    created_at: record.created_at
  };
}

function mapEvidenceClassification(
  record: EvidenceClassificationRecord
): EvidenceClassificationDto {
  return {
    evidence_id: record.evidence_id,
    source_reliability_tier: record.source_reliability_tier,
    evidence_strength_tier: record.evidence_strength_tier,
    evidence_modality: record.evidence_modality,
    institutional_trust_class: record.institutional_trust_class,
    is_primary_source: record.is_primary_source,
    is_machine_generated: record.is_machine_generated,
    requires_human_validation: record.requires_human_validation,
    methodology_framework_id: record.methodology_framework_id || undefined,
    classification_status: record.classification_status,
    metadata: record.metadata_json ? JSON.parse(record.metadata_json) : {},
    created_at: record.created_at,
    updated_at: record.updated_at
  };
}

function mapStatementReference(
  record: SemanticStatementReferenceRecord
): EvidenceStatementReferenceDto {
  return {
    statement_id: record.statement_id,
    property_id: record.property_id,
    value_type: record.value_type,
    value: record.value_json ? JSON.parse(record.value_json) : {},
    evidence_id: record.evidence_id || undefined,
    source_span: record.source_span || undefined,
    ordinal: record.ordinal,
    evidence: record.evidence ? mapSemanticReferenceEvidence(record.evidence) : undefined,
    locators: (record.locators ?? []).map(mapSemanticReferenceLocator)
  };
}

function mapSemanticReferenceEvidence(record: SemanticEvidenceRecord): EvidenceDto {
  return mapEvidence(record);
}

function mapSemanticReferenceLocator(record: SemanticEvidenceLocatorRecord): EvidenceLocatorDto {
  return mapEvidenceLocator(record);
}
