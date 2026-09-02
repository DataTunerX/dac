use sqlx::{PgPool, Row};

use crate::rpc::proto::{
    EvidenceClassificationRecord, EvidenceDerivationRecord, EvidenceLocatorRecord, EvidenceRecord,
    GetEvidenceClassificationRequest, GetEvidenceClassificationResponse, GetEvidenceRequest,
    GetEvidenceResponse, ListEvidenceDerivationsRequest, ListEvidenceDerivationsResponse,
    ListEvidenceLocatorsRequest, ListEvidenceLocatorsResponse, SearchEvidenceRequest,
    SearchEvidenceResponse, UpsertEvidenceClassificationRequest,
    UpsertEvidenceClassificationResponse, UpsertEvidenceDerivationRequest,
    UpsertEvidenceDerivationResponse, UpsertEvidenceLocatorRequest, UpsertEvidenceLocatorResponse,
    UpsertEvidenceRequest, UpsertEvidenceResponse,
};

#[derive(Debug, Clone)]
pub struct EvidenceStore {
    pool: PgPool,
}

impl EvidenceStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_evidence(
        &self,
        req: UpsertEvidenceRequest,
    ) -> Result<UpsertEvidenceResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO evidence_record (
              evidence_id, case_id, event_seq, source_kind, source_id, artifact_version_id,
              evidence_type, evidence_role, methodology_framework_id, evidence_payload,
              created_by_type, created_by_id, is_derived, status
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              NULLIF($2, '')::uuid,
              CASE WHEN $3 <= 0 THEN NULL ELSE $3::bigint END,
              $4,
              $5,
              NULLIF($6, '')::uuid,
              $7,
              $8,
              NULLIF($9, '')::uuid,
              CASE WHEN $10 = '' THEN '{}'::jsonb ELSE $10::jsonb END,
              $11,
              $12,
              $13,
              $14
            )
            ON CONFLICT (evidence_id) DO UPDATE SET
              case_id = EXCLUDED.case_id,
              event_seq = EXCLUDED.event_seq,
              source_kind = EXCLUDED.source_kind,
              source_id = EXCLUDED.source_id,
              artifact_version_id = EXCLUDED.artifact_version_id,
              evidence_type = EXCLUDED.evidence_type,
              evidence_role = EXCLUDED.evidence_role,
              methodology_framework_id = EXCLUDED.methodology_framework_id,
              evidence_payload = EXCLUDED.evidence_payload,
              created_by_type = EXCLUDED.created_by_type,
              created_by_id = EXCLUDED.created_by_id,
              is_derived = EXCLUDED.is_derived,
              status = EXCLUDED.status,
              updated_at = NOW()
            RETURNING evidence_id::text AS evidence_id,
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
                      created_at::text AS created_at,
                      updated_at::text AS updated_at
            "#,
        )
        .bind(&req.evidence_id)
        .bind(&req.case_id)
        .bind(req.event_seq)
        .bind(&req.source_kind)
        .bind(&req.source_id)
        .bind(&req.artifact_version_id)
        .bind(&req.evidence_type)
        .bind(&req.evidence_role)
        .bind(&req.methodology_framework_id)
        .bind(&req.evidence_payload_json)
        .bind(&req.created_by_type)
        .bind(&req.created_by_id)
        .bind(req.is_derived)
        .bind(&req.status)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEvidenceResponse {
            evidence: Some(map_evidence_row(&row)),
        })
    }

    pub async fn get_evidence(
        &self,
        req: GetEvidenceRequest,
    ) -> Result<GetEvidenceResponse, sqlx::Error> {
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
                   created_at::text AS created_at,
                   updated_at::text AS updated_at
            FROM evidence_record
            WHERE evidence_id = $1::uuid
            "#,
        )
        .bind(&req.evidence_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetEvidenceResponse {
            evidence: row.as_ref().map(map_evidence_row),
        })
    }

    pub async fn search_evidence(
        &self,
        req: SearchEvidenceRequest,
    ) -> Result<SearchEvidenceResponse, sqlx::Error> {
        let mut query = String::from(
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
                   created_at::text AS created_at,
                   updated_at::text AS updated_at
            FROM evidence_record
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();

        if !req.case_id.is_empty() {
            query.push_str(&format!(" AND case_id = ${}::uuid", binds.len() + 1));
            binds.push(req.case_id);
        }
        if !req.source_kind.is_empty() {
            query.push_str(&format!(" AND source_kind = ${}", binds.len() + 1));
            binds.push(req.source_kind);
        }
        if !req.evidence_type.is_empty() {
            query.push_str(&format!(" AND evidence_type = ${}", binds.len() + 1));
            binds.push(req.evidence_type);
        }
        if !req.evidence_role.is_empty() {
            query.push_str(&format!(" AND evidence_role = ${}", binds.len() + 1));
            binds.push(req.evidence_role);
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
            query.push_str(&format!(
                " AND (source_kind ILIKE ${idx} OR source_id ILIKE ${idx} OR evidence_type ILIKE ${idx} OR evidence_role ILIKE ${idx})"
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
        Ok(SearchEvidenceResponse {
            evidence: rows.iter().map(map_evidence_row).collect(),
        })
    }

    pub async fn upsert_evidence_locator(
        &self,
        req: UpsertEvidenceLocatorRequest,
    ) -> Result<UpsertEvidenceLocatorResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO evidence_locator (
              evidence_locator_id, evidence_id, locator_type, page_span, char_span, sentence_ref,
              bbox, polygon, time_range, table_cell, measurement_field, locator_payload,
              normalized_text, preview_text
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid,
              $3,
              CASE WHEN $4 = '' THEN NULL ELSE $4::int4range END,
              CASE WHEN $5 = '' THEN NULL ELSE $5::int4range END,
              CASE WHEN $6 = '' THEN NULL ELSE $6::jsonb END,
              CASE WHEN $7 = '' THEN NULL ELSE $7::jsonb END,
              CASE WHEN $8 = '' THEN NULL ELSE $8::jsonb END,
              CASE WHEN $9 = '' THEN NULL ELSE $9::tstzrange END,
              CASE WHEN $10 = '' THEN NULL ELSE $10::jsonb END,
              NULLIF($11, ''),
              CASE WHEN $12 = '' THEN '{}'::jsonb ELSE $12::jsonb END,
              NULLIF($13, ''),
              NULLIF($14, '')
            )
            ON CONFLICT (evidence_locator_id) DO UPDATE SET
              evidence_id = EXCLUDED.evidence_id,
              locator_type = EXCLUDED.locator_type,
              page_span = EXCLUDED.page_span,
              char_span = EXCLUDED.char_span,
              sentence_ref = EXCLUDED.sentence_ref,
              bbox = EXCLUDED.bbox,
              polygon = EXCLUDED.polygon,
              time_range = EXCLUDED.time_range,
              table_cell = EXCLUDED.table_cell,
              measurement_field = EXCLUDED.measurement_field,
              locator_payload = EXCLUDED.locator_payload,
              normalized_text = EXCLUDED.normalized_text,
              preview_text = EXCLUDED.preview_text
            RETURNING evidence_locator_id::text AS evidence_locator_id,
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
                      locator_payload::text AS locator_payload_json,
                      COALESCE(normalized_text, '') AS normalized_text,
                      COALESCE(preview_text, '') AS preview_text,
                      created_at::text AS created_at
            "#,
        )
        .bind(&req.evidence_locator_id)
        .bind(&req.evidence_id)
        .bind(&req.locator_type)
        .bind(&req.page_span)
        .bind(&req.char_span)
        .bind(&req.sentence_ref_json)
        .bind(&req.bbox_json)
        .bind(&req.polygon_json)
        .bind(&req.time_range)
        .bind(&req.table_cell_json)
        .bind(&req.measurement_field)
        .bind(&req.locator_payload_json)
        .bind(&req.normalized_text)
        .bind(&req.preview_text)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEvidenceLocatorResponse {
            locator: Some(map_evidence_locator_row(&row)),
        })
    }

    pub async fn list_evidence_locators(
        &self,
        req: ListEvidenceLocatorsRequest,
    ) -> Result<ListEvidenceLocatorsResponse, sqlx::Error> {
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
                   locator_payload::text AS locator_payload_json,
                   COALESCE(normalized_text, '') AS normalized_text,
                   COALESCE(preview_text, '') AS preview_text,
                   created_at::text AS created_at
            FROM evidence_locator
            WHERE evidence_id = $1::uuid
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            "#,
        )
        .bind(&req.evidence_id)
        .bind(if req.limit > 0 { req.limit } else { 50 })
        .bind(req.offset)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListEvidenceLocatorsResponse {
            locators: rows.iter().map(map_evidence_locator_row).collect(),
        })
    }

    pub async fn upsert_evidence_derivation(
        &self,
        req: UpsertEvidenceDerivationRequest,
    ) -> Result<UpsertEvidenceDerivationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO evidence_derivation (
              evidence_derivation_id, child_evidence_id, parent_evidence_id, derivation_type,
              method, run_id, artifact_version_id, derivation_metadata
            ) VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid,
              $3::uuid,
              $4,
              $5,
              $6,
              NULLIF($7, '')::uuid,
              CASE WHEN $8 = '' THEN '{}'::jsonb ELSE $8::jsonb END
            )
            ON CONFLICT (evidence_derivation_id) DO UPDATE SET
              child_evidence_id = EXCLUDED.child_evidence_id,
              parent_evidence_id = EXCLUDED.parent_evidence_id,
              derivation_type = EXCLUDED.derivation_type,
              method = EXCLUDED.method,
              run_id = EXCLUDED.run_id,
              artifact_version_id = EXCLUDED.artifact_version_id,
              derivation_metadata = EXCLUDED.derivation_metadata
            RETURNING evidence_derivation_id::text AS evidence_derivation_id,
                      child_evidence_id::text AS child_evidence_id,
                      parent_evidence_id::text AS parent_evidence_id,
                      derivation_type,
                      method,
                      run_id,
                      COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                      derivation_metadata::text AS derivation_metadata_json,
                      created_at::text AS created_at
            "#,
        )
        .bind(&req.evidence_derivation_id)
        .bind(&req.child_evidence_id)
        .bind(&req.parent_evidence_id)
        .bind(&req.derivation_type)
        .bind(&req.method)
        .bind(&req.run_id)
        .bind(&req.artifact_version_id)
        .bind(&req.derivation_metadata_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEvidenceDerivationResponse {
            derivation: Some(map_evidence_derivation_row(&row)),
        })
    }

    pub async fn list_evidence_derivations(
        &self,
        req: ListEvidenceDerivationsRequest,
    ) -> Result<ListEvidenceDerivationsResponse, sqlx::Error> {
        let direction = if req.direction.is_empty() {
            "both".to_string()
        } else {
            req.direction.to_lowercase()
        };
        let rows = match direction.as_str() {
            "parents" => {
                sqlx::query(
                    r#"
                    SELECT evidence_derivation_id::text AS evidence_derivation_id,
                           child_evidence_id::text AS child_evidence_id,
                           parent_evidence_id::text AS parent_evidence_id,
                           derivation_type,
                           method,
                           run_id,
                           COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                           derivation_metadata::text AS derivation_metadata_json,
                           created_at::text AS created_at
                    FROM evidence_derivation
                    WHERE child_evidence_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.evidence_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
            "children" => {
                sqlx::query(
                    r#"
                    SELECT evidence_derivation_id::text AS evidence_derivation_id,
                           child_evidence_id::text AS child_evidence_id,
                           parent_evidence_id::text AS parent_evidence_id,
                           derivation_type,
                           method,
                           run_id,
                           COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                           derivation_metadata::text AS derivation_metadata_json,
                           created_at::text AS created_at
                    FROM evidence_derivation
                    WHERE parent_evidence_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.evidence_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
            _ => {
                sqlx::query(
                    r#"
                    SELECT evidence_derivation_id::text AS evidence_derivation_id,
                           child_evidence_id::text AS child_evidence_id,
                           parent_evidence_id::text AS parent_evidence_id,
                           derivation_type,
                           method,
                           run_id,
                           COALESCE(artifact_version_id::text, '') AS artifact_version_id,
                           derivation_metadata::text AS derivation_metadata_json,
                           created_at::text AS created_at
                    FROM evidence_derivation
                    WHERE child_evidence_id = $1::uuid OR parent_evidence_id = $1::uuid
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                    "#,
                )
                .bind(&req.evidence_id)
                .bind(if req.limit > 0 { req.limit } else { 50 })
                .bind(req.offset)
                .fetch_all(&self.pool)
                .await?
            }
        };

        Ok(ListEvidenceDerivationsResponse {
            derivations: rows.iter().map(map_evidence_derivation_row).collect(),
        })
    }

    pub async fn upsert_evidence_classification(
        &self,
        req: UpsertEvidenceClassificationRequest,
    ) -> Result<UpsertEvidenceClassificationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO evidence_classification (
              evidence_id, source_reliability_tier, evidence_strength_tier, evidence_modality,
              institutional_trust_class, is_primary_source, is_machine_generated,
              requires_human_validation, methodology_framework_id, classification_status, metadata
            ) VALUES (
              $1::uuid, $2, $3, $4, $5, $6, $7, $8, NULLIF($9, '')::uuid, $10,
              CASE WHEN $11 = '' THEN '{}'::jsonb ELSE $11::jsonb END
            )
            ON CONFLICT (evidence_id) DO UPDATE SET
              source_reliability_tier = EXCLUDED.source_reliability_tier,
              evidence_strength_tier = EXCLUDED.evidence_strength_tier,
              evidence_modality = EXCLUDED.evidence_modality,
              institutional_trust_class = EXCLUDED.institutional_trust_class,
              is_primary_source = EXCLUDED.is_primary_source,
              is_machine_generated = EXCLUDED.is_machine_generated,
              requires_human_validation = EXCLUDED.requires_human_validation,
              methodology_framework_id = EXCLUDED.methodology_framework_id,
              classification_status = EXCLUDED.classification_status,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING evidence_id::text AS evidence_id,
                      source_reliability_tier,
                      evidence_strength_tier,
                      evidence_modality,
                      institutional_trust_class,
                      is_primary_source,
                      is_machine_generated,
                      requires_human_validation,
                      COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                      classification_status,
                      metadata::text AS metadata_json,
                      created_at::text AS created_at,
                      updated_at::text AS updated_at
            "#,
        )
        .bind(&req.evidence_id)
        .bind(&req.source_reliability_tier)
        .bind(&req.evidence_strength_tier)
        .bind(&req.evidence_modality)
        .bind(&req.institutional_trust_class)
        .bind(req.is_primary_source)
        .bind(req.is_machine_generated)
        .bind(req.requires_human_validation)
        .bind(&req.methodology_framework_id)
        .bind(&req.classification_status)
        .bind(&req.metadata_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEvidenceClassificationResponse {
            classification: Some(map_evidence_classification_row(&row)),
        })
    }

    pub async fn get_evidence_classification(
        &self,
        req: GetEvidenceClassificationRequest,
    ) -> Result<GetEvidenceClassificationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT evidence_id::text AS evidence_id,
                   source_reliability_tier,
                   evidence_strength_tier,
                   evidence_modality,
                   institutional_trust_class,
                   is_primary_source,
                   is_machine_generated,
                   requires_human_validation,
                   COALESCE(methodology_framework_id::text, '') AS methodology_framework_id,
                   classification_status,
                   metadata::text AS metadata_json,
                   created_at::text AS created_at,
                   updated_at::text AS updated_at
            FROM evidence_classification
            WHERE evidence_id = $1::uuid
            "#,
        )
        .bind(&req.evidence_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetEvidenceClassificationResponse {
            classification: row.as_ref().map(map_evidence_classification_row),
        })
    }
}

