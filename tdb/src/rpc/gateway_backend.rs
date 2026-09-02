use std::net::{Ipv4Addr, SocketAddr};

use sqlx::PgPool;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::transport::{Channel, Server};
use tonic::{Request, Response, Status};
use tonic_health::server::health_reporter;

use crate::rpc::artifact::ArtifactStore;
use crate::rpc::assertion::AssertionStore;
use crate::rpc::decision::DecisionStore;
use crate::rpc::embedding::{EmbeddingClient, EmbeddingConfig};
use crate::rpc::entity::EntityStore;
use crate::rpc::event::EventStore;
use crate::rpc::evidence::EvidenceStore;
use crate::rpc::governance::GovernanceStore;
use crate::rpc::memory::MemoryStore;
use crate::rpc::ontology::{
    OntologyRpcStore, SemanticBatchUpsertInput, SemanticEntityUpsertInput,
    SemanticStatementQualifierInput, SemanticStatementReferenceInput,
    SemanticStatementUpsertInput,
};
use crate::rpc::proto::gateway_backend_client::GatewayBackendClient;
use crate::rpc::proto::gateway_backend_server::{GatewayBackend, GatewayBackendServer};
use crate::rpc::proto::{
    AppendEventRequest, AppendEventResponse, AppendWikiLogRequest, AppendWikiLogResponse,
    ArchiveOntologyFactRequest, ArchiveOntologyFactResponse, CreateArtifactRequest,
    CreateArtifactResponse, CreateArtifactVersionRequest, CreateArtifactVersionResponse,
    FindAuthorityAsOfRequest, FindAuthorityAsOfResponse, FindDecisionRequest, FindDecisionResponse,
    GetActiveOntologyAlertByRuleKeyRequest, GetActiveOntologyAlertByRuleKeyResponse,
    GetActiveOntologyCaseByTitleRequest, GetActiveOntologyCaseByTitleResponse,
    GetArtifactVersionAsOfRequest, GetArtifactVersionAsOfResponse, GetArtifactVersionByIdRequest,
    GetArtifactVersionByIdResponse, GetAssertionPolicyRuleRequest, GetAssertionPolicyRuleResponse,
    GetAssertionRequest, GetAssertionResponse, GetEdgesAsOfRequest, GetEdgesAsOfResponse,
    GetEntityRequest, GetEntityResponse, GetEventSentencesRequest, GetEventSentencesResponse,
    GetEventsRequest, GetEventsResponse, GetEvidenceClassificationRequest,
    GetEvidenceClassificationResponse, GetEvidencePolicyRuleRequest, GetEvidencePolicyRuleResponse,
    GetEvidenceRequest, GetEvidenceResponse, GetLatestSnapshotRequest, GetLatestSnapshotResponse,
    GetMethodologyFrameworkBundleRequest, GetMethodologyFrameworkBundleResponse,
    GetMethodologyFrameworkRequest, GetMethodologyFrameworkResponse, GetOntologyAlertDetailRequest,
    GetOntologyAlertDetailResponse, GetOntologyCaseRequest, GetOntologyCaseResponse,
    GetOntologyConceptNeighborsRequest, GetOntologyConceptNeighborsResponse,
    GetOntologyConceptRequest, GetOntologyConceptResponse, GetOntologyFactRequest,
    GetOntologyFactResponse, GetOntologyNormalizedTermRequest, GetOntologyNormalizedTermResponse,
    GetOntologyObjectTypeRequest, GetOntologyObjectTypeResponse, GetOntologyOpsRunRequest,
    GetOntologyOpsRunResponse, GetOntologyRawTermRequest, GetOntologyRawTermResponse,
    GetOntologyRelationTypeRequest, GetOntologyRelationTypeResponse, GetOntologyTermClusterRequest,
    GetOntologyTermClusterResponse, GetPropertyAsOfRequest, GetPropertyAsOfResponse,
    GetReviewPolicyRequest, GetReviewPolicyResponse, GetSemanticStatementProvenanceRequest,
    GetSemanticStatementProvenanceResponse, GetSemanticStatementRequest,
    GetSemanticStatementResponse, GetSemanticStatementsByEvidenceRequest,
    ListSemanticStatementsRequest, ListSemanticStatementsResponse,
    SetSemanticStatementStatusRequest, SetSemanticStatementStatusResponse,
    GetSemanticStatementsByEvidenceResponse, GetTaxonomySchemeRequest, GetTaxonomySchemeResponse,
    GetTermMappingRegistryRequest, GetTermMappingRegistryResponse, GetTermMappingRuleRequest,
    GetTermMappingRuleResponse, GetWikiPageRequest, GetWikiPageResponse, IndexEventRequest,
    IndexEventResponse, InsertAuthorityGrantRequest,
    InsertAuthorityGrantResponse, InsertDecisionEvidenceRequest, InsertDecisionEvidenceResponse,
    InsertMemoryAnswerArtifactRequest, InsertMemoryAnswerArtifactResponse,
    InsertMemoryAnswerValidationRequest, InsertMemoryAnswerValidationResponse,
    InsertMemoryDecisionRequest, InsertMemoryDecisionResponse, InsertMemoryEpisodeSummaryRequest,
    InsertMemoryEpisodeSummaryResponse, InsertOntologyAlertRequest, InsertOntologyAlertResponse,
    InsertOntologyCaseDecisionRequest, InsertOntologyCaseDecisionResponse,
    InsertOntologyCaseEventRequest, InsertOntologyCaseEventResponse, InsertOntologyCaseRequest,
    InsertOntologyCaseResponse, InsertOntologyOpsRuleRunRequest, InsertOntologyOpsRuleRunResponse,
    InsertRuleOverrideRequest, InsertRuleOverrideResponse, InterpretTermBatchRequest,
    InterpretTermBatchResponse, InterpretTermRequest, InterpretTermResponse,
    LinkOntologyCaseFactRequest, LinkOntologyCaseFactResponse, LintWikiDomainRequest,
    LintWikiDomainResponse, ListAssertionEvidenceLinksRequest, ListAssertionEvidenceLinksResponse,
    ListAssertionPolicyRulesRequest, ListAssertionPolicyRulesResponse,
    ListAssertionRelationsRequest, ListAssertionRelationsResponse, ListConceptAliasesRequest,
    ListConceptAliasesResponse, ListConflictPredicateOntologyCandidatesRequest,
    ListDecisionEvidenceRequest, ListDecisionEvidenceResponse, ListEntitiesRequest,
    ListEntitiesResponse, ListEventConceptLinksRequest, ListEventConceptLinksResponse,
    ListEvidenceDerivationsRequest, ListEvidenceDerivationsResponse, ListEvidenceLocatorsRequest,
    ListEvidenceLocatorsResponse, ListEvidencePolicyRulesRequest, ListEvidencePolicyRulesResponse,
    ListMethodologyFrameworksRequest, ListMethodologyFrameworksResponse, ListOntologyAlertsRequest,
    ListOntologyAlertsResponse, ListOntologyCaseDecisionsRequest,
    ListOntologyCaseDecisionsResponse, ListOntologyCaseEventsRequest,
    ListOntologyCaseEventsResponse, ListOntologyCaseFactsRequest, ListOntologyCaseFactsResponse,
    ListOntologyCasesRequest, ListOntologyCasesResponse, ListOntologyClusterMembersRequest,
    ListOntologyClusterMembersResponse, ListOntologyConceptTypeAssignmentsRequest,
    ListOntologyConceptTypeAssignmentsResponse, ListOntologyConceptsRequest,
    ListOntologyConceptsResponse, ListOntologyEdgesRequest, ListOntologyEdgesResponse,
    ListOntologyFactEvidenceRequest, ListOntologyFactEvidenceResponse,
    ListOntologyFactLinkedAlertsRequest, ListOntologyFactLinkedAlertsResponse,
    ListOntologyFactLinkedCasesRequest, ListOntologyFactLinkedCasesResponse,
    ListOntologyFactReviewsRequest, ListOntologyFactReviewsResponse, ListOntologyFactsRequest,
    ListOntologyFactsResponse, ListOntologyObjectTypesRequest, ListOntologyObjectTypesResponse,
    ListOntologyOpsRuleConfigRequest, ListOntologyOpsRuleConfigResponse,
    ListOntologyOpsRunsRequest, ListOntologyOpsRunsResponse, ListOntologyRawTermCandidatesRequest,
    ListOntologyRawTermCandidatesResponse, ListOntologyRawTermNormalizationsRequest,
    ListOntologyRawTermNormalizationsResponse, ListOntologyRelationCandidatesRequest,
    ListOntologyRelationCandidatesResponse, ListOntologyRelationTypesRequest,
    ListOntologyRelationTypesResponse, ListOntologyTermClustersRequest,
    ListOntologyTermClustersResponse, ListPropertyRowsRequest, ListPropertyRowsResponse,
    ListRecentMemoryDecisionsRequest, ListRecentMemoryDecisionsResponse,
    ListRecentMemoryEpisodeSummariesRequest, ListRecentMemoryEpisodeSummariesResponse,
    ListReviewPoliciesRequest, ListReviewPoliciesResponse, ListRuleOverridesAsOfRequest,
    ListRuleOverridesAsOfResponse, ListStalePendingOntologyCandidatesRequest,
    ListTaxonomySchemesRequest, ListTaxonomySchemesResponse, ListTermMappingRegistriesRequest,
    ListTermMappingRegistriesResponse, ListTermMappingRuleEvidenceRequest,
    ListTermMappingRuleEvidenceResponse, ListWikiLogsRequest, ListWikiLogsResponse,
    ListWikiPagesRequest, ListWikiPagesResponse, RecallMemoryAnswerArtifactsRequest,
    RecallMemoryAnswerArtifactsResponse, RefreshTriggeredOntologyAlertRequest,
    RefreshTriggeredOntologyAlertResponse, ReinforceWikiPageRequest, ReinforceWikiPageResponse,
    ReviewOntologyFactRequest, ReviewOntologyFactResponse, SearchAssertionsRequest,
    SearchAssertionsResponse, SearchConceptAliasesRequest, SearchConceptAliasesResponse,
    SearchEvidenceRequest, SearchEvidenceResponse, SearchOntologyConceptsRequest,
    SearchOntologyConceptsResponse, SearchOntologyFactsRequest, SearchOntologyFactsResponse,
    SearchOntologyNormalizedTermsRequest, SearchOntologyNormalizedTermsResponse,
    SearchOntologyRawTermsRequest, SearchOntologyRawTermsResponse, SearchQueryRequest,
    SearchQueryResponse, SearchTermMappingRulesRequest, SearchTermMappingRulesResponse,
    SearchWikiPagesRequest, SearchWikiPagesResponse, SelectOntologyFactsForBulkReviewRequest,
    SelectOntologyFactsForBulkReviewResponse, UpdateOntologyAlertRequest,
    UpdateOntologyAlertResponse, UpdateOntologyCaseRequest, UpdateOntologyCaseResponse,
    UpsertAssertionEvidenceLinkRequest, UpsertAssertionEvidenceLinkResponse,
    UpsertAssertionPolicyRuleRequest, UpsertAssertionPolicyRuleResponse,
    UpsertAssertionRelationRequest, UpsertAssertionRelationResponse, UpsertAssertionRequest,
    UpsertAssertionResponse, UpsertConceptAliasRequest, UpsertConceptAliasResponse,
    UpsertDecisionRequest, UpsertDecisionResponse, UpsertEdgeRequest, UpsertEdgeResponse,
    UpsertEntityRequest, UpsertEntityResponse, UpsertEventConceptLinkRequest,
    UpsertEventConceptLinkResponse, UpsertEvidenceClassificationRequest,
    UpsertEvidenceClassificationResponse, UpsertEvidenceDerivationRequest,
    UpsertEvidenceDerivationResponse, UpsertEvidenceLocatorRequest, UpsertEvidenceLocatorResponse,
    UpsertEvidencePolicyRuleRequest, UpsertEvidencePolicyRuleResponse, UpsertEvidenceRequest,
    UpsertEvidenceResponse, UpsertMethodologyFrameworkRequest, UpsertMethodologyFrameworkResponse,
    UpsertOntologyClusterMemberRequest, UpsertOntologyClusterMemberResponse,
    UpsertOntologyConceptRequest, UpsertOntologyConceptResponse,
    UpsertOntologyConceptTypeAssignmentRequest, UpsertOntologyConceptTypeAssignmentResponse,
    UpsertOntologyEdgeRequest, UpsertOntologyEdgeResponse, UpsertOntologyFactWithEvidenceRequest,
    UpsertOntologyFactWithEvidenceResponse, UpsertOntologyNormalizedTermRequest,
    UpsertOntologyNormalizedTermResponse, UpsertOntologyObjectTypeRequest,
    UpsertOntologyObjectTypeResponse, UpsertOntologyOpsRuleConfigRequest,
    UpsertOntologyOpsRuleConfigResponse, UpsertOntologyRawTermCandidateRequest,
    UpsertOntologyRawTermCandidateResponse, UpsertOntologyRawTermNormalizationRequest,
    UpsertOntologyRawTermNormalizationResponse, UpsertOntologyRawTermRequest,
    UpsertOntologyRawTermResponse, UpsertOntologyRelationCandidateRequest,
    UpsertOntologyRelationCandidateResponse, UpsertOntologyRelationTypeRequest,
    UpsertOntologyRelationTypeResponse, UpsertOntologyTermClusterRequest,
    UpsertOntologyTermClusterResponse, UpsertPropertyRequest, UpsertPropertyResponse,
    UpsertReviewPolicyRequest, UpsertReviewPolicyResponse, UpsertRuleRequest, UpsertRuleResponse,
    UpsertSemanticBatchRequest, UpsertSemanticBatchResponse,
    UpsertTaxonomySchemeRequest, UpsertTaxonomySchemeResponse, UpsertTermMappingRegistryRequest,
    UpsertTermMappingRegistryResponse, UpsertTermMappingRuleEvidenceRequest,
    UpsertTermMappingRuleEvidenceResponse, UpsertTermMappingRuleRequest,
    UpsertTermMappingRuleResponse, UpsertWikiPageLinkRequest, UpsertWikiPageLinkResponse,
    UpsertWikiPageRequest, UpsertWikiPageResponse, WriteSnapshotRequest, WriteSnapshotResponse,
};
use crate::rpc::search::{IndexEventInput, SearchQueryInput, SearchStore};
use crate::rpc::snapshot::SnapshotStore;
use crate::rpc::state::StateStore;
use crate::rpc::wiki::WikiStore;

