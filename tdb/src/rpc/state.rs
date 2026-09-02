use crate::rpc::proto::{
    EdgeRecord, GetEdgesAsOfRequest, GetEdgesAsOfResponse, GetPropertyAsOfRequest,
    GetPropertyAsOfResponse, PropertyRecord, UpsertEdgeRequest, UpsertEdgeResponse,
    UpsertPropertyRequest, UpsertPropertyResponse,
};
use serde_json::Value;
use sqlx::{PgPool, Row};

#[derive(Clone)]
pub struct StateStore {
    pool: PgPool,
}

impl StateStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_property(
        &self,
        req: UpsertPropertyRequest,
    ) -> Result<UpsertPropertyResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        let now = chrono::Utc::now().to_rfc3339();
        let requested_system_from = if req.system_from.is_empty() {
            &now
        } else {
            &req.system_from
        };

        // 1. Get latest open system_from to ensure monotonicity
        let latest_open: Option<String> = sqlx::query(
            r#"
            SELECT MAX(system_from)::text AS system_from
            FROM property_state
            WHERE object_id = $1::uuid AND prop_key = $2 AND system_to IS NULL
            "#,
        )
        .bind(&req.object_id)
        .bind(&req.key)
        .fetch_optional(&mut *tx)
        .await?
        .and_then(|row| row.get("system_from"));

        let effective_system_from =
            monotonic_system_from(requested_system_from, latest_open.as_deref());

        // 2. Close open intervals
        sqlx::query(
            r#"
            UPDATE property_state
            SET valid_to = CASE
                  WHEN valid_from < $1::timestamptz
                  THEN $1::timestamptz
                  ELSE valid_to
                END,
                system_to = $2::timestamptz
            WHERE object_id = $3::uuid
              AND prop_key = $4
              AND valid_to IS NULL
              AND system_to IS NULL
            "#,
        )
        .bind(&req.valid_from)
        .bind(&effective_system_from)
        .bind(&req.object_id)
        .bind(&req.key)
        .execute(&mut *tx)
        .await?;

        // 3. Insert new state
        let value: Value = serde_json::from_str(&req.value_json)
            .map_err(|e| sqlx::Error::Protocol(format!("invalid value JSON: {e}")))?;

        let row = sqlx::query(
            r#"
            INSERT INTO property_state (
              object_id, prop_key, prop_value, valid_from, system_from, source_event_id, confidence
            ) VALUES (
              $1::uuid, $2, $3, $4::timestamptz, $5::timestamptz, $6::uuid, $7
            )
            RETURNING
              property_state_id::text, object_id::text, prop_key as key, prop_value as value,
              valid_from::text, valid_to::text, system_from::text, system_to::text,
              source_event_id::text, confidence
            "#,
        )
        .bind(&req.object_id)
        .bind(&req.key)
        .bind(value)
        .bind(&req.valid_from)
        .bind(&effective_system_from)
        .bind(if req.source_event_id.is_empty() {
            None
        } else {
            Some(&req.source_event_id)
        })
        .bind(req.confidence as f64)
        .fetch_one(&mut *tx)
        .await?;

        let property = map_property_row(&row);
        tx.commit().await?;

        Ok(UpsertPropertyResponse {
            property: Some(property),
        })
    }

    pub async fn get_property_as_of(
        &self,
        req: GetPropertyAsOfRequest,
    ) -> Result<GetPropertyAsOfResponse, sqlx::Error> {
        let now = chrono::Utc::now().to_rfc3339();
        let as_of_system = if req.as_of_system_time.is_empty() {
            &now
        } else {
            &req.as_of_system_time
        };

        let rows = sqlx::query(
            r#"
            SELECT
              property_state_id::text, object_id::text, prop_key as key, prop_value as value,
              valid_from::text, valid_to::text, system_from::text, system_to::text,
              source_event_id::text, confidence
            FROM property_state
            WHERE object_id = $1::uuid
              AND prop_key = $2
              AND valid_from <= $3::timestamptz
              AND (valid_to IS NULL OR valid_to > $3::timestamptz)
              AND system_from <= $4::timestamptz
              AND (system_to IS NULL OR system_to > $4::timestamptz)
            ORDER BY valid_from DESC, system_from DESC, created_at DESC
            LIMIT 2
            "#,
        )
        .bind(&req.object_id)
        .bind(&req.key)
        .bind(&req.as_of_valid_time)
        .bind(as_of_system)
        .fetch_all(&self.pool)
        .await?;

        if rows.is_empty() {
            return Ok(GetPropertyAsOfResponse { property: None });
        }

        // Logic check: if rows.len() > 1, check for ambiguity (same as TS)
        // But for now, just return the first one as a baseline.
        let property = map_property_row(&rows[0]);
        Ok(GetPropertyAsOfResponse {
            property: Some(property),
        })
    }

    pub async fn upsert_edge(
        &self,
        req: UpsertEdgeRequest,
    ) -> Result<UpsertEdgeResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        let now = chrono::Utc::now().to_rfc3339();
        let requested_system_from = if req.system_from.is_empty() {
            &now
        } else {
            &req.system_from
        };

        // 1. Get latest open system_from
        let latest_open: Option<String> = sqlx::query(
            r#"
            SELECT MAX(system_from)::text AS system_from
            FROM edge_state
            WHERE src_id = $1::uuid AND predicate = $2 AND dst_id = $3::uuid AND system_to IS NULL
            "#,
        )
        .bind(&req.src_id)
        .bind(&req.predicate)
        .bind(&req.dst_id)
        .fetch_optional(&mut *tx)
        .await?
        .and_then(|row| row.get("system_from"));

        let effective_system_from =
            monotonic_system_from(requested_system_from, latest_open.as_deref());

        // 2. Close open intervals
        sqlx::query(
            r#"
            UPDATE edge_state
            SET valid_to = CASE
                  WHEN valid_from < $1::timestamptz
                  THEN $1::timestamptz
                  ELSE valid_to
                END,
                system_to = $2::timestamptz
            WHERE src_id = $3::uuid
              AND predicate = $4
              AND dst_id = $5::uuid
              AND valid_to IS NULL
              AND system_to IS NULL
            "#,
        )
        .bind(&req.valid_from)
        .bind(&effective_system_from)
        .bind(&req.src_id)
        .bind(&req.predicate)
        .bind(&req.dst_id)
        .execute(&mut *tx)
        .await?;

        // 3. Insert new state
        let row = sqlx::query(
            r#"
            INSERT INTO edge_state (
              src_id, predicate, dst_id, valid_from, system_from, source_event_id, confidence
            ) VALUES (
              $1::uuid, $2, $3::uuid, $4::timestamptz, $5::timestamptz, $6::uuid, $7
            )
            RETURNING
              edge_state_id::text, src_id::text, predicate, dst_id::text,
              valid_from::text, valid_to::text, system_from::text, system_to::text,
              source_event_id::text, confidence
            "#,
        )
        .bind(&req.src_id)
        .bind(&req.predicate)
        .bind(&req.dst_id)
        .bind(&req.valid_from)
        .bind(&effective_system_from)
        .bind(if req.source_event_id.is_empty() {
            None
        } else {
            Some(&req.source_event_id)
        })
        .bind(req.confidence as f64)
        .fetch_one(&mut *tx)
        .await?;

        let edge = map_edge_row(&row);
        tx.commit().await?;

        Ok(UpsertEdgeResponse { edge: Some(edge) })
    }

    pub async fn get_edges_as_of(
        &self,
        req: GetEdgesAsOfRequest,
    ) -> Result<GetEdgesAsOfResponse, sqlx::Error> {
        let now = chrono::Utc::now().to_rfc3339();
        let as_of_system = if req.as_of_system_time.is_empty() {
            &now
        } else {
            &req.as_of_system_time
        };

        let mut query_str = String::from(
            r#"
            SELECT
              edge_state_id::text, src_id::text, predicate, dst_id::text,
              valid_from::text, valid_to::text, system_from::text, system_to::text,
              source_event_id::text, confidence
            FROM edge_state
            WHERE src_id = $1::uuid
            "#,
        );

        if !req.predicate.is_empty() {
            query_str.push_str(" AND predicate = $2 ");
        } else {
            query_str.push_str(" AND ($2 = $2) "); // placeholder
        }

        query_str.push_str(
            r#"
              AND valid_from <= $3::timestamptz
              AND (valid_to IS NULL OR valid_to > $3::timestamptz)
              AND system_from <= $4::timestamptz
              AND (system_to IS NULL OR system_to > $4::timestamptz)
            ORDER BY valid_from DESC, system_from DESC, created_at DESC
            LIMIT 1000
            "#,
        );

        let rows = sqlx::query(&query_str)
            .bind(&req.src_id)
            .bind(&req.predicate)
            .bind(&req.as_of_valid_time)
            .bind(as_of_system)
            .fetch_all(&self.pool)
            .await?;

        let edges = rows.into_iter().map(|row| map_edge_row(&row)).collect();
        Ok(GetEdgesAsOfResponse { edges })
    }

    pub async fn list_property_rows(
        &self,
        req: crate::rpc::proto::ListPropertyRowsRequest,
    ) -> Result<crate::rpc::proto::ListPropertyRowsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT
              property_state_id::text, object_id::text, prop_key as key, prop_value as value,
              valid_from::text, valid_to::text, system_from::text, system_to::text,
              source_event_id::text, confidence
            FROM property_state
            WHERE object_id = $1::uuid
              AND prop_key = $2
            ORDER BY valid_from DESC, system_from DESC, created_at DESC
            LIMIT $3
            "#,
        )
        .bind(&req.object_id)
        .bind(&req.key)
        .bind(if req.limit > 0 { req.limit } else { 10 })
        .fetch_all(&self.pool)
        .await?;

        let properties = rows.into_iter().map(|row| map_property_row(&row)).collect();
        Ok(crate::rpc::proto::ListPropertyRowsResponse { properties })
    }
}

