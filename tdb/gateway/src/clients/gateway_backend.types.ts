import type { SearchHit, SearchQueryRequest, SearchQueryResult } from '../services/search.service.js';

export type GatewayBackendConfig = {
  address: string;
  timeoutMs: number;
};

export type GatewayBackendClient = {
  searchQuery(request: SearchQueryRequest, traceId?: string): Promise<SearchQueryResult>;
  upsertDomainStreamBinding(request: DomainStreamBindingUpsertRequest): Promise<DomainStreamBindingRecord>;
  listDomainStreamBindings(request: DomainStreamBindingListQuery): Promise<DomainStreamBindingRecord[]>;
  indexEvent(request: IndexEventRequest): Promise<string>;
  appendEvent(request: AppendEventRequest): Promise<AppendEventResponse>;
  getEvents(request: GetEventsRequest): Promise<EventItem[]>;
  getEventSentences(request: GetEventSentencesRequest): Promise<EventSentenceRecord[]>;
  upsertProperty(request: UpsertPropertyRequest): Promise<PropertyRecord>;
  getPropertyAsOf(request: GetPropertyAsOfRequest): Promise<PropertyRecord | undefined>;
  upsertEdge(request: UpsertEdgeRequest): Promise<EdgeRecord>;
  getEdgesAsOf(request: GetEdgesAsOfRequest): Promise<EdgeRecord[]>;
  listPropertyRows(request: ListPropertyRowsRequest): Promise<PropertyRecord[]>;
  upsertEntity(request: UpsertEntityRequest): Promise<EntityRecord>;
  getEntity(request: GetEntityRequest): Promise<EntityRecord | undefined>;
  listEntities(request: ListEntitiesRequest): Promise<EntityRecord[]>;
  writeSnapshot(request: WriteSnapshotRequest): Promise<SnapshotRecord>;
  getLatestSnapshot(request: GetLatestSnapshotRequest): Promise<SnapshotRecord | undefined>;
  createArtifact(request: CreateArtifactRequest): Promise<ArtifactRecord>;
  createArtifactVersion(request: CreateArtifactVersionRequest): Promise<ArtifactVersionRecord>;
  getArtifactVersionAsOf(request: GetArtifactVersionAsOfRequest): Promise<ArtifactVersionRecord | undefined>;
  getArtifactVersionById(request: GetArtifactVersionByIdRequest): Promise<ArtifactVersionRecord | undefined>;
  upsertDecision(request: UpsertDecisionRequest): Promise<DecisionRecord>;
  insertDecisionEvidence(request: InsertDecisionEvidenceRequest): Promise<DecisionEvidenceRecord>;
  findDecision(request: FindDecisionRequest): Promise<DecisionRecord | undefined>;
  listDecisionEvidence(request: ListDecisionEvidenceRequest): Promise<DecisionEvidenceRecord[]>;
  upsertAssertion(request: UpsertAssertionRequest): Promise<AssertionRecord>;
  getAssertion(request: GetAssertionRequest): Promise<AssertionRecord | undefined>;
  searchAssertions(request: SearchAssertionsRequest): Promise<AssertionRecord[]>;
  upsertEvidence(request: UpsertEvidenceRequest): Promise<EvidenceRecord>;
  getEvidence(request: GetEvidenceRequest): Promise<EvidenceRecord | undefined>;
  searchEvidence(request: SearchEvidenceRequest): Promise<EvidenceRecord[]>;
  upsertEvidenceLocator(request: UpsertEvidenceLocatorRequest): Promise<EvidenceLocatorRecord>;
  listEvidenceLocators(request: ListEvidenceLocatorsRequest): Promise<EvidenceLocatorRecord[]>;
  upsertEvidenceDerivation(request: UpsertEvidenceDerivationRequest): Promise<EvidenceDerivationRecord>;
  listEvidenceDerivations(request: ListEvidenceDerivationsRequest): Promise<EvidenceDerivationRecord[]>;
  upsertEvidenceClassification(request: UpsertEvidenceClassificationRequest): Promise<EvidenceClassificationRecord>;
  getEvidenceClassification(request: GetEvidenceClassificationRequest): Promise<EvidenceClassificationRecord | undefined>;
  upsertAssertionEvidenceLink(request: UpsertAssertionEvidenceLinkRequest): Promise<AssertionEvidenceLinkRecord>;
  listAssertionEvidenceLinks(request: ListAssertionEvidenceLinksRequest): Promise<AssertionEvidenceLinkRecord[]>;
  upsertAssertionRelation(request: UpsertAssertionRelationRequest): Promise<AssertionRelationRecord>;
  listAssertionRelations(request: ListAssertionRelationsRequest): Promise<AssertionRelationRecord[]>;
  insertMemoryDecision(request: InsertMemoryDecisionRequest): Promise<MemoryDecisionRecord>;
  listRecentMemoryDecisions(request: ListRecentMemoryDecisionsRequest): Promise<MemoryDecisionRecord[]>;
  insertMemoryEpisodeSummary(request: InsertMemoryEpisodeSummaryRequest): Promise<MemoryEpisodeSummaryRecord>;
  listRecentMemoryEpisodeSummaries(request: ListRecentMemoryEpisodeSummariesRequest): Promise<MemoryEpisodeSummaryRecord[]>;
  insertMemoryAnswerArtifact(request: InsertMemoryAnswerArtifactRequest): Promise<MemoryAnswerArtifactRecord>;
  recallMemoryAnswerArtifacts(request: RecallMemoryAnswerArtifactsRequest): Promise<MemoryAnswerArtifactRecord[]>;
  insertMemoryAnswerValidation(request: InsertMemoryAnswerValidationRequest): Promise<MemoryAnswerValidationRecord>;
  upsertOntologyConcept(request: UpsertOntologyConceptRequest): Promise<OntologyConceptRecord>;
  getOntologyConcept(request: GetOntologyConceptRequest): Promise<OntologyConceptRecord | undefined>;
  listOntologyConcepts(request: ListOntologyConceptsRequest): Promise<OntologyConceptRecord[]>;
  upsertConceptAlias(request: UpsertConceptAliasRequest): Promise<ConceptAliasRecord>;
  listConceptAliases(request: ListConceptAliasesRequest): Promise<ConceptAliasRecord[]>;
  upsertOntologyEdge(request: UpsertOntologyEdgeRequest): Promise<OntologyEdgeRecord>;
  listOntologyEdges(request: ListOntologyEdgesRequest): Promise<OntologyEdgeRecord[]>;
  upsertEventConceptLink(request: UpsertEventConceptLinkRequest): Promise<EventConceptLinkRecord>;
  listEventConceptLinks(request: ListEventConceptLinksRequest): Promise<EventConceptLinkRecord[]>;
  upsertOntologyObjectType(request: UpsertOntologyObjectTypeRequest): Promise<OntologyObjectTypeRecord>;
  getOntologyObjectType(request: GetOntologyObjectTypeRequest): Promise<OntologyObjectTypeRecord | undefined>;
  listOntologyObjectTypes(request: ListOntologyObjectTypesRequest): Promise<OntologyObjectTypeRecord[]>;
  upsertOntologyConceptTypeAssignment(request: UpsertOntologyConceptTypeAssignmentRequest): Promise<OntologyConceptTypeAssignmentRecord>;
  listOntologyConceptTypeAssignments(request: ListOntologyConceptTypeAssignmentsRequest): Promise<OntologyConceptTypeAssignmentRecord[]>;
  upsertOntologyRelationType(request: UpsertOntologyRelationTypeRequest): Promise<OntologyRelationTypeRecord>;
  getOntologyRelationType(request: GetOntologyRelationTypeRequest): Promise<OntologyRelationTypeRecord | undefined>;
  listOntologyRelationTypes(request: ListOntologyRelationTypesRequest): Promise<OntologyRelationTypeRecord[]>;
  listOntologyFacts(request: ListOntologyFactsRequest): Promise<OntologyFactRecord[]>;
  upsertOntologyFactWithEvidence(request: UpsertOntologyFactWithEvidenceRequest): Promise<{ fact: OntologyFactRecord; evidence_count: number }>;
  upsertSemanticBatch(request: UpsertSemanticBatchRequest): Promise<UpsertSemanticBatchResponse>;
  getSemanticStatement(request: GetSemanticStatementRequest): Promise<GetSemanticStatementResponse>;
  listSemanticStatements(request: ListSemanticStatementsRequest): Promise<ListSemanticStatementsResponse>;
  setSemanticStatementStatus(request: SetSemanticStatementStatusRequest): Promise<SetSemanticStatementStatusResponse>;
  getSemanticStatementProvenance(
    request: GetSemanticStatementProvenanceRequest
  ): Promise<GetSemanticStatementProvenanceResponse>;
  getSemanticStatementsByEvidence(
    request: GetSemanticStatementsByEvidenceRequest
  ): Promise<GetSemanticStatementsByEvidenceResponse>;
  searchOntologyConcepts(request: SearchOntologyConceptsRequest): Promise<OntologyConceptRecord[]>;
  searchConceptAliases(request: SearchConceptAliasesRequest): Promise<ConceptAliasRecord[]>;
  searchOntologyFacts(request: SearchOntologyFactsRequest): Promise<OntologyFactRecord[]>;
  getOntologyConceptNeighbors(request: GetOntologyConceptNeighborsRequest): Promise<OntologyNeighborRecord[]>;
  archiveOntologyFact(request: ArchiveOntologyFactRequest): Promise<number>;
  upsertTermMappingRegistry(request: UpsertTermMappingRegistryRequest): Promise<TermMappingRegistryRecord>;
  getTermMappingRegistry(request: GetTermMappingRegistryRequest): Promise<TermMappingRegistryRecord | undefined>;
  listTermMappingRegistries(request: ListTermMappingRegistriesRequest): Promise<TermMappingRegistryRecord[]>;
  upsertOntologyNormalizedTerm(request: UpsertOntologyNormalizedTermRequest): Promise<OntologyNormalizedTermRecord>;
  getOntologyNormalizedTerm(request: GetOntologyNormalizedTermRequest): Promise<OntologyNormalizedTermRecord | undefined>;
  searchOntologyNormalizedTerms(request: SearchOntologyNormalizedTermsRequest): Promise<OntologyNormalizedTermRecord[]>;
  upsertOntologyTermCluster(request: UpsertOntologyTermClusterRequest): Promise<OntologyTermClusterRecord>;
  getOntologyTermCluster(request: GetOntologyTermClusterRequest): Promise<OntologyTermClusterRecord | undefined>;
  listOntologyTermClusters(request: ListOntologyTermClustersRequest): Promise<OntologyTermClusterRecord[]>;
  upsertOntologyClusterMember(request: UpsertOntologyClusterMemberRequest): Promise<OntologyClusterMemberRecord>;
  listOntologyClusterMembers(request: ListOntologyClusterMembersRequest): Promise<OntologyClusterMemberRecord[]>;
  upsertOntologyRelationCandidate(request: UpsertOntologyRelationCandidateRequest): Promise<OntologyRelationCandidateRecord>;
  listOntologyRelationCandidates(request: ListOntologyRelationCandidatesRequest): Promise<OntologyRelationCandidateRecord[]>;
  upsertOntologyRawTerm(request: UpsertOntologyRawTermRequest): Promise<OntologyRawTermRecord>;
  getOntologyRawTerm(request: GetOntologyRawTermRequest): Promise<OntologyRawTermRecord | undefined>;
  searchOntologyRawTerms(request: SearchOntologyRawTermsRequest): Promise<OntologyRawTermRecord[]>;
  upsertOntologyRawTermCandidate(request: UpsertOntologyRawTermCandidateRequest): Promise<OntologyRawTermCandidateRecord>;
  listOntologyRawTermCandidates(request: ListOntologyRawTermCandidatesRequest): Promise<OntologyRawTermCandidateRecord[]>;
  upsertOntologyRawTermNormalization(request: UpsertOntologyRawTermNormalizationRequest): Promise<OntologyRawTermNormalizationRecord>;
  listOntologyRawTermNormalizations(request: ListOntologyRawTermNormalizationsRequest): Promise<OntologyRawTermNormalizationRecord[]>;
  upsertTermMappingRule(request: UpsertTermMappingRuleRequest): Promise<TermMappingRuleRecord>;
  getTermMappingRule(request: GetTermMappingRuleRequest): Promise<TermMappingRuleRecord | undefined>;
  searchTermMappingRules(request: SearchTermMappingRulesRequest): Promise<TermMappingRuleRecord[]>;
  upsertTermMappingRuleEvidence(request: UpsertTermMappingRuleEvidenceRequest): Promise<TermMappingRuleEvidenceRecord>;
  listTermMappingRuleEvidence(request: ListTermMappingRuleEvidenceRequest): Promise<TermMappingRuleEvidenceRecord[]>;
  interpretTerm(request: InterpretTermRequest): Promise<TermMappingInterpretationRecord | undefined>;
  interpretTermBatch(request: InterpretTermBatchRequest): Promise<TermMappingInterpretationRecord[]>;
  // Governance
  upsertRule(request: UpsertRuleRequest): Promise<RuleRecord>;
  insertAuthorityGrant(request: InsertAuthorityGrantRequest): Promise<AuthorityGrantRecord>;
  insertRuleOverride(request: InsertRuleOverrideRequest): Promise<RuleOverrideRecord>;
  findAuthorityAsOf(request: FindAuthorityAsOfRequest): Promise<AuthorityGrantRecord | undefined>;
  listRuleOverridesAsOf(request: ListRuleOverridesAsOfRequest): Promise<RuleOverrideRecord[]>;
  upsertMethodologyFramework(request: UpsertMethodologyFrameworkRequest): Promise<MethodologyFrameworkRecord>;
  getMethodologyFramework(request: GetMethodologyFrameworkRequest): Promise<MethodologyFrameworkRecord | undefined>;
  listMethodologyFrameworks(request: ListMethodologyFrameworksRequest): Promise<MethodologyFrameworkRecord[]>;
  getMethodologyFrameworkBundle(request: GetMethodologyFrameworkBundleRequest): Promise<GetMethodologyFrameworkBundleResponse>;
  upsertTaxonomyScheme(request: UpsertTaxonomySchemeRequest): Promise<TaxonomySchemeRecord>;
  getTaxonomyScheme(request: GetTaxonomySchemeRequest): Promise<TaxonomySchemeRecord | undefined>;
  listTaxonomySchemes(request: ListTaxonomySchemesRequest): Promise<TaxonomySchemeRecord[]>;
  upsertEvidencePolicyRule(request: UpsertEvidencePolicyRuleRequest): Promise<EvidencePolicyRuleRecord>;
  getEvidencePolicyRule(request: GetEvidencePolicyRuleRequest): Promise<EvidencePolicyRuleRecord | undefined>;
  listEvidencePolicyRules(request: ListEvidencePolicyRulesRequest): Promise<EvidencePolicyRuleRecord[]>;
  upsertAssertionPolicyRule(request: UpsertAssertionPolicyRuleRequest): Promise<AssertionPolicyRuleRecord>;
  getAssertionPolicyRule(request: GetAssertionPolicyRuleRequest): Promise<AssertionPolicyRuleRecord | undefined>;
  listAssertionPolicyRules(request: ListAssertionPolicyRulesRequest): Promise<AssertionPolicyRuleRecord[]>;
  upsertReviewPolicy(request: UpsertReviewPolicyRequest): Promise<ReviewPolicyRecord>;
  getReviewPolicy(request: GetReviewPolicyRequest): Promise<ReviewPolicyRecord | undefined>;
  listReviewPolicies(request: ListReviewPoliciesRequest): Promise<ReviewPolicyRecord[]>;
  // Ontology Facts
  reviewOntologyFact(request: ReviewOntologyFactRequest): Promise<number>;
  getOntologyFact(request: GetOntologyFactRequest): Promise<OntologyFactRecord | undefined>;
  listOntologyFactReviews(request: ListOntologyFactReviewsRequest): Promise<OntologyFactReviewRecord[]>;
  listOntologyFactEvidence(request: ListOntologyFactEvidenceRequest): Promise<OntologyFactEvidenceRecord[]>;
  listOntologyFactLinkedCases(request: ListOntologyFactLinkedCasesRequest): Promise<OntologyFactLinkedCaseRecord[]>;
  listOntologyFactLinkedAlerts(request: ListOntologyFactLinkedAlertsRequest): Promise<OntologyFactLinkedAlertRecord[]>;
  selectOntologyFactsForBulkReview(request: SelectOntologyFactsForBulkReviewRequest): Promise<OntologyFactBulkSelectionRecord[]>;
  // Ontology Cases
  insertOntologyCase(request: InsertOntologyCaseRequest): Promise<OntologyCaseRecord>;
  getOntologyCase(request: GetOntologyCaseRequest): Promise<OntologyCaseRecord | undefined>;
  listOntologyCases(request: ListOntologyCasesRequest): Promise<OntologyCaseSummaryRecord[]>;
  updateOntologyCase(request: UpdateOntologyCaseRequest): Promise<number>;
  linkOntologyCaseFact(request: LinkOntologyCaseFactRequest): Promise<boolean>;
  listOntologyCaseFacts(request: ListOntologyCaseFactsRequest): Promise<OntologyCaseFactRecord[]>;
  insertOntologyCaseDecision(request: InsertOntologyCaseDecisionRequest): Promise<OntologyCaseDecisionRecord>;
  listOntologyCaseDecisions(request: ListOntologyCaseDecisionsRequest): Promise<OntologyCaseDecisionRecord[]>;
  insertOntologyCaseEvent(request: InsertOntologyCaseEventRequest): Promise<OntologyCaseEventRecord>;
  listOntologyCaseEvents(request: ListOntologyCaseEventsRequest): Promise<OntologyCaseEventRecord[]>;
  // Ontology Alerts
  insertOntologyAlert(request: InsertOntologyAlertRequest): Promise<OntologyAlertRecord>;
  getOntologyAlertDetail(request: GetOntologyAlertDetailRequest): Promise<OntologyAlertDetailRecord | undefined>;
  listOntologyAlerts(request: ListOntologyAlertsRequest): Promise<OntologyAlertSummaryRecord[]>;
  updateOntologyAlert(request: UpdateOntologyAlertRequest): Promise<number>;

  // Ontology Ops
  upsertOntologyOpsRuleConfig(request: UpsertOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord>;
  listOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord[]>;
  insertOntologyOpsRuleRun(request: InsertOntologyOpsRuleRunRequest): Promise<OntologyOpsRuleRunRecord>;
  getOntologyOpsRun(request: GetOntologyOpsRunRequest): Promise<OntologyOpsRuleRunRecord | undefined>;
  listOntologyOpsRuns(request: ListOntologyOpsRunsRequest): Promise<OntologyOpsRuleRunRecord[]>;
  listApplicableOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord[]>;
  listStalePendingOntologyCandidates(request: ListStalePendingOntologyCandidatesRequest): Promise<OntologyFactRecord[]>;
  listConflictPredicateOntologyCandidates(request: ListConflictPredicateOntologyCandidatesRequest): Promise<OntologyFactRecord[]>;
  getActiveOntologyCaseByTitle(request: GetActiveOntologyCaseByTitleRequest): Promise<OntologyCaseRecord | undefined>;
  getActiveOntologyAlertByRuleKey(request: GetActiveOntologyAlertByRuleKeyRequest): Promise<OntologyAlertRecord | undefined>;
  refreshTriggeredOntologyAlert(request: RefreshTriggeredOntologyAlertRequest): Promise<OntologyAlertRecord>;
  linkOntologyAlertFact(request: LinkOntologyAlertFactRequest): Promise<void>;
  // Wiki
  upsertWikiPage(request: UpsertWikiPageRequest): Promise<UpsertWikiPageResponse>;
  upsertWikiPageLink(request: UpsertWikiPageLinkRequest): Promise<UpsertWikiPageLinkResponse>;
  getWikiPage(request: GetWikiPageRequest): Promise<WikiPageRecord | undefined>;
  searchWikiPages(request: SearchWikiPagesRequest): Promise<WikiPageRecord[]>;
  listWikiPages(request: ListWikiPagesRequest): Promise<ListWikiPagesResponse>;
  reinforceWikiPage(request: ReinforceWikiPageRequest): Promise<WikiPageRecord | undefined>;
  appendWikiLog(request: AppendWikiLogRequest): Promise<WikiLogRecord | undefined>;
  listWikiLogs(request: ListWikiLogsRequest): Promise<WikiLogRecord[]>;
  lintWikiDomain(request: LintWikiDomainRequest): Promise<WikiLintIssue[]>;
  close(): void;
};

export type UpsertDecisionRequest = {
  case_id: string;
  event_seq: number;
  projection_version: string;
  chosen_action: string;
  candidates_json: string;
  scores_json: string;
  constraints_hit: string[];
  detail_json: string;
};

export type UpsertDecisionResponse = {
  decision: DecisionRecord;
};

export type InsertDecisionEvidenceRequest = {
  decision_id: string;
  artifact_version_id: string;
  citation_json: string;
};

export type InsertDecisionEvidenceResponse = {
  evidence: DecisionEvidenceRecord;
};

export type FindDecisionRequest = {
  case_id: string;
  event_seq: number;
  projection_version: string;
};

export type FindDecisionResponse = {
  decision?: DecisionRecord;
};

export type ListDecisionEvidenceRequest = {
  decision_id: string;
};

export type ListDecisionEvidenceResponse = {
  evidence: DecisionEvidenceRecord[];
};

export type DecisionRecord = {
  decision_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  chosen_action: string;
  candidates_json: string;
  scores_json: string;
  constraints_hit: string[];
  detail_json: string;
  created_at: string;
};

export type DecisionEvidenceRecord = {
  decision_evidence_id: string;
  decision_id: string;
  artifact_version_id: string;
  citation_json: string;
  created_at: string;
};

export type UpsertAssertionRequest = {
  assertion_id: string;
  case_id: string;
  subject_type: string;
  subject_id: string;
  predicate: string;
  object_type: string;
  object_id: string;
  object_literal_json: string;
  assertion_type: string;
  asserted_by_type: string;
  asserted_by_id: string;
  confidence: number;
  status: string;
  methodology_framework_id: string;
  source_event_id: string;
  metadata_json: string;
};

export type UpsertAssertionResponse = {
  assertion?: AssertionRecord;
};

export type GetAssertionRequest = {
  assertion_id: string;
};

export type GetAssertionResponse = {
  assertion?: AssertionRecord;
};

export type SearchAssertionsRequest = {
  case_id?: string;
  subject_type?: string;
  subject_id?: string;
  predicate?: string;
  assertion_type?: string;
  status?: string;
  methodology_framework_id?: string;
  query?: string;
  limit?: number;
  offset?: number;
};

export type SearchAssertionsResponse = {
  assertions: AssertionRecord[];
};

export type AssertionRecord = {
  assertion_id: string;
  case_id: string;
  subject_type: string;
  subject_id: string;
  predicate: string;
  object_type: string;
  object_id: string;
  object_literal_json: string;
  assertion_type: string;
  asserted_by_type: string;
  asserted_by_id: string;
  confidence: number;
  status: string;
  methodology_framework_id: string;
  source_event_id: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertEvidenceRequest = {
  evidence_id: string;
  case_id: string;
  event_seq: number;
  source_kind: string;
  source_id: string;
  artifact_version_id: string;
  evidence_type: string;
  evidence_role: string;
  methodology_framework_id: string;
  evidence_payload_json: string;
  created_by_type: string;
  created_by_id: string;
  is_derived: boolean;
  status: string;
};

export type UpsertEvidenceResponse = {
  evidence?: EvidenceRecord;
};

export type GetEvidenceRequest = {
  evidence_id: string;
};

export type GetEvidenceResponse = {
  evidence?: EvidenceRecord;
};

export type SearchEvidenceRequest = {
  case_id: string;
  source_kind: string;
  evidence_type: string;
  evidence_role: string;
  status: string;
  methodology_framework_id: string;
  query: string;
  limit?: number;
  offset?: number;
};

export type SearchEvidenceResponse = {
  evidence: EvidenceRecord[];
};

export type EvidenceRecord = {
  evidence_id: string;
  case_id: string;
  event_seq: number;
  source_kind: string;
  source_id: string;
  artifact_version_id: string;
  evidence_type: string;
  evidence_role: string;
  methodology_framework_id: string;
  evidence_payload_json: string;
  created_by_type: string;
  created_by_id: string;
  is_derived: boolean;
  status: string;
  created_at: string;
  updated_at: string;
};

export type UpsertEvidenceLocatorRequest = {
  evidence_locator_id: string;
  evidence_id: string;
  locator_type: string;
  page_span: string;
  char_span: string;
  sentence_ref_json: string;
  bbox_json: string;
  polygon_json: string;
  time_range: string;
  table_cell_json: string;
  measurement_field: string;
  locator_payload_json: string;
  normalized_text: string;
  preview_text: string;
};

export type UpsertEvidenceLocatorResponse = {
  locator?: EvidenceLocatorRecord;
};

export type ListEvidenceLocatorsRequest = {
  evidence_id: string;
  limit?: number;
  offset?: number;
};

export type ListEvidenceLocatorsResponse = {
  locators: EvidenceLocatorRecord[];
};

export type EvidenceLocatorRecord = {
  evidence_locator_id: string;
  evidence_id: string;
  locator_type: string;
  page_span: string;
  char_span: string;
  sentence_ref_json: string;
  bbox_json: string;
  polygon_json: string;
  time_range: string;
  table_cell_json: string;
  measurement_field: string;
  locator_payload_json: string;
  normalized_text: string;
  preview_text: string;
  created_at: string;
};

export type UpsertEvidenceDerivationRequest = {
  evidence_derivation_id: string;
  child_evidence_id: string;
  parent_evidence_id: string;
  derivation_type: string;
  method: string;
  run_id: string;
  artifact_version_id: string;
  derivation_metadata_json: string;
};

export type UpsertEvidenceDerivationResponse = {
  derivation?: EvidenceDerivationRecord;
};

export type ListEvidenceDerivationsRequest = {
  evidence_id: string;
  direction: string;
  limit?: number;
  offset?: number;
};

export type ListEvidenceDerivationsResponse = {
  derivations: EvidenceDerivationRecord[];
};

export type EvidenceDerivationRecord = {
  evidence_derivation_id: string;
  child_evidence_id: string;
  parent_evidence_id: string;
  derivation_type: string;
  method: string;
  run_id: string;
  artifact_version_id: string;
  derivation_metadata_json: string;
  created_at: string;
};

export type UpsertEvidenceClassificationRequest = {
  evidence_id: string;
  source_reliability_tier: string;
  evidence_strength_tier: string;
  evidence_modality: string;
  institutional_trust_class: string;
  is_primary_source: boolean;
  is_machine_generated: boolean;
  requires_human_validation: boolean;
  methodology_framework_id: string;
  classification_status: string;
  metadata_json: string;
};

export type UpsertEvidenceClassificationResponse = {
  classification?: EvidenceClassificationRecord;
};

export type GetEvidenceClassificationRequest = {
  evidence_id: string;
};

export type GetEvidenceClassificationResponse = {
  classification?: EvidenceClassificationRecord;
};

export type EvidenceClassificationRecord = {
  evidence_id: string;
  source_reliability_tier: string;
  evidence_strength_tier: string;
  evidence_modality: string;
  institutional_trust_class: string;
  is_primary_source: boolean;
  is_machine_generated: boolean;
  requires_human_validation: boolean;
  methodology_framework_id: string;
  classification_status: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertAssertionEvidenceLinkRequest = {
  assertion_evidence_link_id: string;
  assertion_id: string;
  evidence_id: string;
  artifact_version_id: string;
  event_id: string;
  memory_decision_id: string;
  support_type: string;
  weight: number;
  note: string;
  evidence_json: string;
};

export type UpsertAssertionEvidenceLinkResponse = {
  evidence_link?: AssertionEvidenceLinkRecord;
};

export type ListAssertionEvidenceLinksRequest = {
  assertion_id: string;
  limit?: number;
  offset?: number;
};

export type ListAssertionEvidenceLinksResponse = {
  evidence_links: AssertionEvidenceLinkRecord[];
};

export type AssertionEvidenceLinkRecord = {
  assertion_evidence_link_id: string;
  assertion_id: string;
  evidence_id: string;
  artifact_version_id: string;
  event_id: string;
  memory_decision_id: string;
  support_type: string;
  weight: number;
  note: string;
  evidence_json: string;
  created_at: string;
};

export type UpsertAssertionRelationRequest = {
  assertion_relation_id: string;
  from_assertion_id: string;
  to_assertion_id: string;
  relation_type: string;
  metadata_json: string;
};

export type UpsertAssertionRelationResponse = {
  relation?: AssertionRelationRecord;
};

export type ListAssertionRelationsRequest = {
  assertion_id: string;
  direction?: string;
  limit?: number;
  offset?: number;
};

export type ListAssertionRelationsResponse = {
  relations: AssertionRelationRecord[];
};

export type AssertionRelationRecord = {
  assertion_relation_id: string;
  from_assertion_id: string;
  to_assertion_id: string;
  relation_type: string;
  metadata_json: string;
  created_at: string;
};

export type CreateArtifactRequest = {
  artifact_type: string;
  name: string;
  description: string;
};

export type CreateArtifactResponse = {
  artifact: ArtifactRecord;
};

export type CreateArtifactVersionRequest = {
  artifact_id: string;
  version_number: number;
  status: string;
  valid_from: string;
  valid_to: string;
  system_from: string;
  content_ref: string;
  content_hash: string;
  author_id: string;
  approver_id: string;
};

export type CreateArtifactVersionResponse = {
  version: ArtifactVersionRecord;
};

export type GetArtifactVersionAsOfRequest = {
  artifact_id: string;
  as_of_valid_time: string;
};

export type GetArtifactVersionAsOfResponse = {
  version?: ArtifactVersionRecord;
};

export type GetArtifactVersionByIdRequest = {
  artifact_version_id: string;
};

export type GetArtifactVersionByIdResponse = {
  version?: ArtifactVersionRecord;
};

export type ArtifactRecord = {
  artifact_id: string;
  artifact_type: string;
  name: string;
  description: string;
  created_at: string;
};

export type ArtifactVersionRecord = {
  artifact_version_id: string;
  artifact_id: string;
  version_number: number;
  status: string;
  valid_from: string;
  valid_to: string;
  system_from: string;
  system_to: string;
  content_ref: string;
  content_hash: string;
  author_id: string;
  approver_id: string;
  created_at: string;
};

export type WriteSnapshotRequest = {
  case_id: string;
  event_seq: number;
  projection_version: string;
  state_blob_json: string;
  state_hash: string;
};

export type WriteSnapshotResponse = {
  snapshot: SnapshotRecord;
};

export type GetLatestSnapshotRequest = {
  case_id: string;
  projection_version: string;
  target_seq: number;
};

export type GetLatestSnapshotResponse = {
  snapshot?: SnapshotRecord;
};

export type SnapshotRecord = {
  snapshot_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  state_blob_json: string;
  state_hash: string;
  created_at: string;
};

export type UpsertEntityRequest = {
  entity_id: string;
  entity_type: string;
  display_name: string;
  external_refs_json: string;
  status: string;
};

export type UpsertEntityResponse = {
  entity: EntityRecord;
};

export type GetEntityRequest = {
  entity_id: string;
};

export type GetEntityResponse = {
  entity?: EntityRecord;
};

export type ListEntitiesRequest = {
  entity_type?: string;
  status?: string;
  query?: string;
  limit?: number;
  offset?: number;
};

export type ListEntitiesResponse = {
  entities: EntityRecord[];
};

export type EntityRecord = {
  entity_id: string;
  entity_type: string;
  display_name: string;
  external_refs_json: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type UpsertPropertyRequest = {
  object_id: string;
  key: string;
  value_json: string;
  valid_from: string;
  system_from?: string;
  source_event_id?: string;
  confidence?: number;
};

export type UpsertPropertyResponse = {
  property: PropertyRecord;
};

export type GetPropertyAsOfRequest = {
  object_id: string;
  key: string;
  as_of_valid_time: string;
  as_of_system_time?: string;
};

export type GetPropertyAsOfResponse = {
  property?: PropertyRecord;
};

export type PropertyRecord = {
  property_state_id: string;
  object_id: string;
  key: string;
  value_json: string;
  valid_from: string;
  valid_to?: string;
  system_from: string;
  system_to?: string;
  source_event_id?: string;
  confidence?: number;
};

export type UpsertEdgeRequest = {
  src_id: string;
  predicate: string;
  dst_id: string;
  valid_from: string;
  system_from?: string;
  source_event_id?: string;
  confidence?: number;
};

export type UpsertEdgeResponse = {
  edge: EdgeRecord;
};

export type GetEdgesAsOfRequest = {
  src_id: string;
  predicate?: string;
  as_of_valid_time: string;
  as_of_system_time?: string;
};

export type GetEdgesAsOfResponse = {
  edges: EdgeRecord[];
};

export type ListPropertyRowsRequest = {
  object_id: string;
  key: string;
  limit?: number;
};

export type ListPropertyRowsResponse = {
  properties: PropertyRecord[];
};

export type EdgeRecord = {
  edge_state_id: string;
  src_id: string;
  predicate: string;
  dst_id: string;
  valid_from: string;
  valid_to?: string;
  system_from: string;
  system_to?: string;
  source_event_id?: string;
  confidence?: number;
};

export type AppendEventRequest = {
  case_id?: string;
  stream_id?: string;
  event_type: string;
  actor_id?: string;
  subject_id?: string;
  object_id?: string;
  payload_json: string;
  event_text?: string;
  embedding?: number[];
  embedding_model?: string;
  valid_time: string;
  system_time?: string;
};

export type AppendEventResponse = {
  event_id: string;
  event_seq: number;
  system_time: string;
};

export type GetEventsRequest = {
  case_id: string;
  from_seq?: number;
  to_seq?: number;
  limit?: number;
};

export type GetEventSentencesRequest = {
  stream_id: string;
  limit?: number;
};

export type EventSentenceRecord = {
  stream_id: string;
  event_id: string;
  sent_index: number;
  start_char: number;
  end_char: number;
  sentence_text: string;
};

export type GetEventSentencesResponse = {
  sentences: EventSentenceRecord[];
};

export type GetEventsResponse = {
  events: EventItem[];
};

export type EventItem = {
  event_id: string;
  case_id: string;
  event_seq: number;
  event_type: string;
  actor_id: string;
  subject_id: string;
  object_id: string;
  payload_json: string;
  valid_time: string;
  system_time: string;
};

export type IndexEventRequest = {
  case_id: string;
  stream_id: string;
  event_id: string;
  event_seq: number;
  content: string;
  metadata_json: string;
  embedding?: number[];
  embedding_model?: string;
};

export type IndexEventResponse = {
  doc_id: string;
  docId?: string;
};

export type GatewayBackendProtoRequest = {
  query: string;
  domain?: string;
  case_id: string;
  stream_id: string;
  stream_ids: string[];
  mode: string;
  limit: number;
  query_embedding: number[];
  alpha: number;
  trace_id: string;
  stream_prefix: boolean;
};

export type DomainStreamBindingRecord = {
  binding_id: string;
  domain: string;
  stream_id: string;
  status: string;
  binding_kind: string;
  source: string;
  priority: number;
  created_at: string;
  updated_at: string;
};

export type DomainStreamBindingUpsertRequest = {
  domain: string;
  stream_id: string;
  status?: string;
  binding_kind?: string;
  source?: string;
  priority?: number;
};

export type DomainStreamBindingListQuery = {
  domain?: string;
  stream_id?: string;
  status?: string;
  limit?: number;
};

export type GatewayBackendProtoHit = {
  doc_id?: string;
  docId?: string;
  case_id?: string;
  caseId?: string;
  stream_id?: string;
  streamId?: string;
  event_id?: string;
  eventId?: string;
  event_seq?: number;
  eventSeq?: number;
  content?: string;
  metadata_json?: string;
  metadataJson?: string;
  lexical_score?: number;
  lexicalScore?: number;
  vector_score?: number;
  vectorScore?: number;
  hybrid_score?: number;
  hybridScore?: number;
};

export type GatewayBackendProtoResponse = {
  hits?: GatewayBackendProtoHit[];
  resolved_stream_ids?: string[];
  resolvedStreamIds?: string[];
};

export type InsertMemoryDecisionRequest = {
  task_id: string;
  run_id?: string;
  decision_text: string;
  rationale_text: string;
  alternatives_considered: string[];
  source_evidence_json: string;
  entity_ids: string[];
  confidence: number;
  author_json: string;
  decision_timestamp?: string;
  consequences: string[];
  metadata_json: string;
  idempotency_key?: string;
};

export type InsertMemoryDecisionResponse = {
  decision: MemoryDecisionRecord;
};

export type ListRecentMemoryDecisionsRequest = {
  task_id: string;
  run_id?: string;
  entity_ids: string[];
  as_of?: string;
  limit: number;
};

export type ListRecentMemoryDecisionsResponse = {
  decisions: MemoryDecisionRecord[];
};

export type InsertMemoryEpisodeSummaryRequest = {
  episode_label?: string;
  task_id?: string;
  run_id?: string;
  session_id?: string;
  summary_text: string;
  outcomes: string[];
  key_facts_json: string;
  decisions: string[];
  unresolved_questions: string[];
  source_evidence_json: string;
  entity_ids: string[];
  confidence: number;
  author_json: string;
  summary_timestamp?: string;
  metadata_json: string;
  idempotency_key?: string;
};

export type InsertMemoryEpisodeSummaryResponse = {
  summary: MemoryEpisodeSummaryRecord;
};

export type ListRecentMemoryEpisodeSummariesRequest = {
  task_id: string;
  run_id?: string;
  as_of?: string;
  limit: number;
};

export type ListRecentMemoryEpisodeSummariesResponse = {
  summaries: MemoryEpisodeSummaryRecord[];
};

export type InsertMemoryAnswerArtifactRequest = {
  domain_id: string;
  intent: string;
  normalized_question: string;
  question_fingerprint_json: string;
  entity_ids: string[];
  answer_text: string;
  answer_payload_json: string;
  source_task_id?: string;
  source_run_id?: string;
  source_decision_id?: string;
  source_episode_summary_id?: string;
  evidence_refs_json: string;
  provenance_json?: string;
  freshness_policy_json: string;
  validation_contract_json: string;
  metadata_json?: string;
  serving_status?: string;
  superseded_by?: string;
  idempotency_key?: string;
};

export type InsertMemoryAnswerArtifactResponse = {
  artifact: MemoryAnswerArtifactRecord;
};

export type RecallMemoryAnswerArtifactsRequest = {
  domain_id: string;
  intent: string;
  question_fingerprint_json: string;
  entity_ids: string[];
  serving_statuses?: string[];
  limit: number;
};

export type RecallMemoryAnswerArtifactsResponse = {
  artifacts: MemoryAnswerArtifactRecord[];
};

export type InsertMemoryAnswerValidationRequest = {
  answer_artifact_id: string;
  validator_type?: string;
  check_spec_json: string;
  observed_values_json: string;
  pass: boolean;
  failure_reason?: string;
  latency_ms?: number;
  metadata_json?: string;
  validated_at?: string;
};

export type InsertMemoryAnswerValidationResponse = {
  validation: MemoryAnswerValidationRecord;
};

export type MemoryDecisionRecord = {
  memory_decision_id: string;
  task_id: string;
  run_id: string;
  decision_text: string;
  rationale_text: string;
  alternatives_considered: string[];
  source_evidence_json: string;
  entity_ids: string[];
  confidence: number;
  author_json: string;
  decision_timestamp: string;
  consequences: string[];
  metadata_json: string;
  idempotency_key: string;
  created_at: string;
};

export type MemoryEpisodeSummaryRecord = {
  episode_summary_id: string;
  episode_label: string;
  task_id: string;
  run_id: string;
  session_id: string;
  summary_text: string;
  outcomes: string[];
  key_facts_json: string;
  decisions: string[];
  unresolved_questions: string[];
  source_evidence_json: string;
  entity_ids: string[];
  confidence: number;
  author_json: string;
  summary_timestamp: string;
  metadata_json: string;
  idempotency_key: string;
  created_at: string;
};

export type MemoryAnswerArtifactRecord = {
  answer_artifact_id: string;
  domain_id: string;
  intent: string;
  normalized_question: string;
  question_fingerprint_json: string;
  entity_ids: string[];
  answer_text: string;
  answer_payload_json: string;
  source_task_id: string;
  source_run_id: string;
  source_decision_id: string;
  source_episode_summary_id: string;
  evidence_refs_json: string;
  provenance_json: string;
  freshness_policy_json: string;
  validation_contract_json: string;
  metadata_json: string;
  serving_status: string;
  superseded_by: string;
  idempotency_key: string;
  created_at: string;
  updated_at: string;
};

export type MemoryAnswerValidationRecord = {
  answer_validation_id: string;
  answer_artifact_id: string;
  validator_type: string;
  check_spec_json: string;
  observed_values_json: string;
  pass: boolean;
  failure_reason: string;
  latency_ms: number;
  metadata_json: string;
  validated_at: string;
};

export type GatewayBackendTransport = {
  searchQuery(
    request: GatewayBackendProtoRequest,
    options?: { timeoutMs?: number }
  ): Promise<GatewayBackendProtoResponse>;
  upsertDomainStreamBinding(
    request: DomainStreamBindingUpsertRequest,
    options?: { timeoutMs?: number }
  ): Promise<{ binding?: DomainStreamBindingRecord }>;
  listDomainStreamBindings(
    request: DomainStreamBindingListQuery,
    options?: { timeoutMs?: number }
  ): Promise<{ bindings?: DomainStreamBindingRecord[] }>;
  indexEvent(
    request: IndexEventRequest,
    options?: { timeoutMs?: number }
  ): Promise<IndexEventResponse>;
  appendEvent(
    request: AppendEventRequest,
    options?: { timeoutMs?: number }
  ): Promise<AppendEventResponse>;
  getEvents(
    request: GetEventsRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEventsResponse>;
  getEventSentences(
    request: GetEventSentencesRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEventSentencesResponse>;
  upsertProperty(
    request: UpsertPropertyRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertPropertyResponse>;
  getPropertyAsOf(
    request: GetPropertyAsOfRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetPropertyAsOfResponse>;
  upsertEdge(
    request: UpsertEdgeRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEdgeResponse>;
  getEdgesAsOf(
    request: GetEdgesAsOfRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEdgesAsOfResponse>;
  listPropertyRows(
    request: ListPropertyRowsRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListPropertyRowsResponse>;
  upsertEntity(
    request: UpsertEntityRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEntityResponse>;
  getEntity(
    request: GetEntityRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEntityResponse>;
  listEntities(
    request: ListEntitiesRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListEntitiesResponse>;
  writeSnapshot(
    request: WriteSnapshotRequest,
    options?: { timeoutMs?: number }
  ): Promise<WriteSnapshotResponse>;
  getLatestSnapshot(
    request: GetLatestSnapshotRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetLatestSnapshotResponse>;
  createArtifact(
    request: CreateArtifactRequest,
    options?: { timeoutMs?: number }
  ): Promise<CreateArtifactResponse>;
  createArtifactVersion(
    request: CreateArtifactVersionRequest,
    options?: { timeoutMs?: number }
  ): Promise<CreateArtifactVersionResponse>;
  getArtifactVersionAsOf(
    request: GetArtifactVersionAsOfRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetArtifactVersionAsOfResponse>;
  getArtifactVersionById(
    request: GetArtifactVersionByIdRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetArtifactVersionByIdResponse>;
  upsertDecision(
    request: UpsertDecisionRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertDecisionResponse>;
  insertDecisionEvidence(
    request: InsertDecisionEvidenceRequest,
    options?: { timeoutMs?: number }
  ): Promise<InsertDecisionEvidenceResponse>;
  findDecision(
    request: FindDecisionRequest,
    options?: { timeoutMs?: number }
  ): Promise<FindDecisionResponse>;
  listDecisionEvidence(
    request: ListDecisionEvidenceRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListDecisionEvidenceResponse>;
  upsertAssertion(
    request: UpsertAssertionRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertAssertionResponse>;
  getAssertion(
    request: GetAssertionRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetAssertionResponse>;
  searchAssertions(
    request: SearchAssertionsRequest,
    options?: { timeoutMs?: number }
  ): Promise<SearchAssertionsResponse>;
  upsertEvidence(
    request: UpsertEvidenceRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEvidenceResponse>;
  getEvidence(
    request: GetEvidenceRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEvidenceResponse>;
  searchEvidence(
    request: SearchEvidenceRequest,
    options?: { timeoutMs?: number }
  ): Promise<SearchEvidenceResponse>;
  upsertEvidenceLocator(
    request: UpsertEvidenceLocatorRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEvidenceLocatorResponse>;
  listEvidenceLocators(
    request: ListEvidenceLocatorsRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListEvidenceLocatorsResponse>;
  upsertEvidenceDerivation(
    request: UpsertEvidenceDerivationRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEvidenceDerivationResponse>;
  listEvidenceDerivations(
    request: ListEvidenceDerivationsRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListEvidenceDerivationsResponse>;
  upsertEvidenceClassification(
    request: UpsertEvidenceClassificationRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertEvidenceClassificationResponse>;
  getEvidenceClassification(
    request: GetEvidenceClassificationRequest,
    options?: { timeoutMs?: number }
  ): Promise<GetEvidenceClassificationResponse>;
  upsertAssertionEvidenceLink(
    request: UpsertAssertionEvidenceLinkRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertAssertionEvidenceLinkResponse>;
  listAssertionEvidenceLinks(
    request: ListAssertionEvidenceLinksRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListAssertionEvidenceLinksResponse>;
  upsertAssertionRelation(
    request: UpsertAssertionRelationRequest,
    options?: { timeoutMs?: number }
  ): Promise<UpsertAssertionRelationResponse>;
  listAssertionRelations(
    request: ListAssertionRelationsRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListAssertionRelationsResponse>;
  insertMemoryDecision(
    request: InsertMemoryDecisionRequest,
    options?: { timeoutMs?: number }
  ): Promise<InsertMemoryDecisionResponse>;
  listRecentMemoryDecisions(
    request: ListRecentMemoryDecisionsRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListRecentMemoryDecisionsResponse>;
  insertMemoryEpisodeSummary(
    request: InsertMemoryEpisodeSummaryRequest,
    options?: { timeoutMs?: number }
  ): Promise<InsertMemoryEpisodeSummaryResponse>;
  listRecentMemoryEpisodeSummaries(
    request: ListRecentMemoryEpisodeSummariesRequest,
    options?: { timeoutMs?: number }
  ): Promise<ListRecentMemoryEpisodeSummariesResponse>;
  insertMemoryAnswerArtifact(
    request: InsertMemoryAnswerArtifactRequest,
    options?: { timeoutMs?: number }
  ): Promise<InsertMemoryAnswerArtifactResponse>;
  recallMemoryAnswerArtifacts(
    request: RecallMemoryAnswerArtifactsRequest,
    options?: { timeoutMs?: number }
  ): Promise<RecallMemoryAnswerArtifactsResponse>;
  insertMemoryAnswerValidation(
    request: InsertMemoryAnswerValidationRequest,
    options?: { timeoutMs?: number }
  ): Promise<InsertMemoryAnswerValidationResponse>;
  upsertOntologyConcept(request: UpsertOntologyConceptRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyConceptResponse>;
  getOntologyConcept(request: GetOntologyConceptRequest, options?: { timeoutMs?: number }): Promise<GetOntologyConceptResponse>;
  listOntologyConcepts(request: ListOntologyConceptsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyConceptsResponse>;
  upsertConceptAlias(request: UpsertConceptAliasRequest, options?: { timeoutMs?: number }): Promise<UpsertConceptAliasResponse>;
  listConceptAliases(request: ListConceptAliasesRequest, options?: { timeoutMs?: number }): Promise<ListConceptAliasesResponse>;
  upsertOntologyEdge(request: UpsertOntologyEdgeRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyEdgeResponse>;
  listOntologyEdges(request: ListOntologyEdgesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyEdgesResponse>;
  upsertEventConceptLink(request: UpsertEventConceptLinkRequest, options?: { timeoutMs?: number }): Promise<UpsertEventConceptLinkResponse>;
  listEventConceptLinks(request: ListEventConceptLinksRequest, options?: { timeoutMs?: number }): Promise<ListEventConceptLinksResponse>;
  upsertOntologyObjectType(request: UpsertOntologyObjectTypeRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyObjectTypeResponse>;
  getOntologyObjectType(request: GetOntologyObjectTypeRequest, options?: { timeoutMs?: number }): Promise<GetOntologyObjectTypeResponse>;
  listOntologyObjectTypes(request: ListOntologyObjectTypesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyObjectTypesResponse>;
  upsertOntologyConceptTypeAssignment(request: UpsertOntologyConceptTypeAssignmentRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyConceptTypeAssignmentResponse>;
  listOntologyConceptTypeAssignments(request: ListOntologyConceptTypeAssignmentsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyConceptTypeAssignmentsResponse>;
  upsertOntologyRelationType(request: UpsertOntologyRelationTypeRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyRelationTypeResponse>;
  getOntologyRelationType(request: GetOntologyRelationTypeRequest, options?: { timeoutMs?: number }): Promise<GetOntologyRelationTypeResponse>;
  listOntologyRelationTypes(request: ListOntologyRelationTypesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyRelationTypesResponse>;
  listOntologyFacts(request: ListOntologyFactsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactsResponse>;
  upsertOntologyFactWithEvidence(request: UpsertOntologyFactWithEvidenceRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyFactWithEvidenceResponse>;
  upsertSemanticBatch(request: UpsertSemanticBatchRequest, options?: { timeoutMs?: number }): Promise<UpsertSemanticBatchResponse>;
  getSemanticStatement(request: GetSemanticStatementRequest, options?: { timeoutMs?: number }): Promise<GetSemanticStatementResponse>;
  listSemanticStatements(request: ListSemanticStatementsRequest, options?: { timeoutMs?: number }): Promise<ListSemanticStatementsResponse>;
  setSemanticStatementStatus(request: SetSemanticStatementStatusRequest, options?: { timeoutMs?: number }): Promise<SetSemanticStatementStatusResponse>;
  getSemanticStatementProvenance(request: GetSemanticStatementProvenanceRequest, options?: { timeoutMs?: number }): Promise<GetSemanticStatementProvenanceResponse>;
  getSemanticStatementsByEvidence(request: GetSemanticStatementsByEvidenceRequest, options?: { timeoutMs?: number }): Promise<GetSemanticStatementsByEvidenceResponse>;
  searchOntologyConcepts(request: SearchOntologyConceptsRequest, options?: { timeoutMs?: number }): Promise<SearchOntologyConceptsResponse>;
  searchConceptAliases(request: SearchConceptAliasesRequest, options?: { timeoutMs?: number }): Promise<SearchConceptAliasesResponse>;
  searchOntologyFacts(request: SearchOntologyFactsRequest, options?: { timeoutMs?: number }): Promise<SearchOntologyFactsResponse>;
  getOntologyConceptNeighbors(request: GetOntologyConceptNeighborsRequest, options?: { timeoutMs?: number }): Promise<GetOntologyConceptNeighborsResponse>;
  archiveOntologyFact(request: ArchiveOntologyFactRequest, options?: { timeoutMs?: number }): Promise<ArchiveOntologyFactResponse>;
  upsertTermMappingRegistry(request: UpsertTermMappingRegistryRequest, options?: { timeoutMs?: number }): Promise<UpsertTermMappingRegistryResponse>;
  getTermMappingRegistry(request: GetTermMappingRegistryRequest, options?: { timeoutMs?: number }): Promise<GetTermMappingRegistryResponse>;
  listTermMappingRegistries(request: ListTermMappingRegistriesRequest, options?: { timeoutMs?: number }): Promise<ListTermMappingRegistriesResponse>;
  upsertOntologyNormalizedTerm(request: UpsertOntologyNormalizedTermRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyNormalizedTermResponse>;
  getOntologyNormalizedTerm(request: GetOntologyNormalizedTermRequest, options?: { timeoutMs?: number }): Promise<GetOntologyNormalizedTermResponse>;
  searchOntologyNormalizedTerms(request: SearchOntologyNormalizedTermsRequest, options?: { timeoutMs?: number }): Promise<SearchOntologyNormalizedTermsResponse>;
  upsertOntologyTermCluster(request: UpsertOntologyTermClusterRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyTermClusterResponse>;
  getOntologyTermCluster(request: GetOntologyTermClusterRequest, options?: { timeoutMs?: number }): Promise<GetOntologyTermClusterResponse>;
  listOntologyTermClusters(request: ListOntologyTermClustersRequest, options?: { timeoutMs?: number }): Promise<ListOntologyTermClustersResponse>;
  upsertOntologyClusterMember(request: UpsertOntologyClusterMemberRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyClusterMemberResponse>;
  listOntologyClusterMembers(request: ListOntologyClusterMembersRequest, options?: { timeoutMs?: number }): Promise<ListOntologyClusterMembersResponse>;
  upsertOntologyRelationCandidate(request: UpsertOntologyRelationCandidateRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyRelationCandidateResponse>;
  listOntologyRelationCandidates(request: ListOntologyRelationCandidatesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyRelationCandidatesResponse>;
  upsertOntologyRawTerm(request: UpsertOntologyRawTermRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyRawTermResponse>;
  getOntologyRawTerm(request: GetOntologyRawTermRequest, options?: { timeoutMs?: number }): Promise<GetOntologyRawTermResponse>;
  searchOntologyRawTerms(request: SearchOntologyRawTermsRequest, options?: { timeoutMs?: number }): Promise<SearchOntologyRawTermsResponse>;
  upsertOntologyRawTermCandidate(request: UpsertOntologyRawTermCandidateRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyRawTermCandidateResponse>;
  listOntologyRawTermCandidates(request: ListOntologyRawTermCandidatesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyRawTermCandidatesResponse>;
  upsertOntologyRawTermNormalization(request: UpsertOntologyRawTermNormalizationRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyRawTermNormalizationResponse>;
  listOntologyRawTermNormalizations(request: ListOntologyRawTermNormalizationsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyRawTermNormalizationsResponse>;
  upsertTermMappingRule(request: UpsertTermMappingRuleRequest, options?: { timeoutMs?: number }): Promise<UpsertTermMappingRuleResponse>;
  getTermMappingRule(request: GetTermMappingRuleRequest, options?: { timeoutMs?: number }): Promise<GetTermMappingRuleResponse>;
  searchTermMappingRules(request: SearchTermMappingRulesRequest, options?: { timeoutMs?: number }): Promise<SearchTermMappingRulesResponse>;
  upsertTermMappingRuleEvidence(request: UpsertTermMappingRuleEvidenceRequest, options?: { timeoutMs?: number }): Promise<UpsertTermMappingRuleEvidenceResponse>;
  listTermMappingRuleEvidence(request: ListTermMappingRuleEvidenceRequest, options?: { timeoutMs?: number }): Promise<ListTermMappingRuleEvidenceResponse>;
  interpretTerm(request: InterpretTermRequest, options?: { timeoutMs?: number }): Promise<InterpretTermResponse>;
  interpretTermBatch(request: InterpretTermBatchRequest, options?: { timeoutMs?: number }): Promise<InterpretTermBatchResponse>;

  // Governance
  upsertRule(request: UpsertRuleRequest, options?: { timeoutMs?: number }): Promise<UpsertRuleResponse>;
  insertAuthorityGrant(request: InsertAuthorityGrantRequest, options?: { timeoutMs?: number }): Promise<InsertAuthorityGrantResponse>;
  insertRuleOverride(request: InsertRuleOverrideRequest, options?: { timeoutMs?: number }): Promise<InsertRuleOverrideResponse>;
  findAuthorityAsOf(request: FindAuthorityAsOfRequest, options?: { timeoutMs?: number }): Promise<FindAuthorityAsOfResponse>;
  listRuleOverridesAsOf(request: ListRuleOverridesAsOfRequest, options?: { timeoutMs?: number }): Promise<ListRuleOverridesAsOfResponse>;
  upsertMethodologyFramework(request: UpsertMethodologyFrameworkRequest, options?: { timeoutMs?: number }): Promise<UpsertMethodologyFrameworkResponse>;
  getMethodologyFramework(request: GetMethodologyFrameworkRequest, options?: { timeoutMs?: number }): Promise<GetMethodologyFrameworkResponse>;
  listMethodologyFrameworks(request: ListMethodologyFrameworksRequest, options?: { timeoutMs?: number }): Promise<ListMethodologyFrameworksResponse>;
  getMethodologyFrameworkBundle(request: GetMethodologyFrameworkBundleRequest, options?: { timeoutMs?: number }): Promise<GetMethodologyFrameworkBundleResponse>;
  upsertTaxonomyScheme(request: UpsertTaxonomySchemeRequest, options?: { timeoutMs?: number }): Promise<UpsertTaxonomySchemeResponse>;
  getTaxonomyScheme(request: GetTaxonomySchemeRequest, options?: { timeoutMs?: number }): Promise<GetTaxonomySchemeResponse>;
  listTaxonomySchemes(request: ListTaxonomySchemesRequest, options?: { timeoutMs?: number }): Promise<ListTaxonomySchemesResponse>;
  upsertEvidencePolicyRule(request: UpsertEvidencePolicyRuleRequest, options?: { timeoutMs?: number }): Promise<UpsertEvidencePolicyRuleResponse>;
  getEvidencePolicyRule(request: GetEvidencePolicyRuleRequest, options?: { timeoutMs?: number }): Promise<GetEvidencePolicyRuleResponse>;
  listEvidencePolicyRules(request: ListEvidencePolicyRulesRequest, options?: { timeoutMs?: number }): Promise<ListEvidencePolicyRulesResponse>;
  upsertAssertionPolicyRule(request: UpsertAssertionPolicyRuleRequest, options?: { timeoutMs?: number }): Promise<UpsertAssertionPolicyRuleResponse>;
  getAssertionPolicyRule(request: GetAssertionPolicyRuleRequest, options?: { timeoutMs?: number }): Promise<GetAssertionPolicyRuleResponse>;
  listAssertionPolicyRules(request: ListAssertionPolicyRulesRequest, options?: { timeoutMs?: number }): Promise<ListAssertionPolicyRulesResponse>;
  upsertReviewPolicy(request: UpsertReviewPolicyRequest, options?: { timeoutMs?: number }): Promise<UpsertReviewPolicyResponse>;
  getReviewPolicy(request: GetReviewPolicyRequest, options?: { timeoutMs?: number }): Promise<GetReviewPolicyResponse>;
  listReviewPolicies(request: ListReviewPoliciesRequest, options?: { timeoutMs?: number }): Promise<ListReviewPoliciesResponse>;

  // Ontology Fact
  reviewOntologyFact(request: ReviewOntologyFactRequest, options?: { timeoutMs?: number }): Promise<ReviewOntologyFactResponse>;
  getOntologyFact(request: GetOntologyFactRequest, options?: { timeoutMs?: number }): Promise<GetOntologyFactResponse>;
  listOntologyFactReviews(request: ListOntologyFactReviewsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactReviewsResponse>;
  listOntologyFactEvidence(request: ListOntologyFactEvidenceRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactEvidenceResponse>;
  listOntologyFactLinkedCases(request: ListOntologyFactLinkedCasesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactLinkedCasesResponse>;
  listOntologyFactLinkedAlerts(request: ListOntologyFactLinkedAlertsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactLinkedAlertsResponse>;
  selectOntologyFactsForBulkReview(request: SelectOntologyFactsForBulkReviewRequest, options?: { timeoutMs?: number }): Promise<SelectOntologyFactsForBulkReviewResponse>;

  // Ontology Case
  // Ontology Case
  insertOntologyCase(request: InsertOntologyCaseRequest, options?: { timeoutMs?: number }): Promise<InsertOntologyCaseResponse>;
  getOntologyCase(request: GetOntologyCaseRequest, options?: { timeoutMs?: number }): Promise<GetOntologyCaseResponse>;
  listOntologyCases(request: ListOntologyCasesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyCasesResponse>;
  updateOntologyCase(request: UpdateOntologyCaseRequest, options?: { timeoutMs?: number }): Promise<UpdateOntologyCaseResponse>;
  linkOntologyCaseFact(request: LinkOntologyCaseFactRequest, options?: { timeoutMs?: number }): Promise<LinkOntologyCaseFactResponse>;
  listOntologyCaseFacts(request: ListOntologyCaseFactsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyCaseFactsResponse>;
  insertOntologyCaseDecision(request: InsertOntologyCaseDecisionRequest, options?: { timeoutMs?: number }): Promise<InsertOntologyCaseDecisionResponse>;
  listOntologyCaseDecisions(request: ListOntologyCaseDecisionsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyCaseDecisionsResponse>;
  insertOntologyCaseEvent(request: InsertOntologyCaseEventRequest, options?: { timeoutMs?: number }): Promise<InsertOntologyCaseEventResponse>;
  listOntologyCaseEvents(request: ListOntologyCaseEventsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyCaseEventsResponse>;

  // Ontology Alert
  insertOntologyAlert(request: InsertOntologyAlertRequest, options?: { timeoutMs?: number }): Promise<InsertOntologyAlertResponse>;
  getOntologyAlertDetail(request: GetOntologyAlertDetailRequest, options?: { timeoutMs?: number }): Promise<GetOntologyAlertDetailResponse>;
  listOntologyAlerts(request: ListOntologyAlertsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyAlertsResponse>;
  updateOntologyAlert(request: UpdateOntologyAlertRequest, options?: { timeoutMs?: number }): Promise<UpdateOntologyAlertResponse>;
  refreshTriggeredOntologyAlert(request: RefreshTriggeredOntologyAlertRequest, options?: { timeoutMs?: number }): Promise<RefreshTriggeredOntologyAlertResponse>;

  // Ontology Ops
  upsertOntologyOpsRuleConfig(request: UpsertOntologyOpsRuleConfigRequest, options?: { timeoutMs?: number }): Promise<UpsertOntologyOpsRuleConfigResponse>;
  listOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest, options?: { timeoutMs?: number }): Promise<ListOntologyOpsRuleConfigResponse>;
  insertOntologyOpsRuleRun(request: InsertOntologyOpsRuleRunRequest, options?: { timeoutMs?: number }): Promise<InsertOntologyOpsRuleRunResponse>;
  getOntologyOpsRun(request: GetOntologyOpsRunRequest, options?: { timeoutMs?: number }): Promise<GetOntologyOpsRunResponse>;
  listOntologyOpsRuns(request: ListOntologyOpsRunsRequest, options?: { timeoutMs?: number }): Promise<ListOntologyOpsRunsResponse>;
  listApplicableOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest, options?: { timeoutMs?: number }): Promise<ListOntologyOpsRuleConfigResponse>;
  listStalePendingOntologyCandidates(request: ListStalePendingOntologyCandidatesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactsResponse>;
  listConflictPredicateOntologyCandidates(request: ListConflictPredicateOntologyCandidatesRequest, options?: { timeoutMs?: number }): Promise<ListOntologyFactsResponse>;
  getActiveOntologyCaseByTitle(request: GetActiveOntologyCaseByTitleRequest, options?: { timeoutMs?: number }): Promise<GetActiveOntologyCaseByTitleResponse>;
  getActiveOntologyAlertByRuleKey(request: GetActiveOntologyAlertByRuleKeyRequest, options?: { timeoutMs?: number }): Promise<GetActiveOntologyAlertByRuleKeyResponse>;
  linkOntologyAlertFact(request: LinkOntologyAlertFactRequest, options?: { timeoutMs?: number }): Promise<Empty>;
  // Wiki
  upsertWikiPage(request: UpsertWikiPageRequest, options?: { timeoutMs?: number }): Promise<UpsertWikiPageResponse>;
  upsertWikiPageLink(request: UpsertWikiPageLinkRequest, options?: { timeoutMs?: number }): Promise<UpsertWikiPageLinkResponse>;
  getWikiPage(request: GetWikiPageRequest, options?: { timeoutMs?: number }): Promise<GetWikiPageResponse>;
  searchWikiPages(request: SearchWikiPagesRequest, options?: { timeoutMs?: number }): Promise<SearchWikiPagesResponse>;
  listWikiPages(request: ListWikiPagesRequest, options?: { timeoutMs?: number }): Promise<ListWikiPagesResponse>;
  reinforceWikiPage(request: ReinforceWikiPageRequest, options?: { timeoutMs?: number }): Promise<ReinforceWikiPageResponse>;
  appendWikiLog(request: AppendWikiLogRequest, options?: { timeoutMs?: number }): Promise<AppendWikiLogResponse>;
  listWikiLogs(request: ListWikiLogsRequest, options?: { timeoutMs?: number }): Promise<ListWikiLogsResponse>;
  lintWikiDomain(request: LintWikiDomainRequest, options?: { timeoutMs?: number }): Promise<LintWikiDomainResponse>;
  close?(): void;
};

export type UpsertOntologyConceptRequest = {
  concept_id: string;
  canonical_name: string;
  concept_type: string;
  aliases_json: string;
};

export type UpsertOntologyConceptResponse = { concept?: OntologyConceptRecord };
export type GetOntologyConceptRequest = { concept_id: string };
export type GetOntologyConceptResponse = { concept?: OntologyConceptRecord };
export type ListOntologyConceptsRequest = {
  concept_type?: string;
  query?: string;
  limit: number;
  offset: number;
};
export type ListOntologyConceptsResponse = { concepts: OntologyConceptRecord[] };
export type OntologyConceptRecord = {
  concept_id: string;
  canonical_name: string;
  concept_type: string;
  aliases_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertConceptAliasRequest = {
  concept_id: string;
  alias_text: string;
  confidence: number;
  extractor: string;
};
export type UpsertConceptAliasResponse = { alias?: ConceptAliasRecord };
export type ListConceptAliasesRequest = {
  concept_id?: string;
  query?: string;
  limit: number;
  offset: number;
};
export type ListConceptAliasesResponse = { aliases: ConceptAliasRecord[] };
export type ConceptAliasRecord = {
  concept_id: string;
  alias_text: string;
  confidence: number;
  extractor: string;
  created_at: string;
  updated_at: string;
};

export type UpsertOntologyEdgeRequest = {
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  weight: number;
};
export type UpsertOntologyEdgeResponse = { edge?: OntologyEdgeRecord };
export type ListOntologyEdgesRequest = {
  src_concept_id?: string;
  predicate?: string;
  dst_concept_id?: string;
  limit: number;
};
export type ListOntologyEdgesResponse = { edges: OntologyEdgeRecord[] };
export type OntologyEdgeRecord = {
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  weight: number;
  created_at: string;
};

export type UpsertEventConceptLinkRequest = {
  stream_id: string;
  event_id: string;
  concept_id: string;
  role: string;
  confidence: number;
  asset_id?: string;
  version_number?: number;
  extractor: string;
  source_span?: string;
  evidence_json: string;
};
export type UpsertEventConceptLinkResponse = { link?: EventConceptLinkRecord };
export type ListEventConceptLinksRequest = {
  stream_id?: string;
  event_id?: string;
  concept_id?: string;
  role?: string;
  limit: number;
};
export type ListEventConceptLinksResponse = { links: EventConceptLinkRecord[] };
export type EventConceptLinkRecord = {
  stream_id: string;
  event_id: string;
  concept_id: string;
  role: string;
  confidence: number;
  asset_id: string;
  version_number: number;
  extractor: string;
  source_span: string;
  evidence_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertOntologyObjectTypeRequest = {
  type_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
};
export type UpsertOntologyObjectTypeResponse = { object_type?: OntologyObjectTypeRecord };
export type GetOntologyObjectTypeRequest = { type_id: string };
export type GetOntologyObjectTypeResponse = { object_type?: OntologyObjectTypeRecord };
export type ListOntologyObjectTypesRequest = {
  enabled_only: boolean;
  query?: string;
  limit: number;
  offset: number;
};
export type ListOntologyObjectTypesResponse = { object_types: OntologyObjectTypeRecord[] };
export type OntologyObjectTypeRecord = {
  type_id: string;
  display_name: string;
  description: string;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type UpsertOntologyConceptTypeAssignmentRequest = {
  assignment_id: string;
  domain: string;
  concept_id: string;
  object_type_id: string;
  assignment_status: string;
  source_kind: string;
  confidence: number;
  metadata_json: string;
};
export type UpsertOntologyConceptTypeAssignmentResponse = { assignment?: OntologyConceptTypeAssignmentRecord };
export type ListOntologyConceptTypeAssignmentsRequest = {
  domain?: string;
  concept_id?: string;
  object_type_id?: string;
  assignment_status?: string;
  limit: number;
  offset: number;
};
export type ListOntologyConceptTypeAssignmentsResponse = { assignments: OntologyConceptTypeAssignmentRecord[] };
export type OntologyConceptTypeAssignmentRecord = {
  assignment_id: string;
  domain: string;
  concept_id: string;
  object_type_id: string;
  assignment_status: string;
  source_kind: string;
  confidence: number;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertOntologyRelationTypeRequest = {
  predicate: string;
  src_type_id: string;
  dst_type_id: string;
  display_name: string;
  description: string;
  is_symmetric: boolean;
  is_transitive: boolean;
  enabled: boolean;
};
export type UpsertOntologyRelationTypeResponse = { relation_type?: OntologyRelationTypeRecord };
export type GetOntologyRelationTypeRequest = { predicate: string };
export type GetOntologyRelationTypeResponse = { relation_type?: OntologyRelationTypeRecord };
export type ListOntologyRelationTypesRequest = {
  src_type_id?: string;
  dst_type_id?: string;
  enabled_only: boolean;
  query?: string;
  limit: number;
  offset: number;
};
export type ListOntologyRelationTypesResponse = { relation_types: OntologyRelationTypeRecord[] };
export type OntologyRelationTypeRecord = {
  predicate: string;
  src_type_id: string;
  dst_type_id: string;
  display_name: string;
  description: string;
  is_symmetric: boolean;
  is_transitive: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type ListOntologyFactsRequest = {
  status?: string;
  stream_id?: string;
  stream_prefix?: boolean;
  predicate?: string;
  extractor?: string;
  src_concept_id?: string;
  dst_concept_id?: string;
  limit: number;
  offset: number;
};
export type OntologyFactEvidenceWrite = {
  stream_id: string;
  event_id: string;
  asset_id?: string;
  version_number?: number;
  source_span?: string;
  evidence_json: string;
  confidence?: number;
};
export type UpsertOntologyFactWithEvidenceRequest = {
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  qualifier_json: string;
  confidence: number;
  extractor: string;
  status: string;
  review_note: string;
  evidence: OntologyFactEvidenceWrite[];
  valid_from?: string;
  valid_to?: string;
};
export type UpsertOntologyFactWithEvidenceResponse = { fact?: OntologyFactRecord; evidence_count: number };
export type SemanticEntityWrite = {
  entity_id: string;
  entity_kind: string;
  semantic_role: string;
  namespace: string;
  status: string;
  property_datatype?: string;
  metadata_json: string;
};
export type SemanticStatementWrite = {
  statement_key: string;
  subject_id: string;
  property_id: string;
  value_type: string;
  value_entity_id?: string;
  value_json: string;
  status: string;
  confidence: number;
  created_by: string;
  metadata_json: string;
};
export type StatementQualifierWrite = {
  statement_key: string;
  property_id: string;
  value_type: string;
  value_json: string;
  value_entity_id?: string;
  ordinal: number;
};
export type StatementReferenceWrite = {
  statement_key: string;
  property_id: string;
  value_type: string;
  value_json: string;
  evidence_id?: string;
  source_span?: string;
  ordinal: number;
};
export type UpsertSemanticBatchRequest = {
  entities: SemanticEntityWrite[];
  statements: SemanticStatementWrite[];
  qualifiers: StatementQualifierWrite[];
  references: StatementReferenceWrite[];
};
export type UpsertSemanticBatchResponse = {
  semantic_entity_count: number;
  semantic_statement_count: number;
  statement_qualifier_count: number;
  statement_reference_count: number;
};
export type GetSemanticStatementRequest = {
  statement_id: string;
};
export type SemanticStatementRecord = {
  statement_id: string;
  subject_concept_id: string;
  subject_name: string;
  predicate: string;
  object_concept_id: string;
  object_name: string;
  value_type: string;
  value_json: string;
  status: string;
  confidence: number;
  created_by: string;
  metadata_json: string;
  provenance_json: string;
  created_at: string;
  updated_at: string;
};
export type SemanticStatementQualifierRecord = {
  statement_id: string;
  property_id: string;
  value_type: string;
  value_json: string;
  value_entity_id: string;
  ordinal: number;
};
export type GetSemanticStatementResponse = {
  statement?: SemanticStatementRecord;
  qualifiers: SemanticStatementQualifierRecord[];
};
export type ListSemanticStatementsRequest = {
  subject_id: string;
  property_id: string;
  value_entity_id: string;
  status: string;
  limit: number;
  offset: number;
};
export type SemanticStatementWithQualifiers = {
  statement?: SemanticStatementRecord;
  qualifiers: SemanticStatementQualifierRecord[];
};
export type ListSemanticStatementsResponse = {
  statements: SemanticStatementWithQualifiers[];
};
export type SetSemanticStatementStatusRequest = {
  statement_id: string;
  status: string;
  note: string;
};
export type SetSemanticStatementStatusResponse = {
  updated_rows: number;
};
export type SemanticStatementReferenceRecord = {
  statement_id: string;
  property_id: string;
  value_type: string;
  value_json: string;
  source_span: string;
  evidence_id: string;
  ordinal: number;
  evidence?: EvidenceRecord;
  locators?: EvidenceLocatorRecord[];
};
export type GetSemanticStatementProvenanceRequest = {
  statement_id: string;
  include_locators?: boolean;
  evidence_limit?: number;
};
export type GetSemanticStatementProvenanceResponse = {
  references: SemanticStatementReferenceRecord[];
};
export type GetSemanticStatementsByEvidenceRequest = {
  evidence_id: string;
  include_locators?: boolean;
  limit?: number;
};
export type GetSemanticStatementsByEvidenceResponse = {
  references: SemanticStatementReferenceRecord[];
};
export type SearchOntologyConceptsRequest = { query?: string; concept_type?: string; domain?: string; limit: number; offset: number };
export type SearchOntologyConceptsResponse = { concepts: OntologyConceptRecord[] };
export type SearchConceptAliasesRequest = { query?: string; concept_id?: string; limit: number; offset: number };
export type SearchConceptAliasesResponse = { aliases: ConceptAliasRecord[] };
export type SearchOntologyFactsRequest = {
  query?: string;
  status?: string;
  stream_id?: string;
  stream_prefix?: boolean;
  predicate?: string;
  extractor?: string;
  src_concept_id?: string;
  dst_concept_id?: string;
  limit: number;
  offset: number;
};
export type SearchOntologyFactsResponse = { facts: OntologyFactRecord[] };
export type GetOntologyConceptNeighborsRequest = { concept_id: string; direction: string; predicate?: string; limit: number };
export type OntologyNeighborRecord = {
  fact_id: number;
  predicate: string;
  direction: string;
  neighbor_concept_id: string;
  neighbor_canonical_name: string;
  neighbor_concept_type: string;
  status: string;
  confidence: number;
};
export type GetOntologyConceptNeighborsResponse = { neighbors: OntologyNeighborRecord[] };
export type ArchiveOntologyFactRequest = { fact_id: number; reviewer: string; note: string };
export type ArchiveOntologyFactResponse = { updated_rows: number };
export type UpsertTermMappingRegistryRequest = {
  domain: string;
  registry_name: string;
  version_label: string;
  status: string;
  description: string;
  owner: string;
  metadata_json: string;
};
export type UpsertTermMappingRegistryResponse = { registry?: TermMappingRegistryRecord };
export type GetTermMappingRegistryRequest = { registry_id: string };
export type GetTermMappingRegistryResponse = { registry?: TermMappingRegistryRecord };
export type ListTermMappingRegistriesRequest = { domain?: string; status?: string; query?: string; limit: number; offset: number };
export type ListTermMappingRegistriesResponse = { registries: TermMappingRegistryRecord[] };
export type TermMappingRegistryRecord = {
  registry_id: string;
  domain: string;
  registry_name: string;
  version_label: string;
  status: string;
  description: string;
  owner: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyNormalizedTermRequest = {
  normalized_term_id: string;
  domain: string;
  normalized_surface: string;
  normalized_type: string;
  merge_key: string;
  type_confidence: number;
  head_term: string;
  modifier_terms_json: string;
  canonical_candidate_label: string;
  canonical_candidate_concept_id: string;
  primary_cluster_id: string;
  source_support_count: number;
  is_promotable: boolean;
  normalization_status: string;
  metadata_json: string;
};
export type UpsertOntologyNormalizedTermResponse = { normalized_term?: OntologyNormalizedTermRecord };
export type GetOntologyNormalizedTermRequest = { normalized_term_id: string };
export type GetOntologyNormalizedTermResponse = { normalized_term?: OntologyNormalizedTermRecord };
export type SearchOntologyNormalizedTermsRequest = {
  domain?: string;
  normalized_surface?: string;
  query?: string;
  normalized_type?: string;
  normalization_status?: string;
  primary_cluster_id?: string;
  promotable_only: boolean;
  limit: number;
  offset: number;
};
export type SearchOntologyNormalizedTermsResponse = { normalized_terms: OntologyNormalizedTermRecord[] };
export type OntologyNormalizedTermRecord = {
  normalized_term_id: string;
  domain: string;
  normalized_surface: string;
  normalized_type: string;
  merge_key: string;
  type_confidence: number;
  head_term: string;
  modifier_terms_json: string;
  canonical_candidate_label: string;
  canonical_candidate_concept_id: string;
  primary_cluster_id: string;
  source_support_count: number;
  is_promotable: boolean;
  normalization_status: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyTermClusterRequest = {
  cluster_id: string;
  domain: string;
  cluster_type: string;
  proposed_canonical: string;
  proposed_type: string;
  cluster_status: string;
  member_count: number;
  source_support_count: number;
  confidence: number;
  metadata_json: string;
};
export type UpsertOntologyTermClusterResponse = { cluster?: OntologyTermClusterRecord };
export type GetOntologyTermClusterRequest = { cluster_id: string };
export type GetOntologyTermClusterResponse = { cluster?: OntologyTermClusterRecord };
export type ListOntologyTermClustersRequest = {
  domain?: string;
  cluster_type?: string;
  cluster_status?: string;
  proposed_type?: string;
  limit: number;
  offset: number;
};
export type ListOntologyTermClustersResponse = { clusters: OntologyTermClusterRecord[] };
export type OntologyTermClusterRecord = {
  cluster_id: string;
  domain: string;
  cluster_type: string;
  proposed_canonical: string;
  proposed_type: string;
  cluster_status: string;
  member_count: number;
  source_support_count: number;
  confidence: number;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyClusterMemberRequest = {
  cluster_member_id: string;
  cluster_id: string;
  normalized_term_id: string;
  member_role: string;
  membership_confidence: number;
  added_by: string;
  note: string;
};
export type UpsertOntologyClusterMemberResponse = { member?: OntologyClusterMemberRecord };
export type ListOntologyClusterMembersRequest = {
  cluster_id?: string;
  normalized_term_id?: string;
  limit: number;
  offset: number;
};
export type ListOntologyClusterMembersResponse = { members: OntologyClusterMemberRecord[] };
export type OntologyClusterMemberRecord = {
  cluster_member_id: string;
  cluster_id: string;
  normalized_term_id: string;
  member_role: string;
  membership_confidence: number;
  added_by: string;
  note: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyRelationCandidateRequest = {
  relation_candidate_id: string;
  domain: string;
  subject_label: string;
  relation_type: string;
  object_label: string;
  subject_concept_id: string;
  object_concept_id: string;
  candidate_status: string;
  source_kind: string;
  source_cluster_id: string;
  confidence: number;
  metadata_json: string;
};
export type UpsertOntologyRelationCandidateResponse = { relation_candidate?: OntologyRelationCandidateRecord };
export type ListOntologyRelationCandidatesRequest = {
  domain?: string;
  relation_type?: string;
  candidate_status?: string;
  subject_label?: string;
  object_label?: string;
  source_kind?: string;
  limit: number;
  offset: number;
};
export type ListOntologyRelationCandidatesResponse = { relation_candidates: OntologyRelationCandidateRecord[] };
export type OntologyRelationCandidateRecord = {
  relation_candidate_id: string;
  domain: string;
  subject_label: string;
  relation_type: string;
  object_label: string;
  subject_concept_id: string;
  object_concept_id: string;
  candidate_status: string;
  source_kind: string;
  source_cluster_id: string;
  confidence: number;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyRawTermRequest = {
  raw_term_id: string;
  domain: string;
  raw_term: string;
  language: string;
  normalized_hint: string;
  term_type_hint: string;
  source_kind: string;
  source_ref: string;
  artifact_version_id: string;
  evidence_id: string;
  context_text: string;
  context_locator_json: string;
  extracted_by_type: string;
  extracted_by_id: string;
  status: string;
  metadata_json: string;
};
export type UpsertOntologyRawTermResponse = { raw_term?: OntologyRawTermRecord };
export type GetOntologyRawTermRequest = { raw_term_id: string };
export type GetOntologyRawTermResponse = { raw_term?: OntologyRawTermRecord };
export type SearchOntologyRawTermsRequest = {
  domain?: string;
  raw_term?: string;
  query?: string;
  language?: string;
  status?: string;
  term_type_hint?: string;
  limit: number;
  offset: number;
};
export type SearchOntologyRawTermsResponse = { raw_terms: OntologyRawTermRecord[] };
export type OntologyRawTermRecord = {
  raw_term_id: string;
  domain: string;
  raw_term: string;
  language: string;
  normalized_hint: string;
  term_type_hint: string;
  source_kind: string;
  source_ref: string;
  artifact_version_id: string;
  evidence_id: string;
  context_text: string;
  context_locator_json: string;
  extracted_by_type: string;
  extracted_by_id: string;
  status: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyRawTermCandidateRequest = {
  candidate_id: string;
  raw_term_id: string;
  candidate_label: string;
  candidate_concept_id: string;
  candidate_object_type: string;
  candidate_relation_type: string;
  confidence: number;
  candidate_status: string;
  review_note: string;
  metadata_json: string;
};
export type UpsertOntologyRawTermCandidateResponse = { candidate?: OntologyRawTermCandidateRecord };
export type ListOntologyRawTermCandidatesRequest = {
  raw_term_id: string;
  candidate_status?: string;
  limit: number;
  offset: number;
};
export type ListOntologyRawTermCandidatesResponse = { candidates: OntologyRawTermCandidateRecord[] };
export type OntologyRawTermCandidateRecord = {
  candidate_id: string;
  raw_term_id: string;
  candidate_label: string;
  candidate_concept_id: string;
  candidate_object_type: string;
  candidate_relation_type: string;
  confidence: number;
  candidate_status: string;
  review_note: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertOntologyRawTermNormalizationRequest = {
  mapping_id: string;
  raw_term_id: string;
  normalized_term_id: string;
  mapping_confidence: number;
  mapping_type: string;
  mapping_status: string;
  component_role: string;
  normalization_rule: string;
  note: string;
  metadata_json: string;
};
export type UpsertOntologyRawTermNormalizationResponse = { mapping?: OntologyRawTermNormalizationRecord };
export type ListOntologyRawTermNormalizationsRequest = {
  raw_term_id?: string;
  normalized_term_id?: string;
  mapping_status?: string;
  limit: number;
  offset: number;
};
export type ListOntologyRawTermNormalizationsResponse = { mappings: OntologyRawTermNormalizationRecord[] };
export type OntologyRawTermNormalizationRecord = {
  mapping_id: string;
  raw_term_id: string;
  normalized_term_id: string;
  mapping_confidence: number;
  mapping_type: string;
  mapping_status: string;
  component_role: string;
  normalization_rule: string;
  note: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertTermMappingRuleRequest = {
  rule_id: string;
  registry_id: string;
  raw_term: string;
  language: string;
  context_hint: string;
  term_type: string;
  normalization_status: string;
  canonical_term: string;
  canonical_concept_id: string;
  is_compound: boolean;
  split_rule_json: string;
  semantic_slot: string;
  json_targets_json: string;
  ontology_target_kind: string;
  ambiguity_flag: boolean;
  ambiguity_note: string;
  review_status: string;
  confidence: number;
  metadata_json: string;
};
export type UpsertTermMappingRuleResponse = { rule?: TermMappingRuleRecord };
export type GetTermMappingRuleRequest = { rule_id: string };
export type GetTermMappingRuleResponse = { rule?: TermMappingRuleRecord };
export type SearchTermMappingRulesRequest = {
  registry_id?: string;
  raw_term?: string;
  query?: string;
  language?: string;
  term_type?: string;
  semantic_slot?: string;
  review_status?: string;
  ambiguity_only: boolean;
  limit: number;
  offset: number;
};
export type SearchTermMappingRulesResponse = { rules: TermMappingRuleRecord[] };
export type TermMappingRuleRecord = {
  rule_id: string;
  registry_id: string;
  raw_term: string;
  language: string;
  context_hint: string;
  term_type: string;
  normalization_status: string;
  canonical_term: string;
  canonical_concept_id: string;
  is_compound: boolean;
  split_rule_json: string;
  semantic_slot: string;
  json_targets_json: string;
  ontology_target_kind: string;
  ambiguity_flag: boolean;
  ambiguity_note: string;
  review_status: string;
  confidence: number;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};
export type UpsertTermMappingRuleEvidenceRequest = {
  rule_evidence_id: string;
  rule_id: string;
  artifact_id: string;
  artifact_version_id: string;
  event_id: string;
  memory_decision_id: string;
  source_span: string;
  note: string;
  confidence: number;
  evidence_json: string;
};
export type UpsertTermMappingRuleEvidenceResponse = { evidence?: TermMappingRuleEvidenceRecord };
export type ListTermMappingRuleEvidenceRequest = { rule_id: string; limit: number };
export type ListTermMappingRuleEvidenceResponse = { evidence: TermMappingRuleEvidenceRecord[] };
export type TermMappingRuleEvidenceRecord = {
  rule_evidence_id: string;
  rule_id: string;
  artifact_id: string;
  artifact_version_id: string;
  event_id: string;
  memory_decision_id: string;
  source_span: string;
  note: string;
  confidence: number;
  evidence_json: string;
  created_at: string;
  updated_at: string;
};
export type InterpretTermRequest = {
  registry_id?: string;
  domain?: string;
  registry_name?: string;
  version_label?: string;
  raw_term: string;
  language: string;
  context_hint: string;
};
export type InterpretTermResponse = { interpretation?: TermMappingInterpretationRecord };
export type InterpretTermBatchRequest = {
  registry_id?: string;
  domain?: string;
  registry_name?: string;
  version_label?: string;
  raw_terms: string[];
  language: string;
  context_hint: string;
};
export type InterpretTermBatchResponse = { interpretations: TermMappingInterpretationRecord[] };
export type TermMappingInterpretationRecord = {
  found: boolean;
  raw_term: string;
  matched_rule_id: string;
  registry_id: string;
  language: string;
  term_type: string;
  normalization_status: string;
  canonical_term: string;
  canonical_concept_id: string;
  is_compound: boolean;
  split_rule_json: string;
  semantic_slot: string;
  json_targets_json: string;
  ontology_target_kind: string;
  ambiguity_flag: boolean;
  ambiguity_note: string;
  review_status: string;
  confidence: number;
};

// --- Governance ---

export type UpsertMethodologyFrameworkRequest = {
  framework_id: string;
  domain: string;
  framework_name: string;
  version_label: string;
  status: string;
  description: string;
  owner: string;
  question_types_json: string;
  metadata_json: string;
};

export type UpsertMethodologyFrameworkResponse = {
  framework?: MethodologyFrameworkRecord;
};

export type GetMethodologyFrameworkRequest = {
  framework_id: string;
};

export type GetMethodologyFrameworkResponse = {
  framework?: MethodologyFrameworkRecord;
};

export type ListMethodologyFrameworksRequest = {
  domain?: string;
  status?: string;
  query?: string;
  limit: number;
  offset: number;
};

export type ListMethodologyFrameworksResponse = {
  frameworks: MethodologyFrameworkRecord[];
};

export type MethodologyFrameworkRecord = {
  framework_id: string;
  domain: string;
  framework_name: string;
  version_label: string;
  status: string;
  description: string;
  owner: string;
  question_types_json: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type GetMethodologyFrameworkBundleRequest = {
  framework_id: string;
};

export type GetMethodologyFrameworkBundleResponse = {
  framework?: MethodologyFrameworkRecord;
  taxonomy_schemes: TaxonomySchemeRecord[];
  evidence_policy_rules: EvidencePolicyRuleRecord[];
  assertion_policy_rules: AssertionPolicyRuleRecord[];
  review_policies: ReviewPolicyRecord[];
};

export type UpsertTaxonomySchemeRequest = {
  scheme_id: string;
  framework_id: string;
  scheme_name: string;
  scheme_type: string;
  status: string;
  description: string;
  canonical_source: string;
  scheme_json: string;
  metadata_json: string;
};

export type UpsertTaxonomySchemeResponse = {
  scheme?: TaxonomySchemeRecord;
};

export type GetTaxonomySchemeRequest = {
  scheme_id: string;
};

export type GetTaxonomySchemeResponse = {
  scheme?: TaxonomySchemeRecord;
};

export type ListTaxonomySchemesRequest = {
  framework_id?: string;
  scheme_type?: string;
  status?: string;
  query?: string;
  limit: number;
  offset: number;
};

export type ListTaxonomySchemesResponse = {
  schemes: TaxonomySchemeRecord[];
};

export type TaxonomySchemeRecord = {
  scheme_id: string;
  framework_id: string;
  scheme_name: string;
  scheme_type: string;
  status: string;
  description: string;
  canonical_source: string;
  scheme_json: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertEvidencePolicyRuleRequest = {
  evidence_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  question_type: string;
  evidence_kind: string;
  source_tier: string;
  status: string;
  priority: number;
  review_required: boolean;
  applicability_json: string;
  effect_json: string;
  description: string;
  metadata_json: string;
};

export type UpsertEvidencePolicyRuleResponse = {
  rule?: EvidencePolicyRuleRecord;
};

export type GetEvidencePolicyRuleRequest = {
  evidence_policy_rule_id: string;
};

export type GetEvidencePolicyRuleResponse = {
  rule?: EvidencePolicyRuleRecord;
};

export type ListEvidencePolicyRulesRequest = {
  framework_id?: string;
  question_type?: string;
  evidence_kind?: string;
  status?: string;
  query?: string;
  limit: number;
  offset: number;
};

export type ListEvidencePolicyRulesResponse = {
  rules: EvidencePolicyRuleRecord[];
};

export type EvidencePolicyRuleRecord = {
  evidence_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  question_type: string;
  evidence_kind: string;
  source_tier: string;
  status: string;
  priority: number;
  review_required: boolean;
  applicability_json: string;
  effect_json: string;
  description: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertAssertionPolicyRuleRequest = {
  assertion_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  assertion_type: string;
  question_type: string;
  status: string;
  priority: number;
  review_required: boolean;
  required_evidence_json: string;
  outcome_json: string;
  description: string;
  metadata_json: string;
};

export type UpsertAssertionPolicyRuleResponse = {
  rule?: AssertionPolicyRuleRecord;
};

export type GetAssertionPolicyRuleRequest = {
  assertion_policy_rule_id: string;
};

export type GetAssertionPolicyRuleResponse = {
  rule?: AssertionPolicyRuleRecord;
};

export type ListAssertionPolicyRulesRequest = {
  framework_id?: string;
  assertion_type?: string;
  question_type?: string;
  status?: string;
  query?: string;
  limit: number;
  offset: number;
};

export type ListAssertionPolicyRulesResponse = {
  rules: AssertionPolicyRuleRecord[];
};

export type AssertionPolicyRuleRecord = {
  assertion_policy_rule_id: string;
  framework_id: string;
  rule_key: string;
  assertion_type: string;
  question_type: string;
  status: string;
  priority: number;
  review_required: boolean;
  required_evidence_json: string;
  outcome_json: string;
  description: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertReviewPolicyRequest = {
  review_policy_id: string;
  framework_id: string;
  policy_key: string;
  question_type: string;
  trigger_kind: string;
  action: string;
  status: string;
  priority: number;
  trigger_json: string;
  description: string;
  metadata_json: string;
};

export type UpsertReviewPolicyResponse = {
  policy?: ReviewPolicyRecord;
};

export type GetReviewPolicyRequest = {
  review_policy_id: string;
};

export type GetReviewPolicyResponse = {
  policy?: ReviewPolicyRecord;
};

export type ListReviewPoliciesRequest = {
  framework_id?: string;
  question_type?: string;
  trigger_kind?: string;
  status?: string;
  query?: string;
  limit: number;
  offset: number;
};

export type ListReviewPoliciesResponse = {
  policies: ReviewPolicyRecord[];
};

export type ReviewPolicyRecord = {
  review_policy_id: string;
  framework_id: string;
  policy_key: string;
  question_type: string;
  trigger_kind: string;
  action: string;
  status: string;
  priority: number;
  trigger_json: string;
  description: string;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type UpsertRuleRequest = {
  rule_key: string;
  rule_version: number;
  severity: string;
  expression: string;
  effective_from: string;
  effective_to?: string;
  source_artifact_version_id?: string;
  system_from?: string;
  system_to?: string;
};

export type UpsertRuleResponse = {
  rule: RuleRecord;
};

export type RuleRecord = {
  rule_id: string;
  rule_key: string;
  rule_version: number;
  severity: string;
  expression: string;
  effective_from: string;
  effective_to: string;
  source_artifact_version_id: string;
  system_from: string;
  system_to: string;
  created_at: string;
};

export type InsertAuthorityGrantRequest = {
  grantee_id: string;
  action_type: string;
  scope_json: string;
  valid_from: string;
  valid_to?: string;
  system_from?: string;
  mandate_artifact_version_id?: string;
};

export type InsertAuthorityGrantResponse = {
  grant: AuthorityGrantRecord;
};

export type AuthorityGrantRecord = {
  authority_grant_id: string;
  grantee_id: string;
  action_type: string;
  scope_json: string;
  valid_from: string;
  valid_to: string;
  system_from: string;
  system_to: string;
  mandate_artifact_version_id: string;
  created_at: string;
};

export type InsertRuleOverrideRequest = {
  rule_key: string;
  rule_version: number;
  authority_grant_id: string;
  justification_artifact_version_id?: string;
  valid_from: string;
  valid_to?: string;
  system_from?: string;
  case_id?: number;
  event_id?: string;
};

export type InsertRuleOverrideResponse = {
  override: RuleOverrideRecord;
};

export type RuleOverrideRecord = {
  rule_override_id: string;
  rule_key: string;
  rule_version: number;
  authority_grant_id: string;
  justification_artifact_version_id: string;
  valid_from: string;
  valid_to: string;
  system_from: string;
  system_to: string;
  case_id: number;
  event_id: string;
  created_at: string;
};

export type FindAuthorityAsOfRequest = {
  grantee_id: string;
  action_type: string;
  scope_json?: string;
  as_of_valid_time?: string;
  as_of_system_time?: string;
};

export type FindAuthorityAsOfResponse = {
  grant?: AuthorityGrantRecord;
};

export type ListRuleOverridesAsOfRequest = {
  rule_key: string;
  rule_version?: number;
  as_of_valid_time?: string;
  as_of_system_time?: string;
};

export type ListRuleOverridesAsOfResponse = {
  overrides: RuleOverrideRecord[];
};

// --- Ontology Fact ---

export type ReviewOntologyFactRequest = {
  fact_id: number;
  decision: string;
  reviewer: string;
  note: string;
};

export type ReviewOntologyFactResponse = {
  updated_rows: number;
};

export type GetOntologyFactRequest = {
  fact_id: number;
};

export type GetOntologyFactResponse = {
  fact?: OntologyFactRecord;
};

export type OntologyFactRecord = {
  fact_id: number;
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  qualifier_json: string;
  confidence: number;
  extractor: string;
  status: string;
  review_note: string;
  valid_from: string;
  valid_to: string;
  created_at: string;
  updated_at: string;

  // Candidate fields (optional)
  stale_fact_count?: number;
  fact_count?: number;
  dst_count?: number;
  fact_ids?: number[];
  dst_values?: string[];
  stream_id?: string;
  src_concept_label?: string;
  dst_concept_label?: string;
  statement_id?: string;
};

export type ListOntologyFactReviewsRequest = {
  fact_id: number;
};

export type ListOntologyFactReviewsResponse = {
  reviews: OntologyFactReviewRecord[];
};

export type OntologyFactReviewRecord = {
  review_id: number;
  fact_id: number;
  reviewer: string;
  decision: string;
  note: string;
  created_at: string;
};

export type ListOntologyFactEvidenceRequest = {
  fact_id: number;
  limit?: number;
  stream_id?: string;
  evidence_limit?: number;
};

export type ListOntologyFactEvidenceResponse = {
  evidence: OntologyFactEvidenceRecord[];
};

export type OntologyFactEvidenceRecord = {
  stream_id: string;
  event_id: string;
  asset_id: string;
  version_number: number;
  source_span: string;
  evidence_json: string;
  confidence: number;
  created_at: string;
  updated_at: string;
};

export type ListOntologyFactLinkedCasesRequest = {
  fact_id: number;
};

export type ListOntologyFactLinkedCasesResponse = {
  linked_cases: OntologyFactLinkedCaseRecord[];
};

export type OntologyFactLinkedCaseRecord = {
  case_id: number;
  stream_id: string;
  title: string;
  status: string;
  priority: string;
  owner: string;
  linked_at: string;
};

export type ListOntologyFactLinkedAlertsRequest = {
  fact_id: number;
};

export type ListOntologyFactLinkedAlertsResponse = {
  linked_alerts: OntologyFactLinkedAlertRecord[];
};

export type OntologyFactLinkedAlertRecord = {
  alert_id: number;
  case_id: number;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  rule_key: string;
  linked_at: string;
};

export type SelectOntologyFactsForBulkReviewRequest = {
  status: string;
  stream_id?: string;
  predicate?: string;
  extractor?: string;
  stale_days?: number;
  min_confidence: number;
  max_confidence: number;
  limit: number;
};

export type SelectOntologyFactsForBulkReviewResponse = {
  selected: OntologyFactBulkSelectionRecord[];
};

export type OntologyFactBulkSelectionRecord = {
  fact_id: number;
  status: string;
  confidence: number;
};

// --- Ontology Case ---

export type InsertOntologyCaseRequest = {
  stream_id: string;
  title: string;
  description: string;
  priority: string;
  owner: string;
  created_by: string;
};

export type InsertOntologyCaseResponse = {
  ontology_case: OntologyCaseRecord;
};

export type OntologyCaseRecord = {
  case_id: number;
  stream_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  owner: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  closed_at: string;
};

export type GetOntologyCaseRequest = {
  case_id: number;
};

export type GetOntologyCaseResponse = {
  ontology_case?: OntologyCaseRecord;
};

export type ListOntologyCasesRequest = {
  stream_id?: string;
  status: string;
  limit: number;
};

export type ListOntologyCasesResponse = {
  cases: OntologyCaseSummaryRecord[];
};

export type OntologyCaseSummaryRecord = {
  case_id: number;
  stream_id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  owner: string;
  created_by: string;
  created_at: string;
  updated_at: string;
  closed_at: string;
  fact_count: number;
  active_alert_count: number;
};

export type UpdateOntologyCaseRequest = {
  case_id: number;
  status?: string;
  owner?: string;
};

export type UpdateOntologyCaseResponse = {
  updated_rows: number;
};

export type LinkOntologyCaseFactRequest = {
  case_id: number;
  fact_id: number;
  added_by: string;
  added_note: string;
  stream_id: string;
};

export type LinkOntologyCaseFactResponse = {
  linked: boolean;
};

export type ListOntologyCaseFactsRequest = {
  case_id: number;
  evidence_limit: number;
};

export type ListOntologyCaseFactsResponse = {
  facts: OntologyCaseFactRecord[];
};

export type OntologyCaseFactRecord = {
  fact_id: number;
  src_concept_id: string;
  predicate: string;
  dst_concept_id: string;
  confidence: number;
  status: string;
  extractor: string;
  updated_at: string;
  linked_at: string;
  added_by: string;
  added_note: string;
  evidence_count: number;
  evidence_sample_json: string;
};

export type InsertOntologyCaseDecisionRequest = {
  case_id: number;
  decision_kind: string;
  verdict: string;
  summary: string;
  rationale: string;
  as_of_system_time: string;
  as_of_effective_time: string;
  snapshot_id: string;
  source_evidence_json: string;
  supersedes_case_decision_id: number;
  created_by: string;
};

export type InsertOntologyCaseDecisionResponse = {
  decision: OntologyCaseDecisionRecord;
};

export type OntologyCaseDecisionRecord = {
  case_decision_id: number;
  case_id: number;
  decision_kind: string;
  verdict: string;
  summary: string;
  rationale: string;
  as_of_system_time: string;
  as_of_effective_time: string;
  snapshot_id: string;
  source_evidence_json: string;
  supersedes_case_decision_id: number;
  created_by: string;
  created_at: string;
};

export type ListOntologyCaseDecisionsRequest = {
  case_id: number;
};

export type ListOntologyCaseDecisionsResponse = {
  decisions: OntologyCaseDecisionRecord[];
};

export type InsertOntologyCaseEventRequest = {
  case_id: number;
  action: string;
  actor: string;
  note: string;
  payload_json: string;
};

export type InsertOntologyCaseEventResponse = {
  event: OntologyCaseEventRecord;
};

export type OntologyCaseEventRecord = {
  event_id: number;
  case_id: number;
  action: string;
  actor: string;
  note: string;
  payload_json: string;
  created_at: string;
};

export type ListOntologyCaseEventsRequest = {
  case_id: number;
};

export type ListOntologyCaseEventsResponse = {
  events: OntologyCaseEventRecord[];
};

// --- Ontology Alert ---

export type InsertOntologyAlertRequest = {
  case_id?: number;
  stream_id: string;
  severity: string;
  message: string;
  detail_json: string;
  rule_key?: string;
};

export type InsertOntologyAlertResponse = {
  alert: OntologyAlertRecord;
};

export type OntologyAlertRecord = {
  alert_id: number;
  case_id: number;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  detail_json: string;
  rule_key: string;
  trigger_count: number;
  first_triggered_at: string;
  last_triggered_at: string;
  acked_by: string;
  acked_at: string;
  closed_at: string;
  created_at: string;
  updated_at: string;
};

export type GetOntologyAlertDetailRequest = {
  alert_id: number;
};

export type GetOntologyAlertDetailResponse = {
  alert_detail?: OntologyAlertDetailRecord;
};

export type OntologyAlertDetailRecord = {
  alert_id: number;
  case_id?: number;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  detail_json: string;
  rule_key: string;
  trigger_count: number;
  first_triggered_at: string;
  last_triggered_at: string;
  acked_by: string;
  acked_at: string;
  closed_at: string;
  created_at: string;
  updated_at: string;

  alert: OntologyAlertRecord;
  case_title: string;
  linked_fact_count: number;
  linked_fact_ids: number[];
};

export type ListOntologyAlertsRequest = {
  stream_id?: string;
  status: string;
  limit: number;
  case_id?: number;
};

export type ListOntologyAlertsResponse = {
  alerts: OntologyAlertSummaryRecord[];
};

export type OntologyAlertSummaryRecord = {
  alert_id: number;
  case_id?: number;
  stream_id: string;
  severity: string;
  status: string;
  message: string;
  detail_json: string;
  rule_key: string;
  trigger_count: number;
  first_triggered_at: string;
  last_triggered_at: string;
  acked_by: string;
  acked_at: string;
  closed_at: string;
  created_at: string;
  updated_at: string;

  alert: OntologyAlertRecord;
  case_title: string;
  linked_fact_count: number;
  linked_fact_ids: number[];
};

export type UpdateOntologyAlertRequest = {
  alert_id: number;
  status?: string;
  acked_by?: string;
  actor?: string;
};

export type UpdateOntologyAlertResponse = {
  updated_rows: number;
};

export type RefreshTriggeredOntologyAlertRequest = {
  alert_id: number;
  case_id?: number;
  severity?: string;
  message?: string;
  detail_json?: string;
};

export type RefreshTriggeredOntologyAlertResponse = {
  alert: OntologyAlertRecord;
};

export type ListStalePendingOntologyCandidatesRequest = {
  stream_id?: string;
  stale_days: number;
};

export type ListConflictPredicateOntologyCandidatesRequest = {
  stream_id?: string;
  predicate: string;
};

export type ListOntologyFactsResponse = {
  facts: OntologyFactRecord[];
};

export type GetActiveOntologyCaseByTitleRequest = {
  title: string;
};

export type GetActiveOntologyCaseByTitleResponse = {
  case?: OntologyCaseRecord;
};

export type GetActiveOntologyAlertByRuleKeyRequest = {
  rule_key: string;
};

export type GetActiveOntologyAlertByRuleKeyResponse = {
  alert?: OntologyAlertRecord;
};

export type LinkOntologyAlertFactRequest = {
  alert_id: number;
  fact_id: number;
};

export type Empty = {};

// --- Ontology Ops ---

export type UpsertOntologyOpsRuleConfigRequest = {
  stream_id?: string;
  rule_name: string;
  enabled: boolean;
  stale_days: number;
  conflict_predicate: string;
  severity: string;
  note: string;
  updated_by: string;
};

export type UpsertOntologyOpsRuleConfigResponse = {
  config: OntologyOpsRuleConfigRecord;
};

export type OntologyOpsRuleConfigRecord = {
  config_id: number;
  stream_id: string;
  rule_name: string;
  enabled: boolean;
  stale_days: number;
  conflict_predicate: string;
  severity: string;
  note: string;
  updated_by: string;
  updated_at: string;
};

export type ListOntologyOpsRuleConfigRequest = {
  stream_id?: string;
};

export type ListOntologyOpsRuleConfigResponse = {
  configs: OntologyOpsRuleConfigRecord[];
};

export type InsertOntologyOpsRuleRunRequest = {
  stream_id_filter?: string;
  stale_days: number;
  conflict_predicate: string;
  dry_run: boolean;
  candidate_count: number;
  created_case_count: number;
  existing_case_count: number;
  created_alert_count: number;
  existing_alert_count: number;
  payload_json: string;
  duration_ms: number;
  started_at?: string;
  finished_at?: string;
};

export type InsertOntologyOpsRuleRunResponse = {
  run: OntologyOpsRuleRunRecord;
};

export type OntologyOpsRuleRunRecord = {
  run_id: number;
  stream_id_filter: string;
  stale_days: number;
  conflict_predicate: string;
  dry_run: boolean;
  candidate_count: number;
  created_case_count: number;
  existing_case_count: number;
  created_alert_count: number;
  existing_alert_count: number;
  payload_json: string;
  duration_ms: number;
  started_at: string;
  finished_at: string;
};

export type GetOntologyOpsRunRequest = {
  run_id: number;
};

export type GetOntologyOpsRunResponse = {
  run?: OntologyOpsRuleRunRecord;
};

export type ListOntologyOpsRunsRequest = {
  stream_id?: string;
  limit: number;
};

export type ListOntologyOpsRunsResponse = {
  runs: OntologyOpsRuleRunRecord[];
};

// ── Wiki ──────────────────────────────────────────────────────────────────────

export type WikiPageRecord = {
  page_id: string;
  domain: string;
  slug: string;
  title: string;
  content: string;
  page_type: string;
  knowledge_level: string;
  authority_kind: string;
  tags_json: string;
  source_count: number;
  confidence: number;
  last_reinforced_at: string;
  created_at: string;
  updated_at: string;
  superseded_by: string;
};

export type UpsertWikiPageRequest = {
  domain: string;
  slug: string;
  title: string;
  content: string;
  page_type: string;
  tags_json: string;
  confidence: number;
  supersede?: boolean;
  knowledge_level: string;
  authority_kind: string;
};

export type UpsertWikiPageResponse = {
  page_id: string;
  slug: string;
  status: string;
  superseded_page_id?: string;
};

export type UpsertWikiPageLinkRequest = {
  domain: string;
  from_slug: string;
  to_slug: string;
  link_text: string;
};

export type UpsertWikiPageLinkResponse = {
  from_page_id: string;
  to_page_id: string;
  status: string;
};

export type GetWikiPageRequest = {
  domain: string;
  slug: string;
};

export type GetWikiPageResponse = {
  page?: WikiPageRecord;
};

export type SearchWikiPagesRequest = {
  domain: string;
  query: string;
  page_type: string;
  limit: number;
  knowledge_level: string;
  authority_kind: string;
};

export type SearchWikiPagesResponse = {
  pages: WikiPageRecord[];
};

export type ListWikiPagesRequest = {
  domain: string;
  page_type?: string;
  knowledge_level?: string;
  authority_kind?: string;
  include_content?: boolean;
  limit?: number;
  offset?: number;
};

export type ListWikiPagesResponse = {
  pages: WikiPageRecord[];
  total: number;
  limit: number;
  offset: number;
};

export type ReinforceWikiPageRequest = {
  page_id: string;
  delta_confidence: number;
};

export type ReinforceWikiPageResponse = {
  page?: WikiPageRecord;
};

export type WikiLogRecord = {
  log_id: string;
  domain: string;
  action_type: string;
  source_ref: string;
  pages_touched: number;
  summary: string;
  created_at: string;
};

export type AppendWikiLogRequest = {
  domain: string;
  action_type: string;
  source_ref: string;
  pages_touched: number;
  summary: string;
};

export type AppendWikiLogResponse = {
  log?: WikiLogRecord;
};

export type ListWikiLogsRequest = {
  domain: string;
  limit: number;
};

export type ListWikiLogsResponse = {
  logs: WikiLogRecord[];
};

export type WikiLintIssue = {
  type: string;
  page_id: string;
  slug: string;
  description: string;
  severity: string;
};

export type LintWikiDomainRequest = {
  domain: string;
};

export type LintWikiDomainResponse = {
  issues: WikiLintIssue[];
};
