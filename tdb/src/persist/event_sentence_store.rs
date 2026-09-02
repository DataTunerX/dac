use serde::Serialize;
use sqlx::{PgPool, Row};

const MAX_SENTENCE_CHARS: usize = 1024;

#[derive(Debug, Clone, Serialize)]
pub struct EventSentenceRow {
    pub sent_index: i32,
    pub start_char: i32,
    pub end_char: i32,
    pub sentence_text: String,
    pub text_hash: String,
    pub seg_version: String,
}

#[derive(Debug, Clone, Serialize, Default)]
pub struct SegmentEventSentenceStats {
    pub scanned: u64,
    pub updated_events: u64,
    pub inserted_sentences: u64,
    pub deleted_sentences: u64,
    pub skipped_empty_text: u64,
}

#[derive(Debug, Clone)]
struct SegmentCandidate {
    stream_id: String,
    event_id: String,
    text: String,
    text_hash: String,
}

#[derive(Debug, Clone)]
struct SentenceSpan {
    start_char: usize,
    end_char: usize,
    sentence_text: String,
}

pub struct EventSentenceStore {
    pool: PgPool,
}

impl EventSentenceStore {
    pub async fn new(database_url: &str) -> Result<Self, sqlx::Error> {
        let pool = PgPool::connect(database_url).await?;
        let this = Self { pool };
        this.validate_schema().await?;
        Ok(this)
    }

    async fn validate_schema(&self) -> Result<(), sqlx::Error> {
        require_relations(
            &self.pool,
            &[
                "event_sentence",
                "event_sentence_state",
                "idx_event_sentence_stream_event",
                "idx_event_sentence_stream_event_span",
                "idx_event_sentence_stream_event_hash",
                "idx_event_sentence_span_range_gist",
                "idx_event_sentence_span_gist",
                "idx_event_sentence_state_updated",
                "idx_event_sentence_state_hash",
            ],
            "event sentence schema objects",
        )
        .await?;
        require_columns(
            &self.pool,
            &[
                ("event_sentence", "text_hash"),
                ("event_sentence", "span_range"),
                ("event_sentence", "span"),
                ("event_sentence_state", "text_hash"),
                ("event_sentence_state", "seg_version"),
            ],
            "event sentence schema columns",
        )
        .await?;
        require_constraints(
            &self.pool,
            &[
                ("event_sentence", "ck_event_sentence_positive_span"),
                ("event_sentence", "ck_event_sentence_hash_hex32"),
                ("event_sentence_state", "ck_event_sentence_state_hash_hex32"),
            ],
            "event sentence schema constraints",
        )
        .await
    }

