import path from 'node:path';
import { fileURLToPath } from 'node:url';

import grpc, { credentials, loadPackageDefinition, status as grpcStatus } from '@grpc/grpc-js';
import protoLoader from '@grpc/proto-loader';

import { TdbError } from '../errors/tdb_error.js';
import type { SearchHit, SearchQueryRequest, SearchQueryResult } from '../services/search.service.js';
import type {
  GatewayBackendClient,
  GatewayBackendConfig,
  GatewayBackendProtoHit,
  GatewayBackendProtoRequest,
  GatewayBackendProtoResponse,
  GatewayBackendTransport,
  DomainStreamBindingRecord,
  DomainStreamBindingUpsertRequest,
  DomainStreamBindingListQuery,
  IndexEventRequest,
  IndexEventResponse,
  AppendEventRequest,
  AppendEventResponse,
  GetEventsRequest,
  GetEventsResponse,
  EventItem,
  GetEventSentencesRequest,
  GetEventSentencesResponse,
  EventSentenceRecord,
  UpsertPropertyRequest,
  UpsertPropertyResponse,
  GetPropertyAsOfRequest,
  GetPropertyAsOfResponse,
  PropertyRecord,
  UpsertEdgeRequest,
  UpsertEdgeResponse,
  GetEdgesAsOfRequest,
  GetEdgesAsOfResponse,
  EdgeRecord,
  ListPropertyRowsRequest,
  ListPropertyRowsResponse,
  UpsertEntityRequest,
  UpsertEntityResponse,
  GetEntityRequest,
  GetEntityResponse,
  ListEntitiesRequest,
  ListEntitiesResponse,
  EntityRecord,
  WriteSnapshotRequest,
  WriteSnapshotResponse,
  GetLatestSnapshotRequest,
  GetLatestSnapshotResponse,
  SnapshotRecord,
  CreateArtifactRequest,
  CreateArtifactResponse,
  CreateArtifactVersionRequest,
  CreateArtifactVersionResponse,
  GetArtifactVersionAsOfRequest,
  GetArtifactVersionAsOfResponse,
  GetArtifactVersionByIdRequest,
  GetArtifactVersionByIdResponse,
  ArtifactRecord,
  ArtifactVersionRecord,
  UpsertDecisionRequest,
  UpsertDecisionResponse,
  InsertDecisionEvidenceRequest,
  InsertDecisionEvidenceResponse,
  FindDecisionRequest,
  FindDecisionResponse,
  ListDecisionEvidenceRequest,
  ListDecisionEvidenceResponse,
  UpsertAssertionRequest,
  UpsertAssertionResponse,
  GetAssertionRequest,
  GetAssertionResponse,
  SearchAssertionsRequest,
  SearchAssertionsResponse,
  AssertionRecord,
  UpsertEvidenceRequest,
  UpsertEvidenceResponse,
  GetEvidenceRequest,
  GetEvidenceResponse,
  SearchEvidenceRequest,
  SearchEvidenceResponse,
  EvidenceRecord,
  UpsertEvidenceLocatorRequest,
  UpsertEvidenceLocatorResponse,
  ListEvidenceLocatorsRequest,
  ListEvidenceLocatorsResponse,
  EvidenceLocatorRecord,
  UpsertEvidenceDerivationRequest,
  UpsertEvidenceDerivationResponse,
  ListEvidenceDerivationsRequest,
  ListEvidenceDerivationsResponse,
  EvidenceDerivationRecord,
  UpsertEvidenceClassificationRequest,
  UpsertEvidenceClassificationResponse,
  GetEvidenceClassificationRequest,
  GetEvidenceClassificationResponse,
  EvidenceClassificationRecord,
  UpsertAssertionEvidenceLinkRequest,
  UpsertAssertionEvidenceLinkResponse,
  ListAssertionEvidenceLinksRequest,
  ListAssertionEvidenceLinksResponse,
  AssertionEvidenceLinkRecord,
  UpsertAssertionRelationRequest,
  UpsertAssertionRelationResponse,
  ListAssertionRelationsRequest,
  ListAssertionRelationsResponse,
  AssertionRelationRecord,
  InsertMemoryDecisionRequest,
  InsertMemoryDecisionResponse,
  ListRecentMemoryDecisionsRequest,
  ListRecentMemoryDecisionsResponse,
  InsertMemoryEpisodeSummaryRequest,
  InsertMemoryEpisodeSummaryResponse,
  ListRecentMemoryEpisodeSummariesRequest,
  ListRecentMemoryEpisodeSummariesResponse,
  InsertMemoryAnswerArtifactRequest,
  InsertMemoryAnswerArtifactResponse,
  RecallMemoryAnswerArtifactsRequest,
  RecallMemoryAnswerArtifactsResponse,
  InsertMemoryAnswerValidationRequest,
  InsertMemoryAnswerValidationResponse,
  MemoryAnswerArtifactRecord,
  MemoryAnswerValidationRecord,
  UpsertOntologyConceptRequest,
  UpsertOntologyConceptResponse,
  GetOntologyConceptRequest,
  GetOntologyConceptResponse,
  ListOntologyConceptsRequest,
  ListOntologyConceptsResponse,
  OntologyConceptRecord,
  UpsertConceptAliasRequest,
  UpsertConceptAliasResponse,
  ListConceptAliasesRequest,
  ListConceptAliasesResponse,
  ConceptAliasRecord,
  UpsertOntologyEdgeRequest,
  UpsertOntologyEdgeResponse,
  ListOntologyEdgesRequest,
  ListOntologyEdgesResponse,
  OntologyEdgeRecord,
  UpsertEventConceptLinkRequest,
  UpsertEventConceptLinkResponse,
  ListEventConceptLinksRequest,
  ListEventConceptLinksResponse,
  EventConceptLinkRecord,
  UpsertOntologyObjectTypeRequest,
  UpsertOntologyObjectTypeResponse,
  GetOntologyObjectTypeRequest,
  GetOntologyObjectTypeResponse,
  ListOntologyObjectTypesRequest,
  ListOntologyObjectTypesResponse,
  OntologyObjectTypeRecord,
  UpsertOntologyConceptTypeAssignmentRequest,
  UpsertOntologyConceptTypeAssignmentResponse,
  ListOntologyConceptTypeAssignmentsRequest,
  ListOntologyConceptTypeAssignmentsResponse,
  OntologyConceptTypeAssignmentRecord,
  UpsertOntologyRelationTypeRequest,
  UpsertOntologyRelationTypeResponse,
  GetOntologyRelationTypeRequest,
  GetOntologyRelationTypeResponse,
  ListOntologyRelationTypesRequest,
  ListOntologyRelationTypesResponse,
  OntologyRelationTypeRecord,
  ListOntologyFactsRequest,
  UpsertOntologyFactWithEvidenceRequest,
  UpsertOntologyFactWithEvidenceResponse,
  UpsertSemanticBatchRequest,
  UpsertSemanticBatchResponse,
  GetSemanticStatementRequest,
  GetSemanticStatementResponse,
  ListSemanticStatementsRequest,
  ListSemanticStatementsResponse,
  SetSemanticStatementStatusRequest,
  SetSemanticStatementStatusResponse,
  GetSemanticStatementProvenanceRequest,
  GetSemanticStatementProvenanceResponse,
  GetSemanticStatementsByEvidenceRequest,
  GetSemanticStatementsByEvidenceResponse,
  SemanticStatementRecord,
  SemanticStatementQualifierRecord,
  SemanticStatementReferenceRecord,
  SearchOntologyConceptsRequest,
  SearchOntologyConceptsResponse,
  SearchConceptAliasesRequest,
  SearchConceptAliasesResponse,
  SearchOntologyFactsRequest,
  SearchOntologyFactsResponse,
  GetOntologyConceptNeighborsRequest,
  GetOntologyConceptNeighborsResponse,
  OntologyNeighborRecord,
  ArchiveOntologyFactRequest,
  ArchiveOntologyFactResponse,
  UpsertTermMappingRegistryRequest,
  UpsertTermMappingRegistryResponse,
  GetTermMappingRegistryRequest,
  GetTermMappingRegistryResponse,
  ListTermMappingRegistriesRequest,
  ListTermMappingRegistriesResponse,
  TermMappingRegistryRecord,
  UpsertOntologyNormalizedTermRequest,
  UpsertOntologyNormalizedTermResponse,
  GetOntologyNormalizedTermRequest,
  GetOntologyNormalizedTermResponse,
  SearchOntologyNormalizedTermsRequest,
  SearchOntologyNormalizedTermsResponse,
  OntologyNormalizedTermRecord,
  UpsertOntologyTermClusterRequest,
  UpsertOntologyTermClusterResponse,
  GetOntologyTermClusterRequest,
  GetOntologyTermClusterResponse,
  ListOntologyTermClustersRequest,
  ListOntologyTermClustersResponse,
  OntologyTermClusterRecord,
  UpsertOntologyClusterMemberRequest,
  UpsertOntologyClusterMemberResponse,
  ListOntologyClusterMembersRequest,
  ListOntologyClusterMembersResponse,
  OntologyClusterMemberRecord,
  UpsertOntologyRelationCandidateRequest,
  UpsertOntologyRelationCandidateResponse,
  ListOntologyRelationCandidatesRequest,
  ListOntologyRelationCandidatesResponse,
  OntologyRelationCandidateRecord,
  UpsertOntologyRawTermRequest,
  UpsertOntologyRawTermResponse,
  GetOntologyRawTermRequest,
  GetOntologyRawTermResponse,
  SearchOntologyRawTermsRequest,
  SearchOntologyRawTermsResponse,
  OntologyRawTermRecord,
  UpsertOntologyRawTermCandidateRequest,
  UpsertOntologyRawTermCandidateResponse,
  ListOntologyRawTermCandidatesRequest,
  ListOntologyRawTermCandidatesResponse,
  OntologyRawTermCandidateRecord,
  UpsertOntologyRawTermNormalizationRequest,
  UpsertOntologyRawTermNormalizationResponse,
  ListOntologyRawTermNormalizationsRequest,
  ListOntologyRawTermNormalizationsResponse,
  OntologyRawTermNormalizationRecord,
  UpsertTermMappingRuleRequest,
  UpsertTermMappingRuleResponse,
  GetTermMappingRuleRequest,
  GetTermMappingRuleResponse,
  SearchTermMappingRulesRequest,
  SearchTermMappingRulesResponse,
  TermMappingRuleRecord,
  UpsertTermMappingRuleEvidenceRequest,
  UpsertTermMappingRuleEvidenceResponse,
  ListTermMappingRuleEvidenceRequest,
  ListTermMappingRuleEvidenceResponse,
  TermMappingRuleEvidenceRecord,
  InterpretTermRequest,
  InterpretTermResponse,
  InterpretTermBatchRequest,
  InterpretTermBatchResponse,
  TermMappingInterpretationRecord,
  UpsertMethodologyFrameworkRequest,
  UpsertMethodologyFrameworkResponse,
  GetMethodologyFrameworkRequest,
  GetMethodologyFrameworkResponse,
  ListMethodologyFrameworksRequest,
  ListMethodologyFrameworksResponse,
  MethodologyFrameworkRecord,
  GetMethodologyFrameworkBundleRequest,
  GetMethodologyFrameworkBundleResponse,
  UpsertTaxonomySchemeRequest,
  UpsertTaxonomySchemeResponse,
  GetTaxonomySchemeRequest,
  GetTaxonomySchemeResponse,
  ListTaxonomySchemesRequest,
  ListTaxonomySchemesResponse,
  TaxonomySchemeRecord,
  UpsertEvidencePolicyRuleRequest,
  UpsertEvidencePolicyRuleResponse,
  GetEvidencePolicyRuleRequest,
  GetEvidencePolicyRuleResponse,
  ListEvidencePolicyRulesRequest,
  ListEvidencePolicyRulesResponse,
  EvidencePolicyRuleRecord,
  UpsertAssertionPolicyRuleRequest,
  UpsertAssertionPolicyRuleResponse,
  GetAssertionPolicyRuleRequest,
  GetAssertionPolicyRuleResponse,
  ListAssertionPolicyRulesRequest,
  ListAssertionPolicyRulesResponse,
  AssertionPolicyRuleRecord,
  UpsertReviewPolicyRequest,
  UpsertReviewPolicyResponse,
  GetReviewPolicyRequest,
  GetReviewPolicyResponse,
  ListReviewPoliciesRequest,
  ListReviewPoliciesResponse,
  ReviewPolicyRecord,
  DecisionRecord,
  DecisionEvidenceRecord,
  MemoryDecisionRecord,
  MemoryEpisodeSummaryRecord,
  UpsertRuleRequest, UpsertRuleResponse, RuleRecord,
  InsertAuthorityGrantRequest, InsertAuthorityGrantResponse, AuthorityGrantRecord,
  InsertRuleOverrideRequest, InsertRuleOverrideResponse, RuleOverrideRecord,
  FindAuthorityAsOfRequest, FindAuthorityAsOfResponse,
  ListRuleOverridesAsOfRequest, ListRuleOverridesAsOfResponse,
  ReviewOntologyFactRequest, ReviewOntologyFactResponse,
  GetOntologyFactRequest, GetOntologyFactResponse, OntologyFactRecord,
  ListOntologyFactReviewsRequest, ListOntologyFactReviewsResponse, OntologyFactReviewRecord,
  ListOntologyFactEvidenceRequest, ListOntologyFactEvidenceResponse, OntologyFactEvidenceRecord,
  ListOntologyFactLinkedCasesRequest, ListOntologyFactLinkedCasesResponse, OntologyFactLinkedCaseRecord,
  ListOntologyFactLinkedAlertsRequest, ListOntologyFactLinkedAlertsResponse, OntologyAlertRecord as OntologyAlertRecordInner, OntologyFactLinkedAlertRecord,
  SelectOntologyFactsForBulkReviewRequest, SelectOntologyFactsForBulkReviewResponse, OntologyFactBulkSelectionRecord,
  InsertOntologyCaseRequest, InsertOntologyCaseResponse, OntologyCaseRecord,
  GetOntologyCaseRequest, GetOntologyCaseResponse,
  ListOntologyCasesRequest, ListOntologyCasesResponse, OntologyCaseSummaryRecord,
  UpdateOntologyCaseRequest, UpdateOntologyCaseResponse,
  LinkOntologyCaseFactRequest, LinkOntologyCaseFactResponse,
  ListOntologyCaseFactsRequest, ListOntologyCaseFactsResponse, OntologyCaseFactRecord,
  InsertOntologyCaseDecisionRequest, InsertOntologyCaseDecisionResponse, OntologyCaseDecisionRecord,
  ListOntologyCaseDecisionsRequest, ListOntologyCaseDecisionsResponse, OntologyCaseDecisionRecord as OntologyCaseDecisionRecordInner,
  InsertOntologyCaseEventRequest, InsertOntologyCaseEventResponse, OntologyCaseEventRecord,
  ListOntologyCaseEventsRequest, ListOntologyCaseEventsResponse, OntologyCaseEventRecord as OntologyCaseEventRecordInner,
  InsertOntologyAlertRequest, InsertOntologyAlertResponse, OntologyAlertRecord,
  GetOntologyAlertDetailRequest, GetOntologyAlertDetailResponse, OntologyAlertDetailRecord,
  ListOntologyAlertsRequest, ListOntologyAlertsResponse, OntologyAlertSummaryRecord,
  UpdateOntologyAlertRequest, UpdateOntologyAlertResponse,
  RefreshTriggeredOntologyAlertRequest, RefreshTriggeredOntologyAlertResponse,
  UpsertOntologyOpsRuleConfigRequest, UpsertOntologyOpsRuleConfigResponse, OntologyOpsRuleConfigRecord,
  ListOntologyOpsRuleConfigRequest, ListOntologyOpsRuleConfigResponse,
  InsertOntologyOpsRuleRunRequest, InsertOntologyOpsRuleRunResponse, OntologyOpsRuleRunRecord,
  GetOntologyOpsRunRequest, GetOntologyOpsRunResponse,
  ListOntologyOpsRunsRequest, ListOntologyOpsRunsResponse,
  ListStalePendingOntologyCandidatesRequest,
  ListConflictPredicateOntologyCandidatesRequest,
  ListOntologyFactsResponse,
  GetActiveOntologyCaseByTitleRequest,
  GetActiveOntologyCaseByTitleResponse,
  GetActiveOntologyAlertByRuleKeyRequest,
  GetActiveOntologyAlertByRuleKeyResponse,
  LinkOntologyAlertFactRequest,
  Empty,
  UpsertWikiPageRequest, UpsertWikiPageResponse,
  UpsertWikiPageLinkRequest, UpsertWikiPageLinkResponse,
  GetWikiPageRequest, GetWikiPageResponse, WikiPageRecord,
  SearchWikiPagesRequest, SearchWikiPagesResponse,
  ListWikiPagesRequest, ListWikiPagesResponse,
  ReinforceWikiPageRequest, ReinforceWikiPageResponse,
  AppendWikiLogRequest, AppendWikiLogResponse, WikiLogRecord,
  ListWikiLogsRequest, ListWikiLogsResponse,
  LintWikiDomainRequest, LintWikiDomainResponse, WikiLintIssue,
} from './gateway_backend.types.js';

type GrpcSearchQueryCallback = (
  error: grpc.ServiceError | null,
  response: GatewayBackendProtoResponse
) => void;

type GrpcIndexEventCallback = (
  error: grpc.ServiceError | null,
  response: IndexEventResponse
) => void;

type GrpcAppendEventCallback = (
  error: grpc.ServiceError | null,
  response: AppendEventResponse
) => void;

type GrpcGetEventsCallback = (
  error: grpc.ServiceError | null,
  response: GetEventsResponse
) => void;

type GrpcGetEventSentencesCallback = (
  error: grpc.ServiceError | null,
  response: GetEventSentencesResponse
) => void;

type GrpcUpsertPropertyCallback = (
  error: grpc.ServiceError | null,
  response: UpsertPropertyResponse
) => void;

type GrpcGetPropertyAsOfCallback = (
  error: grpc.ServiceError | null,
  response: GetPropertyAsOfResponse
) => void;

