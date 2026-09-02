use serde_json::Value;
use sqlx::{PgPool, Row};

use crate::rpc::gateway_backend::GatewayBackendError;
use crate::rpc::proto::{
    DomainStreamBindingRecord, IndexEventRequest, SearchHit, SearchQueryRequest,
    UpsertDomainStreamBindingRequest,
};
use crate::rpc::stream_filter::stream_array_match;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SearchMode {
    Lexical,
    Vector,
    Hybrid,
}

impl SearchMode {
    pub fn from_wire(raw: &str) -> Result<Self, GatewayBackendError> {
        match raw.trim() {
            "" | "hybrid" => Ok(Self::Hybrid),
            "lexical" => Ok(Self::Lexical),
            "vector" => Ok(Self::Vector),
            other => Err(GatewayBackendError::invalid_argument(format!(
                "unsupported search mode: {other}"
            ))),
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Lexical => "lexical",
            Self::Vector => "vector",
            Self::Hybrid => "hybrid",
        }
    }
}

#[derive(Debug, Clone)]
pub struct SearchQueryInput {
    pub query_text: String,
    pub domain: Option<String>,
    pub case_id: Option<String>,
    pub stream_ids: Vec<String>,
    pub resolved_stream_ids: Vec<String>,
    pub stream_prefix: bool,
    pub mode: SearchMode,
    pub limit: i32,
    pub query_embedding: Option<Vec<f64>>,
    pub alpha: f64,
}

impl SearchQueryInput {
    pub fn from_proto(request: SearchQueryRequest) -> Result<Self, GatewayBackendError> {
        let query_text = request.query.trim().to_string();
        if query_text.is_empty() {
            return Err(GatewayBackendError::invalid_argument("query is required"));
        }

        let stream_ids = if !request.stream_ids.is_empty() {
            request
                .stream_ids
                .into_iter()
                .map(|stream_id| stream_id.trim().to_string())
                .filter(|stream_id| !stream_id.is_empty())
                .collect()
        } else {
            let stream_id = request.stream_id.trim().to_string();
            if stream_id.is_empty() {
                Vec::new()
            } else {
                vec![stream_id]
            }
        };

        Ok(Self {
            query_text,
            domain: non_empty(request.domain),
            case_id: non_empty(request.case_id),
            stream_ids,
            resolved_stream_ids: Vec::new(),
            stream_prefix: request.stream_prefix,
            mode: SearchMode::from_wire(&request.mode)?,
            limit: if request.limit <= 0 {
                30
            } else {
                request.limit.min(200)
            },
            query_embedding: if request.query_embedding.is_empty() {
                None
            } else {
                Some(request.query_embedding)
            },
            alpha: if (0.0..=1.0).contains(&request.alpha) && request.alpha != 0.0 {
                request.alpha
            } else {
                0.7
            },
        })
    }
}

#[derive(Debug, Clone)]
pub struct IndexEventInput {
    pub case_id: String,
    pub stream_id: String,
    pub event_id: String,
    pub event_seq: i32,
    pub content: String,
    pub metadata: Value,
    pub embedding: Option<Vec<f64>>,
    pub embedding_model: Option<String>,
}

impl IndexEventInput {
    pub fn from_proto(request: IndexEventRequest) -> Result<Self, GatewayBackendError> {
        let metadata = if request.metadata_json.trim().is_empty() {
            Value::Object(serde_json::Map::new())
        } else {
            serde_json::from_str(&request.metadata_json).map_err(|err| {
                GatewayBackendError::invalid_argument(format!("invalid metadata_json: {err}"))
            })?
        };

        Ok(Self {
            case_id: request.case_id,
            stream_id: request.stream_id,
            event_id: request.event_id,
            event_seq: request.event_seq,
            content: request.content,
            metadata,
            embedding: if request.embedding.is_empty() {
                None
            } else {
                Some(request.embedding)
            },
            embedding_model: non_empty(request.embedding_model),
        })
    }
}

#[derive(Debug, Clone)]
pub struct SearchHitRow {
    pub doc_id: String,
    pub case_id: String,
    pub stream_id: Option<String>,
    pub event_id: String,
    pub event_seq: i32,
    pub content: String,
    pub metadata: Value,
    pub lexical_score: f64,
    pub vector_score: f64,
    pub hybrid_score: f64,
}