#[derive(Debug, Clone)]
pub struct GatewayBackendConfig {
    pub embedding: EmbeddingConfig,
}

impl GatewayBackendConfig {
    /// Load backend config from environment variables.
    /// The startup script sources `tdb/.env`; callers can still override values
    /// by exporting env vars before launching the backend.
    pub fn load() -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        Self::from_env()
    }

    pub fn from_env() -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        Ok(Self {
            embedding: EmbeddingConfig::from_env(),
        })
    }

    pub fn embedding_startup_summary(&self) -> String {
        let provider = "backend";
        let enabled = self.embedding.enabled;
        let model = self.embedding.model.as_str();
        let source = if self.embedding.base_url.is_some() {
            "configured"
        } else {
            "missing"
        };
        let strict = self.embedding.strict;
        format!(
            "embedding provider={provider} enabled={enabled} model={model} config_source={source} strict={strict}"
        )
    }
}

#[derive(Debug)]
pub struct GatewayBackendError {
    code: tonic::Code,
    message: String,
}

impl GatewayBackendError {
    pub fn invalid_argument(message: impl Into<String>) -> Self {
        Self {
            code: tonic::Code::InvalidArgument,
            message: message.into(),
        }
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self {
            code: tonic::Code::Internal,
            message: message.into(),
        }
    }

