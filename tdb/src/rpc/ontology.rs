use std::collections::HashMap;

use serde_json::Value;
use sqlx::types::Json;
use sqlx::{postgres::PgRow, PgPool, Row};
use uuid::Uuid;

use crate::persist::ontology_store::OntologyStore;
use crate::rpc::proto::{
    ArchiveOntologyFactRequest, ArchiveOntologyFactResponse, ConceptAliasRecord,
    EventConceptLinkRecord, GetOntologyConceptNeighborsRequest,
    GetOntologyConceptNeighborsResponse, GetOntologyConceptRequest, GetOntologyConceptResponse,
    GetSemanticStatementProvenanceRequest, GetSemanticStatementProvenanceResponse,
    GetSemanticStatementRequest, GetSemanticStatementResponse,
    GetSemanticStatementsByEvidenceRequest, GetSemanticStatementsByEvidenceResponse,
    ListSemanticStatementsRequest, ListSemanticStatementsResponse,
    SetSemanticStatementStatusRequest, SetSemanticStatementStatusResponse,
    SemanticStatementWithQualifiers,
    GetOntologyNormalizedTermRequest, GetOntologyNormalizedTermResponse,
    GetOntologyObjectTypeRequest, GetOntologyObjectTypeResponse, GetOntologyRawTermRequest,
    GetOntologyRawTermResponse, GetOntologyRelationTypeRequest, GetOntologyRelationTypeResponse,
    GetOntologyTermClusterRequest, GetOntologyTermClusterResponse, GetTermMappingRegistryRequest,
    GetTermMappingRegistryResponse, GetTermMappingRuleRequest, GetTermMappingRuleResponse,
    InterpretTermBatchRequest, InterpretTermBatchResponse, InterpretTermRequest,
    InterpretTermResponse, ListConceptAliasesRequest, ListConceptAliasesResponse,
    ListEventConceptLinksRequest, ListEventConceptLinksResponse, ListOntologyClusterMembersRequest,
    ListOntologyClusterMembersResponse, ListOntologyConceptTypeAssignmentsRequest,
    ListOntologyConceptTypeAssignmentsResponse, ListOntologyConceptsRequest,
    ListOntologyConceptsResponse, ListOntologyEdgesRequest, ListOntologyEdgesResponse,
    ListOntologyFactsRequest, ListOntologyFactsResponse, ListOntologyObjectTypesRequest,
    ListOntologyObjectTypesResponse, ListOntologyRawTermCandidatesRequest,
    ListOntologyRawTermCandidatesResponse, ListOntologyRawTermNormalizationsRequest,
    ListOntologyRawTermNormalizationsResponse, ListOntologyRelationCandidatesRequest,
    ListOntologyRelationCandidatesResponse, ListOntologyRelationTypesRequest,
    ListOntologyRelationTypesResponse, ListOntologyTermClustersRequest,
    ListOntologyTermClustersResponse, ListTermMappingRegistriesRequest,
    ListTermMappingRegistriesResponse, ListTermMappingRuleEvidenceRequest,
    ListTermMappingRuleEvidenceResponse, OntologyClusterMemberRecord, OntologyConceptRecord,
    OntologyConceptTypeAssignmentRecord, OntologyEdgeRecord, OntologyFactEvidenceWrite,
    OntologyFactRecord, OntologyNeighborRecord, OntologyNormalizedTermRecord,
    OntologyObjectTypeRecord, OntologyRawTermCandidateRecord, OntologyRawTermNormalizationRecord,
    OntologyRawTermRecord, OntologyRelationCandidateRecord, OntologyRelationTypeRecord,
    OntologyTermClusterRecord, SearchConceptAliasesRequest, SearchConceptAliasesResponse,
    SearchOntologyConceptsRequest, SearchOntologyConceptsResponse, SearchOntologyFactsRequest,
    SearchOntologyFactsResponse, SearchOntologyNormalizedTermsRequest,
    SearchOntologyNormalizedTermsResponse, SearchOntologyRawTermsRequest,
    SearchOntologyRawTermsResponse, SearchTermMappingRulesRequest, SearchTermMappingRulesResponse,
    EvidenceLocatorRecord, EvidenceRecord, SemanticStatementQualifierRecord,
    SemanticStatementRecord, SemanticStatementReferenceRecord,
    TermMappingInterpretationRecord, TermMappingRegistryRecord, TermMappingRuleEvidenceRecord,
    TermMappingRuleRecord, UpsertConceptAliasRequest, UpsertConceptAliasResponse,
    UpsertEventConceptLinkRequest, UpsertEventConceptLinkResponse,
    UpsertOntologyClusterMemberRequest, UpsertOntologyClusterMemberResponse,
    UpsertOntologyConceptRequest, UpsertOntologyConceptResponse,
    UpsertOntologyConceptTypeAssignmentRequest, UpsertOntologyConceptTypeAssignmentResponse,
    UpsertOntologyEdgeRequest, UpsertOntologyEdgeResponse, UpsertOntologyFactWithEvidenceRequest,
    UpsertOntologyFactWithEvidenceResponse, UpsertOntologyNormalizedTermRequest,
    UpsertOntologyNormalizedTermResponse, UpsertOntologyObjectTypeRequest,
    UpsertOntologyObjectTypeResponse, UpsertOntologyRawTermCandidateRequest,
    UpsertOntologyRawTermCandidateResponse, UpsertOntologyRawTermNormalizationRequest,
    UpsertOntologyRawTermNormalizationResponse, UpsertOntologyRawTermRequest,
    UpsertOntologyRawTermResponse, UpsertOntologyRelationCandidateRequest,
    UpsertOntologyRelationCandidateResponse, UpsertOntologyRelationTypeRequest,
    UpsertOntologyRelationTypeResponse, UpsertOntologyTermClusterRequest,
    UpsertOntologyTermClusterResponse, UpsertSemanticBatchResponse,
    UpsertTermMappingRegistryRequest, UpsertTermMappingRegistryResponse,
    UpsertTermMappingRuleEvidenceRequest, UpsertTermMappingRuleEvidenceResponse,
    UpsertTermMappingRuleRequest, UpsertTermMappingRuleResponse,
};
use crate::rpc::stream_filter::stream_scalar_match;

const SEMANTIC_QUALIFIER_PROPERTY_ID: &str = "tdb.qualifier.payload";
const SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID: &str = "tdb.ref.legacy_event";
const SEMANTIC_ACTIVE_FACT_STATUSES: &[&str] = &["extracted", "accepted", "reviewed", "proposed"];

#[derive(Debug, Clone)]
pub struct OntologyRpcStore {
    pool: PgPool,
}

#[derive(Debug, Clone)]
pub struct SemanticEntityUpsertInput {
    pub entity_id: String,
    pub entity_kind: String,
    pub semantic_role: String,
    pub namespace: String,
    pub status: String,
    pub property_datatype: Option<String>,
    pub metadata_json: Value,
}

#[derive(Debug, Clone)]
pub struct SemanticStatementUpsertInput {
    pub statement_key: String,
    pub subject_id: String,
    pub property_id: String,
    pub value_type: String,
    pub value_entity_id: Option<String>,
    pub value_json: Value,
    pub status: String,
    pub confidence: Option<f64>,
    pub created_by: String,
    pub metadata_json: Value,
}

#[derive(Debug, Clone)]
pub struct SemanticStatementQualifierInput {
    pub statement_key: String,
    pub property_id: String,
    pub value_type: String,
    pub value_json: Value,
    pub value_entity_id: Option<String>,
    pub ordinal: i32,
}

#[derive(Debug, Clone)]
pub struct SemanticStatementReferenceInput {
    pub statement_key: String,
    pub property_id: String,
    pub value_type: String,
    pub value_json: Value,
    pub evidence_id: Option<String>,
    pub source_span: Option<String>,
    pub ordinal: i32,
}

#[derive(Debug, Clone, Default)]
pub struct SemanticBatchUpsertInput {
    pub entities: Vec<SemanticEntityUpsertInput>,
    pub statements: Vec<SemanticStatementUpsertInput>,
    pub qualifiers: Vec<SemanticStatementQualifierInput>,
    pub references: Vec<SemanticStatementReferenceInput>,
}