#[derive(Debug, Clone)]
pub struct DomainStreamBindingRow {
    pub binding_id: String,
    pub domain: String,
    pub stream_id: String,
    pub status: String,
    pub binding_kind: String,
    pub source: String,
    pub priority: i32,
    pub created_at: String,
    pub updated_at: String,
}

impl From<DomainStreamBindingRow> for DomainStreamBindingRecord {
    fn from(value: DomainStreamBindingRow) -> Self {
        Self {
            binding_id: value.binding_id,
            domain: value.domain,
            stream_id: value.stream_id,
            status: value.status,
            binding_kind: value.binding_kind,
            source: value.source,
            priority: value.priority,
            created_at: value.created_at,
            updated_at: value.updated_at,
        }
    }
}

impl From<SearchHitRow> for SearchHit {
    fn from(value: SearchHitRow) -> Self {
        Self {
            doc_id: value.doc_id,
            case_id: value.case_id,
            stream_id: value.stream_id.unwrap_or_default(),
            event_id: value.event_id,
            event_seq: value.event_seq,
            content: value.content,
            metadata_json: serde_json::to_string(&value.metadata).unwrap_or_else(|_| "{}".into()),
            lexical_score: value.lexical_score,
            vector_score: value.vector_score,
            hybrid_score: value.hybrid_score,
        }
    }
}

#[derive(Clone)]
pub struct SearchStore {
    pool: PgPool,
}