type GrpcUpsertEdgeCallback = (error: grpc.ServiceError | null, response: UpsertEdgeResponse) => void;
type GrpcReviewOntologyFactCallback = (error: grpc.ServiceError | null, response: ReviewOntologyFactResponse) => void;
type GrpcGetOntologyFactCallback = (error: grpc.ServiceError | null, response: GetOntologyFactResponse) => void;
type GrpcListOntologyFactReviewsCallback = (error: grpc.ServiceError | null, response: ListOntologyFactReviewsResponse) => void;
type GrpcListOntologyFactEvidenceCallback = (error: grpc.ServiceError | null, response: ListOntologyFactEvidenceResponse) => void;
type GrpcListOntologyFactLinkedCasesCallback = (error: grpc.ServiceError | null, response: ListOntologyFactLinkedCasesResponse) => void;
type GrpcListOntologyFactLinkedAlertsCallback = (error: grpc.ServiceError | null, response: ListOntologyFactLinkedAlertsResponse) => void;
type GrpcSelectOntologyFactsForBulkReviewCallback = (error: grpc.ServiceError | null, response: SelectOntologyFactsForBulkReviewResponse) => void;
type GrpcInsertOntologyCaseCallback = (error: grpc.ServiceError | null, response: InsertOntologyCaseResponse) => void;
type GrpcGetOntologyCaseCallback = (error: grpc.ServiceError | null, response: GetOntologyCaseResponse) => void;
type GrpcListOntologyCasesCallback = (error: grpc.ServiceError | null, response: ListOntologyCasesResponse) => void;
type GrpcUpdateOntologyCaseCallback = (error: grpc.ServiceError | null, response: UpdateOntologyCaseResponse) => void;
type GrpcLinkOntologyCaseFactCallback = (error: grpc.ServiceError | null, response: LinkOntologyCaseFactResponse) => void;
type GrpcListOntologyCaseFactsCallback = (error: grpc.ServiceError | null, response: ListOntologyCaseFactsResponse) => void;
type GrpcInsertOntologyCaseDecisionCallback = (error: grpc.ServiceError | null, response: InsertOntologyCaseDecisionResponse) => void;
type GrpcListOntologyCaseDecisionsCallback = (error: grpc.ServiceError | null, response: ListOntologyCaseDecisionsResponse) => void;
type GrpcInsertOntologyCaseEventCallback = (error: grpc.ServiceError | null, response: InsertOntologyCaseEventResponse) => void;
type GrpcListOntologyCaseEventsCallback = (error: grpc.ServiceError | null, response: ListOntologyCaseEventsResponse) => void;
type GrpcInsertOntologyAlertCallback = (error: grpc.ServiceError | null, response: InsertOntologyAlertResponse) => void;
type GrpcGetOntologyAlertDetailCallback = (error: grpc.ServiceError | null, response: GetOntologyAlertDetailResponse) => void;
type GrpcListOntologyAlertsCallback = (error: grpc.ServiceError | null, response: ListOntologyAlertsResponse) => void;
type GrpcUpdateOntologyAlertCallback = (error: grpc.ServiceError | null, response: UpdateOntologyAlertResponse) => void;
type GrpcRefreshTriggeredOntologyAlertCallback = (error: grpc.ServiceError | null, response: RefreshTriggeredOntologyAlertResponse) => void;
type GrpcUpsertOntologyOpsRuleConfigCallback = (error: grpc.ServiceError | null, response: UpsertOntologyOpsRuleConfigResponse) => void;
type GrpcListOntologyOpsRuleConfigCallback = (error: grpc.ServiceError | null, response: ListOntologyOpsRuleConfigResponse) => void;
type GrpcInsertOntologyOpsRuleRunCallback = (error: grpc.ServiceError | null, response: InsertOntologyOpsRuleRunResponse) => void;
type GrpcGetOntologyOpsRunCallback = (error: grpc.ServiceError | null, response: GetOntologyOpsRunResponse) => void;
type GrpcListOntologyOpsRunsCallback = (error: grpc.ServiceError | null, response: ListOntologyOpsRunsResponse) => void;
type GrpcListApplicableOntologyOpsRuleConfigCallback = (error: grpc.ServiceError | null, response: ListOntologyOpsRuleConfigResponse) => void;
type GrpcListStalePendingOntologyCandidatesCallback = (error: grpc.ServiceError | null, response: ListOntologyFactsResponse) => void;
type GrpcListConflictPredicateOntologyCandidatesCallback = (error: grpc.ServiceError | null, response: ListOntologyFactsResponse) => void;
type GrpcUpsertTermMappingRegistryCallback = (error: grpc.ServiceError | null, response: UpsertTermMappingRegistryResponse) => void;
type GrpcGetTermMappingRegistryCallback = (error: grpc.ServiceError | null, response: GetTermMappingRegistryResponse) => void;
type GrpcListTermMappingRegistriesCallback = (error: grpc.ServiceError | null, response: ListTermMappingRegistriesResponse) => void;
type GrpcUpsertTermMappingRuleCallback = (error: grpc.ServiceError | null, response: UpsertTermMappingRuleResponse) => void;
type GrpcGetTermMappingRuleCallback = (error: grpc.ServiceError | null, response: GetTermMappingRuleResponse) => void;
type GrpcSearchTermMappingRulesCallback = (error: grpc.ServiceError | null, response: SearchTermMappingRulesResponse) => void;
type GrpcUpsertTermMappingRuleEvidenceCallback = (error: grpc.ServiceError | null, response: UpsertTermMappingRuleEvidenceResponse) => void;
type GrpcListTermMappingRuleEvidenceCallback = (error: grpc.ServiceError | null, response: ListTermMappingRuleEvidenceResponse) => void;
type GrpcInterpretTermCallback = (error: grpc.ServiceError | null, response: InterpretTermResponse) => void;
type GrpcInterpretTermBatchCallback = (error: grpc.ServiceError | null, response: InterpretTermBatchResponse) => void;
type GrpcUpsertMethodologyFrameworkCallback = (error: grpc.ServiceError | null, response: UpsertMethodologyFrameworkResponse) => void;
type GrpcGetMethodologyFrameworkCallback = (error: grpc.ServiceError | null, response: GetMethodologyFrameworkResponse) => void;
type GrpcListMethodologyFrameworksCallback = (error: grpc.ServiceError | null, response: ListMethodologyFrameworksResponse) => void;
type GrpcGetMethodologyFrameworkBundleCallback = (error: grpc.ServiceError | null, response: GetMethodologyFrameworkBundleResponse) => void;
type GrpcUpsertTaxonomySchemeCallback = (error: grpc.ServiceError | null, response: UpsertTaxonomySchemeResponse) => void;
type GrpcGetTaxonomySchemeCallback = (error: grpc.ServiceError | null, response: GetTaxonomySchemeResponse) => void;
type GrpcListTaxonomySchemesCallback = (error: grpc.ServiceError | null, response: ListTaxonomySchemesResponse) => void;
type GrpcUpsertEvidencePolicyRuleCallback = (error: grpc.ServiceError | null, response: UpsertEvidencePolicyRuleResponse) => void;
type GrpcGetEvidencePolicyRuleCallback = (error: grpc.ServiceError | null, response: GetEvidencePolicyRuleResponse) => void;
type GrpcListEvidencePolicyRulesCallback = (error: grpc.ServiceError | null, response: ListEvidencePolicyRulesResponse) => void;
type GrpcUpsertAssertionPolicyRuleCallback = (error: grpc.ServiceError | null, response: UpsertAssertionPolicyRuleResponse) => void;
type GrpcGetAssertionPolicyRuleCallback = (error: grpc.ServiceError | null, response: GetAssertionPolicyRuleResponse) => void;
type GrpcListAssertionPolicyRulesCallback = (error: grpc.ServiceError | null, response: ListAssertionPolicyRulesResponse) => void;
type GrpcUpsertReviewPolicyCallback = (error: grpc.ServiceError | null, response: UpsertReviewPolicyResponse) => void;
type GrpcGetReviewPolicyCallback = (error: grpc.ServiceError | null, response: GetReviewPolicyResponse) => void;
type GrpcListReviewPoliciesCallback = (error: grpc.ServiceError | null, response: ListReviewPoliciesResponse) => void;
type GrpcUpsertEvidenceCallback = (error: grpc.ServiceError | null, response: UpsertEvidenceResponse) => void;
type GrpcGetEvidenceCallback = (error: grpc.ServiceError | null, response: GetEvidenceResponse) => void;
type GrpcSearchEvidenceCallback = (error: grpc.ServiceError | null, response: SearchEvidenceResponse) => void;
type GrpcUpsertEvidenceLocatorCallback = (error: grpc.ServiceError | null, response: UpsertEvidenceLocatorResponse) => void;
type GrpcListEvidenceLocatorsCallback = (error: grpc.ServiceError | null, response: ListEvidenceLocatorsResponse) => void;
type GrpcUpsertEvidenceDerivationCallback = (error: grpc.ServiceError | null, response: UpsertEvidenceDerivationResponse) => void;
type GrpcListEvidenceDerivationsCallback = (error: grpc.ServiceError | null, response: ListEvidenceDerivationsResponse) => void;
type GrpcUpsertEvidenceClassificationCallback = (error: grpc.ServiceError | null, response: UpsertEvidenceClassificationResponse) => void;
type GrpcGetEvidenceClassificationCallback = (error: grpc.ServiceError | null, response: GetEvidenceClassificationResponse) => void;
type GrpcUpsertWikiPageCallback = (error: grpc.ServiceError | null, response: UpsertWikiPageResponse) => void;
type GrpcUpsertWikiPageLinkCallback = (error: grpc.ServiceError | null, response: UpsertWikiPageLinkResponse) => void;
type GrpcGetWikiPageCallback = (error: grpc.ServiceError | null, response: GetWikiPageResponse) => void;
type GrpcSearchWikiPagesCallback = (error: grpc.ServiceError | null, response: SearchWikiPagesResponse) => void;
type GrpcListWikiPagesCallback = (error: grpc.ServiceError | null, response: ListWikiPagesResponse) => void;
type GrpcReinforceWikiPageCallback = (error: grpc.ServiceError | null, response: ReinforceWikiPageResponse) => void;
type GrpcAppendWikiLogCallback = (error: grpc.ServiceError | null, response: AppendWikiLogResponse) => void;
type GrpcListWikiLogsCallback = (error: grpc.ServiceError | null, response: ListWikiLogsResponse) => void;
type GrpcLintWikiDomainCallback = (error: grpc.ServiceError | null, response: LintWikiDomainResponse) => void;

type GrpcGetEdgesAsOfCallback = (
  error: grpc.ServiceError | null,
  response: GetEdgesAsOfResponse
) => void;

type GrpcListPropertyRowsCallback = (
  error: grpc.ServiceError | null,
  response: ListPropertyRowsResponse
) => void;

type GrpcUpsertEntityCallback = (
  error: grpc.ServiceError | null,
  response: UpsertEntityResponse
) => void;

type GrpcGetEntityCallback = (
  error: grpc.ServiceError | null,
  response: GetEntityResponse
) => void;

type GrpcListEntitiesCallback = (
  error: grpc.ServiceError | null,
  response: ListEntitiesResponse
) => void;

type GrpcWriteSnapshotCallback = (
  error: grpc.ServiceError | null,
  response: WriteSnapshotResponse
) => void;

type GrpcGetLatestSnapshotCallback = (
  error: grpc.ServiceError | null,
  response: GetLatestSnapshotResponse
) => void;

type GrpcCreateArtifactCallback = (
  error: grpc.ServiceError | null,
  response: CreateArtifactResponse
) => void;

type GrpcCreateArtifactVersionCallback = (
  error: grpc.ServiceError | null,
  response: CreateArtifactVersionResponse
) => void;

type GrpcGetArtifactVersionAsOfCallback = (
  error: grpc.ServiceError | null,
  response: GetArtifactVersionAsOfResponse
) => void;

type GrpcGetArtifactVersionByIdCallback = (
  error: grpc.ServiceError | null,
  response: GetArtifactVersionByIdResponse
) => void;

type GrpcUpsertDecisionCallback = (
  error: grpc.ServiceError | null,
  response: UpsertDecisionResponse
) => void;

type GrpcInsertDecisionEvidenceCallback = (
  error: grpc.ServiceError | null,
  response: InsertDecisionEvidenceResponse
) => void;

type GrpcFindDecisionCallback = (
  error: grpc.ServiceError | null,
  response: FindDecisionResponse
) => void;

type GrpcListDecisionEvidenceCallback = (
  error: grpc.ServiceError | null,
  response: ListDecisionEvidenceResponse
) => void;

type GrpcUpsertAssertionCallback = (
  error: grpc.ServiceError | null,
  response: UpsertAssertionResponse
) => void;

type GrpcGetAssertionCallback = (
  error: grpc.ServiceError | null,
  response: GetAssertionResponse
) => void;

type GrpcSearchAssertionsCallback = (
  error: grpc.ServiceError | null,
  response: SearchAssertionsResponse
) => void;

type GrpcUpsertAssertionEvidenceLinkCallback = (
  error: grpc.ServiceError | null,
  response: UpsertAssertionEvidenceLinkResponse
) => void;

type GrpcListAssertionEvidenceLinksCallback = (
  error: grpc.ServiceError | null,
  response: ListAssertionEvidenceLinksResponse
) => void;

type GrpcUpsertAssertionRelationCallback = (
  error: grpc.ServiceError | null,
  response: UpsertAssertionRelationResponse
) => void;

type GrpcListAssertionRelationsCallback = (
  error: grpc.ServiceError | null,
  response: ListAssertionRelationsResponse
) => void;

type GrpcInsertMemoryDecisionCallback = (
  error: grpc.ServiceError | null,
  response: InsertMemoryDecisionResponse
) => void;

type GrpcListRecentMemoryDecisionsCallback = (
  error: grpc.ServiceError | null,
  response: ListRecentMemoryDecisionsResponse
) => void;

type GrpcInsertMemoryEpisodeSummaryCallback = (
  error: grpc.ServiceError | null,
  response: InsertMemoryEpisodeSummaryResponse
) => void;

type GrpcListRecentMemoryEpisodeSummariesCallback = (
  error: grpc.ServiceError | null,
  response: ListRecentMemoryEpisodeSummariesResponse
) => void;

type GrpcInsertMemoryAnswerArtifactCallback = (
  error: grpc.ServiceError | null,
  response: InsertMemoryAnswerArtifactResponse
) => void;

type GrpcRecallMemoryAnswerArtifactsCallback = (
  error: grpc.ServiceError | null,
  response: RecallMemoryAnswerArtifactsResponse
) => void;

type GrpcInsertMemoryAnswerValidationCallback = (
  error: grpc.ServiceError | null,
  response: InsertMemoryAnswerValidationResponse
) => void;

type GrpcUpsertOntologyConceptCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyConceptResponse
) => void;
type GrpcGetOntologyConceptCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyConceptResponse
) => void;
type GrpcListOntologyConceptsCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyConceptsResponse
) => void;
type GrpcUpsertConceptAliasCallback = (
  error: grpc.ServiceError | null,
  response: UpsertConceptAliasResponse
) => void;
type GrpcListConceptAliasesCallback = (
  error: grpc.ServiceError | null,
  response: ListConceptAliasesResponse
) => void;
type GrpcUpsertOntologyEdgeCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyEdgeResponse
) => void;
type GrpcListOntologyEdgesCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyEdgesResponse
) => void;
type GrpcUpsertEventConceptLinkCallback = (
  error: grpc.ServiceError | null,
  response: UpsertEventConceptLinkResponse
) => void;
type GrpcListEventConceptLinksCallback = (
  error: grpc.ServiceError | null,
  response: ListEventConceptLinksResponse
) => void;
type GrpcUpsertOntologyObjectTypeCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyObjectTypeResponse
) => void;
type GrpcGetOntologyObjectTypeCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyObjectTypeResponse
) => void;
type GrpcListOntologyObjectTypesCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyObjectTypesResponse
) => void;
type GrpcUpsertOntologyConceptTypeAssignmentCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyConceptTypeAssignmentResponse
) => void;
type GrpcListOntologyConceptTypeAssignmentsCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyConceptTypeAssignmentsResponse
) => void;
type GrpcUpsertOntologyRelationTypeCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyRelationTypeResponse
) => void;
type GrpcGetOntologyRelationTypeCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyRelationTypeResponse
) => void;
type GrpcListOntologyRelationTypesCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyRelationTypesResponse
) => void;
type GrpcListOntologyFactsCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyFactsResponse
) => void;
type GrpcUpsertOntologyFactWithEvidenceCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyFactWithEvidenceResponse
) => void;
type GrpcUpsertSemanticBatchCallback = (
  error: grpc.ServiceError | null,
  response: UpsertSemanticBatchResponse
) => void;
type GrpcSearchOntologyConceptsCallback = (
  error: grpc.ServiceError | null,
  response: SearchOntologyConceptsResponse
) => void;
type GrpcSearchConceptAliasesCallback = (
  error: grpc.ServiceError | null,
  response: SearchConceptAliasesResponse
) => void;
type GrpcSearchOntologyFactsCallback = (
  error: grpc.ServiceError | null,
  response: SearchOntologyFactsResponse
) => void;
type GrpcGetOntologyConceptNeighborsCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyConceptNeighborsResponse
) => void;
type GrpcArchiveOntologyFactCallback = (
  error: grpc.ServiceError | null,
  response: ArchiveOntologyFactResponse
) => void;
type GrpcUpsertOntologyNormalizedTermCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyNormalizedTermResponse
) => void;
type GrpcGetOntologyNormalizedTermCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyNormalizedTermResponse
) => void;
type GrpcSearchOntologyNormalizedTermsCallback = (
  error: grpc.ServiceError | null,
  response: SearchOntologyNormalizedTermsResponse
) => void;
type GrpcUpsertOntologyTermClusterCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyTermClusterResponse
) => void;
type GrpcGetOntologyTermClusterCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyTermClusterResponse
) => void;
type GrpcListOntologyTermClustersCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyTermClustersResponse
) => void;
type GrpcUpsertOntologyClusterMemberCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyClusterMemberResponse
) => void;
type GrpcListOntologyClusterMembersCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyClusterMembersResponse
) => void;
type GrpcUpsertOntologyRawTermCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyRawTermResponse
) => void;
type GrpcGetOntologyRawTermCallback = (
  error: grpc.ServiceError | null,
  response: GetOntologyRawTermResponse
) => void;
type GrpcSearchOntologyRawTermsCallback = (
  error: grpc.ServiceError | null,
  response: SearchOntologyRawTermsResponse
) => void;
type GrpcUpsertOntologyRawTermCandidateCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyRawTermCandidateResponse
) => void;
type GrpcListOntologyRawTermCandidatesCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyRawTermCandidatesResponse
) => void;
type GrpcUpsertOntologyRelationCandidateCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyRelationCandidateResponse
) => void;
type GrpcListOntologyRelationCandidatesCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyRelationCandidatesResponse
) => void;
type GrpcUpsertOntologyRawTermNormalizationCallback = (
  error: grpc.ServiceError | null,
  response: UpsertOntologyRawTermNormalizationResponse
) => void;
type GrpcListOntologyRawTermNormalizationsCallback = (
  error: grpc.ServiceError | null,
  response: ListOntologyRawTermNormalizationsResponse
) => void;

