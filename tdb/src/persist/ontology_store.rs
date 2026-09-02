use crate::persist::bridge_log::log_info;
use serde_json::{Value, json};
use sqlx::types::Json;
use sqlx::{PgPool, Row};
use uuid::Uuid;

const SEMANTIC_NAMESPACE_LEGACY_ONTOLOGY: &str = "legacy_ontology";
const SEMANTIC_PROPERTY_QUALIFIER_PAYLOAD: &str = "tdb.qualifier.payload";
const SEMANTIC_PROPERTY_REFERENCE_LEGACY_EVENT: &str = "tdb.ref.legacy_event";
const SEMANTIC_PROPERTY_REFERENCE_SOURCE_SPAN: &str = "tdb.ref.source_span";
const ARCHEOLOGY_CONTEXT_CULTURE: &str = "archeology.context.culture";
const ARCHEOLOGY_CONTEXT_PERIOD: &str = "archeology.context.period";
const ARCHEOLOGY_CONTEXT_PLACE: &str = "archeology.context.place";
const ARCHEOLOGY_CONTEXT_RELIGION: &str = "archeology.context.religion";
const ARCHEOLOGY_CONTEXT_FRAME: &str = "archeology.context.frame";
const ARCHEOLOGY_CONTEXT_DIFFERENCE: &str = "archeology.context.difference";
const ARCHEOLOGY_CONTEXT_SCOPE: &str = "archeology.context.scope";

pub struct OntologyStore {
    pool: PgPool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SemanticKernelBackfillReport {
    pub concepts_synced: u64,
    pub aliases_synced: u64,
    pub facts_synced: u64,
}

#[derive(Clone, Debug)]
pub struct OntologyConceptInput {
    pub concept_id: String,
    pub canonical_name: String,
    pub concept_type: String,
    pub aliases: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct OntologyFactInput {
    pub src_concept_id: String,
    pub predicate: String,
    pub dst_concept_id: String,
    pub qualifier_json: Value,
    pub confidence: f64,
    pub extractor: String,
    pub status: String,
    pub review_note: String,
}

#[derive(Clone, Debug)]
pub struct OntologyFactEvidenceInput {
    pub stream_id: String,
    pub event_id: String,
    pub asset_id: Option<String>,
    pub version_number: Option<u64>,
    pub source_span: Option<String>,
    pub evidence_json: Value,
    pub confidence: f64,
}

#[derive(Clone, Debug)]
pub struct OntologyFactReviewInput {
    pub reviewer: String,
    pub decision: String,
    pub note: String,
}

#[derive(Clone, Debug, PartialEq)]
struct SemanticTermInput {
    entity_id: String,
    term_type: String,
    term: String,
    normalized_term: String,
    status: String,
    metadata_json: Value,
}

#[derive(Clone, Debug, PartialEq)]
struct SemanticReferenceClaimInput {
    property_id: String,
    value_type: String,
    value_json: Value,
    source_span: Option<String>,
}

#[derive(Clone, Copy, Debug)]
enum SemanticStatementSyncMode<'a> {
    Backfill,
    Review {
        reviewer: &'a str,
        decision: &'a str,
        note: &'a str,
    },
}

impl OntologyStore {
    pub fn from_pool(pool: PgPool) -> Self {
        Self { pool }
    }

    pub async fn new(database_url: &str) -> Result<Self, sqlx::Error> {
        let pool = PgPool::connect(database_url).await?;
        let this = Self::from_pool(pool);
        this.validate_schema().await?;
        Ok(this)
    }

    pub async fn upsert_concept(&self, input: &OntologyConceptInput) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"
            INSERT INTO ontology_concept (
              concept_id, canonical_name, concept_type, aliases
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (concept_id) DO UPDATE SET
              canonical_name = EXCLUDED.canonical_name,
              concept_type = EXCLUDED.concept_type,
              aliases = EXCLUDED.aliases,
              updated_at = NOW()
            "#,
        )
        .bind(&input.concept_id)
        .bind(&input.canonical_name)
        .bind(&input.concept_type)
        .bind(Json(&input.aliases))
        .execute(&self.pool)
        .await?;
        let mut tx = self.pool.begin().await?;
        upsert_semantic_concept_entity(&mut tx, input).await?;
        for term in build_semantic_concept_terms(input) {
            upsert_semantic_term(&mut tx, &term).await?;
        }
        tx.commit().await?;
        Ok(())
    }