impl OntologyRpcStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_concept(
        &self,
        req: UpsertOntologyConceptRequest,
    ) -> Result<UpsertOntologyConceptResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_concept (concept_id, canonical_name, concept_type, aliases)
            VALUES ($1, $2, $3, $4::jsonb)
            ON CONFLICT (concept_id) DO UPDATE SET
              canonical_name = EXCLUDED.canonical_name,
              concept_type = EXCLUDED.concept_type,
              aliases = EXCLUDED.aliases,
              updated_at = NOW()
            RETURNING concept_id, canonical_name, concept_type, aliases::text AS aliases_json, created_at, updated_at
            "#,
        )
        .bind(&req.concept_id)
        .bind(&req.canonical_name)
        .bind(&req.concept_type)
        .bind(if req.aliases_json.is_empty() { "[]" } else { &req.aliases_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyConceptResponse {
            concept: Some(map_concept_row(&row)),
        })
    }

    pub async fn get_concept(
        &self,
        req: GetOntologyConceptRequest,
    ) -> Result<GetOntologyConceptResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT concept_id, canonical_name, concept_type, aliases::text AS aliases_json, created_at, updated_at
            FROM ontology_concept
            WHERE concept_id = $1
            "#,
        )
        .bind(&req.concept_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyConceptResponse {
            concept: row.as_ref().map(map_concept_row),
        })
    }

    pub async fn upsert_semantic_batch(
        &self,
        batch: SemanticBatchUpsertInput,
    ) -> Result<UpsertSemanticBatchResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        let mut statement_ids = HashMap::new();

        for entity in &batch.entities {
            upsert_semantic_entity_record(&mut tx, entity).await?;
        }

        for statement in &batch.statements {
            let statement_id = upsert_semantic_statement_record(&mut tx, statement).await?;
            statement_ids.insert(statement.statement_key.clone(), statement_id);
            sqlx::query("DELETE FROM statement_qualifier WHERE statement_id = $1")
                .bind(statement_id)
                .execute(&mut *tx)
                .await?;
            sqlx::query("DELETE FROM statement_reference WHERE statement_id = $1")
                .bind(statement_id)
                .execute(&mut *tx)
                .await?;
        }

        for qualifier in &batch.qualifiers {
            let Some(statement_id) = statement_ids.get(&qualifier.statement_key) else {
                continue;
            };
            sqlx::query(
                r#"
                INSERT INTO statement_qualifier (
                  statement_id, property_id, value_type, value_entity_id, value_json, ordinal
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                "#,
            )
            .bind(*statement_id)
            .bind(&qualifier.property_id)
            .bind(&qualifier.value_type)
            .bind(&qualifier.value_entity_id)
            .bind(Json(qualifier.value_json.clone()))
            .bind(qualifier.ordinal)
            .execute(&mut *tx)
            .await?;
        }

        for reference in &batch.references {
            let Some(statement_id) = statement_ids.get(&reference.statement_key) else {
                continue;
            };
            let evidence_uuid = reference
                .evidence_id
                .as_deref()
                .and_then(|value| Uuid::parse_str(value).ok());
            sqlx::query(
                r#"
                INSERT INTO statement_reference (
                  reference_claim_id, reference_id, statement_id, property_id,
                  value_type, value_json, evidence_id, source_span, ordinal
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                "#,
            )
            .bind(semantic_reference_claim_uuid(&reference.statement_key, reference.ordinal))
            .bind(semantic_reference_uuid(&reference.statement_key, reference.ordinal))
            .bind(*statement_id)
            .bind(&reference.property_id)
            .bind(&reference.value_type)
            .bind(Json(reference.value_json.clone()))
            .bind(evidence_uuid)
            .bind(&reference.source_span)
            .bind(reference.ordinal)
            .execute(&mut *tx)
            .await?;
        }

        tx.commit().await?;
        Ok(UpsertSemanticBatchResponse {
            semantic_entity_count: i32::try_from(batch.entities.len()).unwrap_or(i32::MAX),
            semantic_statement_count: i32::try_from(batch.statements.len()).unwrap_or(i32::MAX),
            statement_qualifier_count: i32::try_from(batch.qualifiers.len()).unwrap_or(i32::MAX),
            statement_reference_count: i32::try_from(batch.references.len()).unwrap_or(i32::MAX),
        })
    }

    pub async fn get_statement(
        &self,
        req: GetSemanticStatementRequest,
    ) -> Result<GetSemanticStatementResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT
              ss.statement_id::text AS statement_id,
              ss.subject_id AS subject_concept_id,
              COALESCE(sc.canonical_name, '') AS subject_name,
              ss.property_id AS predicate,
              COALESCE(ss.value_entity_id, '') AS object_concept_id,
              COALESCE(dc.canonical_name, '') AS object_name,
              ss.value_type,
              ss.value_json::text AS value_json,
              COALESCE(ss.confidence, 0.0) AS confidence,
              ss.status,
              COALESCE(ss.created_by, '') AS created_by,
              ss.metadata_json::text AS metadata_json,
              '{}'::text AS provenance_json,
              ss.created_at,
              ss.updated_at
            FROM semantic_statement ss
            LEFT JOIN ontology_concept sc ON sc.concept_id = ss.subject_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = ss.value_entity_id
            WHERE ss.statement_id = $1::uuid
            "#,
        )
        .bind(&req.statement_id)
        .fetch_optional(&self.pool)
        .await?;

        let qualifiers = sqlx::query(
            r#"
            SELECT
              statement_id::text AS statement_id,
              property_id,
              value_type,
              COALESCE(value_entity_id, '') AS value_entity_id,
              value_json::text AS value_json,
              ordinal
            FROM statement_qualifier
            WHERE statement_id = $1::uuid
            ORDER BY ordinal ASC, property_id ASC
            "#,
        )
        .bind(&req.statement_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(GetSemanticStatementResponse {
            statement: row.as_ref().map(map_semantic_statement_row),
            qualifiers: qualifiers
                .iter()
                .map(map_semantic_statement_qualifier_row)
                .collect(),
        })
    }

    pub async fn list_statements(
        &self,
        req: ListSemanticStatementsRequest,
    ) -> Result<ListSemanticStatementsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT
              ss.statement_id::text AS statement_id,
              ss.subject_id AS subject_concept_id,
              COALESCE(sc.canonical_name, '') AS subject_name,
              ss.property_id AS predicate,
              COALESCE(ss.value_entity_id, '') AS object_concept_id,
              COALESCE(dc.canonical_name, '') AS object_name,
              ss.value_type,
              ss.value_json::text AS value_json,
              COALESCE(ss.confidence, 0.0) AS confidence,
              ss.status,
              COALESCE(ss.created_by, '') AS created_by,
              ss.metadata_json::text AS metadata_json,
              '{}'::text AS provenance_json,
              ss.created_at,
              ss.updated_at
            FROM semantic_statement ss
            LEFT JOIN ontology_concept sc ON sc.concept_id = ss.subject_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = ss.value_entity_id
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.subject_id.is_empty() {
            query.push_str(&format!(" AND ss.subject_id = ${}", binds.len() + 1));
            binds.push(req.subject_id);
        }
        if !req.property_id.is_empty() {
            query.push_str(&format!(" AND ss.property_id = ${}", binds.len() + 1));
            binds.push(req.property_id);
        }
        if !req.value_entity_id.is_empty() {
            query.push_str(&format!(" AND ss.value_entity_id = ${}", binds.len() + 1));
            binds.push(req.value_entity_id);
        }
        // Unlike the legacy fact API, retired statements are excluded by
        // default: callers listing a subject want its current claims, not its
        // history. Pass status='all' to see everything.
        //
        // The retired states are exactly 'rejected' and 'deprecated' — see the
        // CHECK on semantic_statement.status, whose full domain is
        // proposed|extracted|reviewed|accepted|deprecated|rejected. There is no
        // 'retracted' state, so filtering on that name would silently match
        // every row and quietly disable this default.
        if req.status == "all" {
            // no filter
        } else if !req.status.is_empty() {
            query.push_str(&format!(" AND ss.status = ${}", binds.len() + 1));
            binds.push(req.status);
        } else {
            query.push_str(" AND ss.status NOT IN ('rejected', 'deprecated')");
        }
        query.push_str(" ORDER BY ss.updated_at DESC, ss.statement_id ASC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);
        let rows = sql_query.fetch_all(&self.pool).await?;

        let statement_ids: Vec<String> = rows
            .iter()
            .map(|row| row.get::<String, _>("statement_id"))
            .collect();

        // One query for every qualifier in the page, then group in memory —
        // querying per statement would be N+1 on a subject with many claims.
        let mut qualifiers_by_statement: HashMap<String, Vec<SemanticStatementQualifierRecord>> =
            HashMap::new();
        if !statement_ids.is_empty() {
            let qualifier_rows = sqlx::query(
                r#"
                SELECT
                  statement_id::text AS statement_id,
                  property_id,
                  value_type,
                  COALESCE(value_entity_id, '') AS value_entity_id,
                  value_json::text AS value_json,
                  ordinal
                FROM statement_qualifier
                WHERE statement_id = ANY($1::uuid[])
                ORDER BY statement_id ASC, ordinal ASC, property_id ASC
                "#,
            )
            .bind(&statement_ids)
            .fetch_all(&self.pool)
            .await?;
            for row in &qualifier_rows {
                let record = map_semantic_statement_qualifier_row(row);
                qualifiers_by_statement
                    .entry(record.statement_id.clone())
                    .or_default()
                    .push(record);
            }
        }

        Ok(ListSemanticStatementsResponse {
            statements: rows
                .iter()
                .map(|row| {
                    let statement = map_semantic_statement_row(row);
                    let qualifiers = qualifiers_by_statement
                        .get(&statement.statement_id)
                        .cloned()
                        .unwrap_or_default();
                    SemanticStatementWithQualifiers {
                        statement: Some(statement),
                        qualifiers,
                    }
                })
                .collect(),
        })
    }

    pub async fn set_statement_status(
        &self,
        req: SetSemanticStatementStatusRequest,
    ) -> Result<SetSemanticStatementStatusResponse, sqlx::Error> {
        // upsert-batch addresses statements by statement_key, so it can only
        // reach rows whose key is known. Statements dual-written from
        // ontology_fact get a random statement_id and carry no key at all,
        // leaving no way to retire them. This closes that gap by addressing a
        // statement directly by id.
        const ALLOWED: [&str; 6] = [
            "proposed", "extracted", "reviewed", "accepted", "deprecated", "rejected",
        ];
        if !ALLOWED.contains(&req.status.as_str()) {
            // Surface a clear error instead of letting the table CHECK turn
            // into an opaque 500.
            return Err(sqlx::Error::Protocol(format!(
                "invalid statement status {:?}; expected one of {}",
                req.status,
                ALLOWED.join(", ")
            )));
        }

        let updated = sqlx::query(
            r#"
            UPDATE semantic_statement
            SET status = $2,
                metadata_json = metadata_json
                  || jsonb_build_object('status_note', $3::text)
                  || jsonb_build_object('status_changed_at', NOW()::text),
                updated_at = NOW()
            WHERE statement_id = $1::uuid
            "#,
        )
        .bind(&req.statement_id)
        .bind(&req.status)
        .bind(&req.note)
        .execute(&self.pool)
        .await?
        .rows_affected();

        Ok(SetSemanticStatementStatusResponse {
            updated_rows: updated as i32,
        })
    }

    pub async fn get_statement_provenance(
        &self,
        req: GetSemanticStatementProvenanceRequest,
    ) -> Result<GetSemanticStatementProvenanceResponse, sqlx::Error> {
        let limit = if req.evidence_limit > 0 {
            req.evidence_limit
        } else {
            50
        };
        let reference_rows = sqlx::query(
            r#"
            SELECT
              statement_id::text AS statement_id,
              property_id,
              value_type,
              value_json::text AS value_json,
              COALESCE(evidence_id::text, '') AS evidence_id,
              COALESCE(source_span, '') AS source_span,
              ordinal
            FROM statement_reference
            WHERE statement_id = $1::uuid
            ORDER BY ordinal ASC, property_id ASC
            LIMIT $2
            "#,
        )
        .bind(&req.statement_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await?;

        let evidence_ids = collect_reference_evidence_ids(&reference_rows);

        let evidence_map = load_evidence_map(&self.pool, &evidence_ids).await?;
        let locator_map = if req.include_locators {
            load_evidence_locator_map(&self.pool, &evidence_ids).await?
        } else {
            HashMap::new()
        };

        Ok(GetSemanticStatementProvenanceResponse {
            references: reference_rows
                .iter()
                .map(|row| {
                    map_semantic_statement_reference_row(
                        row,
                        &evidence_map,
                        &locator_map,
                    )
                })
                .collect(),
        })
    }

    pub async fn get_statements_by_evidence(
        &self,
        req: GetSemanticStatementsByEvidenceRequest,
    ) -> Result<GetSemanticStatementsByEvidenceResponse, sqlx::Error> {
        let limit = if req.limit > 0 { req.limit } else { 50 };
        let reference_rows = sqlx::query(
            r#"
            SELECT
              statement_id::text AS statement_id,
              property_id,
              value_type,
              value_json::text AS value_json,
              COALESCE(evidence_id::text, '') AS evidence_id,
              COALESCE(source_span, '') AS source_span,
              ordinal
            FROM statement_reference
            WHERE evidence_id = $1::uuid
            ORDER BY created_at DESC, ordinal ASC
            LIMIT $2
            "#,
        )
        .bind(&req.evidence_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await?;

        let evidence_ids = collect_reference_evidence_ids(&reference_rows);
        let evidence_map = load_evidence_map(&self.pool, &evidence_ids).await?;
        let locator_map = if req.include_locators {
            load_evidence_locator_map(&self.pool, &evidence_ids).await?
        } else {
            HashMap::new()
        };

        Ok(GetSemanticStatementsByEvidenceResponse {
            references: reference_rows
                .iter()
                .map(|row| map_semantic_statement_reference_row(row, &evidence_map, &locator_map))
                .collect(),
        })
    }

    pub async fn list_concepts(
        &self,
        req: ListOntologyConceptsRequest,
    ) -> Result<ListOntologyConceptsResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT concept_id, canonical_name, concept_type, aliases::text AS aliases_json, created_at, updated_at FROM ontology_concept WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();

        if !req.concept_type.is_empty() {
            query.push_str(&format!(" AND concept_type = ${}", binds.len() + 1));
            binds.push(req.concept_type);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (canonical_name ILIKE ${idx} OR concept_id ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyConceptsResponse {
            concepts: rows.iter().map(map_concept_row).collect(),
        })
    }

    pub async fn upsert_concept_alias(
        &self,
        req: UpsertConceptAliasRequest,
    ) -> Result<UpsertConceptAliasResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO concept_alias (concept_id, alias_text, confidence, extractor)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (concept_id, alias_text) DO UPDATE SET
              confidence = GREATEST(concept_alias.confidence, EXCLUDED.confidence),
              extractor = EXCLUDED.extractor,
              updated_at = NOW()
            RETURNING concept_id, alias_text, confidence, extractor, created_at, updated_at
            "#,
        )
        .bind(&req.concept_id)
        .bind(&req.alias_text)
        .bind(req.confidence)
        .bind(&req.extractor)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertConceptAliasResponse {
            alias: Some(map_alias_row(&row)),
        })
    }

    pub async fn list_concept_aliases(
        &self,
        req: ListConceptAliasesRequest,
    ) -> Result<ListConceptAliasesResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT concept_id, alias_text, confidence, extractor, created_at, updated_at FROM concept_alias WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.concept_id.is_empty() {
            query.push_str(&format!(" AND concept_id = ${}", binds.len() + 1));
            binds.push(req.concept_id);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND alias_text ILIKE ${idx}"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListConceptAliasesResponse {
            aliases: rows.iter().map(map_alias_row).collect(),
        })
    }

    pub async fn upsert_edge(
        &self,
        req: UpsertOntologyEdgeRequest,
    ) -> Result<UpsertOntologyEdgeResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_edge (src_concept_id, predicate, dst_concept_id, weight)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (src_concept_id, predicate, dst_concept_id) DO UPDATE SET
              weight = GREATEST(ontology_edge.weight, EXCLUDED.weight)
            RETURNING src_concept_id, predicate, dst_concept_id, weight, created_at
            "#,
        )
        .bind(&req.src_concept_id)
        .bind(&req.predicate)
        .bind(&req.dst_concept_id)
        .bind(req.weight)
        .fetch_one(&mut *tx)
        .await?;

        ensure_semantic_item_entity_from_ontology_concept(&mut tx, &req.src_concept_id).await?;
        ensure_semantic_item_entity_from_ontology_concept(&mut tx, &req.dst_concept_id).await?;
        ensure_semantic_property_entity_from_relation_type(&mut tx, &req.predicate).await?;
        upsert_semantic_statement_for_edge(
            &mut tx,
            &req.src_concept_id,
            &req.predicate,
            &req.dst_concept_id,
            req.weight,
        )
        .await?;
        tx.commit().await?;
        Ok(UpsertOntologyEdgeResponse {
            edge: Some(map_edge_row(&row)),
        })
    }

    pub async fn list_edges(
        &self,
        req: ListOntologyEdgesRequest,
    ) -> Result<ListOntologyEdgesResponse, sqlx::Error> {
        let semantic_rows = self.list_edges_from_semantic_statements(&req).await?;
        if !semantic_rows.is_empty() {
            return Ok(ListOntologyEdgesResponse {
                edges: semantic_rows.iter().map(map_edge_row).collect(),
            });
        }

        let mut query = String::from(
            "SELECT src_concept_id, predicate, dst_concept_id, weight, created_at FROM ontology_edge WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.src_concept_id.is_empty() {
            query.push_str(&format!(" AND src_concept_id = ${}", binds.len() + 1));
            binds.push(req.src_concept_id);
        }
        if !req.predicate.is_empty() {
            query.push_str(&format!(" AND predicate = ${}", binds.len() + 1));
            binds.push(req.predicate);
        }
        if !req.dst_concept_id.is_empty() {
            query.push_str(&format!(" AND dst_concept_id = ${}", binds.len() + 1));
            binds.push(req.dst_concept_id);
        }
        query.push_str(" ORDER BY created_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });

        let rows = sql_query.fetch_all(&self.pool).await?;
        self.backfill_semantic_projection_for_legacy_edges(&rows).await?;
        Ok(ListOntologyEdgesResponse {
            edges: rows.iter().map(map_edge_row).collect(),
        })
    }

    async fn list_edges_from_semantic_statements(
        &self,
        req: &ListOntologyEdgesRequest,
    ) -> Result<Vec<PgRow>, sqlx::Error> {
        let (query, binds, limit) = build_semantic_edge_projection_query(req);
        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(limit);
        sql_query.fetch_all(&self.pool).await
    }

    pub async fn upsert_event_concept_link(
        &self,
        req: UpsertEventConceptLinkRequest,
    ) -> Result<UpsertEventConceptLinkResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO event_concept_link (
              stream_id, event_id, concept_id, role, confidence,
              asset_id, version_number, extractor, source_span, evidence_json
            )
            VALUES ($1, $2, $3, $4, $5, $6, NULLIF($7, 0), $8, NULLIF($9, ''), $10::jsonb)
            ON CONFLICT (stream_id, event_id, concept_id, role) DO UPDATE SET
              confidence = GREATEST(event_concept_link.confidence, EXCLUDED.confidence),
              asset_id = COALESCE(EXCLUDED.asset_id, event_concept_link.asset_id),
              version_number = COALESCE(EXCLUDED.version_number, event_concept_link.version_number),
              extractor = EXCLUDED.extractor,
              source_span = COALESCE(EXCLUDED.source_span, event_concept_link.source_span),
              evidence_json = CASE
                WHEN event_concept_link.evidence_json = '{}'::jsonb THEN EXCLUDED.evidence_json
                ELSE event_concept_link.evidence_json
              END,
              updated_at = NOW()
            RETURNING stream_id, event_id, concept_id, role, confidence, COALESCE(asset_id, '') AS asset_id,
                      COALESCE(version_number, 0) AS version_number, extractor, COALESCE(source_span, '') AS source_span,
                      evidence_json::text AS evidence_json, created_at, updated_at
            "#,
        )
        .bind(&req.stream_id)
        .bind(&req.event_id)
        .bind(&req.concept_id)
        .bind(&req.role)
        .bind(req.confidence)
        .bind(if req.asset_id.is_empty() { None } else { Some(req.asset_id.as_str()) })
        .bind(req.version_number)
        .bind(&req.extractor)
        .bind(&req.source_span)
        .bind(if req.evidence_json.is_empty() { "{}" } else { &req.evidence_json })
        .fetch_one(&self.pool)
        .await?;
        Ok(UpsertEventConceptLinkResponse {
            link: Some(map_event_link_row(&row)),
        })
    }

    pub async fn list_event_concept_links(
        &self,
        req: ListEventConceptLinksRequest,
    ) -> Result<ListEventConceptLinksResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT stream_id, event_id, concept_id, role, confidence, COALESCE(asset_id, '') AS asset_id, COALESCE(version_number, 0) AS version_number, extractor, COALESCE(source_span, '') AS source_span, evidence_json::text AS evidence_json, created_at, updated_at FROM event_concept_link WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.stream_id.is_empty() {
            query.push_str(&format!(" AND stream_id = ${}", binds.len() + 1));
            binds.push(req.stream_id);
        }
        if !req.event_id.is_empty() {
            query.push_str(&format!(" AND event_id = ${}", binds.len() + 1));
            binds.push(req.event_id);
        }
        if !req.concept_id.is_empty() {
            query.push_str(&format!(" AND concept_id = ${}", binds.len() + 1));
            binds.push(req.concept_id);
        }
        if !req.role.is_empty() {
            query.push_str(&format!(" AND role = ${}", binds.len() + 1));
            binds.push(req.role);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListEventConceptLinksResponse {
            links: rows.iter().map(map_event_link_row).collect(),
        })
    }

    pub async fn upsert_object_type(
        &self,
        req: UpsertOntologyObjectTypeRequest,
    ) -> Result<UpsertOntologyObjectTypeResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_object_type (type_id, display_name, description, enabled)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (type_id) DO UPDATE SET
              display_name = EXCLUDED.display_name,
              description = EXCLUDED.description,
              enabled = EXCLUDED.enabled,
              updated_at = NOW()
            RETURNING type_id, display_name, description, enabled, created_at, updated_at
            "#,
        )
        .bind(&req.type_id)
        .bind(&req.display_name)
        .bind(&req.description)
        .bind(req.enabled)
        .fetch_one(&self.pool)
        .await?;
        Ok(UpsertOntologyObjectTypeResponse {
            object_type: Some(map_object_type_row(&row)),
        })
    }

    pub async fn get_object_type(
        &self,
        req: GetOntologyObjectTypeRequest,
    ) -> Result<GetOntologyObjectTypeResponse, sqlx::Error> {
        let row = sqlx::query(
            "SELECT type_id, display_name, description, enabled, created_at, updated_at FROM ontology_object_type WHERE type_id = $1",
        )
        .bind(&req.type_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(GetOntologyObjectTypeResponse {
            object_type: row.as_ref().map(map_object_type_row),
        })
    }

    pub async fn list_object_types(
        &self,
        req: ListOntologyObjectTypesRequest,
    ) -> Result<ListOntologyObjectTypesResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT type_id, display_name, description, enabled, created_at, updated_at FROM ontology_object_type WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if req.enabled_only {
            query.push_str(" AND enabled = true");
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (type_id ILIKE ${idx} OR display_name ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyObjectTypesResponse {
            object_types: rows.iter().map(map_object_type_row).collect(),
        })
    }

    pub async fn upsert_concept_type_assignment(
        &self,
        req: UpsertOntologyConceptTypeAssignmentRequest,
    ) -> Result<UpsertOntologyConceptTypeAssignmentResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            WITH existing AS (
              SELECT assignment_id
              FROM ontology_concept_type_assignment
              WHERE (
                NULLIF($1, '')::uuid IS NOT NULL
                AND assignment_id = NULLIF($1, '')::uuid
              ) OR (
                domain = $2
                AND concept_id = $3
                AND object_type_id = $4
              )
              ORDER BY assignment_id
              LIMIT 1
            )
            INSERT INTO ontology_concept_type_assignment (
              assignment_id, domain, concept_id, object_type_id,
              assignment_status, source_kind, confidence, metadata_json
            )
            VALUES (
              COALESCE((SELECT assignment_id FROM existing), NULLIF($1, '')::uuid, gen_random_uuid()),
              $2, $3, $4, $5, $6, NULLIF($7, 0), $8::jsonb
            )
            ON CONFLICT (assignment_id) DO UPDATE SET
              domain = EXCLUDED.domain,
              concept_id = EXCLUDED.concept_id,
              object_type_id = EXCLUDED.object_type_id,
              assignment_status = EXCLUDED.assignment_status,
              source_kind = EXCLUDED.source_kind,
              confidence = EXCLUDED.confidence,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING assignment_id::text AS assignment_id, domain, concept_id, object_type_id,
                      assignment_status, source_kind, COALESCE(confidence, 0) AS confidence,
                      metadata_json::text AS metadata_json, created_at, updated_at
            "#,
        )
        .bind(&req.assignment_id)
        .bind(&req.domain)
        .bind(&req.concept_id)
        .bind(&req.object_type_id)
        .bind(if req.assignment_status.is_empty() { "auto" } else { &req.assignment_status })
        .bind(&req.source_kind)
        .bind(req.confidence)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyConceptTypeAssignmentResponse {
            assignment: Some(map_ontology_concept_type_assignment_row(&row)),
        })
    }

    pub async fn list_concept_type_assignments(
        &self,
        req: ListOntologyConceptTypeAssignmentsRequest,
    ) -> Result<ListOntologyConceptTypeAssignmentsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT assignment_id::text AS assignment_id, domain, concept_id, object_type_id,
                   assignment_status, source_kind, COALESCE(confidence, 0) AS confidence,
                   metadata_json::text AS metadata_json, created_at, updated_at
            FROM ontology_concept_type_assignment
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.concept_id.is_empty() {
            query.push_str(&format!(" AND concept_id = ${}", binds.len() + 1));
            binds.push(req.concept_id);
        }
        if !req.object_type_id.is_empty() {
            query.push_str(&format!(" AND object_type_id = ${}", binds.len() + 1));
            binds.push(req.object_type_id);
        }
        if !req.assignment_status.is_empty() {
            query.push_str(&format!(" AND assignment_status = ${}", binds.len() + 1));
            binds.push(req.assignment_status);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyConceptTypeAssignmentsResponse {
            assignments: rows
                .iter()
                .map(map_ontology_concept_type_assignment_row)
                .collect(),
        })
    }

    pub async fn upsert_relation_type(
        &self,
        req: UpsertOntologyRelationTypeRequest,
    ) -> Result<UpsertOntologyRelationTypeResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_relation_type (
              predicate, src_type_id, dst_type_id, display_name, description, is_symmetric, is_transitive, enabled
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (predicate) DO UPDATE SET
              src_type_id = EXCLUDED.src_type_id,
              dst_type_id = EXCLUDED.dst_type_id,
              display_name = EXCLUDED.display_name,
              description = EXCLUDED.description,
              is_symmetric = EXCLUDED.is_symmetric,
              is_transitive = EXCLUDED.is_transitive,
              enabled = EXCLUDED.enabled,
              updated_at = NOW()
            RETURNING predicate, src_type_id, dst_type_id, display_name, description, is_symmetric, is_transitive, enabled, created_at, updated_at
            "#,
        )
        .bind(&req.predicate)
        .bind(&req.src_type_id)
        .bind(&req.dst_type_id)
        .bind(&req.display_name)
        .bind(&req.description)
        .bind(req.is_symmetric)
        .bind(req.is_transitive)
        .bind(req.enabled)
        .fetch_one(&self.pool)
        .await?;
        Ok(UpsertOntologyRelationTypeResponse {
            relation_type: Some(map_relation_type_row(&row)),
        })
    }

    pub async fn get_relation_type(
        &self,
        req: GetOntologyRelationTypeRequest,
    ) -> Result<GetOntologyRelationTypeResponse, sqlx::Error> {
        let row = sqlx::query(
            "SELECT predicate, src_type_id, dst_type_id, display_name, description, is_symmetric, is_transitive, enabled, created_at, updated_at FROM ontology_relation_type WHERE predicate = $1",
        )
        .bind(&req.predicate)
        .fetch_optional(&self.pool)
        .await?;
        Ok(GetOntologyRelationTypeResponse {
            relation_type: row.as_ref().map(map_relation_type_row),
        })
    }

    pub async fn list_relation_types(
        &self,
        req: ListOntologyRelationTypesRequest,
    ) -> Result<ListOntologyRelationTypesResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT predicate, src_type_id, dst_type_id, display_name, description, is_symmetric, is_transitive, enabled, created_at, updated_at FROM ontology_relation_type WHERE 1=1",
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.src_type_id.is_empty() {
            query.push_str(&format!(" AND src_type_id = ${}", binds.len() + 1));
            binds.push(req.src_type_id);
        }
        if !req.dst_type_id.is_empty() {
            query.push_str(&format!(" AND dst_type_id = ${}", binds.len() + 1));
            binds.push(req.dst_type_id);
        }
        if req.enabled_only {
            query.push_str(" AND enabled = true");
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (predicate ILIKE ${idx} OR display_name ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyRelationTypesResponse {
            relation_types: rows.iter().map(map_relation_type_row).collect(),
        })
    }

    pub async fn list_facts(
        &self,
        req: ListOntologyFactsRequest,
    ) -> Result<ListOntologyFactsResponse, sqlx::Error> {
        let semantic_rows = self.list_facts_from_semantic_statements(&req).await?;
        if !semantic_rows.is_empty() {
            return Ok(ListOntologyFactsResponse {
                facts: semantic_rows.iter().map(map_fact_row).collect(),
            });
        }

        let mut query = String::from(
            r#"
            SELECT f.fact_id, f.src_concept_id, f.predicate, f.dst_concept_id,
                   f.qualifier_json::text AS qualifier_json, f.confidence, f.extractor, f.status,
                   f.review_note, COALESCE(f.valid_from::text, '') AS valid_from, COALESCE(f.valid_to::text, '') AS valid_to,
                   f.created_at, f.updated_at,
                   COALESCE(sc.canonical_name, '') AS src_concept_label,
                   COALESCE(dc.canonical_name, '') AS dst_concept_label
            FROM ontology_fact f
            LEFT JOIN ontology_concept sc ON sc.concept_id = f.src_concept_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.status.is_empty() && req.status != "all" {
            query.push_str(&format!(" AND f.status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.predicate.is_empty() {
            query.push_str(&format!(" AND f.predicate = ${}", binds.len() + 1));
            binds.push(req.predicate);
        }
        if !req.extractor.is_empty() {
            query.push_str(&format!(" AND f.extractor = ${}", binds.len() + 1));
            binds.push(req.extractor);
        }
        if !req.stream_id.is_empty() {
            query.push_str(&format!(
                " AND EXISTS (SELECT 1 FROM ontology_fact_evidence fe WHERE fe.fact_id = f.fact_id AND {})",
                stream_scalar_match("fe.stream_id", binds.len() + 1, req.stream_prefix)
            ));
            binds.push(req.stream_id);
        }
        if !req.src_concept_id.is_empty() {
            query.push_str(&format!(" AND f.src_concept_id = ${}", binds.len() + 1));
            binds.push(req.src_concept_id);
        }
        if !req.dst_concept_id.is_empty() {
            query.push_str(&format!(" AND f.dst_concept_id = ${}", binds.len() + 1));
            binds.push(req.dst_concept_id);
        }
        query.push_str(" ORDER BY f.confidence DESC, f.updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);
        let rows = sql_query.fetch_all(&self.pool).await?;
        self.backfill_semantic_kernel_for_legacy_rows(&rows).await?;
        let statement_id_map = self
            .load_statement_ids_by_legacy_fact_rows(&rows)
            .await?;
        Ok(ListOntologyFactsResponse {
            facts: rows
                .iter()
                .map(|row| map_fact_row_with_statement_id(row, statement_id_map.get(&row.get::<i64, _>("fact_id")).cloned()))
                .collect(),
        })
    }

    async fn list_facts_from_semantic_statements(
        &self,
        req: &ListOntologyFactsRequest,
    ) -> Result<Vec<PgRow>, sqlx::Error> {
        let (query, binds, limit, offset) =
            build_semantic_fact_projection_query(&SemanticFactQueryOptions {
            status: &req.status,
            stream_id: &req.stream_id,
            stream_prefix: req.stream_prefix,
            predicate: &req.predicate,
            extractor: &req.extractor,
            src_concept_id: &req.src_concept_id,
            dst_concept_id: &req.dst_concept_id,
            query: "",
            limit: req.limit,
            offset: req.offset,
        });
        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(limit);
        sql_query = sql_query.bind(offset);
        sql_query.fetch_all(&self.pool).await
    }

    pub async fn upsert_fact_with_evidence(
        &self,
        req: UpsertOntologyFactWithEvidenceRequest,
    ) -> Result<UpsertOntologyFactWithEvidenceResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        let qualifier_json = if req.qualifier_json.is_empty() {
            "{}"
        } else {
            &req.qualifier_json
        };
        let existing = sqlx::query(
            r#"
            SELECT fact_id
            FROM ontology_fact
            WHERE src_concept_id = $1
              AND predicate = $2
              AND dst_concept_id = $3
              AND qualifier_json = $4::jsonb
              AND extractor = $5
            ORDER BY fact_id DESC
            LIMIT 1
            "#,
        )
        .bind(&req.src_concept_id)
        .bind(&req.predicate)
        .bind(&req.dst_concept_id)
        .bind(qualifier_json)
        .bind(&req.extractor)
        .fetch_optional(&mut *tx)
        .await?;

        let fact_id: i64 = if let Some(row) = existing {
            let id: i64 = row.try_get("fact_id")?;
            sqlx::query(
                r#"
                UPDATE ontology_fact
                SET confidence = GREATEST(confidence, $2),
                    status = $3,
                    review_note = CASE WHEN TRIM($4) = '' THEN review_note ELSE TRIM($4) END,
                    valid_from = CASE WHEN TRIM($5) = '' THEN valid_from ELSE $5::timestamptz END,
                    valid_to = CASE WHEN TRIM($6) = '' THEN valid_to ELSE $6::timestamptz END,
                    updated_at = NOW()
                WHERE fact_id = $1
                "#,
            )
            .bind(id)
            .bind(req.confidence)
            .bind(&req.status)
            .bind(&req.review_note)
            .bind(&req.valid_from)
            .bind(&req.valid_to)
            .execute(&mut *tx)
            .await?;
            id
        } else {
            let row = sqlx::query(
                r#"
                INSERT INTO ontology_fact (
                  src_concept_id, predicate, dst_concept_id, qualifier_json,
                  confidence, extractor, status, review_note, valid_from, valid_to
                )
                VALUES (
                  $1, $2, $3, $4::jsonb, $5, $6, $7, $8,
                  NULLIF(TRIM($9), '')::timestamptz,
                  NULLIF(TRIM($10), '')::timestamptz
                )
                RETURNING fact_id
                "#,
            )
            .bind(&req.src_concept_id)
            .bind(&req.predicate)
            .bind(&req.dst_concept_id)
            .bind(qualifier_json)
            .bind(req.confidence)
            .bind(&req.extractor)
            .bind(&req.status)
            .bind(&req.review_note)
            .bind(&req.valid_from)
            .bind(&req.valid_to)
            .fetch_one(&mut *tx)
            .await?;
            row.try_get("fact_id")?
        };

        for evidence in &req.evidence {
            self.insert_fact_evidence(&mut tx, fact_id, evidence)
                .await?;
        }

        let row = sqlx::query(
            r#"
            SELECT f.fact_id, f.src_concept_id, f.predicate, f.dst_concept_id,
                   f.qualifier_json::text AS qualifier_json, f.confidence, f.extractor, f.status,
                   f.review_note, COALESCE(f.valid_from::text, '') AS valid_from, COALESCE(f.valid_to::text, '') AS valid_to,
                   f.created_at, f.updated_at,
                   COALESCE(sc.canonical_name, '') AS src_concept_label,
                   COALESCE(dc.canonical_name, '') AS dst_concept_label
            FROM ontology_fact f
            LEFT JOIN ontology_concept sc ON sc.concept_id = f.src_concept_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
            WHERE f.fact_id = $1
            "#,
        )
        .bind(fact_id)
        .fetch_one(&mut *tx)
        .await?;

        tx.commit().await?;
        Ok(UpsertOntologyFactWithEvidenceResponse {
            fact: Some(map_fact_row(&row)),
            evidence_count: req.evidence.len() as i32,
        })
    }

    pub async fn search_concepts(
        &self,
        req: SearchOntologyConceptsRequest,
    ) -> Result<SearchOntologyConceptsResponse, sqlx::Error> {
        if req.domain.is_empty() {
            return self
                .list_concepts(ListOntologyConceptsRequest {
                    concept_type: req.concept_type,
                    query: req.query,
                    limit: req.limit,
                    offset: req.offset,
                })
                .await
                .map(|res| SearchOntologyConceptsResponse {
                    concepts: res.concepts,
                });
        }

        let mut query = String::from(
            r#"SELECT DISTINCT c.concept_id, c.canonical_name, c.concept_type,
                      c.aliases::text AS aliases_json, c.created_at, c.updated_at
               FROM ontology_concept c
               JOIN ontology_concept_type_assignment cta ON cta.concept_id = c.concept_id
               WHERE cta.domain = $1"#,
        );
        let mut binds: Vec<String> = vec![req.domain];

        if !req.concept_type.is_empty() {
            query.push_str(&format!(" AND c.concept_type = ${}", binds.len() + 1));
            binds.push(req.concept_type);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (c.canonical_name ILIKE ${idx} OR c.concept_id ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY c.updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(SearchOntologyConceptsResponse {
            concepts: rows.iter().map(map_concept_row).collect(),
        })
    }

    pub async fn search_aliases(
        &self,
        req: SearchConceptAliasesRequest,
    ) -> Result<SearchConceptAliasesResponse, sqlx::Error> {
        self.list_concept_aliases(ListConceptAliasesRequest {
            concept_id: req.concept_id,
            query: req.query,
            limit: req.limit,
            offset: req.offset,
        })
        .await
        .map(|res| SearchConceptAliasesResponse {
            aliases: res.aliases,
        })
    }

    pub async fn search_facts(
        &self,
        req: SearchOntologyFactsRequest,
    ) -> Result<SearchOntologyFactsResponse, sqlx::Error> {
        let semantic_rows = self.search_facts_from_semantic_statements(&req).await?;
        if !semantic_rows.is_empty() {
            return Ok(SearchOntologyFactsResponse {
                facts: semantic_rows.iter().map(map_fact_row).collect(),
            });
        }

        let mut query = String::from(
            r#"
            SELECT f.fact_id, f.src_concept_id, f.predicate, f.dst_concept_id,
                   f.qualifier_json::text AS qualifier_json, f.confidence, f.extractor, f.status,
                   f.review_note, COALESCE(f.valid_from::text, '') AS valid_from, COALESCE(f.valid_to::text, '') AS valid_to,
                   f.created_at, f.updated_at,
                   COALESCE(sc.canonical_name, '') AS src_concept_label,
                   COALESCE(dc.canonical_name, '') AS dst_concept_label
            FROM ontology_fact f
            LEFT JOIN ontology_concept sc ON sc.concept_id = f.src_concept_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.status.is_empty() && req.status != "all" {
            query.push_str(&format!(" AND f.status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.stream_id.is_empty() {
            query.push_str(&format!(
                " AND EXISTS (SELECT 1 FROM ontology_fact_evidence fe WHERE fe.fact_id = f.fact_id AND {})",
                stream_scalar_match("fe.stream_id", binds.len() + 1, req.stream_prefix)
            ));
            binds.push(req.stream_id);
        }
        if !req.predicate.is_empty() {
            query.push_str(&format!(" AND f.predicate = ${}", binds.len() + 1));
            binds.push(req.predicate);
        }
        if !req.extractor.is_empty() {
            query.push_str(&format!(" AND f.extractor = ${}", binds.len() + 1));
            binds.push(req.extractor);
        }
        if !req.src_concept_id.is_empty() {
            query.push_str(&format!(" AND f.src_concept_id = ${}", binds.len() + 1));
            binds.push(req.src_concept_id);
        }
        if !req.dst_concept_id.is_empty() {
            query.push_str(&format!(" AND f.dst_concept_id = ${}", binds.len() + 1));
            binds.push(req.dst_concept_id);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (f.predicate ILIKE ${idx} OR sc.canonical_name ILIKE ${idx} OR dc.canonical_name ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY f.confidence DESC, f.updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));
        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);
        let rows = sql_query.fetch_all(&self.pool).await?;
        self.backfill_semantic_kernel_for_legacy_rows(&rows).await?;
        let statement_id_map = self
            .load_statement_ids_by_legacy_fact_rows(&rows)
            .await?;
        Ok(SearchOntologyFactsResponse {
            facts: rows
                .iter()
                .map(|row| map_fact_row_with_statement_id(row, statement_id_map.get(&row.get::<i64, _>("fact_id")).cloned()))
                .collect(),
        })
    }

    async fn search_facts_from_semantic_statements(
        &self,
        req: &SearchOntologyFactsRequest,
    ) -> Result<Vec<PgRow>, sqlx::Error> {
        let (query, binds, limit, offset) =
            build_semantic_fact_projection_query(&SemanticFactQueryOptions {
            status: &req.status,
            stream_id: &req.stream_id,
            stream_prefix: req.stream_prefix,
            predicate: &req.predicate,
            extractor: &req.extractor,
            src_concept_id: &req.src_concept_id,
            dst_concept_id: &req.dst_concept_id,
            query: &req.query,
            limit: if req.limit > 0 { req.limit } else { 50 },
            offset: req.offset,
        });
        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(limit);
        sql_query = sql_query.bind(offset);
        sql_query.fetch_all(&self.pool).await
    }

    pub async fn get_neighbors(
        &self,
        req: GetOntologyConceptNeighborsRequest,
    ) -> Result<GetOntologyConceptNeighborsResponse, sqlx::Error> {
        let mut neighbors = Vec::new();
        if req.direction == "out" || req.direction == "both" || req.direction.is_empty() {
            neighbors.extend(
                self.query_neighbors(&req.concept_id, "out", &req.predicate, req.limit)
                    .await?,
            );
        }
        if req.direction == "in" || req.direction == "both" {
            neighbors.extend(
                self.query_neighbors(&req.concept_id, "in", &req.predicate, req.limit)
                    .await?,
            );
        }
        if neighbors.len() > req.limit.max(1) as usize {
            neighbors.truncate(req.limit.max(1) as usize);
        }
        Ok(GetOntologyConceptNeighborsResponse { neighbors })
    }

    pub async fn archive_fact(
        &self,
        req: ArchiveOntologyFactRequest,
    ) -> Result<ArchiveOntologyFactResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        let updated = sqlx::query(
            r#"
            UPDATE ontology_fact
            SET status = 'rejected',
                review_note = CASE WHEN TRIM($2) = '' THEN review_note ELSE TRIM($2) END,
                updated_at = NOW()
            WHERE fact_id = $1
            "#,
        )
        .bind(req.fact_id)
        .bind(&req.note)
        .execute(&mut *tx)
        .await?
        .rows_affected();
        if updated > 0 {
            sqlx::query(
                "INSERT INTO ontology_fact_review (fact_id, reviewer, decision, note) VALUES ($1, $2, 'reject', $3)",
            )
            .bind(req.fact_id)
            .bind(&req.reviewer)
            .bind(&req.note)
            .execute(&mut *tx)
            .await?;
        }
        tx.commit().await?;
        Ok(ArchiveOntologyFactResponse {
            updated_rows: updated as i32,
        })
    }

    pub async fn upsert_term_mapping_registry(
        &self,
        req: UpsertTermMappingRegistryRequest,
    ) -> Result<UpsertTermMappingRegistryResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO term_mapping_registry (
              domain, registry_name, version_label, status, description, owner, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            ON CONFLICT (domain, registry_name, version_label) DO UPDATE SET
              status = EXCLUDED.status,
              description = EXCLUDED.description,
              owner = EXCLUDED.owner,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING registry_id::text AS registry_id, domain, registry_name, version_label, status,
                      description, owner, metadata::text AS metadata_json, created_at, updated_at
            "#,
        )
        .bind(&req.domain)
        .bind(&req.registry_name)
        .bind(&req.version_label)
        .bind(&req.status)
        .bind(&req.description)
        .bind(&req.owner)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertTermMappingRegistryResponse {
            registry: Some(map_term_mapping_registry_row(&row)),
        })
    }

    pub async fn get_term_mapping_registry(
        &self,
        req: GetTermMappingRegistryRequest,
    ) -> Result<GetTermMappingRegistryResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT registry_id::text AS registry_id, domain, registry_name, version_label, status,
                   description, owner, metadata::text AS metadata_json, created_at, updated_at
            FROM term_mapping_registry
            WHERE registry_id = $1::uuid
            "#,
        )
        .bind(&req.registry_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetTermMappingRegistryResponse {
            registry: row.as_ref().map(map_term_mapping_registry_row),
        })
    }

    pub async fn list_term_mapping_registries(
        &self,
        req: ListTermMappingRegistriesRequest,
    ) -> Result<ListTermMappingRegistriesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT registry_id::text AS registry_id, domain, registry_name, version_label, status,
                   description, owner, metadata::text AS metadata_json, created_at, updated_at
            FROM term_mapping_registry
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (registry_name ILIKE ${idx} OR version_label ILIKE ${idx} OR description ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListTermMappingRegistriesResponse {
            registries: rows.iter().map(map_term_mapping_registry_row).collect(),
        })
    }

    pub async fn upsert_term_mapping_rule(
        &self,
        req: UpsertTermMappingRuleRequest,
    ) -> Result<UpsertTermMappingRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO term_mapping_rule (
              rule_id, registry_id, raw_term, language, context_hint, term_type,
              normalization_status, canonical_term, canonical_concept_id, is_compound,
              split_rule_json, semantic_slot, json_targets_json, ontology_target_kind,
              ambiguity_flag, ambiguity_note, review_status, confidence, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, $4, $5, $6, $7, $8, NULLIF($9, ''),
              $10, $11::jsonb, $12, $13::jsonb, $14, $15, $16, $17, NULLIF($18, 0), $19::jsonb
            )
            ON CONFLICT (registry_id, raw_term, language) DO UPDATE SET
              context_hint = EXCLUDED.context_hint,
              term_type = EXCLUDED.term_type,
              normalization_status = EXCLUDED.normalization_status,
              canonical_term = EXCLUDED.canonical_term,
              canonical_concept_id = EXCLUDED.canonical_concept_id,
              is_compound = EXCLUDED.is_compound,
              split_rule_json = EXCLUDED.split_rule_json,
              semantic_slot = EXCLUDED.semantic_slot,
              json_targets_json = EXCLUDED.json_targets_json,
              ontology_target_kind = EXCLUDED.ontology_target_kind,
              ambiguity_flag = EXCLUDED.ambiguity_flag,
              ambiguity_note = EXCLUDED.ambiguity_note,
              review_status = EXCLUDED.review_status,
              confidence = EXCLUDED.confidence,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING rule_id::text AS rule_id, registry_id::text AS registry_id, raw_term, language,
                      context_hint, term_type, normalization_status, canonical_term,
                      COALESCE(canonical_concept_id, '') AS canonical_concept_id, is_compound,
                      split_rule_json::text AS split_rule_json, semantic_slot,
                      json_targets_json::text AS json_targets_json, ontology_target_kind,
                      ambiguity_flag, ambiguity_note, review_status,
                      COALESCE(confidence, 0) AS confidence, metadata::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.rule_id)
        .bind(&req.registry_id)
        .bind(&req.raw_term)
        .bind(&req.language)
        .bind(&req.context_hint)
        .bind(&req.term_type)
        .bind(&req.normalization_status)
        .bind(&req.canonical_term)
        .bind(&req.canonical_concept_id)
        .bind(req.is_compound)
        .bind(if req.split_rule_json.is_empty() { "{}" } else { &req.split_rule_json })
        .bind(&req.semantic_slot)
        .bind(if req.json_targets_json.is_empty() { "[]" } else { &req.json_targets_json })
        .bind(&req.ontology_target_kind)
        .bind(req.ambiguity_flag)
        .bind(&req.ambiguity_note)
        .bind(&req.review_status)
        .bind(req.confidence)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertTermMappingRuleResponse {
            rule: Some(map_term_mapping_rule_row(&row)),
        })
    }

    pub async fn get_term_mapping_rule(
        &self,
        req: GetTermMappingRuleRequest,
    ) -> Result<GetTermMappingRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT rule_id::text AS rule_id, registry_id::text AS registry_id, raw_term, language,
                   context_hint, term_type, normalization_status, canonical_term,
                   COALESCE(canonical_concept_id, '') AS canonical_concept_id, is_compound,
                   split_rule_json::text AS split_rule_json, semantic_slot,
                   json_targets_json::text AS json_targets_json, ontology_target_kind,
                   ambiguity_flag, ambiguity_note, review_status,
                   COALESCE(confidence, 0) AS confidence, metadata::text AS metadata_json,
                   created_at, updated_at
            FROM term_mapping_rule
            WHERE rule_id = $1::uuid
            "#,
        )
        .bind(&req.rule_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetTermMappingRuleResponse {
            rule: row.as_ref().map(map_term_mapping_rule_row),
        })
    }

    pub async fn search_term_mapping_rules(
        &self,
        req: SearchTermMappingRulesRequest,
    ) -> Result<SearchTermMappingRulesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT rule_id::text AS rule_id, registry_id::text AS registry_id, raw_term, language,
                   context_hint, term_type, normalization_status, canonical_term,
                   COALESCE(canonical_concept_id, '') AS canonical_concept_id, is_compound,
                   split_rule_json::text AS split_rule_json, semantic_slot,
                   json_targets_json::text AS json_targets_json, ontology_target_kind,
                   ambiguity_flag, ambiguity_note, review_status,
                   COALESCE(confidence, 0) AS confidence, metadata::text AS metadata_json,
                   created_at, updated_at
            FROM term_mapping_rule
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.registry_id.is_empty() {
            query.push_str(&format!(" AND registry_id = ${}::uuid", binds.len() + 1));
            binds.push(req.registry_id);
        }
        if !req.raw_term.is_empty() {
            query.push_str(&format!(" AND raw_term = ${}", binds.len() + 1));
            binds.push(req.raw_term);
        }
        if !req.language.is_empty() {
            query.push_str(&format!(" AND language = ${}", binds.len() + 1));
            binds.push(req.language);
        }
        if !req.term_type.is_empty() {
            query.push_str(&format!(" AND term_type = ${}", binds.len() + 1));
            binds.push(req.term_type);
        }
        if !req.semantic_slot.is_empty() {
            query.push_str(&format!(" AND semantic_slot = ${}", binds.len() + 1));
            binds.push(req.semantic_slot);
        }
        if !req.review_status.is_empty() {
            query.push_str(&format!(" AND review_status = ${}", binds.len() + 1));
            binds.push(req.review_status);
        }
        if req.ambiguity_only {
            query.push_str(" AND ambiguity_flag = true");
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (raw_term ILIKE ${idx} OR canonical_term ILIKE ${idx} OR context_hint ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(SearchTermMappingRulesResponse {
            rules: rows.iter().map(map_term_mapping_rule_row).collect(),
        })
    }

    pub async fn upsert_term_mapping_rule_evidence(
        &self,
        req: UpsertTermMappingRuleEvidenceRequest,
    ) -> Result<UpsertTermMappingRuleEvidenceResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO term_mapping_rule_evidence (
              rule_evidence_id, rule_id, artifact_id, artifact_version_id, event_id,
              memory_decision_id, source_span, note, confidence, evidence_json
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid,
              NULLIF($3, '')::uuid,
              NULLIF($4, '')::uuid,
              NULLIF($5, '')::uuid,
              NULLIF($6, '')::uuid,
              NULLIF($7, ''),
              $8,
              NULLIF($9, 0),
              $10::jsonb
            )
            RETURNING rule_evidence_id::text AS rule_evidence_id, rule_id::text AS rule_id,
                      COALESCE(artifact_id::text, '') AS artifact_id,
                      COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                      COALESCE(event_id::text, '') AS event_id,
                      COALESCE(memory_decision_id::text, '') AS memory_decision_id,
                      COALESCE(source_span, '') AS source_span,
                      note,
                      COALESCE(confidence, 0) AS confidence,
                      evidence_json::text AS evidence_json,
                      created_at,
                      updated_at
            "#,
        )
        .bind(&req.rule_evidence_id)
        .bind(&req.rule_id)
        .bind(&req.artifact_id)
        .bind(&req.artifact_version_id)
        .bind(&req.event_id)
        .bind(&req.memory_decision_id)
        .bind(&req.source_span)
        .bind(&req.note)
        .bind(req.confidence)
        .bind(if req.evidence_json.is_empty() {
            "{}"
        } else {
            &req.evidence_json
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertTermMappingRuleEvidenceResponse {
            evidence: Some(map_term_mapping_rule_evidence_row(&row)),
        })
    }

    pub async fn list_term_mapping_rule_evidence(
        &self,
        req: ListTermMappingRuleEvidenceRequest,
    ) -> Result<ListTermMappingRuleEvidenceResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT rule_evidence_id::text AS rule_evidence_id, rule_id::text AS rule_id,
                   COALESCE(artifact_id::text, '') AS artifact_id,
                   COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                   COALESCE(event_id::text, '') AS event_id,
                   COALESCE(memory_decision_id::text, '') AS memory_decision_id,
                   COALESCE(source_span, '') AS source_span,
                   note,
                   COALESCE(confidence, 0) AS confidence,
                   evidence_json::text AS evidence_json,
                   created_at,
                   updated_at
            FROM term_mapping_rule_evidence
            WHERE rule_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2
            "#,
        )
        .bind(&req.rule_id)
        .bind(if req.limit > 0 { req.limit } else { 50 })
        .fetch_all(&self.pool)
        .await?;

        Ok(ListTermMappingRuleEvidenceResponse {
            evidence: rows
                .iter()
                .map(map_term_mapping_rule_evidence_row)
                .collect(),
        })
    }

    pub async fn interpret_term(
        &self,
        req: InterpretTermRequest,
    ) -> Result<InterpretTermResponse, sqlx::Error> {
        let registry_id = self
            .resolve_registry_id(
                &req.registry_id,
                &req.domain,
                &req.registry_name,
                &req.version_label,
            )
            .await?;

        let interpretation = if let Some(registry_id) = registry_id {
            let row = sqlx::query(
                r#"
                SELECT rule_id::text AS rule_id, registry_id::text AS registry_id, raw_term, language,
                       context_hint, term_type, normalization_status, canonical_term,
                       COALESCE(canonical_concept_id, '') AS canonical_concept_id, is_compound,
                       split_rule_json::text AS split_rule_json, semantic_slot,
                       json_targets_json::text AS json_targets_json, ontology_target_kind,
                       ambiguity_flag, ambiguity_note, review_status,
                       COALESCE(confidence, 0) AS confidence, metadata::text AS metadata_json,
                       created_at, updated_at
                FROM term_mapping_rule
                WHERE registry_id = $1::uuid
                  AND raw_term = $2
                  AND language = $3
                ORDER BY
                  CASE review_status
                    WHEN 'accepted' THEN 1
                    WHEN 'reviewed' THEN 2
                    WHEN 'pending' THEN 3
                    ELSE 4
                  END,
                  updated_at DESC
                LIMIT 1
                "#,
            )
            .bind(&registry_id)
            .bind(&req.raw_term)
            .bind(if req.language.is_empty() { "zh" } else { req.language.as_str() })
            .fetch_optional(&self.pool)
            .await?;

            row.as_ref()
                .map(map_term_mapping_interpretation_row)
                .unwrap_or_else(|| TermMappingInterpretationRecord {
                    found: false,
                    raw_term: req.raw_term.clone(),
                    matched_rule_id: String::new(),
                    registry_id,
                    language: if req.language.is_empty() {
                        "zh".into()
                    } else {
                        req.language.clone()
                    },
                    term_type: String::new(),
                    normalization_status: String::new(),
                    canonical_term: String::new(),
                    canonical_concept_id: String::new(),
                    is_compound: false,
                    split_rule_json: "{}".into(),
                    semantic_slot: String::new(),
                    json_targets_json: "[]".into(),
                    ontology_target_kind: String::new(),
                    ambiguity_flag: false,
                    ambiguity_note: String::new(),
                    review_status: String::new(),
                    confidence: 0.0,
                })
        } else {
            TermMappingInterpretationRecord {
                found: false,
                raw_term: req.raw_term.clone(),
                matched_rule_id: String::new(),
                registry_id: String::new(),
                language: if req.language.is_empty() {
                    "zh".into()
                } else {
                    req.language.clone()
                },
                term_type: String::new(),
                normalization_status: String::new(),
                canonical_term: String::new(),
                canonical_concept_id: String::new(),
                is_compound: false,
                split_rule_json: "{}".into(),
                semantic_slot: String::new(),
                json_targets_json: "[]".into(),
                ontology_target_kind: String::new(),
                ambiguity_flag: false,
                ambiguity_note: String::new(),
                review_status: String::new(),
                confidence: 0.0,
            }
        };

        Ok(InterpretTermResponse {
            interpretation: Some(interpretation),
        })
    }

    pub async fn interpret_term_batch(
        &self,
        req: InterpretTermBatchRequest,
    ) -> Result<InterpretTermBatchResponse, sqlx::Error> {
        let registry_id = self
            .resolve_registry_id(
                &req.registry_id,
                &req.domain,
                &req.registry_name,
                &req.version_label,
            )
            .await?;

        let mut interpretations = Vec::with_capacity(req.raw_terms.len());
        for raw_term in &req.raw_terms {
            let response = self
                .interpret_term(InterpretTermRequest {
                    registry_id: registry_id.clone().unwrap_or_default(),
                    domain: String::new(),
                    registry_name: String::new(),
                    version_label: String::new(),
                    raw_term: raw_term.clone(),
                    language: req.language.clone(),
                    context_hint: req.context_hint.clone(),
                })
                .await?;
            if let Some(interpretation) = response.interpretation {
                interpretations.push(interpretation);
            }
        }

        Ok(InterpretTermBatchResponse { interpretations })
    }

    pub async fn upsert_ontology_raw_term(
        &self,
        req: UpsertOntologyRawTermRequest,
    ) -> Result<UpsertOntologyRawTermResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_raw_term (
              raw_term_id, domain, raw_term, language, normalized_hint, term_type_hint,
              source_kind, source_ref, artifact_version_id, evidence_id, context_text,
              context_locator_json, extracted_by_type, extracted_by_id, status, metadata_json
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2, $3, $4, $5, $6, $7, $8,
              NULLIF($9, '')::uuid,
              NULLIF($10, '')::uuid,
              $11,
              $12::jsonb,
              $13, $14, $15, $16::jsonb
            )
            ON CONFLICT (raw_term_id) DO UPDATE SET
              domain = EXCLUDED.domain,
              raw_term = EXCLUDED.raw_term,
              language = EXCLUDED.language,
              normalized_hint = EXCLUDED.normalized_hint,
              term_type_hint = EXCLUDED.term_type_hint,
              source_kind = EXCLUDED.source_kind,
              source_ref = EXCLUDED.source_ref,
              artifact_version_id = EXCLUDED.artifact_version_id,
              evidence_id = EXCLUDED.evidence_id,
              context_text = EXCLUDED.context_text,
              context_locator_json = EXCLUDED.context_locator_json,
              extracted_by_type = EXCLUDED.extracted_by_type,
              extracted_by_id = EXCLUDED.extracted_by_id,
              status = EXCLUDED.status,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING raw_term_id::text AS raw_term_id, domain, raw_term, language,
                      normalized_hint, term_type_hint, source_kind, source_ref,
                      COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                      COALESCE(evidence_id::text, '') AS evidence_id,
                      context_text,
                      context_locator_json::text AS context_locator_json,
                      extracted_by_type, extracted_by_id, status,
                      metadata_json::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.raw_term_id)
        .bind(&req.domain)
        .bind(&req.raw_term)
        .bind(if req.language.is_empty() {
            "zh"
        } else {
            &req.language
        })
        .bind(&req.normalized_hint)
        .bind(&req.term_type_hint)
        .bind(&req.source_kind)
        .bind(&req.source_ref)
        .bind(&req.artifact_version_id)
        .bind(&req.evidence_id)
        .bind(&req.context_text)
        .bind(if req.context_locator_json.is_empty() {
            "{}"
        } else {
            &req.context_locator_json
        })
        .bind(&req.extracted_by_type)
        .bind(&req.extracted_by_id)
        .bind(if req.status.is_empty() {
            "new"
        } else {
            &req.status
        })
        .bind(if req.metadata_json.is_empty() {
            "{}"
        } else {
            &req.metadata_json
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyRawTermResponse {
            raw_term: Some(map_ontology_raw_term_row(&row)),
        })
    }

    pub async fn get_ontology_raw_term(
        &self,
        req: GetOntologyRawTermRequest,
    ) -> Result<GetOntologyRawTermResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT raw_term_id::text AS raw_term_id, domain, raw_term, language,
                   normalized_hint, term_type_hint, source_kind, source_ref,
                   COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                   COALESCE(evidence_id::text, '') AS evidence_id,
                   context_text,
                   context_locator_json::text AS context_locator_json,
                   extracted_by_type, extracted_by_id, status,
                   metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_raw_term
            WHERE raw_term_id = $1::uuid
            "#,
        )
        .bind(&req.raw_term_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyRawTermResponse {
            raw_term: row.as_ref().map(map_ontology_raw_term_row),
        })
    }

    pub async fn search_ontology_raw_terms(
        &self,
        req: SearchOntologyRawTermsRequest,
    ) -> Result<SearchOntologyRawTermsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT raw_term_id::text AS raw_term_id, domain, raw_term, language,
                   normalized_hint, term_type_hint, source_kind, source_ref,
                   COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                   COALESCE(evidence_id::text, '') AS evidence_id,
                   context_text,
                   context_locator_json::text AS context_locator_json,
                   extracted_by_type, extracted_by_id, status,
                   metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_raw_term
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.raw_term.is_empty() {
            query.push_str(&format!(" AND raw_term = ${}", binds.len() + 1));
            binds.push(req.raw_term);
        }
        if !req.language.is_empty() {
            query.push_str(&format!(" AND language = ${}", binds.len() + 1));
            binds.push(req.language);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.term_type_hint.is_empty() {
            query.push_str(&format!(" AND term_type_hint = ${}", binds.len() + 1));
            binds.push(req.term_type_hint);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (raw_term ILIKE ${idx} OR normalized_hint ILIKE ${idx} OR context_text ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(SearchOntologyRawTermsResponse {
            raw_terms: rows.iter().map(map_ontology_raw_term_row).collect(),
        })
    }

    pub async fn upsert_ontology_raw_term_candidate(
        &self,
        req: UpsertOntologyRawTermCandidateRequest,
    ) -> Result<UpsertOntologyRawTermCandidateResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_raw_term_candidate (
              candidate_id, raw_term_id, candidate_label, candidate_concept_id,
              candidate_object_type, candidate_relation_type, confidence,
              candidate_status, review_note, metadata_json
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, NULLIF($4, ''), $5, $6,
              NULLIF($7, 0), $8, $9, $10::jsonb
            )
            ON CONFLICT (candidate_id) DO UPDATE SET
              raw_term_id = EXCLUDED.raw_term_id,
              candidate_label = EXCLUDED.candidate_label,
              candidate_concept_id = EXCLUDED.candidate_concept_id,
              candidate_object_type = EXCLUDED.candidate_object_type,
              candidate_relation_type = EXCLUDED.candidate_relation_type,
              confidence = EXCLUDED.confidence,
              candidate_status = EXCLUDED.candidate_status,
              review_note = EXCLUDED.review_note,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING candidate_id::text AS candidate_id, raw_term_id::text AS raw_term_id,
                      candidate_label,
                      COALESCE(candidate_concept_id, '') AS candidate_concept_id,
                      candidate_object_type, candidate_relation_type,
                      COALESCE(confidence, 0) AS confidence,
                      candidate_status, review_note,
                      metadata_json::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.candidate_id)
        .bind(&req.raw_term_id)
        .bind(&req.candidate_label)
        .bind(&req.candidate_concept_id)
        .bind(&req.candidate_object_type)
        .bind(&req.candidate_relation_type)
        .bind(req.confidence)
        .bind(if req.candidate_status.is_empty() {
            "proposed"
        } else {
            &req.candidate_status
        })
        .bind(&req.review_note)
        .bind(if req.metadata_json.is_empty() {
            "{}"
        } else {
            &req.metadata_json
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyRawTermCandidateResponse {
            candidate: Some(map_ontology_raw_term_candidate_row(&row)),
        })
    }

    pub async fn list_ontology_raw_term_candidates(
        &self,
        req: ListOntologyRawTermCandidatesRequest,
    ) -> Result<ListOntologyRawTermCandidatesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT candidate_id::text AS candidate_id, raw_term_id::text AS raw_term_id,
                   candidate_label,
                   COALESCE(candidate_concept_id, '') AS candidate_concept_id,
                   candidate_object_type, candidate_relation_type,
                   COALESCE(confidence, 0) AS confidence,
                   candidate_status, review_note,
                   metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_raw_term_candidate
            WHERE raw_term_id = $1::uuid
            "#,
        );

        if !req.candidate_status.is_empty() {
            query.push_str(" AND candidate_status = $2");
            query.push_str(" ORDER BY updated_at DESC LIMIT $3 OFFSET $4");
            let rows = sqlx::query(&query)
                .bind(&req.raw_term_id)
                .bind(&req.candidate_status)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?;
            return Ok(ListOntologyRawTermCandidatesResponse {
                candidates: rows
                    .iter()
                    .map(map_ontology_raw_term_candidate_row)
                    .collect(),
            });
        }

        query.push_str(" ORDER BY updated_at DESC LIMIT $2 OFFSET $3");
        let rows = sqlx::query(&query)
            .bind(&req.raw_term_id)
            .bind(if req.limit > 0 { req.limit } else { 50 })
            .bind(req.offset)
            .fetch_all(&self.pool)
            .await?;
        Ok(ListOntologyRawTermCandidatesResponse {
            candidates: rows
                .iter()
                .map(map_ontology_raw_term_candidate_row)
                .collect(),
        })
    }

    pub async fn upsert_ontology_normalized_term(
        &self,
        req: UpsertOntologyNormalizedTermRequest,
    ) -> Result<UpsertOntologyNormalizedTermResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            WITH existing AS (
              SELECT normalized_term_id
              FROM ontology_normalized_term
              WHERE (
                NULLIF($1, '')::uuid IS NOT NULL
                AND normalized_term_id = NULLIF($1, '')::uuid
              )
              OR (
                domain = $2
                AND normalized_surface = $3
                AND normalized_type = $4
              )
              ORDER BY
                CASE
                  WHEN NULLIF($1, '')::uuid IS NOT NULL AND normalized_term_id = NULLIF($1, '')::uuid THEN 0
                  ELSE 1
                END
              LIMIT 1
            )
            INSERT INTO ontology_normalized_term (
              normalized_term_id, domain, normalized_surface, normalized_type, merge_key,
              type_confidence, head_term, modifier_terms_json, canonical_candidate_label,
              canonical_candidate_concept_id, primary_cluster_id, source_support_count,
              is_promotable, normalization_status, metadata_json
            )
            VALUES (
              COALESCE(
                (SELECT normalized_term_id FROM existing),
                NULLIF($1, '')::uuid,
                gen_random_uuid()
              ),
              $2, $3, $4, $5, NULLIF($6, 0), $7, $8::jsonb, $9,
              NULLIF($10, ''), NULLIF($11, '')::uuid, $12, $13, $14, $15::jsonb
            )
            ON CONFLICT (normalized_term_id) DO UPDATE SET
              domain = EXCLUDED.domain,
              normalized_surface = EXCLUDED.normalized_surface,
              normalized_type = EXCLUDED.normalized_type,
              merge_key = EXCLUDED.merge_key,
              type_confidence = EXCLUDED.type_confidence,
              head_term = EXCLUDED.head_term,
              modifier_terms_json = EXCLUDED.modifier_terms_json,
              canonical_candidate_label = EXCLUDED.canonical_candidate_label,
              canonical_candidate_concept_id = EXCLUDED.canonical_candidate_concept_id,
              primary_cluster_id = EXCLUDED.primary_cluster_id,
              source_support_count = EXCLUDED.source_support_count,
              is_promotable = EXCLUDED.is_promotable,
              normalization_status = EXCLUDED.normalization_status,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING normalized_term_id::text AS normalized_term_id, domain, normalized_surface,
                      normalized_type, merge_key, COALESCE(type_confidence, 0) AS type_confidence,
                      head_term, modifier_terms_json::text AS modifier_terms_json,
                      canonical_candidate_label,
                      COALESCE(canonical_candidate_concept_id, '') AS canonical_candidate_concept_id,
                      COALESCE(primary_cluster_id::text, '') AS primary_cluster_id,
                      source_support_count, is_promotable, normalization_status,
                      metadata_json::text AS metadata_json, created_at, updated_at
            "#,
        )
        .bind(&req.normalized_term_id)
        .bind(&req.domain)
        .bind(&req.normalized_surface)
        .bind(&req.normalized_type)
        .bind(&req.merge_key)
        .bind(req.type_confidence)
        .bind(&req.head_term)
        .bind(if req.modifier_terms_json.is_empty() { "[]" } else { &req.modifier_terms_json })
        .bind(&req.canonical_candidate_label)
        .bind(&req.canonical_candidate_concept_id)
        .bind(&req.primary_cluster_id)
        .bind(req.source_support_count)
        .bind(req.is_promotable)
        .bind(if req.normalization_status.is_empty() { "auto" } else { &req.normalization_status })
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyNormalizedTermResponse {
            normalized_term: Some(map_ontology_normalized_term_row(&row)),
        })
    }

    pub async fn get_ontology_normalized_term(
        &self,
        req: GetOntologyNormalizedTermRequest,
    ) -> Result<GetOntologyNormalizedTermResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT normalized_term_id::text AS normalized_term_id, domain, normalized_surface,
                   normalized_type, merge_key, COALESCE(type_confidence, 0) AS type_confidence,
                   head_term, modifier_terms_json::text AS modifier_terms_json,
                   canonical_candidate_label,
                   COALESCE(canonical_candidate_concept_id, '') AS canonical_candidate_concept_id,
                   COALESCE(primary_cluster_id::text, '') AS primary_cluster_id,
                   source_support_count, is_promotable, normalization_status,
                   metadata_json::text AS metadata_json, created_at, updated_at
            FROM ontology_normalized_term
            WHERE normalized_term_id = $1::uuid
            "#,
        )
        .bind(&req.normalized_term_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyNormalizedTermResponse {
            normalized_term: row.as_ref().map(map_ontology_normalized_term_row),
        })
    }

    pub async fn search_ontology_normalized_terms(
        &self,
        req: SearchOntologyNormalizedTermsRequest,
    ) -> Result<SearchOntologyNormalizedTermsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT normalized_term_id::text AS normalized_term_id, domain, normalized_surface,
                   normalized_type, merge_key, COALESCE(type_confidence, 0) AS type_confidence,
                   head_term, modifier_terms_json::text AS modifier_terms_json,
                   canonical_candidate_label,
                   COALESCE(canonical_candidate_concept_id, '') AS canonical_candidate_concept_id,
                   COALESCE(primary_cluster_id::text, '') AS primary_cluster_id,
                   source_support_count, is_promotable, normalization_status,
                   metadata_json::text AS metadata_json, created_at, updated_at
            FROM ontology_normalized_term
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.normalized_surface.is_empty() {
            query.push_str(&format!(" AND normalized_surface = ${}", binds.len() + 1));
            binds.push(req.normalized_surface);
        }
        if !req.normalized_type.is_empty() {
            query.push_str(&format!(" AND normalized_type = ${}", binds.len() + 1));
            binds.push(req.normalized_type);
        }
        if !req.normalization_status.is_empty() {
            query.push_str(&format!(" AND normalization_status = ${}", binds.len() + 1));
            binds.push(req.normalization_status);
        }
        if !req.primary_cluster_id.is_empty() {
            query.push_str(&format!(
                " AND primary_cluster_id = ${}::uuid",
                binds.len() + 1
            ));
            binds.push(req.primary_cluster_id);
        }
        if req.promotable_only {
            query.push_str(" AND is_promotable = TRUE");
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(
                " AND (normalized_surface ILIKE ${idx} OR head_term ILIKE ${idx} OR canonical_candidate_label ILIKE ${idx})"
            ));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(SearchOntologyNormalizedTermsResponse {
            normalized_terms: rows.iter().map(map_ontology_normalized_term_row).collect(),
        })
    }

    pub async fn upsert_ontology_term_cluster(
        &self,
        req: UpsertOntologyTermClusterRequest,
    ) -> Result<UpsertOntologyTermClusterResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_term_cluster (
              cluster_id, domain, cluster_type, proposed_canonical, proposed_type,
              cluster_status, member_count, source_support_count, confidence, metadata_json
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2, $3, $4, $5, $6, $7, $8, NULLIF($9, 0), $10::jsonb
            )
            ON CONFLICT (cluster_id) DO UPDATE SET
              domain = EXCLUDED.domain,
              cluster_type = EXCLUDED.cluster_type,
              proposed_canonical = EXCLUDED.proposed_canonical,
              proposed_type = EXCLUDED.proposed_type,
              cluster_status = EXCLUDED.cluster_status,
              member_count = EXCLUDED.member_count,
              source_support_count = EXCLUDED.source_support_count,
              confidence = EXCLUDED.confidence,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING cluster_id::text AS cluster_id, domain, cluster_type, proposed_canonical,
                      proposed_type, cluster_status, member_count, source_support_count,
                      COALESCE(confidence, 0) AS confidence, metadata_json::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.cluster_id)
        .bind(&req.domain)
        .bind(if req.cluster_type.is_empty() {
            "same_family"
        } else {
            &req.cluster_type
        })
        .bind(&req.proposed_canonical)
        .bind(&req.proposed_type)
        .bind(if req.cluster_status.is_empty() {
            "auto"
        } else {
            &req.cluster_status
        })
        .bind(req.member_count)
        .bind(req.source_support_count)
        .bind(req.confidence)
        .bind(if req.metadata_json.is_empty() {
            "{}"
        } else {
            &req.metadata_json
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyTermClusterResponse {
            cluster: Some(map_ontology_term_cluster_row(&row)),
        })
    }

    pub async fn get_ontology_term_cluster(
        &self,
        req: GetOntologyTermClusterRequest,
    ) -> Result<GetOntologyTermClusterResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT cluster_id::text AS cluster_id, domain, cluster_type, proposed_canonical,
                   proposed_type, cluster_status, member_count, source_support_count,
                   COALESCE(confidence, 0) AS confidence, metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_term_cluster
            WHERE cluster_id = $1::uuid
            "#,
        )
        .bind(&req.cluster_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyTermClusterResponse {
            cluster: row.as_ref().map(map_ontology_term_cluster_row),
        })
    }

    pub async fn list_ontology_term_clusters(
        &self,
        req: ListOntologyTermClustersRequest,
    ) -> Result<ListOntologyTermClustersResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT cluster_id::text AS cluster_id, domain, cluster_type, proposed_canonical,
                   proposed_type, cluster_status, member_count, source_support_count,
                   COALESCE(confidence, 0) AS confidence, metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_term_cluster
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.cluster_type.is_empty() {
            query.push_str(&format!(" AND cluster_type = ${}", binds.len() + 1));
            binds.push(req.cluster_type);
        }
        if !req.cluster_status.is_empty() {
            query.push_str(&format!(" AND cluster_status = ${}", binds.len() + 1));
            binds.push(req.cluster_status);
        }
        if !req.proposed_type.is_empty() {
            query.push_str(&format!(" AND proposed_type = ${}", binds.len() + 1));
            binds.push(req.proposed_type);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyTermClustersResponse {
            clusters: rows.iter().map(map_ontology_term_cluster_row).collect(),
        })
    }

    pub async fn upsert_ontology_cluster_member(
        &self,
        req: UpsertOntologyClusterMemberRequest,
    ) -> Result<UpsertOntologyClusterMemberResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_cluster_member (
              cluster_member_id, cluster_id, normalized_term_id, member_role,
              membership_confidence, added_by, note
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3::uuid, $4, NULLIF($5, 0), $6, $7
            )
            ON CONFLICT (cluster_member_id) DO UPDATE SET
              cluster_id = EXCLUDED.cluster_id,
              normalized_term_id = EXCLUDED.normalized_term_id,
              member_role = EXCLUDED.member_role,
              membership_confidence = EXCLUDED.membership_confidence,
              added_by = EXCLUDED.added_by,
              note = EXCLUDED.note,
              updated_at = NOW()
            RETURNING cluster_member_id::text AS cluster_member_id, cluster_id::text AS cluster_id,
                      normalized_term_id::text AS normalized_term_id, member_role,
                      COALESCE(membership_confidence, 0) AS membership_confidence,
                      added_by, note, created_at, updated_at
            "#,
        )
        .bind(&req.cluster_member_id)
        .bind(&req.cluster_id)
        .bind(&req.normalized_term_id)
        .bind(if req.member_role.is_empty() {
            "core"
        } else {
            &req.member_role
        })
        .bind(req.membership_confidence)
        .bind(if req.added_by.is_empty() {
            "system"
        } else {
            &req.added_by
        })
        .bind(&req.note)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyClusterMemberResponse {
            member: Some(map_ontology_cluster_member_row(&row)),
        })
    }

    pub async fn list_ontology_cluster_members(
        &self,
        req: ListOntologyClusterMembersRequest,
    ) -> Result<ListOntologyClusterMembersResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT cluster_member_id::text AS cluster_member_id, cluster_id::text AS cluster_id,
                   normalized_term_id::text AS normalized_term_id, member_role,
                   COALESCE(membership_confidence, 0) AS membership_confidence,
                   added_by, note, created_at, updated_at
            FROM ontology_cluster_member
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.cluster_id.is_empty() {
            query.push_str(&format!(" AND cluster_id = ${}::uuid", binds.len() + 1));
            binds.push(req.cluster_id);
        }
        if !req.normalized_term_id.is_empty() {
            query.push_str(&format!(
                " AND normalized_term_id = ${}::uuid",
                binds.len() + 1
            ));
            binds.push(req.normalized_term_id);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyClusterMembersResponse {
            members: rows.iter().map(map_ontology_cluster_member_row).collect(),
        })
    }

    pub async fn upsert_ontology_relation_candidate(
        &self,
        req: UpsertOntologyRelationCandidateRequest,
    ) -> Result<UpsertOntologyRelationCandidateResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            WITH existing AS (
              SELECT relation_candidate_id
              FROM ontology_relation_candidate
              WHERE (
                NULLIF($1, '')::uuid IS NOT NULL
                AND relation_candidate_id = NULLIF($1, '')::uuid
              ) OR (
                domain = $2
                AND subject_label = $3
                AND relation_type = $4
                AND object_label = $5
              )
              ORDER BY relation_candidate_id
              LIMIT 1
            )
            INSERT INTO ontology_relation_candidate (
              relation_candidate_id, domain, subject_label, relation_type, object_label,
              subject_concept_id, object_concept_id, candidate_status, source_kind,
              source_cluster_id, confidence, metadata_json
            )
            VALUES (
              COALESCE((SELECT relation_candidate_id FROM existing), NULLIF($1, '')::uuid, gen_random_uuid()),
              $2, $3, $4, $5,
              NULLIF($6, ''), NULLIF($7, ''),
              $8, $9, NULLIF($10, '')::uuid,
              NULLIF($11, 0), $12::jsonb
            )
            ON CONFLICT (relation_candidate_id) DO UPDATE SET
              domain = EXCLUDED.domain,
              subject_label = EXCLUDED.subject_label,
              relation_type = EXCLUDED.relation_type,
              object_label = EXCLUDED.object_label,
              subject_concept_id = EXCLUDED.subject_concept_id,
              object_concept_id = EXCLUDED.object_concept_id,
              candidate_status = EXCLUDED.candidate_status,
              source_kind = EXCLUDED.source_kind,
              source_cluster_id = EXCLUDED.source_cluster_id,
              confidence = EXCLUDED.confidence,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING relation_candidate_id::text AS relation_candidate_id, domain, subject_label,
                      relation_type, object_label, subject_concept_id, object_concept_id,
                      candidate_status, source_kind, source_cluster_id::text AS source_cluster_id,
                      COALESCE(confidence, 0) AS confidence, metadata_json::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.relation_candidate_id)
        .bind(&req.domain)
        .bind(&req.subject_label)
        .bind(&req.relation_type)
        .bind(&req.object_label)
        .bind(&req.subject_concept_id)
        .bind(&req.object_concept_id)
        .bind(match req.candidate_status.as_str() {
            "accepted" | "rejected" | "needs_review" => req.candidate_status.as_str(),
            _ => "auto",
        })
        .bind(&req.source_kind)
        .bind(&req.source_cluster_id)
        .bind(req.confidence)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyRelationCandidateResponse {
            relation_candidate: Some(map_ontology_relation_candidate_row(&row)),
        })
    }

    pub async fn list_ontology_relation_candidates(
        &self,
        req: ListOntologyRelationCandidatesRequest,
    ) -> Result<ListOntologyRelationCandidatesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT relation_candidate_id::text AS relation_candidate_id, domain, subject_label,
                   relation_type, object_label, subject_concept_id, object_concept_id,
                   candidate_status, source_kind, source_cluster_id::text AS source_cluster_id,
                   COALESCE(confidence, 0) AS confidence, metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_relation_candidate
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.relation_type.is_empty() {
            query.push_str(&format!(" AND relation_type = ${}", binds.len() + 1));
            binds.push(req.relation_type);
        }
        if !req.candidate_status.is_empty() {
            query.push_str(&format!(" AND candidate_status = ${}", binds.len() + 1));
            binds.push(req.candidate_status);
        }
        if !req.subject_label.is_empty() {
            query.push_str(&format!(" AND subject_label = ${}", binds.len() + 1));
            binds.push(req.subject_label);
        }
        if !req.object_label.is_empty() {
            query.push_str(&format!(" AND object_label = ${}", binds.len() + 1));
            binds.push(req.object_label);
        }
        if !req.source_kind.is_empty() {
            query.push_str(&format!(" AND source_kind = ${}", binds.len() + 1));
            binds.push(req.source_kind);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyRelationCandidatesResponse {
            relation_candidates: rows
                .iter()
                .map(map_ontology_relation_candidate_row)
                .collect(),
        })
    }

    pub async fn upsert_ontology_raw_term_normalization(
        &self,
        req: UpsertOntologyRawTermNormalizationRequest,
    ) -> Result<UpsertOntologyRawTermNormalizationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            WITH existing AS (
              SELECT mapping_id
              FROM ontology_raw_term_normalization
              WHERE (
                NULLIF($1, '')::uuid IS NOT NULL
                AND mapping_id = NULLIF($1, '')::uuid
              )
              OR (
                raw_term_id = $2::uuid
                AND normalized_term_id = $3::uuid
                AND mapping_type = $5
              )
              ORDER BY
                CASE
                  WHEN NULLIF($1, '')::uuid IS NOT NULL AND mapping_id = NULLIF($1, '')::uuid THEN 0
                  ELSE 1
                END
              LIMIT 1
            )
            INSERT INTO ontology_raw_term_normalization (
              mapping_id, raw_term_id, normalized_term_id, mapping_confidence, mapping_type,
              mapping_status, component_role, normalization_rule, note, metadata_json
            )
            VALUES (
              COALESCE(
                (SELECT mapping_id FROM existing),
                NULLIF($1, '')::uuid,
                gen_random_uuid()
              ),
              $2::uuid, $3::uuid, NULLIF($4, 0), $5, $6, $7, $8, $9, $10::jsonb
            )
            ON CONFLICT (mapping_id) DO UPDATE SET
              raw_term_id = EXCLUDED.raw_term_id,
              normalized_term_id = EXCLUDED.normalized_term_id,
              mapping_confidence = EXCLUDED.mapping_confidence,
              mapping_type = EXCLUDED.mapping_type,
              mapping_status = EXCLUDED.mapping_status,
              component_role = EXCLUDED.component_role,
              normalization_rule = EXCLUDED.normalization_rule,
              note = EXCLUDED.note,
              metadata_json = EXCLUDED.metadata_json,
              updated_at = NOW()
            RETURNING mapping_id::text AS mapping_id, raw_term_id::text AS raw_term_id,
                      normalized_term_id::text AS normalized_term_id,
                      COALESCE(mapping_confidence, 0) AS mapping_confidence,
                      mapping_type, mapping_status, component_role,
                      normalization_rule, note, metadata_json::text AS metadata_json,
                      created_at, updated_at
            "#,
        )
        .bind(&req.mapping_id)
        .bind(&req.raw_term_id)
        .bind(&req.normalized_term_id)
        .bind(req.mapping_confidence)
        .bind(if req.mapping_type.is_empty() {
            "surface_normalized"
        } else {
            &req.mapping_type
        })
        .bind(if req.mapping_status.is_empty() {
            "auto"
        } else {
            &req.mapping_status
        })
        .bind(&req.component_role)
        .bind(&req.normalization_rule)
        .bind(&req.note)
        .bind(if req.metadata_json.is_empty() {
            "{}"
        } else {
            &req.metadata_json
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyRawTermNormalizationResponse {
            mapping: Some(map_ontology_raw_term_normalization_row(&row)),
        })
    }

    pub async fn list_ontology_raw_term_normalizations(
        &self,
        req: ListOntologyRawTermNormalizationsRequest,
    ) -> Result<ListOntologyRawTermNormalizationsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT mapping_id::text AS mapping_id, raw_term_id::text AS raw_term_id,
                   normalized_term_id::text AS normalized_term_id,
                   COALESCE(mapping_confidence, 0) AS mapping_confidence,
                   mapping_type, mapping_status, component_role,
                   normalization_rule, note, metadata_json::text AS metadata_json,
                   created_at, updated_at
            FROM ontology_raw_term_normalization
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.raw_term_id.is_empty() {
            query.push_str(&format!(" AND raw_term_id = ${}::uuid", binds.len() + 1));
            binds.push(req.raw_term_id);
        }
        if !req.normalized_term_id.is_empty() {
            query.push_str(&format!(
                " AND normalized_term_id = ${}::uuid",
                binds.len() + 1
            ));
            binds.push(req.normalized_term_id);
        }
        if !req.mapping_status.is_empty() {
            query.push_str(&format!(" AND mapping_status = ${}", binds.len() + 1));
            binds.push(req.mapping_status);
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListOntologyRawTermNormalizationsResponse {
            mappings: rows
                .iter()
                .map(map_ontology_raw_term_normalization_row)
                .collect(),
        })
    }

    async fn resolve_registry_id(
        &self,
        registry_id: &str,
        domain: &str,
        registry_name: &str,
        version_label: &str,
    ) -> Result<Option<String>, sqlx::Error> {
        if !registry_id.is_empty() {
            return Ok(Some(registry_id.to_string()));
        }

        let row = if !domain.is_empty() && !registry_name.is_empty() && !version_label.is_empty() {
            sqlx::query(
                r#"
                SELECT registry_id::text AS registry_id
                FROM term_mapping_registry
                WHERE domain = $1
                  AND registry_name = $2
                  AND version_label = $3
                LIMIT 1
                "#,
            )
            .bind(domain)
            .bind(registry_name)
            .bind(version_label)
            .fetch_optional(&self.pool)
            .await?
        } else if !domain.is_empty() {
            sqlx::query(
                r#"
                SELECT registry_id::text AS registry_id
                FROM term_mapping_registry
                WHERE domain = $1
                  AND status = 'active'
                ORDER BY updated_at DESC
                LIMIT 1
                "#,
            )
            .bind(domain)
            .fetch_optional(&self.pool)
            .await?
        } else {
            None
        };

        Ok(row.map(|r| r.get("registry_id")))
    }

    async fn insert_fact_evidence(
        &self,
        tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
        fact_id: i64,
        evidence: &OntologyFactEvidenceWrite,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"
            INSERT INTO ontology_fact_evidence (
              fact_id, stream_id, event_id, asset_id, version_number,
              source_span, evidence_json, confidence
            )
            VALUES ($1, $2, $3, NULLIF($4, ''), NULLIF($5, 0), NULLIF($6, ''), $7::jsonb, $8)
            ON CONFLICT (fact_id, stream_id, event_id) DO UPDATE SET
              confidence = GREATEST(ontology_fact_evidence.confidence, EXCLUDED.confidence),
              source_span = COALESCE(EXCLUDED.source_span, ontology_fact_evidence.source_span),
              evidence_json = ontology_fact_evidence.evidence_json || EXCLUDED.evidence_json,
              asset_id = COALESCE(EXCLUDED.asset_id, ontology_fact_evidence.asset_id),
              version_number = COALESCE(EXCLUDED.version_number, ontology_fact_evidence.version_number),
              updated_at = NOW()
            "#,
        )
        .bind(fact_id)
        .bind(&evidence.stream_id)
        .bind(&evidence.event_id)
        .bind(&evidence.asset_id)
        .bind(evidence.version_number)
        .bind(&evidence.source_span)
        .bind(if evidence.evidence_json.is_empty() { "{}" } else { &evidence.evidence_json })
        .bind(evidence.confidence)
        .execute(&mut **tx)
        .await?;
        Ok(())
    }

    async fn query_neighbors(
        &self,
        concept_id: &str,
        direction: &str,
        predicate: &str,
        limit: i32,
    ) -> Result<Vec<OntologyNeighborRecord>, sqlx::Error> {
        let semantic_rows = self
            .load_semantic_neighbors(concept_id, direction, predicate, limit)
            .await?;
        if !semantic_rows.is_empty() {
            return Ok(semantic_rows
                .iter()
                .map(|row| OntologyNeighborRecord {
                    fact_id: row.get("fact_id"),
                    predicate: row.get("predicate"),
                    direction: row.get("direction"),
                    neighbor_concept_id: row.get("neighbor_concept_id"),
                    neighbor_canonical_name: row.get("neighbor_canonical_name"),
                    neighbor_concept_type: row.get("neighbor_concept_type"),
                    status: row.get("status"),
                    confidence: row.get::<f64, _>("confidence") as _,
                })
                .collect());
        }

        let sql = if direction == "in" {
            r#"
            SELECT f.fact_id, 'in' AS direction, f.predicate, f.src_concept_id AS neighbor_concept_id,
                   c.canonical_name AS neighbor_canonical_name, c.concept_type AS neighbor_concept_type,
                   f.status, f.confidence
            FROM ontology_fact f
            JOIN ontology_concept c ON c.concept_id = f.src_concept_id
            WHERE f.dst_concept_id = $1
              AND ($2 = '' OR f.predicate = $2)
              AND f.status <> 'rejected'
            ORDER BY f.confidence DESC, f.updated_at DESC
            LIMIT $3
            "#
        } else {
            r#"
            SELECT f.fact_id, 'out' AS direction, f.predicate, f.dst_concept_id AS neighbor_concept_id,
                   c.canonical_name AS neighbor_canonical_name, c.concept_type AS neighbor_concept_type,
                   f.status, f.confidence
            FROM ontology_fact f
            JOIN ontology_concept c ON c.concept_id = f.dst_concept_id
            WHERE f.src_concept_id = $1
              AND ($2 = '' OR f.predicate = $2)
              AND f.status <> 'rejected'
            ORDER BY f.confidence DESC, f.updated_at DESC
            LIMIT $3
            "#
        };
        let rows = sqlx::query(sql)
            .bind(concept_id)
            .bind(predicate)
            .bind(limit.max(1))
            .fetch_all(&self.pool)
            .await?;
        self.backfill_semantic_kernel_for_legacy_rows(&rows).await?;
        Ok(rows
            .iter()
            .map(|row| OntologyNeighborRecord {
                fact_id: row.get("fact_id"),
                predicate: row.get("predicate"),
                direction: row.get("direction"),
                neighbor_concept_id: row.get("neighbor_concept_id"),
                neighbor_canonical_name: row.get("neighbor_canonical_name"),
                neighbor_concept_type: row.get("neighbor_concept_type"),
                status: row.get("status"),
                confidence: row.get::<f64, _>("confidence") as _,
            })
            .collect())
    }
}

