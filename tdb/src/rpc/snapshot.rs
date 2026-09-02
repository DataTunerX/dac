use crate::rpc::proto::{
    GetLatestSnapshotRequest, GetLatestSnapshotResponse, SnapshotRecord, WriteSnapshotRequest,
    WriteSnapshotResponse,
};
use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct SnapshotStore {
    pool: PgPool,
}

impl SnapshotStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn write_snapshot(
        &self,
        req: WriteSnapshotRequest,
    ) -> Result<WriteSnapshotResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        // 1. Ensure projection version exists
        sqlx::query(
            r#"
            INSERT INTO projection_version (projection_version)
            VALUES ($1)
            ON CONFLICT (projection_version) DO NOTHING
            "#,
        )
        .bind(&req.projection_version)
        .execute(&mut *tx)
        .await?;

        // 2. Insert snapshot
        let row = sqlx::query(
            r#"
            INSERT INTO state_snapshot (case_id, event_seq, projection_version, state_blob, state_hash)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5)
            RETURNING snapshot_id::text, case_id::text, event_seq, projection_version, state_blob::text as state_blob_json, state_hash, created_at
            "#,
        )
        .bind(&req.case_id)
        .bind(req.event_seq)
        .bind(&req.projection_version)
        .bind(&req.state_blob_json)
        .bind(&req.state_hash)
        .fetch_one(&mut *tx)
        .await?;

        tx.commit().await?;

        Ok(WriteSnapshotResponse {
            snapshot: Some(map_snapshot_row(&row)),
        })
    }

    pub async fn get_latest_snapshot(
        &self,
        req: GetLatestSnapshotRequest,
    ) -> Result<GetLatestSnapshotResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT snapshot_id::text, case_id::text, event_seq, projection_version, state_blob::text as state_blob_json, state_hash, created_at
            FROM state_snapshot
            WHERE case_id = $1::uuid
              AND projection_version = $2
              AND event_seq <= $3
            ORDER BY event_seq DESC
            LIMIT 1
            "#,
        )
        .bind(&req.case_id)
        .bind(&req.projection_version)
        .bind(req.target_seq)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetLatestSnapshotResponse {
            snapshot: row.map(|r| map_snapshot_row(&r)),
        })
    }
}

fn map_snapshot_row(row: &sqlx::postgres::PgRow) -> SnapshotRecord {
    use sqlx::Row;
    SnapshotRecord {
        snapshot_id: row.get("snapshot_id"),
        case_id: row.get("case_id"),
        event_seq: row.get("event_seq"),
        projection_version: row.get("projection_version"),
        state_blob_json: row
            .get::<Option<String>, _>("state_blob_json")
            .unwrap_or_else(|| "{}".to_string()),
        state_hash: row
            .get::<Option<String>, _>("state_hash")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}
