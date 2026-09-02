use std::collections::HashSet;
use std::error::Error;

use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{PgPool, Row};

use crate::persist::ontology_store::{
    OntologyConceptInput, OntologyFactEvidenceInput, OntologyFactInput, OntologyStore,
};

type DynError = Box<dyn Error + Send + Sync>;

#[derive(Debug, Clone, Serialize)]
pub struct EventProjectionStats {
    pub stream_id: String,
    pub dry_run: bool,
    pub source_facts_scanned: u64,
    pub source_facts_projected: u64,
    pub event_concepts_upserted: u64,
    pub slot_facts_written: u64,
    pub skipped_pronoun_surface: u64,
    pub skipped_unsupported_predicate: u64,
}

#[derive(Debug, Clone)]
pub struct SourceFactRow {
    pub fact_id: i64,
    pub src_concept_id: String,
    pub src_name: String,
    pub predicate: String,
    pub dst_concept_id: String,
    pub dst_name: String,
    pub confidence: f64,
    pub event_id: String,
    pub sent_index: i32,
    pub start_char: i32,
    pub end_char: i32,
}

#[derive(Debug, Clone)]
pub struct EventEvidenceRef {
    pub stream_id: String,
    pub event_id: String,
    pub sent_index: i32,
    pub start_char: i32,
    pub end_char: i32,
    pub source_fact_id: i64,
    pub source_predicate: String,
    pub confidence: f64,
}

pub fn default_projection_predicates() -> HashSet<String> {
    ["ate", "located_at"]
        .iter()
        .map(|s| s.to_string())
        .collect()
}

pub async fn validate_event_projection_registry(pool: &PgPool) -> Result<(), sqlx::Error> {
    let required = [
        ("has_actor", "event", "entity"),
        ("has_object", "event", "entity"),
        ("occurs_at", "event", "location"),
        ("causes", "event", "event"),
        ("enables_action", "event", "activity"),
        ("chosen_action", "event", "activity"),
    ];
    let mut missing = Vec::new();
    for (predicate, src_type_id, dst_type_id) in required {
        let row = sqlx::query(
            r#"
            SELECT EXISTS (
              SELECT 1
              FROM ontology_relation_type
              WHERE predicate = $1
                AND src_type_id = $2
                AND dst_type_id = $3
            ) AS present
            "#,
        )
        .bind(predicate)
        .bind(src_type_id)
        .bind(dst_type_id)
        .fetch_one(pool)
        .await?;
        let present: bool = row.try_get("present")?;
        if !present {
            missing.push(format!("{predicate}({src_type_id}->{dst_type_id})"));
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required event projection registry entries: {}. Load eval/DocFood/tools/predicate_discovery/ontology_registry.digital_twin_mvp.v2.json via `tdb_agent_bridge load_ontology_registry` before building the event ontology.",
        missing.join(", ")
    )))
}

pub async fn create_or_get_event_concept(
    store: &OntologyStore,
    stream_id: &str,
    event_key: &str,
    canonical_name: &str,
) -> Result<String, sqlx::Error> {
    let concept_id = format!("event:{stream_id}:{event_key}");
    store
        .upsert_concept(&OntologyConceptInput {
            concept_id: concept_id.clone(),
            canonical_name: canonical_name.to_string(),
            concept_type: "event".to_string(),
            aliases: vec![event_key.to_string()],
        })
        .await?;
    Ok(concept_id)
}

pub async fn upsert_event_slot_fact(
    store: &OntologyStore,
    event_concept_id: &str,
    predicate: &str,
    dst_concept_id: &str,
    qualifier_json: Value,
    evidence_ref: &EventEvidenceRef,
    dry_run: bool,
) -> Result<bool, sqlx::Error> {
    if dry_run {
        return Ok(false);
    }
    let evidence_json = json!({
        "schema": "sentence_v1",
        "sent_index": evidence_ref.sent_index,
        "start_char": evidence_ref.start_char,
        "end_char": evidence_ref.end_char,
        "source_fact_id": evidence_ref.source_fact_id,
        "source_predicate": evidence_ref.source_predicate,
        "extractor": "controlled_v1",
        "projection": "event_ontology_v1"
    });

    store
        .upsert_fact_with_evidence(
            &OntologyFactInput {
                src_concept_id: event_concept_id.to_string(),
                predicate: predicate.to_string(),
                dst_concept_id: dst_concept_id.to_string(),
                qualifier_json,
                confidence: evidence_ref.confidence.clamp(0.0, 1.0),
                extractor: "controlled_v1".to_string(),
                status: "candidate".to_string(),
                review_note: "event projection from minimal predicates".to_string(),
            },
            &OntologyFactEvidenceInput {
                stream_id: evidence_ref.stream_id.clone(),
                event_id: evidence_ref.event_id.clone(),
                asset_id: None,
                version_number: None,
                source_span: None,
                evidence_json,
                confidence: evidence_ref.confidence.clamp(0.0, 1.0),
            },
        )
        .await
}