fn monotonic_system_from(requested_iso: &str, latest_open_iso: Option<&str>) -> String {
    let latest_open_iso = match latest_open_iso {
        Some(iso) => iso,
        None => return requested_iso.to_string(),
    };

    let requested_ms = chrono::DateTime::parse_from_rfc3339(requested_iso)
        .map(|dt| dt.timestamp_millis())
        .unwrap_or(0);
    let latest_open_ms = chrono::DateTime::parse_from_rfc3339(latest_open_iso)
        .map(|dt| dt.timestamp_millis())
        .unwrap_or(0);

    if requested_ms > latest_open_ms {
        requested_iso.to_string()
    } else {
        // Ensure strict monotonicity
        chrono::DateTime::from_timestamp_millis(latest_open_ms + 1)
            .unwrap()
            .to_rfc3339()
    }
}

fn map_property_row(row: &sqlx::postgres::PgRow) -> PropertyRecord {
    PropertyRecord {
        property_state_id: row.get("property_state_id"),
        object_id: row.get("object_id"),
        key: row.get("key"),
        value_json: row.get::<Value, _>("value").to_string(),
        valid_from: row.get("valid_from"),
        valid_to: row.get::<Option<String>, _>("valid_to").unwrap_or_default(),
        system_from: row.get("system_from"),
        system_to: row
            .get::<Option<String>, _>("system_to")
            .unwrap_or_default(),
        source_event_id: row
            .get::<Option<String>, _>("source_event_id")
            .unwrap_or_default(),
        confidence: row.get::<Option<f64>, _>("confidence").unwrap_or(0.0) as f32,
    }
}

fn map_edge_row(row: &sqlx::postgres::PgRow) -> EdgeRecord {
    EdgeRecord {
        edge_state_id: row.get("edge_state_id"),
        src_id: row.get("src_id"),
        predicate: row.get("predicate"),
        dst_id: row.get("dst_id"),
        valid_from: row.get("valid_from"),
        valid_to: row.get::<Option<String>, _>("valid_to").unwrap_or_default(),
        system_from: row.get("system_from"),
        system_to: row
            .get::<Option<String>, _>("system_to")
            .unwrap_or_default(),
        source_event_id: row
            .get::<Option<String>, _>("source_event_id")
            .unwrap_or_default(),
        confidence: row.get::<Option<f64>, _>("confidence").unwrap_or(0.0) as f32,
    }
}