    pub fn embedding_disabled() -> Self {
        Self::internal("embedding request skipped")
    }

    pub fn not_configured(message: impl Into<String>) -> Self {
        Self {
            code: tonic::Code::Unimplemented,
            message: message.into(),
        }
    }
}

impl From<GatewayBackendError> for Status {
    fn from(value: GatewayBackendError) -> Self {
        Status::new(value.code, value.message)
    }
}

#[derive(Clone)]
pub struct GatewayBackendService {
    store: Option<SearchStore>,
    event: Option<EventStore>,
    state: Option<StateStore>,
    entity: Option<EntityStore>,
    memory: Option<MemoryStore>,
    snapshot: Option<SnapshotStore>,
    artifact: Option<ArtifactStore>,
    assertion: Option<AssertionStore>,
    evidence: Option<EvidenceStore>,
    decision: Option<DecisionStore>,
    ontology: Option<OntologyRpcStore>,
    governance: Option<GovernanceStore>,
    wiki: Option<WikiStore>,
    embedding: EmbeddingClient,
}

fn non_empty_string(value: String) -> Option<String> {
    let trimmed = value.trim().to_string();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed)
    }
}

impl Default for GatewayBackendService {
    fn default() -> Self {
        Self {
            store: None,
            event: None,
            state: None,
            entity: None,
            memory: None,
            snapshot: None,
            artifact: None,
            assertion: None,
            evidence: None,
            decision: None,
            ontology: None,
            governance: None,
            wiki: None,
            embedding: EmbeddingClient::new(EmbeddingConfig {
                enabled: false,
                base_url: None,
                api_key: None,
                model: "qwen3-embedding:8b".into(),
                timeout_ms: 120_000,
                max_chars: 1000,
                strict: false,
            }),
        }
    }
}

impl GatewayBackendService {
    pub async fn from_config(
        database_url: &str,
        config: GatewayBackendConfig,
    ) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let pool = PgPool::connect(database_url).await?;
        let search = SearchStore::new(pool.clone());
        Ok(Self {
            store: Some(search.clone()),
            event: Some(EventStore::new(pool.clone(), search)),
            state: Some(StateStore::new(pool.clone())),
            entity: Some(EntityStore::new(pool.clone())),
            memory: Some(MemoryStore::new(pool.clone())),
            snapshot: Some(SnapshotStore::new(pool.clone())),
            artifact: Some(ArtifactStore::new(pool.clone())),
            assertion: Some(AssertionStore::new(pool.clone())),
            evidence: Some(EvidenceStore::new(pool.clone())),
            decision: Some(DecisionStore::new(pool.clone())),
            ontology: Some(OntologyRpcStore::new(pool.clone())),
            governance: Some(GovernanceStore::new(pool.clone())),
            wiki: Some(WikiStore::new(pool)),
            embedding: EmbeddingClient::new(config.embedding),
        })
    }
}