    pub async fn segment_events(
        &self,
        stream_id: Option<&str>,
        limit: Option<usize>,
        seg_version: &str,
    ) -> Result<SegmentEventSentenceStats, sqlx::Error> {
        let candidates = self
            .fetch_changed_events(stream_id, limit, seg_version)
            .await?;
        let mut stats = SegmentEventSentenceStats::default();

        for candidate in candidates {
            stats.scanned += 1;
            if candidate.text.is_empty() {
                stats.skipped_empty_text += 1;
            }

            let spans = split_sentences_with_spans(&candidate.text);
            let mut tx = self.pool.begin().await?;
            let deleted = sqlx::query(
                r#"
                DELETE FROM event_sentence
                WHERE stream_id = $1 AND event_id = $2
                "#,
            )
            .bind(&candidate.stream_id)
            .bind(&candidate.event_id)
            .execute(&mut *tx)
            .await?
            .rows_affected();

            for (idx, span) in spans.iter().enumerate() {
                sqlx::query(
                    r#"
                    INSERT INTO event_sentence (
                      stream_id, event_id, sent_index, start_char, end_char,
                      sentence_text, text_hash, seg_version
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (stream_id, event_id, sent_index) DO UPDATE SET
                      start_char = EXCLUDED.start_char,
                      end_char = EXCLUDED.end_char,
                      sentence_text = EXCLUDED.sentence_text,
                      text_hash = EXCLUDED.text_hash,
                      seg_version = EXCLUDED.seg_version,
                      updated_at = NOW()
                    "#,
                )
                .bind(&candidate.stream_id)
                .bind(&candidate.event_id)
                .bind(idx as i32)
                .bind(span.start_char as i32)
                .bind(span.end_char as i32)
                .bind(&span.sentence_text)
                .bind(&candidate.text_hash)
                .bind(seg_version)
                .execute(&mut *tx)
                .await?;
            }

            sqlx::query(
                r#"
                INSERT INTO event_sentence_state (stream_id, event_id, text_hash, seg_version, sentence_count)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (stream_id, event_id) DO UPDATE SET
                  text_hash = EXCLUDED.text_hash,
                  seg_version = EXCLUDED.seg_version,
                  sentence_count = EXCLUDED.sentence_count,
                  updated_at = NOW()
                "#,
            )
            .bind(&candidate.stream_id)
            .bind(&candidate.event_id)
            .bind(&candidate.text_hash)
            .bind(seg_version)
            .bind(spans.len() as i32)
            .execute(&mut *tx)
            .await?;
            tx.commit().await?;

            stats.updated_events += 1;
            stats.deleted_sentences += deleted;
            stats.inserted_sentences += spans.len() as u64;
        }

        Ok(stats)
    }

    async fn fetch_changed_events(
        &self,
        stream_id: Option<&str>,
        limit: Option<usize>,
        seg_version: &str,
    ) -> Result<Vec<SegmentCandidate>, sqlx::Error> {
        let limit_i64 = limit.map(|v| v as i64).unwrap_or(0);
        let rows = sqlx::query(
            r#"
            SELECT
              d.stream_id,
              d.event_id::TEXT AS event_id,
              d.content AS text,
              md5(d.content) AS text_hash
            FROM search_document d
            LEFT JOIN event_sentence_state ss
              ON ss.stream_id = d.stream_id
             AND ss.event_id = d.event_id::TEXT
            WHERE d.stream_id IS NOT NULL
              AND ($1::TEXT IS NULL OR d.stream_id = $1)
              AND (
                ss.stream_id IS NULL
                OR TRIM(ss.text_hash) <> md5(d.content)
                OR ss.seg_version <> $2
              )
            ORDER BY d.updated_at DESC
            LIMIT CASE WHEN $3::BIGINT > 0 THEN $3 ELSE 9223372036854775807 END
            "#,
        )
        .bind(stream_id)
        .bind(seg_version)
        .bind(limit_i64)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|row| SegmentCandidate {
                stream_id: row.try_get("stream_id").unwrap_or_default(),
                event_id: row.try_get("event_id").unwrap_or_default(),
                text: row.try_get("text").unwrap_or_default(),
                text_hash: row
                    .try_get::<String, _>("text_hash")
                    .unwrap_or_default()
                    .trim()
                    .to_ascii_lowercase(),
            })
            .collect())
    }

    pub async fn locate_span(
        &self,
        stream_id: &str,
        event_id: &str,
        start_char: i32,
        end_char: i32,
    ) -> Result<Vec<EventSentenceRow>, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT sent_index, start_char, end_char, sentence_text, text_hash, seg_version
            FROM event_sentence
            WHERE stream_id = $1
              AND event_id = $2
              AND span && int4range($3, $4, '[)')
            ORDER BY sent_index
            "#,
        )
        .bind(stream_id)
        .bind(event_id)
        .bind(start_char)
        .bind(end_char)
        .fetch_all(&self.pool)
        .await?;

        Ok(rows
            .into_iter()
            .map(|row| EventSentenceRow {
                sent_index: row.try_get("sent_index").unwrap_or_default(),
                start_char: row.try_get("start_char").unwrap_or_default(),
                end_char: row.try_get("end_char").unwrap_or_default(),
                sentence_text: row.try_get("sentence_text").unwrap_or_default(),
                text_hash: row.try_get("text_hash").unwrap_or_default(),
                seg_version: row.try_get("seg_version").unwrap_or_default(),
            })
            .collect())
    }
}

fn split_sentences_with_spans(text: &str) -> Vec<SentenceSpan> {
    if text.is_empty() {
        return Vec::new();
    }
    let chars: Vec<char> = text.chars().collect();
    let byte_offsets = build_char_byte_offsets(text, chars.len());
    let mut raw_spans: Vec<SentenceSpan> = Vec::new();

    let mut start = 0usize;
    let mut i = 0usize;
    while i < chars.len() {
        if is_sentence_terminator(chars[i]) {
            let mut end = i + 1;
            while end < chars.len() && is_sentence_terminator(chars[end]) {
                end += 1;
            }
            while end < chars.len() && is_trailing_closer(chars[end]) {
                end += 1;
            }
            if end > start {
                raw_spans.push(SentenceSpan {
                    start_char: start,
                    end_char: end,
                    sentence_text: text[byte_offsets[start]..byte_offsets[end]].to_string(),
                });
            }
            start = end;
            i = end;
            continue;
        }
        i += 1;
    }

    if start < chars.len() {
        raw_spans.push(SentenceSpan {
            start_char: start,
            end_char: chars.len(),
            sentence_text: text[byte_offsets[start]..byte_offsets[chars.len()]].to_string(),
        });
    }
    let merged = merge_tiny_fragments(raw_spans);
    enforce_max_sentence_chars(merged, text, &byte_offsets)
}

