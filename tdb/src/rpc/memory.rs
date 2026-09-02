use crate::rpc::proto::{
    InsertMemoryAnswerArtifactRequest, InsertMemoryAnswerArtifactResponse,
    InsertMemoryAnswerValidationRequest, InsertMemoryAnswerValidationResponse,
    InsertMemoryDecisionRequest, InsertMemoryDecisionResponse, InsertMemoryEpisodeSummaryRequest,
    InsertMemoryEpisodeSummaryResponse, ListRecentMemoryDecisionsRequest,
    ListRecentMemoryDecisionsResponse, ListRecentMemoryEpisodeSummariesRequest,
    ListRecentMemoryEpisodeSummariesResponse, MemoryAnswerArtifactRecord,
    MemoryAnswerValidationRecord, MemoryDecisionRecord, MemoryEpisodeSummaryRecord,
    RecallMemoryAnswerArtifactsRequest, RecallMemoryAnswerArtifactsResponse,
};
use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct MemoryStore {
    pool: PgPool,
}

impl MemoryStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn insert_memory_decision(
        &self,
        req: InsertMemoryDecisionRequest,
    ) -> Result<InsertMemoryDecisionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO memory_decision_record (
                task_id, run_id, decision_text, rationale_text, alternatives_considered,
                source_evidence, entity_ids, confidence, author, decision_timestamp,
                consequences, metadata, idempotency_key
            ) VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9::jsonb, COALESCE($10::timestamptz, NOW()), $11::jsonb, $12::jsonb, $13)
            RETURNING memory_decision_id::text, task_id, run_id, decision_text, rationale_text,
                      alternatives_considered, source_evidence::text as source_evidence_json, 
                      entity_ids, confidence, author::text as author_json, decision_timestamp,
                      consequences, metadata::text as metadata_json, idempotency_key, created_at
            "#,
        )
        .bind(&req.task_id)
        .bind(if req.run_id.is_empty() { None } else { Some(&req.run_id) })
        .bind(&req.decision_text)
        .bind(&req.rationale_text)
        .bind(serde_json::to_string(&req.alternatives_considered).unwrap_or_else(|_| "[]".to_string()))
        .bind(&req.source_evidence_json)
        .bind(serde_json::to_string(&req.entity_ids).unwrap_or_else(|_| "[]".to_string()))
        .bind(req.confidence as f64)
        .bind(&req.author_json)
        .bind(if req.decision_timestamp.is_empty() { None } else { Some(&req.decision_timestamp) })
        .bind(serde_json::to_string(&req.consequences).unwrap_or_else(|_| "[]".to_string()))
        .bind(&req.metadata_json)
        .bind(if req.idempotency_key.is_empty() { None } else { Some(&req.idempotency_key) })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertMemoryDecisionResponse {
            decision: Some(map_decision_row(&row)),
        })
    }

    pub async fn list_recent_memory_decisions(
        &self,
        req: ListRecentMemoryDecisionsRequest,
    ) -> Result<ListRecentMemoryDecisionsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT memory_decision_id::text, task_id, run_id, decision_text, rationale_text,
                   alternatives_considered, source_evidence::text as source_evidence_json, 
                   entity_ids, confidence, author::text as author_json, decision_timestamp,
                   consequences, metadata::text as metadata_json, idempotency_key, created_at
            FROM memory_decision_record
            WHERE 1=1
            "#,
        );
        let mut params = Vec::new();

        if !req.task_id.is_empty() {
            params.push(req.task_id.clone());
            query.push_str(&format!(" AND task_id = ${}", params.len()));
        }
        if !req.run_id.is_empty() {
            params.push(req.run_id.clone());
            query.push_str(&format!(" AND run_id = ${}", params.len()));
        }
        if !req.entity_ids.is_empty() {
            params.push(serde_json::to_string(&req.entity_ids).unwrap());
            query.push_str(&format!(" AND entity_ids ?| ${}::jsonb", params.len()));
        }
        if !req.as_of.is_empty() {
            params.push(req.as_of.clone());
            query.push_str(&format!(
                " AND decision_timestamp <= ${}::timestamptz",
                params.len()
            ));
        }

        query.push_str(" ORDER BY decision_timestamp DESC, created_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListRecentMemoryDecisionsResponse {
            decisions: rows.iter().map(map_decision_row).collect(),
        })
    }

    pub async fn insert_memory_episode_summary(
        &self,
        req: InsertMemoryEpisodeSummaryRequest,
    ) -> Result<InsertMemoryEpisodeSummaryResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO memory_episode_summary (
                episode_label, task_id, run_id, session_id, summary_text, outcomes,
                key_facts, decisions, unresolved_questions, source_evidence,
                entity_ids, confidence, author, summary_timestamp, metadata, idempotency_key
            ) VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12, $13::jsonb, COALESCE($14::timestamptz, NOW()), $15::jsonb, $16)
            RETURNING episode_summary_id::text, episode_label, task_id, run_id, session_id,
                      summary_text, outcomes, key_facts::text as key_facts_json, decisions,
                      unresolved_questions, source_evidence::text as source_evidence_json, 
                      entity_ids, confidence, author::text as author_json, summary_timestamp,
                      metadata::text as metadata_json, idempotency_key, created_at
            "#,
        )
        .bind(if req.episode_label.is_empty() { None } else { Some(&req.episode_label) })
        .bind(if req.task_id.is_empty() { None } else { Some(&req.task_id) })
        .bind(if req.run_id.is_empty() { None } else { Some(&req.run_id) })
        .bind(if req.session_id.is_empty() { None } else { Some(&req.session_id) })
        .bind(&req.summary_text)
        .bind(serde_json::to_string(&req.outcomes).unwrap_or_else(|_| "[]".to_string()))
        .bind(&req.key_facts_json)
        .bind(serde_json::to_string(&req.decisions).unwrap_or_else(|_| "[]".to_string()))
        .bind(serde_json::to_string(&req.unresolved_questions).unwrap_or_else(|_| "[]".to_string()))
        .bind(&req.source_evidence_json)
        .bind(serde_json::to_string(&req.entity_ids).unwrap_or_else(|_| "[]".to_string()))
        .bind(req.confidence as f64)
        .bind(&req.author_json)
        .bind(if req.summary_timestamp.is_empty() { None } else { Some(&req.summary_timestamp) })
        .bind(&req.metadata_json)
        .bind(if req.idempotency_key.is_empty() { None } else { Some(&req.idempotency_key) })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertMemoryEpisodeSummaryResponse {
            summary: Some(map_summary_row(&row)),
        })
    }

    pub async fn list_recent_memory_episode_summaries(
        &self,
        req: ListRecentMemoryEpisodeSummariesRequest,
    ) -> Result<ListRecentMemoryEpisodeSummariesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT episode_summary_id::text, episode_label, task_id, run_id, session_id,
                   summary_text, outcomes, key_facts::text as key_facts_json, decisions,
                   unresolved_questions, source_evidence::text as source_evidence_json, 
                   entity_ids, confidence, author::text as author_json, summary_timestamp,
                   metadata::text as metadata_json, idempotency_key, created_at
            FROM memory_episode_summary
            WHERE 1=1
            "#,
        );
        let mut params = Vec::new();

        if !req.task_id.is_empty() {
            params.push(req.task_id.clone());
            query.push_str(&format!(" AND task_id = ${}", params.len()));
        }
        if !req.run_id.is_empty() {
            params.push(req.run_id.clone());
            query.push_str(&format!(" AND run_id = ${}", params.len()));
        }
        if !req.as_of.is_empty() {
            params.push(req.as_of.clone());
            query.push_str(&format!(
                " AND summary_timestamp <= ${}::timestamptz",
                params.len()
            ));
        }

        query.push_str(" ORDER BY summary_timestamp DESC, created_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListRecentMemoryEpisodeSummariesResponse {
            summaries: rows.iter().map(map_summary_row).collect(),
        })
    }

    pub async fn insert_memory_answer_artifact(
        &self,
        req: InsertMemoryAnswerArtifactRequest,
    ) -> Result<InsertMemoryAnswerArtifactResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO memory_answer_artifact (
                domain_id, intent, normalized_question, question_fingerprint, entity_ids,
                answer_text, answer_payload, source_task_id, source_run_id, source_decision_id,
                source_episode_summary_id, evidence_refs, provenance, freshness_policy,
                validation_contract, metadata, serving_status, superseded_by, idempotency_key
            ) VALUES (
                $1, $2, $3, $4::jsonb, $5::jsonb,
                $6, $7::jsonb, $8, $9, NULLIF($10, '')::uuid,
                NULLIF($11, '')::uuid, $12::jsonb, $13::jsonb, $14::jsonb,
                $15::jsonb, $16::jsonb, COALESCE(NULLIF($17, ''), 'active'),
                NULLIF($18, '')::uuid, $19
            )
            RETURNING answer_artifact_id::text, domain_id, intent, normalized_question,
                      question_fingerprint::text as question_fingerprint_json,
                      entity_ids, answer_text, answer_payload::text as answer_payload_json,
                      COALESCE(source_task_id, '') as source_task_id,
                      COALESCE(source_run_id, '') as source_run_id,
                      COALESCE(source_decision_id::text, '') as source_decision_id,
                      COALESCE(source_episode_summary_id::text, '') as source_episode_summary_id,
                      evidence_refs::text as evidence_refs_json,
                      provenance::text as provenance_json,
                      freshness_policy::text as freshness_policy_json,
                      validation_contract::text as validation_contract_json,
                      metadata::text as metadata_json,
                      serving_status,
                      COALESCE(superseded_by::text, '') as superseded_by,
                      COALESCE(idempotency_key, '') as idempotency_key,
                      created_at,
                      updated_at
            "#,
        )
        .bind(&req.domain_id)
        .bind(&req.intent)
        .bind(&req.normalized_question)
        .bind(&req.question_fingerprint_json)
        .bind(serde_json::to_string(&req.entity_ids).unwrap_or_else(|_| "[]".to_string()))
        .bind(&req.answer_text)
        .bind(&req.answer_payload_json)
        .bind(if req.source_task_id.is_empty() {
            None
        } else {
            Some(&req.source_task_id)
        })
        .bind(if req.source_run_id.is_empty() {
            None
        } else {
            Some(&req.source_run_id)
        })
        .bind(&req.source_decision_id)
        .bind(&req.source_episode_summary_id)
        .bind(&req.evidence_refs_json)
        .bind(if req.provenance_json.is_empty() {
            "{}"
        } else {
            &req.provenance_json
        })
        .bind(&req.freshness_policy_json)
        .bind(&req.validation_contract_json)
        .bind(if req.metadata_json.is_empty() {
            "{}"
        } else {
            &req.metadata_json
        })
        .bind(&req.serving_status)
        .bind(&req.superseded_by)
        .bind(if req.idempotency_key.is_empty() {
            None
        } else {
            Some(&req.idempotency_key)
        })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertMemoryAnswerArtifactResponse {
            artifact: Some(map_answer_artifact_row(&row)),
        })
    }

    pub async fn recall_memory_answer_artifacts(
        &self,
        req: RecallMemoryAnswerArtifactsRequest,
    ) -> Result<RecallMemoryAnswerArtifactsResponse, sqlx::Error> {
        let statuses = if req.serving_statuses.is_empty() {
            vec!["active".to_string()]
        } else {
            req.serving_statuses.clone()
        };
        let rows = sqlx::query(
            r#"
            SELECT answer_artifact_id::text, domain_id, intent, normalized_question,
                   question_fingerprint::text as question_fingerprint_json,
                   entity_ids, answer_text, answer_payload::text as answer_payload_json,
                   COALESCE(source_task_id, '') as source_task_id,
                   COALESCE(source_run_id, '') as source_run_id,
                   COALESCE(source_decision_id::text, '') as source_decision_id,
                   COALESCE(source_episode_summary_id::text, '') as source_episode_summary_id,
                   evidence_refs::text as evidence_refs_json,
                   provenance::text as provenance_json,
                   freshness_policy::text as freshness_policy_json,
                   validation_contract::text as validation_contract_json,
                   metadata::text as metadata_json,
                   serving_status,
                   COALESCE(superseded_by::text, '') as superseded_by,
                   COALESCE(idempotency_key, '') as idempotency_key,
                   created_at,
                   updated_at
            FROM memory_answer_artifact
            WHERE domain_id = $1
              AND intent = $2
              AND serving_status = ANY($3)
              AND ($4::jsonb = '{}'::jsonb OR question_fingerprint @> $4::jsonb)
              AND ($5::jsonb = '[]'::jsonb OR entity_ids @> $5::jsonb)
            ORDER BY updated_at DESC, created_at DESC
            LIMIT $6
            "#,
        )
        .bind(&req.domain_id)
        .bind(&req.intent)
        .bind(&statuses)
        .bind(if req.question_fingerprint_json.is_empty() {
            "{}"
        } else {
            &req.question_fingerprint_json
        })
        .bind(serde_json::to_string(&req.entity_ids).unwrap_or_else(|_| "[]".to_string()))
        .bind(req.limit)
        .fetch_all(&self.pool)
        .await?;

        Ok(RecallMemoryAnswerArtifactsResponse {
            artifacts: rows.iter().map(map_answer_artifact_row).collect(),
        })
    }

    pub async fn insert_memory_answer_validation(
        &self,
        req: InsertMemoryAnswerValidationRequest,
    ) -> Result<InsertMemoryAnswerValidationResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO memory_answer_validation (
                answer_artifact_id, validator_type, check_spec, observed_values, pass,
                failure_reason, latency_ms, metadata, validated_at
            ) VALUES (
                $1::uuid, COALESCE(NULLIF($2, ''), 'runtime'), $3::jsonb, $4::jsonb, $5,
                NULLIF($6, ''), NULLIF($7, 0), $8::jsonb, COALESCE(NULLIF($9, '')::timestamptz, NOW())
            )
            RETURNING answer_validation_id::text, answer_artifact_id::text, validator_type,
                      check_spec::text as check_spec_json,
                      observed_values::text as observed_values_json,
                      pass, COALESCE(failure_reason, '') as failure_reason,
                      COALESCE(latency_ms, 0) as latency_ms,
                      metadata::text as metadata_json,
                      validated_at
            "#,
        )
        .bind(&req.answer_artifact_id)
        .bind(&req.validator_type)
        .bind(&req.check_spec_json)
        .bind(&req.observed_values_json)
        .bind(req.pass)
        .bind(&req.failure_reason)
        .bind(req.latency_ms)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .bind(&req.validated_at)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertMemoryAnswerValidationResponse {
            validation: Some(map_answer_validation_row(&row)),
        })
    }
}

