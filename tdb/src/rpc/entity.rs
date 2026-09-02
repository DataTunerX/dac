use crate::rpc::proto::{
    EntityRecord, GetEntityRequest, GetEntityResponse, ListEntitiesRequest, ListEntitiesResponse,
    UpsertEntityRequest, UpsertEntityResponse,
};
use sqlx::PgPool;

#[derive(Debug, Clone)]
pub struct EntityStore {
    pool: PgPool,
}

impl EntityStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_entity(
        &self,
        req: UpsertEntityRequest,
    ) -> Result<UpsertEntityResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO entity (entity_id, entity_type, display_name, external_refs, status)
            VALUES ($1::uuid, $2, $3, $4::jsonb, $5)
            ON CONFLICT (entity_id) DO UPDATE SET
                entity_type = EXCLUDED.entity_type,
                display_name = EXCLUDED.display_name,
                external_refs = EXCLUDED.external_refs,
                status = EXCLUDED.status,
                updated_at = NOW()
            RETURNING entity_id::text, entity_type, display_name, external_refs::text as external_refs_json, status::text, created_at, updated_at
            "#,
        )
        .bind(&req.entity_id)
        .bind(&req.entity_type)
        .bind(&req.display_name)
        .bind(&req.external_refs_json)
        .bind(&req.status)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEntityResponse {
            entity: Some(map_entity_row(&row)),
        })
    }

    pub async fn get_entity(
        &self,
        req: GetEntityRequest,
    ) -> Result<GetEntityResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT entity_id::text, entity_type, display_name, external_refs::text as external_refs_json, status::text, created_at, updated_at
            FROM entity
            WHERE entity_id = $1::uuid
            "#,
        )
        .bind(&req.entity_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetEntityResponse {
            entity: row.map(|r| map_entity_row(&r)),
        })
    }

    pub async fn list_entities(
        &self,
        req: ListEntitiesRequest,
    ) -> Result<ListEntitiesResponse, sqlx::Error> {
        let mut query = String::from(
            "SELECT entity_id::text, entity_type, display_name, external_refs::text as external_refs_json, status::text, created_at, updated_at FROM entity WHERE 1=1",
        );
        let mut params_count = 0;

        if !req.entity_type.is_empty() {
            params_count += 1;
            query.push_str(&format!(" AND entity_type = ${}", params_count));
        }

        if !req.status.is_empty() {
            params_count += 1;
            query.push_str(&format!(" AND status = ${}", params_count));
        }

        if !req.query.is_empty() {
            params_count += 1;
            query.push_str(&format!(
                " AND (display_name ILIKE ${} OR entity_id::text ILIKE ${})",
                params_count, params_count
            ));
        }

        query.push_str(" ORDER BY updated_at DESC");

        params_count += 1;
        query.push_str(&format!(" LIMIT ${}", params_count));

        params_count += 1;
        query.push_str(&format!(" OFFSET ${}", params_count));

        let mut sql_query = sqlx::query(&query);

        if !req.entity_type.is_empty() {
            sql_query = sql_query.bind(&req.entity_type);
        }
        if !req.status.is_empty() {
            sql_query = sql_query.bind(&req.status);
        }
        if !req.query.is_empty() {
            let q = format!("%{}%", req.query);
            sql_query = sql_query.bind(q);
        }

        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;

        let entities = rows.into_iter().map(|r| map_entity_row(&r)).collect();
        Ok(ListEntitiesResponse { entities })
    }
}

fn map_entity_row(row: &sqlx::postgres::PgRow) -> EntityRecord {
    use sqlx::Row;
    EntityRecord {
        entity_id: row.get("entity_id"),
        entity_type: row.get("entity_type"),
        display_name: row.get("display_name"),
        external_refs_json: row
            .get::<Option<String>, _>("external_refs_json")
            .unwrap_or_else(|| "{}".to_string()),
        status: row.get("status"),
        created_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("created_at")
            .to_rfc3339(),
        updated_at: row
            .get::<chrono::DateTime<chrono::Utc>, _>("updated_at")
            .to_rfc3339(),
    }
}
