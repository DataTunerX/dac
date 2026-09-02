use crate::rpc::proto::{
    ArtifactRecord, ArtifactVersionRecord, CreateArtifactRequest, CreateArtifactResponse,
    CreateArtifactVersionRequest, CreateArtifactVersionResponse, GetArtifactVersionAsOfRequest,
    GetArtifactVersionAsOfResponse, GetArtifactVersionByIdRequest, GetArtifactVersionByIdResponse,
};
use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct ArtifactStore {
    pool: PgPool,
}

impl ArtifactStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn create_artifact(
        &self,
        req: CreateArtifactRequest,
    ) -> Result<CreateArtifactResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO artifact (artifact_type, name, description)
            VALUES ($1, $2, $3)
            RETURNING artifact_id::text, artifact_type, name, description, created_at
            "#,
        )
        .bind(&req.artifact_type)
        .bind(&req.name)
        .bind(&req.description)
        .fetch_one(&self.pool)
        .await?;

        Ok(CreateArtifactResponse {
            artifact: Some(map_artifact_row(&row)),
        })
    }

    pub async fn create_artifact_version(
        &self,
        req: CreateArtifactVersionRequest,
    ) -> Result<CreateArtifactVersionResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        // Handle UUID conversions
        let artifact_id = uuid::Uuid::parse_str(&req.artifact_id)
            .map_err(|e| sqlx::Error::Protocol(e.to_string()))?;
        let author_id = if req.author_id.is_empty() {
            None
        } else {
            Some(
                uuid::Uuid::parse_str(&req.author_id)
                    .map_err(|e| sqlx::Error::Protocol(e.to_string()))?,
            )
        };
        let approver_id = if req.approver_id.is_empty() {
            None
        } else {
            Some(
                uuid::Uuid::parse_str(&req.approver_id)
                    .map_err(|e| sqlx::Error::Protocol(e.to_string()))?,
            )
        };

        let row = sqlx::query(
            r#"
            INSERT INTO artifact_version (
                artifact_id, version_number, status, valid_from, valid_to, system_from,
                content_ref, content_hash, author_id, approver_id
            )
            VALUES (
                $1,
                $2,
                $3,
                $4::timestamptz,
                $5::timestamptz,
                $6::timestamptz,
                $7,
                $8,
                $9,
                $10
            )
            RETURNING artifact_version_id::text, artifact_id::text, version_number::int4 AS version_number, status::text,
                      valid_from, valid_to, system_from, system_to, content_ref, content_hash,
                      author_id::text, approver_id::text, created_at
            "#,
        )
        .bind(artifact_id)
        .bind(req.version_number)
        .bind(&req.status)
        .bind(&req.valid_from)
        .bind(if req.valid_to.is_empty() { None } else { Some(&req.valid_to) })
        .bind(&req.system_from)
        .bind(&req.content_ref)
        .bind(if req.content_hash.is_empty() { None } else { Some(&req.content_hash) })
        .bind(author_id)
        .bind(approver_id)
        .fetch_one(&mut *tx)
        .await?;

        tx.commit().await?;

        Ok(CreateArtifactVersionResponse {
            version: Some(map_artifact_version_row(&row)),
        })
    }

    pub async fn get_artifact_version_as_of(
        &self,
        req: GetArtifactVersionAsOfRequest,
    ) -> Result<GetArtifactVersionAsOfResponse, sqlx::Error> {
        let artifact_id = uuid::Uuid::parse_str(&req.artifact_id)
            .map_err(|e| sqlx::Error::Protocol(e.to_string()))?;

        let row = sqlx::query(
            r#"
            SELECT artifact_version_id::text, artifact_id::text, version_number::int4 AS version_number, status::text,
                   valid_from, valid_to, system_from, system_to, content_ref, content_hash,
                   author_id::text, approver_id::text, created_at
            FROM artifact_version
            WHERE artifact_id = $1
              AND valid_from <= $2::timestamptz
              AND (valid_to IS NULL OR valid_to > $2::timestamptz)
            ORDER BY valid_from DESC, created_at DESC
            LIMIT 1
            "#,
        )
        .bind(artifact_id)
        .bind(&req.as_of_valid_time)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetArtifactVersionAsOfResponse {
            version: row.map(|r| map_artifact_version_row(&r)),
        })
    }

    pub async fn get_artifact_version_by_id(
        &self,
        req: GetArtifactVersionByIdRequest,
    ) -> Result<GetArtifactVersionByIdResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT artifact_version_id::text, artifact_id::text, version_number::int4 AS version_number, status,
                   valid_from, valid_to, system_from, system_to,
                   content_ref, content_hash, author_id::text, approver_id::text, created_at
            FROM artifact_version
            WHERE artifact_version_id = $1::uuid
            "#,
        )
        .bind(&req.artifact_version_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetArtifactVersionByIdResponse {
            version: row.map(|r| map_artifact_version_row(&r)),
        })
    }
}

fn map_artifact_row(row: &sqlx::postgres::PgRow) -> ArtifactRecord {
    use sqlx::Row;
    ArtifactRecord {
        artifact_id: row.get("artifact_id"),
        artifact_type: row.get("artifact_type"),
        name: row.get("name"),
        description: row
            .get::<Option<String>, _>("description")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}

fn map_artifact_version_row(row: &sqlx::postgres::PgRow) -> ArtifactVersionRecord {
    use sqlx::Row;
    ArtifactVersionRecord {
        artifact_version_id: row.get("artifact_version_id"),
        artifact_id: row.get("artifact_id"),
        version_number: row.get("version_number"),
        status: row.get("status"),
        valid_from: row
            .get::<chrono::DateTime<chrono::Utc>, _>("valid_from")
            .to_rfc3339(),
        valid_to: row
            .get::<Option<chrono::DateTime<chrono::Utc>>, _>("valid_to")
            .map(|t| t.to_rfc3339())
            .unwrap_or_default(),
        system_from: row
            .get::<chrono::DateTime<chrono::Utc>, _>("system_from")
            .to_rfc3339(),
        system_to: row
            .get::<Option<chrono::DateTime<chrono::Utc>>, _>("system_to")
            .map(|t| t.to_rfc3339())
            .unwrap_or_default(),
        content_ref: row.get("content_ref"),
        content_hash: row
            .get::<Option<String>, _>("content_hash")
            .unwrap_or_default(),
        author_id: row
            .get::<Option<String>, _>("author_id")
            .unwrap_or_default(),
        approver_id: row
            .get::<Option<String>, _>("approver_id")
            .unwrap_or_default(),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
    }
}
