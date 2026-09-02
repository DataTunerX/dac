use sqlx::PgPool;

use crate::rpc::proto::{
    AssertionEvidenceLinkRecord, AssertionRecord, AssertionRelationRecord, GetAssertionRequest,
    GetAssertionResponse, ListAssertionEvidenceLinksRequest, ListAssertionEvidenceLinksResponse,
    ListAssertionRelationsRequest, ListAssertionRelationsResponse, SearchAssertionsRequest,
    SearchAssertionsResponse, UpsertAssertionEvidenceLinkRequest,
    UpsertAssertionEvidenceLinkResponse, UpsertAssertionRelationRequest,
    UpsertAssertionRelationResponse, UpsertAssertionRequest, UpsertAssertionResponse,
};

#[derive(Debug, Clone)]
pub struct AssertionStore {
    pool: PgPool,
}

impl AssertionStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_assertion(
        &self,
        req: UpsertAssertionRequest,
    ) -> Result<UpsertAssertionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO assertion (
              assertion_id, case_id, subject_type, subject_id, predicate, object_type, object_id,
              object_literal, assertion_type, asserted_by_type, asserted_by_id, confidence,
              status, methodology_framework_id, source_event_id, metadata
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              NULLIF($2, '')::uuid,
              $3,
              $4::uuid,
              $5,
              $6,
              NULLIF($7, '')::uuid,
              CASE WHEN $8 = '' THEN NULL ELSE $8::jsonb END,
              $9,
              $10,
              $11,
              CASE WHEN $12 < 0 THEN NULL ELSE $12::double precision END,
              $13,
              NULLIF($14, '')::uuid,
              NULLIF($15, '')::uuid,
              CASE WHEN $16 = '' THEN '{}'::jsonb ELSE $16::jsonb END
            )
            ON CONFLICT (assertion_id) DO UPDATE SET
              case_id = EXCLUDED.case_id,
              subject_type = EXCLUDED.subject_type,
              subject_id = EXCLUDED.subject_id,
              predicate = EXCLUDED.predicate,
              object_type = EXCLUDED.object_type,
              object_id = EXCLUDED.object_id,
              object_literal = EXCLUDED.object_literal,
              assertion_type = EXCLUDED.assertion_type,
              asserted_by_type = EXCLUDED.asserted_by_type,
              asserted_by_id = EXCLUDED.asserted_by_id,
              confidence = EXCLUDED.confidence,
              status = EXCLUDED.status,
              methodology_framework_id = EXCLUDED.methodology_framework_id,
              source_event_id = EXCLUDED.source_event_id,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING assertion_id::text AS assertion_id,
                      COALESCE(case_id::text, '') AS case_id,
                      subject_type,
                      subject_id::text AS subject_id,
                      predicate,
                      object_type,
                      COALESCE(object_id::text, '') AS object_id,
                      COALESCE(object_literal::text, '') AS object_literal_json,
                      assertion_type,
                      asserted_by_type,
                      asserted_by_id,
                      COALESCE(confidence, 0.0) AS confidence,
                      status,
                      COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                      COALESCE(source_event_id::text, '') AS source_event_id,
                      metadata::text AS metadata_json,
                      created_at::text,
                      updated_at::text
            "#,
        )
        .bind(&req.assertion_id)
        .bind(&req.case_id)
        .bind(&req.subject_type)
        .bind(&req.subject_id)
        .bind(&req.predicate)
        .bind(&req.object_type)
        .bind(&req.object_id)
        .bind(&req.object_literal_json)
        .bind(&req.assertion_type)
        .bind(&req.asserted_by_type)
        .bind(&req.asserted_by_id)
        .bind(req.confidence)
        .bind(&req.status)
        .bind(&req.methodology_framework_id)
        .bind(&req.source_event_id)
        .bind(&req.metadata_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertAssertionResponse {
            assertion: Some(map_assertion_row(&row)),
        })
    }

    pub async fn get_assertion(
        &self,
        req: GetAssertionRequest,
    ) -> Result<GetAssertionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT assertion_id::text AS assertion_id,
                   COALESCE(case_id::text, '') AS case_id,
                   subject_type,
                   subject_id::text AS subject_id,
                   predicate,
                   object_type,
                   COALESCE(object_id::text, '') AS object_id,
                   COALESCE(object_literal::text, '') AS object_literal_json,
                   assertion_type,
                   asserted_by_type,
                   asserted_by_id,
                   COALESCE(confidence, 0.0) AS confidence,
                   status,
                   COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                   COALESCE(source_event_id::text, '') AS source_event_id,
                   metadata::text AS metadata_json,
                   created_at::text,
                   updated_at::text
            FROM assertion
            WHERE assertion_id = $1::uuid
            "#,
        )
        .bind(&req.assertion_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetAssertionResponse {
            assertion: row.as_ref().map(map_assertion_row),
        })
    }

    pub async fn search_assertions(
        &self,
        req: SearchAssertionsRequest,
    ) -> Result<SearchAssertionsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT assertion_id::text AS assertion_id,
                   COALESCE(case_id::text, '') AS case_id,
                   subject_type,
                   subject_id::text AS subject_id,
                   predicate,
                   object_type,
                   COALESCE(object_id::text, '') AS object_id,
                   COALESCE(object_literal::text, '') AS object_literal_json,
                   assertion_type,
                   asserted_by_type,
                   asserted_by_id,
                   COALESCE(confidence, 0.0) AS confidence,
                   status,
                   COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                   COALESCE(source_event_id::text, '') AS source_event_id,
                   metadata::text AS metadata_json,
                   created_at::text,
                   updated_at::text
            FROM assertion
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();

        if !req.case_id.is_empty() {
            query.push_str(&format!(" AND case_id = ${}::uuid", binds.len() + 1));
            binds.push(req.case_id);
        }
        if !req.subject_type.is_empty() {
            query.push_str(&format!(" AND subject_type = ${}", binds.len() + 1));
            binds.push(req.subject_type);
        }
        if !req.subject_id.is_empty() {
            query.push_str(&format!(" AND subject_id = ${}::uuid", binds.len() + 1));
            binds.push(req.subject_id);
        }
        if !req.predicate.is_empty() {
            query.push_str(&format!(" AND predicate = ${}", binds.len() + 1));
            binds.push(req.predicate);
        }
        if !req.assertion_type.is_empty() {
            query.push_str(&format!(" AND assertion_type = ${}", binds.len() + 1));
            binds.push(req.assertion_type);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.methodology_framework_id.is_empty() {
            query.push_str(&format!(
                " AND methodology_framework_id = ${}::uuid",
                binds.len() + 1
            ));
            binds.push(req.methodology_framework_id);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (predicate ILIKE ${idx} OR assertion_type ILIKE ${idx} OR status ILIKE ${idx})"));
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
        Ok(SearchAssertionsResponse {
            assertions: rows.iter().map(map_assertion_row).collect(),
        })
    }

    pub async fn upsert_assertion_evidence_link(
        &self,
        req: UpsertAssertionEvidenceLinkRequest,
    ) -> Result<UpsertAssertionEvidenceLinkResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO assertion_evidence_link (
              assertion_evidence_link_id, assertion_id, evidence_id, artifact_version_id, event_id, memory_decision_id,
              support_type, weight, note, evidence_json
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid,
              NULLIF($3, '')::uuid,
              NULLIF($4, '')::uuid,
              NULLIF($5, '')::uuid,
              NULLIF($6, '')::uuid,
              $7,
              CASE WHEN $8 < 0 THEN NULL ELSE $8::double precision END,
              $9,
              CASE WHEN $10 = '' THEN '{}'::jsonb ELSE $10::jsonb END
            )
            ON CONFLICT (assertion_evidence_link_id) DO UPDATE SET
              assertion_id = EXCLUDED.assertion_id,
              evidence_id = EXCLUDED.evidence_id,
              artifact_version_id = EXCLUDED.artifact_version_id,
              event_id = EXCLUDED.event_id,
              memory_decision_id = EXCLUDED.memory_decision_id,
              support_type = EXCLUDED.support_type,
              weight = EXCLUDED.weight,
              note = EXCLUDED.note,
              evidence_json = EXCLUDED.evidence_json
            RETURNING assertion_evidence_link_id::text AS assertion_evidence_link_id,
                      assertion_id::text AS assertion_id,
                      COALESCE(evidence_id::text, '') AS evidence_id,
                      COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                      COALESCE(event_id::text, '') AS event_id,
                      COALESCE(memory_decision_id::text, '') AS memory_decision_id,
                      support_type,
                      COALESCE(weight, 0.0) AS weight,
                      note,
                      evidence_json::text AS evidence_json,
                      created_at::text
            "#,
        )
        .bind(&req.assertion_evidence_link_id)
        .bind(&req.assertion_id)
        .bind(&req.evidence_id)
        .bind(&req.artifact_version_id)
        .bind(&req.event_id)
        .bind(&req.memory_decision_id)
        .bind(&req.support_type)
        .bind(req.weight)
        .bind(&req.note)
        .bind(&req.evidence_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertAssertionEvidenceLinkResponse {
            evidence_link: Some(map_assertion_evidence_link_row(&row)),
        })
    }

    pub async fn list_assertion_evidence_links(
        &self,
        req: ListAssertionEvidenceLinksRequest,
    ) -> Result<ListAssertionEvidenceLinksResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT assertion_evidence_link_id::text AS assertion_evidence_link_id,
                   assertion_id::text AS assertion_id,
                   COALESCE(evidence_id::text, '') AS evidence_id,
                   COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                   COALESCE(event_id::text, '') AS event_id,
                   COALESCE(memory_decision_id::text, '') AS memory_decision_id,
                   support_type,
                   COALESCE(weight, 0.0) AS weight,
                   note,
                   evidence_json::text AS evidence_json,
                   created_at::text
            FROM assertion_evidence_link
            WHERE assertion_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            "#,
        )
        .bind(&req.assertion_id)
        .bind(if req.limit > 0 { req.limit } else { 50 })
        .bind(req.offset)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListAssertionEvidenceLinksResponse {
            evidence_links: rows.iter().map(map_assertion_evidence_link_row).collect(),
        })
    }

    pub async fn upsert_assertion_relation(
        &self,
        req: UpsertAssertionRelationRequest,
    ) -> Result<UpsertAssertionRelationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO assertion_relation (
              assertion_relation_id, from_assertion_id, to_assertion_id, relation_type, metadata
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid,
              $3::uuid,
              $4,
              CASE WHEN $5 = '' THEN '{}'::jsonb ELSE $5::jsonb END
            )
            ON CONFLICT (assertion_relation_id) DO UPDATE SET
              from_assertion_id = EXCLUDED.from_assertion_id,
              to_assertion_id = EXCLUDED.to_assertion_id,
              relation_type = EXCLUDED.relation_type,
              metadata = EXCLUDED.metadata
            RETURNING assertion_relation_id::text AS assertion_relation_id,
                      from_assertion_id::text AS from_assertion_id,
                      to_assertion_id::text AS to_assertion_id,
                      relation_type,
                      metadata::text AS metadata_json,
                      created_at::text
            "#,
        )
        .bind(&req.assertion_relation_id)
        .bind(&req.from_assertion_id)
        .bind(&req.to_assertion_id)
        .bind(&req.relation_type)
        .bind(&req.metadata_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertAssertionRelationResponse {
            relation: Some(map_assertion_relation_row(&row)),
        })
    }

    pub async fn list_assertion_relations(
        &self,
        req: ListAssertionRelationsRequest,
    ) -> Result<ListAssertionRelationsResponse, sqlx::Error> {
        let direction = if req.direction.is_empty() {
            "both".to_string()
        } else {
            req.direction.to_lowercase()
        };
        let rows = match direction.as_str() {
            "incoming" => {
                sqlx::query(
                    r#"
                    SELECT assertion_relation_id::text AS assertion_relation_id,
                           from_assertion_id::text AS from_assertion_id,
                           to_assertion_id::text AS to_assertion_id,
                           relation_type,
                           metadata::text AS metadata_json,
                           created_at::text
                    FROM assertion_relation
                    WHERE to_assertion_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.assertion_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
            "outgoing" => {
                sqlx::query(
                    r#"
                    SELECT assertion_relation_id::text AS assertion_relation_id,
                           from_assertion_id::text AS from_assertion_id,
                           to_assertion_id::text AS to_assertion_id,
                           relation_type,
                           metadata::text AS metadata_json,
                           created_at::text
                    FROM assertion_relation
                    WHERE from_assertion_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.assertion_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
            _ => {
                sqlx::query(
                    r#"
                    SELECT assertion_relation_id::text AS assertion_relation_id,
                           from_assertion_id::text AS from_assertion_id,
                           to_assertion_id::text AS to_assertion_id,
                           relation_type,
                           metadata::text AS metadata_json,
                           created_at::text
                    FROM assertion_relation
                    WHERE from_assertion_id = $1::uuid OR to_assertion_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.assertion_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
        };

        Ok(ListAssertionRelationsResponse {
            relations: rows.iter().map(map_assertion_relation_row).collect(),
        })
    }
}

fn map_assertion_row(row: &sqlx::postgres::PgRow) -> AssertionRecord {
    use sqlx::Row;
    AssertionRecord {
        assertion_id: row.get("assertion_id"),
        case_id: row.get("case_id"),
        subject_type: row.get("subject_type"),
        subject_id: row.get("subject_id"),
        predicate: row.get("predicate"),
        object_type: row.get("object_type"),
        object_id: row.get("object_id"),
        object_literal_json: row
            .get::<Option<String>, _>("object_literal_json")
            .unwrap_or_default(),
        assertion_type: row.get("assertion_type"),
        asserted_by_type: row.get("asserted_by_type"),
        asserted_by_id: row.get("asserted_by_id"),
        confidence: row.get::<f64, _>("confidence") as f32,
        status: row.get("status"),
        methodology_framework_id: row.get("methodology_framework_id"),
        source_event_id: row.get("source_event_id"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_assertion_evidence_link_row(row: &sqlx::postgres::PgRow) -> AssertionEvidenceLinkRecord {
    use sqlx::Row;
    AssertionEvidenceLinkRecord {
        assertion_evidence_link_id: row.get("assertion_evidence_link_id"),
        assertion_id: row.get("assertion_id"),
        evidence_id: row.get("evidence_id"),
        artifact_version_id: row.get("artifact_version_id"),
        event_id: row.get("event_id"),
        memory_decision_id: row.get("memory_decision_id"),
        support_type: row.get("support_type"),
        weight: row.get::<f64, _>("weight") as f32,
        note: row.get("note"),
        evidence_json: row
            .get::<Option<String>, _>("evidence_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row.get("created_at"),
    }
}

fn map_assertion_relation_row(row: &sqlx::postgres::PgRow) -> AssertionRelationRecord {
    use sqlx::Row;
    AssertionRelationRecord {
        assertion_relation_id: row.get("assertion_relation_id"),
        from_assertion_id: row.get("from_assertion_id"),
        to_assertion_id: row.get("to_assertion_id"),
        relation_type: row.get("relation_type"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row.get("created_at"),
    }
}
