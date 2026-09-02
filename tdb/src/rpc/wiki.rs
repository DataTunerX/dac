use sqlx::PgPool;

use crate::rpc::proto::{
    AppendWikiLogRequest, AppendWikiLogResponse, GetWikiPageRequest, GetWikiPageResponse,
    LintWikiDomainRequest, LintWikiDomainResponse, ListWikiLogsRequest, ListWikiLogsResponse,
    ListWikiPagesRequest, ListWikiPagesResponse, ReinforceWikiPageRequest,
    ReinforceWikiPageResponse, SearchWikiPagesRequest, SearchWikiPagesResponse,
    UpsertWikiPageLinkRequest, UpsertWikiPageLinkResponse, UpsertWikiPageRequest,
    UpsertWikiPageResponse, WikiLintIssue, WikiLogRecord, WikiPageRecord,
};

// Convert a natural-language query to an OR-based tsquery string.
// Strips English stopwords so that "What are the products of Netapp"
// becomes "products | netapp", which matches any page containing
// either significant term rather than requiring all words to appear.
fn build_or_tsquery(query: &str) -> String {
    const STOPWORDS: &[&str] = &[
        "a", "an", "the", "and", "but", "or", "if", "in", "on", "at", "to", "for", "of", "with",
        "by", "from", "as", "is", "are", "was", "were", "be", "been", "being", "have", "has",
        "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "shall",
        "can", "what", "which", "who", "whom", "this", "that", "these", "those", "i", "me", "my",
        "we", "us", "our", "you", "your", "he", "him", "his", "she", "her", "they", "them",
        "their", "it", "its", "not", "no", "so", "up", "out", "about", "than", "how", "when",
        "where", "why", "all", "both", "each", "more", "most", "other", "some", "such", "then",
        "there", "here",
    ];
    let tokens: Vec<String> = query
        .split(|c: char| !c.is_alphanumeric() && c != '_')
        .filter(|t| t.len() > 1)
        .map(|t| t.to_lowercase())
        .filter(|t| !STOPWORDS.contains(&t.as_str()))
        .collect();
    if tokens.is_empty() {
        // Fall back to simplified form of original query
        query
            .split_whitespace()
            .filter(|t| t.len() > 1)
            .collect::<Vec<_>>()
            .join(" | ")
    } else {
        tokens.join(" | ")
    }
}

#[derive(Debug, Clone)]
pub struct WikiStore {
    pool: PgPool,
}

