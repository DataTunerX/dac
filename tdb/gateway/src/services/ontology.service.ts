import type { Static } from '@sinclair/typebox';

import type {
  ConceptAliasRecord,
  EventConceptLinkRecord,
  GatewayBackendClient,
  OntologyConceptRecord,
  OntologyClusterMemberRecord,
  OntologyConceptTypeAssignmentRecord,
  OntologyEdgeRecord,
  OntologyFactRecord,
  OntologyNeighborRecord,
  SemanticStatementQualifierRecord,
  SemanticStatementRecord,
  SemanticStatementReferenceRecord,
  EvidenceRecord,
  EvidenceLocatorRecord,
  OntologyNormalizedTermRecord,
  OntologyObjectTypeRecord,
  OntologyRelationCandidateRecord,
  OntologyRawTermCandidateRecord,
  OntologyRawTermNormalizationRecord,
  OntologyRawTermRecord,
  OntologyRelationTypeRecord,
  OntologyTermClusterRecord,
  TermMappingInterpretationRecord,
  TermMappingRegistryRecord,
  TermMappingRuleEvidenceRecord,
  TermMappingRuleRecord
} from '../clients/gateway_backend.types.js';
import {
  ConceptAliasSearchQuerySchema,
  ConceptAliasListQuerySchema,
  ConceptAliasUpsertRequestSchema,
  EventConceptLinkListQuerySchema,
  EventConceptLinkUpsertRequestSchema,
  OntologyConceptGetQuerySchema,
  OntologyConceptListQuerySchema,
  OntologyConceptNeighborsQuerySchema,
  OntologyConceptSearchQuerySchema,
  OntologyConceptTypeAssignmentListQuerySchema,
  OntologyConceptTypeAssignmentUpsertRequestSchema,
  OntologyConceptUpsertRequestSchema,
  OntologyEdgeListQuerySchema,
  OntologyEdgeUpsertRequestSchema,
  OntologyFactArchiveRequestSchema,
  OntologyFactListQuerySchema,
  OntologyFactSearchQuerySchema,
  OntologyFactUpsertWithEvidenceRequestSchema,
  SemanticStatementGetQuerySchema,
  SemanticStatementListQuerySchema,
  SemanticStatementStatusRequestSchema,
  SemanticStatementProvenanceQuerySchema,
  SemanticBatchUpsertRequestSchema,
  OntologyObjectTypeGetQuerySchema,
  OntologyObjectTypeListQuerySchema,
  OntologyObjectTypeUpsertRequestSchema,
  OntologyClusterMemberListQuerySchema,
  OntologyClusterMemberUpsertRequestSchema,
  OntologyNormalizedTermGetQuerySchema,
  OntologyNormalizedTermSearchQuerySchema,
  OntologyNormalizedTermUpsertRequestSchema,
  OntologyRawTermCandidateListQuerySchema,
  OntologyRawTermCandidateUpsertRequestSchema,
  OntologyRawTermGetQuerySchema,
  OntologyRelationCandidateListQuerySchema,
  OntologyRelationCandidateUpsertRequestSchema,
  OntologyRawTermNormalizationListQuerySchema,
  OntologyRawTermNormalizationUpsertRequestSchema,
  OntologyRawTermSearchQuerySchema,
  OntologyRawTermUpsertRequestSchema,
  OntologyRelationTypeGetQuerySchema,
  OntologyRelationTypeListQuerySchema,
  OntologyRelationTypeUpsertRequestSchema,
  OntologyTermClusterGetQuerySchema,
  OntologyTermClusterListQuerySchema,
  OntologyTermClusterUpsertRequestSchema,
  TermMappingInterpretBatchRequestSchema,
  TermMappingInterpretQuerySchema,
  TermMappingRegistryGetQuerySchema,
  TermMappingRegistryListQuerySchema,
  TermMappingRegistryUpsertRequestSchema,
  TermMappingRuleEvidenceListQuerySchema,
  TermMappingRuleEvidenceUpsertRequestSchema,
  TermMappingRuleGetQuerySchema,
  TermMappingRuleSearchQuerySchema,
  TermMappingRuleUpsertRequestSchema
} from '../schema/v2/ontology.js';