    pub async fn upsert_edge(
        &self,
        src_concept_id: &str,
        predicate: &str,
        dst_concept_id: &str,
        weight: f64,
    ) -> Result<(), sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        sqlx::query(
            r#"
            INSERT INTO ontology_edge (
              src_concept_id, predicate, dst_concept_id, weight
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (src_concept_id, predicate, dst_concept_id) DO UPDATE SET
              weight = GREATEST(ontology_edge.weight, EXCLUDED.weight)
            "#,
        )
        .bind(src_concept_id)
        .bind(predicate)
        .bind(dst_concept_id)
        .bind(weight)
        .execute(&mut *tx)
        .await?;
        ensure_semantic_item_entity(&mut tx, src_concept_id).await?;
        ensure_semantic_item_entity(&mut tx, dst_concept_id).await?;
        ensure_semantic_property_entity(&mut tx, predicate).await?;
        upsert_semantic_edge_statement(&mut tx, src_concept_id, predicate, dst_concept_id, weight)
            .await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn upsert_event_concept_link(
        &self,
        stream_id: &str,
        event_id: &str,
        concept_id: &str,
        role: &str,
        confidence: f64,
        asset_id: Option<&str>,
        version_number: Option<u64>,
    ) -> Result<(), sqlx::Error> {
        self.upsert_event_concept_link_with_meta(
            stream_id,
            event_id,
            concept_id,
            role,
            confidence,
            asset_id,
            version_number,
            "rule_v1",
            None,
            None,
        )
        .await
    }

    pub async fn upsert_event_concept_link_with_meta(
        &self,
        stream_id: &str,
        event_id: &str,
        concept_id: &str,
        role: &str,
        confidence: f64,
        asset_id: Option<&str>,
        version_number: Option<u64>,
        extractor: &str,
        source_span: Option<&str>,
        evidence_json: Option<&Value>,
    ) -> Result<(), sqlx::Error> {
        let version_number_i64 = version_number.map(|v| v as i64);
        let evidence = evidence_json
            .cloned()
            .unwrap_or_else(|| serde_json::json!({}));
        sqlx::query(
            r#"
            INSERT INTO event_concept_link (
              stream_id, event_id, concept_id, role, confidence,
              asset_id, version_number, extractor, source_span, evidence_json
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (stream_id, event_id, concept_id, role) DO UPDATE SET
              confidence = GREATEST(event_concept_link.confidence, EXCLUDED.confidence),
              asset_id = COALESCE(EXCLUDED.asset_id, event_concept_link.asset_id),
              version_number = COALESCE(EXCLUDED.version_number, event_concept_link.version_number),
              extractor = EXCLUDED.extractor,
              source_span = COALESCE(EXCLUDED.source_span, event_concept_link.source_span),
              evidence_json = CASE
                WHEN event_concept_link.evidence_json = '{}'::jsonb THEN EXCLUDED.evidence_json
                ELSE event_concept_link.evidence_json
              END,
              updated_at = NOW()
            "#,
        )
        .bind(stream_id)
        .bind(event_id)
        .bind(concept_id)
        .bind(role)
        .bind(confidence)
        .bind(asset_id)
        .bind(version_number_i64)
        .bind(extractor)
        .bind(source_span)
        .bind(Json(evidence))
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn upsert_concept_alias(
        &self,
        concept_id: &str,
        alias_text: &str,
        confidence: f64,
        extractor: &str,
    ) -> Result<(), sqlx::Error> {
        sqlx::query(
            r#"
            INSERT INTO concept_alias (concept_id, alias_text, confidence, extractor)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (concept_id, alias_text) DO UPDATE SET
              confidence = GREATEST(concept_alias.confidence, EXCLUDED.confidence),
              extractor = EXCLUDED.extractor,
              updated_at = NOW()
            "#,
        )
        .bind(concept_id)
        .bind(alias_text)
        .bind(confidence)
        .bind(extractor)
        .execute(&self.pool)
        .await?;
        let mut tx = self.pool.begin().await?;
        ensure_semantic_item_entity(&mut tx, concept_id).await?;
        let semantic_term = build_semantic_alias_term(concept_id, alias_text, confidence, extractor);
        upsert_semantic_term(&mut tx, &semantic_term).await?;
        tx.commit().await?;
        Ok(())
    }

    pub async fn upsert_fact_with_evidence(
        &self,
        fact: &OntologyFactInput,
        evidence: &OntologyFactEvidenceInput,
    ) -> Result<bool, sqlx::Error> {
        let mut tx = self.pool.begin().await?;
        let normalized_evidence_json = normalize_evidence_span(&mut tx, evidence).await?;
        if !predicate_enabled(&mut tx, &fact.predicate).await? {
            log_info(&format!(
                "ontology_fact_skip_predicate_disabled_or_missing predicate={} extractor={} stream_id={} event_id={}",
                fact.predicate, fact.extractor, evidence.stream_id, evidence.event_id
            ));
            tx.rollback().await?;
            return Ok(false);
        }
        let effective_status =
            normalize_ingest_fact_status(&fact.extractor, &fact.status, &normalized_evidence_json);
        let existing = sqlx::query(
            r#"
            SELECT fact_id
            FROM ontology_fact
            WHERE src_concept_id = $1
              AND predicate = $2
              AND dst_concept_id = $3
              AND qualifier_json = $4
              AND extractor = $5
            ORDER BY fact_id DESC
            LIMIT 1
            "#,
        )
        .bind(&fact.src_concept_id)
        .bind(&fact.predicate)
        .bind(&fact.dst_concept_id)
        .bind(Json(fact.qualifier_json.clone()))
        .bind(&fact.extractor)
        .fetch_optional(&mut *tx)
        .await?;

        let fact_id: i64 = if let Some(row) = existing {
            let id: i64 = row.try_get("fact_id")?;
            sqlx::query(
                r#"
                UPDATE ontology_fact
                SET confidence = GREATEST(confidence, $2),
                    status = CASE
                      WHEN status = 'rejected' THEN status
                      ELSE $3
                    END,
                    review_note = CASE
                      WHEN review_note = '' THEN $4
                      ELSE review_note
                    END,
                    updated_at = NOW()
                WHERE fact_id = $1
                "#,
            )
            .bind(id)
            .bind(fact.confidence.clamp(0.0, 1.0))
            .bind(&effective_status)
            .bind(&fact.review_note)
            .execute(&mut *tx)
            .await?;
            id
        } else {
            let row = sqlx::query(
                r#"
                INSERT INTO ontology_fact (
                  src_concept_id, predicate, dst_concept_id, qualifier_json,
                  confidence, extractor, status, review_note
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING fact_id
                "#,
            )
            .bind(&fact.src_concept_id)
            .bind(&fact.predicate)
            .bind(&fact.dst_concept_id)
            .bind(Json(fact.qualifier_json.clone()))
            .bind(fact.confidence.clamp(0.0, 1.0))
            .bind(&fact.extractor)
            .bind(&effective_status)
            .bind(&fact.review_note)
            .fetch_one(&mut *tx)
            .await?;
            row.try_get("fact_id")?
        };

        let version_number_i64 = evidence.version_number.map(|v| v as i64);
        sqlx::query(
            r#"
            INSERT INTO ontology_fact_evidence (
              fact_id, stream_id, event_id, asset_id, version_number,
              source_span, evidence_json, confidence
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (fact_id, stream_id, event_id) DO UPDATE SET
              confidence = GREATEST(ontology_fact_evidence.confidence, EXCLUDED.confidence),
              source_span = COALESCE(EXCLUDED.source_span, ontology_fact_evidence.source_span),
              evidence_json =
                (
                  COALESCE(ontology_fact_evidence.evidence_json, '{}'::jsonb)
                  - 'sent_index'
                  - 'start_char'
                  - 'end_char'
                  - 'text_hash'
                  - 'seg_version'
                  - 'event_sentence_pk'
                  - 'span_strategy'
                  - 'span_status'
                  - 'overlap_chars'
                  - 'covered_sentence_count'
                )
                || EXCLUDED.evidence_json,
              asset_id = COALESCE(EXCLUDED.asset_id, ontology_fact_evidence.asset_id),
              version_number = COALESCE(EXCLUDED.version_number, ontology_fact_evidence.version_number),
              updated_at = NOW()
            "#,
        )
        .bind(fact_id)
        .bind(&evidence.stream_id)
        .bind(&evidence.event_id)
        .bind(evidence.asset_id.as_deref())
        .bind(version_number_i64)
        .bind(evidence.source_span.as_deref())
        .bind(Json(normalized_evidence_json))
        .bind(evidence.confidence.clamp(0.0, 1.0))
        .execute(&mut *tx)
        .await?;

        ensure_semantic_item_entity(&mut tx, &fact.src_concept_id).await?;
        ensure_semantic_item_entity(&mut tx, &fact.dst_concept_id).await?;
        ensure_semantic_property_entity(&mut tx, &fact.predicate).await?;
        ensure_semantic_system_property(
            &mut tx,
            SEMANTIC_PROPERTY_QUALIFIER_PAYLOAD,
            "json",
            "Qualifier Payload",
        )
        .await?;
        ensure_semantic_context_properties(&mut tx).await?;
        ensure_semantic_system_property(
            &mut tx,
            SEMANTIC_PROPERTY_REFERENCE_LEGACY_EVENT,
            "json",
            "Legacy Event Reference",
        )
        .await?;
        ensure_semantic_system_property(
            &mut tx,
            SEMANTIC_PROPERTY_REFERENCE_SOURCE_SPAN,
            "string",
            "Reference Source Span",
        )
        .await?;
        let statement_id =
            upsert_semantic_statement(&mut tx, fact_id, fact, &effective_status).await?;
        replace_semantic_statement_qualifiers(&mut tx, statement_id, &fact.qualifier_json).await?;
        replace_semantic_statement_references(&mut tx, statement_id, evidence).await?;
        append_semantic_statement_revision(&mut tx, statement_id, fact_id, fact).await?;

        tx.commit().await?;
        Ok(true)
    }

    pub async fn review_fact(
        &self,
        fact_id: i64,
        review: &OntologyFactReviewInput,
    ) -> Result<u64, sqlx::Error> {
        let status = match review.decision.trim().to_lowercase().as_str() {
            "accept" => "accepted",
            "reject" => "rejected",
            "needs_work" => "needs_review",
            _ => "needs_review",
        };
        let mut tx = self.pool.begin().await?;
        let updated = sqlx::query(
            r#"
            UPDATE ontology_fact
            SET status = $2,
                review_note = CASE
                  WHEN $3 = '' THEN review_note
                  ELSE $3
                END,
                updated_at = NOW()
            WHERE fact_id = $1
            "#,
        )
        .bind(fact_id)
        .bind(status)
        .bind(review.note.trim())
        .execute(&mut *tx)
        .await?
        .rows_affected();

        if updated > 0 {
            sqlx::query(
                r#"
                INSERT INTO ontology_fact_review (
                  fact_id, reviewer, decision, note
                )
                VALUES ($1, $2, $3, $4)
                "#,
            )
            .bind(fact_id)
            .bind(review.reviewer.trim())
            .bind(review.decision.trim().to_lowercase())
            .bind(review.note.trim())
            .execute(&mut *tx)
            .await?;

            sync_semantic_statement_for_legacy_fact(
                &mut tx,
                fact_id,
                SemanticStatementSyncMode::Review {
                    reviewer: review.reviewer.trim(),
                    decision: review.decision.trim(),
                    note: review.note.trim(),
                },
            )
            .await?;
        }
        tx.commit().await?;
        Ok(updated)
    }

    pub async fn backfill_semantic_kernel_from_legacy_ontology(
        &self,
        fact_limit: Option<usize>,
    ) -> Result<SemanticKernelBackfillReport, sqlx::Error> {
        let fact_ids = if let Some(limit) = fact_limit {
            sqlx::query_scalar::<_, i64>(
                r#"
                SELECT fact_id
                FROM ontology_fact
                ORDER BY fact_id ASC
                LIMIT $1
                "#,
            )
            .bind(limit as i64)
            .fetch_all(&self.pool)
            .await?
        } else {
            sqlx::query_scalar::<_, i64>(
                r#"
                SELECT fact_id
                FROM ontology_fact
                ORDER BY fact_id ASC
                "#,
            )
            .fetch_all(&self.pool)
            .await?
        };
        self.backfill_semantic_kernel_for_legacy_fact_ids(&fact_ids)
            .await
    }

    pub async fn backfill_semantic_kernel_for_legacy_fact_ids(
        &self,
        fact_ids: &[i64],
    ) -> Result<SemanticKernelBackfillReport, sqlx::Error> {
        if fact_ids.is_empty() {
            return Ok(SemanticKernelBackfillReport::default());
        }

        let mut tx = self.pool.begin().await?;
        let mut report = SemanticKernelBackfillReport::default();

        let concept_ids = sqlx::query_scalar::<_, String>(
            r#"
            SELECT DISTINCT concept_id
            FROM (
              SELECT src_concept_id AS concept_id
              FROM ontology_fact
              WHERE fact_id = ANY($1)
              UNION
              SELECT dst_concept_id AS concept_id
              FROM ontology_fact
              WHERE fact_id = ANY($1)
            ) concepts
            ORDER BY concept_id ASC
            "#,
        )
        .bind(fact_ids)
        .fetch_all(&mut *tx)
        .await?;

        let concept_rows = sqlx::query(
            r#"
            SELECT concept_id, canonical_name, concept_type, aliases
            FROM ontology_concept
            WHERE concept_id = ANY($1)
            ORDER BY updated_at ASC, concept_id ASC
            "#,
        )
        .bind(&concept_ids)
        .fetch_all(&mut *tx)
        .await?;
        for row in concept_rows {
            let aliases: Value = row.try_get("aliases")?;
            let concept = OntologyConceptInput {
                concept_id: row.try_get("concept_id")?,
                canonical_name: row.try_get("canonical_name")?,
                concept_type: row.try_get("concept_type")?,
                aliases: aliases
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|value| value.as_str())
                    .map(trim_text)
                    .filter(|value| !value.is_empty())
                    .collect(),
            };
            upsert_semantic_concept_entity(&mut tx, &concept).await?;
            for term in build_semantic_concept_terms(&concept) {
                upsert_semantic_term(&mut tx, &term).await?;
            }
            report.concepts_synced += 1;
        }

        let alias_rows = sqlx::query(
            r#"
            SELECT concept_id, alias_text, confidence, extractor
            FROM concept_alias
            WHERE concept_id = ANY($1)
            ORDER BY updated_at ASC, concept_id ASC, alias_text ASC
            "#,
        )
        .bind(&concept_ids)
        .fetch_all(&mut *tx)
        .await?;
        for row in alias_rows {
            let concept_id: String = row.try_get("concept_id")?;
            ensure_semantic_item_entity(&mut tx, &concept_id).await?;
            let semantic_term = build_semantic_alias_term(
                &concept_id,
                &row.try_get::<String, _>("alias_text")?,
                row.try_get::<f64, _>("confidence")?,
                &row.try_get::<String, _>("extractor")?,
            );
            upsert_semantic_term(&mut tx, &semantic_term).await?;
            report.aliases_synced += 1;
        }

        for fact_id in fact_ids {
            sync_semantic_statement_for_legacy_fact(
                &mut tx,
                *fact_id,
                SemanticStatementSyncMode::Backfill,
            )
            .await?;
            report.facts_synced += 1;
        }

        tx.commit().await?;
        Ok(report)
    }

    async fn validate_schema(&self) -> Result<(), sqlx::Error> {
        require_relations(
            &self.pool,
            &[
                "ontology_concept",
                "ontology_edge",
                "event_concept_link",
                "concept_alias",
                "ontology_object_type",
                "ontology_relation_type",
                "ontology_fact",
                "ontology_fact_evidence",
                "ontology_fact_review",
                "ontology_case",
                "ontology_case_fact",
                "ontology_case_event",
                "ontology_alert",
                "ontology_alert_fact",
                "ontology_ops_rule_config",
                "ontology_ops_rule_run",
                "semantic_entity",
                "semantic_term",
                "semantic_statement",
                "statement_qualifier",
                "statement_reference",
                "statement_revision",
                "idx_ontology_concept_canonical",
                "idx_ontology_edge_src_pred",
                "idx_ontology_edge_dst_pred",
                "idx_event_concept_link_stream_event",
                "idx_event_concept_link_concept",
                "idx_concept_alias_alias_text",
                "idx_ontology_fact_src_pred",
                "idx_ontology_fact_dst_pred",
                "idx_ontology_fact_status",
                "idx_fact_evidence_stream_event",
                "idx_fact_evidence_fact",
                "idx_fact_review_fact",
                "idx_ontology_case_stream_status",
                "idx_ontology_case_fact_fact",
                "idx_ontology_case_event_case",
                "idx_ontology_alert_stream_status",
                "idx_ontology_alert_rule_key",
                "uq_ontology_alert_active_rule",
                "idx_ontology_alert_fact_fact",
                "uq_ontology_ops_rule_config_scope",
                "idx_ontology_ops_rule_run_started",
                "idx_ontology_ops_rule_run_stream",
                "idx_semantic_entity_kind_status",
                "idx_semantic_entity_namespace",
                "idx_semantic_term_entity_lang_type_term",
                "idx_semantic_term_normalized",
                "idx_semantic_statement_subject_property",
                "idx_semantic_statement_value_entity",
                "idx_semantic_statement_status_rank",
                "idx_statement_qualifier_statement",
                "idx_statement_reference_statement",
                "idx_statement_reference_evidence",
                "idx_statement_reference_legacy_event",
                "idx_statement_revision_statement",
            ],
            "ontology extension schema objects",
        )
        .await?;
        require_columns(
            &self.pool,
            &[
                ("event_concept_link", "extractor"),
                ("event_concept_link", "source_span"),
                ("event_concept_link", "evidence_json"),
                ("ontology_alert", "rule_key"),
                ("ontology_alert", "trigger_count"),
                ("ontology_alert", "first_triggered_at"),
                ("ontology_alert", "last_triggered_at"),
                ("semantic_entity", "entity_kind"),
                ("semantic_entity", "semantic_role"),
                ("semantic_term", "normalized_term"),
                ("semantic_statement", "property_id"),
                ("statement_reference", "reference_id"),
            ],
            "ontology extension schema columns",
        )
        .await?;
        require_constraints(
            &self.pool,
            &[
                ("event_concept_link", "ck_event_concept_link_extractor"),
                ("concept_alias", "concept_alias_extractor_check"),
                ("ontology_edge", "ck_ontology_edge_predicate"),
            ],
            "ontology extension schema constraints",
        )
        .await?;
        require_object_types(
            &self.pool,
            &[
                "entity", "event", "session", "time", "topic", "phrase", "location", "activity",
            ],
        )
        .await?;
        require_relation_types(
            &self.pool,
            &[
                "same_as",
                "is_a",
                "part_of",
                "related_to",
                "participates_in",
                "occurs_at",
                "happens_when",
                "associated_with_place",
                "has_birthday_on",
                "has_home_country",
                "has_hometown",
                "born_in",
            ],
        )
        .await
    }

    #[allow(dead_code)]
    pub async fn concept_count(&self) -> Result<u64, sqlx::Error> {
        let row = sqlx::query("SELECT COUNT(*)::BIGINT AS c FROM ontology_concept")
            .fetch_one(&self.pool)
            .await?;
        let c: i64 = row.try_get("c")?;
        Ok(c.max(0) as u64)
    }
}

fn json_i32(value: &Value, key: &str) -> Option<i32> {
    value
        .get(key)
        .and_then(|v| v.as_i64())
        .and_then(|v| i32::try_from(v).ok())
}

fn is_ingest_extractor(extractor: &str) -> bool {
    matches!(
        extractor.trim().to_ascii_lowercase().as_str(),
        "rule_v1" | "rule_v2" | "llm_v1" | "llm_v2" | "hybrid" | "controlled_v1"
    )
}

fn normalize_ingest_fact_status(
    extractor: &str,
    requested_status: &str,
    evidence_json: &Value,
) -> String {
    let requested = requested_status.trim().to_ascii_lowercase();
    if is_ingest_extractor(extractor) {
        return "candidate".to_string();
    }
    if requested == "accepted" {
        let span_status = evidence_json
            .get("span_status")
            .and_then(|v| v.as_str())
            .unwrap_or("");
        if span_status != "located" {
            return "candidate".to_string();
        }
    }
    match requested.as_str() {
        "accepted" | "candidate" | "rejected" | "needs_review" => requested,
        _ => "candidate".to_string(),
    }
}

fn map_legacy_fact_status_to_semantic_status(status: &str) -> &'static str {
    match status.trim().to_ascii_lowercase().as_str() {
        "accepted" => "accepted",
        "candidate" => "extracted",
        "needs_review" => "reviewed",
        "rejected" => "rejected",
        "deprecated" => "deprecated",
        _ => "proposed",
    }
}

fn trim_text(value: &str) -> String {
    value.trim().to_string()
}

fn normalize_term_surface(value: &str) -> String {
    trim_text(value)
}

fn build_semantic_alias_term(
    concept_id: &str,
    alias_text: &str,
    confidence: f64,
    extractor: &str,
) -> SemanticTermInput {
    let term = trim_text(alias_text);
    SemanticTermInput {
        entity_id: concept_id.to_string(),
        term_type: "alias".to_string(),
        normalized_term: normalize_term_surface(&term),
        term,
        status: "active".to_string(),
        metadata_json: json!({
            "legacy_confidence": confidence.clamp(0.0, 1.0),
            "legacy_extractor": extractor.trim(),
            "dual_write_source": "concept_alias"
        }),
    }
}

fn build_semantic_fact_statement_metadata(fact_id: i64, fact: &OntologyFactInput) -> Value {
    json!({
        "legacy_fact_id": fact_id,
        "legacy_predicate": fact.predicate,
        "legacy_extractor": fact.extractor,
        "legacy_review_note": fact.review_note,
        "legacy_qualifier_json": fact.qualifier_json,
        "dual_write_source": "ontology_fact"
    })
}

fn build_semantic_fact_reference_claims(
    evidence: &OntologyFactEvidenceInput,
) -> Vec<SemanticReferenceClaimInput> {
    let mut claims = vec![SemanticReferenceClaimInput {
        property_id: SEMANTIC_PROPERTY_REFERENCE_LEGACY_EVENT.to_string(),
        value_type: "json".to_string(),
        value_json: json!({
            "stream_id": evidence.stream_id,
            "event_id": evidence.event_id,
            "asset_id": evidence.asset_id,
            "version_number": evidence.version_number,
            "confidence": evidence.confidence.clamp(0.0, 1.0),
            "evidence_json": evidence.evidence_json
        }),
        source_span: evidence.source_span.clone(),
    }];

    if let Some(source_span) = evidence
        .source_span
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
    {
        claims.push(SemanticReferenceClaimInput {
            property_id: SEMANTIC_PROPERTY_REFERENCE_SOURCE_SPAN.to_string(),
            value_type: "json".to_string(),
            value_json: Value::String(source_span.to_string()),
            source_span: Some(source_span.to_string()),
        });
    }

    claims
}

fn build_semantic_item_metadata(concept: &OntologyConceptInput) -> Value {
    json!({
        "legacy_concept_type": concept.concept_type,
        "legacy_canonical_name": concept.canonical_name,
        "legacy_aliases": concept.aliases,
        "dual_write_source": "ontology_concept"
    })
}

fn build_semantic_concept_terms(concept: &OntologyConceptInput) -> Vec<SemanticTermInput> {
    let mut terms = vec![SemanticTermInput {
        entity_id: concept.concept_id.clone(),
        term_type: "label".to_string(),
        term: trim_text(&concept.canonical_name),
        normalized_term: normalize_term_surface(&concept.canonical_name),
        status: "active".to_string(),
        metadata_json: json!({
            "legacy_concept_type": concept.concept_type,
            "dual_write_source": "ontology_concept"
        }),
    }];

    for alias in &concept.aliases {
        let normalized = trim_text(alias);
        if normalized.is_empty() || normalized == terms[0].term {
            continue;
        }
        terms.push(SemanticTermInput {
            entity_id: concept.concept_id.clone(),
            term_type: "alias".to_string(),
            term: normalized.clone(),
            normalized_term: normalize_term_surface(&normalized),
            status: "active".to_string(),
            metadata_json: json!({
                "legacy_concept_type": concept.concept_type,
                "dual_write_source": "ontology_concept_aliases_array"
            }),
        });
    }

    terms
}

async fn upsert_semantic_concept_entity(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    concept: &OntologyConceptInput,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, namespace, status, metadata_json
        )
        VALUES ($1, 'item', 'concept', $2, 'active', $3)
        ON CONFLICT (entity_id) DO UPDATE SET
          entity_kind = EXCLUDED.entity_kind,
          semantic_role = EXCLUDED.semantic_role,
          namespace = EXCLUDED.namespace,
          status = EXCLUDED.status,
          metadata_json = EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(&concept.concept_id)
    .bind(SEMANTIC_NAMESPACE_LEGACY_ONTOLOGY)
    .bind(Json(build_semantic_item_metadata(concept)))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn ensure_semantic_item_entity(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    concept_id: &str,
) -> Result<(), sqlx::Error> {
    let inserted = sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, namespace, status, metadata_json
        )
        SELECT
          concept_id,
          'item',
          'concept',
          $2,
          'active',
          jsonb_build_object(
            'legacy_concept_type', concept_type,
            'legacy_canonical_name', canonical_name,
            'legacy_aliases', aliases,
            'dual_write_source', 'ontology_concept'
          )
        FROM ontology_concept
        WHERE concept_id = $1
        ON CONFLICT (entity_id) DO UPDATE SET
          entity_kind = EXCLUDED.entity_kind,
          semantic_role = EXCLUDED.semantic_role,
          namespace = EXCLUDED.namespace,
          status = EXCLUDED.status,
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(concept_id)
    .bind(SEMANTIC_NAMESPACE_LEGACY_ONTOLOGY)
    .execute(&mut **tx)
    .await?
    .rows_affected();

    if inserted == 0 {
        sqlx::query(
            r#"
            INSERT INTO semantic_entity (
              entity_id, entity_kind, semantic_role, namespace, status, metadata_json
            )
            VALUES ($1, 'item', 'concept', $2, 'active', '{"dual_write_source":"compat_fallback"}'::jsonb)
            ON CONFLICT (entity_id) DO NOTHING
            "#,
        )
        .bind(concept_id)
        .bind(SEMANTIC_NAMESPACE_LEGACY_ONTOLOGY)
        .execute(&mut **tx)
        .await?;
    }

    Ok(())
}

async fn ensure_semantic_property_entity(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    predicate: &str,
) -> Result<(), sqlx::Error> {
    let inserted = sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
        )
        SELECT
          predicate,
          'property',
          'object_property',
          'entity',
          $2,
          CASE WHEN enabled THEN 'active' ELSE 'deprecated' END,
          jsonb_build_object(
            'display_name', display_name,
            'description', description,
            'src_type_id', src_type_id,
            'dst_type_id', dst_type_id,
            'is_symmetric', is_symmetric,
            'is_transitive', is_transitive,
            'dual_write_source', 'ontology_relation_type'
          )
        FROM ontology_relation_type
        WHERE predicate = $1
        ON CONFLICT (entity_id) DO UPDATE SET
          entity_kind = EXCLUDED.entity_kind,
          semantic_role = EXCLUDED.semantic_role,
          property_datatype = EXCLUDED.property_datatype,
          namespace = EXCLUDED.namespace,
          status = EXCLUDED.status,
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(predicate)
    .bind(SEMANTIC_NAMESPACE_LEGACY_ONTOLOGY)
    .execute(&mut **tx)
    .await?
    .rows_affected();

    if inserted == 0 {
        ensure_semantic_system_property(tx, predicate, "entity", predicate).await?;
    }

    Ok(())
}

async fn ensure_semantic_system_property(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    property_id: &str,
    property_datatype: &str,
    display_name: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO semantic_entity (
          entity_id, entity_kind, semantic_role, property_datatype, namespace, status, metadata_json
        )
        VALUES (
          $1,
          'property',
          'annotation_property',
          $2,
          'tdb.system',
          'active',
          jsonb_build_object('display_name', $3, 'dual_write_source', 'semantic_system_property')
        )
        ON CONFLICT (entity_id) DO UPDATE SET
          property_datatype = EXCLUDED.property_datatype,
          metadata_json = semantic_entity.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(property_id)
    .bind(property_datatype)
    .bind(display_name)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn ensure_semantic_context_properties(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
) -> Result<(), sqlx::Error> {
    for (property_id, display_name) in [
        (ARCHEOLOGY_CONTEXT_CULTURE, "Archaeology Context Culture"),
        (ARCHEOLOGY_CONTEXT_PERIOD, "Archaeology Context Period"),
        (ARCHEOLOGY_CONTEXT_PLACE, "Archaeology Context Place"),
        (ARCHEOLOGY_CONTEXT_RELIGION, "Archaeology Context Religion"),
        (ARCHEOLOGY_CONTEXT_FRAME, "Archaeology Context Frame"),
        (ARCHEOLOGY_CONTEXT_DIFFERENCE, "Archaeology Context Difference"),
        (ARCHEOLOGY_CONTEXT_SCOPE, "Archaeology Context Scope"),
    ] {
        ensure_semantic_system_property(tx, property_id, "string", display_name).await?;
    }
    Ok(())
}

async fn upsert_semantic_term(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    term: &SemanticTermInput,
) -> Result<(), sqlx::Error> {
    sqlx::query(
        r#"
        INSERT INTO semantic_term (
          entity_id, language, term_type, term, normalized_term, status, metadata_json
        )
        VALUES ($1, 'und', $2, $3, $4, $5, $6)
        ON CONFLICT (entity_id, language, term_type, term) DO UPDATE SET
          normalized_term = EXCLUDED.normalized_term,
          status = EXCLUDED.status,
          metadata_json = semantic_term.metadata_json || EXCLUDED.metadata_json,
          updated_at = NOW()
        "#,
    )
    .bind(&term.entity_id)
    .bind(&term.term_type)
    .bind(&term.term)
    .bind(&term.normalized_term)
    .bind(&term.status)
    .bind(Json(term.metadata_json.clone()))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn upsert_semantic_statement(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    fact_id: i64,
    fact: &OntologyFactInput,
    effective_status: &str,
) -> Result<Uuid, sqlx::Error> {
    let metadata = build_semantic_fact_statement_metadata(fact_id, fact);
    let semantic_status = map_legacy_fact_status_to_semantic_status(effective_status);
    let existing = sqlx::query(
        r#"
        SELECT statement_id
        FROM semantic_statement
        WHERE metadata_json @> jsonb_build_object('legacy_fact_id', to_jsonb($1::bigint))
        ORDER BY updated_at DESC
        LIMIT 1
        "#,
    )
    .bind(fact_id)
    .fetch_optional(&mut **tx)
    .await?;

    if let Some(row) = existing {
        let statement_id: Uuid = row.try_get("statement_id")?;
        sqlx::query(
            r#"
            UPDATE semantic_statement
            SET subject_id = $2,
                property_id = $3,
                value_type = 'entity',
                value_entity_id = $4,
                value_json = '{}'::jsonb,
                rank = CASE WHEN $5 = 'rejected' THEN 'deprecated' ELSE 'normal' END,
                status = $5,
                confidence = $6,
                created_by = $7,
                metadata_json = $8,
                updated_at = NOW()
            WHERE statement_id = $1
            "#,
        )
        .bind(statement_id)
        .bind(&fact.src_concept_id)
        .bind(&fact.predicate)
        .bind(&fact.dst_concept_id)
        .bind(semantic_status)
        .bind(fact.confidence.clamp(0.0, 1.0))
        .bind(trim_text(&fact.extractor))
        .bind(Json(metadata))
        .execute(&mut **tx)
        .await?;
        return Ok(statement_id);
    }

    let row = sqlx::query(
        r#"
        INSERT INTO semantic_statement (
          subject_id, property_id, value_type, value_entity_id, value_json,
          rank, status, confidence, created_by, metadata_json
        )
        VALUES ($1, $2, 'entity', $3, '{}'::jsonb, $4, $5, $6, $7, $8)
        RETURNING statement_id
        "#,
    )
    .bind(&fact.src_concept_id)
    .bind(&fact.predicate)
    .bind(&fact.dst_concept_id)
    .bind(if semantic_status == "rejected" {
        "deprecated"
    } else {
        "normal"
    })
    .bind(semantic_status)
    .bind(fact.confidence.clamp(0.0, 1.0))
    .bind(trim_text(&fact.extractor))
    .bind(Json(metadata))
    .fetch_one(&mut **tx)
    .await?;
    row.try_get("statement_id")
}

async fn replace_semantic_statement_qualifiers(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement_id: Uuid,
    qualifier_json: &Value,
) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM statement_qualifier WHERE statement_id = $1")
        .bind(statement_id)
        .execute(&mut **tx)
        .await?;

    if qualifier_json.is_null()
        || qualifier_json.as_object().map(|item| item.is_empty()).unwrap_or(false)
    {
        return Ok(());
    }

    sqlx::query(
        r#"
        INSERT INTO statement_qualifier (
          statement_id, property_id, value_type, value_json, ordinal
        )
        VALUES ($1, $2, 'json', $3, 0)
        "#,
    )
    .bind(statement_id)
    .bind(SEMANTIC_PROPERTY_QUALIFIER_PAYLOAD)
    .bind(Json(qualifier_json.clone()))
    .execute(&mut **tx)
    .await?;

    for (ordinal, qualifier) in build_structured_context_qualifiers(qualifier_json)
        .into_iter()
        .enumerate()
    {
        sqlx::query(
            r#"
            INSERT INTO statement_qualifier (
              statement_id, property_id, value_type, value_json, ordinal
            )
            VALUES ($1, $2, 'string', $3, $4)
            "#,
        )
        .bind(statement_id)
        .bind(qualifier.property_id)
        .bind(Json(json!(qualifier.value)))
        .bind(i32::try_from(ordinal + 1).unwrap_or(1))
        .execute(&mut **tx)
        .await?;
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct StructuredContextQualifier {
    property_id: &'static str,
    value: String,
}

fn build_structured_context_qualifiers(qualifier_json: &Value) -> Vec<StructuredContextQualifier> {
    let Some(qualifiers) = qualifier_json.as_object() else {
        return vec![];
    };
    let mut structured = Vec::new();

    if let Some(value) = qualifier_string_value(qualifiers, &["culture", "civilization"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_CULTURE,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["period"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_PERIOD,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["place", "site", "region"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_PLACE,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["religion"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_RELIGION,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["context"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_FRAME,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["difference"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_DIFFERENCE,
            value,
        });
    }
    if let Some(value) = qualifier_string_value(qualifiers, &["scope"]) {
        structured.push(StructuredContextQualifier {
            property_id: ARCHEOLOGY_CONTEXT_SCOPE,
            value,
        });
    }

    structured
}

fn qualifier_string_value(
    qualifiers: &serde_json::Map<String, Value>,
    keys: &[&str],
) -> Option<String> {
    keys.iter().find_map(|key| {
        qualifiers
            .get(*key)
            .and_then(Value::as_str)
            .map(trim_text)
            .filter(|value| !value.is_empty())
    })
}

async fn replace_semantic_statement_references(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement_id: Uuid,
    evidence: &OntologyFactEvidenceInput,
) -> Result<(), sqlx::Error> {
    replace_semantic_statement_references_for_evidences(tx, statement_id, &[evidence.clone()]).await
}

async fn replace_semantic_statement_references_for_evidences(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement_id: Uuid,
    evidences: &[OntologyFactEvidenceInput],
) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM statement_reference WHERE statement_id = $1")
        .bind(statement_id)
        .execute(&mut **tx)
        .await?;

    let mut ordinal = 0usize;
    for evidence in evidences {
        let reference_id = Uuid::new_v4();
        for claim in build_semantic_fact_reference_claims(evidence) {
            sqlx::query(
                r#"
                INSERT INTO statement_reference (
                  reference_claim_id, reference_id, statement_id, property_id,
                  value_type, value_json, legacy_stream_id, legacy_event_id, source_span, ordinal
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                "#,
            )
            .bind(Uuid::new_v4())
            .bind(reference_id)
            .bind(statement_id)
            .bind(&claim.property_id)
            .bind(&claim.value_type)
            .bind(Json(claim.value_json.clone()))
            .bind(&evidence.stream_id)
            .bind(&evidence.event_id)
            .bind(claim.source_span.as_deref())
            .bind(i32::try_from(ordinal).unwrap_or(0))
            .execute(&mut **tx)
            .await?;
            ordinal += 1;
        }
    }

    Ok(())
}

async fn append_semantic_statement_revision(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement_id: Uuid,
    fact_id: i64,
    fact: &OntologyFactInput,
) -> Result<(), sqlx::Error> {
    append_semantic_statement_revision_with_kind(
        tx,
        statement_id,
        fact_id,
        fact,
        None,
        format!("legacy ontology_fact sync fact_id={fact_id}"),
    )
    .await
}

async fn append_semantic_statement_revision_with_kind(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    statement_id: Uuid,
    fact_id: i64,
    fact: &OntologyFactInput,
    revision_kind: Option<&str>,
    summary: String,
) -> Result<(), sqlx::Error> {
    let row = sqlx::query(
        r#"
        SELECT COALESCE(MAX(revision_number), 0) + 1 AS next_revision
        FROM statement_revision
        WHERE statement_id = $1
        "#,
    )
    .bind(statement_id)
    .fetch_one(&mut **tx)
    .await?;
    let next_revision: i32 = row.try_get("next_revision")?;

    sqlx::query(
        r#"
        INSERT INTO statement_revision (
          statement_id, revision_number, revision_kind, editor, summary, statement_snapshot_json
        )
        VALUES ($1, $2, $3, $4, $5, $6)
        "#,
    )
    .bind(statement_id)
    .bind(next_revision)
    .bind(revision_kind.unwrap_or(if next_revision == 1 { "create" } else { "update" }))
    .bind(trim_text(&fact.extractor))
    .bind(summary)
    .bind(Json(json!({
        "legacy_fact_id": fact_id,
        "src_concept_id": fact.src_concept_id,
        "predicate": fact.predicate,
        "dst_concept_id": fact.dst_concept_id,
        "qualifier_json": fact.qualifier_json,
        "confidence": fact.confidence.clamp(0.0, 1.0),
        "status": fact.status
    })))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn upsert_semantic_edge_statement(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    src_concept_id: &str,
    predicate: &str,
    dst_concept_id: &str,
    weight: f64,
) -> Result<(), sqlx::Error> {
    let existing = sqlx::query(
        r#"
        SELECT statement_id
        FROM semantic_statement
        WHERE subject_id = $1
          AND property_id = $2
          AND value_type = 'entity'
          AND value_entity_id = $3
        ORDER BY
          CASE status
            WHEN 'accepted' THEN 0
            WHEN 'extracted' THEN 1
            WHEN 'reviewed' THEN 2
            ELSE 3
          END,
          updated_at DESC
        LIMIT 1
        "#,
    )
    .bind(src_concept_id)
    .bind(predicate)
    .bind(dst_concept_id)
    .fetch_optional(&mut **tx)
    .await?;

    if let Some(row) = existing {
        let statement_id: Uuid = row.try_get("statement_id")?;
        sqlx::query(
            r#"
            UPDATE semantic_statement
            SET confidence = GREATEST(confidence, $2),
                status = CASE
                  WHEN status IN ('rejected', 'deprecated') THEN status
                  ELSE 'accepted'
                END,
                metadata_json = COALESCE(metadata_json, '{}'::jsonb)
                  || jsonb_build_object(
                    'dual_write_edge_source', 'ontology_edge',
                    'legacy_edge_weight', $3::double precision
                  ),
                updated_at = NOW()
            WHERE statement_id = $1
            "#,
        )
        .bind(statement_id)
        .bind(weight.clamp(0.0, 1.0))
        .bind(weight.clamp(0.0, 1.0))
        .execute(&mut **tx)
        .await?;
        return Ok(());
    }

    sqlx::query(
        r#"
        INSERT INTO semantic_statement (
          subject_id, property_id, value_type, value_entity_id, value_json,
          rank, status, confidence, created_by, metadata_json
        )
        VALUES (
          $1, $2, 'entity', $3, '{}'::jsonb,
          'normal', 'accepted', $4, 'legacy_ontology_edge',
          jsonb_build_object(
            'dual_write_source', 'ontology_edge',
            'legacy_edge_weight', $4::double precision
          )
        )
        "#,
    )
    .bind(src_concept_id)
    .bind(predicate)
    .bind(dst_concept_id)
    .bind(weight.clamp(0.0, 1.0))
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn sync_semantic_statement_for_legacy_fact(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    fact_id: i64,
    sync_mode: SemanticStatementSyncMode<'_>,
) -> Result<(), sqlx::Error> {
    let fact_row = sqlx::query(
        r#"
        SELECT
          src_concept_id,
          predicate,
          dst_concept_id,
          qualifier_json,
          confidence,
          extractor,
          status,
          review_note
        FROM ontology_fact
        WHERE fact_id = $1
        "#,
    )
    .bind(fact_id)
    .fetch_one(&mut **tx)
    .await?;

    let fact = OntologyFactInput {
        src_concept_id: fact_row.try_get("src_concept_id")?,
        predicate: fact_row.try_get("predicate")?,
        dst_concept_id: fact_row.try_get("dst_concept_id")?,
        qualifier_json: fact_row.try_get("qualifier_json")?,
        confidence: fact_row.try_get::<f64, _>("confidence")?,
        extractor: fact_row.try_get("extractor")?,
        status: fact_row.try_get("status")?,
        review_note: fact_row.try_get("review_note")?,
    };

    let evidence_rows = sqlx::query(
        r#"
        SELECT
          stream_id,
          event_id,
          asset_id,
          version_number,
          source_span,
          evidence_json,
          confidence
        FROM ontology_fact_evidence
        WHERE fact_id = $1
        ORDER BY created_at ASC, stream_id ASC, event_id ASC
        "#,
    )
    .bind(fact_id)
    .fetch_all(&mut **tx)
    .await?;
    let evidences: Vec<OntologyFactEvidenceInput> = evidence_rows
        .into_iter()
        .map(|row| {
            Ok(OntologyFactEvidenceInput {
                stream_id: row.try_get("stream_id")?,
                event_id: row.try_get("event_id")?,
                asset_id: row.try_get("asset_id")?,
                version_number: row
                    .try_get::<Option<i64>, _>("version_number")?
                    .and_then(|value| u64::try_from(value).ok()),
                source_span: row.try_get("source_span")?,
                evidence_json: row.try_get("evidence_json")?,
                confidence: row.try_get::<f64, _>("confidence")?,
            })
        })
        .collect::<Result<_, sqlx::Error>>()?;

    ensure_semantic_item_entity(tx, &fact.src_concept_id).await?;
    ensure_semantic_item_entity(tx, &fact.dst_concept_id).await?;
    ensure_semantic_property_entity(tx, &fact.predicate).await?;
    ensure_semantic_system_property(
        tx,
        SEMANTIC_PROPERTY_QUALIFIER_PAYLOAD,
        "json",
        "Qualifier Payload",
    )
    .await?;
    ensure_semantic_context_properties(tx).await?;
    ensure_semantic_system_property(
        tx,
        SEMANTIC_PROPERTY_REFERENCE_LEGACY_EVENT,
        "json",
        "Legacy Event Reference",
    )
    .await?;
    ensure_semantic_system_property(
        tx,
        SEMANTIC_PROPERTY_REFERENCE_SOURCE_SPAN,
        "string",
        "Reference Source Span",
    )
    .await?;

    let statement_id = upsert_semantic_statement(tx, fact_id, &fact, &fact.status).await?;
    replace_semantic_statement_qualifiers(tx, statement_id, &fact.qualifier_json).await?;
    replace_semantic_statement_references_for_evidences(tx, statement_id, &evidences).await?;

    let revision_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM statement_revision WHERE statement_id = $1",
    )
    .bind(statement_id)
    .fetch_one(&mut **tx)
    .await?;

    match sync_mode {
        SemanticStatementSyncMode::Backfill => {
            if revision_count == 0 {
                append_semantic_statement_revision_with_kind(
                    tx,
                    statement_id,
                    fact_id,
                    &fact,
                    Some("create"),
                    format!("legacy ontology_fact backfill fact_id={fact_id}"),
                )
                .await?;
            }
        }
        SemanticStatementSyncMode::Review {
            reviewer,
            decision,
            note,
        } => {
            append_semantic_statement_revision_with_kind(
                tx,
                statement_id,
                fact_id,
                &fact,
                Some("status_change"),
                format!(
                    "legacy ontology_fact review fact_id={fact_id} reviewer={} decision={} note={}",
                    trim_text(reviewer),
                    trim_text(decision),
                    trim_text(note)
                ),
            )
            .await?;
        }
    }

    Ok(())
}

async fn predicate_enabled(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    predicate: &str,
) -> Result<bool, sqlx::Error> {
    let row = sqlx::query(
        r#"
        SELECT enabled
        FROM ontology_relation_type
        WHERE predicate = $1
        LIMIT 1
        "#,
    )
    .bind(predicate)
    .fetch_optional(&mut **tx)
    .await?;
    Ok(row
        .and_then(|r| r.try_get::<bool, _>("enabled").ok())
        .unwrap_or(false))
}

fn overlap_len(a_start: i32, a_end: i32, b_start: i32, b_end: i32) -> i32 {
    (a_end.min(b_end) - a_start.max(b_start)).max(0)
}

async fn normalize_evidence_span(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    evidence: &OntologyFactEvidenceInput,
) -> Result<Value, sqlx::Error> {
    let mut out = evidence.evidence_json.clone();
    let start_char = json_i32(&out, "start_char");
    let end_char = json_i32(&out, "end_char");
    let req_sent_index = json_i32(&out, "sent_index");
    let input_span_valid = matches!((start_char, end_char), (Some(s), Some(e)) if e > s);

    let state_row = sqlx::query(
        r#"
        SELECT text_hash, seg_version
        FROM event_sentence_state
        WHERE stream_id = $1 AND event_id = $2
        "#,
    )
    .bind(&evidence.stream_id)
    .bind(&evidence.event_id)
    .fetch_optional(&mut **tx)
    .await?;

    let (text_hash, seg_version) = if let Some(row) = state_row {
        (
            row.try_get::<String, _>("text_hash").unwrap_or_default(),
            row.try_get::<String, _>("seg_version").unwrap_or_default(),
        )
    } else {
        ("".to_string(), "".to_string())
    };

    let mut located_sent_index: Option<i32> = None;
    let mut final_start = start_char;
    let mut final_end = end_char;
    let mut span_status = "unlocated".to_string();
    let mut overlap_chars: i32 = 0;
    let mut covered_sentence_count: i32 = 0;

    if let Some(sent_idx) = req_sent_index {
        if let Some(row) = sqlx::query(
            r#"
            SELECT sent_index, start_char, end_char
            FROM event_sentence
            WHERE stream_id = $1 AND event_id = $2 AND sent_index = $3
            "#,
        )
        .bind(&evidence.stream_id)
        .bind(&evidence.event_id)
        .bind(sent_idx)
        .fetch_optional(&mut **tx)
        .await?
        {
            let s_start: i32 = row.try_get("start_char").unwrap_or_default();
            let s_end: i32 = row.try_get("end_char").unwrap_or_default();
            let overlaps = if let (Some(sc), Some(ec)) = (start_char, end_char) {
                overlap_len(sc, ec, s_start, s_end) > 0
            } else {
                true
            };
            if overlaps {
                located_sent_index = Some(sent_idx);
                final_start = Some(start_char.unwrap_or(s_start));
                final_end = Some(end_char.unwrap_or(s_end));
                span_status = "located".to_string();
                overlap_chars = if let (Some(sc), Some(ec)) = (start_char, end_char) {
                    overlap_len(sc, ec, s_start, s_end)
                } else {
                    s_end - s_start
                };
                covered_sentence_count = 1;
            }
        }
    }

    if located_sent_index.is_none() {
        if input_span_valid {
            let sc = start_char.unwrap_or_default();
            let ec = end_char.unwrap_or_default();
            let rows = sqlx::query(
                r#"
                SELECT sent_index, start_char, end_char
                FROM event_sentence
                WHERE stream_id = $1
                  AND event_id = $2
                  AND NOT (end_char <= $3 OR start_char >= $4)
                ORDER BY sent_index
                "#,
            )
            .bind(&evidence.stream_id)
            .bind(&evidence.event_id)
            .bind(sc)
            .bind(ec)
            .fetch_all(&mut **tx)
            .await?;
            covered_sentence_count = rows.len() as i32;

            let mut best: Option<(i32, i32, i32, i32)> = None;
            for row in rows {
                let sent_index: i32 = row.try_get("sent_index").unwrap_or_default();
                let s_start: i32 = row.try_get("start_char").unwrap_or_default();
                let s_end: i32 = row.try_get("end_char").unwrap_or_default();
                let ov = overlap_len(sc, ec, s_start, s_end);
                if ov <= 0 {
                    continue;
                }
                match best {
                    None => best = Some((sent_index, s_start, s_end, ov)),
                    Some((best_idx, _, _, best_ov)) => {
                        if ov > best_ov || (ov == best_ov && sent_index < best_idx) {
                            best = Some((sent_index, s_start, s_end, ov));
                        }
                    }
                }
            }
            if let Some((idx, _, _, _)) = best {
                located_sent_index = Some(idx);
                final_start = Some(sc);
                final_end = Some(ec);
                span_status = "located".to_string();
                overlap_chars = best.map(|(_, _, _, ov)| ov).unwrap_or_default();
            }
        }
    }

    // Only use first-sentence fallback when caller did not provide a valid span.
    if located_sent_index.is_none() && !input_span_valid {
        if let Some(row) = sqlx::query(
            r#"
            SELECT sent_index, start_char, end_char
            FROM event_sentence
            WHERE stream_id = $1 AND event_id = $2
            ORDER BY sent_index
            LIMIT 1
            "#,
        )
        .bind(&evidence.stream_id)
        .bind(&evidence.event_id)
        .fetch_optional(&mut **tx)
        .await?
        {
            let idx: i32 = row.try_get("sent_index").unwrap_or_default();
            let s_start: i32 = row.try_get("start_char").unwrap_or_default();
            let s_end: i32 = row.try_get("end_char").unwrap_or_default();
            located_sent_index = Some(idx);
            if final_start.is_none() {
                final_start = Some(s_start);
            }
            if final_end.is_none() {
                final_end = Some(s_end);
            }
            span_status = "fallback_first_sentence".to_string();
            overlap_chars = s_end - s_start;
            covered_sentence_count = 1;
        }
    }

    out["sent_index"] = located_sent_index.map(Value::from).unwrap_or(Value::Null);
    out["start_char"] = final_start.map(Value::from).unwrap_or(Value::Null);
    out["end_char"] = final_end.map(Value::from).unwrap_or(Value::Null);
    out["text_hash"] = Value::from(text_hash.trim().to_ascii_lowercase());
    out["seg_version"] = Value::from(seg_version);
    out["event_sentence_pk"] = json!({
        "stream_id": &evidence.stream_id,
        "event_id": &evidence.event_id,
        "sent_index": located_sent_index
    });
    out["span_status"] = Value::from(span_status);
    out["span_strategy"] = Value::from("sentence_v1");
    out["overlap_chars"] = Value::from(overlap_chars);
    out["covered_sentence_count"] = Value::from(covered_sentence_count);
    Ok(out)
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
        "missing required {label}: {}. Apply db/migrations_v2 with the full migration profile; runtime DDL has been removed.",
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
        "missing required {label}: {}. Apply db/migrations_v2 with the full migration profile; runtime DDL has been removed.",
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
        "missing required {label}: {}. Apply db/migrations_v2 with the full migration profile; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

async fn require_object_types(pool: &PgPool, type_ids: &[&str]) -> Result<(), sqlx::Error> {
    let mut missing = Vec::new();
    for type_id in type_ids {
        let row = sqlx::query(
            r#"
            SELECT EXISTS (
              SELECT 1
              FROM ontology_object_type
              WHERE type_id = $1
            ) AS present
            "#,
        )
        .bind(*type_id)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(*type_id);
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required ontology object types: {}. Apply db/migrations_v2 with the full migration profile; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

async fn require_relation_types(pool: &PgPool, predicates: &[&str]) -> Result<(), sqlx::Error> {
    let mut missing = Vec::new();
    for predicate in predicates {
        let row = sqlx::query(
            r#"
            SELECT EXISTS (
              SELECT 1
              FROM ontology_relation_type
              WHERE predicate = $1
            ) AS present
            "#,
        )
        .bind(*predicate)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(*predicate);
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required ontology relation types: {}. Apply db/migrations_v2 with the full migration profile; runtime DDL has been removed.",
        missing.join(", ")
    )))
}

#[cfg(test)]
mod tests {
    use super::{
        OntologyConceptInput, OntologyFactEvidenceInput, OntologyFactInput,
        build_semantic_alias_term, build_semantic_concept_terms,
        build_semantic_fact_reference_claims, build_semantic_fact_statement_metadata,
        build_semantic_item_metadata, is_ingest_extractor, map_legacy_fact_status_to_semantic_status,
        normalize_ingest_fact_status,
    };
    use serde_json::json;

    #[test]
    fn ingest_extractors_always_candidate() {
        let evidence = json!({"span_status":"located"});
        assert!(is_ingest_extractor("controlled_v1"));
        assert_eq!(
            normalize_ingest_fact_status("controlled_v1", "accepted", &evidence),
            "candidate"
        );
        assert_eq!(
            normalize_ingest_fact_status("llm_v1", "accepted", &evidence),
            "candidate"
        );
    }

    #[test]
    fn non_ingest_accepted_requires_located_span() {
        let located = json!({"span_status":"located"});
        let unlocated = json!({"span_status":"unlocated"});
        assert_eq!(
            normalize_ingest_fact_status("manual_review", "accepted", &located),
            "accepted"
        );
        assert_eq!(
            normalize_ingest_fact_status("manual_review", "accepted", &unlocated),
            "candidate"
        );
    }

    #[test]
    fn alias_dual_write_keeps_non_unique_normalized_term() {
        let term = build_semantic_alias_term("c-1", " 田野工作 ", 0.91, "llm_v2");
        assert_eq!(term.entity_id, "c-1");
        assert_eq!(term.term_type, "alias");
        assert_eq!(term.term, "田野工作");
        assert_eq!(term.normalized_term, "田野工作");
        assert_eq!(term.status, "active");
        assert_eq!(term.metadata_json["legacy_confidence"], json!(0.91));
        assert_eq!(term.metadata_json["legacy_extractor"], json!("llm_v2"));
    }

    #[test]
    fn fact_dual_write_metadata_tracks_legacy_fact_identity() {
        let fact = OntologyFactInput {
            src_concept_id: "Q1002".to_string(),
            predicate: "part_of".to_string(),
            dst_concept_id: "Q1003".to_string(),
            qualifier_json: json!({"scope":"ritual"}),
            confidence: 0.73,
            extractor: "manual_review".to_string(),
            status: "accepted".to_string(),
            review_note: "kept".to_string(),
        };

        let metadata = build_semantic_fact_statement_metadata(42, &fact);
        assert_eq!(metadata["legacy_fact_id"], json!(42));
        assert_eq!(metadata["legacy_predicate"], json!("part_of"));
        assert_eq!(metadata["legacy_extractor"], json!("manual_review"));
        assert_eq!(metadata["legacy_review_note"], json!("kept"));
        assert_eq!(metadata["legacy_qualifier_json"], json!({"scope":"ritual"}));
    }

    #[test]
    fn fact_dual_write_reference_claims_capture_evidence_and_span() {
        let evidence = OntologyFactEvidenceInput {
            stream_id: "arch-1".to_string(),
            event_id: "evt-9".to_string(),
            asset_id: Some("artifact-7".to_string()),
            version_number: Some(3),
            source_span: Some("p3:12-18".to_string()),
            evidence_json: json!({"sent_index": 2, "span_status": "located"}),
            confidence: 0.88,
        };

        let claims = build_semantic_fact_reference_claims(&evidence);
        assert_eq!(claims.len(), 2);
        assert_eq!(claims[0].property_id, "tdb.ref.legacy_event");
        assert_eq!(
            claims[0].value_json,
            json!({
                "stream_id": "arch-1",
                "event_id": "evt-9",
                "asset_id": "artifact-7",
                "version_number": 3,
                "confidence": 0.88,
                "evidence_json": {"sent_index": 2, "span_status": "located"}
            })
        );
        assert_eq!(claims[1].property_id, "tdb.ref.source_span");
        assert_eq!(claims[1].value_json, json!("p3:12-18"));
    }

    #[test]
    fn concept_dual_write_builds_label_and_alias_terms() {
        let concept = OntologyConceptInput {
            concept_id: "Q1002".to_string(),
            canonical_name: "田野工作".to_string(),
            concept_type: "activity".to_string(),
            aliases: vec!["田野".to_string(), "考古田野".to_string()],
        };

        let terms = build_semantic_concept_terms(&concept);
        assert_eq!(terms.len(), 3);
        assert_eq!(terms[0].term_type, "label");
        assert_eq!(terms[0].term, "田野工作");
        assert_eq!(terms[0].normalized_term, "田野工作");
        assert_eq!(terms[1].term_type, "alias");
        assert_eq!(terms[1].term, "田野");
        assert_eq!(terms[2].term, "考古田野");
    }

    #[test]
    fn concept_dual_write_entity_metadata_keeps_legacy_shape() {
        let concept = OntologyConceptInput {
            concept_id: "Q1002".to_string(),
            canonical_name: "田野工作".to_string(),
            concept_type: "activity".to_string(),
            aliases: vec!["田野".to_string()],
        };

        let metadata = build_semantic_item_metadata(&concept);
        assert_eq!(metadata["legacy_concept_type"], json!("activity"));
        assert_eq!(metadata["legacy_canonical_name"], json!("田野工作"));
        assert_eq!(metadata["legacy_aliases"], json!(["田野"]));
        assert_eq!(metadata["dual_write_source"], json!("ontology_concept"));
    }

    #[test]
    fn semantic_statement_status_maps_legacy_candidate_to_extracted() {
        assert_eq!(
            map_legacy_fact_status_to_semantic_status("candidate"),
            "extracted"
        );
        assert_eq!(
            map_legacy_fact_status_to_semantic_status("accepted"),
            "accepted"
        );
        assert_eq!(
            map_legacy_fact_status_to_semantic_status("needs_review"),
            "reviewed"
        );
        assert_eq!(
            map_legacy_fact_status_to_semantic_status("rejected"),
            "rejected"
        );
    }
}