impl WikiStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn upsert_wiki_page(
        &self,
        req: UpsertWikiPageRequest,
    ) -> Result<UpsertWikiPageResponse, sqlx::Error> {
        let now = chrono::Utc::now().to_rfc3339();
        let tags_json = if req.tags_json.is_empty() {
            "[]".to_string()
        } else {
            req.tags_json.clone()
        };
        let confidence = if req.confidence == 0.0 {
            0.5_f64
        } else {
            req.confidence as f64
        };
        let knowledge_level = req.knowledge_level.clone();
        let authority_kind = req.authority_kind.clone();

        // ── Supersession mode ───────────────────────────────────────────────────
        // Create a new page version and link the old one via superseded_by.
        if req.supersede {
            let existing: Option<(String,)> = sqlx::query_as(
                "SELECT page_id::text FROM wiki_page WHERE domain = $1 AND slug = $2 AND superseded_by IS NULL"
            )
            .bind(&req.domain)
            .bind(&req.slug)
            .fetch_optional(&self.pool)
            .await?;

            if let Some((old_page_id,)) = existing {
                // Insert new current version (no UNIQUE conflict — old row still has superseded_by IS NULL
                // but will be updated immediately after, so we insert directly).
                // To avoid the partial unique conflict during INSERT, we first clear the old slug
                // by temporarily marking it superseded with a placeholder, then fix it up.
                // Simpler: INSERT new row with a temp slug, UPDATE old row, then fix new row's slug.
                //
                // Cleanest approach: UPDATE old row first (removes it from the partial index),
                // then INSERT new row.
                //
                // Step 1: temporarily mark old as superseded with a sentinel so it leaves the partial index.
                sqlx::query(
                    "UPDATE wiki_page SET superseded_by = page_id WHERE page_id = $1::uuid",
                )
                .bind(&old_page_id)
                .execute(&self.pool)
                .await?;

                // Step 2: INSERT new current page (unique constraint clear now).
                let new_row: (String, String) = sqlx::query_as(
                    r#"
                    INSERT INTO wiki_page (
                      domain, slug, title, content, page_type, knowledge_level, authority_kind,
                      tags, confidence, source_count, last_reinforced_at
                    )
                    VALUES ($1, $2, $3, $4, $5, NULLIF($6, ''), NULLIF($7, ''), $8::jsonb, $9, 1, $10::timestamptz)
                    RETURNING page_id::text, slug
                    "#,
                )
                .bind(&req.domain)
                .bind(&req.slug)
                .bind(&req.title)
                .bind(&req.content)
                .bind(&req.page_type)
                .bind(&knowledge_level)
                .bind(&authority_kind)
                .bind(&tags_json)
                .bind(confidence)
                .bind(&now)
                .fetch_one(&self.pool)
                .await?;

                // Step 3: point old page's superseded_by to the real new page_id.
                sqlx::query(
                    "UPDATE wiki_page SET superseded_by = $1::uuid WHERE page_id = $2::uuid",
                )
                .bind(&new_row.0)
                .bind(&old_page_id)
                .execute(&self.pool)
                .await?;

                return Ok(UpsertWikiPageResponse {
                    page_id: new_row.0,
                    slug: new_row.1,
                    status: "versioned".to_string(),
                    superseded_page_id: old_page_id,
                });
            }
            // No existing page — fall through to normal insert below.
        }

        // ── Normal upsert (ON CONFLICT with partial unique index) ───────────────
        let existing: Option<(String,)> = sqlx::query_as(
            "SELECT page_id::text FROM wiki_page WHERE domain = $1 AND slug = $2 AND superseded_by IS NULL"
        )
        .bind(&req.domain)
        .bind(&req.slug)
        .fetch_optional(&self.pool)
        .await?;

        let status = if existing.is_some() {
            "updated"
        } else {
            "created"
        };

        let row: (String, String) = sqlx::query_as(
            r#"
            INSERT INTO wiki_page (
              domain, slug, title, content, page_type, knowledge_level, authority_kind,
              tags, confidence, source_count, last_reinforced_at
            )
            VALUES ($1, $2, $3, $4, $5, NULLIF($6, ''), NULLIF($7, ''), $8::jsonb, $9, 1, $10::timestamptz)
            ON CONFLICT (domain, slug) WHERE superseded_by IS NULL DO UPDATE SET
              title              = EXCLUDED.title,
              content            = EXCLUDED.content,
              page_type          = EXCLUDED.page_type,
              knowledge_level    = EXCLUDED.knowledge_level,
              authority_kind     = EXCLUDED.authority_kind,
              tags               = EXCLUDED.tags,
              confidence         = EXCLUDED.confidence,
              source_count       = wiki_page.source_count + 1,
              last_reinforced_at = $10::timestamptz,
              updated_at         = $10::timestamptz
            RETURNING page_id::text, slug
            "#,
        )
        .bind(&req.domain)
        .bind(&req.slug)
        .bind(&req.title)
        .bind(&req.content)
        .bind(&req.page_type)
        .bind(&knowledge_level)
        .bind(&authority_kind)
        .bind(&tags_json)
        .bind(confidence)
        .bind(&now)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertWikiPageResponse {
            page_id: row.0,
            slug: row.1,
            status: status.to_string(),
            superseded_page_id: String::new(),
        })
    }

    pub async fn get_wiki_page(
        &self,
        req: GetWikiPageRequest,
    ) -> Result<GetWikiPageResponse, sqlx::Error> {
        let row: Option<(String, String, String, String, String, String, Option<String>, Option<String>, String, i32, f64, String, String, String, Option<String>)> =
            sqlx::query_as(
                r#"
                SELECT
                  page_id::text, domain, slug, title, content, page_type, knowledge_level, authority_kind,
                  tags::text, source_count, confidence,
                  last_reinforced_at::text, created_at::text, updated_at::text,
                  superseded_by::text
                FROM wiki_page
                WHERE domain = $1 AND slug = $2 AND superseded_by IS NULL
                "#,
            )
            .bind(&req.domain)
            .bind(&req.slug)
            .fetch_optional(&self.pool)
            .await?;

        let page = row.map(map_page_row);
        Ok(GetWikiPageResponse { page })
    }

    pub async fn upsert_wiki_page_link(
        &self,
        req: UpsertWikiPageLinkRequest,
    ) -> Result<UpsertWikiPageLinkResponse, sqlx::Error> {
        let from_page_id: Option<(String,)> = sqlx::query_as(
            r#"
            SELECT page_id::text
            FROM wiki_page
            WHERE domain = $1 AND slug = $2 AND superseded_by IS NULL
            "#,
        )
        .bind(&req.domain)
        .bind(&req.from_slug)
        .fetch_optional(&self.pool)
        .await?;

        let to_page_id: Option<(String,)> = sqlx::query_as(
            r#"
            SELECT page_id::text
            FROM wiki_page
            WHERE domain = $1 AND slug = $2 AND superseded_by IS NULL
            "#,
        )
        .bind(&req.domain)
        .bind(&req.to_slug)
        .fetch_optional(&self.pool)
        .await?;

        let (from_page_id, to_page_id) = match (from_page_id, to_page_id) {
            (Some((from_page_id,)), Some((to_page_id,))) => (from_page_id, to_page_id),
            _ => {
                return Ok(UpsertWikiPageLinkResponse {
                    from_page_id: String::new(),
                    to_page_id: String::new(),
                    status: "missing_page".to_string(),
                });
            }
        };

        let status = if sqlx::query_as::<_, (bool,)>(
            r#"
            SELECT EXISTS(
              SELECT 1
              FROM wiki_page_link
              WHERE from_page_id = $1::uuid AND to_page_id = $2::uuid
            )
            "#,
        )
        .bind(&from_page_id)
        .bind(&to_page_id)
        .fetch_one(&self.pool)
        .await?
        .0
        {
            "updated"
        } else {
            "created"
        };

        sqlx::query(
            r#"
            INSERT INTO wiki_page_link (from_page_id, to_page_id, link_text)
            VALUES ($1::uuid, $2::uuid, NULLIF($3, ''))
            ON CONFLICT (from_page_id, to_page_id) DO UPDATE SET
              link_text = COALESCE(EXCLUDED.link_text, wiki_page_link.link_text)
            "#,
        )
        .bind(&from_page_id)
        .bind(&to_page_id)
        .bind(&req.link_text)
        .execute(&self.pool)
        .await?;

        Ok(UpsertWikiPageLinkResponse {
            from_page_id,
            to_page_id,
            status: status.to_string(),
        })
    }

    pub async fn search_wiki_pages(
        &self,
        req: SearchWikiPagesRequest,
    ) -> Result<SearchWikiPagesResponse, sqlx::Error> {
        let limit = if req.limit <= 0 {
            20i64
        } else {
            req.limit as i64
        };

        // Build OR-based tsquery from natural-language input so queries like
        // "What are the products of Netapp" match pages containing "netapp"
        // even though "products" / stopwords don't appear in wiki content.
        let or_query = build_or_tsquery(&req.query);

        let rows: Vec<(
            String,
            String,
            String,
            String,
            String,
            String,
            Option<String>,
            Option<String>,
            String,
            i32,
            f64,
            String,
            String,
            String,
            Option<String>,
        )> = if req.page_type.is_empty()
            && req.knowledge_level.is_empty()
            && req.authority_kind.is_empty()
        {
            sqlx::query_as(
                    r#"
                    SELECT
                      page_id::text, domain, slug, title, content, page_type, knowledge_level, authority_kind,
                      tags::text, source_count, confidence,
                      last_reinforced_at::text, created_at::text, updated_at::text,
                      superseded_by::text
                    FROM wiki_page
                    WHERE domain = $1
                      AND superseded_by IS NULL
                      AND (
                        to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))
                            @@ to_tsquery('english', $2)
                        OR title ILIKE '%' || $3 || '%'
                      )
                    ORDER BY ts_rank(
                      to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,'')),
                      to_tsquery('english', $2)
                    ) DESC,
                    CASE WHEN authority_kind = 'accepted_ontology' THEN 1 ELSE 0 END DESC,
                    CASE WHEN page_type = 'concept' AND knowledge_level = 'concept_like' THEN 1 ELSE 0 END DESC,
                    updated_at DESC
                    LIMIT $4
                    "#,
                )
                .bind(&req.domain)
                .bind(&or_query)
                .bind(&req.query)
                .bind(limit)
                .fetch_all(&self.pool)
                .await?
        } else {
            sqlx::query_as(
                    r#"
                    SELECT
                      page_id::text, domain, slug, title, content, page_type, knowledge_level, authority_kind,
                      tags::text, source_count, confidence,
                      last_reinforced_at::text, created_at::text, updated_at::text,
                      superseded_by::text
                    FROM wiki_page
                    WHERE domain = $1
                      AND ($2 = '' OR page_type = $2)
                      AND superseded_by IS NULL
                      AND ($3 = '' OR knowledge_level = $3)
                      AND ($4 = '' OR authority_kind = $4)
                      AND (
                        to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,''))
                            @@ to_tsquery('english', $5)
                        OR title ILIKE '%' || $6 || '%'
                      )
                    ORDER BY ts_rank(
                      to_tsvector('english', coalesce(title,'') || ' ' || coalesce(content,'')),
                      to_tsquery('english', $5)
                    ) DESC,
                    CASE WHEN authority_kind = 'accepted_ontology' THEN 1 ELSE 0 END DESC,
                    CASE WHEN page_type = 'concept' AND knowledge_level = 'concept_like' THEN 1 ELSE 0 END DESC,
                    updated_at DESC
                    LIMIT $7
                    "#,
                )
                .bind(&req.domain)
                .bind(&req.page_type)
                .bind(&req.knowledge_level)
                .bind(&req.authority_kind)
                .bind(&or_query)
                .bind(&req.query)
                .bind(limit)
                .fetch_all(&self.pool)
                .await?
        };

        Ok(SearchWikiPagesResponse {
            pages: rows.into_iter().map(map_page_row).collect(),
        })
    }

    pub async fn list_wiki_pages(
        &self,
        req: ListWikiPagesRequest,
    ) -> Result<ListWikiPagesResponse, sqlx::Error> {
        let limit = if req.limit <= 0 {
            200i64
        } else {
            req.limit.min(1000) as i64
        };
        let offset = req.offset.max(0) as i64;
        let content_select = if req.include_content {
            "content"
        } else {
            "''::text AS content"
        };
        let base_select = format!(
            r#"
                    SELECT
                      page_id::text, domain, slug, title, {content_select}, page_type, knowledge_level, authority_kind,
                      tags::text, source_count, confidence,
                      last_reinforced_at::text, created_at::text, updated_at::text,
                      superseded_by::text
                    FROM wiki_page
            "#
        );
        let total: i64 = if req.page_type.is_empty()
            && req.knowledge_level.is_empty()
            && req.authority_kind.is_empty()
        {
            sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM wiki_page
                WHERE domain = $1 AND superseded_by IS NULL
                "#,
            )
            .bind(&req.domain)
            .fetch_one(&self.pool)
            .await?
        } else {
            sqlx::query_scalar(
                r#"
                SELECT COUNT(*)
                FROM wiki_page
                WHERE domain = $1
                  AND ($2 = '' OR page_type = $2)
                  AND ($3 = '' OR knowledge_level = $3)
                  AND ($4 = '' OR authority_kind = $4)
                  AND superseded_by IS NULL
                "#,
            )
            .bind(&req.domain)
            .bind(&req.page_type)
            .bind(&req.knowledge_level)
            .bind(&req.authority_kind)
            .fetch_one(&self.pool)
            .await?
        };
        let rows: Vec<(
            String,
            String,
            String,
            String,
            String,
            String,
            Option<String>,
            Option<String>,
            String,
            i32,
            f64,
            String,
            String,
            String,
            Option<String>,
        )> = if req.page_type.is_empty()
            && req.knowledge_level.is_empty()
            && req.authority_kind.is_empty()
        {
            sqlx::query_as(&format!(
                r#"
                    {base_select}
                    WHERE domain = $1 AND superseded_by IS NULL
                    ORDER BY page_type, title
                    LIMIT $2 OFFSET $3
                "#
            ))
                .bind(&req.domain)
                .bind(limit)
                .bind(offset)
                .fetch_all(&self.pool)
                .await?
        } else {
            sqlx::query_as(&format!(
                r#"
                    {base_select}
                    WHERE domain = $1
                      AND ($2 = '' OR page_type = $2)
                      AND ($3 = '' OR knowledge_level = $3)
                      AND ($4 = '' OR authority_kind = $4)
                      AND superseded_by IS NULL
                    ORDER BY title
                    LIMIT $5 OFFSET $6
                "#
            ))
                .bind(&req.domain)
                .bind(&req.page_type)
                .bind(&req.knowledge_level)
                .bind(&req.authority_kind)
                .bind(limit)
                .bind(offset)
                .fetch_all(&self.pool)
                .await?
        };

        Ok(ListWikiPagesResponse {
            pages: rows.into_iter().map(map_page_row).collect(),
            total: total as i32,
            limit: limit as i32,
            offset: offset as i32,
        })
    }

    pub async fn reinforce_wiki_page(
        &self,
        req: ReinforceWikiPageRequest,
    ) -> Result<ReinforceWikiPageResponse, sqlx::Error> {
        let now = chrono::Utc::now().to_rfc3339();
        let delta = if req.delta_confidence == 0.0 {
            0.05_f64
        } else {
            req.delta_confidence as f64
        };

        let row: Option<(String, String, String, String, String, String, Option<String>, Option<String>, String, i32, f64, String, String, String, Option<String>)> =
            sqlx::query_as(
                r#"
                UPDATE wiki_page
                SET
                  confidence         = LEAST(1.0, confidence + $2),
                  last_reinforced_at = $3::timestamptz,
                  updated_at         = $3::timestamptz
                WHERE page_id = $1::uuid
                RETURNING
                  page_id::text, domain, slug, title, content, page_type, knowledge_level, authority_kind,
                  tags::text, source_count, confidence,
                  last_reinforced_at::text, created_at::text, updated_at::text,
                  superseded_by::text
                "#,
            )
            .bind(&req.page_id)
            .bind(delta)
            .bind(&now)
            .fetch_optional(&self.pool)
            .await?;

        Ok(ReinforceWikiPageResponse {
            page: row.map(map_page_row),
        })
    }

    pub async fn append_wiki_log(
        &self,
        req: AppendWikiLogRequest,
    ) -> Result<AppendWikiLogResponse, sqlx::Error> {
        let source_ref: Option<&str> = if req.source_ref.is_empty() {
            None
        } else {
            Some(&req.source_ref)
        };
        let summary: Option<&str> = if req.summary.is_empty() {
            None
        } else {
            Some(&req.summary)
        };

        let row: (String, String, String, Option<String>, i32, Option<String>, String) =
            sqlx::query_as(
                r#"
                INSERT INTO wiki_operation_log (domain, action_type, source_ref, pages_touched, summary)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING log_id::text, domain, action_type, source_ref, pages_touched, summary, created_at::text
                "#,
            )
            .bind(&req.domain)
            .bind(&req.action_type)
            .bind(source_ref)
            .bind(req.pages_touched)
            .bind(summary)
            .fetch_one(&self.pool)
            .await?;

        Ok(AppendWikiLogResponse {
            log: Some(WikiLogRecord {
                log_id: row.0,
                domain: row.1,
                action_type: row.2,
                source_ref: row.3.unwrap_or_default(),
                pages_touched: row.4,
                summary: row.5.unwrap_or_default(),
                created_at: row.6,
            }),
        })
    }

    pub async fn list_wiki_logs(
        &self,
        req: ListWikiLogsRequest,
    ) -> Result<ListWikiLogsResponse, sqlx::Error> {
        let limit = if req.limit <= 0 {
            50i64
        } else {
            req.limit as i64
        };

        let rows: Vec<(String, String, String, Option<String>, i32, Option<String>, String)> =
            sqlx::query_as(
                r#"
                SELECT log_id::text, domain, action_type, source_ref, pages_touched, summary, created_at::text
                FROM wiki_operation_log
                WHERE domain = $1
                ORDER BY created_at DESC
                LIMIT $2
                "#,
            )
            .bind(&req.domain)
            .bind(limit)
            .fetch_all(&self.pool)
            .await?;

        let logs = rows
            .into_iter()
            .map(|r| WikiLogRecord {
                log_id: r.0,
                domain: r.1,
                action_type: r.2,
                source_ref: r.3.unwrap_or_default(),
                pages_touched: r.4,
                summary: r.5.unwrap_or_default(),
                created_at: r.6,
            })
            .collect();

        Ok(ListWikiLogsResponse { logs })
    }

    pub async fn lint_wiki_domain(
        &self,
        req: LintWikiDomainRequest,
    ) -> Result<LintWikiDomainResponse, sqlx::Error> {
        let mut issues: Vec<WikiLintIssue> = Vec::new();

        // 1. Orphan pages
        let orphans: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug FROM wiki_page wp
            WHERE wp.domain = $1
              AND wp.superseded_by IS NULL
              AND wp.page_type NOT IN ('index', 'log')
              AND NOT EXISTS (
                SELECT 1 FROM wiki_page_link wpl WHERE wpl.to_page_id = wp.page_id
              )
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in orphans {
            issues.push(WikiLintIssue {
                r#type: "orphan_page".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!("Page \"{slug}\" has no inbound links"),
                severity: "warning".to_string(),
            });
        }

        // 2. Stale pages
        let stale: Vec<(String, String, f64)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug, confidence FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND confidence < 0.3
              AND last_reinforced_at < NOW() - INTERVAL '30 days'
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug, confidence) in stale {
            issues.push(WikiLintIssue {
                r#type: "stale_page".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!("Page \"{slug}\" has low confidence ({confidence:.2}) and has not been reinforced in 30+ days"),
                severity: "warning".to_string(),
            });
        }

        // 3. Empty pages
        let empty: Vec<(String, String, i64)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug, char_length(content) AS len FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND char_length(content) < 20
              AND page_type NOT IN ('log')
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug, len) in empty {
            issues.push(WikiLintIssue {
                r#type: "empty_page".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!("Page \"{slug}\" has very short content ({len} chars)"),
                severity: "error".to_string(),
            });
        }

        let fact_like_without_support: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT wp.page_id::text, wp.slug
            FROM wiki_page wp
            WHERE wp.domain = $1
              AND wp.superseded_by IS NULL
              AND wp.knowledge_level = 'fact_like'
              AND COALESCE(wp.authority_kind, '') <> 'accepted_ontology'
              AND NOT EXISTS (
                SELECT 1
                FROM wiki_page_link wpl
                JOIN wiki_page other ON other.page_id IN (wpl.from_page_id, wpl.to_page_id)
                WHERE (wpl.from_page_id = wp.page_id OR wpl.to_page_id = wp.page_id)
                  AND other.page_id <> wp.page_id
                  AND other.superseded_by IS NULL
              )
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in fact_like_without_support {
            issues.push(WikiLintIssue {
                r#type: "fact_like_without_support".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is labeled fact_like but has no link support and is not accepted_ontology"
                ),
                severity: "warning".to_string(),
            });
        }

        let candidate_derived_concepts: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug
            FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND page_type = 'concept'
              AND authority_kind = 'candidate_derived'
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in candidate_derived_concepts {
            issues.push(WikiLintIssue {
                r#type: "candidate_derived_concept_page".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is a concept page but still derives from candidate_derived authority"
                ),
                severity: "warning".to_string(),
            });
        }

        let accepted_summary_mismatches: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug
            FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND page_type = 'source_summary'
              AND authority_kind = 'accepted_ontology'
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in accepted_summary_mismatches {
            issues.push(WikiLintIssue {
                r#type: "accepted_ontology_summary_mismatch".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is a source_summary page but is marked accepted_ontology"
                ),
                severity: "warning".to_string(),
            });
        }

        let weak_principles: Vec<(String, String, String)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug, knowledge_level
            FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND knowledge_level IN ('principle_like', 'theory_like')
              AND authority_kind = 'candidate_derived'
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug, knowledge_level) in weak_principles {
            issues.push(WikiLintIssue {
                r#type: "weak_principle_authority".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is marked {knowledge_level} but still derives from candidate_derived authority"
                ),
                severity: "warning".to_string(),
            });
        }

        let principle_without_method_authority: Vec<(String, String, String, Option<String>)> =
            sqlx::query_as(
                r#"
            SELECT page_id::text, slug, knowledge_level, authority_kind
            FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND knowledge_level IN ('principle_like', 'theory_like')
              AND COALESCE(authority_kind, '') <> 'methodology'
            "#,
            )
            .bind(&req.domain)
            .fetch_all(&self.pool)
            .await?;

        for (page_id, slug, knowledge_level, authority_kind) in principle_without_method_authority {
            issues.push(WikiLintIssue {
                r#type: "principle_without_method_authority".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is marked {knowledge_level} but authority_kind is {} instead of methodology",
                    authority_kind.unwrap_or_default()
                ),
                severity: "info".to_string(),
            });
        }

        let accepted_concept_mismatches: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT page_id::text, slug
            FROM wiki_page
            WHERE domain = $1
              AND superseded_by IS NULL
              AND page_type = 'concept'
              AND authority_kind = 'accepted_ontology'
              AND knowledge_level = 'fact_like'
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in accepted_concept_mismatches {
            issues.push(WikiLintIssue {
                r#type: "accepted_concept_level_mismatch".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is an accepted ontology concept but is labeled fact_like instead of concept_like"
                ),
                severity: "warning".to_string(),
            });
        }

        let generalization_without_multi_support: Vec<(String, String, i64)> = sqlx::query_as(
            r#"
            SELECT
              wp.page_id::text,
              wp.slug,
              COUNT(DISTINCT other.page_id)::bigint AS support_count
            FROM wiki_page wp
            LEFT JOIN wiki_page_link wpl
              ON (wpl.from_page_id = wp.page_id OR wpl.to_page_id = wp.page_id)
            LEFT JOIN wiki_page other
              ON other.page_id IN (wpl.from_page_id, wpl.to_page_id)
             AND other.page_id <> wp.page_id
             AND other.superseded_by IS NULL
             AND other.page_type IN ('concept', 'comparison')
            WHERE wp.domain = $1
              AND wp.superseded_by IS NULL
              AND wp.knowledge_level = 'generalization_like'
            GROUP BY wp.page_id, wp.slug
            HAVING COUNT(DISTINCT other.page_id) < 2
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug, support_count) in generalization_without_multi_support {
            issues.push(WikiLintIssue {
                r#type: "generalization_without_multi_support".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is labeled generalization_like but has only {support_count} concept/comparison support link(s)"
                ),
                severity: "info".to_string(),
            });
        }

        let unsupported_generalizations: Vec<(String, String)> = sqlx::query_as(
            r#"
            SELECT wp.page_id::text, wp.slug
            FROM wiki_page wp
            WHERE wp.domain = $1
              AND wp.superseded_by IS NULL
              AND wp.knowledge_level = 'generalization_like'
              AND NOT EXISTS (
                SELECT 1
                FROM wiki_page_link wpl
                JOIN wiki_page other ON other.page_id IN (wpl.from_page_id, wpl.to_page_id)
                WHERE (wpl.from_page_id = wp.page_id OR wpl.to_page_id = wp.page_id)
                  AND other.page_id <> wp.page_id
                  AND other.superseded_by IS NULL
                  AND other.page_type IN ('concept', 'comparison')
              )
            "#,
        )
        .bind(&req.domain)
        .fetch_all(&self.pool)
        .await?;

        for (page_id, slug) in unsupported_generalizations {
            issues.push(WikiLintIssue {
                r#type: "unsupported_generalization".to_string(),
                page_id,
                slug: slug.clone(),
                description: format!(
                    "Page \"{slug}\" is labeled generalization_like but has no concept/comparison link support"
                ),
                severity: "info".to_string(),
            });
        }

        Ok(LintWikiDomainResponse { issues })
    }
}

fn map_page_row(
    r: (
        String,
        String,
        String,
        String,
        String,
        String,
        Option<String>,
        Option<String>,
        String,
        i32,
        f64,
        String,
        String,
        String,
        Option<String>,
    ),
) -> WikiPageRecord {
    WikiPageRecord {
        page_id: r.0,
        domain: r.1,
        slug: r.2,
        title: r.3,
        content: r.4,
        page_type: r.5,
        knowledge_level: r.6.unwrap_or_default(),
        authority_kind: r.7.unwrap_or_default(),
        tags_json: r.8,
        source_count: r.9,
        confidence: r.10 as f32,
        last_reinforced_at: r.11,
        created_at: r.12,
        updated_at: r.13,
        superseded_by: r.14.unwrap_or_default(),
    }
}