struct SemanticFactQueryOptions<'a> {
    status: &'a str,
    stream_id: &'a str,
    stream_prefix: bool,
    predicate: &'a str,
    extractor: &'a str,
    src_concept_id: &'a str,
    dst_concept_id: &'a str,
    query: &'a str,
    limit: i32,
    offset: i32,
}

fn map_concept_row(row: &sqlx::postgres::PgRow) -> OntologyConceptRecord {
    OntologyConceptRecord {
        concept_id: row.get("concept_id"),
        canonical_name: row.get("canonical_name"),
        concept_type: row.get("concept_type"),
        aliases_json: row
            .get::<Option<String>, _>("aliases_json")
            .unwrap_or_else(|| "[]".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_alias_row(row: &sqlx::postgres::PgRow) -> ConceptAliasRecord {
    ConceptAliasRecord {
        concept_id: row.get("concept_id"),
        alias_text: row.get("alias_text"),
        confidence: row.get::<f64, _>("confidence") as _,
        extractor: row.get("extractor"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_edge_row(row: &sqlx::postgres::PgRow) -> OntologyEdgeRecord {
    OntologyEdgeRecord {
        src_concept_id: row.get("src_concept_id"),
        predicate: row.get("predicate"),
        dst_concept_id: row.get("dst_concept_id"),
        weight: row.get::<f64, _>("weight") as _,
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

fn map_event_link_row(row: &sqlx::postgres::PgRow) -> EventConceptLinkRecord {
    EventConceptLinkRecord {
        stream_id: row.get("stream_id"),
        event_id: row.get("event_id"),
        concept_id: row.get("concept_id"),
        role: row.get("role"),
        confidence: row.get::<f64, _>("confidence") as _,
        asset_id: row.get("asset_id"),
        version_number: row.get("version_number"),
        extractor: row.get("extractor"),
        source_span: row.get("source_span"),
        evidence_json: row
            .get::<Option<String>, _>("evidence_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn semantic_statement_status_to_legacy_case(status_expr: &str) -> String {
    format!(
        r#"CASE {status_expr}
                WHEN 'extracted' THEN 'candidate'
                WHEN 'accepted' THEN 'accepted'
                WHEN 'reviewed' THEN 'needs_review'
                WHEN 'rejected' THEN 'rejected'
                WHEN 'deprecated' THEN 'rejected'
                ELSE 'candidate'
              END"#
    )
}

fn semantic_status_filters_for_legacy_status(status: &str) -> &'static [&'static str] {
    match status {
        "accepted" => &["accepted"],
        "candidate" => &["extracted", "proposed"],
        "needs_review" => &["reviewed"],
        "rejected" => &["rejected", "deprecated"],
        _ => &["extracted", "accepted", "reviewed", "rejected", "deprecated", "proposed"],
    }
}

fn semantic_status_list_sql(statuses: &[&str]) -> String {
    statuses
        .iter()
        .map(|status| format!("'{}'", status.replace('\'', "''")))
        .collect::<Vec<_>>()
        .join(", ")
}

fn semantic_fact_projection_base_query() -> String {
    format!(
        r#"
        SELECT
          COALESCE((ss.metadata_json->>'legacy_fact_id')::bigint, 0) AS fact_id,
          ss.statement_id::text AS statement_id,
          ss.subject_id AS src_concept_id,
          ss.property_id AS predicate,
          ss.value_entity_id AS dst_concept_id,
          COALESCE(sq.value_json::text, '{{}}'::text) AS qualifier_json,
          ss.confidence,
          COALESCE(NULLIF(ss.metadata_json->>'legacy_extractor', ''), ss.created_by, '') AS extractor,
          {} AS status,
          COALESCE(ss.metadata_json->>'legacy_review_note', '') AS review_note,
          ''::text AS valid_from,
          ''::text AS valid_to,
          ss.created_at,
          ss.updated_at,
          COALESCE(sc.canonical_name, '') AS src_concept_label,
          COALESCE(dc.canonical_name, '') AS dst_concept_label
        FROM semantic_statement ss
        LEFT JOIN ontology_concept sc ON sc.concept_id = ss.subject_id
        LEFT JOIN ontology_concept dc ON dc.concept_id = ss.value_entity_id
        LEFT JOIN statement_qualifier sq
          ON sq.statement_id = ss.statement_id
         AND sq.property_id = $1
        WHERE ss.value_type = 'entity'
          AND ss.subject_id <> ''
          AND ss.property_id <> ''
          AND COALESCE(ss.value_entity_id, '') <> ''
          AND COALESCE(ss.metadata_json->>'statement_scope', '') <> 'aggregation'
        "#,
        semantic_statement_status_to_legacy_case("ss.status")
    )
}

fn build_semantic_fact_projection_query(
    options: &SemanticFactQueryOptions<'_>,
) -> (String, Vec<String>, i32, i32) {
    let mut query = semantic_fact_projection_base_query();
    let mut binds: Vec<String> = vec![SEMANTIC_QUALIFIER_PROPERTY_ID.to_string()];

    if !options.status.is_empty() && options.status != "all" {
        query.push_str(&format!(
            " AND ss.status IN ({})",
            semantic_status_list_sql(semantic_status_filters_for_legacy_status(options.status))
        ));
    }
    if !options.predicate.is_empty() {
        query.push_str(&format!(" AND ss.property_id = ${}", binds.len() + 1));
        binds.push(options.predicate.to_string());
    }
    if !options.extractor.is_empty() {
        query.push_str(&format!(
            " AND COALESCE(NULLIF(ss.metadata_json->>'legacy_extractor', ''), ss.created_by, '') = ${}",
            binds.len() + 1
        ));
        binds.push(options.extractor.to_string());
    }
    if !options.stream_id.is_empty() {
        query.push_str(&format!(
            " AND EXISTS (SELECT 1 FROM statement_reference sr WHERE sr.statement_id = ss.statement_id AND sr.property_id = ${} AND {})",
            binds.len() + 2,
            stream_scalar_match("sr.legacy_stream_id", binds.len() + 1, options.stream_prefix)
        ));
        binds.push(options.stream_id.to_string());
        binds.push(SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID.to_string());
    }
    if !options.src_concept_id.is_empty() {
        query.push_str(&format!(" AND ss.subject_id = ${}", binds.len() + 1));
        binds.push(options.src_concept_id.to_string());
    }
    if !options.dst_concept_id.is_empty() {
        query.push_str(&format!(" AND ss.value_entity_id = ${}", binds.len() + 1));
        binds.push(options.dst_concept_id.to_string());
    }
    if !options.query.is_empty() {
        let idx = binds.len() + 1;
        query.push_str(&format!(
            " AND (ss.property_id ILIKE ${idx} OR sc.canonical_name ILIKE ${idx} OR dc.canonical_name ILIKE ${idx})"
        ));
        binds.push(format!("%{}%", options.query));
    }

    query.push_str(" ORDER BY ss.confidence DESC, ss.updated_at DESC");
    query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
    query.push_str(&format!(" OFFSET ${}", binds.len() + 2));
    (
        query,
        binds,
        if options.limit > 0 { options.limit } else { 100 },
        options.offset,
    )
}

fn build_semantic_edge_projection_query(
    req: &ListOntologyEdgesRequest,
) -> (String, Vec<String>, i32) {
    let mut query = String::from(
        format!(
            r#"
            SELECT
              ss.subject_id AS src_concept_id,
              ss.property_id AS predicate,
              ss.value_entity_id AS dst_concept_id,
              ss.confidence AS weight,
              ss.created_at
            FROM semantic_statement ss
            WHERE ss.value_type = 'entity'
              AND ss.subject_id <> ''
              AND ss.property_id <> ''
              AND COALESCE(ss.value_entity_id, '') <> ''
              AND COALESCE(ss.metadata_json->>'statement_scope', '') <> 'aggregation'
              AND ss.status IN ({})
            "#,
            semantic_status_list_sql(SEMANTIC_ACTIVE_FACT_STATUSES)
        )
        .as_str(),
    );
    let mut binds: Vec<String> = Vec::new();
    if !req.src_concept_id.is_empty() {
        query.push_str(&format!(" AND ss.subject_id = ${}", binds.len() + 1));
        binds.push(req.src_concept_id.clone());
    }
    if !req.predicate.is_empty() {
        query.push_str(&format!(" AND ss.property_id = ${}", binds.len() + 1));
        binds.push(req.predicate.clone());
    }
    if !req.dst_concept_id.is_empty() {
        query.push_str(&format!(" AND ss.value_entity_id = ${}", binds.len() + 1));
        binds.push(req.dst_concept_id.clone());
    }
    query.push_str(" ORDER BY ss.created_at DESC");
    query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
    (query, binds, if req.limit > 0 { req.limit } else { 100 })
}

impl OntologyRpcStore {
    async fn load_semantic_neighbors(
        &self,
        concept_id: &str,
        direction: &str,
        predicate: &str,
        limit: i32,
    ) -> Result<Vec<PgRow>, sqlx::Error> {
        let (neighbor_select, concept_join, concept_filter) = if direction == "in" {
            (
                "ss.subject_id AS neighbor_concept_id",
                "c.concept_id = ss.subject_id",
                "ss.value_entity_id = $1",
            )
        } else {
            (
                "ss.value_entity_id AS neighbor_concept_id",
                "c.concept_id = ss.value_entity_id",
                "ss.subject_id = $1",
            )
        };
        let query = format!(
            r#"
            SELECT
              COALESCE((ss.metadata_json->>'legacy_fact_id')::bigint, 0) AS fact_id,
              '{direction}' AS direction,
              ss.property_id AS predicate,
              {neighbor_select},
              c.canonical_name AS neighbor_canonical_name,
              c.concept_type AS neighbor_concept_type,
              {} AS status,
              ss.confidence
            FROM semantic_statement ss
            JOIN ontology_concept c ON {concept_join}
            WHERE {concept_filter}
              AND ($2 = '' OR ss.property_id = $2)
              AND COALESCE(ss.metadata_json->>'statement_scope', '') <> 'aggregation'
              AND ss.status IN ({})
            ORDER BY ss.confidence DESC, ss.updated_at DESC
            LIMIT $3
            "#,
            semantic_statement_status_to_legacy_case("ss.status"),
            semantic_status_list_sql(SEMANTIC_ACTIVE_FACT_STATUSES),
        );

        sqlx::query(&query)
            .bind(concept_id)
            .bind(predicate)
            .bind(limit.max(1))
            .fetch_all(&self.pool)
            .await
    }

    async fn backfill_semantic_kernel_for_legacy_rows(
        &self,
        rows: &[PgRow],
    ) -> Result<(), sqlx::Error> {
        let fact_ids = rows
            .iter()
            .filter_map(|row| row.try_get::<i64, _>("fact_id").ok())
            .filter(|fact_id| *fact_id > 0)
            .collect::<Vec<_>>();
        if fact_ids.is_empty() {
            return Ok(());
        }

        let store = OntologyStore::from_pool(self.pool.clone());
        store
            .backfill_semantic_kernel_for_legacy_fact_ids(&fact_ids)
            .await?;
        Ok(())
    }

    async fn load_statement_ids_by_legacy_fact_rows(
        &self,
        rows: &[PgRow],
    ) -> Result<HashMap<i64, String>, sqlx::Error> {
        let fact_ids = rows
            .iter()
            .filter_map(|row| row.try_get::<i64, _>("fact_id").ok())
            .filter(|fact_id| *fact_id > 0)
            .collect::<Vec<_>>();
        if fact_ids.is_empty() {
            return Ok(HashMap::new());
        }

        let rows = sqlx::query(
            r#"
            SELECT
              (metadata_json->>'legacy_fact_id')::bigint AS fact_id,
              statement_id::text AS statement_id
            FROM semantic_statement
            WHERE metadata_json ? 'legacy_fact_id'
              AND (metadata_json->>'legacy_fact_id')::bigint = ANY($1)
            "#,
        )
        .bind(&fact_ids)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .filter_map(|row| {
                let fact_id = row.try_get::<i64, _>("fact_id").ok()?;
                let statement_id = row.try_get::<String, _>("statement_id").ok()?;
                Some((fact_id, statement_id))
            })
            .collect())
    }

    async fn backfill_semantic_projection_for_legacy_edges(
        &self,
        rows: &[PgRow],
    ) -> Result<(), sqlx::Error> {
        if rows.is_empty() {
            return Ok(());
        }

        let mut tx = self.pool.begin().await?;
        for row in rows {
            let src_concept_id = row.try_get::<String, _>("src_concept_id")?;
            let predicate = row.try_get::<String, _>("predicate")?;
            let dst_concept_id = row.try_get::<String, _>("dst_concept_id")?;
            let weight = row.try_get::<f64, _>("weight")?;

            ensure_semantic_item_entity_from_ontology_concept(&mut tx, &src_concept_id).await?;
            ensure_semantic_item_entity_from_ontology_concept(&mut tx, &dst_concept_id).await?;
            ensure_semantic_property_entity_from_relation_type(&mut tx, &predicate).await?;
            upsert_semantic_statement_for_edge(
                &mut tx,
                &src_concept_id,
                &predicate,
                &dst_concept_id,
                weight,
            )
            .await?;
        }
        tx.commit().await?;
        Ok(())
    }
}

async fn ensure_semantic_item_entity_from_ontology_concept(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    concept_id: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, namespace, status, metadata_json
        )
        SELECT
          concept_id,
          'item',
          'concept',
          'legacy_ontology',
          'active',
          jsonb_build_object(
            'legacy_concept_type', concept_type,
            'legacy_canonical_name', canonical_name,
            'legacy_aliases', aliases,
            'dual_write_source', 'ontology_edge'
          )
        FROM ontology_concept
        WHERE concept_id = $1
        ON CONFLICT (entity_id) DO UPDATE SET
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(concept_id)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn ensure_semantic_property_entity_from_relation_type(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    predicate: &str,
) -> Result<(), sqlx::Error> {
    let inserted = sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
        )
        SELECT
          predicate,
          'property',
          'object_property',
          'entity',
          'legacy_ontology',
          CASE WHEN enabled THEN 'active' ELSE 'deprecated' END,
          jsonb_build_object(
            'display_name', display_name,
            'description', description,
            'src_type_id', src_type_id,
            'dst_type_id', dst_type_id,
            'dual_write_source', 'ontology_edge'
          )
        FROM ontology_relation_type
        WHERE predicate = $1
        ON CONFLICT (entity_id) DO UPDATE SET
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(predicate)
    .execute(&mut **tx)
    .await?
    .rows_affected();

    if inserted == 0 {
        sqlx::query(
            r#"
            INSERT INTO semantic_entity (
              entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
            )
            VALUES (
              $1,
              'property',
              'annotation_property',
              'entity',
              'legacy_ontology',
              'active',
              jsonb_build_object('display_name', $1, 'dual_write_source', 'ontology_edge_fallback')
            )
            ON CONFLICT (entity_id) DO UPDATE SET
              metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
              updated_at = NOW()
            "#,
        )
        .bind(predicate)
        .execute(&mut **tx)
        .await?;
    }

    Ok(())
}

async fn upsert_semantic_statement_for_edge(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    src_concept_id: &str,
    predicate: &str,
    dst_concept_id: &str,
    weight: f64,
) -> Result<(), sqlx::Error> {
    let existing = sqlx::query(
        r#"
        SELECT statement_id
        FROM semantic_statement
        WHERE subject_id = $1
          AND property_id = $2
          AND value_type = 'entity'
          AND value_entity_id = $3
        ORDER BY
          CASE status
            WHEN 'accepted' THEN 0
            WHEN 'extracted' THEN 1
            WHEN 'reviewed' THEN 2
            ELSE 3
          END,
          updated_at DESC
        LIMIT 1
        "#,
    )
    .bind(src_concept_id)
    .bind(predicate)
    .bind(dst_concept_id)
    .fetch_optional(&mut **tx)
    .await?;

    if let Some(row) = existing {
        let statement_id: uuid::Uuid = row.get("statement_id");
        sqlx::query(
            r#"
            UPDATE semantic_statement
            SET confidence = GREATEST(confidence, $2),
                metadata_json = COALESCE(metadata_json, '{}'::jsonb)
                  || jsonb_build_object('dual_write_edge_source', 'ontology_edge', 'legacy_edge_weight', $3::double precision),
                updated_at = NOW()
            WHERE statement_id = $1
            "#,
        )
        .bind(statement_id)
        .bind(weight)
        .bind(weight)
        .execute(&mut **tx)
        .await?;
        return Ok(());
    }

    sqlx::query(
        r#"
        INSERT INTO semantic_statement (
          subject_id, property_id, value_type, value_entity_id, value_json,
          rank, status, confidence, created_by, metadata_json
        )
        VALUES (
          $1, $2, 'entity', $3, '{}'::jsonb,
          'normal', 'accepted', $4, 'legacy_ontology_edge',
          jsonb_build_object('dual_write_source', 'ontology_edge', 'legacy_edge_weight', $4::double precision)
        )
        "#,
    )
    .bind(src_concept_id)
    .bind(predicate)
    .bind(dst_concept_id)
    .bind(weight)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn upsert_semantic_entity_record(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    entity: &SemanticEntityUpsertInput,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (entity_id) DO UPDATE SET
          entity_kind = EXCLUDED.entity_kind,
          semantic_role = EXCLUDED.semantic_role,
          property_datatype = EXCLUDED.property_datatype,
          namespace = EXCLUDED.namespace,
          status = EXCLUDED.status,
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(&entity.entity_id)
    .bind(&entity.entity_kind)
    .bind(&entity.semantic_role)
    .bind(&entity.property_datatype)
    .bind(&entity.namespace)
    .bind(&entity.status)
    .bind(Json(entity.metadata_json.clone()))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn upsert_semantic_statement_record(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement: &SemanticStatementUpsertInput,
) -> Result<Uuid, sqlx::Error> {
    let statement_id = semantic_statement_uuid(&statement.statement_key);
    sqlx::query(
        r#"
        INSERT INTO semantic_statement (
          statement_id, subject_id, property_id, value_type, value_entity_id, value_json,
          rank, status, confidence, created_by, metadata_json
        )
        VALUES ($1, $2, $3, $4, $5, $6, 'normal', $7, $8, $9, $10)
        ON CONFLICT (statement_id) DO UPDATE SET
          subject_id = EXCLUDED.subject_id,
          property_id = EXCLUDED.property_id,
          value_type = EXCLUDED.value_type,
          value_entity_id = EXCLUDED.value_entity_id,
          value_json = EXCLUDED.value_json,
          rank = EXCLUDED.rank,
          status = EXCLUDED.status,
          confidence = EXCLUDED.confidence,
          created_by = EXCLUDED.created_by,
          metadata_json = EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(statement_id)
    .bind(&statement.subject_id)
    .bind(&statement.property_id)
    .bind(&statement.value_type)
    .bind(&statement.value_entity_id)
    .bind(Json(statement.value_json.clone()))
    .bind(&statement.status)
    .bind(statement.confidence)
    .bind(&statement.created_by)
    .bind(Json(statement.metadata_json.clone()))
    .execute(&mut **tx)
    .await?;
    Ok(statement_id)
}

fn semantic_statement_uuid(statement_key: &str) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("tdb.semantic_statement:{statement_key}").as_bytes(),
    )
}

fn semantic_reference_uuid(statement_key: &str, ordinal: i32) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("{statement_key}:{ordinal}:reference").as_bytes(),
    )
}

fn semantic_reference_claim_uuid(statement_key: &str, ordinal: i32) -> Uuid {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("{statement_key}:{ordinal}:claim").as_bytes(),
    )
}

async fn load_evidence_map(
    pool: &PgPool,
    evidence_ids: &[String],
) -> Result<HashMap<String, EvidenceRecord>, sqlx::Error> {
    let mut map = HashMap::new();
    for evidence_id in evidence_ids {
        let row = sqlx::query(
            r#"
            SELECT evidence_id::text AS evidence_id,
                   COALESCE(case_id::text, '') AS case_id,
                   COALESCE(event_seq, 0) AS event_seq,
                   source_kind,
                   source_id,
                   COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                   evidence_type,
                   evidence_role,
                   COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                   evidence_payload::text AS evidence_payload_json,
                   created_by_type,
                   created_by_id,
                   is_derived,
                   status,
                   created_at,
                   updated_at
            FROM evidence_record
            WHERE evidence_id = $1::uuid
            "#,
        )
        .bind(evidence_id)
        .fetch_optional(pool)
        .await?;
        if let Some(row) = row {
            map.insert(evidence_id.clone(), map_semantic_evidence_row(&row));
        }
    }
    Ok(map)
}

async fn load_evidence_locator_map(
    pool: &PgPool,
    evidence_ids: &[String],
) -> Result<HashMap<String, Vec<EvidenceLocatorRecord>>, sqlx::Error> {
    let mut map = HashMap::new();
    for evidence_id in evidence_ids {
        let rows = sqlx::query(
            r#"
            SELECT evidence_locator_id::text AS evidence_locator_id,
                   evidence_id::text AS evidence_id,
                   locator_type,
                   COALESCE(page_span::text, '') AS page_span,
                   COALESCE(char_span::text, '') AS char_span,
                   COALESCE(sentence_ref::text, '') AS sentence_ref_json,
                   COALESCE(bbox::text, '') AS bbox_json,
                   COALESCE(polygon::text, '') AS polygon_json,
                   COALESCE(time_range::text, '') AS time_range,
                   COALESCE(table_cell::text, '') AS table_cell_json,
                   COALESCE(measurement_field, '') AS measurement_field,
                   COALESCE(locator_payload::text, '') AS locator_payload_json,
                   COALESCE(normalized_text, '') AS normalized_text,
                   COALESCE(preview_text, '') AS preview_text,
                   created_at
            FROM evidence_locator
            WHERE evidence_id = $1::uuid
            ORDER BY created_at ASC
            "#,
        )
        .bind(evidence_id)
        .fetch_all(pool)
        .await?;
        map.insert(
            evidence_id.clone(),
            rows.iter().map(map_semantic_evidence_locator_row).collect(),
        );
    }
    Ok(map)
}

fn map_object_type_row(row: &sqlx::postgres::PgRow) -> OntologyObjectTypeRecord {
    OntologyObjectTypeRecord {
        type_id: row.get("type_id"),
        display_name: row.get("display_name"),
        description: row.get("description"),
        enabled: row.get("enabled"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_concept_type_assignment_row(
    row: &sqlx::postgres::PgRow,
) -> OntologyConceptTypeAssignmentRecord {
    OntologyConceptTypeAssignmentRecord {
        assignment_id: row.get("assignment_id"),
        domain: row.get("domain"),
        concept_id: row.get("concept_id"),
        object_type_id: row.get("object_type_id"),
        assignment_status: row.get("assignment_status"),
        source_kind: row.get("source_kind"),
        confidence: row.get("confidence"),
        metadata_json: row.get("metadata_json"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_relation_type_row(row: &sqlx::postgres::PgRow) -> OntologyRelationTypeRecord {
    OntologyRelationTypeRecord {
        predicate: row.get("predicate"),
        src_type_id: row.get("src_type_id"),
        dst_type_id: row.get("dst_type_id"),
        display_name: row.get("display_name"),
        description: row.get("description"),
        is_symmetric: row.get("is_symmetric"),
        is_transitive: row.get("is_transitive"),
        enabled: row.get("enabled"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_fact_row(row: &sqlx::postgres::PgRow) -> OntologyFactRecord {
    map_fact_row_with_statement_id(row, None)
}

fn map_fact_row_with_statement_id(
    row: &sqlx::postgres::PgRow,
    statement_id_override: Option<String>,
) -> OntologyFactRecord {
    OntologyFactRecord {
        fact_id: row.get("fact_id"),
        src_concept_id: row.get("src_concept_id"),
        predicate: row.get("predicate"),
        dst_concept_id: row.get("dst_concept_id"),
        qualifier_json: row
            .get::<Option<String>, _>("qualifier_json")
            .unwrap_or_else(|| "{}".into()),
        confidence: row.get::<f64, _>("confidence") as _,
        extractor: row.get("extractor"),
        status: row.get("status"),
        review_note: row.get("review_note"),
        valid_from: row.get("valid_from"),
        valid_to: row.get("valid_to"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
        stream_id: String::new(),
        stale_fact_count: 0,
        fact_count: 0,
        dst_count: 0,
        fact_ids: vec![],
        dst_values: vec![],
        src_concept_label: row
            .try_get::<String, _>("src_concept_label")
            .unwrap_or_default(),
        dst_concept_label: row
            .try_get::<String, _>("dst_concept_label")
            .unwrap_or_default(),
        statement_id: statement_id_override.unwrap_or_else(|| {
            row.try_get::<String, _>("statement_id")
                .unwrap_or_default()
        }),
    }
}

fn map_term_mapping_registry_row(row: &sqlx::postgres::PgRow) -> TermMappingRegistryRecord {
    TermMappingRegistryRecord {
        registry_id: row.get("registry_id"),
        domain: row.get("domain"),
        registry_name: row.get("registry_name"),
        version_label: row.get("version_label"),
        status: row.get("status"),
        description: row.get("description"),
        owner: row.get("owner"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_term_mapping_rule_row(row: &sqlx::postgres::PgRow) -> TermMappingRuleRecord {
    TermMappingRuleRecord {
        rule_id: row.get("rule_id"),
        registry_id: row.get("registry_id"),
        raw_term: row.get("raw_term"),
        language: row.get("language"),
        context_hint: row.get("context_hint"),
        term_type: row.get("term_type"),
        normalization_status: row.get("normalization_status"),
        canonical_term: row.get("canonical_term"),
        canonical_concept_id: row.get("canonical_concept_id"),
        is_compound: row.get("is_compound"),
        split_rule_json: row
            .get::<Option<String>, _>("split_rule_json")
            .unwrap_or_else(|| "{}".into()),
        semantic_slot: row.get("semantic_slot"),
        json_targets_json: row
            .get::<Option<String>, _>("json_targets_json")
            .unwrap_or_else(|| "[]".into()),
        ontology_target_kind: row.get("ontology_target_kind"),
        ambiguity_flag: row.get("ambiguity_flag"),
        ambiguity_note: row.get("ambiguity_note"),
        review_status: row.get("review_status"),
        confidence: row.get::<f64, _>("confidence") as _,
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_term_mapping_rule_evidence_row(
    row: &sqlx::postgres::PgRow,
) -> TermMappingRuleEvidenceRecord {
    TermMappingRuleEvidenceRecord {
        rule_evidence_id: row.get("rule_evidence_id"),
        rule_id: row.get("rule_id"),
        artifact_id: row.get("artifact_id"),
        artifact_version_id: row.get("artifact_version_id"),
        event_id: row.get("event_id"),
        memory_decision_id: row.get("memory_decision_id"),
        source_span: row.get("source_span"),
        note: row.get("note"),
        confidence: row.get::<f64, _>("confidence") as _,
        evidence_json: row
            .get::<Option<String>, _>("evidence_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_term_mapping_interpretation_row(
    row: &sqlx::postgres::PgRow,
) -> TermMappingInterpretationRecord {
    TermMappingInterpretationRecord {
        found: true,
        raw_term: row.get("raw_term"),
        matched_rule_id: row.get("rule_id"),
        registry_id: row.get("registry_id"),
        language: row.get("language"),
        term_type: row.get("term_type"),
        normalization_status: row.get("normalization_status"),
        canonical_term: row.get("canonical_term"),
        canonical_concept_id: row.get("canonical_concept_id"),
        is_compound: row.get("is_compound"),
        split_rule_json: row
            .get::<Option<String>, _>("split_rule_json")
            .unwrap_or_else(|| "{}".into()),
        semantic_slot: row.get("semantic_slot"),
        json_targets_json: row
            .get::<Option<String>, _>("json_targets_json")
            .unwrap_or_else(|| "[]".into()),
        ontology_target_kind: row.get("ontology_target_kind"),
        ambiguity_flag: row.get("ambiguity_flag"),
        ambiguity_note: row.get("ambiguity_note"),
        review_status: row.get("review_status"),
        confidence: row.get::<f64, _>("confidence") as _,
    }
}

fn map_ontology_raw_term_row(row: &sqlx::postgres::PgRow) -> OntologyRawTermRecord {
    OntologyRawTermRecord {
        raw_term_id: row.get("raw_term_id"),
        domain: row.get("domain"),
        raw_term: row.get("raw_term"),
        language: row.get("language"),
        normalized_hint: row.get("normalized_hint"),
        term_type_hint: row.get("term_type_hint"),
        source_kind: row.get("source_kind"),
        source_ref: row.get("source_ref"),
        artifact_version_id: row.get("artifact_version_id"),
        evidence_id: row.get("evidence_id"),
        context_text: row.get("context_text"),
        context_locator_json: row
            .get::<Option<String>, _>("context_locator_json")
            .unwrap_or_else(|| "{}".into()),
        extracted_by_type: row.get("extracted_by_type"),
        extracted_by_id: row.get("extracted_by_id"),
        status: row.get("status"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_raw_term_candidate_row(
    row: &sqlx::postgres::PgRow,
) -> OntologyRawTermCandidateRecord {
    OntologyRawTermCandidateRecord {
        candidate_id: row.get("candidate_id"),
        raw_term_id: row.get("raw_term_id"),
        candidate_label: row.get("candidate_label"),
        candidate_concept_id: row.get("candidate_concept_id"),
        candidate_object_type: row.get("candidate_object_type"),
        candidate_relation_type: row.get("candidate_relation_type"),
        confidence: row.get::<f64, _>("confidence") as _,
        candidate_status: row.get("candidate_status"),
        review_note: row.get("review_note"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_normalized_term_row(row: &sqlx::postgres::PgRow) -> OntologyNormalizedTermRecord {
    OntologyNormalizedTermRecord {
        normalized_term_id: row.get("normalized_term_id"),
        domain: row.get("domain"),
        normalized_surface: row.get("normalized_surface"),
        normalized_type: row.get("normalized_type"),
        merge_key: row.get("merge_key"),
        type_confidence: row.get::<f64, _>("type_confidence") as _,
        head_term: row.get("head_term"),
        modifier_terms_json: row
            .get::<Option<String>, _>("modifier_terms_json")
            .unwrap_or_else(|| "[]".into()),
        canonical_candidate_label: row.get("canonical_candidate_label"),
        canonical_candidate_concept_id: row.get("canonical_candidate_concept_id"),
        primary_cluster_id: row.get("primary_cluster_id"),
        source_support_count: row.get("source_support_count"),
        is_promotable: row.get("is_promotable"),
        normalization_status: row.get("normalization_status"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_term_cluster_row(row: &sqlx::postgres::PgRow) -> OntologyTermClusterRecord {
    OntologyTermClusterRecord {
        cluster_id: row.get("cluster_id"),
        domain: row.get("domain"),
        cluster_type: row.get("cluster_type"),
        proposed_canonical: row.get("proposed_canonical"),
        proposed_type: row.get("proposed_type"),
        cluster_status: row.get("cluster_status"),
        member_count: row.get("member_count"),
        source_support_count: row.get("source_support_count"),
        confidence: row.get::<f64, _>("confidence") as _,
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_cluster_member_row(row: &sqlx::postgres::PgRow) -> OntologyClusterMemberRecord {
    OntologyClusterMemberRecord {
        cluster_member_id: row.get("cluster_member_id"),
        cluster_id: row.get("cluster_id"),
        normalized_term_id: row.get("normalized_term_id"),
        member_role: row.get("member_role"),
        membership_confidence: row.get::<f64, _>("membership_confidence") as _,
        added_by: row.get("added_by"),
        note: row.get("note"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_relation_candidate_row(
    row: &sqlx::postgres::PgRow,
) -> OntologyRelationCandidateRecord {
    OntologyRelationCandidateRecord {
        relation_candidate_id: row.get("relation_candidate_id"),
        domain: row.get("domain"),
        subject_label: row.get("subject_label"),
        relation_type: row.get("relation_type"),
        object_label: row.get("object_label"),
        subject_concept_id: row
            .get::<Option<String>, _>("subject_concept_id")
            .unwrap_or_default(),
        object_concept_id: row
            .get::<Option<String>, _>("object_concept_id")
            .unwrap_or_default(),
        candidate_status: row.get("candidate_status"),
        source_kind: row.get("source_kind"),
        source_cluster_id: row
            .get::<Option<String>, _>("source_cluster_id")
            .unwrap_or_default(),
        confidence: row.get::<f64, _>("confidence") as _,
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_ontology_raw_term_normalization_row(
    row: &sqlx::postgres::PgRow,
) -> OntologyRawTermNormalizationRecord {
    OntologyRawTermNormalizationRecord {
        mapping_id: row.get("mapping_id"),
        raw_term_id: row.get("raw_term_id"),
        normalized_term_id: row.get("normalized_term_id"),
        mapping_confidence: row.get::<f64, _>("mapping_confidence") as _,
        mapping_type: row.get("mapping_type"),
        mapping_status: row.get("mapping_status"),
        component_role: row.get("component_role"),
        normalization_rule: row.get("normalization_rule"),
        note: row.get("note"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".into()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_semantic_statement_row(row: &sqlx::postgres::PgRow) -> SemanticStatementRecord {
    SemanticStatementRecord {
        statement_id: row.get("statement_id"),
        subject_concept_id: row.get("subject_concept_id"),
        subject_name: row.get("subject_name"),
        predicate: row.get("predicate"),
        object_concept_id: row.get("object_concept_id"),
        object_name: row.get("object_name"),
        value_type: row.get("value_type"),
        value_json: row.get("value_json"),
        confidence: row.get("confidence"),
        status: row.get("status"),
        created_by: row.get("created_by"),
        metadata_json: row.get("metadata_json"),
        provenance_json: row.get("provenance_json"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_semantic_statement_qualifier_row(
    row: &sqlx::postgres::PgRow,
) -> SemanticStatementQualifierRecord {
    SemanticStatementQualifierRecord {
        statement_id: row.get("statement_id"),
        property_id: row.get("property_id"),
        value_type: row.get("value_type"),
        value_entity_id: row.get("value_entity_id"),
        value_json: row.get("value_json"),
        ordinal: row.get("ordinal"),
    }
}

fn map_semantic_statement_reference_row(
    row: &sqlx::postgres::PgRow,
    evidence_map: &HashMap<String, EvidenceRecord>,
    locator_map: &HashMap<String, Vec<EvidenceLocatorRecord>>,
) -> SemanticStatementReferenceRecord {
    let evidence_id = extract_reference_evidence_id(row).unwrap_or_default();
    SemanticStatementReferenceRecord {
        statement_id: row.get("statement_id"),
        property_id: row.get("property_id"),
        value_type: row.get("value_type"),
        value_json: row.get("value_json"),
        evidence_id: evidence_id.clone(),
        source_span: row.get("source_span"),
        ordinal: row.get("ordinal"),
        evidence: evidence_map.get(&evidence_id).cloned(),
        locators: locator_map.get(&evidence_id).cloned().unwrap_or_default(),
    }
}

fn collect_reference_evidence_ids(rows: &[sqlx::postgres::PgRow]) -> Vec<String> {
    let mut evidence_ids = Vec::new();
    for row in rows {
        if let Some(evidence_id) = extract_reference_evidence_id(row) {
            if !evidence_ids.contains(&evidence_id) {
                evidence_ids.push(evidence_id);
            }
        }
    }
    evidence_ids
}

fn extract_reference_evidence_id(row: &sqlx::postgres::PgRow) -> Option<String> {
    let direct = row
        .try_get::<String, _>("evidence_id")
        .ok()
        .filter(|value| !value.is_empty());
    if direct.is_some() {
        return direct;
    }

    let property_id = row.try_get::<String, _>("property_id").ok()?;
    if property_id != SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID {
        return None;
    }

    let value_json = row.try_get::<String, _>("value_json").ok()?;
    let parsed = serde_json::from_str::<Value>(&value_json).ok()?;
    parsed
        .get("evidence_json")
        .and_then(|value| value.get("tdb_evidence_id"))
        .and_then(|value| value.as_str())
        .filter(|value| !value.is_empty())
        .map(ToOwned::to_owned)
}

fn map_semantic_evidence_row(row: &sqlx::postgres::PgRow) -> EvidenceRecord {
    EvidenceRecord {
        evidence_id: row.get("evidence_id"),
        case_id: row.get("case_id"),
        event_seq: row.get("event_seq"),
        source_kind: row.get("source_kind"),
        source_id: row.get("source_id"),
        artifact_version_id: row.get("artifact_version_id"),
        evidence_type: row.get("evidence_type"),
        evidence_role: row.get("evidence_role"),
        methodology_framework_id: row.get("methodology_framework_id"),
        evidence_payload_json: row.get("evidence_payload_json"),
        created_by_type: row.get("created_by_type"),
        created_by_id: row.get("created_by_id"),
        is_derived: row.get("is_derived"),
        status: row.get("status"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_semantic_evidence_locator_row(row: &sqlx::postgres::PgRow) -> EvidenceLocatorRecord {
    EvidenceLocatorRecord {
        evidence_locator_id: row.get("evidence_locator_id"),
        evidence_id: row.get("evidence_id"),
        locator_type: row.get("locator_type"),
        page_span: row.get("page_span"),
        char_span: row.get("char_span"),
        sentence_ref_json: row.get("sentence_ref_json"),
        bbox_json: row.get("bbox_json"),
        polygon_json: row.get("polygon_json"),
        time_range: row.get("time_range"),
        table_cell_json: row.get("table_cell_json"),
        measurement_field: row.get("measurement_field"),
        locator_payload_json: row.get("locator_payload_json"),
        normalized_text: row.get("normalized_text"),
        preview_text: row.get("preview_text"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

#[cfg(test)]
mod tests {
    use super::{
        ListOntologyEdgesRequest, SemanticFactQueryOptions, build_semantic_edge_projection_query,
        build_semantic_fact_projection_query,
    };

    #[test]
    fn semantic_fact_projection_excludes_aggregation_scope() {
        let (query, _, _, _) = build_semantic_fact_projection_query(&SemanticFactQueryOptions {
            status: "all",
            stream_id: "",
            stream_prefix: false,
            predicate: "",
            extractor: "",
            src_concept_id: "",
            dst_concept_id: "",
            query: "",
            limit: 10,
            offset: 0,
        });

        assert!(query.contains("statement_scope"));
        assert!(query.contains("aggregation"));
    }

    #[test]
    fn semantic_edge_projection_excludes_aggregation_scope() {
        let (query, _, _) = build_semantic_edge_projection_query(&ListOntologyEdgesRequest {
            src_concept_id: String::new(),
            predicate: String::new(),
            dst_concept_id: String::new(),
            limit: 10,
        });

        assert!(query.contains("statement_scope"));
        assert!(query.contains("aggregation"));
    }
}
