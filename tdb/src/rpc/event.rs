use crate::rpc::proto::{
    AppendEventRequest, AppendEventResponse, EventItem, EventSentenceRecord,
    GetEventSentencesRequest, GetEventSentencesResponse, GetEventsRequest, GetEventsResponse,
};
use crate::rpc::search::{IndexEventInput, SearchStore};
use serde_json::Value;
use sqlx::{PgPool, Row};
use uuid::Uuid;

#[derive(Clone)]
pub struct EventStore {
    pool: PgPool,
    search: SearchStore,
}

impl EventStore {
    pub fn new(pool: PgPool, search: SearchStore) -> Self {
        Self { pool, search }
    }

    pub async fn append(
        &self,
        req: AppendEventRequest,
    ) -> Result<AppendEventResponse, sqlx::Error> {
        let mut tx = self.pool.begin().await?;

        // 1. Resolve case_id
        let case_id = if !req.case_id.is_empty() {
            req.case_id.clone()
        } else {
            // uuid_generate_v5('6ba7b811-9dad-11d1-80b4-00c04fd430c8', stream_id)
            let namespace = Uuid::parse_str("6ba7b811-9dad-11d1-80b4-00c04fd430c8").unwrap();
            Uuid::new_v5(&namespace, req.stream_id.as_bytes()).to_string()
        };

        // 2. Upsert case_context if stream_id is provided
        if !req.stream_id.is_empty() {
            sqlx::query(
                r#"
                INSERT INTO case_context (case_id, stream_id, updated_at)
                VALUES ($1::uuid, $2, NOW())
                ON CONFLICT (case_id) DO UPDATE SET
                  updated_at = NOW()
                WHERE case_context.stream_id = EXCLUDED.stream_id
                "#,
            )
            .bind(&case_id)
            .bind(&req.stream_id)
            .execute(&mut *tx)
            .await?;
        }

        // 3. Allocate next_event_seq
        let event_seq: i64 = sqlx::query(
            r#"
            INSERT INTO case_seq (case_id, next_event_seq, updated_at)
            VALUES ($1::uuid, 1, NOW())
            ON CONFLICT (case_id) DO UPDATE
              SET next_event_seq = case_seq.next_event_seq + 1,
                  updated_at = NOW()
            RETURNING next_event_seq
            "#,
        )
        .bind(&case_id)
        .fetch_one(&mut *tx)
        .await?
        .get("next_event_seq");

        // 4. Insert event
        let payload: Value = serde_json::from_str(&req.payload_json)
            .map_err(|e| sqlx::Error::Protocol(format!("invalid payload JSON: {e}")))?;

        let row = sqlx::query(
            r#"
            INSERT INTO case_event_ledger (
              case_id, event_seq, event_type, actor_id, subject_id, object_id,
              payload, valid_time, system_time
            ) VALUES (
              $1::uuid, $2, $3, $4::uuid, $5::uuid, $6::uuid, $7,
              $8::timestamptz, COALESCE($9::timestamptz, NOW())
            )
            RETURNING event_id::text, system_time::text
            "#,
        )
        .bind(&case_id)
        .bind(event_seq)
        .bind(&req.event_type)
        .bind(if req.actor_id.is_empty() {
            None
        } else {
            Some(&req.actor_id)
        })
        .bind(if req.subject_id.is_empty() {
            None
        } else {
            Some(&req.subject_id)
        })
        .bind(if req.object_id.is_empty() {
            None
        } else {
            Some(&req.object_id)
        })
        .bind(payload)
        .bind(&req.valid_time)
        .bind(if req.system_time.is_empty() {
            None
        } else {
            Some(&req.system_time)
        })
        .fetch_one(&mut *tx)
        .await?;

        let event_id: String = row.get("event_id");
        let system_time: String = row.get("system_time");

        tx.commit().await?;

        // 5. Index event if needed
        if !req.event_text.is_empty() {
            let index_input = IndexEventInput {
                case_id: case_id.clone(),
                stream_id: req.stream_id.clone(),
                event_id: event_id.clone(),
                event_seq: event_seq as i32,
                content: req.event_text.clone(),
                metadata: serde_json::from_str(&req.payload_json).unwrap_or(Value::Null),
                embedding: if req.embedding.is_empty() {
                    None
                } else {
                    Some(req.embedding.clone())
                },
                embedding_model: Some(req.embedding_model.clone()),
            };
            let _ = self.search.index(&index_input).await;
        }

        Ok(AppendEventResponse {
            event_id,
            event_seq: event_seq as i32,
            system_time,
        })
    }

    pub async fn get_events(
        &self,
        req: GetEventsRequest,
    ) -> Result<GetEventsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT
              event_id::text, case_id::text, event_seq, event_type,
              actor_id::text, subject_id::text, object_id::text,
              payload, valid_time::text, system_time::text
            FROM case_event_ledger
            WHERE case_id = $1::uuid
              AND (event_seq >= $2 OR $2 = 0)
              AND (event_seq <= $3 OR $3 = 0)
            ORDER BY event_seq ASC
            LIMIT $4
            "#,
        )
        .bind(&req.case_id)
        .bind(req.from_seq)
        .bind(req.to_seq)
        .bind(if req.limit > 0 { req.limit } else { 200 })
        .fetch_all(&self.pool)
        .await?;

        let events = rows
            .into_iter()
            .map(|row| EventItem {
                event_id: row.get("event_id"),
                case_id: row.get("case_id"),
                event_seq: row.get::<i64, _>("event_seq") as i32,
                event_type: row.get("event_type"),
                actor_id: row.get::<Option<String>, _>("actor_id").unwrap_or_default(),
                subject_id: row
                    .get::<Option<String>, _>("subject_id")
                    .unwrap_or_default(),
                object_id: row
                    .get::<Option<String>, _>("object_id")
                    .unwrap_or_default(),
                payload_json: row.get::<Value, _>("payload").to_string(),
                valid_time: row.get("valid_time"),
                system_time: row.get("system_time"),
            })
            .collect();

        Ok(GetEventsResponse { events })
    }

    pub async fn get_event_sentences(
        &self,
        req: GetEventSentencesRequest,
    ) -> Result<GetEventSentencesResponse, sqlx::Error> {
        let limit = if req.limit > 0 { req.limit } else { 500 };
        let rows = sqlx::query(
            r#"
            SELECT stream_id, event_id::text, sent_index, start_char, end_char, sentence_text
            FROM event_sentence
            WHERE stream_id = $1
            ORDER BY event_id, sent_index ASC
            LIMIT $2
            "#,
        )
        .bind(&req.stream_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await?;

        let sentences = rows
            .into_iter()
            .map(|row| EventSentenceRecord {
                stream_id: row.get("stream_id"),
                event_id: row.get("event_id"),
                sent_index: row.get("sent_index"),
                start_char: row.get::<Option<i32>, _>("start_char").unwrap_or(0),
                end_char: row.get::<Option<i32>, _>("end_char").unwrap_or(0),
                sentence_text: row.get("sentence_text"),
            })
            .collect();

        Ok(GetEventSentencesResponse { sentences })
    }
}