export type OntologyConceptUpsertRequest = Static<typeof OntologyConceptUpsertRequestSchema>;
export type OntologyConceptGetQuery = Static<typeof OntologyConceptGetQuerySchema>;
export type OntologyConceptListQuery = Static<typeof OntologyConceptListQuerySchema>;
export type OntologyConceptSearchQuery = Static<typeof OntologyConceptSearchQuerySchema>;
export type OntologyConceptTypeAssignmentUpsertRequest = Static<typeof OntologyConceptTypeAssignmentUpsertRequestSchema>;
export type OntologyConceptTypeAssignmentListQuery = Static<typeof OntologyConceptTypeAssignmentListQuerySchema>;
export type ConceptAliasUpsertRequest = Static<typeof ConceptAliasUpsertRequestSchema>;
export type ConceptAliasListQuery = Static<typeof ConceptAliasListQuerySchema>;
export type ConceptAliasSearchQuery = Static<typeof ConceptAliasSearchQuerySchema>;
export type OntologyEdgeUpsertRequest = Static<typeof OntologyEdgeUpsertRequestSchema>;
export type OntologyEdgeListQuery = Static<typeof OntologyEdgeListQuerySchema>;
export type EventConceptLinkUpsertRequest = Static<typeof EventConceptLinkUpsertRequestSchema>;
export type EventConceptLinkListQuery = Static<typeof EventConceptLinkListQuerySchema>;
export type OntologyObjectTypeUpsertRequest = Static<typeof OntologyObjectTypeUpsertRequestSchema>;
export type OntologyObjectTypeGetQuery = Static<typeof OntologyObjectTypeGetQuerySchema>;
export type OntologyObjectTypeListQuery = Static<typeof OntologyObjectTypeListQuerySchema>;
export type OntologyRelationTypeUpsertRequest = Static<typeof OntologyRelationTypeUpsertRequestSchema>;
export type OntologyRelationTypeGetQuery = Static<typeof OntologyRelationTypeGetQuerySchema>;
export type OntologyRelationTypeListQuery = Static<typeof OntologyRelationTypeListQuerySchema>;
export type OntologyFactListQuery = Static<typeof OntologyFactListQuerySchema>;
export type OntologyFactUpsertWithEvidenceRequest = Static<typeof OntologyFactUpsertWithEvidenceRequestSchema>;
export type SemanticBatchUpsertRequest = Static<typeof SemanticBatchUpsertRequestSchema>;
export type OntologyFactSearchQuery = Static<typeof OntologyFactSearchQuerySchema>;
export type SemanticStatementGetQuery = Static<typeof SemanticStatementGetQuerySchema>;
export type SemanticStatementListQuery = Static<typeof SemanticStatementListQuerySchema>;
export type SemanticStatementStatusRequest = Static<typeof SemanticStatementStatusRequestSchema>;
export type SemanticStatementProvenanceQuery = Static<typeof SemanticStatementProvenanceQuerySchema>;
export type OntologyConceptNeighborsQuery = Static<typeof OntologyConceptNeighborsQuerySchema>;
export type OntologyFactArchiveRequest = Static<typeof OntologyFactArchiveRequestSchema>;
export type TermMappingRegistryUpsertRequest = Static<typeof TermMappingRegistryUpsertRequestSchema>;
export type TermMappingRegistryGetQuery = Static<typeof TermMappingRegistryGetQuerySchema>;
export type TermMappingRegistryListQuery = Static<typeof TermMappingRegistryListQuerySchema>;
export type OntologyNormalizedTermUpsertRequest = Static<typeof OntologyNormalizedTermUpsertRequestSchema>;
export type OntologyNormalizedTermGetQuery = Static<typeof OntologyNormalizedTermGetQuerySchema>;
export type OntologyNormalizedTermSearchQuery = Static<typeof OntologyNormalizedTermSearchQuerySchema>;
export type OntologyTermClusterUpsertRequest = Static<typeof OntologyTermClusterUpsertRequestSchema>;
export type OntologyTermClusterGetQuery = Static<typeof OntologyTermClusterGetQuerySchema>;
export type OntologyTermClusterListQuery = Static<typeof OntologyTermClusterListQuerySchema>;
export type OntologyClusterMemberUpsertRequest = Static<typeof OntologyClusterMemberUpsertRequestSchema>;
export type OntologyClusterMemberListQuery = Static<typeof OntologyClusterMemberListQuerySchema>;
export type OntologyRawTermUpsertRequest = Static<typeof OntologyRawTermUpsertRequestSchema>;
export type OntologyRawTermGetQuery = Static<typeof OntologyRawTermGetQuerySchema>;
export type OntologyRelationCandidateUpsertRequest = Static<typeof OntologyRelationCandidateUpsertRequestSchema>;
export type OntologyRelationCandidateListQuery = Static<typeof OntologyRelationCandidateListQuerySchema>;
export type OntologyRawTermSearchQuery = Static<typeof OntologyRawTermSearchQuerySchema>;
export type OntologyRawTermCandidateUpsertRequest = Static<typeof OntologyRawTermCandidateUpsertRequestSchema>;
export type OntologyRawTermCandidateListQuery = Static<typeof OntologyRawTermCandidateListQuerySchema>;
export type OntologyRawTermNormalizationUpsertRequest = Static<typeof OntologyRawTermNormalizationUpsertRequestSchema>;
export type OntologyRawTermNormalizationListQuery = Static<typeof OntologyRawTermNormalizationListQuerySchema>;
export type TermMappingRuleUpsertRequest = Static<typeof TermMappingRuleUpsertRequestSchema>;
export type TermMappingRuleGetQuery = Static<typeof TermMappingRuleGetQuerySchema>;
export type TermMappingRuleSearchQuery = Static<typeof TermMappingRuleSearchQuerySchema>;
export type TermMappingRuleEvidenceUpsertRequest = Static<typeof TermMappingRuleEvidenceUpsertRequestSchema>;
export type TermMappingRuleEvidenceListQuery = Static<typeof TermMappingRuleEvidenceListQuerySchema>;
export type TermMappingInterpretQuery = Static<typeof TermMappingInterpretQuerySchema>;
export type TermMappingInterpretBatchRequest = Static<typeof TermMappingInterpretBatchRequestSchema>;

