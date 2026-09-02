use serde_json::{Value, json};
use sqlx::{PgPool, Row};

use crate::persist::ontology_store::OntologyStore;

const SEMANTIC_QUALIFIER_PROPERTY_ID: &str = "tdb.qualifier.payload";
const SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID: &str = "tdb.ref.legacy_event";

pub async fn load_fact_history_payload(
    pool: &PgPool,
    fact_id: i64,
    stream_id_filter: Option<&str>,
    evidence_limit: usize,
) -> Result<Option<Value>, sqlx::Error> {
    if let Some(row) = sqlx::query(
        r#"
        SELECT
          fact_id,
          src_concept_id,
          predicate,
          dst_concept_id,
          qualifier_json,
          confidence,
          extractor,
          status,
          review_note,
          valid_from,
          valid_to,
          created_at,
          updated_at
        FROM ontology_fact
        WHERE fact_id = $1
        "#,
    )
    .bind(fact_id)
    .fetch_optional(pool)
    .await?
    {
        let store = OntologyStore::from_pool(pool.clone());
        store
            .backfill_semantic_kernel_for_legacy_fact_ids(&[fact_id])
            .await?;
        return build_legacy_fact_history_payload(pool, row, fact_id, stream_id_filter, evidence_limit).await.map(Some);
    }

    let Some(row) = sqlx::query(
        r#"
        SELECT
          ss.statement_id,
          COALESCE((ss.metadata_json->>'legacy_fact_id')::bigint, 0) AS fact_id,
          ss.subject_id AS src_concept_id,
          ss.property_id AS predicate,
          ss.value_entity_id AS dst_concept_id,
          COALESCE(sq.value_json, '{}'::jsonb) AS qualifier_json,
          ss.confidence,
          COALESCE(NULLIF(ss.metadata_json->>'legacy_extractor', ''), ss.created_by, '') AS extractor,
          CASE ss.status
            WHEN 'extracted' THEN 'candidate'
            WHEN 'accepted' THEN 'accepted'
            WHEN 'reviewed' THEN 'needs_review'
            WHEN 'rejected' THEN 'rejected'
            WHEN 'deprecated' THEN 'rejected'
            ELSE 'candidate'
          END AS status,
          COALESCE(ss.metadata_json->>'legacy_review_note', '') AS review_note,
          ss.created_at,
          ss.updated_at
        FROM semantic_statement ss
        LEFT JOIN statement_qualifier sq
          ON sq.statement_id = ss.statement_id
         AND sq.property_id = $2
        WHERE ss.metadata_json @> jsonb_build_object('legacy_fact_id', to_jsonb($1::bigint))
        ORDER BY ss.updated_at DESC
        LIMIT 1
        "#,
    )
    .bind(fact_id)
    .bind(SEMANTIC_QUALIFIER_PROPERTY_ID)
    .fetch_optional(pool)
    .await?
    else {
        return Ok(None);
    };

    let statement_id: uuid::Uuid = row.try_get("statement_id")?;

    let evidence_rows = if let Some(stream_id) = stream_id_filter {
        sqlx::query(
            r#"
            SELECT
              COALESCE(sr.legacy_stream_id, sr.value_json->>'stream_id', '') AS stream_id,
              COALESCE(sr.legacy_event_id, sr.value_json->>'event_id', '') AS event_id,
              sr.value_json->>'asset_id' AS asset_id,
              NULLIF(sr.value_json->>'version_number', '')::bigint AS version_number,
              sr.source_span,
              COALESCE(sr.value_json->'evidence_json', '{}'::jsonb) AS evidence_json,
              COALESCE((sr.value_json->>'confidence')::double precision, 0.0) AS confidence,
              sr.created_at,
              sr.created_at AS updated_at
            FROM statement_reference sr
            WHERE sr.statement_id = $1
              AND sr.property_id = $2
              AND COALESCE(sr.legacy_stream_id, sr.value_json->>'stream_id', '') = $3
            ORDER BY sr.ordinal ASC, sr.created_at DESC
            LIMIT $4
            "#,
        )
        .bind(statement_id)
        .bind(SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID)
        .bind(stream_id)
        .bind(evidence_limit as i64)
        .fetch_all(pool)
        .await?
    } else {
        sqlx::query(
            r#"
            SELECT
              COALESCE(sr.legacy_stream_id, sr.value_json->>'stream_id', '') AS stream_id,
              COALESCE(sr.legacy_event_id, sr.value_json->>'event_id', '') AS event_id,
              sr.value_json->>'asset_id' AS asset_id,
              NULLIF(sr.value_json->>'version_number', '')::bigint AS version_number,
              sr.source_span,
              COALESCE(sr.value_json->'evidence_json', '{}'::jsonb) AS evidence_json,
              COALESCE((sr.value_json->>'confidence')::double precision, 0.0) AS confidence,
              sr.created_at,
              sr.created_at AS updated_at
            FROM statement_reference sr
            WHERE sr.statement_id = $1
              AND sr.property_id = $2
            ORDER BY sr.ordinal ASC, sr.created_at DESC
            LIMIT $3
            "#,
        )
        .bind(statement_id)
        .bind(SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID)
        .bind(evidence_limit as i64)
        .fetch_all(pool)
        .await?
    };

    let review_rows = sqlx::query(
        r#"
        SELECT review_id, reviewer, decision, note, created_at
        FROM ontology_fact_review
        WHERE fact_id = $1
        ORDER BY created_at DESC
        "#,
    )
    .bind(fact_id)
    .fetch_all(pool)
    .await?;

    let evidence = map_evidence_rows(evidence_rows);
    Ok(Some(json!({
        "fact": {
            "fact_id": row.try_get::<i64, _>("fact_id").unwrap_or(0),
            "src_concept_id": row.try_get::<String, _>("src_concept_id").unwrap_or_default(),
            "predicate": row.try_get::<String, _>("predicate").unwrap_or_default(),
            "dst_concept_id": row.try_get::<String, _>("dst_concept_id").unwrap_or_default(),
            "qualifier_json": row.try_get::<serde_json::Value, _>("qualifier_json").unwrap_or(json!({})),
            "confidence": row.try_get::<f64, _>("confidence").unwrap_or(0.0),
            "extractor": row.try_get::<String, _>("extractor").unwrap_or_default(),
            "status": row.try_get::<String, _>("status").unwrap_or_default(),
            "review_note": row.try_get::<String, _>("review_note").unwrap_or_default(),
            "valid_from": Value::Null,
            "valid_to": Value::Null,
            "created_at": row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
            "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
        },
        "reviews": map_review_rows(review_rows),
        "evidence": evidence.clone(),
        "evidence_count": evidence.len(),
        "stream_id_filter": stream_id_filter,
    })))
}