// Governance Callbacks
type GrpcUpsertRuleCallback = (error: grpc.ServiceError | null, response: UpsertRuleResponse) => void;
type GrpcInsertAuthorityGrantCallback = (error: grpc.ServiceError | null, response: InsertAuthorityGrantResponse) => void;
type GrpcInsertRuleOverrideCallback = (error: grpc.ServiceError | null, response: InsertRuleOverrideResponse) => void;
type GrpcFindAuthorityAsOfCallback = (error: grpc.ServiceError | null, response: FindAuthorityAsOfResponse) => void;
type GrpcListRuleOverridesAsOfCallback = (error: grpc.ServiceError | null, response: ListRuleOverridesAsOfResponse) => void;
type GrpcGetActiveOntologyCaseByTitleCallback = (error: grpc.ServiceError | null, response: GetActiveOntologyCaseByTitleResponse) => void;
type GrpcGetActiveOntologyAlertByRuleKeyCallback = (error: grpc.ServiceError | null, response: GetActiveOntologyAlertByRuleKeyResponse) => void;
type GrpcLinkOntologyAlertFactCallback = (error: grpc.ServiceError | null, response: Empty) => void;
type GrpcUpsertDomainStreamBindingCallback = (
  error: grpc.ServiceError | null,
  response: { binding?: DomainStreamBindingRecord }
) => void;
type GrpcListDomainStreamBindingsCallback = (
  error: grpc.ServiceError | null,
  response: { bindings?: DomainStreamBindingRecord[] }
) => void;

type GrpcGatewayBackendService = grpc.Client & {
  SearchQuery(
    request: GatewayBackendProtoRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcSearchQueryCallback
  ): void;
  UpsertDomainStreamBinding(
    request: DomainStreamBindingUpsertRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertDomainStreamBindingCallback
  ): void;
  ListDomainStreamBindings(
    request: DomainStreamBindingListQuery,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListDomainStreamBindingsCallback
  ): void;
  IndexEvent(
    request: IndexEventRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcIndexEventCallback
  ): void;
  AppendEvent(
    request: AppendEventRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcAppendEventCallback
  ): void;
  GetEvents(
    request: GetEventsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEventsCallback
  ): void;
  GetEventSentences(
    request: GetEventSentencesRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEventSentencesCallback
  ): void;
  UpsertProperty(
    request: UpsertPropertyRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertPropertyCallback
  ): void;
  GetPropertyAsOf(
    request: GetPropertyAsOfRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetPropertyAsOfCallback
  ): void;
  UpsertEdge(
    request: UpsertEdgeRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEdgeCallback
  ): void;
  GetEdgesAsOf(
    request: GetEdgesAsOfRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEdgesAsOfCallback
  ): void;
  ListPropertyRows(
    request: ListPropertyRowsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListPropertyRowsCallback
  ): void;
  UpsertEntity(
    request: UpsertEntityRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEntityCallback
  ): void;
  GetEntity(
    request: GetEntityRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEntityCallback
  ): void;
  ListEntities(
    request: ListEntitiesRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListEntitiesCallback
  ): void;
  WriteSnapshot(
    request: WriteSnapshotRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcWriteSnapshotCallback
  ): void;
  GetLatestSnapshot(
    request: GetLatestSnapshotRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetLatestSnapshotCallback
  ): void;
  CreateArtifact(
    request: CreateArtifactRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcCreateArtifactCallback
  ): void;
  CreateArtifactVersion(
    request: CreateArtifactVersionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcCreateArtifactVersionCallback
  ): void;
  GetArtifactVersionAsOf(
    request: GetArtifactVersionAsOfRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetArtifactVersionAsOfCallback
  ): void;
  GetArtifactVersionById(
    request: GetArtifactVersionByIdRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetArtifactVersionByIdCallback
  ): void;
  UpsertDecision(
    request: UpsertDecisionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertDecisionCallback
  ): void;
  InsertDecisionEvidence(
    request: InsertDecisionEvidenceRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcInsertDecisionEvidenceCallback
  ): void;
  FindDecision(
    request: FindDecisionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcFindDecisionCallback
  ): void;
  ListDecisionEvidence(
    request: ListDecisionEvidenceRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListDecisionEvidenceCallback
  ): void;
  UpsertAssertion(
    request: UpsertAssertionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertAssertionCallback
  ): void;
  GetAssertion(
    request: GetAssertionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetAssertionCallback
  ): void;
  SearchAssertions(
    request: SearchAssertionsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcSearchAssertionsCallback
  ): void;
  UpsertEvidence(
    request: UpsertEvidenceRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEvidenceCallback
  ): void;
  GetEvidence(
    request: GetEvidenceRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEvidenceCallback
  ): void;
  SearchEvidence(
    request: SearchEvidenceRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcSearchEvidenceCallback
  ): void;
  UpsertEvidenceLocator(
    request: UpsertEvidenceLocatorRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEvidenceLocatorCallback
  ): void;
  ListEvidenceLocators(
    request: ListEvidenceLocatorsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListEvidenceLocatorsCallback
  ): void;
  UpsertEvidenceDerivation(
    request: UpsertEvidenceDerivationRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEvidenceDerivationCallback
  ): void;
  ListEvidenceDerivations(
    request: ListEvidenceDerivationsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListEvidenceDerivationsCallback
  ): void;
  UpsertEvidenceClassification(
    request: UpsertEvidenceClassificationRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertEvidenceClassificationCallback
  ): void;
  GetEvidenceClassification(
    request: GetEvidenceClassificationRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcGetEvidenceClassificationCallback
  ): void;
  UpsertAssertionEvidenceLink(
    request: UpsertAssertionEvidenceLinkRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertAssertionEvidenceLinkCallback
  ): void;
  ListAssertionEvidenceLinks(
    request: ListAssertionEvidenceLinksRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListAssertionEvidenceLinksCallback
  ): void;
  UpsertAssertionRelation(
    request: UpsertAssertionRelationRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcUpsertAssertionRelationCallback
  ): void;
  ListAssertionRelations(
    request: ListAssertionRelationsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListAssertionRelationsCallback
  ): void;
  InsertMemoryDecision(
    request: InsertMemoryDecisionRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcInsertMemoryDecisionCallback
  ): void;
  ListRecentMemoryDecisions(
    request: ListRecentMemoryDecisionsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListRecentMemoryDecisionsCallback
  ): void;
  InsertMemoryEpisodeSummary(
    request: InsertMemoryEpisodeSummaryRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcInsertMemoryEpisodeSummaryCallback
  ): void;
  ListRecentMemoryEpisodeSummaries(
    request: ListRecentMemoryEpisodeSummariesRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcListRecentMemoryEpisodeSummariesCallback
  ): void;
  InsertMemoryAnswerArtifact(
    request: InsertMemoryAnswerArtifactRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcInsertMemoryAnswerArtifactCallback
  ): void;
  RecallMemoryAnswerArtifacts(
    request: RecallMemoryAnswerArtifactsRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcRecallMemoryAnswerArtifactsCallback
  ): void;
  InsertMemoryAnswerValidation(
    request: InsertMemoryAnswerValidationRequest,
    metadata: grpc.Metadata,
    options: grpc.CallOptions,
    callback: GrpcInsertMemoryAnswerValidationCallback
  ): void;
  UpsertOntologyConcept(request: UpsertOntologyConceptRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyConceptCallback): void;
  GetOntologyConcept(request: GetOntologyConceptRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyConceptCallback): void;
  ListOntologyConcepts(request: ListOntologyConceptsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyConceptsCallback): void;
  UpsertConceptAlias(request: UpsertConceptAliasRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertConceptAliasCallback): void;
  ListConceptAliases(request: ListConceptAliasesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListConceptAliasesCallback): void;
  UpsertOntologyEdge(request: UpsertOntologyEdgeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyEdgeCallback): void;
  ListOntologyEdges(request: ListOntologyEdgesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyEdgesCallback): void;
  UpsertEventConceptLink(request: UpsertEventConceptLinkRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertEventConceptLinkCallback): void;
  ListEventConceptLinks(request: ListEventConceptLinksRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListEventConceptLinksCallback): void;
  UpsertOntologyObjectType(request: UpsertOntologyObjectTypeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyObjectTypeCallback): void;
  GetOntologyObjectType(request: GetOntologyObjectTypeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyObjectTypeCallback): void;
  ListOntologyObjectTypes(request: ListOntologyObjectTypesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyObjectTypesCallback): void;
  UpsertOntologyConceptTypeAssignment(request: UpsertOntologyConceptTypeAssignmentRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyConceptTypeAssignmentCallback): void;
  ListOntologyConceptTypeAssignments(request: ListOntologyConceptTypeAssignmentsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyConceptTypeAssignmentsCallback): void;
  UpsertOntologyRelationType(request: UpsertOntologyRelationTypeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyRelationTypeCallback): void;
  GetOntologyRelationType(request: GetOntologyRelationTypeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyRelationTypeCallback): void;
  ListOntologyRelationTypes(request: ListOntologyRelationTypesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyRelationTypesCallback): void;
  ListOntologyFacts(request: ListOntologyFactsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyFactsCallback): void;
  UpsertOntologyFactWithEvidence(request: UpsertOntologyFactWithEvidenceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyFactWithEvidenceCallback): void;
  UpsertSemanticBatch(request: UpsertSemanticBatchRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertSemanticBatchCallback): void;
  GetSemanticStatement(request: GetSemanticStatementRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: (error: grpc.ServiceError | null, response: GetSemanticStatementResponse) => void): void;
  ListSemanticStatements(request: ListSemanticStatementsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: (error: grpc.ServiceError | null, response: ListSemanticStatementsResponse) => void): void;
  SetSemanticStatementStatus(request: SetSemanticStatementStatusRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: (error: grpc.ServiceError | null, response: SetSemanticStatementStatusResponse) => void): void;
  GetSemanticStatementProvenance(request: GetSemanticStatementProvenanceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: (error: grpc.ServiceError | null, response: GetSemanticStatementProvenanceResponse) => void): void;
  GetSemanticStatementsByEvidence(request: GetSemanticStatementsByEvidenceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: (error: grpc.ServiceError | null, response: GetSemanticStatementsByEvidenceResponse) => void): void;
  SearchOntologyConcepts(request: SearchOntologyConceptsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchOntologyConceptsCallback): void;
  SearchConceptAliases(request: SearchConceptAliasesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchConceptAliasesCallback): void;
  SearchOntologyFacts(request: SearchOntologyFactsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchOntologyFactsCallback): void;
  GetOntologyConceptNeighbors(request: GetOntologyConceptNeighborsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyConceptNeighborsCallback): void;
  ArchiveOntologyFact(request: ArchiveOntologyFactRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcArchiveOntologyFactCallback): void;
  UpsertTermMappingRegistry(request: UpsertTermMappingRegistryRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertTermMappingRegistryCallback): void;
  GetTermMappingRegistry(request: GetTermMappingRegistryRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetTermMappingRegistryCallback): void;
  ListTermMappingRegistries(request: ListTermMappingRegistriesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListTermMappingRegistriesCallback): void;
  UpsertOntologyNormalizedTerm(request: UpsertOntologyNormalizedTermRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyNormalizedTermCallback): void;
  GetOntologyNormalizedTerm(request: GetOntologyNormalizedTermRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyNormalizedTermCallback): void;
  SearchOntologyNormalizedTerms(request: SearchOntologyNormalizedTermsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchOntologyNormalizedTermsCallback): void;
  UpsertOntologyTermCluster(request: UpsertOntologyTermClusterRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyTermClusterCallback): void;
  GetOntologyTermCluster(request: GetOntologyTermClusterRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyTermClusterCallback): void;
  ListOntologyTermClusters(request: ListOntologyTermClustersRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyTermClustersCallback): void;
  UpsertOntologyClusterMember(request: UpsertOntologyClusterMemberRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyClusterMemberCallback): void;
  ListOntologyClusterMembers(request: ListOntologyClusterMembersRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyClusterMembersCallback): void;
  UpsertOntologyRelationCandidate(request: UpsertOntologyRelationCandidateRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyRelationCandidateCallback): void;
  ListOntologyRelationCandidates(request: ListOntologyRelationCandidatesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyRelationCandidatesCallback): void;
  UpsertOntologyRawTerm(request: UpsertOntologyRawTermRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyRawTermCallback): void;
  GetOntologyRawTerm(request: GetOntologyRawTermRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyRawTermCallback): void;
  SearchOntologyRawTerms(request: SearchOntologyRawTermsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchOntologyRawTermsCallback): void;
  UpsertOntologyRawTermCandidate(request: UpsertOntologyRawTermCandidateRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyRawTermCandidateCallback): void;
  ListOntologyRawTermCandidates(request: ListOntologyRawTermCandidatesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyRawTermCandidatesCallback): void;
  UpsertOntologyRawTermNormalization(request: UpsertOntologyRawTermNormalizationRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyRawTermNormalizationCallback): void;
  ListOntologyRawTermNormalizations(request: ListOntologyRawTermNormalizationsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyRawTermNormalizationsCallback): void;
  UpsertTermMappingRule(request: UpsertTermMappingRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertTermMappingRuleCallback): void;
  GetTermMappingRule(request: GetTermMappingRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetTermMappingRuleCallback): void;
  SearchTermMappingRules(request: SearchTermMappingRulesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchTermMappingRulesCallback): void;
  UpsertTermMappingRuleEvidence(request: UpsertTermMappingRuleEvidenceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertTermMappingRuleEvidenceCallback): void;
  ListTermMappingRuleEvidence(request: ListTermMappingRuleEvidenceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListTermMappingRuleEvidenceCallback): void;
  InterpretTerm(request: InterpretTermRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInterpretTermCallback): void;
  InterpretTermBatch(request: InterpretTermBatchRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInterpretTermBatchCallback): void;

  // Governance
  UpsertRule(request: UpsertRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertRuleCallback): void;
  InsertAuthorityGrant(request: InsertAuthorityGrantRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertAuthorityGrantCallback): void;
  InsertRuleOverride(request: InsertRuleOverrideRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertRuleOverrideCallback): void;
  FindAuthorityAsOf(request: FindAuthorityAsOfRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcFindAuthorityAsOfCallback): void;
  ListRuleOverridesAsOf(request: ListRuleOverridesAsOfRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListRuleOverridesAsOfCallback): void;
  UpsertMethodologyFramework(request: UpsertMethodologyFrameworkRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertMethodologyFrameworkCallback): void;
  GetMethodologyFramework(request: GetMethodologyFrameworkRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetMethodologyFrameworkCallback): void;
  ListMethodologyFrameworks(request: ListMethodologyFrameworksRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListMethodologyFrameworksCallback): void;
  GetMethodologyFrameworkBundle(request: GetMethodologyFrameworkBundleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetMethodologyFrameworkBundleCallback): void;
  UpsertTaxonomyScheme(request: UpsertTaxonomySchemeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertTaxonomySchemeCallback): void;
  GetTaxonomyScheme(request: GetTaxonomySchemeRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetTaxonomySchemeCallback): void;
  ListTaxonomySchemes(request: ListTaxonomySchemesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListTaxonomySchemesCallback): void;
  UpsertEvidencePolicyRule(request: UpsertEvidencePolicyRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertEvidencePolicyRuleCallback): void;
  GetEvidencePolicyRule(request: GetEvidencePolicyRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetEvidencePolicyRuleCallback): void;
  ListEvidencePolicyRules(request: ListEvidencePolicyRulesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListEvidencePolicyRulesCallback): void;
  UpsertAssertionPolicyRule(request: UpsertAssertionPolicyRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertAssertionPolicyRuleCallback): void;
  GetAssertionPolicyRule(request: GetAssertionPolicyRuleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetAssertionPolicyRuleCallback): void;
  ListAssertionPolicyRules(request: ListAssertionPolicyRulesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListAssertionPolicyRulesCallback): void;
  UpsertReviewPolicy(request: UpsertReviewPolicyRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertReviewPolicyCallback): void;
  GetReviewPolicy(request: GetReviewPolicyRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetReviewPolicyCallback): void;
  ListReviewPolicies(request: ListReviewPoliciesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListReviewPoliciesCallback): void;
  ReviewOntologyFact(request: ReviewOntologyFactRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcReviewOntologyFactCallback): void;
  GetOntologyFact(request: GetOntologyFactRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyFactCallback): void;
  ListOntologyFactReviews(request: ListOntologyFactReviewsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyFactReviewsCallback): void;
  ListOntologyFactEvidence(request: ListOntologyFactEvidenceRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyFactEvidenceCallback): void;
  ListOntologyFactLinkedCases(request: ListOntologyFactLinkedCasesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyFactLinkedCasesCallback): void;
  ListOntologyFactLinkedAlerts(request: ListOntologyFactLinkedAlertsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyFactLinkedAlertsCallback): void;
  SelectOntologyFactsForBulkReview(request: SelectOntologyFactsForBulkReviewRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSelectOntologyFactsForBulkReviewCallback): void;
  InsertOntologyCase(request: InsertOntologyCaseRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertOntologyCaseCallback): void;
  GetOntologyCase(request: GetOntologyCaseRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyCaseCallback): void;
  ListOntologyCases(request: ListOntologyCasesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyCasesCallback): void;
  UpdateOntologyCase(request: UpdateOntologyCaseRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpdateOntologyCaseCallback): void;
  LinkOntologyCaseFact(request: LinkOntologyCaseFactRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcLinkOntologyCaseFactCallback): void;
  ListOntologyCaseFacts(request: ListOntologyCaseFactsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyCaseFactsCallback): void;
  InsertOntologyCaseDecision(request: InsertOntologyCaseDecisionRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertOntologyCaseDecisionCallback): void;
  ListOntologyCaseDecisions(request: ListOntologyCaseDecisionsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyCaseDecisionsCallback): void;
  InsertOntologyCaseEvent(request: InsertOntologyCaseEventRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertOntologyCaseEventCallback): void;
  ListOntologyCaseEvents(request: ListOntologyCaseEventsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyCaseEventsCallback): void;
  InsertOntologyAlert(request: InsertOntologyAlertRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertOntologyAlertCallback): void;
  GetOntologyAlertDetail(request: GetOntologyAlertDetailRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyAlertDetailCallback): void;
  ListOntologyAlerts(request: ListOntologyAlertsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyAlertsCallback): void;
  UpdateOntologyAlert(request: UpdateOntologyAlertRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpdateOntologyAlertCallback): void;
  RefreshTriggeredOntologyAlert(request: RefreshTriggeredOntologyAlertRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcRefreshTriggeredOntologyAlertCallback): void;
  UpsertOntologyOpsRuleConfig(request: UpsertOntologyOpsRuleConfigRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertOntologyOpsRuleConfigCallback): void;
  ListOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyOpsRuleConfigCallback): void;
  InsertOntologyOpsRuleRun(request: InsertOntologyOpsRuleRunRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcInsertOntologyOpsRuleRunCallback): void;
  GetOntologyOpsRun(request: GetOntologyOpsRunRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetOntologyOpsRunCallback): void;
  ListOntologyOpsRuns(request: ListOntologyOpsRunsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListOntologyOpsRunsCallback): void;
  ListApplicableOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListApplicableOntologyOpsRuleConfigCallback): void;
  ListStalePendingOntologyCandidates(request: ListStalePendingOntologyCandidatesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListStalePendingOntologyCandidatesCallback): void;
  ListConflictPredicateOntologyCandidates(request: ListConflictPredicateOntologyCandidatesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListConflictPredicateOntologyCandidatesCallback): void;
  GetActiveOntologyCaseByTitle(request: GetActiveOntologyCaseByTitleRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetActiveOntologyCaseByTitleCallback): void;
  GetActiveOntologyAlertByRuleKey(request: GetActiveOntologyAlertByRuleKeyRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetActiveOntologyAlertByRuleKeyCallback): void;
  LinkOntologyAlertFact(request: LinkOntologyAlertFactRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcLinkOntologyAlertFactCallback): void;
  UpsertWikiPage(request: UpsertWikiPageRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertWikiPageCallback): void;
  UpsertWikiPageLink(request: UpsertWikiPageLinkRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcUpsertWikiPageLinkCallback): void;
  GetWikiPage(request: GetWikiPageRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcGetWikiPageCallback): void;
  SearchWikiPages(request: SearchWikiPagesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcSearchWikiPagesCallback): void;
  ListWikiPages(request: ListWikiPagesRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListWikiPagesCallback): void;
  ReinforceWikiPage(request: ReinforceWikiPageRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcReinforceWikiPageCallback): void;
  AppendWikiLog(request: AppendWikiLogRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcAppendWikiLogCallback): void;
  ListWikiLogs(request: ListWikiLogsRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcListWikiLogsCallback): void;
  LintWikiDomain(request: LintWikiDomainRequest, metadata: grpc.Metadata, options: grpc.CallOptions, callback: GrpcLintWikiDomainCallback): void;
};