export class OntologyService {
  constructor(private readonly backend: GatewayBackendClient) {}

  async upsertConcept(request: OntologyConceptUpsertRequest) {
    return mapConcept(await this.backend.upsertOntologyConcept({
      concept_id: request.concept_id,
      canonical_name: request.canonical_name,
      concept_type: request.concept_type,
      aliases_json: JSON.stringify(request.aliases ?? [])
    }));
  }

  async getConcept(query: OntologyConceptGetQuery) {
    const record = await this.backend.getOntologyConcept({ concept_id: query.concept_id });
    return record ? mapConcept(record) : undefined;
  }

  async listConcepts(query: OntologyConceptListQuery) {
    const records = await this.backend.listOntologyConcepts({
      concept_type: query.concept_type,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapConcept);
  }

  async searchConcepts(query: OntologyConceptSearchQuery) {
    const records = await this.backend.searchOntologyConcepts({
      query: query.q,
      concept_type: query.concept_type,
      domain: query.domain,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapConcept);
  }

  async upsertAlias(request: ConceptAliasUpsertRequest) {
    return mapAlias(await this.backend.upsertConceptAlias(request));
  }

  async listAliases(query: ConceptAliasListQuery) {
    const records = await this.backend.listConceptAliases({
      concept_id: query.concept_id,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapAlias);
  }

  async searchAliases(query: ConceptAliasSearchQuery) {
    const records = await this.backend.searchConceptAliases({
      query: query.q,
      concept_id: query.concept_id,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapAlias);
  }

  async upsertEdge(request: OntologyEdgeUpsertRequest) {
    return mapEdge(await this.backend.upsertOntologyEdge(request));
  }

  async listEdges(query: OntologyEdgeListQuery) {
    const records = await this.backend.listOntologyEdges({
      src_concept_id: query.src_concept_id,
      predicate: query.predicate,
      dst_concept_id: query.dst_concept_id,
      limit: query.limit ?? 100
    });
    return records.map(mapEdge);
  }

  async upsertEventLink(request: EventConceptLinkUpsertRequest) {
    return mapEventLink(await this.backend.upsertEventConceptLink({
      ...request,
      evidence_json: JSON.stringify(request.evidence ?? {}),
      version_number: request.version_number
    }));
  }

  async listEventLinks(query: EventConceptLinkListQuery) {
    const records = await this.backend.listEventConceptLinks({
      stream_id: query.stream_id,
      event_id: query.event_id,
      concept_id: query.concept_id,
      role: query.role,
      limit: query.limit ?? 100
    });
    return records.map(mapEventLink);
  }

  async upsertObjectType(request: OntologyObjectTypeUpsertRequest) {
    return mapObjectType(await this.backend.upsertOntologyObjectType({
      type_id: request.type_id,
      display_name: request.display_name,
      description: request.description ?? '',
      enabled: request.enabled ?? true
    }));
  }

  async getObjectType(query: OntologyObjectTypeGetQuery) {
    const record = await this.backend.getOntologyObjectType({ type_id: query.type_id });
    return record ? mapObjectType(record) : undefined;
  }

  async listObjectTypes(query: OntologyObjectTypeListQuery) {
    const records = await this.backend.listOntologyObjectTypes({
      enabled_only: query.enabled_only ?? false,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapObjectType);
  }

  async upsertConceptTypeAssignment(request: OntologyConceptTypeAssignmentUpsertRequest) {
    return mapConceptTypeAssignment(await this.backend.upsertOntologyConceptTypeAssignment({
      assignment_id: request.assignment_id ?? '',
      domain: request.domain,
      concept_id: request.concept_id,
      object_type_id: request.object_type_id,
      assignment_status: request.assignment_status ?? 'auto',
      source_kind: request.source_kind,
      confidence: request.confidence ?? 0,
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async listConceptTypeAssignments(query: OntologyConceptTypeAssignmentListQuery) {
    const records = await this.backend.listOntologyConceptTypeAssignments({
      domain: query.domain,
      concept_id: query.concept_id,
      object_type_id: query.object_type_id,
      assignment_status: query.assignment_status,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapConceptTypeAssignment);
  }

  async upsertRelationType(request: OntologyRelationTypeUpsertRequest) {
    return mapRelationType(await this.backend.upsertOntologyRelationType({
      predicate: request.predicate,
      src_type_id: request.src_type_id,
      dst_type_id: request.dst_type_id,
      display_name: request.display_name,
      description: request.description ?? '',
      is_symmetric: request.is_symmetric ?? false,
      is_transitive: request.is_transitive ?? false,
      enabled: request.enabled ?? true
    }));
  }

  async getRelationType(query: OntologyRelationTypeGetQuery) {
    const record = await this.backend.getOntologyRelationType({ predicate: query.predicate });
    return record ? mapRelationType(record) : undefined;
  }

  async listRelationTypes(query: OntologyRelationTypeListQuery) {
    const records = await this.backend.listOntologyRelationTypes({
      src_type_id: query.src_type_id,
      dst_type_id: query.dst_type_id,
      enabled_only: query.enabled_only ?? false,
      query: query.q,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapRelationType);
  }

  async getFact(fact_id: number) {
    const record = await this.backend.getOntologyFact({ fact_id });
    return record ? mapFact(record) : undefined;
  }

  async listFacts(query: OntologyFactListQuery) {
    const records = await this.backend.listOntologyFacts({
      status: query.status,
      stream_id: query.stream_id,
      stream_prefix: query.stream_prefix ?? false,
      predicate: query.predicate,
      extractor: query.extractor,
      src_concept_id: query.src_concept_id,
      dst_concept_id: query.dst_concept_id,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapFact);
  }

  async upsertFactWithEvidence(request: OntologyFactUpsertWithEvidenceRequest) {
    const response = await this.backend.upsertOntologyFactWithEvidence({
      src_concept_id: request.src_concept_id,
      predicate: request.predicate,
      dst_concept_id: request.dst_concept_id,
      qualifier_json: JSON.stringify(request.qualifier ?? {}),
      confidence: request.confidence,
      extractor: request.extractor,
      status: request.status,
      review_note: request.review_note ?? '',
      valid_from: request.valid_from,
      valid_to: request.valid_to,
      evidence: request.evidence.map((item) => ({
        stream_id: item.stream_id,
        event_id: item.event_id,
        source_span: item.source_span,
        evidence_json: JSON.stringify(item.evidence ?? {}),
        confidence: item.confidence
      }))
    });
    return {
      fact: mapFact(response.fact),
      evidence_count: response.evidence_count
    };
  }

  async upsertSemanticBatch(request: SemanticBatchUpsertRequest) {
    return this.backend.upsertSemanticBatch({
      entities: request.entities.map((entity) => ({
        entity_id: entity.entity_id,
        entity_kind: entity.entity_kind,
        semantic_role: entity.semantic_role,
        namespace: entity.namespace,
        status: entity.status,
        property_datatype: entity.property_datatype ?? '',
        metadata_json: JSON.stringify(entity.metadata_json ?? {})
      })),
      statements: request.statements.map((statement) => ({
        statement_key: statement.statement_key,
        subject_id: statement.subject_id,
        property_id: statement.property_id,
        value_type: statement.value_type,
        value_entity_id: statement.value_entity_id ?? '',
        value_json: JSON.stringify(statement.value_json ?? {}),
        status: statement.status,
        confidence: statement.confidence ?? 0,
        created_by: statement.created_by,
        metadata_json: JSON.stringify(statement.metadata_json ?? {})
      })),
      qualifiers: request.qualifiers.map((qualifier) => ({
        statement_key: qualifier.statement_key,
        property_id: qualifier.property_id,
        value_type: qualifier.value_type,
        value_json: JSON.stringify(qualifier.value_json ?? {}),
        value_entity_id: qualifier.value_entity_id ?? '',
        ordinal: qualifier.ordinal
      })),
      references: request.references.map((reference) => ({
        statement_key: reference.statement_key,
        property_id: reference.property_id,
        value_type: reference.value_type,
        value_json: JSON.stringify(reference.value_json ?? {}),
        evidence_id: reference.evidence_id ?? '',
        source_span: reference.source_span ?? '',
        ordinal: reference.ordinal
      }))
    });
  }

  async getSemanticStatement(query: SemanticStatementGetQuery) {
    const response = await this.backend.getSemanticStatement({
      statement_id: query.statement_id
    });
    return {
      statement: response.statement ? mapSemanticStatement(response.statement) : undefined,
      qualifiers: response.qualifiers.map(mapSemanticStatementQualifier)
    };
  }

  async listSemanticStatements(query: SemanticStatementListQuery) {
    const response = await this.backend.listSemanticStatements({
      subject_id: query.subject_id ?? '',
      property_id: query.property_id ?? '',
      value_entity_id: query.value_entity_id ?? '',
      status: query.status ?? '',
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return {
      statements: response.statements
        .filter((entry) => entry.statement)
        .map((entry) => ({
          statement: mapSemanticStatement(entry.statement!),
          qualifiers: entry.qualifiers.map(mapSemanticStatementQualifier)
        }))
    };
  }

  async setSemanticStatementStatus(request: SemanticStatementStatusRequest) {
    return this.backend.setSemanticStatementStatus({
      statement_id: request.statement_id,
      status: request.status,
      note: request.note ?? ''
    });
  }

  async getSemanticStatementProvenance(query: SemanticStatementProvenanceQuery) {
    const response = await this.backend.getSemanticStatementProvenance({
      statement_id: query.statement_id,
      include_locators: query.include_locators ?? true,
      evidence_limit: query.evidence_limit ?? 50
    });
    return {
      references: response.references.map(mapSemanticStatementReference)
    };
  }

  async searchFacts(query: OntologyFactSearchQuery) {
    const records = await this.backend.searchOntologyFacts({
      query: query.q,
      status: query.status,
      stream_id: query.stream_id,
      stream_prefix: query.stream_prefix ?? false,
      predicate: query.predicate,
      extractor: query.extractor,
      src_concept_id: query.src_concept_id,
      dst_concept_id: query.dst_concept_id,
      limit: query.limit ?? 100,
      offset: query.offset ?? 0
    });
    return records.map(mapFact);
  }

  async getConceptNeighbors(query: OntologyConceptNeighborsQuery) {
    const records = await this.backend.getOntologyConceptNeighbors({
      concept_id: query.concept_id,
      direction: query.direction,
      predicate: query.predicate,
      limit: query.limit ?? 100
    });
    return records.map(mapNeighbor);
  }

  async archiveFact(request: OntologyFactArchiveRequest) {
    return this.backend.archiveOntologyFact(request);
  }

  async upsertTermMappingRegistry(request: TermMappingRegistryUpsertRequest) {
    return mapTermMappingRegistry(await this.backend.upsertTermMappingRegistry({
      domain: request.domain,
      registry_name: request.registry_name,
      version_label: request.version_label,
      status: request.status,
      description: request.description ?? '',
      owner: request.owner ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async getTermMappingRegistry(query: TermMappingRegistryGetQuery) {
    const record = await this.backend.getTermMappingRegistry({ registry_id: query.registry_id });
    return record ? mapTermMappingRegistry(record) : undefined;
  }

  async listTermMappingRegistries(query: TermMappingRegistryListQuery) {
    const records = await this.backend.listTermMappingRegistries({
      domain: query.domain,
      status: query.status,
      query: query.q,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapTermMappingRegistry);
  }

  async upsertNormalizedTerm(request: OntologyNormalizedTermUpsertRequest) {
    return mapOntologyNormalizedTerm(await this.backend.upsertOntologyNormalizedTerm({
      normalized_term_id: request.normalized_term_id ?? '',
      domain: request.domain,
      normalized_surface: request.normalized_surface,
      normalized_type: request.normalized_type ?? '',
      merge_key: request.merge_key ?? '',
      type_confidence: request.type_confidence ?? 0,
      head_term: request.head_term ?? '',
      modifier_terms_json: JSON.stringify(request.modifier_terms ?? []),
      canonical_candidate_label: request.canonical_candidate_label ?? '',
      canonical_candidate_concept_id: request.canonical_candidate_concept_id ?? '',
      primary_cluster_id: request.primary_cluster_id ?? '',
      source_support_count: request.source_support_count ?? 0,
      is_promotable: request.is_promotable ?? false,
      normalization_status: request.normalization_status ?? 'auto',
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async getNormalizedTerm(query: OntologyNormalizedTermGetQuery) {
    const record = await this.backend.getOntologyNormalizedTerm({ normalized_term_id: query.normalized_term_id });
    return record ? mapOntologyNormalizedTerm(record) : undefined;
  }

  async searchNormalizedTerms(query: OntologyNormalizedTermSearchQuery) {
    const records = await this.backend.searchOntologyNormalizedTerms({
      domain: query.domain,
      normalized_surface: query.normalized_surface,
      query: query.q,
      normalized_type: query.normalized_type,
      normalization_status: query.normalization_status,
      primary_cluster_id: query.primary_cluster_id,
      promotable_only: query.promotable_only ?? false,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyNormalizedTerm);
  }

  async upsertTermCluster(request: OntologyTermClusterUpsertRequest) {
    return mapOntologyTermCluster(await this.backend.upsertOntologyTermCluster({
      cluster_id: request.cluster_id ?? '',
      domain: request.domain,
      cluster_type: request.cluster_type ?? 'alias_like',
      proposed_canonical: request.proposed_canonical ?? '',
      proposed_type: request.proposed_type ?? '',
      cluster_status: request.cluster_status ?? 'auto',
      member_count: request.member_count ?? 0,
      source_support_count: request.source_support_count ?? 0,
      confidence: request.confidence ?? 0,
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async getTermCluster(query: OntologyTermClusterGetQuery) {
    const record = await this.backend.getOntologyTermCluster({ cluster_id: query.cluster_id });
    return record ? mapOntologyTermCluster(record) : undefined;
  }

  async listTermClusters(query: OntologyTermClusterListQuery) {
    const records = await this.backend.listOntologyTermClusters({
      domain: query.domain,
      cluster_type: query.cluster_type,
      cluster_status: query.cluster_status,
      proposed_type: query.proposed_type,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyTermCluster);
  }

  async upsertClusterMember(request: OntologyClusterMemberUpsertRequest) {
    return mapOntologyClusterMember(await this.backend.upsertOntologyClusterMember({
      cluster_member_id: request.cluster_member_id ?? '',
      cluster_id: request.cluster_id,
      normalized_term_id: request.normalized_term_id,
      member_role: request.member_role ?? 'core',
      membership_confidence: request.membership_confidence ?? 0,
      added_by: request.added_by ?? 'system',
      note: request.note ?? ''
    }));
  }

  async listClusterMembers(query: OntologyClusterMemberListQuery) {
    const records = await this.backend.listOntologyClusterMembers({
      cluster_id: query.cluster_id,
      normalized_term_id: query.normalized_term_id,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyClusterMember);
  }

  async upsertRelationCandidate(request: OntologyRelationCandidateUpsertRequest) {
    return mapOntologyRelationCandidate(await this.backend.upsertOntologyRelationCandidate({
      relation_candidate_id: request.relation_candidate_id ?? '',
      domain: request.domain,
      subject_label: request.subject_label,
      relation_type: request.relation_type,
      object_label: request.object_label,
      subject_concept_id: request.subject_concept_id ?? '',
      object_concept_id: request.object_concept_id ?? '',
      candidate_status: request.candidate_status ?? 'auto',
      source_kind: request.source_kind,
      source_cluster_id: request.source_cluster_id ?? '',
      confidence: request.confidence ?? 0,
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async listRelationCandidates(query: OntologyRelationCandidateListQuery) {
    const records = await this.backend.listOntologyRelationCandidates({
      domain: query.domain,
      relation_type: query.relation_type,
      candidate_status: query.candidate_status,
      subject_label: query.subject_label,
      object_label: query.object_label,
      source_kind: query.source_kind,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyRelationCandidate);
  }

  async upsertRawTerm(request: OntologyRawTermUpsertRequest) {
    return mapOntologyRawTerm(await this.backend.upsertOntologyRawTerm({
      raw_term_id: request.raw_term_id ?? '',
      domain: request.domain,
      raw_term: request.raw_term,
      language: request.language ?? 'zh',
      normalized_hint: request.normalized_hint ?? '',
      term_type_hint: request.term_type_hint ?? '',
      source_kind: request.source_kind,
      source_ref: request.source_ref ?? '',
      artifact_version_id: request.artifact_version_id ?? '',
      evidence_id: request.evidence_id ?? '',
      context_text: request.context_text ?? '',
      context_locator_json: JSON.stringify(request.context_locator ?? {}),
      extracted_by_type: request.extracted_by_type,
      extracted_by_id: request.extracted_by_id ?? '',
      status: request.status ?? 'new',
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async getRawTerm(query: OntologyRawTermGetQuery) {
    const record = await this.backend.getOntologyRawTerm({ raw_term_id: query.raw_term_id });
    return record ? mapOntologyRawTerm(record) : undefined;
  }

  async searchRawTerms(query: OntologyRawTermSearchQuery) {
    const records = await this.backend.searchOntologyRawTerms({
      domain: query.domain,
      raw_term: query.raw_term,
      query: query.q,
      language: query.language,
      status: query.status,
      term_type_hint: query.term_type_hint,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyRawTerm);
  }

  async upsertRawTermCandidate(request: OntologyRawTermCandidateUpsertRequest) {
    return mapOntologyRawTermCandidate(await this.backend.upsertOntologyRawTermCandidate({
      candidate_id: request.candidate_id ?? '',
      raw_term_id: request.raw_term_id,
      candidate_label: request.candidate_label ?? '',
      candidate_concept_id: request.candidate_concept_id ?? '',
      candidate_object_type: request.candidate_object_type ?? '',
      candidate_relation_type: request.candidate_relation_type ?? '',
      confidence: request.confidence ?? 0,
      candidate_status: request.candidate_status ?? 'proposed',
      review_note: request.review_note ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async listRawTermCandidates(query: OntologyRawTermCandidateListQuery) {
    const records = await this.backend.listOntologyRawTermCandidates({
      raw_term_id: query.raw_term_id,
      candidate_status: query.candidate_status,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyRawTermCandidate);
  }

  async upsertRawTermNormalization(request: OntologyRawTermNormalizationUpsertRequest) {
    return mapOntologyRawTermNormalization(await this.backend.upsertOntologyRawTermNormalization({
      mapping_id: request.mapping_id ?? '',
      raw_term_id: request.raw_term_id,
      normalized_term_id: request.normalized_term_id,
      mapping_confidence: request.mapping_confidence ?? 0,
      mapping_type: request.mapping_type ?? 'exact_surface',
      mapping_status: request.mapping_status ?? 'auto',
      component_role: request.component_role ?? '',
      normalization_rule: request.normalization_rule ?? '',
      note: request.note ?? '',
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async listRawTermNormalizations(query: OntologyRawTermNormalizationListQuery) {
    const records = await this.backend.listOntologyRawTermNormalizations({
      raw_term_id: query.raw_term_id,
      normalized_term_id: query.normalized_term_id,
      mapping_status: query.mapping_status,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapOntologyRawTermNormalization);
  }

  async upsertTermMappingRule(request: TermMappingRuleUpsertRequest) {
    return mapTermMappingRule(await this.backend.upsertTermMappingRule({
      rule_id: request.rule_id ?? '',
      registry_id: request.registry_id,
      raw_term: request.raw_term,
      language: request.language ?? 'zh',
      context_hint: request.context_hint ?? '',
      term_type: request.term_type,
      normalization_status: request.normalization_status,
      canonical_term: request.canonical_term ?? '',
      canonical_concept_id: request.canonical_concept_id ?? '',
      is_compound: request.is_compound ?? false,
      split_rule_json: JSON.stringify(request.split_rule ?? {}),
      semantic_slot: request.semantic_slot ?? '',
      json_targets_json: JSON.stringify(request.json_targets ?? []),
      ontology_target_kind: request.ontology_target_kind ?? 'concept',
      ambiguity_flag: request.ambiguity_flag ?? false,
      ambiguity_note: request.ambiguity_note ?? '',
      review_status: request.review_status ?? 'pending',
      confidence: request.confidence ?? 0,
      metadata_json: JSON.stringify(request.metadata ?? {})
    }));
  }

  async getTermMappingRule(query: TermMappingRuleGetQuery) {
    const record = await this.backend.getTermMappingRule({ rule_id: query.rule_id });
    return record ? mapTermMappingRule(record) : undefined;
  }

  async searchTermMappingRules(query: TermMappingRuleSearchQuery) {
    const records = await this.backend.searchTermMappingRules({
      registry_id: query.registry_id,
      raw_term: query.raw_term,
      query: query.q,
      language: query.language,
      term_type: query.term_type,
      semantic_slot: query.semantic_slot,
      review_status: query.review_status,
      ambiguity_only: query.ambiguity_only ?? false,
      limit: query.limit ?? 50,
      offset: query.offset ?? 0
    });
    return records.map(mapTermMappingRule);
  }

  async upsertTermMappingRuleEvidence(request: TermMappingRuleEvidenceUpsertRequest) {
    return mapTermMappingRuleEvidence(await this.backend.upsertTermMappingRuleEvidence({
      rule_evidence_id: request.rule_evidence_id ?? '',
      rule_id: request.rule_id,
      artifact_id: request.artifact_id ?? '',
      artifact_version_id: request.artifact_version_id ?? '',
      event_id: request.event_id ?? '',
      memory_decision_id: request.memory_decision_id ?? '',
      source_span: request.source_span ?? '',
      note: request.note ?? '',
      confidence: request.confidence ?? 0,
      evidence_json: JSON.stringify(request.evidence ?? {})
    }));
  }

  async listTermMappingRuleEvidence(query: TermMappingRuleEvidenceListQuery) {
    const records = await this.backend.listTermMappingRuleEvidence({
      rule_id: query.rule_id,
      limit: query.limit ?? 50
    });
    return records.map(mapTermMappingRuleEvidence);
  }

  async interpretTerm(query: TermMappingInterpretQuery) {
    const record = await this.backend.interpretTerm({
      registry_id: query.registry_id,
      domain: query.domain,
      registry_name: query.registry_name,
      version_label: query.version_label,
      raw_term: query.raw_term,
      language: query.language ?? 'zh',
      context_hint: query.context_hint ?? ''
    });
    return record ? mapTermMappingInterpretation(record) : undefined;
  }

  async interpretTermBatch(request: TermMappingInterpretBatchRequest) {
    const records = await this.backend.interpretTermBatch({
      registry_id: request.registry_id,
      domain: request.domain,
      registry_name: request.registry_name,
      version_label: request.version_label,
      raw_terms: request.raw_terms,
      language: request.language ?? 'zh',
      context_hint: request.context_hint ?? ''
    });
    return records.map(mapTermMappingInterpretation);
  }
}

function safeJson(value: unknown, fallback: unknown) {
  if (value === null || value === undefined || value === '') {
    return fallback;
  }
  // Some records arrive already parsed: the gRPC client runs parseJsonString on
  // JSON-bearing fields (statement value_json, qualifier value_json, ...), so by
  // the time they reach here they are objects, not strings. Calling JSON.parse
  // on an object stringifies it to "[object Object]", throws, and silently
  // returns the fallback — which wiped every qualifier value to {} on read.
  if (typeof value !== 'string') {
    return value;
  }
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function mapConcept(record: OntologyConceptRecord) {
  return { ...record, aliases: safeJson(record.aliases_json, []) as string[] };
}
function mapAlias(record: ConceptAliasRecord) { return record; }
function mapEdge(record: OntologyEdgeRecord) { return record; }
function mapEventLink(record: EventConceptLinkRecord) {
  return { ...record, evidence: safeJson(record.evidence_json, {}) as Record<string, unknown> };
}
function mapObjectType(record: OntologyObjectTypeRecord) { return record; }
function mapConceptTypeAssignment(record: OntologyConceptTypeAssignmentRecord) {
  return {
    ...record,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}
function mapRelationType(record: OntologyRelationTypeRecord) { return record; }
function mapFact(record: OntologyFactRecord) {
  return {
    ...record,
    statement_id: record.statement_id || undefined,
    qualifier: safeJson(record.qualifier_json, {}),
    valid_from: record.valid_from || undefined,
    valid_to: record.valid_to || undefined
  };
}

function mapNeighbor(record: OntologyNeighborRecord) {
  return record;
}

function mapSemanticStatement(record: SemanticStatementRecord) {
  return {
    ...record,
    value_json: safeJson(record.value_json, {}),
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>,
    provenance: safeJson(record.provenance_json, {}) as Record<string, unknown>
  };
}

function mapSemanticStatementQualifier(record: SemanticStatementQualifierRecord) {
  return {
    ...record,
    value_entity_id: record.value_entity_id || undefined,
    value: safeJson(record.value_json, {})
  };
}

function mapSemanticStatementReference(record: SemanticStatementReferenceRecord) {
  return {
    ...record,
    evidence_id: record.evidence_id || undefined,
    source_span: record.source_span || undefined,
    value: safeJson(record.value_json, {}),
    evidence: record.evidence ? mapSemanticEvidence(record.evidence) : undefined,
    locators: (record.locators ?? []).map(mapSemanticEvidenceLocator)
  };
}

function mapSemanticEvidence(record: EvidenceRecord) {
  return {
    ...record,
    case_id: record.case_id || undefined,
    event_seq: record.event_seq > 0 ? record.event_seq : undefined,
    artifact_version_id: record.artifact_version_id || undefined,
    methodology_framework_id: record.methodology_framework_id || undefined,
    evidence_payload: safeJson(record.evidence_payload_json, {}) as Record<string, unknown>
  };
}

function mapSemanticEvidenceLocator(record: EvidenceLocatorRecord) {
  return {
    ...record,
    page_span: record.page_span || undefined,
    char_span: record.char_span || undefined,
    sentence_ref: record.sentence_ref_json ? safeJson(record.sentence_ref_json, {}) as Record<string, unknown> : undefined,
    bbox: record.bbox_json ? safeJson(record.bbox_json, {}) as Record<string, unknown> : undefined,
    polygon: record.polygon_json ? safeJson(record.polygon_json, {}) as Record<string, unknown> : undefined,
    time_range: record.time_range || undefined,
    table_cell: record.table_cell_json ? safeJson(record.table_cell_json, {}) as Record<string, unknown> : undefined,
    measurement_field: record.measurement_field || undefined,
    locator_payload: safeJson(record.locator_payload_json, {}) as Record<string, unknown>,
    normalized_text: record.normalized_text || undefined,
    preview_text: record.preview_text || undefined
  };
}

function mapTermMappingRegistry(record: TermMappingRegistryRecord) {
  return { ...record, metadata: safeJson(record.metadata_json, {}) as Record<string, unknown> };
}

function mapOntologyNormalizedTerm(record: OntologyNormalizedTermRecord) {
  return {
    ...record,
    modifier_terms: safeJson(record.modifier_terms_json, []) as string[],
    canonical_candidate_concept_id: record.canonical_candidate_concept_id || undefined,
    primary_cluster_id: record.primary_cluster_id || undefined,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapOntologyTermCluster(record: OntologyTermClusterRecord) {
  return {
    ...record,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapOntologyClusterMember(record: OntologyClusterMemberRecord) {
  return record;
}

function mapOntologyRelationCandidate(record: OntologyRelationCandidateRecord) {
  return {
    ...record,
    subject_concept_id: record.subject_concept_id || undefined,
    object_concept_id: record.object_concept_id || undefined,
    source_cluster_id: record.source_cluster_id || undefined,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapOntologyRawTerm(record: OntologyRawTermRecord) {
  return {
    ...record,
    artifact_version_id: record.artifact_version_id || undefined,
    evidence_id: record.evidence_id || undefined,
    context_locator: safeJson(record.context_locator_json, {}) as Record<string, unknown>,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapOntologyRawTermCandidate(record: OntologyRawTermCandidateRecord) {
  return {
    ...record,
    candidate_concept_id: record.candidate_concept_id || undefined,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapOntologyRawTermNormalization(record: OntologyRawTermNormalizationRecord) {
  return {
    ...record,
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapTermMappingRule(record: TermMappingRuleRecord) {
  return {
    ...record,
    split_rule: safeJson(record.split_rule_json, {}) as Record<string, unknown>,
    json_targets: safeJson(record.json_targets_json, []) as string[],
    metadata: safeJson(record.metadata_json, {}) as Record<string, unknown>
  };
}

function mapTermMappingRuleEvidence(record: TermMappingRuleEvidenceRecord) {
  return { ...record, evidence: safeJson(record.evidence_json, {}) as Record<string, unknown> };
}

function mapTermMappingInterpretation(record: TermMappingInterpretationRecord) {
  return {
    ...record,
    matched_rule_id: record.matched_rule_id || undefined,
    split_rule: safeJson(record.split_rule_json, {}) as Record<string, unknown>,
    json_targets: safeJson(record.json_targets_json, []) as string[]
  };
}
