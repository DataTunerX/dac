use crate::rpc::proto::{
    DecisionEvidenceRecord, DecisionRecord, FindDecisionRequest, FindDecisionResponse,
    InsertDecisionEvidenceRequest, InsertDecisionEvidenceResponse, ListDecisionEvidenceRequest,
    ListDecisionEvidenceResponse, UpsertDecisionRequest, UpsertDecisionResponse,
};
use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct DecisionStore {
    pool: PgPool,
}

impl DecisionStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_decision(
        &self,
        req: UpsertDecisionRequest,
    ) -> Result<UpsertDecisionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO decision (case_id, event_seq, projection_version, chosen_action, candidates, scores, constraints_hit, detail)
            VALUES ($1::uuid, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8::jsonb)
            ON CONFLICT (case_id, event_seq, projection_version) DO UPDATE SET
                chosen_action = EXCLUDED.chosen_action,
                candidates = EXCLUDED.candidates,
                scores = EXCLUDED.scores,
                constraints_hit = EXCLUDED.constraints_hit,
                detail = EXCLUDED.detail
            RETURNING decision_id::text, case_id::text, event_seq, projection_version, chosen_action, 
                      candidates::text as candidates_json, scores::text as scores_json, 
                      constraints_hit, detail::text as detail_json, created_at
            "#,
        )
        .bind(&req.case_id)
        .bind(req.event_seq)
        .bind(&req.projection_version)
        .bind(&req.chosen_action)
        .bind(&req.candidates_json)
        .bind(&req.scores_json)
        .bind(&req.constraints_hit)
        .bind(&req.detail_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertDecisionResponse {
            decision: Some(map_decision_row(&row)),
        })
    }

    pub async fn insert_decision_evidence(
        &self,
        req: InsertDecisionEvidenceRequest,
    ) -> Result<InsertDecisionEvidenceResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO decision_evidence (decision_id, artifact_version_id, citation)
            VALUES ($1::uuid, $2::uuid, $3::jsonb)
            RETURNING decision_evidence_id::text, decision_id::text, artifact_version_id::text, 
                      citation::text as citation_json, created_at
            "#,
        )
        .bind(&req.decision_id)
        .bind(&req.artifact_version_id)
        .bind(&req.citation_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertDecisionEvidenceResponse {
            evidence: Some(map_evidence_row(&row)),
        })
    }

    pub async fn find_decision(
        &self,
        req: FindDecisionRequest,
    ) -> Result<FindDecisionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT decision_id::text, case_id::text, event_seq, projection_version, chosen_action, 
                   candidates::text as candidates_json, scores::text as scores_json, 
                   constraints_hit, detail::text as detail_json, created_at
            FROM decision
            WHERE case_id = $1::uuid
              AND event_seq = $2
              AND projection_version = $3
            "#,
        )
        .bind(&req.case_id)
        .bind(req.event_seq)
        .bind(&req.projection_version)
        .fetch_optional(&self.pool)
        .await?;

        Ok(FindDecisionResponse {
            decision: row.map(|r| map_decision_row(&r)),
        })
    }

    pub async fn list_decision_evidence(
        &self,
        req: ListDecisionEvidenceRequest,
    ) -> Result<ListDecisionEvidenceResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT decision_evidence_id::text, decision_id::text, artifact_version_id::text, 
                   citation::text as citation_json, created_at
            FROM decision_evidence
            WHERE decision_id = $1::uuid
            ORDER BY created_at ASC
            "#,
        )
        .bind(&req.decision_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListDecisionEvidenceResponse {
            evidence: rows.iter().map(map_evidence_row).collect(),
        })
    }
}

fn map_decision_row(row: &sqlx::postgres::PgRow) -> DecisionRecord {
    use sqlx::Row;
    DecisionRecord {
        decision_id: row.get("decision_id"),
        case_id: row.get("case_id"),
        event_seq: row.get("event_seq"),
        projection_version: row.get("projection_version"),
        chosen_action: row.get("chosen_action"),
        candidates_json: row
            .get::<Option<String>, _>("candidates_json")
            .unwrap_or_else(|| "[]".to_string()),
        scores_json: row
            .get::<Option<String>, _>("scores_json")
            .unwrap_or_else(|| "{}".to_string()),
        constraints_hit: row.get("constraints_hit"),
        detail_json: row
            .get::<Option<String>, _>("detail_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

fn map_evidence_row(row: &sqlx::postgres::PgRow) -> DecisionEvidenceRecord {
    use sqlx::Row;
    DecisionEvidenceRecord {
        decision_evidence_id: row.get("decision_evidence_id"),
        decision_id: row.get("decision_id"),
        artifact_version_id: row.get("artifact_version_id"),
        citation_json: row
            .get::<Option<String>, _>("citation_json")
            .unwrap_or_else(|| "{}".to_string()),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}