export function createGatewayBackendClient(
  config: GatewayBackendConfig & { transport?: GatewayBackendTransport }
): GatewayBackendClient {
  const transport = config.transport ?? createGrpcTransport(config);

  return {
    async searchQuery(request: SearchQueryRequest, traceId = ''): Promise<SearchQueryResult> {
      try {
        const response = await transport.searchQuery(toProtoRequest(request, traceId), {
          timeoutMs: config.timeoutMs
        });
        return {
          hits: (response.hits ?? []).map(fromProtoHit),
          resolved_stream_ids: response.resolved_stream_ids ?? response.resolvedStreamIds ?? []
        };
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertDomainStreamBinding(request) {
      try {
        const response = await transport.upsertDomainStreamBinding(request, {
          timeoutMs: config.timeoutMs
        });
        return fromProtoDomainStreamBinding(response.binding ?? {});
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listDomainStreamBindings(request) {
      try {
        const response = await transport.listDomainStreamBindings(request, {
          timeoutMs: config.timeoutMs
        });
        return (response.bindings ?? []).map(fromProtoDomainStreamBinding);
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async indexEvent(request: IndexEventRequest): Promise<string> {
      try {
        const response = await transport.indexEvent(request, {
          timeoutMs: config.timeoutMs
        });
        return response.doc_id ?? response.docId ?? '';
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async appendEvent(request: AppendEventRequest): Promise<AppendEventResponse> {
      try {
        return await transport.appendEvent(request, {
          timeoutMs: config.timeoutMs
        });
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEvents(request: GetEventsRequest): Promise<EventItem[]> {
      try {
        const response = await transport.getEvents(request, {
          timeoutMs: config.timeoutMs
        });
        return response.events ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEventSentences(request: GetEventSentencesRequest): Promise<EventSentenceRecord[]> {
      try {
        const response = await transport.getEventSentences(request, {
          timeoutMs: config.timeoutMs
        });
        return response.sentences ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertProperty(request: UpsertPropertyRequest): Promise<PropertyRecord> {
      try {
        const response = await transport.upsertProperty(request, {
          timeoutMs: config.timeoutMs
        });
        return response.property;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getPropertyAsOf(request: GetPropertyAsOfRequest): Promise<PropertyRecord | undefined> {
      try {
        const response = await transport.getPropertyAsOf(request, {
          timeoutMs: config.timeoutMs
        });
        return response.property;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEdge(request: UpsertEdgeRequest): Promise<EdgeRecord> {
      try {
        const response = await transport.upsertEdge(request, {
          timeoutMs: config.timeoutMs
        });
        return response.edge;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEdgesAsOf(request: GetEdgesAsOfRequest): Promise<EdgeRecord[]> {
      try {
        const response = await transport.getEdgesAsOf(request, {
          timeoutMs: config.timeoutMs
        });
        return response.edges ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listPropertyRows(request: ListPropertyRowsRequest): Promise<PropertyRecord[]> {
      try {
        const response = await transport.listPropertyRows(request, {
          timeoutMs: config.timeoutMs
        });
        return response.properties ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEntity(request: UpsertEntityRequest): Promise<EntityRecord> {
      try {
        const response = await transport.upsertEntity(request, {
          timeoutMs: config.timeoutMs
        });
        return response.entity;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEntity(request: GetEntityRequest): Promise<EntityRecord | undefined> {
      try {
        const response = await transport.getEntity(request, {
          timeoutMs: config.timeoutMs
        });
        return response.entity;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listEntities(request: ListEntitiesRequest): Promise<EntityRecord[]> {
      try {
        const response = await transport.listEntities(request, {
          timeoutMs: config.timeoutMs
        });
        return response.entities ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async writeSnapshot(request: WriteSnapshotRequest): Promise<SnapshotRecord> {
      try {
        const response = await transport.writeSnapshot(request, {
          timeoutMs: config.timeoutMs
        });
        return response.snapshot;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getLatestSnapshot(request: GetLatestSnapshotRequest): Promise<SnapshotRecord | undefined> {
      try {
        const response = await transport.getLatestSnapshot(request, {
          timeoutMs: config.timeoutMs
        });
        return response.snapshot;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async createArtifact(request: CreateArtifactRequest): Promise<ArtifactRecord> {
      try {
        const response = await transport.createArtifact(request, {
          timeoutMs: config.timeoutMs
        });
        return response.artifact;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async createArtifactVersion(request: CreateArtifactVersionRequest): Promise<ArtifactVersionRecord> {
      try {
        const response = await transport.createArtifactVersion(request, {
          timeoutMs: config.timeoutMs
        });
        return response.version;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getArtifactVersionAsOf(request: GetArtifactVersionAsOfRequest): Promise<ArtifactVersionRecord | undefined> {
      try {
        const response = await transport.getArtifactVersionAsOf(request, {
          timeoutMs: config.timeoutMs
        });
        return response.version;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getArtifactVersionById(request: GetArtifactVersionByIdRequest): Promise<ArtifactVersionRecord | undefined> {
      try {
        const response = await transport.getArtifactVersionById(request, {
          timeoutMs: config.timeoutMs
        });
        return response.version;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertDecision(request: UpsertDecisionRequest): Promise<DecisionRecord> {
      try {
        const response = await transport.upsertDecision(request, {
          timeoutMs: config.timeoutMs
        });
        return response.decision;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async insertDecisionEvidence(request: InsertDecisionEvidenceRequest): Promise<DecisionEvidenceRecord> {
      try {
        const response = await transport.insertDecisionEvidence(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async findDecision(request: FindDecisionRequest): Promise<DecisionRecord | undefined> {
      try {
        const response = await transport.findDecision(request, {
          timeoutMs: config.timeoutMs
        });
        return response.decision;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listDecisionEvidence(request: ListDecisionEvidenceRequest): Promise<DecisionEvidenceRecord[]> {
      try {
        const response = await transport.listDecisionEvidence(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertAssertion(request: UpsertAssertionRequest): Promise<AssertionRecord> {
      try {
        const response = await transport.upsertAssertion(request, {
          timeoutMs: config.timeoutMs
        });
        return response.assertion!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getAssertion(request: GetAssertionRequest): Promise<AssertionRecord | undefined> {
      try {
        const response = await transport.getAssertion(request, {
          timeoutMs: config.timeoutMs
        });
        return response.assertion;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async searchAssertions(request: SearchAssertionsRequest): Promise<AssertionRecord[]> {
      try {
        const response = await transport.searchAssertions(request, {
          timeoutMs: config.timeoutMs
        });
        return response.assertions ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEvidence(request: UpsertEvidenceRequest): Promise<EvidenceRecord> {
      try {
        const response = await transport.upsertEvidence(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEvidence(request: GetEvidenceRequest): Promise<EvidenceRecord | undefined> {
      try {
        const response = await transport.getEvidence(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async searchEvidence(request: SearchEvidenceRequest): Promise<EvidenceRecord[]> {
      try {
        const response = await transport.searchEvidence(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEvidenceLocator(
      request: UpsertEvidenceLocatorRequest
    ): Promise<EvidenceLocatorRecord> {
      try {
        const response = await transport.upsertEvidenceLocator(request, {
          timeoutMs: config.timeoutMs
        });
        return response.locator!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listEvidenceLocators(
      request: ListEvidenceLocatorsRequest
    ): Promise<EvidenceLocatorRecord[]> {
      try {
        const response = await transport.listEvidenceLocators(request, {
          timeoutMs: config.timeoutMs
        });
        return response.locators ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEvidenceDerivation(
      request: UpsertEvidenceDerivationRequest
    ): Promise<EvidenceDerivationRecord> {
      try {
        const response = await transport.upsertEvidenceDerivation(request, {
          timeoutMs: config.timeoutMs
        });
        return response.derivation!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listEvidenceDerivations(
      request: ListEvidenceDerivationsRequest
    ): Promise<EvidenceDerivationRecord[]> {
      try {
        const response = await transport.listEvidenceDerivations(request, {
          timeoutMs: config.timeoutMs
        });
        return response.derivations ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertEvidenceClassification(
      request: UpsertEvidenceClassificationRequest
    ): Promise<EvidenceClassificationRecord> {
      try {
        const response = await transport.upsertEvidenceClassification(request, {
          timeoutMs: config.timeoutMs
        });
        return response.classification!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async getEvidenceClassification(
      request: GetEvidenceClassificationRequest
    ): Promise<EvidenceClassificationRecord | undefined> {
      try {
        const response = await transport.getEvidenceClassification(request, {
          timeoutMs: config.timeoutMs
        });
        return response.classification;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertAssertionEvidenceLink(
      request: UpsertAssertionEvidenceLinkRequest
    ): Promise<AssertionEvidenceLinkRecord> {
      try {
        const response = await transport.upsertAssertionEvidenceLink(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence_link!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listAssertionEvidenceLinks(
      request: ListAssertionEvidenceLinksRequest
    ): Promise<AssertionEvidenceLinkRecord[]> {
      try {
        const response = await transport.listAssertionEvidenceLinks(request, {
          timeoutMs: config.timeoutMs
        });
        return response.evidence_links ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertAssertionRelation(
      request: UpsertAssertionRelationRequest
    ): Promise<AssertionRelationRecord> {
      try {
        const response = await transport.upsertAssertionRelation(request, {
          timeoutMs: config.timeoutMs
        });
        return response.relation!;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async listAssertionRelations(
      request: ListAssertionRelationsRequest
    ): Promise<AssertionRelationRecord[]> {
      try {
        const response = await transport.listAssertionRelations(request, {
          timeoutMs: config.timeoutMs
        });
        return response.relations ?? [];
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async insertMemoryDecision(request: InsertMemoryDecisionRequest): Promise<MemoryDecisionRecord> {
      try {
        const response = await transport.insertMemoryDecision(request, {
          timeoutMs: config.timeoutMs
        });
        return response.decision;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async listRecentMemoryDecisions(
      request: ListRecentMemoryDecisionsRequest
    ): Promise<MemoryDecisionRecord[]> {
      try {
        const response = await transport.listRecentMemoryDecisions(request, {
          timeoutMs: config.timeoutMs
        });
        return response.decisions;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async insertMemoryEpisodeSummary(
      request: InsertMemoryEpisodeSummaryRequest
    ): Promise<MemoryEpisodeSummaryRecord> {
      try {
        const response = await transport.insertMemoryEpisodeSummary(request, {
          timeoutMs: config.timeoutMs
        });
        return response.summary;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async listRecentMemoryEpisodeSummaries(
      request: ListRecentMemoryEpisodeSummariesRequest
    ): Promise<MemoryEpisodeSummaryRecord[]> {
      try {
        const response = await transport.listRecentMemoryEpisodeSummaries(request, {
          timeoutMs: config.timeoutMs
        });
        return response.summaries;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async insertMemoryAnswerArtifact(
      request: InsertMemoryAnswerArtifactRequest
    ): Promise<MemoryAnswerArtifactRecord> {
      try {
        const response = await transport.insertMemoryAnswerArtifact(request, {
          timeoutMs: config.timeoutMs
        });
        return response.artifact;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async recallMemoryAnswerArtifacts(
      request: RecallMemoryAnswerArtifactsRequest
    ): Promise<MemoryAnswerArtifactRecord[]> {
      try {
        const response = await transport.recallMemoryAnswerArtifacts(request, {
          timeoutMs: config.timeoutMs
        });
        return response.artifacts;
      } catch (error) {
        throw toTdbError(error);
      }
    },

    async insertMemoryAnswerValidation(
      request: InsertMemoryAnswerValidationRequest
    ): Promise<MemoryAnswerValidationRecord> {
      try {
        const response = await transport.insertMemoryAnswerValidation(request, {
          timeoutMs: config.timeoutMs
        });
        return response.validation;
      } catch (error) {
        throw toTdbError(error);
      }
    },
    async upsertOntologyConcept(request: UpsertOntologyConceptRequest): Promise<OntologyConceptRecord> {
      try {
        const response = await transport.upsertOntologyConcept(request, { timeoutMs: config.timeoutMs });
        return response.concept!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyConcept(request: GetOntologyConceptRequest): Promise<OntologyConceptRecord | undefined> {
      try {
        const response = await transport.getOntologyConcept(request, { timeoutMs: config.timeoutMs });
        return response.concept;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyConcepts(request: ListOntologyConceptsRequest): Promise<OntologyConceptRecord[]> {
      try {
        const response = await transport.listOntologyConcepts(request, { timeoutMs: config.timeoutMs });
        return response.concepts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertConceptAlias(request: UpsertConceptAliasRequest): Promise<ConceptAliasRecord> {
      try {
        const response = await transport.upsertConceptAlias(request, { timeoutMs: config.timeoutMs });
        return response.alias!;
      } catch (error) { throw toTdbError(error); }
    },
    async listConceptAliases(request: ListConceptAliasesRequest): Promise<ConceptAliasRecord[]> {
      try {
        const response = await transport.listConceptAliases(request, { timeoutMs: config.timeoutMs });
        return response.aliases ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyEdge(request: UpsertOntologyEdgeRequest): Promise<OntologyEdgeRecord> {
      try {
        const response = await transport.upsertOntologyEdge(request, { timeoutMs: config.timeoutMs });
        return response.edge!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyEdges(request: ListOntologyEdgesRequest): Promise<OntologyEdgeRecord[]> {
      try {
        const response = await transport.listOntologyEdges(request, { timeoutMs: config.timeoutMs });
        return response.edges ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertEventConceptLink(request: UpsertEventConceptLinkRequest): Promise<EventConceptLinkRecord> {
      try {
        const response = await transport.upsertEventConceptLink(request, { timeoutMs: config.timeoutMs });
        return response.link!;
      } catch (error) { throw toTdbError(error); }
    },
    async listEventConceptLinks(request: ListEventConceptLinksRequest): Promise<EventConceptLinkRecord[]> {
      try {
        const response = await transport.listEventConceptLinks(request, { timeoutMs: config.timeoutMs });
        return response.links ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyObjectType(request: UpsertOntologyObjectTypeRequest): Promise<OntologyObjectTypeRecord> {
      try {
        const response = await transport.upsertOntologyObjectType(request, { timeoutMs: config.timeoutMs });
        return response.object_type!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyObjectType(request: GetOntologyObjectTypeRequest): Promise<OntologyObjectTypeRecord | undefined> {
      try {
        const response = await transport.getOntologyObjectType(request, { timeoutMs: config.timeoutMs });
        return response.object_type;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyObjectTypes(request: ListOntologyObjectTypesRequest): Promise<OntologyObjectTypeRecord[]> {
      try {
        const response = await transport.listOntologyObjectTypes(request, { timeoutMs: config.timeoutMs });
        return response.object_types ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyConceptTypeAssignment(request: UpsertOntologyConceptTypeAssignmentRequest): Promise<OntologyConceptTypeAssignmentRecord> {
      try {
        const response = await transport.upsertOntologyConceptTypeAssignment(request, { timeoutMs: config.timeoutMs });
        return response.assignment!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyConceptTypeAssignments(request: ListOntologyConceptTypeAssignmentsRequest): Promise<OntologyConceptTypeAssignmentRecord[]> {
      try {
        const response = await transport.listOntologyConceptTypeAssignments(request, { timeoutMs: config.timeoutMs });
        return response.assignments ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyRelationType(request: UpsertOntologyRelationTypeRequest): Promise<OntologyRelationTypeRecord> {
      try {
        const response = await transport.upsertOntologyRelationType(request, { timeoutMs: config.timeoutMs });
        return response.relation_type!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyRelationType(request: GetOntologyRelationTypeRequest): Promise<OntologyRelationTypeRecord | undefined> {
      try {
        const response = await transport.getOntologyRelationType(request, { timeoutMs: config.timeoutMs });
        return response.relation_type;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyRelationTypes(request: ListOntologyRelationTypesRequest): Promise<OntologyRelationTypeRecord[]> {
      try {
        const response = await transport.listOntologyRelationTypes(request, { timeoutMs: config.timeoutMs });
        return response.relation_types ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyFacts(request: ListOntologyFactsRequest): Promise<OntologyFactRecord[]> {
      try {
        const response = await transport.listOntologyFacts(request, { timeoutMs: config.timeoutMs });
        return response.facts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyFactWithEvidence(request: UpsertOntologyFactWithEvidenceRequest): Promise<{ fact: OntologyFactRecord; evidence_count: number }> {
      try {
        const response = await transport.upsertOntologyFactWithEvidence(request, { timeoutMs: config.timeoutMs });
        return { fact: response.fact!, evidence_count: response.evidence_count };
      } catch (error) { throw toTdbError(error); }
    },
    async upsertSemanticBatch(request: UpsertSemanticBatchRequest): Promise<UpsertSemanticBatchResponse> {
      try {
        return await transport.upsertSemanticBatch(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async getSemanticStatement(request: GetSemanticStatementRequest): Promise<GetSemanticStatementResponse> {
      try {
        const response = await transport.getSemanticStatement(request, { timeoutMs: config.timeoutMs });
        return {
          statement: response.statement ? mapSemanticStatement(response.statement) : undefined,
          qualifiers: (response.qualifiers ?? []).map(mapSemanticStatementQualifier)
        };
      } catch (error) { throw toTdbError(error); }
    },
    async listSemanticStatements(
      request: ListSemanticStatementsRequest
    ): Promise<ListSemanticStatementsResponse> {
      try {
        const response = await transport.listSemanticStatements(request, { timeoutMs: config.timeoutMs });
        return {
          statements: (response.statements ?? []).map((entry) => ({
            statement: entry.statement ? mapSemanticStatement(entry.statement) : undefined,
            qualifiers: (entry.qualifiers ?? []).map(mapSemanticStatementQualifier)
          }))
        };
      } catch (error) { throw toTdbError(error); }
    },
    async setSemanticStatementStatus(
      request: SetSemanticStatementStatusRequest
    ): Promise<SetSemanticStatementStatusResponse> {
      try {
        return await transport.setSemanticStatementStatus(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async getSemanticStatementProvenance(
      request: GetSemanticStatementProvenanceRequest
    ): Promise<GetSemanticStatementProvenanceResponse> {
      try {
        const response = await transport.getSemanticStatementProvenance(request, { timeoutMs: config.timeoutMs });
        return {
          references: (response.references ?? []).map(mapSemanticStatementReference)
        };
      } catch (error) { throw toTdbError(error); }
    },
    async getSemanticStatementsByEvidence(
      request: GetSemanticStatementsByEvidenceRequest
    ): Promise<GetSemanticStatementsByEvidenceResponse> {
      try {
        const response = await transport.getSemanticStatementsByEvidence(request, { timeoutMs: config.timeoutMs });
        return {
          references: (response.references ?? []).map(mapSemanticStatementReference)
        };
      } catch (error) { throw toTdbError(error); }
    },
    async searchOntologyConcepts(request: SearchOntologyConceptsRequest): Promise<OntologyConceptRecord[]> {
      try {
        const response = await transport.searchOntologyConcepts(request, { timeoutMs: config.timeoutMs });
        return response.concepts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async searchConceptAliases(request: SearchConceptAliasesRequest): Promise<ConceptAliasRecord[]> {
      try {
        const response = await transport.searchConceptAliases(request, { timeoutMs: config.timeoutMs });
        return response.aliases ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async searchOntologyFacts(request: SearchOntologyFactsRequest): Promise<OntologyFactRecord[]> {
      try {
        const response = await transport.searchOntologyFacts(request, { timeoutMs: config.timeoutMs });
        return response.facts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyConceptNeighbors(request: GetOntologyConceptNeighborsRequest): Promise<OntologyNeighborRecord[]> {
      try {
        const response = await transport.getOntologyConceptNeighbors(request, { timeoutMs: config.timeoutMs });
        return response.neighbors ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async archiveOntologyFact(request: ArchiveOntologyFactRequest): Promise<number> {
      try {
        const response = await transport.archiveOntologyFact(request, { timeoutMs: config.timeoutMs });
        return response.updated_rows;
      } catch (error) { throw toTdbError(error); }
    },
    async upsertTermMappingRegistry(request: UpsertTermMappingRegistryRequest): Promise<TermMappingRegistryRecord> {
      try {
        const response = await transport.upsertTermMappingRegistry(request, { timeoutMs: config.timeoutMs });
        return response.registry!;
      } catch (error) { throw toTdbError(error); }
    },
    async getTermMappingRegistry(request: GetTermMappingRegistryRequest): Promise<TermMappingRegistryRecord | undefined> {
      try {
        const response = await transport.getTermMappingRegistry(request, { timeoutMs: config.timeoutMs });
        return response.registry;
      } catch (error) { throw toTdbError(error); }
    },
    async listTermMappingRegistries(request: ListTermMappingRegistriesRequest): Promise<TermMappingRegistryRecord[]> {
      try {
        const response = await transport.listTermMappingRegistries(request, { timeoutMs: config.timeoutMs });
        return response.registries ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyNormalizedTerm(request: UpsertOntologyNormalizedTermRequest): Promise<OntologyNormalizedTermRecord> {
      try {
        const response = await transport.upsertOntologyNormalizedTerm(request, { timeoutMs: config.timeoutMs });
        return response.normalized_term!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyNormalizedTerm(request: GetOntologyNormalizedTermRequest): Promise<OntologyNormalizedTermRecord | undefined> {
      try {
        const response = await transport.getOntologyNormalizedTerm(request, { timeoutMs: config.timeoutMs });
        return response.normalized_term;
      } catch (error) { throw toTdbError(error); }
    },
    async searchOntologyNormalizedTerms(request: SearchOntologyNormalizedTermsRequest): Promise<OntologyNormalizedTermRecord[]> {
      try {
        const response = await transport.searchOntologyNormalizedTerms(request, { timeoutMs: config.timeoutMs });
        return response.normalized_terms ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyTermCluster(request: UpsertOntologyTermClusterRequest): Promise<OntologyTermClusterRecord> {
      try {
        const response = await transport.upsertOntologyTermCluster(request, { timeoutMs: config.timeoutMs });
        return response.cluster!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyTermCluster(request: GetOntologyTermClusterRequest): Promise<OntologyTermClusterRecord | undefined> {
      try {
        const response = await transport.getOntologyTermCluster(request, { timeoutMs: config.timeoutMs });
        return response.cluster;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyTermClusters(request: ListOntologyTermClustersRequest): Promise<OntologyTermClusterRecord[]> {
      try {
        const response = await transport.listOntologyTermClusters(request, { timeoutMs: config.timeoutMs });
        return response.clusters ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyClusterMember(request: UpsertOntologyClusterMemberRequest): Promise<OntologyClusterMemberRecord> {
      try {
        const response = await transport.upsertOntologyClusterMember(request, { timeoutMs: config.timeoutMs });
        return response.member!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyClusterMembers(request: ListOntologyClusterMembersRequest): Promise<OntologyClusterMemberRecord[]> {
      try {
        const response = await transport.listOntologyClusterMembers(request, { timeoutMs: config.timeoutMs });
        return response.members ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyRelationCandidate(request: UpsertOntologyRelationCandidateRequest): Promise<OntologyRelationCandidateRecord> {
      try {
        const response = await transport.upsertOntologyRelationCandidate(request, { timeoutMs: config.timeoutMs });
        return response.relation_candidate!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyRelationCandidates(request: ListOntologyRelationCandidatesRequest): Promise<OntologyRelationCandidateRecord[]> {
      try {
        const response = await transport.listOntologyRelationCandidates(request, { timeoutMs: config.timeoutMs });
        return response.relation_candidates ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyRawTerm(request: UpsertOntologyRawTermRequest): Promise<OntologyRawTermRecord> {
      try {
        const response = await transport.upsertOntologyRawTerm(request, { timeoutMs: config.timeoutMs });
        return response.raw_term!;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyRawTerm(request: GetOntologyRawTermRequest): Promise<OntologyRawTermRecord | undefined> {
      try {
        const response = await transport.getOntologyRawTerm(request, { timeoutMs: config.timeoutMs });
        return response.raw_term;
      } catch (error) { throw toTdbError(error); }
    },
    async searchOntologyRawTerms(request: SearchOntologyRawTermsRequest): Promise<OntologyRawTermRecord[]> {
      try {
        const response = await transport.searchOntologyRawTerms(request, { timeoutMs: config.timeoutMs });
        return response.raw_terms ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyRawTermCandidate(request: UpsertOntologyRawTermCandidateRequest): Promise<OntologyRawTermCandidateRecord> {
      try {
        const response = await transport.upsertOntologyRawTermCandidate(request, { timeoutMs: config.timeoutMs });
        return response.candidate!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyRawTermCandidates(request: ListOntologyRawTermCandidatesRequest): Promise<OntologyRawTermCandidateRecord[]> {
      try {
        const response = await transport.listOntologyRawTermCandidates(request, { timeoutMs: config.timeoutMs });
        return response.candidates ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertOntologyRawTermNormalization(request: UpsertOntologyRawTermNormalizationRequest): Promise<OntologyRawTermNormalizationRecord> {
      try {
        const response = await transport.upsertOntologyRawTermNormalization(request, { timeoutMs: config.timeoutMs });
        return response.mapping!;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyRawTermNormalizations(request: ListOntologyRawTermNormalizationsRequest): Promise<OntologyRawTermNormalizationRecord[]> {
      try {
        const response = await transport.listOntologyRawTermNormalizations(request, { timeoutMs: config.timeoutMs });
        return response.mappings ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertTermMappingRule(request: UpsertTermMappingRuleRequest): Promise<TermMappingRuleRecord> {
      try {
        const response = await transport.upsertTermMappingRule(request, { timeoutMs: config.timeoutMs });
        return response.rule!;
      } catch (error) { throw toTdbError(error); }
    },
    async getTermMappingRule(request: GetTermMappingRuleRequest): Promise<TermMappingRuleRecord | undefined> {
      try {
        const response = await transport.getTermMappingRule(request, { timeoutMs: config.timeoutMs });
        return response.rule;
      } catch (error) { throw toTdbError(error); }
    },
    async searchTermMappingRules(request: SearchTermMappingRulesRequest): Promise<TermMappingRuleRecord[]> {
      try {
        const response = await transport.searchTermMappingRules(request, { timeoutMs: config.timeoutMs });
        return response.rules ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertTermMappingRuleEvidence(request: UpsertTermMappingRuleEvidenceRequest): Promise<TermMappingRuleEvidenceRecord> {
      try {
        const response = await transport.upsertTermMappingRuleEvidence(request, { timeoutMs: config.timeoutMs });
        return response.evidence!;
      } catch (error) { throw toTdbError(error); }
    },
    async listTermMappingRuleEvidence(request: ListTermMappingRuleEvidenceRequest): Promise<TermMappingRuleEvidenceRecord[]> {
      try {
        const response = await transport.listTermMappingRuleEvidence(request, { timeoutMs: config.timeoutMs });
        return response.evidence ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async interpretTerm(request: InterpretTermRequest): Promise<TermMappingInterpretationRecord | undefined> {
      try {
        const response = await transport.interpretTerm(request, { timeoutMs: config.timeoutMs });
        return response.interpretation;
      } catch (error) { throw toTdbError(error); }
    },
    async interpretTermBatch(request: InterpretTermBatchRequest): Promise<TermMappingInterpretationRecord[]> {
      try {
        const response = await transport.interpretTermBatch(request, { timeoutMs: config.timeoutMs });
        return response.interpretations ?? [];
      } catch (error) { throw toTdbError(error); }
    },

    // Governance
    async upsertMethodologyFramework(request: UpsertMethodologyFrameworkRequest): Promise<MethodologyFrameworkRecord> {
      try {
        const response = await transport.upsertMethodologyFramework(request, { timeoutMs: config.timeoutMs });
        return response.framework!;
      } catch (error) { throw toTdbError(error); }
    },
    async getMethodologyFramework(request: GetMethodologyFrameworkRequest): Promise<MethodologyFrameworkRecord | undefined> {
      try {
        const response = await transport.getMethodologyFramework(request, { timeoutMs: config.timeoutMs });
        return response.framework;
      } catch (error) { throw toTdbError(error); }
    },
    async listMethodologyFrameworks(request: ListMethodologyFrameworksRequest): Promise<MethodologyFrameworkRecord[]> {
      try {
        const response = await transport.listMethodologyFrameworks(request, { timeoutMs: config.timeoutMs });
        return response.frameworks ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async getMethodologyFrameworkBundle(request: GetMethodologyFrameworkBundleRequest): Promise<GetMethodologyFrameworkBundleResponse> {
      try {
        return await transport.getMethodologyFrameworkBundle(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async upsertTaxonomyScheme(request: UpsertTaxonomySchemeRequest): Promise<TaxonomySchemeRecord> {
      try {
        const response = await transport.upsertTaxonomyScheme(request, { timeoutMs: config.timeoutMs });
        return response.scheme!;
      } catch (error) { throw toTdbError(error); }
    },
    async getTaxonomyScheme(request: GetTaxonomySchemeRequest): Promise<TaxonomySchemeRecord | undefined> {
      try {
        const response = await transport.getTaxonomyScheme(request, { timeoutMs: config.timeoutMs });
        return response.scheme;
      } catch (error) { throw toTdbError(error); }
    },
    async listTaxonomySchemes(request: ListTaxonomySchemesRequest): Promise<TaxonomySchemeRecord[]> {
      try {
        const response = await transport.listTaxonomySchemes(request, { timeoutMs: config.timeoutMs });
        return response.schemes ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertEvidencePolicyRule(request: UpsertEvidencePolicyRuleRequest): Promise<EvidencePolicyRuleRecord> {
      try {
        const response = await transport.upsertEvidencePolicyRule(request, { timeoutMs: config.timeoutMs });
        return response.rule!;
      } catch (error) { throw toTdbError(error); }
    },
    async getEvidencePolicyRule(request: GetEvidencePolicyRuleRequest): Promise<EvidencePolicyRuleRecord | undefined> {
      try {
        const response = await transport.getEvidencePolicyRule(request, { timeoutMs: config.timeoutMs });
        return response.rule;
      } catch (error) { throw toTdbError(error); }
    },
    async listEvidencePolicyRules(request: ListEvidencePolicyRulesRequest): Promise<EvidencePolicyRuleRecord[]> {
      try {
        const response = await transport.listEvidencePolicyRules(request, { timeoutMs: config.timeoutMs });
        return response.rules ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertAssertionPolicyRule(request: UpsertAssertionPolicyRuleRequest): Promise<AssertionPolicyRuleRecord> {
      try {
        const response = await transport.upsertAssertionPolicyRule(request, { timeoutMs: config.timeoutMs });
        return response.rule!;
      } catch (error) { throw toTdbError(error); }
    },
    async getAssertionPolicyRule(request: GetAssertionPolicyRuleRequest): Promise<AssertionPolicyRuleRecord | undefined> {
      try {
        const response = await transport.getAssertionPolicyRule(request, { timeoutMs: config.timeoutMs });
        return response.rule;
      } catch (error) { throw toTdbError(error); }
    },
    async listAssertionPolicyRules(request: ListAssertionPolicyRulesRequest): Promise<AssertionPolicyRuleRecord[]> {
      try {
        const response = await transport.listAssertionPolicyRules(request, { timeoutMs: config.timeoutMs });
        return response.rules ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertReviewPolicy(request: UpsertReviewPolicyRequest): Promise<ReviewPolicyRecord> {
      try {
        const response = await transport.upsertReviewPolicy(request, { timeoutMs: config.timeoutMs });
        return response.policy!;
      } catch (error) { throw toTdbError(error); }
    },
    async getReviewPolicy(request: GetReviewPolicyRequest): Promise<ReviewPolicyRecord | undefined> {
      try {
        const response = await transport.getReviewPolicy(request, { timeoutMs: config.timeoutMs });
        return response.policy;
      } catch (error) { throw toTdbError(error); }
    },
    async listReviewPolicies(request: ListReviewPoliciesRequest): Promise<ReviewPolicyRecord[]> {
      try {
        const response = await transport.listReviewPolicies(request, { timeoutMs: config.timeoutMs });
        return response.policies ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async upsertRule(request: UpsertRuleRequest): Promise<RuleRecord> {
      try {
        const response = await transport.upsertRule(request, { timeoutMs: config.timeoutMs });
        return response.rule;
      } catch (error) { throw toTdbError(error); }
    },
    async insertAuthorityGrant(request: InsertAuthorityGrantRequest): Promise<AuthorityGrantRecord> {
      try {
        const response = await transport.insertAuthorityGrant(request, { timeoutMs: config.timeoutMs });
        return response.grant;
      } catch (error) { throw toTdbError(error); }
    },
    async insertRuleOverride(request: InsertRuleOverrideRequest): Promise<RuleOverrideRecord> {
      try {
        const response = await transport.insertRuleOverride(request, { timeoutMs: config.timeoutMs });
        return response.override;
      } catch (error) { throw toTdbError(error); }
    },
    async findAuthorityAsOf(request: FindAuthorityAsOfRequest): Promise<AuthorityGrantRecord | undefined> {
      try {
        const response = await transport.findAuthorityAsOf(request, { timeoutMs: config.timeoutMs });
        return response.grant;
      } catch (error) { throw toTdbError(error); }
    },
    async listRuleOverridesAsOf(request: ListRuleOverridesAsOfRequest): Promise<RuleOverrideRecord[]> {
      try {
        const response = await transport.listRuleOverridesAsOf(request, { timeoutMs: config.timeoutMs });
        return response.overrides ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    // Ontology Fact
    async reviewOntologyFact(request: ReviewOntologyFactRequest): Promise<number> {
      try {
        const response = await transport.reviewOntologyFact(request, { timeoutMs: config.timeoutMs });
        return response.updated_rows;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyFact(request: GetOntologyFactRequest): Promise<OntologyFactRecord | undefined> {
      try {
        const response = await transport.getOntologyFact(request, { timeoutMs: config.timeoutMs });
        return response.fact;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyFactReviews(request: ListOntologyFactReviewsRequest): Promise<OntologyFactReviewRecord[]> {
      try {
        const response = await transport.listOntologyFactReviews(request, { timeoutMs: config.timeoutMs });
        return response.reviews ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyFactEvidence(request: ListOntologyFactEvidenceRequest): Promise<OntologyFactEvidenceRecord[]> {
      try {
        const response = await transport.listOntologyFactEvidence(request, { timeoutMs: config.timeoutMs });
        return response.evidence ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyFactLinkedCases(request: ListOntologyFactLinkedCasesRequest): Promise<OntologyFactLinkedCaseRecord[]> {
      try {
        const response = await transport.listOntologyFactLinkedCases(request, { timeoutMs: config.timeoutMs });
        return response.linked_cases ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyFactLinkedAlerts(request: ListOntologyFactLinkedAlertsRequest): Promise<OntologyFactLinkedAlertRecord[]> {
      try {
        const response = await transport.listOntologyFactLinkedAlerts(request, { timeoutMs: config.timeoutMs });
        return response.linked_alerts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async selectOntologyFactsForBulkReview(request: SelectOntologyFactsForBulkReviewRequest): Promise<OntologyFactBulkSelectionRecord[]> {
      try {
        const response = await transport.selectOntologyFactsForBulkReview(request, { timeoutMs: config.timeoutMs });
        return response.selected ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    // Ontology Case
    async insertOntologyCase(request: InsertOntologyCaseRequest): Promise<OntologyCaseRecord> {
      try {
        const response = await transport.insertOntologyCase(request, { timeoutMs: config.timeoutMs });
        return response.ontology_case;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyCase(request: GetOntologyCaseRequest): Promise<OntologyCaseRecord | undefined> {
      try {
        const response = await transport.getOntologyCase(request, { timeoutMs: config.timeoutMs });
        return response.ontology_case;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyCases(request: ListOntologyCasesRequest): Promise<OntologyCaseSummaryRecord[]> {
      try {
        const response = await transport.listOntologyCases(request, { timeoutMs: config.timeoutMs });
        return response.cases ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async updateOntologyCase(request: UpdateOntologyCaseRequest): Promise<number> {
      try {
        const response = await transport.updateOntologyCase(request, { timeoutMs: config.timeoutMs });
        return response.updated_rows;
      } catch (error) { throw toTdbError(error); }
    },
    async linkOntologyCaseFact(request: LinkOntologyCaseFactRequest): Promise<boolean> {
      try {
        const response = await transport.linkOntologyCaseFact(request, { timeoutMs: config.timeoutMs });
        return response.linked;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyCaseFacts(request: ListOntologyCaseFactsRequest): Promise<OntologyCaseFactRecord[]> {
      try {
        const response = await transport.listOntologyCaseFacts(request, { timeoutMs: config.timeoutMs });
        return response.facts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async insertOntologyCaseDecision(request: InsertOntologyCaseDecisionRequest): Promise<OntologyCaseDecisionRecord> {
      try {
        const response = await transport.insertOntologyCaseDecision(request, { timeoutMs: config.timeoutMs });
        return response.decision;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyCaseDecisions(request: ListOntologyCaseDecisionsRequest): Promise<OntologyCaseDecisionRecord[]> {
      try {
        const response = await transport.listOntologyCaseDecisions(request, { timeoutMs: config.timeoutMs });
        return response.decisions ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async insertOntologyCaseEvent(request: InsertOntologyCaseEventRequest): Promise<OntologyCaseEventRecord> {
      try {
        const response = await transport.insertOntologyCaseEvent(request, { timeoutMs: config.timeoutMs });
        return response.event;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyCaseEvents(request: ListOntologyCaseEventsRequest): Promise<OntologyCaseEventRecord[]> {
      try {
        const response = await transport.listOntologyCaseEvents(request, { timeoutMs: config.timeoutMs });
        return response.events ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    // Ontology Alert
    async insertOntologyAlert(request: InsertOntologyAlertRequest): Promise<OntologyAlertRecord> {
      try {
        const response = await transport.insertOntologyAlert(request, { timeoutMs: config.timeoutMs });
        return response.alert;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyAlertDetail(request: GetOntologyAlertDetailRequest): Promise<OntologyAlertDetailRecord | undefined> {
      try {
        const response = await transport.getOntologyAlertDetail(request, { timeoutMs: config.timeoutMs });
        return response.alert_detail;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyAlerts(request: ListOntologyAlertsRequest): Promise<OntologyAlertSummaryRecord[]> {
      try {
        const response = await transport.listOntologyAlerts(request, { timeoutMs: config.timeoutMs });
        return response.alerts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async updateOntologyAlert(request: UpdateOntologyAlertRequest): Promise<number> {
      try {
        const response = await transport.updateOntologyAlert(request, { timeoutMs: config.timeoutMs });
        return response.updated_rows;
      } catch (error) { throw toTdbError(error); }
    },
    async refreshTriggeredOntologyAlert(request: RefreshTriggeredOntologyAlertRequest): Promise<OntologyAlertRecord> {
      try {
        const response = await transport.refreshTriggeredOntologyAlert(request, { timeoutMs: config.timeoutMs });
        return response.alert;
      } catch (error) { throw toTdbError(error); }
    },
    async listApplicableOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord[]> {
      try {
        const response = await transport.listApplicableOntologyOpsRuleConfig(request, { timeoutMs: config.timeoutMs });
        return response.configs ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listStalePendingOntologyCandidates(request: ListStalePendingOntologyCandidatesRequest): Promise<OntologyFactRecord[]> {
      try {
        const response = await transport.listStalePendingOntologyCandidates(request, { timeoutMs: config.timeoutMs });
        return response.facts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listConflictPredicateOntologyCandidates(request: ListConflictPredicateOntologyCandidatesRequest): Promise<OntologyFactRecord[]> {
      try {
        const response = await transport.listConflictPredicateOntologyCandidates(request, { timeoutMs: config.timeoutMs });
        return response.facts ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async getActiveOntologyCaseByTitle(request: GetActiveOntologyCaseByTitleRequest): Promise<OntologyCaseRecord | undefined> {
      try {
        const response = await transport.getActiveOntologyCaseByTitle(request, { timeoutMs: config.timeoutMs });
        return response.case;
      } catch (error) { throw toTdbError(error); }
    },
    async getActiveOntologyAlertByRuleKey(request: GetActiveOntologyAlertByRuleKeyRequest): Promise<OntologyAlertRecord | undefined> {
      try {
        const response = await transport.getActiveOntologyAlertByRuleKey(request, { timeoutMs: config.timeoutMs });
        return response.alert;
      } catch (error) { throw toTdbError(error); }
    },
    async linkOntologyAlertFact(request: LinkOntologyAlertFactRequest): Promise<void> {
      try {
        await transport.linkOntologyAlertFact(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    // Ontology Ops
    async upsertOntologyOpsRuleConfig(request: UpsertOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord> {
      try {
        const response = await transport.upsertOntologyOpsRuleConfig(request, { timeoutMs: config.timeoutMs });
        return response.config;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyOpsRuleConfig(request: ListOntologyOpsRuleConfigRequest): Promise<OntologyOpsRuleConfigRecord[]> {
      try {
        const response = await transport.listOntologyOpsRuleConfig(request, { timeoutMs: config.timeoutMs });
        return response.configs ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async insertOntologyOpsRuleRun(request: InsertOntologyOpsRuleRunRequest): Promise<OntologyOpsRuleRunRecord> {
      try {
        const response = await transport.insertOntologyOpsRuleRun(request, { timeoutMs: config.timeoutMs });
        return response.run;
      } catch (error) { throw toTdbError(error); }
    },
    async getOntologyOpsRun(request: GetOntologyOpsRunRequest): Promise<OntologyOpsRuleRunRecord | undefined> {
      try {
        const response = await transport.getOntologyOpsRun(request, { timeoutMs: config.timeoutMs });
        return response.run;
      } catch (error) { throw toTdbError(error); }
    },
    async listOntologyOpsRuns(request: ListOntologyOpsRunsRequest): Promise<OntologyOpsRuleRunRecord[]> {
      try {
        const response = await transport.listOntologyOpsRuns(request, { timeoutMs: config.timeoutMs });
        return response.runs ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    // Wiki
    async upsertWikiPage(request: UpsertWikiPageRequest): Promise<UpsertWikiPageResponse> {
      try {
        return await transport.upsertWikiPage(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async upsertWikiPageLink(request: UpsertWikiPageLinkRequest): Promise<UpsertWikiPageLinkResponse> {
      try {
        return await transport.upsertWikiPageLink(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async getWikiPage(request: GetWikiPageRequest): Promise<WikiPageRecord | undefined> {
      try {
        const response = await transport.getWikiPage(request, { timeoutMs: config.timeoutMs });
        return response.page;
      } catch (error) { throw toTdbError(error); }
    },
    async searchWikiPages(request: SearchWikiPagesRequest): Promise<WikiPageRecord[]> {
      try {
        const response = await transport.searchWikiPages(request, { timeoutMs: config.timeoutMs });
        return response.pages ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async listWikiPages(request: ListWikiPagesRequest): Promise<ListWikiPagesResponse> {
      try {
        return await transport.listWikiPages(request, { timeoutMs: config.timeoutMs });
      } catch (error) { throw toTdbError(error); }
    },
    async reinforceWikiPage(request: ReinforceWikiPageRequest): Promise<WikiPageRecord | undefined> {
      try {
        const response = await transport.reinforceWikiPage(request, { timeoutMs: config.timeoutMs });
        return response.page;
      } catch (error) { throw toTdbError(error); }
    },
    async appendWikiLog(request: AppendWikiLogRequest): Promise<WikiLogRecord | undefined> {
      try {
        const response = await transport.appendWikiLog(request, { timeoutMs: config.timeoutMs });
        return response.log;
      } catch (error) { throw toTdbError(error); }
    },
    async listWikiLogs(request: ListWikiLogsRequest): Promise<WikiLogRecord[]> {
      try {
        const response = await transport.listWikiLogs(request, { timeoutMs: config.timeoutMs });
        return response.logs ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    async lintWikiDomain(request: LintWikiDomainRequest): Promise<WikiLintIssue[]> {
      try {
        const response = await transport.lintWikiDomain(request, { timeoutMs: config.timeoutMs });
        return response.issues ?? [];
      } catch (error) { throw toTdbError(error); }
    },
    close(): void {
      transport.close?.();
    }
  };
}

function createGrpcTransport(config: GatewayBackendConfig): GatewayBackendTransport {
  const protoPath = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../proto/gateway_backend.proto'
  );
  const packageDefinition = protoLoader.loadSync(protoPath, {
    keepCase: true,
    longs: Number,
    enums: String,
    defaults: true,
    oneofs: true
  });
  const loaded = loadPackageDefinition(packageDefinition) as Record<string, unknown>;
  const gatewayBackendCtor = (((loaded.tdb as Record<string, unknown>).gateway as Record<string, unknown>)
    .backend as Record<string, unknown>).v1 as Record<string, unknown>;
  const ClientCtor = gatewayBackendCtor.GatewayBackend as grpc.ServiceClientConstructor;
  const client = new ClientCtor(
    config.address,
    credentials.createInsecure()
  ) as unknown as GrpcGatewayBackendService;

  return {
    searchQuery(request, options = {}) {
      return new Promise<GatewayBackendProtoResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.SearchQuery(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertDomainStreamBinding(request, options = {}) {
      return new Promise<{ binding?: DomainStreamBindingRecord }>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertDomainStreamBinding(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listDomainStreamBindings(request, options = {}) {
      return new Promise<{ bindings?: DomainStreamBindingRecord[] }>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListDomainStreamBindings(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    indexEvent(request, options = {}) {
      return new Promise<IndexEventResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.IndexEvent(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    appendEvent(request, options = {}) {
      return new Promise<AppendEventResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.AppendEvent(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEvents(request, options = {}) {
      return new Promise<GetEventsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEvents(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEventSentences(request, options = {}) {
      return new Promise<GetEventSentencesResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEventSentences(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertProperty(request, options = {}) {
      return new Promise<UpsertPropertyResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertProperty(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getPropertyAsOf(request, options = {}) {
      return new Promise<GetPropertyAsOfResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetPropertyAsOf(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEdge(request, options = {}) {
      return new Promise<UpsertEdgeResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertEdge(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEdgesAsOf(request, options = {}) {
      return new Promise<GetEdgesAsOfResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEdgesAsOf(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listPropertyRows(request, options = {}) {
      return new Promise<ListPropertyRowsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListPropertyRows(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEntity(request, options = {}) {
      return new Promise<UpsertEntityResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertEntity(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEntity(request, options = {}) {
      return new Promise<GetEntityResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEntity(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listEntities(request, options = {}) {
      return new Promise<ListEntitiesResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListEntities(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    writeSnapshot(request, options = {}) {
      return new Promise<WriteSnapshotResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.WriteSnapshot(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getLatestSnapshot(request, options = {}) {
      return new Promise<GetLatestSnapshotResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetLatestSnapshot(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    createArtifact(request, options = {}) {
      return new Promise<CreateArtifactResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.CreateArtifact(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    createArtifactVersion(request, options = {}) {
      return new Promise<CreateArtifactVersionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.CreateArtifactVersion(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getArtifactVersionAsOf(request, options = {}) {
      return new Promise<GetArtifactVersionAsOfResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetArtifactVersionAsOf(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getArtifactVersionById(request, options = {}) {
      return new Promise<GetArtifactVersionByIdResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetArtifactVersionById(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertDecision(request, options = {}) {
      return new Promise<UpsertDecisionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertDecision(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    insertDecisionEvidence(request, options = {}) {
      return new Promise<InsertDecisionEvidenceResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.InsertDecisionEvidence(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    findDecision(request, options = {}) {
      return new Promise<FindDecisionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.FindDecision(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listDecisionEvidence(request, options = {}) {
      return new Promise<ListDecisionEvidenceResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListDecisionEvidence(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertAssertion(request, options = {}) {
      return new Promise<UpsertAssertionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertAssertion(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getAssertion(request, options = {}) {
      return new Promise<GetAssertionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetAssertion(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    searchAssertions(request, options = {}) {
      return new Promise<SearchAssertionsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.SearchAssertions(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEvidence(request, options = {}) {
      return new Promise<UpsertEvidenceResponse>((resolve, reject) => {
        if (typeof client.UpsertEvidence !== 'function') {
          reject(new Error('client.UpsertEvidence is not available'));
          return;
        }
        const metadata = new grpc.Metadata();
        client.UpsertEvidence(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEvidence(request, options = {}) {
      return new Promise<GetEvidenceResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEvidence(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    searchEvidence(request, options = {}) {
      return new Promise<SearchEvidenceResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.SearchEvidence(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEvidenceLocator(request, options = {}) {
      return new Promise<UpsertEvidenceLocatorResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertEvidenceLocator(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listEvidenceLocators(request, options = {}) {
      return new Promise<ListEvidenceLocatorsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListEvidenceLocators(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEvidenceDerivation(request, options = {}) {
      return new Promise<UpsertEvidenceDerivationResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertEvidenceDerivation(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listEvidenceDerivations(request, options = {}) {
      return new Promise<ListEvidenceDerivationsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListEvidenceDerivations(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertEvidenceClassification(request, options = {}) {
      return new Promise<UpsertEvidenceClassificationResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertEvidenceClassification(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    getEvidenceClassification(request, options = {}) {
      return new Promise<GetEvidenceClassificationResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.GetEvidenceClassification(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertAssertionEvidenceLink(request, options = {}) {
      return new Promise<UpsertAssertionEvidenceLinkResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertAssertionEvidenceLink(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listAssertionEvidenceLinks(request, options = {}) {
      return new Promise<ListAssertionEvidenceLinksResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListAssertionEvidenceLinks(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    upsertAssertionRelation(request, options = {}) {
      return new Promise<UpsertAssertionRelationResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.UpsertAssertionRelation(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },
    listAssertionRelations(request, options = {}) {
      return new Promise<ListAssertionRelationsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListAssertionRelations(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    insertMemoryDecision(request, options = {}) {
      return new Promise<InsertMemoryDecisionResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.InsertMemoryDecision(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    listRecentMemoryDecisions(request, options = {}) {
      return new Promise<ListRecentMemoryDecisionsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListRecentMemoryDecisions(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    insertMemoryEpisodeSummary(request, options = {}) {
      return new Promise<InsertMemoryEpisodeSummaryResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.InsertMemoryEpisodeSummary(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    listRecentMemoryEpisodeSummaries(request, options = {}) {
      return new Promise<ListRecentMemoryEpisodeSummariesResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.ListRecentMemoryEpisodeSummaries(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    insertMemoryAnswerArtifact(request, options = {}) {
      return new Promise<InsertMemoryAnswerArtifactResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.InsertMemoryAnswerArtifact(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    recallMemoryAnswerArtifacts(request, options = {}) {
      return new Promise<RecallMemoryAnswerArtifactsResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.RecallMemoryAnswerArtifacts(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    insertMemoryAnswerValidation(request, options = {}) {
      return new Promise<InsertMemoryAnswerValidationResponse>((resolve, reject) => {
        const metadata = new grpc.Metadata();
        client.InsertMemoryAnswerValidation(
          request,
          metadata,
          {
            deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs))
          },
          (error, response) => {
            if (error) {
              reject(error);
              return;
            }
            resolve(response);
          }
        );
      });
    },

    upsertOntologyConcept(request, options = {}) {
      return new Promise<UpsertOntologyConceptResponse>((resolve, reject) => {
        client.UpsertOntologyConcept(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyConcept(request, options = {}) {
      return new Promise<GetOntologyConceptResponse>((resolve, reject) => {
        client.GetOntologyConcept(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyConcepts(request, options = {}) {
      return new Promise<ListOntologyConceptsResponse>((resolve, reject) => {
        client.ListOntologyConcepts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertConceptAlias(request, options = {}) {
      return new Promise<UpsertConceptAliasResponse>((resolve, reject) => {
        client.UpsertConceptAlias(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listConceptAliases(request, options = {}) {
      return new Promise<ListConceptAliasesResponse>((resolve, reject) => {
        client.ListConceptAliases(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyEdge(request, options = {}) {
      return new Promise<UpsertOntologyEdgeResponse>((resolve, reject) => {
        client.UpsertOntologyEdge(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyEdges(request, options = {}) {
      return new Promise<ListOntologyEdgesResponse>((resolve, reject) => {
        client.ListOntologyEdges(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertEventConceptLink(request, options = {}) {
      return new Promise<UpsertEventConceptLinkResponse>((resolve, reject) => {
        client.UpsertEventConceptLink(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listEventConceptLinks(request, options = {}) {
      return new Promise<ListEventConceptLinksResponse>((resolve, reject) => {
        client.ListEventConceptLinks(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyObjectType(request, options = {}) {
      return new Promise<UpsertOntologyObjectTypeResponse>((resolve, reject) => {
        client.UpsertOntologyObjectType(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyObjectType(request, options = {}) {
      return new Promise<GetOntologyObjectTypeResponse>((resolve, reject) => {
        client.GetOntologyObjectType(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyObjectTypes(request, options = {}) {
      return new Promise<ListOntologyObjectTypesResponse>((resolve, reject) => {
        client.ListOntologyObjectTypes(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyConceptTypeAssignment(request, options = {}) {
      return new Promise<UpsertOntologyConceptTypeAssignmentResponse>((resolve, reject) => {
        client.UpsertOntologyConceptTypeAssignment(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyConceptTypeAssignments(request, options = {}) {
      return new Promise<ListOntologyConceptTypeAssignmentsResponse>((resolve, reject) => {
        client.ListOntologyConceptTypeAssignments(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyRelationType(request, options = {}) {
      return new Promise<UpsertOntologyRelationTypeResponse>((resolve, reject) => {
        client.UpsertOntologyRelationType(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyRelationType(request, options = {}) {
      return new Promise<GetOntologyRelationTypeResponse>((resolve, reject) => {
        client.GetOntologyRelationType(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyRelationTypes(request, options = {}) {
      return new Promise<ListOntologyRelationTypesResponse>((resolve, reject) => {
        client.ListOntologyRelationTypes(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyFacts(request, options = {}) {
      return new Promise<ListOntologyFactsResponse>((resolve, reject) => {
        client.ListOntologyFacts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyFactWithEvidence(request, options = {}) {
      return new Promise<UpsertOntologyFactWithEvidenceResponse>((resolve, reject) => {
        client.UpsertOntologyFactWithEvidence(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertSemanticBatch(request, options = {}) {
      return new Promise<UpsertSemanticBatchResponse>((resolve, reject) => {
        client.UpsertSemanticBatch(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getSemanticStatement(request, options = {}) {
      return new Promise<GetSemanticStatementResponse>((resolve, reject) => {
        client.GetSemanticStatement(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    setSemanticStatementStatus(request, options = {}) {
      return new Promise<SetSemanticStatementStatusResponse>((resolve, reject) => {
        client.SetSemanticStatementStatus(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listSemanticStatements(request, options = {}) {
      return new Promise<ListSemanticStatementsResponse>((resolve, reject) => {
        client.ListSemanticStatements(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getSemanticStatementProvenance(request, options = {}) {
      return new Promise<GetSemanticStatementProvenanceResponse>((resolve, reject) => {
        client.GetSemanticStatementProvenance(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getSemanticStatementsByEvidence(request, options = {}) {
      return new Promise<GetSemanticStatementsByEvidenceResponse>((resolve, reject) => {
        client.GetSemanticStatementsByEvidence(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchOntologyConcepts(request, options = {}) {
      return new Promise<SearchOntologyConceptsResponse>((resolve, reject) => {
        client.SearchOntologyConcepts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchConceptAliases(request, options = {}) {
      return new Promise<SearchConceptAliasesResponse>((resolve, reject) => {
        client.SearchConceptAliases(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchOntologyFacts(request, options = {}) {
      return new Promise<SearchOntologyFactsResponse>((resolve, reject) => {
        client.SearchOntologyFacts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyConceptNeighbors(request, options = {}) {
      return new Promise<GetOntologyConceptNeighborsResponse>((resolve, reject) => {
        client.GetOntologyConceptNeighbors(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    archiveOntologyFact(request, options = {}) {
      return new Promise<ArchiveOntologyFactResponse>((resolve, reject) => {
        client.ArchiveOntologyFact(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertTermMappingRegistry(request, options = {}) {
      return new Promise<UpsertTermMappingRegistryResponse>((resolve, reject) => {
        client.UpsertTermMappingRegistry(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getTermMappingRegistry(request, options = {}) {
      return new Promise<GetTermMappingRegistryResponse>((resolve, reject) => {
        client.GetTermMappingRegistry(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listTermMappingRegistries(request, options = {}) {
      return new Promise<ListTermMappingRegistriesResponse>((resolve, reject) => {
        client.ListTermMappingRegistries(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyNormalizedTerm(request, options = {}) {
      return new Promise<UpsertOntologyNormalizedTermResponse>((resolve, reject) => {
        client.UpsertOntologyNormalizedTerm(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyNormalizedTerm(request, options = {}) {
      return new Promise<GetOntologyNormalizedTermResponse>((resolve, reject) => {
        client.GetOntologyNormalizedTerm(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchOntologyNormalizedTerms(request, options = {}) {
      return new Promise<SearchOntologyNormalizedTermsResponse>((resolve, reject) => {
        client.SearchOntologyNormalizedTerms(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyTermCluster(request, options = {}) {
      return new Promise<UpsertOntologyTermClusterResponse>((resolve, reject) => {
        client.UpsertOntologyTermCluster(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyTermCluster(request, options = {}) {
      return new Promise<GetOntologyTermClusterResponse>((resolve, reject) => {
        client.GetOntologyTermCluster(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyTermClusters(request, options = {}) {
      return new Promise<ListOntologyTermClustersResponse>((resolve, reject) => {
        client.ListOntologyTermClusters(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyClusterMember(request, options = {}) {
      return new Promise<UpsertOntologyClusterMemberResponse>((resolve, reject) => {
        client.UpsertOntologyClusterMember(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyClusterMembers(request, options = {}) {
      return new Promise<ListOntologyClusterMembersResponse>((resolve, reject) => {
        client.ListOntologyClusterMembers(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyRelationCandidate(request, options = {}) {
      return new Promise<UpsertOntologyRelationCandidateResponse>((resolve, reject) => {
        client.UpsertOntologyRelationCandidate(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyRelationCandidates(request, options = {}) {
      return new Promise<ListOntologyRelationCandidatesResponse>((resolve, reject) => {
        client.ListOntologyRelationCandidates(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyRawTerm(request, options = {}) {
      return new Promise<UpsertOntologyRawTermResponse>((resolve, reject) => {
        client.UpsertOntologyRawTerm(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyRawTerm(request, options = {}) {
      return new Promise<GetOntologyRawTermResponse>((resolve, reject) => {
        client.GetOntologyRawTerm(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchOntologyRawTerms(request, options = {}) {
      return new Promise<SearchOntologyRawTermsResponse>((resolve, reject) => {
        client.SearchOntologyRawTerms(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyRawTermCandidate(request, options = {}) {
      return new Promise<UpsertOntologyRawTermCandidateResponse>((resolve, reject) => {
        client.UpsertOntologyRawTermCandidate(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyRawTermCandidates(request, options = {}) {
      return new Promise<ListOntologyRawTermCandidatesResponse>((resolve, reject) => {
        client.ListOntologyRawTermCandidates(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyRawTermNormalization(request, options = {}) {
      return new Promise<UpsertOntologyRawTermNormalizationResponse>((resolve, reject) => {
        client.UpsertOntologyRawTermNormalization(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyRawTermNormalizations(request, options = {}) {
      return new Promise<ListOntologyRawTermNormalizationsResponse>((resolve, reject) => {
        client.ListOntologyRawTermNormalizations(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertTermMappingRule(request, options = {}) {
      return new Promise<UpsertTermMappingRuleResponse>((resolve, reject) => {
        client.UpsertTermMappingRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getTermMappingRule(request, options = {}) {
      return new Promise<GetTermMappingRuleResponse>((resolve, reject) => {
        client.GetTermMappingRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchTermMappingRules(request, options = {}) {
      return new Promise<SearchTermMappingRulesResponse>((resolve, reject) => {
        client.SearchTermMappingRules(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertTermMappingRuleEvidence(request, options = {}) {
      return new Promise<UpsertTermMappingRuleEvidenceResponse>((resolve, reject) => {
        client.UpsertTermMappingRuleEvidence(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listTermMappingRuleEvidence(request, options = {}) {
      return new Promise<ListTermMappingRuleEvidenceResponse>((resolve, reject) => {
        client.ListTermMappingRuleEvidence(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    interpretTerm(request, options = {}) {
      return new Promise<InterpretTermResponse>((resolve, reject) => {
        client.InterpretTerm(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    interpretTermBatch(request, options = {}) {
      return new Promise<InterpretTermBatchResponse>((resolve, reject) => {
        client.InterpretTermBatch(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertMethodologyFramework(request, options = {}) {
      return new Promise<UpsertMethodologyFrameworkResponse>((resolve, reject) => {
        client.UpsertMethodologyFramework(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getMethodologyFramework(request, options = {}) {
      return new Promise<GetMethodologyFrameworkResponse>((resolve, reject) => {
        client.GetMethodologyFramework(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listMethodologyFrameworks(request, options = {}) {
      return new Promise<ListMethodologyFrameworksResponse>((resolve, reject) => {
        client.ListMethodologyFrameworks(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getMethodologyFrameworkBundle(request, options = {}) {
      return new Promise<GetMethodologyFrameworkBundleResponse>((resolve, reject) => {
        client.GetMethodologyFrameworkBundle(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertTaxonomyScheme(request, options = {}) {
      return new Promise<UpsertTaxonomySchemeResponse>((resolve, reject) => {
        client.UpsertTaxonomyScheme(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getTaxonomyScheme(request, options = {}) {
      return new Promise<GetTaxonomySchemeResponse>((resolve, reject) => {
        client.GetTaxonomyScheme(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listTaxonomySchemes(request, options = {}) {
      return new Promise<ListTaxonomySchemesResponse>((resolve, reject) => {
        client.ListTaxonomySchemes(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertEvidencePolicyRule(request, options = {}) {
      return new Promise<UpsertEvidencePolicyRuleResponse>((resolve, reject) => {
        client.UpsertEvidencePolicyRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getEvidencePolicyRule(request, options = {}) {
      return new Promise<GetEvidencePolicyRuleResponse>((resolve, reject) => {
        client.GetEvidencePolicyRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listEvidencePolicyRules(request, options = {}) {
      return new Promise<ListEvidencePolicyRulesResponse>((resolve, reject) => {
        client.ListEvidencePolicyRules(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertAssertionPolicyRule(request, options = {}) {
      return new Promise<UpsertAssertionPolicyRuleResponse>((resolve, reject) => {
        client.UpsertAssertionPolicyRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getAssertionPolicyRule(request, options = {}) {
      return new Promise<GetAssertionPolicyRuleResponse>((resolve, reject) => {
        client.GetAssertionPolicyRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listAssertionPolicyRules(request, options = {}) {
      return new Promise<ListAssertionPolicyRulesResponse>((resolve, reject) => {
        client.ListAssertionPolicyRules(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertReviewPolicy(request, options = {}) {
      return new Promise<UpsertReviewPolicyResponse>((resolve, reject) => {
        client.UpsertReviewPolicy(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getReviewPolicy(request, options = {}) {
      return new Promise<GetReviewPolicyResponse>((resolve, reject) => {
        client.GetReviewPolicy(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listReviewPolicies(request, options = {}) {
      return new Promise<ListReviewPoliciesResponse>((resolve, reject) => {
        client.ListReviewPolicies(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },

    upsertRule(request, options = {}) {
      return new Promise<UpsertRuleResponse>((resolve, reject) => {
        client.UpsertRule(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertAuthorityGrant(request, options = {}) {
      return new Promise<InsertAuthorityGrantResponse>((resolve, reject) => {
        client.InsertAuthorityGrant(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertRuleOverride(request, options = {}) {
      return new Promise<InsertRuleOverrideResponse>((resolve, reject) => {
        client.InsertRuleOverride(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    findAuthorityAsOf(request, options = {}) {
      return new Promise<FindAuthorityAsOfResponse>((resolve, reject) => {
        client.FindAuthorityAsOf(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listRuleOverridesAsOf(request, options = {}) {
      return new Promise<ListRuleOverridesAsOfResponse>((resolve, reject) => {
        client.ListRuleOverridesAsOf(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    reviewOntologyFact(request, options = {}) {
      return new Promise<ReviewOntologyFactResponse>((resolve, reject) => {
        client.ReviewOntologyFact(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyFact(request, options = {}) {
      return new Promise<GetOntologyFactResponse>((resolve, reject) => {
        client.GetOntologyFact(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyFactReviews(request, options = {}) {
      return new Promise<ListOntologyFactReviewsResponse>((resolve, reject) => {
        client.ListOntologyFactReviews(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyFactEvidence(request, options = {}) {
      return new Promise<ListOntologyFactEvidenceResponse>((resolve, reject) => {
        client.ListOntologyFactEvidence(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyFactLinkedCases(request, options = {}) {
      return new Promise<ListOntologyFactLinkedCasesResponse>((resolve, reject) => {
        client.ListOntologyFactLinkedCases(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyFactLinkedAlerts(request, options = {}) {
      return new Promise<ListOntologyFactLinkedAlertsResponse>((resolve, reject) => {
        client.ListOntologyFactLinkedAlerts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    selectOntologyFactsForBulkReview(request, options = {}) {
      return new Promise<SelectOntologyFactsForBulkReviewResponse>((resolve, reject) => {
        client.SelectOntologyFactsForBulkReview(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertOntologyCase(request, options = {}) {
      return new Promise<InsertOntologyCaseResponse>((resolve, reject) => {
        client.InsertOntologyCase(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyCase(request, options = {}) {
      return new Promise<GetOntologyCaseResponse>((resolve, reject) => {
        client.GetOntologyCase(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyCases(request, options = {}) {
      return new Promise<ListOntologyCasesResponse>((resolve, reject) => {
        client.ListOntologyCases(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: ListOntologyCasesResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    updateOntologyCase(request, options = {}) {
      return new Promise<UpdateOntologyCaseResponse>((resolve, reject) => {
        client.UpdateOntologyCase(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    linkOntologyCaseFact(request, options = {}) {
      return new Promise<LinkOntologyCaseFactResponse>((resolve, reject) => {
        client.LinkOntologyCaseFact(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyCaseFacts(request, options = {}) {
      return new Promise<ListOntologyCaseFactsResponse>((resolve, reject) => {
        client.ListOntologyCaseFacts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertOntologyCaseDecision(request, options = {}) {
      return new Promise<InsertOntologyCaseDecisionResponse>((resolve, reject) => {
        client.InsertOntologyCaseDecision(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyCaseDecisions(request, options = {}) {
      return new Promise<ListOntologyCaseDecisionsResponse>((resolve, reject) => {
        client.ListOntologyCaseDecisions(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: ListOntologyCaseDecisionsResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertOntologyCaseEvent(request, options = {}) {
      return new Promise<InsertOntologyCaseEventResponse>((resolve, reject) => {
        client.InsertOntologyCaseEvent(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyCaseEvents(request, options = {}) {
      return new Promise<ListOntologyCaseEventsResponse>((resolve, reject) => {
        client.ListOntologyCaseEvents(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: ListOntologyCaseEventsResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertOntologyAlert(request, options = {}) {
      return new Promise<InsertOntologyAlertResponse>((resolve, reject) => {
        client.InsertOntologyAlert(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: InsertOntologyAlertResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyAlertDetail(request, options = {}) {
      return new Promise<GetOntologyAlertDetailResponse>((resolve, reject) => {
        client.GetOntologyAlertDetail(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: GetOntologyAlertDetailResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyAlerts(request, options = {}) {
      return new Promise<ListOntologyAlertsResponse>((resolve, reject) => {
        client.ListOntologyAlerts(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: ListOntologyAlertsResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    updateOntologyAlert(request, options = {}) {
      return new Promise<UpdateOntologyAlertResponse>((resolve, reject) => {
        client.UpdateOntologyAlert(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error: grpc.ServiceError | null, response: UpdateOntologyAlertResponse) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    refreshTriggeredOntologyAlert(request, options = {}) {
      return new Promise<RefreshTriggeredOntologyAlertResponse>((resolve, reject) => {
        client.RefreshTriggeredOntologyAlert(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertOntologyOpsRuleConfig(request, options = {}) {
      return new Promise<UpsertOntologyOpsRuleConfigResponse>((resolve, reject) => {
        client.UpsertOntologyOpsRuleConfig(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyOpsRuleConfig(request, options = {}) {
      return new Promise<ListOntologyOpsRuleConfigResponse>((resolve, reject) => {
        client.ListOntologyOpsRuleConfig(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    insertOntologyOpsRuleRun(request, options = {}) {
      return new Promise<InsertOntologyOpsRuleRunResponse>((resolve, reject) => {
        client.InsertOntologyOpsRuleRun(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getOntologyOpsRun(request, options = {}) {
      return new Promise<GetOntologyOpsRunResponse>((resolve, reject) => {
        client.GetOntologyOpsRun(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listOntologyOpsRuns(request, options = {}) {
      return new Promise<ListOntologyOpsRunsResponse>((resolve, reject) => {
        client.ListOntologyOpsRuns(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listApplicableOntologyOpsRuleConfig(request, options = {}) {
      return new Promise<ListOntologyOpsRuleConfigResponse>((resolve, reject) => {
        client.ListApplicableOntologyOpsRuleConfig(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listStalePendingOntologyCandidates(request, options = {}) {
      return new Promise<ListOntologyFactsResponse>((resolve, reject) => {
        client.ListStalePendingOntologyCandidates(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listConflictPredicateOntologyCandidates(request, options = {}) {
      return new Promise<ListOntologyFactsResponse>((resolve, reject) => {
        client.ListConflictPredicateOntologyCandidates(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getActiveOntologyCaseByTitle(request, options = {}) {
      return new Promise<GetActiveOntologyCaseByTitleResponse>((resolve, reject) => {
        client.GetActiveOntologyCaseByTitle(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getActiveOntologyAlertByRuleKey(request, options = {}) {
      return new Promise<GetActiveOntologyAlertByRuleKeyResponse>((resolve, reject) => {
        client.GetActiveOntologyAlertByRuleKey(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },

    linkOntologyAlertFact(request, options = {}) {
      return new Promise<Empty>((resolve, reject) => {
        client.LinkOntologyAlertFact(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertWikiPage(request, options = {}) {
      return new Promise<UpsertWikiPageResponse>((resolve, reject) => {
        client.UpsertWikiPage(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    upsertWikiPageLink(request, options = {}) {
      return new Promise<UpsertWikiPageLinkResponse>((resolve, reject) => {
        client.UpsertWikiPageLink(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    getWikiPage(request, options = {}) {
      return new Promise<GetWikiPageResponse>((resolve, reject) => {
        client.GetWikiPage(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    searchWikiPages(request, options = {}) {
      return new Promise<SearchWikiPagesResponse>((resolve, reject) => {
        client.SearchWikiPages(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listWikiPages(request, options = {}) {
      return new Promise<ListWikiPagesResponse>((resolve, reject) => {
        client.ListWikiPages(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    reinforceWikiPage(request, options = {}) {
      return new Promise<ReinforceWikiPageResponse>((resolve, reject) => {
        client.ReinforceWikiPage(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    appendWikiLog(request, options = {}) {
      return new Promise<AppendWikiLogResponse>((resolve, reject) => {
        client.AppendWikiLog(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    listWikiLogs(request, options = {}) {
      return new Promise<ListWikiLogsResponse>((resolve, reject) => {
        client.ListWikiLogs(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    lintWikiDomain(request, options = {}) {
      return new Promise<LintWikiDomainResponse>((resolve, reject) => {
        client.LintWikiDomain(request, new grpc.Metadata(), { deadline: new Date(Date.now() + (options.timeoutMs ?? config.timeoutMs)) }, (error, response) => {
          if (error) { reject(error); return; }
          resolve(response);
        });
      });
    },
    close(): void {
      client.close();
    }
  };
}

function mapSemanticStatement(record: SemanticStatementRecord): SemanticStatementRecord {
  const valueJsonRaw = (record as { value_json?: string; valueJson?: string }).value_json
    ?? (record as { value_json?: string; valueJson?: string }).valueJson
    ?? '';
  const metadataRaw = (record as { metadata_json?: string; metadataJson?: string }).metadata_json
    ?? (record as { metadata_json?: string; metadataJson?: string }).metadataJson
    ?? '{}';
  const provenanceRaw = (record as { provenance_json?: string; provenanceJson?: string }).provenance_json
    ?? (record as { provenance_json?: string; provenanceJson?: string }).provenanceJson
    ?? '{}';
  return {
    statement_id: (record as { statement_id?: string; statementId?: string }).statement_id
      ?? (record as { statement_id?: string; statementId?: string }).statementId
      ?? '',
    subject_concept_id: (record as {
      subject_concept_id?: string; subjectConceptId?: string; subject_id?: string; subjectId?: string;
    }).subject_concept_id
      ?? (record as {
        subject_concept_id?: string; subjectConceptId?: string; subject_id?: string; subjectId?: string;
      }).subjectConceptId
      ?? (record as {
        subject_concept_id?: string; subjectConceptId?: string; subject_id?: string; subjectId?: string;
      }).subject_id
      ?? (record as {
        subject_concept_id?: string; subjectConceptId?: string; subject_id?: string; subjectId?: string;
      }).subjectId
      ?? '',
    subject_name: (record as {
      subject_name?: string; subjectName?: string; subject_label?: string; subjectLabel?: string;
    }).subject_name
      ?? (record as {
        subject_name?: string; subjectName?: string; subject_label?: string; subjectLabel?: string;
      }).subjectName
      ?? (record as {
        subject_name?: string; subjectName?: string; subject_label?: string; subjectLabel?: string;
      }).subject_label
      ?? (record as {
        subject_name?: string; subjectName?: string; subject_label?: string; subjectLabel?: string;
      }).subjectLabel
      ?? '',
    predicate: (record as { predicate?: string; property_id?: string; propertyId?: string }).predicate
      ?? (record as { predicate?: string; property_id?: string; propertyId?: string }).property_id
      ?? (record as { predicate?: string; property_id?: string; propertyId?: string }).propertyId
      ?? '',
    value_type: (record as { value_type?: string; valueType?: string }).value_type
      ?? (record as { value_type?: string; valueType?: string }).valueType
      ?? '',
    object_concept_id: (record as {
      object_concept_id?: string; objectConceptId?: string; value_entity_id?: string; valueEntityId?: string;
    }).object_concept_id
      ?? (record as {
        object_concept_id?: string; objectConceptId?: string; value_entity_id?: string; valueEntityId?: string;
      }).objectConceptId
      ?? (record as {
        object_concept_id?: string; objectConceptId?: string; value_entity_id?: string; valueEntityId?: string;
      }).value_entity_id
      ?? (record as {
        object_concept_id?: string; objectConceptId?: string; value_entity_id?: string; valueEntityId?: string;
      }).valueEntityId
      ?? '',
    object_name: (record as {
      object_name?: string; objectName?: string; value_entity_label?: string; valueEntityLabel?: string;
    }).object_name
      ?? (record as {
        object_name?: string; objectName?: string; value_entity_label?: string; valueEntityLabel?: string;
      }).objectName
      ?? (record as {
        object_name?: string; objectName?: string; value_entity_label?: string; valueEntityLabel?: string;
      }).value_entity_label
      ?? (record as {
        object_name?: string; objectName?: string; value_entity_label?: string; valueEntityLabel?: string;
      }).valueEntityLabel
      ?? '',
    value_json: parseJsonString(valueJsonRaw),
    status: record.status,
    confidence: record.confidence,
    created_by: (record as { created_by?: string; createdBy?: string }).created_by
      ?? (record as { created_by?: string; createdBy?: string }).createdBy
      ?? '',
    metadata_json: metadataRaw,
    provenance_json: provenanceRaw,
    created_at: (record as { created_at?: string; createdAt?: string }).created_at
      ?? (record as { created_at?: string; createdAt?: string }).createdAt
      ?? '',
    updated_at: (record as { updated_at?: string; updatedAt?: string }).updated_at
      ?? (record as { updated_at?: string; updatedAt?: string }).updatedAt
      ?? ''
  } as unknown as SemanticStatementRecord;
}

function mapSemanticStatementQualifier(
  record: SemanticStatementQualifierRecord
): SemanticStatementQualifierRecord {
  return {
    statement_id: (record as { statement_id?: string; statementId?: string }).statement_id
      ?? (record as { statement_id?: string; statementId?: string }).statementId
      ?? '',
    property_id: (record as { property_id?: string; propertyId?: string }).property_id
      ?? (record as { property_id?: string; propertyId?: string }).propertyId
      ?? '',
    value_type: (record as { value_type?: string; valueType?: string }).value_type
      ?? (record as { value_type?: string; valueType?: string }).valueType
      ?? '',
    value_json: parseJsonString(
      (record as { value_json?: string; valueJson?: string }).value_json
        ?? (record as { value_json?: string; valueJson?: string }).valueJson
        ?? ''
    ),
    value_entity_id: (record as { value_entity_id?: string; valueEntityId?: string }).value_entity_id
      ?? (record as { value_entity_id?: string; valueEntityId?: string }).valueEntityId
      ?? '',
    ordinal: record.ordinal
  } as unknown as SemanticStatementQualifierRecord;
}

function mapSemanticStatementReference(
  record: SemanticStatementReferenceRecord
): SemanticStatementReferenceRecord {
  return {
    statement_id: (record as { statement_id?: string; statementId?: string }).statement_id
      ?? (record as { statement_id?: string; statementId?: string }).statementId
      ?? '',
    property_id: (record as { property_id?: string; propertyId?: string }).property_id
      ?? (record as { property_id?: string; propertyId?: string }).propertyId
      ?? '',
    value_type: (record as { value_type?: string; valueType?: string }).value_type
      ?? (record as { value_type?: string; valueType?: string }).valueType
      ?? '',
    value_json: parseJsonString(
      (record as { value_json?: string; valueJson?: string }).value_json
        ?? (record as { value_json?: string; valueJson?: string }).valueJson
        ?? ''
    ),
    source_span: (record as { source_span?: string; sourceSpan?: string }).source_span
      ?? (record as { source_span?: string; sourceSpan?: string }).sourceSpan
      ?? '',
    evidence_id: (record as { evidence_id?: string; evidenceId?: string }).evidence_id
      ?? (record as { evidence_id?: string; evidenceId?: string }).evidenceId
      ?? '',
    ordinal: record.ordinal,
    evidence: record.evidence ? mapEvidenceRecord(record.evidence) : undefined,
    locators: (record.locators ?? []).map(mapEvidenceLocatorRecord)
  } as unknown as SemanticStatementReferenceRecord;
}

function mapEvidenceRecord(record: EvidenceRecord): EvidenceRecord {
  const payloadRaw = (record as { evidence_payload_json?: string; evidencePayloadJson?: string }).evidence_payload_json
    ?? (record as { evidence_payload_json?: string; evidencePayloadJson?: string }).evidencePayloadJson
    ?? '{}';
  return {
    evidence_id: (record as { evidence_id?: string; evidenceId?: string }).evidence_id
      ?? (record as { evidence_id?: string; evidenceId?: string }).evidenceId
      ?? '',
    case_id: (record as { case_id?: string; caseId?: string }).case_id
      ?? (record as { case_id?: string; caseId?: string }).caseId
      ?? '',
    event_seq: (record as { event_seq?: number; eventSeq?: number }).event_seq
      ?? (record as { event_seq?: number; eventSeq?: number }).eventSeq
      ?? 0,
    source_kind: (record as { source_kind?: string; sourceKind?: string }).source_kind
      ?? (record as { source_kind?: string; sourceKind?: string }).sourceKind
      ?? '',
    source_id: (record as { source_id?: string; sourceId?: string }).source_id
      ?? (record as { source_id?: string; sourceId?: string }).sourceId
      ?? '',
    artifact_version_id: (record as { artifact_version_id?: string; artifactVersionId?: string }).artifact_version_id
      ?? (record as { artifact_version_id?: string; artifactVersionId?: string }).artifactVersionId
      ?? '',
    evidence_type: (record as { evidence_type?: string; evidenceType?: string }).evidence_type
      ?? (record as { evidence_type?: string; evidenceType?: string }).evidenceType
      ?? '',
    evidence_role: (record as { evidence_role?: string; evidenceRole?: string }).evidence_role
      ?? (record as { evidence_role?: string; evidenceRole?: string }).evidenceRole
      ?? '',
    methodology_framework_id: (record as { methodology_framework_id?: string; methodologyFrameworkId?: string }).methodology_framework_id
      ?? (record as { methodology_framework_id?: string; methodologyFrameworkId?: string }).methodologyFrameworkId
      ?? '',
    evidence_payload: parseJsonString(payloadRaw),
    created_by_type: (record as { created_by_type?: string; createdByType?: string }).created_by_type
      ?? (record as { created_by_type?: string; createdByType?: string }).createdByType
      ?? '',
    created_by_id: (record as { created_by_id?: string; createdById?: string }).created_by_id
      ?? (record as { created_by_id?: string; createdById?: string }).createdById
      ?? '',
    is_derived: (record as { is_derived?: boolean; isDerived?: boolean }).is_derived
      ?? (record as { is_derived?: boolean; isDerived?: boolean }).isDerived
      ?? false,
    status: record.status,
    created_at: (record as { created_at?: string; createdAt?: string }).created_at
      ?? (record as { created_at?: string; createdAt?: string }).createdAt
      ?? '',
    updated_at: (record as { updated_at?: string; updatedAt?: string }).updated_at
      ?? (record as { updated_at?: string; updatedAt?: string }).updatedAt
      ?? ''
  } as unknown as EvidenceRecord;
}

function mapEvidenceLocatorRecord(record: EvidenceLocatorRecord): EvidenceLocatorRecord {
  return {
    evidence_locator_id: (record as { evidence_locator_id?: string; evidenceLocatorId?: string }).evidence_locator_id
      ?? (record as { evidence_locator_id?: string; evidenceLocatorId?: string }).evidenceLocatorId
      ?? '',
    evidence_id: (record as { evidence_id?: string; evidenceId?: string }).evidence_id
      ?? (record as { evidence_id?: string; evidenceId?: string }).evidenceId
      ?? '',
    locator_type: (record as { locator_type?: string; locatorType?: string }).locator_type
      ?? (record as { locator_type?: string; locatorType?: string }).locatorType
      ?? '',
    page_span: (record as { page_span?: string; pageSpan?: string }).page_span
      ?? (record as { page_span?: string; pageSpan?: string }).pageSpan
      ?? '',
    char_span: (record as { char_span?: string; charSpan?: string }).char_span
      ?? (record as { char_span?: string; charSpan?: string }).charSpan
      ?? '',
    sentence_ref: parseJsonString(
      (record as { sentence_ref_json?: string; sentenceRefJson?: string }).sentence_ref_json
        ?? (record as { sentence_ref_json?: string; sentenceRefJson?: string }).sentenceRefJson
        ?? '{}'
    ),
    bbox: parseJsonString(
      (record as { bbox_json?: string; bboxJson?: string }).bbox_json
        ?? (record as { bbox_json?: string; bboxJson?: string }).bboxJson
        ?? '{}'
    ),
    polygon: parseJsonString(
      (record as { polygon_json?: string; polygonJson?: string }).polygon_json
        ?? (record as { polygon_json?: string; polygonJson?: string }).polygonJson
        ?? '{}'
    ),
    time_range: (record as { time_range?: string; timeRange?: string }).time_range
      ?? (record as { time_range?: string; timeRange?: string }).timeRange
      ?? '',
    table_cell: parseJsonString(
      (record as { table_cell_json?: string; tableCellJson?: string }).table_cell_json
        ?? (record as { table_cell_json?: string; tableCellJson?: string }).tableCellJson
        ?? '{}'
    ),
    measurement_field: (record as { measurement_field?: string; measurementField?: string }).measurement_field
      ?? (record as { measurement_field?: string; measurementField?: string }).measurementField
      ?? '',
    locator_payload: parseJsonString(
      (record as { locator_payload_json?: string; locatorPayloadJson?: string }).locator_payload_json
        ?? (record as { locator_payload_json?: string; locatorPayloadJson?: string }).locatorPayloadJson
        ?? '{}'
    ),
    normalized_text: (record as { normalized_text?: string; normalizedText?: string }).normalized_text
      ?? (record as { normalized_text?: string; normalizedText?: string }).normalizedText
      ?? '',
    preview_text: (record as { preview_text?: string; previewText?: string }).preview_text
      ?? (record as { preview_text?: string; previewText?: string }).previewText
      ?? '',
    created_at: (record as { created_at?: string; createdAt?: string }).created_at
      ?? (record as { created_at?: string; createdAt?: string }).createdAt
      ?? ''
  } as unknown as EvidenceLocatorRecord;
}

function parseJsonString(value: string): unknown {
  if (!value) {
    return {};
  }
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function toProtoRequest(request: SearchQueryRequest, traceId: string): GatewayBackendProtoRequest {
  return {
    query: request.query,
    domain: request.domain ?? '',
    case_id: request.case_id ?? '',
    stream_id: request.stream_id ?? '',
    stream_ids: request.stream_ids ?? [],
    mode: request.mode ?? '',
    limit: request.limit ?? 0,
    query_embedding: request.query_embedding ?? [],
    alpha: request.alpha ?? 0,
    trace_id: traceId,
    stream_prefix: request.stream_prefix ?? false
  };
}

function fromProtoHit(hit: GatewayBackendProtoHit): SearchHit {
  const metadataRaw = hit.metadata_json ?? hit.metadataJson ?? '{}';
  const metadataParsed = JSON.parse(metadataRaw) as unknown;
  if (
    metadataParsed === null ||
    Array.isArray(metadataParsed) ||
    typeof metadataParsed !== 'object'
  ) {
    throw new TdbError('INTERNAL_ERROR', 500, 'Search backend returned invalid metadata');
  }

  return {
    doc_id: hit.doc_id ?? hit.docId ?? '',
    case_id: hit.case_id ?? hit.caseId ?? '',
    stream_id: hit.stream_id ?? hit.streamId ?? undefined,
    event_id: hit.event_id ?? hit.eventId ?? '',
    event_seq: Number(hit.event_seq ?? hit.eventSeq ?? 0),
    content: hit.content ?? '',
    metadata: metadataParsed as Record<string, unknown>,
    lexical_score: Number(hit.lexical_score ?? hit.lexicalScore ?? 0),
    vector_score: Number(hit.vector_score ?? hit.vectorScore ?? 0),
    hybrid_score: Number(hit.hybrid_score ?? hit.hybridScore ?? 0)
  };
}

function fromProtoDomainStreamBinding(binding: Record<string, unknown>) {
  return {
    binding_id: String(binding.binding_id ?? binding.bindingId ?? ''),
    domain: String(binding.domain ?? ''),
    stream_id: String(binding.stream_id ?? binding.streamId ?? ''),
    status: String(binding.status ?? ''),
    binding_kind: String(binding.binding_kind ?? binding.bindingKind ?? ''),
    source: String(binding.source ?? ''),
    priority: Number(binding.priority ?? 0),
    created_at: String(binding.created_at ?? binding.createdAt ?? ''),
    updated_at: String(binding.updated_at ?? binding.updatedAt ?? '')
  };
}

function toTdbError(error: unknown): TdbError {
  if (error instanceof TdbError) {
    return error;
  }

  // Log the raw gRPC error for debugging
  console.error('[toTdbError] raw error:', JSON.stringify(error, null, 2));

  if (isGrpcLikeError(error)) {
    if (
      error.code === grpcStatus.UNAVAILABLE ||
      error.code === grpcStatus.DEADLINE_EXCEEDED ||
      error.code === 'UNAVAILABLE' ||
      error.code === 'DEADLINE_EXCEEDED'
    ) {
      return new TdbError('BACKEND_UNAVAILABLE', 503, 'Search backend is unavailable');
    }
    if (error.code === grpcStatus.INVALID_ARGUMENT || error.code === 'INVALID_ARGUMENT') {
      return new TdbError('BAD_REQUEST', 400, error.details || 'Invalid request');
    }
  }

  return new TdbError('INTERNAL_ERROR', 500, 'Internal server error');
}

function isGrpcLikeError(
  value: unknown
): value is { code?: number | string; details?: string } {
  return typeof value === 'object' && value !== null && 'code' in value;
}