pub async fn build_event_ontology_from_triples(
    database_url: &str,
    stream_id: &str,
    predicates: &HashSet<String>,
    dry_run: bool,
) -> Result<EventProjectionStats, DynError> {
    let pool = PgPool::connect(database_url).await?;
    let store = OntologyStore::new(database_url).await?;
    validate_event_projection_registry(&pool).await?;

    let mut predicate_vec: Vec<String> = predicates.iter().cloned().collect();
    predicate_vec.sort();

    let rows = sqlx::query(
        r#"
        SELECT
          f.fact_id,
          f.src_concept_id,
          sc.canonical_name AS src_name,
          f.predicate,
          f.dst_concept_id,
          dc.canonical_name AS dst_name,
          f.confidence,
          fe.event_id,
          COALESCE((fe.evidence_json->>'sent_index')::int, 0) AS sent_index,
          COALESCE((fe.evidence_json->>'start_char')::int, 0) AS start_char,
          COALESCE((fe.evidence_json->>'end_char')::int, 0) AS end_char
        FROM ontology_fact f
        JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
        JOIN ontology_concept sc ON sc.concept_id = f.src_concept_id
        JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
        WHERE fe.stream_id = $1
          AND f.predicate = ANY($2)
          AND f.status IN ('accepted', 'candidate')
        ORDER BY fe.event_id ASC,
                 COALESCE((fe.evidence_json->>'sent_index')::int, 0) ASC,
                 f.fact_id ASC
        "#,
    )
    .bind(stream_id)
    .bind(&predicate_vec)
    .fetch_all(&pool)
    .await?;

    let mut stats = EventProjectionStats {
        stream_id: stream_id.to_string(),
        dry_run,
        source_facts_scanned: rows.len() as u64,
        source_facts_projected: 0,
        event_concepts_upserted: 0,
        slot_facts_written: 0,
        skipped_pronoun_surface: 0,
        skipped_unsupported_predicate: 0,
    };

    for row in rows {
        let src = SourceFactRow {
            fact_id: row.try_get("fact_id")?,
            src_concept_id: row.try_get("src_concept_id")?,
            src_name: row.try_get("src_name")?,
            predicate: row.try_get("predicate")?,
            dst_concept_id: row.try_get("dst_concept_id")?,
            dst_name: row.try_get("dst_name")?,
            confidence: row.try_get("confidence")?,
            event_id: row.try_get("event_id")?,
            sent_index: row.try_get("sent_index")?,
            start_char: row.try_get("start_char")?,
            end_char: row.try_get("end_char")?,
        };

        if is_pronoun_surface(&src.src_name) || is_pronoun_surface(&src.dst_name) {
            stats.skipped_pronoun_surface += 1;
            continue;
        }

        let (event_key, canonical_name, actor_role, maybe_object_predicate, object_role) =
            match src.predicate.as_str() {
                "ate" => (
                    format!("eat:{}:{}:{}", src.event_id, src.sent_index, src.fact_id),
                    "EatingEvent",
                    "eater",
                    Some("has_object"),
                    Some("food"),
                ),
                "located_at" => (
                    format!("arrive:{}:{}:{}", src.event_id, src.sent_index, src.fact_id),
                    "ArrivalEvent",
                    "traveler",
                    Some("occurs_at"),
                    None,
                ),
                _ => {
                    stats.skipped_unsupported_predicate += 1;
                    continue;
                }
            };

        let event_concept_id = if dry_run {
            format!("event:{stream_id}:{event_key}")
        } else {
            create_or_get_event_concept(&store, stream_id, &event_key, canonical_name).await?
        };
        stats.event_concepts_upserted += 1;

        let ev = EventEvidenceRef {
            stream_id: stream_id.to_string(),
            event_id: src.event_id.clone(),
            sent_index: src.sent_index,
            start_char: src.start_char,
            end_char: src.end_char,
            source_fact_id: src.fact_id,
            source_predicate: src.predicate.clone(),
            confidence: src.confidence,
        };

        if upsert_event_slot_fact(
            &store,
            &event_concept_id,
            "has_actor",
            &src.src_concept_id,
            json!({
                "schema": "event_projection_v1",
                "role": actor_role,
                "source_fact_id": src.fact_id
            }),
            &ev,
            dry_run,
        )
        .await?
        {
            stats.slot_facts_written += 1;
        }

        if let Some(slot_predicate) = maybe_object_predicate {
            let qualifier = if let Some(role) = object_role {
                json!({
                    "schema": "event_projection_v1",
                    "role": role,
                    "source_fact_id": src.fact_id
                })
            } else {
                json!({
                    "schema": "event_projection_v1",
                    "source_fact_id": src.fact_id
                })
            };

            if upsert_event_slot_fact(
                &store,
                &event_concept_id,
                slot_predicate,
                &src.dst_concept_id,
                qualifier,
                &ev,
                dry_run,
            )
            .await?
            {
                stats.slot_facts_written += 1;
            }
        }

        stats.source_facts_projected += 1;
    }

    Ok(stats)
}

fn is_pronoun_surface(raw: &str) -> bool {
    let s = raw.trim();
    !s.is_empty()
        && [
            "我", "你", "他", "她", "它", "他们", "我们", "你们", "此", "彼", "此物", "这厮",
            "那厮", "这", "那",
        ]
        .contains(&s)
}