fn map_evidence_row(row: &sqlx::postgres::PgRow) -> EvidenceRecord {
    EvidenceRecord {
        evidence_id: row.get("evidence_id"),
        case_id: row.get("case_id"),
        event_seq: row.get::<i64, _>("event_seq"),
        source_kind: row.get("source_kind"),
        source_id: row.get("source_id"),
        artifact_version_id: row.get("artifact_version_id"),
        evidence_type: row.get("evidence_type"),
        evidence_role: row.get("evidence_role"),
        methodology_framework_id: row.get("methodology_framework_id"),
        evidence_payload_json: row
            .get::<Option<String>, _>("evidence_payload_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_by_type: row.get("created_by_type"),
        created_by_id: row.get("created_by_id"),
        is_derived: row.get("is_derived"),
        status: row.get("status"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_evidence_locator_row(row: &sqlx::postgres::PgRow) -> EvidenceLocatorRecord {
    EvidenceLocatorRecord {
        evidence_locator_id: row.get("evidence_locator_id"),
        evidence_id: row.get("evidence_id"),
        locator_type: row.get("locator_type"),
        page_span: row.get("page_span"),
        char_span: row.get("char_span"),
        sentence_ref_json: row
            .get::<Option<String>, _>("sentence_ref_json")
            .unwrap_or_default(),
        bbox_json: row
            .get::<Option<String>, _>("bbox_json")
            .unwrap_or_default(),
        polygon_json: row
            .get::<Option<String>, _>("polygon_json")
            .unwrap_or_default(),
        time_range: row.get("time_range"),
        table_cell_json: row
            .get::<Option<String>, _>("table_cell_json")
            .unwrap_or_default(),
        measurement_field: row.get("measurement_field"),
        locator_payload_json: row
            .get::<Option<String>, _>("locator_payload_json")
            .unwrap_or_else(|| "{}".to_string()),
        normalized_text: row.get("normalized_text"),
        preview_text: row.get("preview_text"),
        created_at: row.get("created_at"),
    }
}

fn map_evidence_derivation_row(row: &sqlx::postgres::PgRow) -> EvidenceDerivationRecord {
    EvidenceDerivationRecord {
        evidence_derivation_id: row.get("evidence_derivation_id"),
        child_evidence_id: row.get("child_evidence_id"),
        parent_evidence_id: row.get("parent_evidence_id"),
        derivation_type: row.get("derivation_type"),
        method: row.get("method"),
        run_id: row.get("run_id"),
        artifact_version_id: row.get("artifact_version_id"),
        derivation_metadata_json: row
            .get::<Option<String>, _>("derivation_metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row.get("created_at"),
    }
}

fn map_evidence_classification_row(row: &sqlx::postgres::PgRow) -> EvidenceClassificationRecord {
    EvidenceClassificationRecord {
        evidence_id: row.get("evidence_id"),
        source_reliability_tier: row.get("source_reliability_tier"),
        evidence_strength_tier: row.get("evidence_strength_tier"),
        evidence_modality: row.get("evidence_modality"),
        institutional_trust_class: row.get("institutional_trust_class"),
        is_primary_source: row.get("is_primary_source"),
        is_machine_generated: row.get("is_machine_generated"),
        requires_human_validation: row.get("requires_human_validation"),
        methodology_framework_id: row.get("methodology_framework_id"),
        classification_status: row.get("classification_status"),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}