async fn build_legacy_fact_history_payload(
    pool: &PgPool,
    fact_row: sqlx::postgres::PgRow,
    fact_id: i64,
    stream_id_filter: Option<&str>,
    evidence_limit: usize,
) -> Result<Value, sqlx::Error> {
    let evidence_rows = if let Some(stream_id) = stream_id_filter {
        sqlx::query(
            r#"
            SELECT
              stream_id,
              event_id,
              asset_id,
              version_number,
              source_span,
              evidence_json,
              confidence,
              created_at,
              updated_at
            FROM ontology_fact_evidence
            WHERE fact_id = $1
              AND stream_id = $2
            ORDER BY updated_at DESC
            LIMIT $3
            "#,
        )
        .bind(fact_id)
        .bind(stream_id)
        .bind(evidence_limit as i64)
        .fetch_all(pool)
        .await?
    } else {
        sqlx::query(
            r#"
            SELECT
              stream_id,
              event_id,
              asset_id,
              version_number,
              source_span,
              evidence_json,
              confidence,
              created_at,
              updated_at
            FROM ontology_fact_evidence
            WHERE fact_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            "#,
        )
        .bind(fact_id)
        .bind(evidence_limit as i64)
        .fetch_all(pool)
        .await?
    };

    let review_rows = sqlx::query(
        r#"
        SELECT review_id, reviewer, decision, note, created_at
        FROM ontology_fact_review
        WHERE fact_id = $1
        ORDER BY created_at DESC
        "#,
    )
    .bind(fact_id)
    .fetch_all(pool)
    .await?;

    let evidence = map_evidence_rows(evidence_rows);
    Ok(json!({
        "fact": {
            "fact_id": fact_row.try_get::<i64, _>("fact_id").unwrap_or(0),
            "src_concept_id": fact_row.try_get::<String, _>("src_concept_id").unwrap_or_default(),
            "predicate": fact_row.try_get::<String, _>("predicate").unwrap_or_default(),
            "dst_concept_id": fact_row.try_get::<String, _>("dst_concept_id").unwrap_or_default(),
            "qualifier_json": fact_row.try_get::<serde_json::Value, _>("qualifier_json").unwrap_or(json!({})),
            "confidence": fact_row.try_get::<f64, _>("confidence").unwrap_or(0.0),
            "extractor": fact_row.try_get::<String, _>("extractor").unwrap_or_default(),
            "status": fact_row.try_get::<String, _>("status").unwrap_or_default(),
            "review_note": fact_row.try_get::<String, _>("review_note").unwrap_or_default(),
            "valid_from": fact_row.try_get::<Option<time::OffsetDateTime>, _>("valid_from").ok().flatten().map(|t| t.to_string()),
            "valid_to": fact_row.try_get::<Option<time::OffsetDateTime>, _>("valid_to").ok().flatten().map(|t| t.to_string()),
            "created_at": fact_row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
            "updated_at": fact_row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
        },
        "reviews": map_review_rows(review_rows),
        "evidence": evidence.clone(),
        "evidence_count": evidence.len(),
        "stream_id_filter": stream_id_filter,
    }))
}

fn map_evidence_rows(rows: Vec<sqlx::postgres::PgRow>) -> Vec<Value> {
    rows.into_iter()
        .map(|row| {
            json!({
                "stream_id": row.try_get::<String, _>("stream_id").unwrap_or_default(),
                "event_id": row.try_get::<String, _>("event_id").unwrap_or_default(),
                "asset_id": row.try_get::<Option<String>, _>("asset_id").ok().flatten(),
                "version_number": row.try_get::<Option<i64>, _>("version_number").ok().flatten(),
                "source_span": row.try_get::<Option<String>, _>("source_span").ok().flatten(),
                "evidence_json": row.try_get::<serde_json::Value, _>("evidence_json").unwrap_or(json!({})),
                "confidence": row.try_get::<f64, _>("confidence").unwrap_or(0.0),
                "created_at": row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
            })
        })
        .collect()
}

fn map_review_rows(rows: Vec<sqlx::postgres::PgRow>) -> Vec<Value> {
    rows.into_iter()
        .map(|row| {
            json!({
                "review_id": row.try_get::<i64, _>("review_id").unwrap_or(0),
                "reviewer": row.try_get::<String, _>("reviewer").unwrap_or_default(),
                "decision": row.try_get::<String, _>("decision").unwrap_or_default(),
                "note": row.try_get::<String, _>("note").unwrap_or_default(),
                "created_at": row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
            })
        })
        .collect()
}