async fn require_relations(
    pool: &PgPool,
    relations: &[&str],
    label: &str,
) -> Result<(), sqlx::Error> {
    let mut missing = Vec::new();
    for relation in relations {
        let row = sqlx::query(
            r#"
            SELECT to_regclass($1) IS NOT NULL AS present
            "#,
        )
        .bind(relation)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(*relation);
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required {label}: {}. Apply db/migrations_v2 first; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

async fn require_columns(
    pool: &PgPool,
    columns: &[(&str, &str)],
    label: &str,
) -> Result<(), sqlx::Error> {
    let mut missing = Vec::new();
    for (table_name, column_name) in columns {
        let row = sqlx::query(
            r#"
            SELECT EXISTS (
              SELECT 1
              FROM information_schema.columns
              WHERE table_schema = 'public'
                AND table_name = $1
                AND column_name = $2
            ) AS present
            "#,
        )
        .bind(*table_name)
        .bind(*column_name)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(format!("{table_name}.{column_name}"));
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required {label}: {}. Apply db/migrations_v2 first; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

async fn require_constraints(
    pool: &PgPool,
    constraints: &[(&str, &str)],
    label: &str,
) -> Result<(), sqlx::Error> {
    let mut missing = Vec::new();
    for (table_name, constraint_name) in constraints {
        let row = sqlx::query(
            r#"
            SELECT EXISTS (
              SELECT 1
              FROM pg_constraint c
              JOIN pg_class t ON t.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = t.relnamespace
              WHERE n.nspname = 'public'
                AND t.relname = $1
                AND c.conname = $2
            ) AS present
            "#,
        )
        .bind(*table_name)
        .bind(*constraint_name)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(format!("{table_name}.{constraint_name}"));
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required {label}: {}. Apply db/migrations_v2 first; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

fn build_char_byte_offsets(text: &str, char_len: usize) -> Vec<usize> {
    let mut offsets = Vec::with_capacity(char_len + 1);
    for (idx, _) in text.char_indices() {
        offsets.push(idx);
    }
    offsets.push(text.len());
    offsets
}

fn is_sentence_terminator(ch: char) -> bool {
    matches!(ch, '。' | '！' | '？' | '；' | '…' | '.' | '!' | '?' | ';')
}

fn is_trailing_closer(ch: char) -> bool {
    matches!(
        ch,
        '"' | '\'' | ')' | ']' | '}' | '”' | '’' | '）' | '】' | '』' | '》' | '」'
    )
}

fn merge_tiny_fragments(spans: Vec<SentenceSpan>) -> Vec<SentenceSpan> {
    if spans.is_empty() {
        return spans;
    }
    let mut merged: Vec<SentenceSpan> = Vec::with_capacity(spans.len());
    for span in spans {
        if is_tiny_fragment(&span.sentence_text) {
            if let Some(last) = merged.last_mut() {
                last.end_char = span.end_char;
                last.sentence_text.push_str(&span.sentence_text);
                continue;
            }
        }
        merged.push(span);
    }

    if merged.len() > 1 && is_tiny_fragment(&merged[0].sentence_text) {
        let first = merged.remove(0);
        if let Some(next) = merged.first_mut() {
            next.start_char = first.start_char;
            next.sentence_text = format!("{}{}", first.sentence_text, next.sentence_text);
        }
    }
    merged
}

fn enforce_max_sentence_chars(
    spans: Vec<SentenceSpan>,
    text: &str,
    byte_offsets: &[usize],
) -> Vec<SentenceSpan> {
    let mut out: Vec<SentenceSpan> = Vec::new();
    for span in spans {
        let len = span.end_char.saturating_sub(span.start_char);
        if len <= MAX_SENTENCE_CHARS {
            out.push(span);
            continue;
        }
        let mut cur = span.start_char;
        while cur < span.end_char {
            let next = (cur + MAX_SENTENCE_CHARS).min(span.end_char);
            out.push(SentenceSpan {
                start_char: cur,
                end_char: next,
                sentence_text: text[byte_offsets[cur]..byte_offsets[next]].to_string(),
            });
            cur = next;
        }
    }
    out
}

fn is_tiny_fragment(text: &str) -> bool {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return true;
    }
    let char_count = trimmed.chars().count();
    if char_count >= 3 {
        return false;
    }
    trimmed
        .chars()
        .all(|ch| ch.is_ascii_punctuation() || is_sentence_terminator(ch) || is_trailing_closer(ch))
}

#[cfg(test)]
mod tests {
    use super::split_sentences_with_spans;

    #[test]
    fn sentence_split_preserves_text_roundtrip() {
        let text = "八戒偷吃了人参果。悟空说：“你又吃了？”随后二人离开。";
        let spans = split_sentences_with_spans(text);
        assert_eq!(spans.len(), 3);
        let merged = spans
            .iter()
            .map(|s| s.sentence_text.clone())
            .collect::<Vec<_>>()
            .join("");
        assert_eq!(merged, text);
    }

    #[test]
    fn sentence_split_generates_valid_spans() {
        let text = "A... B!? C；D";
        let spans = split_sentences_with_spans(text);
        assert!(!spans.is_empty());
        let char_len = text.chars().count();
        for s in spans {
            assert!(s.start_char < s.end_char);
            assert!(s.end_char <= char_len);
        }
    }

    #[test]
    fn sentence_split_forces_long_sentence_chunking() {
        let text = "a".repeat(2500);
        let spans = split_sentences_with_spans(&text);
        assert!(spans.len() >= 3);
        let merged = spans
            .into_iter()
            .map(|s| s.sentence_text)
            .collect::<String>();
        assert_eq!(merged, text);
    }
}