fn map_decision_row(row: &sqlx::postgres::PgRow) -> MemoryDecisionRecord {
    use sqlx::Row;
    MemoryDecisionRecord {
        memory_decision_id: row.get("memory_decision_id"),
        task_id: row.get("task_id"),
        run_id: row.get::<Option<String>, _>("run_id").unwrap_or_default(),
        decision_text: row.get("decision_text"),
        rationale_text: row.get("rationale_text"),
        alternatives_considered: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("alternatives_considered")
            .map(|j| j.0)
            .unwrap_or_default(),
        source_evidence_json: row
            .get::<Option<String>, _>("source_evidence_json")
            .unwrap_or_else(|| "[]".to_string()),
        entity_ids: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("entity_ids")
            .map(|j| j.0)
            .unwrap_or_default(),
        confidence: row.get::<Option<f64>, _>("confidence").unwrap_or(0.0) as f32,
        author_json: row
            .get::<Option<String>, _>("author_json")
            .unwrap_or_else(|| "{}".to_string()),
        decision_timestamp: row
            .get::<chrono::DateTime<chrono::Utc>, _>("decision_timestamp")
            .to_rfc3339(),
        consequences: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("consequences")
            .map(|j| j.0)
            .unwrap_or_default(),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        idempotency_key: row
            .get::<Option<String>, _>("idempotency_key")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

fn map_summary_row(row: &sqlx::postgres::PgRow) -> MemoryEpisodeSummaryRecord {
    use sqlx::Row;
    MemoryEpisodeSummaryRecord {
        episode_summary_id: row.get("episode_summary_id"),
        episode_label: row
            .get::<Option<String>, _>("episode_label")
            .unwrap_or_default(),
        task_id: row.get::<Option<String>, _>("task_id").unwrap_or_default(),
        run_id: row.get::<Option<String>, _>("run_id").unwrap_or_default(),
        session_id: row
            .get::<Option<String>, _>("session_id")
            .unwrap_or_default(),
        summary_text: row.get("summary_text"),
        outcomes: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("outcomes")
            .map(|j| j.0)
            .unwrap_or_default(),
        key_facts_json: row
            .get::<Option<String>, _>("key_facts_json")
            .unwrap_or_else(|| "[]".to_string()),
        decisions: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("decisions")
            .map(|j| j.0)
            .unwrap_or_default(),
        unresolved_questions: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("unresolved_questions")
            .map(|j| j.0)
            .unwrap_or_default(),
        source_evidence_json: row
            .get::<Option<String>, _>("source_evidence_json")
            .unwrap_or_else(|| "[]".to_string()),
        entity_ids: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("entity_ids")
            .map(|j| j.0)
            .unwrap_or_default(),
        confidence: row.get::<Option<f64>, _>("confidence").unwrap_or(0.0) as f32,
        author_json: row
            .get::<Option<String>, _>("author_json")
            .unwrap_or_else(|| "{}".to_string()),
        summary_timestamp: row
            .get::<chrono::DateTime<chrono::Utc>, _>("summary_timestamp")
            .to_rfc3339(),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        idempotency_key: row
            .get::<Option<String>, _>("idempotency_key")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

fn map_answer_artifact_row(row: &sqlx::postgres::PgRow) -> MemoryAnswerArtifactRecord {
    use sqlx::Row;
    MemoryAnswerArtifactRecord {
        answer_artifact_id: row.get("answer_artifact_id"),
        domain_id: row.get("domain_id"),
        intent: row.get("intent"),
        normalized_question: row.get("normalized_question"),
        question_fingerprint_json: row
            .get::<Option<String>, _>("question_fingerprint_json")
            .unwrap_or_else(|| "{}".to_string()),
        entity_ids: row
            .get::<Option<sqlx::types::Json<Vec<String>>>, _>("entity_ids")
            .map(|j| j.0)
            .unwrap_or_default(),
        answer_text: row.get("answer_text"),
        answer_payload_json: row
            .get::<Option<String>, _>("answer_payload_json")
            .unwrap_or_else(|| "{}".to_string()),
        source_task_id: row
            .get::<Option<String>, _>("source_task_id")
            .unwrap_or_default(),
        source_run_id: row
            .get::<Option<String>, _>("source_run_id")
            .unwrap_or_default(),
        source_decision_id: row
            .get::<Option<String>, _>("source_decision_id")
            .unwrap_or_default(),
        source_episode_summary_id: row
            .get::<Option<String>, _>("source_episode_summary_id")
            .unwrap_or_default(),
        evidence_refs_json: row
            .get::<Option<String>, _>("evidence_refs_json")
            .unwrap_or_else(|| "[]".to_string()),
        provenance_json: row
            .get::<Option<String>, _>("provenance_json")
            .unwrap_or_else(|| "{}".to_string()),
        freshness_policy_json: row
            .get::<Option<String>, _>("freshness_policy_json")
            .unwrap_or_else(|| "{}".to_string()),
        validation_contract_json: row
            .get::<Option<String>, _>("validation_contract_json")
            .unwrap_or_else(|| "{}".to_string()),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        serving_status: row.get("serving_status"),
        superseded_by: row
            .get::<Option<String>, _>("superseded_by")
            .unwrap_or_default(),
        idempotency_key: row
            .get::<Option<String>, _>("idempotency_key")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}

fn map_answer_validation_row(row: &sqlx::postgres::PgRow) -> MemoryAnswerValidationRecord {
    use sqlx::Row;
    MemoryAnswerValidationRecord {
        answer_validation_id: row.get("answer_validation_id"),
        answer_artifact_id: row.get("answer_artifact_id"),
        validator_type: row.get("validator_type"),
        check_spec_json: row
            .get::<Option<String>, _>("check_spec_json")
            .unwrap_or_else(|| "{}".to_string()),
        observed_values_json: row
            .get::<Option<String>, _>("observed_values_json")
            .unwrap_or_else(|| "{}".to_string()),
        pass: row.get("pass"),
        failure_reason: row
            .get::<Option<String>, _>("failure_reason")
            .unwrap_or_default(),
        latency_ms: row.get::<Option<i32>, _>("latency_ms").unwrap_or_default(),
        metadata_json: row
            .get::<Option<String>, _>("metadata_json")
            .unwrap_or_else(|| "{}".to_string()),
        validated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("validated_at")
            .to_rfc3339(),
    }
}