#[tonic::async_trait]
impl GatewayBackend for GatewayBackendService {
    async fn search_query(
        &self,
        request: Request<SearchQueryRequest>,
    ) -> Result<Response<SearchQueryResponse>, Status> {
        let mut input = SearchQueryInput::from_proto(request.into_inner())?;
        if input.query_embedding.is_none() && input.mode != crate::rpc::search::SearchMode::Lexical
        {
            match self.embedding.generate(&input.query_text).await {
                Ok(embedding) => input.query_embedding = embedding,
                Err(err) if err.message == "embedding request skipped" => {}
                Err(err) => return Err(err.into()),
            }
        }

        let store = self.store.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("SearchQuery is not implemented yet")
        })?;
        store.resolve_domain_stream_scope(&mut input).await?;
        let rows = store
            .search(&input)
            .await
            .map_err(|err| GatewayBackendError::internal(format!("search query failed: {err}")))?;

        Ok(Response::new(SearchQueryResponse {
            hits: rows.into_iter().map(Into::into).collect(),
            resolved_stream_ids: input.resolved_stream_ids,
        }))
    }

    async fn upsert_domain_stream_binding(
        &self,
        request: Request<crate::rpc::proto::UpsertDomainStreamBindingRequest>,
    ) -> Result<Response<crate::rpc::proto::UpsertDomainStreamBindingResponse>, Status> {
        let store = self.store.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("SearchQuery is not implemented yet")
        })?;
        let binding = store
            .upsert_domain_stream_binding(&request.into_inner())
            .await?;
        Ok(Response::new(
            crate::rpc::proto::UpsertDomainStreamBindingResponse {
                binding: Some(binding.into()),
            },
        ))
    }

    async fn list_domain_stream_bindings(
        &self,
        request: Request<crate::rpc::proto::ListDomainStreamBindingsRequest>,
    ) -> Result<Response<crate::rpc::proto::ListDomainStreamBindingsResponse>, Status> {
        let store = self.store.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("SearchQuery is not implemented yet")
        })?;
        let req = request.into_inner();
        let bindings = store
            .list_domain_stream_bindings(
                non_empty_string(req.domain).as_deref(),
                non_empty_string(req.stream_id).as_deref(),
                non_empty_string(req.status).as_deref(),
                req.limit,
            )
            .await?;
        Ok(Response::new(
            crate::rpc::proto::ListDomainStreamBindingsResponse {
                bindings: bindings.into_iter().map(Into::into).collect(),
            },
        ))
    }

    async fn index_event(
        &self,
        request: Request<IndexEventRequest>,
    ) -> Result<Response<IndexEventResponse>, Status> {
        let input = IndexEventInput::from_proto(request.into_inner())?;
        let store = self
            .store
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("SearchStore is not initialized"))?;
        let doc_id = store
            .index(&input)
            .await
            .map_err(|err| GatewayBackendError::internal(format!("index event failed: {err}")))?;

        Ok(Response::new(IndexEventResponse { doc_id }))
    }

    async fn append_event(
        &self,
        request: Request<AppendEventRequest>,
    ) -> Result<Response<AppendEventResponse>, Status> {
        let event = self
            .event
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EventStore is not initialized"))?;
        let req = request.into_inner();
        let event_text = req.event_text.clone();
        let has_embedding = !req.embedding.is_empty();
        let res = event
            .append(req)
            .await
            .map_err(|err| GatewayBackendError::internal(format!("append event failed: {err}")))?;

        // Auto-generate embedding for indexed events when not provided by caller
        if !event_text.is_empty() && !has_embedding {
            if let Some(search) = &self.store {
                match self.embedding.generate(&event_text).await {
                    Ok(Some(vec)) => {
                        let model = self.embedding.model().to_string();
                        let _ = search.upsert_embedding(&res.event_id, &vec, &model).await;
                    }
                    _ => {}
                }
            }
        }

        Ok(Response::new(res))
    }

    async fn get_events(
        &self,
        request: Request<GetEventsRequest>,
    ) -> Result<Response<GetEventsResponse>, Status> {
        let event = self
            .event
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EventStore is not initialized"))?;
        let res = event
            .get_events(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("get events failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn get_event_sentences(
        &self,
        request: Request<GetEventSentencesRequest>,
    ) -> Result<Response<GetEventSentencesResponse>, Status> {
        let event = self
            .event
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EventStore is not initialized"))?;
        let res = event
            .get_event_sentences(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get event sentences failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_property(
        &self,
        request: Request<UpsertPropertyRequest>,
    ) -> Result<Response<UpsertPropertyResponse>, Status> {
        let state = self
            .state
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("StateStore is not initialized"))?;
        let res = state
            .upsert_property(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert property failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_property_as_of(
        &self,
        request: Request<GetPropertyAsOfRequest>,
    ) -> Result<Response<GetPropertyAsOfResponse>, Status> {
        let state = self
            .state
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("StateStore is not initialized"))?;
        let res = state
            .get_property_as_of(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get property as of failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_edge(
        &self,
        request: Request<UpsertEdgeRequest>,
    ) -> Result<Response<UpsertEdgeResponse>, Status> {
        let state = self
            .state
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("StateStore is not initialized"))?;
        let res = state
            .upsert_edge(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("upsert edge failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn get_edges_as_of(
        &self,
        request: Request<GetEdgesAsOfRequest>,
    ) -> Result<Response<GetEdgesAsOfResponse>, Status> {
        let state = self
            .state
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("StateStore is not initialized"))?;
        let res = state
            .get_edges_as_of(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get edges as of failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn list_property_rows(
        &self,
        request: Request<ListPropertyRowsRequest>,
    ) -> Result<Response<ListPropertyRowsResponse>, Status> {
        let state = self
            .state
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("StateStore is not initialized"))?;
        let res = state
            .list_property_rows(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list property rows failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_entity(
        &self,
        request: Request<UpsertEntityRequest>,
    ) -> Result<Response<UpsertEntityResponse>, Status> {
        let entity = self
            .entity
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EntityStore is not initialized"))?;
        let res = entity
            .upsert_entity(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("upsert entity failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn get_entity(
        &self,
        request: Request<GetEntityRequest>,
    ) -> Result<Response<GetEntityResponse>, Status> {
        let entity = self
            .entity
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EntityStore is not initialized"))?;
        let res = entity
            .get_entity(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("get entity failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn list_entities(
        &self,
        request: Request<ListEntitiesRequest>,
    ) -> Result<Response<ListEntitiesResponse>, Status> {
        let entity = self
            .entity
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("EntityStore is not initialized"))?;
        let res = entity
            .list_entities(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("list entities failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn write_snapshot(
        &self,
        request: Request<WriteSnapshotRequest>,
    ) -> Result<Response<WriteSnapshotResponse>, Status> {
        let snapshot = self.snapshot.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("SnapshotStore is not initialized")
        })?;
        let res = snapshot
            .write_snapshot(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("write snapshot failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_latest_snapshot(
        &self,
        request: Request<GetLatestSnapshotRequest>,
    ) -> Result<Response<GetLatestSnapshotResponse>, Status> {
        let snapshot = self.snapshot.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("SnapshotStore is not initialized")
        })?;
        let res = snapshot
            .get_latest_snapshot(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get latest snapshot failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn create_artifact(
        &self,
        request: Request<CreateArtifactRequest>,
    ) -> Result<Response<CreateArtifactResponse>, Status> {
        let artifact = self.artifact.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("ArtifactStore is not initialized")
        })?;
        let res = artifact
            .create_artifact(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("create artifact failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn create_artifact_version(
        &self,
        request: Request<CreateArtifactVersionRequest>,
    ) -> Result<Response<CreateArtifactVersionResponse>, Status> {
        let artifact = self.artifact.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("ArtifactStore is not initialized")
        })?;
        let res = artifact
            .create_artifact_version(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("create artifact version failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_artifact_version_as_of(
        &self,
        request: Request<GetArtifactVersionAsOfRequest>,
    ) -> Result<Response<GetArtifactVersionAsOfResponse>, Status> {
        let artifact = self.artifact.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("ArtifactStore is not initialized")
        })?;
        let res = artifact
            .get_artifact_version_as_of(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get artifact version as of failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_artifact_version_by_id(
        &self,
        request: Request<GetArtifactVersionByIdRequest>,
    ) -> Result<Response<GetArtifactVersionByIdResponse>, Status> {
        let artifact = self.artifact.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("ArtifactStore is not initialized")
        })?;
        let res = artifact
            .get_artifact_version_by_id(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get artifact version by id failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_decision(
        &self,
        request: Request<UpsertDecisionRequest>,
    ) -> Result<Response<UpsertDecisionResponse>, Status> {
        let decision = self.decision.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("DecisionStore is not initialized")
        })?;
        let res = decision
            .upsert_decision(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert decision failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_assertion(
        &self,
        request: Request<UpsertAssertionRequest>,
    ) -> Result<Response<UpsertAssertionResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .upsert_assertion(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert assertion failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_assertion(
        &self,
        request: Request<GetAssertionRequest>,
    ) -> Result<Response<GetAssertionResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .get_assertion(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("get assertion failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn search_assertions(
        &self,
        request: Request<SearchAssertionsRequest>,
    ) -> Result<Response<SearchAssertionsResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .search_assertions(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("search assertions failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_evidence(
        &self,
        request: Request<UpsertEvidenceRequest>,
    ) -> Result<Response<UpsertEvidenceResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .upsert_evidence(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert evidence failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn get_evidence(
        &self,
        request: Request<GetEvidenceRequest>,
    ) -> Result<Response<GetEvidenceResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .get_evidence(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("get evidence failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn search_evidence(
        &self,
        request: Request<SearchEvidenceRequest>,
    ) -> Result<Response<SearchEvidenceResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .search_evidence(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("search evidence failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_evidence_locator(
        &self,
        request: Request<UpsertEvidenceLocatorRequest>,
    ) -> Result<Response<UpsertEvidenceLocatorResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .upsert_evidence_locator(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert evidence locator failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn list_evidence_locators(
        &self,
        request: Request<ListEvidenceLocatorsRequest>,
    ) -> Result<Response<ListEvidenceLocatorsResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .list_evidence_locators(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list evidence locators failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_evidence_derivation(
        &self,
        request: Request<UpsertEvidenceDerivationRequest>,
    ) -> Result<Response<UpsertEvidenceDerivationResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .upsert_evidence_derivation(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert evidence derivation failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn list_evidence_derivations(
        &self,
        request: Request<ListEvidenceDerivationsRequest>,
    ) -> Result<Response<ListEvidenceDerivationsResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .list_evidence_derivations(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list evidence derivations failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_evidence_classification(
        &self,
        request: Request<UpsertEvidenceClassificationRequest>,
    ) -> Result<Response<UpsertEvidenceClassificationResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .upsert_evidence_classification(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "upsert evidence classification failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn get_evidence_classification(
        &self,
        request: Request<GetEvidenceClassificationRequest>,
    ) -> Result<Response<GetEvidenceClassificationResponse>, Status> {
        let evidence = self.evidence.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("EvidenceStore is not initialized")
        })?;
        let res = evidence
            .get_evidence_classification(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("get evidence classification failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_assertion_evidence_link(
        &self,
        request: Request<UpsertAssertionEvidenceLinkRequest>,
    ) -> Result<Response<UpsertAssertionEvidenceLinkResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .upsert_assertion_evidence_link(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "upsert assertion evidence link failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn list_assertion_evidence_links(
        &self,
        request: Request<ListAssertionEvidenceLinksRequest>,
    ) -> Result<Response<ListAssertionEvidenceLinksResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .list_assertion_evidence_links(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "list assertion evidence links failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_assertion_relation(
        &self,
        request: Request<UpsertAssertionRelationRequest>,
    ) -> Result<Response<UpsertAssertionRelationResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .upsert_assertion_relation(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("upsert assertion relation failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn list_assertion_relations(
        &self,
        request: Request<ListAssertionRelationsRequest>,
    ) -> Result<Response<ListAssertionRelationsResponse>, Status> {
        let assertion = self.assertion.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("AssertionStore is not initialized")
        })?;
        let res = assertion
            .list_assertion_relations(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list assertion relations failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn insert_decision_evidence(
        &self,
        request: Request<InsertDecisionEvidenceRequest>,
    ) -> Result<Response<InsertDecisionEvidenceResponse>, Status> {
        let decision = self.decision.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("DecisionStore is not initialized")
        })?;
        let res = decision
            .insert_decision_evidence(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("insert decision evidence failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn find_decision(
        &self,
        request: Request<FindDecisionRequest>,
    ) -> Result<Response<FindDecisionResponse>, Status> {
        let decision = self.decision.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("DecisionStore is not initialized")
        })?;
        let res = decision
            .find_decision(request.into_inner())
            .await
            .map_err(|err| GatewayBackendError::internal(format!("find decision failed: {err}")))?;
        Ok(Response::new(res))
    }

    async fn list_decision_evidence(
        &self,
        request: Request<ListDecisionEvidenceRequest>,
    ) -> Result<Response<ListDecisionEvidenceResponse>, Status> {
        let decision = self.decision.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("DecisionStore is not initialized")
        })?;
        let res = decision
            .list_decision_evidence(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list decision evidence failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn insert_memory_decision(
        &self,
        request: Request<InsertMemoryDecisionRequest>,
    ) -> Result<Response<InsertMemoryDecisionResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .insert_memory_decision(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("insert memory decision failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn list_recent_memory_decisions(
        &self,
        request: Request<ListRecentMemoryDecisionsRequest>,
    ) -> Result<Response<ListRecentMemoryDecisionsResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .list_recent_memory_decisions(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!("list recent memory decisions failed: {err}"))
            })?;
        Ok(Response::new(res))
    }

    async fn insert_memory_episode_summary(
        &self,
        request: Request<InsertMemoryEpisodeSummaryRequest>,
    ) -> Result<Response<InsertMemoryEpisodeSummaryResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .insert_memory_episode_summary(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "insert memory episode summary failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn list_recent_memory_episode_summaries(
        &self,
        request: Request<ListRecentMemoryEpisodeSummariesRequest>,
    ) -> Result<Response<ListRecentMemoryEpisodeSummariesResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .list_recent_memory_episode_summaries(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "list recent memory episode summaries failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn insert_memory_answer_artifact(
        &self,
        request: Request<InsertMemoryAnswerArtifactRequest>,
    ) -> Result<Response<InsertMemoryAnswerArtifactResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .insert_memory_answer_artifact(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "insert memory answer artifact failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn recall_memory_answer_artifacts(
        &self,
        request: Request<RecallMemoryAnswerArtifactsRequest>,
    ) -> Result<Response<RecallMemoryAnswerArtifactsResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .recall_memory_answer_artifacts(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "recall memory answer artifacts failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn insert_memory_answer_validation(
        &self,
        request: Request<InsertMemoryAnswerValidationRequest>,
    ) -> Result<Response<InsertMemoryAnswerValidationResponse>, Status> {
        let memory = self
            .memory
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("MemoryStore is not initialized"))?;
        let res = memory
            .insert_memory_answer_validation(request.into_inner())
            .await
            .map_err(|err| {
                GatewayBackendError::internal(format!(
                    "insert memory answer validation failed: {err}"
                ))
            })?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_concept(
        &self,
        req: Request<UpsertOntologyConceptRequest>,
    ) -> Result<Response<UpsertOntologyConceptResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_concept(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_concept(
        &self,
        req: Request<GetOntologyConceptRequest>,
    ) -> Result<Response<GetOntologyConceptResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_concept(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_concepts(
        &self,
        req: Request<ListOntologyConceptsRequest>,
    ) -> Result<Response<ListOntologyConceptsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_concepts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_concept_alias(
        &self,
        req: Request<UpsertConceptAliasRequest>,
    ) -> Result<Response<UpsertConceptAliasResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_concept_alias(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_concept_aliases(
        &self,
        req: Request<ListConceptAliasesRequest>,
    ) -> Result<Response<ListConceptAliasesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_concept_aliases(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_edge(
        &self,
        req: Request<UpsertOntologyEdgeRequest>,
    ) -> Result<Response<UpsertOntologyEdgeResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_edge(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_edges(
        &self,
        req: Request<ListOntologyEdgesRequest>,
    ) -> Result<Response<ListOntologyEdgesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_edges(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_event_concept_link(
        &self,
        req: Request<UpsertEventConceptLinkRequest>,
    ) -> Result<Response<UpsertEventConceptLinkResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_event_concept_link(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_event_concept_links(
        &self,
        req: Request<ListEventConceptLinksRequest>,
    ) -> Result<Response<ListEventConceptLinksResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_event_concept_links(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_object_type(
        &self,
        req: Request<UpsertOntologyObjectTypeRequest>,
    ) -> Result<Response<UpsertOntologyObjectTypeResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_object_type(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_object_type(
        &self,
        req: Request<GetOntologyObjectTypeRequest>,
    ) -> Result<Response<GetOntologyObjectTypeResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_object_type(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_object_types(
        &self,
        req: Request<ListOntologyObjectTypesRequest>,
    ) -> Result<Response<ListOntologyObjectTypesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_object_types(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_concept_type_assignment(
        &self,
        req: Request<UpsertOntologyConceptTypeAssignmentRequest>,
    ) -> Result<Response<UpsertOntologyConceptTypeAssignmentResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_concept_type_assignment(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_concept_type_assignments(
        &self,
        req: Request<ListOntologyConceptTypeAssignmentsRequest>,
    ) -> Result<Response<ListOntologyConceptTypeAssignmentsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_concept_type_assignments(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_relation_type(
        &self,
        req: Request<UpsertOntologyRelationTypeRequest>,
    ) -> Result<Response<UpsertOntologyRelationTypeResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_relation_type(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_relation_type(
        &self,
        req: Request<GetOntologyRelationTypeRequest>,
    ) -> Result<Response<GetOntologyRelationTypeResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_relation_type(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_relation_types(
        &self,
        req: Request<ListOntologyRelationTypesRequest>,
    ) -> Result<Response<ListOntologyRelationTypesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_relation_types(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_facts(
        &self,
        req: Request<ListOntologyFactsRequest>,
    ) -> Result<Response<ListOntologyFactsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_facts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_fact_with_evidence(
        &self,
        req: Request<UpsertOntologyFactWithEvidenceRequest>,
    ) -> Result<Response<UpsertOntologyFactWithEvidenceResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_fact_with_evidence(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_semantic_batch(
        &self,
        req: Request<UpsertSemanticBatchRequest>,
    ) -> Result<Response<UpsertSemanticBatchResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let batch = semantic_batch_from_proto(req.into_inner())?;
        let res = ontology
            .upsert_semantic_batch(batch)
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_semantic_statement(
        &self,
        req: Request<GetSemanticStatementRequest>,
    ) -> Result<Response<GetSemanticStatementResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_statement(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_semantic_statements(
        &self,
        req: Request<ListSemanticStatementsRequest>,
    ) -> Result<Response<ListSemanticStatementsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_statements(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn set_semantic_statement_status(
        &self,
        req: Request<SetSemanticStatementStatusRequest>,
    ) -> Result<Response<SetSemanticStatementStatusResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .set_statement_status(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_semantic_statement_provenance(
        &self,
        req: Request<GetSemanticStatementProvenanceRequest>,
    ) -> Result<Response<GetSemanticStatementProvenanceResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_statement_provenance(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_semantic_statements_by_evidence(
        &self,
        req: Request<GetSemanticStatementsByEvidenceRequest>,
    ) -> Result<Response<GetSemanticStatementsByEvidenceResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_statements_by_evidence(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_ontology_concepts(
        &self,
        req: Request<SearchOntologyConceptsRequest>,
    ) -> Result<Response<SearchOntologyConceptsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_concepts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_concept_aliases(
        &self,
        req: Request<SearchConceptAliasesRequest>,
    ) -> Result<Response<SearchConceptAliasesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_aliases(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_ontology_facts(
        &self,
        req: Request<SearchOntologyFactsRequest>,
    ) -> Result<Response<SearchOntologyFactsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_facts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_concept_neighbors(
        &self,
        req: Request<GetOntologyConceptNeighborsRequest>,
    ) -> Result<Response<GetOntologyConceptNeighborsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_neighbors(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn archive_ontology_fact(
        &self,
        req: Request<ArchiveOntologyFactRequest>,
    ) -> Result<Response<ArchiveOntologyFactResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .archive_fact(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_term_mapping_registry(
        &self,
        req: Request<UpsertTermMappingRegistryRequest>,
    ) -> Result<Response<UpsertTermMappingRegistryResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_term_mapping_registry(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_term_mapping_registry(
        &self,
        req: Request<GetTermMappingRegistryRequest>,
    ) -> Result<Response<GetTermMappingRegistryResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_term_mapping_registry(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_term_mapping_registries(
        &self,
        req: Request<ListTermMappingRegistriesRequest>,
    ) -> Result<Response<ListTermMappingRegistriesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_term_mapping_registries(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_term_mapping_rule(
        &self,
        req: Request<UpsertTermMappingRuleRequest>,
    ) -> Result<Response<UpsertTermMappingRuleResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_term_mapping_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_term_mapping_rule(
        &self,
        req: Request<GetTermMappingRuleRequest>,
    ) -> Result<Response<GetTermMappingRuleResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_term_mapping_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_term_mapping_rules(
        &self,
        req: Request<SearchTermMappingRulesRequest>,
    ) -> Result<Response<SearchTermMappingRulesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_term_mapping_rules(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_term_mapping_rule_evidence(
        &self,
        req: Request<UpsertTermMappingRuleEvidenceRequest>,
    ) -> Result<Response<UpsertTermMappingRuleEvidenceResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_term_mapping_rule_evidence(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_term_mapping_rule_evidence(
        &self,
        req: Request<ListTermMappingRuleEvidenceRequest>,
    ) -> Result<Response<ListTermMappingRuleEvidenceResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_term_mapping_rule_evidence(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn interpret_term(
        &self,
        req: Request<InterpretTermRequest>,
    ) -> Result<Response<InterpretTermResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .interpret_term(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn interpret_term_batch(
        &self,
        req: Request<InterpretTermBatchRequest>,
    ) -> Result<Response<InterpretTermBatchResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .interpret_term_batch(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_raw_term(
        &self,
        req: Request<UpsertOntologyRawTermRequest>,
    ) -> Result<Response<UpsertOntologyRawTermResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_raw_term(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_raw_term(
        &self,
        req: Request<GetOntologyRawTermRequest>,
    ) -> Result<Response<GetOntologyRawTermResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_ontology_raw_term(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_ontology_raw_terms(
        &self,
        req: Request<SearchOntologyRawTermsRequest>,
    ) -> Result<Response<SearchOntologyRawTermsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_ontology_raw_terms(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_raw_term_candidate(
        &self,
        req: Request<UpsertOntologyRawTermCandidateRequest>,
    ) -> Result<Response<UpsertOntologyRawTermCandidateResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_raw_term_candidate(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_raw_term_candidates(
        &self,
        req: Request<ListOntologyRawTermCandidatesRequest>,
    ) -> Result<Response<ListOntologyRawTermCandidatesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_ontology_raw_term_candidates(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_normalized_term(
        &self,
        req: Request<UpsertOntologyNormalizedTermRequest>,
    ) -> Result<Response<UpsertOntologyNormalizedTermResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_normalized_term(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_normalized_term(
        &self,
        req: Request<GetOntologyNormalizedTermRequest>,
    ) -> Result<Response<GetOntologyNormalizedTermResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_ontology_normalized_term(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_ontology_normalized_terms(
        &self,
        req: Request<SearchOntologyNormalizedTermsRequest>,
    ) -> Result<Response<SearchOntologyNormalizedTermsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .search_ontology_normalized_terms(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_term_cluster(
        &self,
        req: Request<UpsertOntologyTermClusterRequest>,
    ) -> Result<Response<UpsertOntologyTermClusterResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_term_cluster(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_term_cluster(
        &self,
        req: Request<GetOntologyTermClusterRequest>,
    ) -> Result<Response<GetOntologyTermClusterResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .get_ontology_term_cluster(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_term_clusters(
        &self,
        req: Request<ListOntologyTermClustersRequest>,
    ) -> Result<Response<ListOntologyTermClustersResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_ontology_term_clusters(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_cluster_member(
        &self,
        req: Request<UpsertOntologyClusterMemberRequest>,
    ) -> Result<Response<UpsertOntologyClusterMemberResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_cluster_member(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_cluster_members(
        &self,
        req: Request<ListOntologyClusterMembersRequest>,
    ) -> Result<Response<ListOntologyClusterMembersResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_ontology_cluster_members(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_relation_candidate(
        &self,
        req: Request<UpsertOntologyRelationCandidateRequest>,
    ) -> Result<Response<UpsertOntologyRelationCandidateResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_relation_candidate(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_relation_candidates(
        &self,
        req: Request<ListOntologyRelationCandidatesRequest>,
    ) -> Result<Response<ListOntologyRelationCandidatesResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_ontology_relation_candidates(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_ontology_raw_term_normalization(
        &self,
        req: Request<UpsertOntologyRawTermNormalizationRequest>,
    ) -> Result<Response<UpsertOntologyRawTermNormalizationResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .upsert_ontology_raw_term_normalization(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_raw_term_normalizations(
        &self,
        req: Request<ListOntologyRawTermNormalizationsRequest>,
    ) -> Result<Response<ListOntologyRawTermNormalizationsResponse>, Status> {
        let ontology = self
            .ontology
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("OntologyStore not initialized"))?;
        let res = ontology
            .list_ontology_raw_term_normalizations(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    // --- Governance ---

    async fn upsert_rule(
        &self,
        req: Request<UpsertRuleRequest>,
    ) -> Result<Response<UpsertRuleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn insert_authority_grant(
        &self,
        req: Request<InsertAuthorityGrantRequest>,
    ) -> Result<Response<InsertAuthorityGrantResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_authority_grant(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn insert_rule_override(
        &self,
        req: Request<InsertRuleOverrideRequest>,
    ) -> Result<Response<InsertRuleOverrideResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_rule_override(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn find_authority_as_of(
        &self,
        req: Request<FindAuthorityAsOfRequest>,
    ) -> Result<Response<FindAuthorityAsOfResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .find_authority_as_of(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_rule_overrides_as_of(
        &self,
        req: Request<ListRuleOverridesAsOfRequest>,
    ) -> Result<Response<ListRuleOverridesAsOfResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_rule_overrides_as_of(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_methodology_framework(
        &self,
        req: Request<UpsertMethodologyFrameworkRequest>,
    ) -> Result<Response<UpsertMethodologyFrameworkResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_methodology_framework(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_methodology_framework(
        &self,
        req: Request<GetMethodologyFrameworkRequest>,
    ) -> Result<Response<GetMethodologyFrameworkResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_methodology_framework(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_methodology_frameworks(
        &self,
        req: Request<ListMethodologyFrameworksRequest>,
    ) -> Result<Response<ListMethodologyFrameworksResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_methodology_frameworks(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_methodology_framework_bundle(
        &self,
        req: Request<GetMethodologyFrameworkBundleRequest>,
    ) -> Result<Response<GetMethodologyFrameworkBundleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_methodology_framework_bundle(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_taxonomy_scheme(
        &self,
        req: Request<UpsertTaxonomySchemeRequest>,
    ) -> Result<Response<UpsertTaxonomySchemeResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_taxonomy_scheme(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_taxonomy_scheme(
        &self,
        req: Request<GetTaxonomySchemeRequest>,
    ) -> Result<Response<GetTaxonomySchemeResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_taxonomy_scheme(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_taxonomy_schemes(
        &self,
        req: Request<ListTaxonomySchemesRequest>,
    ) -> Result<Response<ListTaxonomySchemesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_taxonomy_schemes(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_evidence_policy_rule(
        &self,
        req: Request<UpsertEvidencePolicyRuleRequest>,
    ) -> Result<Response<UpsertEvidencePolicyRuleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_evidence_policy_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_evidence_policy_rule(
        &self,
        req: Request<GetEvidencePolicyRuleRequest>,
    ) -> Result<Response<GetEvidencePolicyRuleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_evidence_policy_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_evidence_policy_rules(
        &self,
        req: Request<ListEvidencePolicyRulesRequest>,
    ) -> Result<Response<ListEvidencePolicyRulesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_evidence_policy_rules(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_assertion_policy_rule(
        &self,
        req: Request<UpsertAssertionPolicyRuleRequest>,
    ) -> Result<Response<UpsertAssertionPolicyRuleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_assertion_policy_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_assertion_policy_rule(
        &self,
        req: Request<GetAssertionPolicyRuleRequest>,
    ) -> Result<Response<GetAssertionPolicyRuleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_assertion_policy_rule(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_assertion_policy_rules(
        &self,
        req: Request<ListAssertionPolicyRulesRequest>,
    ) -> Result<Response<ListAssertionPolicyRulesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_assertion_policy_rules(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_review_policy(
        &self,
        req: Request<UpsertReviewPolicyRequest>,
    ) -> Result<Response<UpsertReviewPolicyResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_review_policy(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_review_policy(
        &self,
        req: Request<GetReviewPolicyRequest>,
    ) -> Result<Response<GetReviewPolicyResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_review_policy(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_review_policies(
        &self,
        req: Request<ListReviewPoliciesRequest>,
    ) -> Result<Response<ListReviewPoliciesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_review_policies(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    // --- Ontology Facts ---

    async fn review_ontology_fact(
        &self,
        req: Request<ReviewOntologyFactRequest>,
    ) -> Result<Response<ReviewOntologyFactResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .review_ontology_fact(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_fact(
        &self,
        req: Request<GetOntologyFactRequest>,
    ) -> Result<Response<GetOntologyFactResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_ontology_fact(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_fact_reviews(
        &self,
        req: Request<ListOntologyFactReviewsRequest>,
    ) -> Result<Response<ListOntologyFactReviewsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_fact_reviews(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_fact_evidence(
        &self,
        req: Request<ListOntologyFactEvidenceRequest>,
    ) -> Result<Response<ListOntologyFactEvidenceResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_fact_evidence(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_fact_linked_cases(
        &self,
        req: Request<ListOntologyFactLinkedCasesRequest>,
    ) -> Result<Response<ListOntologyFactLinkedCasesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_fact_linked_cases(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_fact_linked_alerts(
        &self,
        req: Request<ListOntologyFactLinkedAlertsRequest>,
    ) -> Result<Response<ListOntologyFactLinkedAlertsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_fact_linked_alerts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn select_ontology_facts_for_bulk_review(
        &self,
        req: Request<SelectOntologyFactsForBulkReviewRequest>,
    ) -> Result<Response<SelectOntologyFactsForBulkReviewResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .select_ontology_facts_for_bulk_review(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    // --- Ontology Cases ---

    async fn insert_ontology_case(
        &self,
        req: Request<InsertOntologyCaseRequest>,
    ) -> Result<Response<InsertOntologyCaseResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_ontology_case(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_case(
        &self,
        req: Request<GetOntologyCaseRequest>,
    ) -> Result<Response<GetOntologyCaseResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_ontology_case(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_cases(
        &self,
        req: Request<ListOntologyCasesRequest>,
    ) -> Result<Response<ListOntologyCasesResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_cases(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn update_ontology_case(
        &self,
        req: Request<UpdateOntologyCaseRequest>,
    ) -> Result<Response<UpdateOntologyCaseResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .update_ontology_case(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn link_ontology_case_fact(
        &self,
        req: Request<LinkOntologyCaseFactRequest>,
    ) -> Result<Response<LinkOntologyCaseFactResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .link_ontology_case_fact(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_case_facts(
        &self,
        req: Request<ListOntologyCaseFactsRequest>,
    ) -> Result<Response<ListOntologyCaseFactsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_case_facts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn insert_ontology_case_decision(
        &self,
        req: Request<InsertOntologyCaseDecisionRequest>,
    ) -> Result<Response<InsertOntologyCaseDecisionResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_ontology_case_decision(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_case_decisions(
        &self,
        req: Request<ListOntologyCaseDecisionsRequest>,
    ) -> Result<Response<ListOntologyCaseDecisionsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_case_decisions(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn insert_ontology_case_event(
        &self,
        req: Request<InsertOntologyCaseEventRequest>,
    ) -> Result<Response<InsertOntologyCaseEventResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_ontology_case_event(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_case_events(
        &self,
        req: Request<ListOntologyCaseEventsRequest>,
    ) -> Result<Response<ListOntologyCaseEventsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_case_events(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    // --- Ontology Alerts ---

    async fn insert_ontology_alert(
        &self,
        req: Request<InsertOntologyAlertRequest>,
    ) -> Result<Response<InsertOntologyAlertResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_ontology_alert(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_alert_detail(
        &self,
        req: Request<GetOntologyAlertDetailRequest>,
    ) -> Result<Response<GetOntologyAlertDetailResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_ontology_alert_detail(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_alerts(
        &self,
        req: Request<ListOntologyAlertsRequest>,
    ) -> Result<Response<ListOntologyAlertsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_alerts(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn update_ontology_alert(
        &self,
        req: Request<UpdateOntologyAlertRequest>,
    ) -> Result<Response<UpdateOntologyAlertResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .update_ontology_alert(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn refresh_triggered_ontology_alert(
        &self,
        req: Request<RefreshTriggeredOntologyAlertRequest>,
    ) -> Result<Response<RefreshTriggeredOntologyAlertResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .refresh_triggered_ontology_alert(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    // --- Ontology Ops ---

    async fn upsert_ontology_ops_rule_config(
        &self,
        req: Request<UpsertOntologyOpsRuleConfigRequest>,
    ) -> Result<Response<UpsertOntologyOpsRuleConfigResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .upsert_ontology_ops_rule_config(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_ops_rule_config(
        &self,
        req: Request<ListOntologyOpsRuleConfigRequest>,
    ) -> Result<Response<ListOntologyOpsRuleConfigResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_ops_rule_config(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_stale_pending_ontology_candidates(
        &self,
        req: Request<ListStalePendingOntologyCandidatesRequest>,
    ) -> Result<Response<ListOntologyFactsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_stale_pending_ontology_candidates(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_conflict_predicate_ontology_candidates(
        &self,
        req: Request<ListConflictPredicateOntologyCandidatesRequest>,
    ) -> Result<Response<ListOntologyFactsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_conflict_predicate_ontology_candidates(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_active_ontology_case_by_title(
        &self,
        req: Request<GetActiveOntologyCaseByTitleRequest>,
    ) -> Result<Response<GetActiveOntologyCaseByTitleResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_active_ontology_case_by_title(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_active_ontology_alert_by_rule_key(
        &self,
        req: Request<GetActiveOntologyAlertByRuleKeyRequest>,
    ) -> Result<Response<GetActiveOntologyAlertByRuleKeyResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_active_ontology_alert_by_rule_key(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn insert_ontology_ops_rule_run(
        &self,
        req: Request<InsertOntologyOpsRuleRunRequest>,
    ) -> Result<Response<InsertOntologyOpsRuleRunResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .insert_ontology_ops_rule_run(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_ontology_ops_run(
        &self,
        req: Request<GetOntologyOpsRunRequest>,
    ) -> Result<Response<GetOntologyOpsRunResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .get_ontology_ops_run(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_ontology_ops_runs(
        &self,
        req: Request<ListOntologyOpsRunsRequest>,
    ) -> Result<Response<ListOntologyOpsRunsResponse>, Status> {
        let gov = self.governance.as_ref().ok_or_else(|| {
            GatewayBackendError::not_configured("GovernanceStore not initialized")
        })?;
        let res = gov
            .list_ontology_ops_runs(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_wiki_page(
        &self,
        req: Request<UpsertWikiPageRequest>,
    ) -> Result<Response<UpsertWikiPageResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .upsert_wiki_page(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn upsert_wiki_page_link(
        &self,
        req: Request<UpsertWikiPageLinkRequest>,
    ) -> Result<Response<UpsertWikiPageLinkResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .upsert_wiki_page_link(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn get_wiki_page(
        &self,
        req: Request<GetWikiPageRequest>,
    ) -> Result<Response<GetWikiPageResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .get_wiki_page(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn search_wiki_pages(
        &self,
        req: Request<SearchWikiPagesRequest>,
    ) -> Result<Response<SearchWikiPagesResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .search_wiki_pages(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_wiki_pages(
        &self,
        req: Request<ListWikiPagesRequest>,
    ) -> Result<Response<ListWikiPagesResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .list_wiki_pages(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn reinforce_wiki_page(
        &self,
        req: Request<ReinforceWikiPageRequest>,
    ) -> Result<Response<ReinforceWikiPageResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .reinforce_wiki_page(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn append_wiki_log(
        &self,
        req: Request<AppendWikiLogRequest>,
    ) -> Result<Response<AppendWikiLogResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .append_wiki_log(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn list_wiki_logs(
        &self,
        req: Request<ListWikiLogsRequest>,
    ) -> Result<Response<ListWikiLogsResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .list_wiki_logs(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }

    async fn lint_wiki_domain(
        &self,
        req: Request<LintWikiDomainRequest>,
    ) -> Result<Response<LintWikiDomainResponse>, Status> {
        let wiki = self
            .wiki
            .as_ref()
            .ok_or_else(|| GatewayBackendError::not_configured("WikiStore not initialized"))?;
        let res = wiki
            .lint_wiki_domain(req.into_inner())
            .await
            .map_err(|e| GatewayBackendError::internal(e.to_string()))?;
        Ok(Response::new(res))
    }
}

pub async fn serve(addr: SocketAddr) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let service = GatewayBackendService::default();
    serve_with_service(addr, service).await
}

pub async fn serve_with_service(
    addr: SocketAddr,
    service: GatewayBackendService,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let (mut reporter, health_service) = health_reporter();
    reporter
        .set_serving::<GatewayBackendServer<GatewayBackendService>>()
        .await;

    Server::builder()
        .add_service(health_service)
        .add_service(GatewayBackendServer::new(service))
        .serve(addr)
        .await?;

    Ok(())
}

pub mod test_support {
    use super::*;

    pub async fn spawn_test_server()
    -> Result<(SocketAddr, oneshot::Sender<()>), Box<dyn std::error::Error + Send + Sync>> {
        spawn_test_server_with_service(GatewayBackendService::default()).await
    }

    pub async fn spawn_test_server_with_service(
        service: GatewayBackendService,
    ) -> Result<(SocketAddr, oneshot::Sender<()>), Box<dyn std::error::Error + Send + Sync>> {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).await?;
        let addr = listener.local_addr()?;
        let incoming = TcpListenerStream::new(listener);
        let (shutdown_tx, shutdown_rx) = oneshot::channel::<()>();

        tokio::spawn(async move {
            let (mut reporter, health_service) = health_reporter();
            reporter
                .set_serving::<GatewayBackendServer<GatewayBackendService>>()
                .await;

            Server::builder()
                .add_service(health_service)
                .add_service(GatewayBackendServer::new(service))
                .serve_with_incoming_shutdown(incoming, async {
                    let _ = shutdown_rx.await;
                })
                .await
                .expect("test gRPC server should run");
        });

        Ok((addr, shutdown_tx))
    }

    pub async fn connect_client(
        addr: SocketAddr,
    ) -> Result<GatewayBackendClient<Channel>, tonic::transport::Error> {
        GatewayBackendClient::connect(format!("http://{}", addr)).await
    }

    pub async fn spawn_test_server_with_database(
        database_url: &str,
    ) -> Result<(SocketAddr, oneshot::Sender<()>), Box<dyn std::error::Error + Send + Sync>> {
        let service = GatewayBackendService::from_config(
            database_url,
            GatewayBackendConfig {
                embedding: EmbeddingConfig {
                    enabled: false,
                    base_url: None,
                    api_key: None,
                    model: "qwen3-embedding:8b".into(),
                    timeout_ms: 120_000,
                    max_chars: 1000,
                    strict: false,
                },
            },
        )
        .await?;
        spawn_test_server_with_service(service).await
    }
}

fn semantic_batch_from_proto(
    req: UpsertSemanticBatchRequest,
) -> Result<SemanticBatchUpsertInput, GatewayBackendError> {
    Ok(SemanticBatchUpsertInput {
        entities: req
            .entities
            .into_iter()
            .map(|entity| {
                Ok(SemanticEntityUpsertInput {
                    entity_id: entity.entity_id,
                    entity_kind: entity.entity_kind,
                    semantic_role: entity.semantic_role,
                    namespace: entity.namespace,
                    status: entity.status,
                    property_datatype: non_empty_string(entity.property_datatype),
                    metadata_json: parse_json_field(&entity.metadata_json, "entity.metadata_json")?,
                })
            })
            .collect::<Result<Vec<_>, GatewayBackendError>>()?,
        statements: req
            .statements
            .into_iter()
            .map(|statement| {
                Ok(SemanticStatementUpsertInput {
                    statement_key: statement.statement_key,
                    subject_id: statement.subject_id,
                    property_id: statement.property_id,
                    value_type: statement.value_type,
                    value_entity_id: non_empty_string(statement.value_entity_id),
                    value_json: parse_json_field(&statement.value_json, "statement.value_json")?,
                    status: statement.status,
                    confidence: Some(statement.confidence),
                    created_by: statement.created_by,
                    metadata_json: parse_json_field(
                        &statement.metadata_json,
                        "statement.metadata_json",
                    )?,
                })
            })
            .collect::<Result<Vec<_>, GatewayBackendError>>()?,
        qualifiers: req
            .qualifiers
            .into_iter()
            .map(|qualifier| {
                Ok(SemanticStatementQualifierInput {
                    statement_key: qualifier.statement_key,
                    property_id: qualifier.property_id,
                    value_type: qualifier.value_type,
                    value_json: parse_json_field(&qualifier.value_json, "qualifier.value_json")?,
                    value_entity_id: non_empty_string(qualifier.value_entity_id),
                    ordinal: qualifier.ordinal,
                })
            })
            .collect::<Result<Vec<_>, GatewayBackendError>>()?,
        references: req
            .references
            .into_iter()
            .map(|reference| {
                Ok(SemanticStatementReferenceInput {
                    statement_key: reference.statement_key,
                    property_id: reference.property_id,
                    value_type: reference.value_type,
                    value_json: parse_json_field(&reference.value_json, "reference.value_json")?,
                    evidence_id: non_empty_string(reference.evidence_id),
                    source_span: non_empty_string(reference.source_span),
                    ordinal: reference.ordinal,
                })
            })
            .collect::<Result<Vec<_>, GatewayBackendError>>()?,
    })
}

fn parse_json_field(
    raw: &str,
    field_name: &str,
) -> Result<serde_json::Value, GatewayBackendError> {
    let candidate = if raw.trim().is_empty() { "{}" } else { raw };
    serde_json::from_str(candidate).map_err(|err| {
        GatewayBackendError::invalid_argument(format!("invalid JSON for {field_name}: {err}"))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedding_startup_summary_reports_configured_backend_provider() {
        let config = GatewayBackendConfig {
            embedding: EmbeddingConfig {
                enabled: true,
                base_url: Some("http://127.0.0.1:11434/v1".into()),
                api_key: Some("secret".into()),
                model: "qwen3-embedding:8b".into(),
                timeout_ms: 120_000,
                max_chars: 1000,
                strict: true,
            },
        };

        let summary = config.embedding_startup_summary();

        assert!(summary.contains("provider=backend"));
        assert!(summary.contains("enabled=true"));
        assert!(summary.contains("model=qwen3-embedding:8b"));
        assert!(summary.contains("config_source=configured"));
        assert!(summary.contains("strict=true"));
    }

    #[test]
    fn embedding_startup_summary_reports_missing_config() {
        let config = GatewayBackendConfig {
            embedding: EmbeddingConfig {
                enabled: true,
                base_url: None,
                api_key: None,
                model: "qwen3-embedding:8b".into(),
                timeout_ms: 120_000,
                max_chars: 1000,
                strict: false,
            },
        };

        let summary = config.embedding_startup_summary();

        assert!(summary.contains("config_source=missing"));
        assert!(summary.contains("strict=false"));
    }
}