impl SearchStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn resolve_domain_stream_scope(
        &self,
        input: &mut SearchQueryInput,
    ) -> Result<(), GatewayBackendError> {
        let Some(domain) = input.domain.clone() else {
            input.resolved_stream_ids = input.stream_ids.clone();
            return Ok(());
        };

        let rows = sqlx::query(
            r#"
            SELECT stream_id
            FROM domain_stream_binding
            WHERE domain = $1
              AND status = 'active'
              AND binding_kind IN ('primary', 'auxiliary')
            ORDER BY priority ASC, stream_id ASC
            "#,
        )
        .bind(&domain)
        .fetch_all(&self.pool)
        .await
        .map_err(|err| {
            GatewayBackendError::internal(format!(
                "resolve domain stream binding failed for {domain}: {err}"
            ))
        })?;

        let domain_stream_ids: Vec<String> = rows
            .into_iter()
            .filter_map(|row| row.try_get::<Option<String>, _>("stream_id").ok().flatten())
            .filter(|stream_id| !stream_id.trim().is_empty())
            .collect();

        if input.stream_ids.is_empty() {
            input.stream_ids = domain_stream_ids.clone();
            input.resolved_stream_ids = domain_stream_ids;
            return Ok(());
        }

        let requested: std::collections::HashSet<&str> =
            input.stream_ids.iter().map(String::as_str).collect();
        let allowed: std::collections::HashSet<&str> =
            domain_stream_ids.iter().map(String::as_str).collect();
        let missing: Vec<String> = requested
            .difference(&allowed)
            .map(|stream_id| (*stream_id).to_string())
            .collect();

        if !missing.is_empty() {
            return Err(GatewayBackendError::invalid_argument(format!(
                "stream_id does not belong to domain {domain}: {}",
                missing.join(", ")
            )));
        }

        input.resolved_stream_ids = input.stream_ids.clone();
        Ok(())
    }

    pub async fn upsert_domain_stream_binding(
        &self,
        req: &UpsertDomainStreamBindingRequest,
    ) -> Result<DomainStreamBindingRow, GatewayBackendError> {
        let domain = req.domain.trim();
        let stream_id = req.stream_id.trim();
        if domain.is_empty() || stream_id.is_empty() {
            return Err(GatewayBackendError::invalid_argument(
                "domain and stream_id are required",
            ));
        }

        let status = match req.status.trim() {
            "" | "active" => "active",
            "inactive" => "inactive",
            other => {
                return Err(GatewayBackendError::invalid_argument(format!(
                    "unsupported binding status: {other}"
                )));
            }
        };
        let binding_kind = match req.binding_kind.trim() {
            "" | "primary" => "primary",
            "auxiliary" | "eval" | "debug" => req.binding_kind.trim(),
            other => {
                return Err(GatewayBackendError::invalid_argument(format!(
                    "unsupported binding kind: {other}"
                )));
            }
        };
        let source = if req.source.trim().is_empty() {
            "manual"
        } else {
            req.source.trim()
        };
        let priority = if req.priority <= 0 { 100 } else { req.priority };

        let row = sqlx::query(
            r#"
            INSERT INTO domain_stream_binding (
              domain, stream_id, status, binding_kind, source, priority, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (domain, stream_id) DO UPDATE SET
              status = EXCLUDED.status,
              binding_kind = EXCLUDED.binding_kind,
              source = EXCLUDED.source,
              priority = EXCLUDED.priority,
              updated_at = NOW()
            RETURNING
              binding_id::text AS binding_id,
              domain,
              stream_id,
              status,
              binding_kind,
              source,
              priority,
              created_at::text AS created_at,
              updated_at::text AS updated_at
            "#,
        )
        .bind(domain)
        .bind(stream_id)
        .bind(status)
        .bind(binding_kind)
        .bind(source)
        .bind(priority)
        .fetch_one(&self.pool)
        .await
        .map_err(|err| {
            GatewayBackendError::internal(format!(
                "upsert domain stream binding failed for {domain}/{stream_id}: {err}"
            ))
        })?;

        Ok(DomainStreamBindingRow {
            binding_id: row.get("binding_id"),
            domain: row.get("domain"),
            stream_id: row.get("stream_id"),
            status: row.get("status"),
            binding_kind: row.get("binding_kind"),
            source: row.get("source"),
            priority: row.get("priority"),
            created_at: row.get("created_at"),
            updated_at: row.get("updated_at"),
        })
    }

    pub async fn list_domain_stream_bindings(
        &self,
        domain: Option<&str>,
        stream_id: Option<&str>,
        status: Option<&str>,
        limit: i32,
    ) -> Result<Vec<DomainStreamBindingRow>, GatewayBackendError> {
        let rows = sqlx::query(
            r#"
            SELECT
              binding_id::text AS binding_id,
              domain,
              stream_id,
              status,
              binding_kind,
              source,
              priority,
              created_at::text AS created_at,
              updated_at::text AS updated_at
            FROM domain_stream_binding
            WHERE ($1::text IS NULL OR domain = $1)
              AND ($2::text IS NULL OR stream_id = $2)
              AND ($3::text IS NULL OR status = $3)
            ORDER BY domain ASC, priority ASC, stream_id ASC
            LIMIT $4
            "#,
        )
        .bind(domain)
        .bind(stream_id)
        .bind(status)
        .bind(if limit <= 0 { 100 } else { limit.min(500) })
        .fetch_all(&self.pool)
        .await
        .map_err(|err| {
            GatewayBackendError::internal(format!("list domain stream bindings failed: {err}"))
        })?;

        Ok(rows
            .into_iter()
            .map(|row| DomainStreamBindingRow {
                binding_id: row.get("binding_id"),
                domain: row.get("domain"),
                stream_id: row.get("stream_id"),
                status: row.get("status"),
                binding_kind: row.get("binding_kind"),
                source: row.get("source"),
                priority: row.get("priority"),
                created_at: row.get("created_at"),
                updated_at: row.get("updated_at"),
            })
            .collect())
    }

    pub async fn search(&self, input: &SearchQueryInput) -> Result<Vec<SearchHitRow>, sqlx::Error> {
        let lexical_enabled = input.mode != SearchMode::Vector;
        let vector_enabled = input.mode != SearchMode::Lexical
            && input
                .query_embedding
                .as_ref()
                .map(|values| !values.is_empty())
                .unwrap_or(false);

        // Stream filter fragment ($3 is the text[] of stream ids). Exact match by
        // default; dot-delimited namespace prefix match when stream_prefix is set.
        // Injected into the static SQL below — no extra bind/positional parameter.
        let stream_clause = stream_array_match("d.stream_id", 3, input.stream_prefix);

        // Use two separate SQL paths to avoid CAST($N AS vector) when no embedding is
        // provided. PostgreSQL infers $N must be of type `vector` from the CAST, so
        // binding NULL/text fails even when the CASE branch is never reached.
        let rows = if vector_enabled {
            let vector_literal = input
                .query_embedding
                .as_ref()
                .map(|values| {
                    format!(
                        "[{}]",
                        values
                            .iter()
                            .map(|v| v.to_string())
                            .collect::<Vec<_>>()
                            .join(",")
                    )
                })
                .unwrap_or_default();

            sqlx::query(&format!(
                r#"
                WITH lexical AS (
                  SELECT
                    d.doc_id::text AS doc_id,
                    CASE
                      WHEN $4::boolean IS TRUE
                      THEN ts_rank_cd(to_tsvector('simple', d.content), plainto_tsquery('simple', $1))
                      ELSE 0.0
                    END AS lexical_score
                  FROM search_document d
                  WHERE ($2::uuid IS NULL OR d.case_id = $2::uuid)
                    AND (
                      COALESCE(array_length($3::text[], 1), 0) = 0
                      OR {stream_clause}
                    )
                    AND (
                      $4::boolean IS FALSE
                      OR to_tsvector('simple', d.content) @@ plainto_tsquery('simple', $1)
                    )
                ),
                vector_part AS (
                  SELECT
                    d.doc_id::text AS doc_id,
                    CASE
                      WHEN e.embedding IS NOT NULL
                      THEN GREATEST(0.0, 1 - (e.embedding <=> $5::vector))
                      ELSE 0.0
                    END AS vector_score
                  FROM search_document d
                  LEFT JOIN search_embedding e ON e.doc_id = d.doc_id
                  WHERE ($2::uuid IS NULL OR d.case_id = $2::uuid)
                    AND (
                      COALESCE(array_length($3::text[], 1), 0) = 0
                      OR {stream_clause}
                    )
                )
                SELECT
                  d.doc_id::text AS doc_id,
                  d.case_id::text AS case_id,
                  d.stream_id,
                  d.event_id::text AS event_id,
                  d.event_seq,
                  d.content,
                  d.metadata,
                  COALESCE(l.lexical_score, 0.0)::float8 AS lexical_score,
                  COALESCE(v.vector_score, 0.0)::float8 AS vector_score,
                  CASE
                    WHEN $8::text = 'lexical' THEN COALESCE(l.lexical_score, 0.0)::float8
                    WHEN $8::text = 'vector'  THEN COALESCE(v.vector_score, 0.0)::float8
                    ELSE (
                      ($6::float8 * COALESCE(l.lexical_score, 0.0)::float8)
                      + ((1.0 - $6::float8) * COALESCE(v.vector_score, 0.0)::float8)
                    )::float8
                  END AS hybrid_score
                FROM search_document d
                LEFT JOIN lexical l ON l.doc_id = d.doc_id::text
                LEFT JOIN vector_part v ON v.doc_id = d.doc_id::text
                WHERE ($2::uuid IS NULL OR d.case_id = $2::uuid)
                  AND (
                    COALESCE(array_length($3::text[], 1), 0) = 0
                    OR {stream_clause}
                  )
                ORDER BY hybrid_score DESC, d.event_seq DESC
                LIMIT $7
                "#,
            ))
            .bind(&input.query_text)
            .bind(input.case_id.as_deref())
            .bind(&input.stream_ids)
            .bind(lexical_enabled)
            .bind(vector_literal)
            .bind(input.alpha)
            .bind(i64::from(input.limit))
            .bind(input.mode.as_str())
            .fetch_all(&self.pool)
            .await?
        } else {
            // Lexical-only path — no vector CTE, no vector parameter needed.
            sqlx::query(&format!(
                r#"
                WITH lexical AS (
                  SELECT
                    d.doc_id::text AS doc_id,
                    CASE
                      WHEN $4::boolean IS TRUE
                      THEN ts_rank_cd(to_tsvector('simple', d.content), plainto_tsquery('simple', $1))
                      ELSE 0.0
                    END AS lexical_score
                  FROM search_document d
                  WHERE ($2::uuid IS NULL OR d.case_id = $2::uuid)
                    AND (
                      COALESCE(array_length($3::text[], 1), 0) = 0
                      OR {stream_clause}
                    )
                    AND (
                      $4::boolean IS FALSE
                      OR to_tsvector('simple', d.content) @@ plainto_tsquery('simple', $1)
                    )
                )
                SELECT
                  d.doc_id::text AS doc_id,
                  d.case_id::text AS case_id,
                  d.stream_id,
                  d.event_id::text AS event_id,
                  d.event_seq,
                  d.content,
                  d.metadata,
                  COALESCE(l.lexical_score, 0.0)::float8 AS lexical_score,
                  0.0::float8 AS vector_score,
                  COALESCE(l.lexical_score, 0.0)::float8 AS hybrid_score
                FROM search_document d
                JOIN lexical l ON l.doc_id = d.doc_id::text
                WHERE ($2::uuid IS NULL OR d.case_id = $2::uuid)
                  AND (
                    COALESCE(array_length($3::text[], 1), 0) = 0
                    OR {stream_clause}
                  )
                ORDER BY hybrid_score DESC, d.event_seq DESC
                LIMIT $5
                "#,
            ))
            .bind(&input.query_text)
            .bind(input.case_id.as_deref())
            .bind(&input.stream_ids)
            .bind(lexical_enabled)
            .bind(i64::from(input.limit))
            .fetch_all(&self.pool)
            .await?
        };

        rows.into_iter()
            .map(|row| {
                Ok(SearchHitRow {
                    doc_id: row.try_get("doc_id")?,
                    case_id: row.try_get("case_id")?,
                    stream_id: row.try_get("stream_id")?,
                    event_id: row.try_get("event_id")?,
                    event_seq: row.try_get::<i64, _>("event_seq")? as i32,
                    content: row.try_get("content")?,
                    metadata: row.try_get("metadata")?,
                    lexical_score: row.try_get("lexical_score")?,
                    vector_score: row.try_get("vector_score")?,
                    hybrid_score: row.try_get("hybrid_score")?,
                })
            })
            .collect()
    }

    pub async fn index(&self, input: &IndexEventInput) -> Result<String, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        let doc_id: String = sqlx::query(
            r#"
            INSERT INTO search_document (
              case_id, stream_id, event_id, event_seq, content, metadata, updated_at
            ) VALUES (
              $1::uuid, $2, $3::uuid, $4, $5, $6, NOW()
            )
            ON CONFLICT (event_id) DO UPDATE SET
              case_id = EXCLUDED.case_id,
              stream_id = EXCLUDED.stream_id,
              event_seq = EXCLUDED.event_seq,
              content = EXCLUDED.content,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING doc_id::text
            "#,
        )
        .bind(&input.case_id)
        .bind(&input.stream_id)
        .bind(&input.event_id)
        .bind(i64::from(input.event_seq))
        .bind(&input.content)
        .bind(&input.metadata)
        .fetch_one(&mut *tx)
        .await?
        .try_get("doc_id")?;

        if let Some(embedding) = &input.embedding {
            let vector_literal = format!(
                "[{}]",
                embedding
                    .iter()
                    .map(|v| v.to_string())
                    .collect::<Vec<_>>()
                    .join(",")
            );

            sqlx::query(
                r#"
                INSERT INTO search_embedding (doc_id, embedding, embedding_model, updated_at)
                VALUES ($1::uuid, CAST($2 AS vector), $3, NOW())
                ON CONFLICT (doc_id) DO UPDATE SET
                  embedding = EXCLUDED.embedding,
                  embedding_model = EXCLUDED.embedding_model,
                  updated_at = NOW()
                "#,
            )
            .bind(&doc_id)
            .bind(vector_literal)
            .bind(&input.embedding_model)
            .execute(&mut *tx)
            .await?;
        }

        tx.commit().await?;
        Ok(doc_id)
    }

    pub async fn upsert_embedding(
        &self,
        event_id: &str,
        embedding: &[f64],
        model: &str,
    ) -> Result<(), sqlx::Error> {
        let vector_literal = format!(
            "[{}]",
            embedding
                .iter()
                .map(|v| v.to_string())
                .collect::<Vec<_>>()
                .join(",")
        );
        sqlx::query(
            r#"
            INSERT INTO search_embedding (doc_id, embedding, embedding_model, updated_at)
            SELECT doc_id, CAST($2 AS vector), $3, NOW()
            FROM search_document WHERE event_id = $1::uuid
            ON CONFLICT (doc_id) DO UPDATE SET
              embedding = EXCLUDED.embedding,
              embedding_model = EXCLUDED.embedding_model,
              updated_at = NOW()
            "#,
        )
        .bind(event_id)
        .bind(vector_literal)
        .bind(model)
        .execute(&self.pool)
        .await?;
        Ok(())
    }
}

fn non_empty(value: String) -> Option<String> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        None
    } else {
        Some(trimmed.to_string())
    }
}
