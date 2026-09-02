use std::collections::{BTreeMap, HashMap, HashSet};
use std::error::Error;

use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{PgPool, Row};
use time::OffsetDateTime;

type DynError = Box<dyn Error + Send + Sync>;
const SEMANTIC_QUALIFIER_PROPERTY_ID: &str = "tdb.qualifier.payload";
const SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID: &str = "tdb.ref.legacy_event";

#[derive(Debug, Clone, Serialize)]
pub struct EventParticipant {
    pub concept_id: String,
    pub canonical_name: String,
    pub role: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct EventNode {
    pub event_concept_id: String,
    pub event_name: String,
    pub source_event_id: String,
    pub sent_index: i32,
    pub participants: Vec<EventParticipant>,
    pub locations: Vec<String>,
    pub objects: Vec<String>,
    pub causes_to: Vec<String>,
    pub evidence_sentence_keys: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct ProjectionFilters {
    pub include_candidate: bool,
    pub include_accepted: bool,
}

impl Default for ProjectionFilters {
    fn default() -> Self {
        Self {
            include_candidate: true,
            include_accepted: true,
        }
    }
}

pub async fn project_state(
    database_url: &str,
    stream_id: &str,
    as_of: OffsetDateTime,
    filters: ProjectionFilters,
) -> Result<Value, DynError> {
    let pool = PgPool::connect(database_url).await?;
    let events = load_event_nodes(&pool, stream_id, &filters).await?;
    Ok(project_state_from_events(stream_id, as_of, &events))
}

pub async fn load_event_nodes(
    pool: &PgPool,
    stream_id: &str,
    filters: &ProjectionFilters,
) -> Result<Vec<EventNode>, sqlx::Error> {
    let semantic_statuses = semantic_projection_statuses(filters);
    let semantic_rows = sqlx::query(
        r#"
        SELECT
          ss.statement_id::text AS row_id,
          ss.subject_id AS event_concept_id,
          ec.canonical_name AS event_name,
          ss.property_id AS predicate,
          ss.value_entity_id AS dst_concept_id,
          dc.canonical_name AS dst_name,
          COALESCE(sq.value_json->>'role', '') AS role,
          COALESCE(sr.legacy_event_id, sr.value_json->>'event_id', '') AS event_id,
          COALESCE((sr.value_json->'evidence_json'->>'sent_index')::int, 0) AS sent_index,
          COALESCE(sr.value_json->'evidence_json'->>'event_sentence_pk', '') AS event_sentence_pk
        FROM semantic_statement ss
        JOIN ontology_concept ec ON ec.concept_id = ss.subject_id
        JOIN ontology_concept dc ON dc.concept_id = ss.value_entity_id
        LEFT JOIN statement_qualifier sq
          ON sq.statement_id = ss.statement_id
         AND sq.property_id = $3
        LEFT JOIN LATERAL (
          SELECT legacy_event_id, value_json
          FROM statement_reference
          WHERE statement_id = ss.statement_id
            AND property_id = $4
            AND legacy_stream_id = $1
          ORDER BY ordinal ASC
          LIMIT 1
        ) sr ON TRUE
        WHERE ec.concept_type = 'event'
          AND ss.value_type = 'entity'
          AND ss.status = ANY($2)
          AND ss.property_id IN ('has_actor', 'occurs_at', 'has_object', 'causes')
          AND sr.value_json IS NOT NULL
        ORDER BY event_id ASC, sent_index ASC, row_id ASC
        "#,
    )
    .bind(stream_id)
    .bind(&semantic_statuses)
    .bind(SEMANTIC_QUALIFIER_PROPERTY_ID)
    .bind(SEMANTIC_REFERENCE_LEGACY_EVENT_PROPERTY_ID)
    .fetch_all(pool)
    .await?;
    if !semantic_rows.is_empty() {
        return build_event_nodes_from_rows(semantic_rows);
    }

    let statuses = legacy_projection_statuses(filters);
    let rows = sqlx::query(
        r#"
        SELECT
          f.fact_id,
          f.src_concept_id AS event_concept_id,
          ec.canonical_name AS event_name,
          f.predicate,
          f.dst_concept_id,
          dc.canonical_name AS dst_name,
          COALESCE(f.qualifier_json->>'role', '') AS role,
          fe.event_id,
          COALESCE((fe.evidence_json->>'sent_index')::int, 0) AS sent_index,
          COALESCE((fe.evidence_json->>'event_sentence_pk'), '') AS event_sentence_pk
        FROM ontology_fact f
        JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
        JOIN ontology_concept ec ON ec.concept_id = f.src_concept_id
        JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
        WHERE fe.stream_id = $1
          AND ec.concept_type = 'event'
          AND f.status = ANY($2)
          AND f.predicate IN ('has_actor', 'occurs_at', 'has_object', 'causes')
        ORDER BY fe.event_id ASC,
                 COALESCE((fe.evidence_json->>'sent_index')::int, 0) ASC,
                 f.fact_id ASC
        "#,
    )
    .bind(stream_id)
    .bind(&statuses)
    .fetch_all(pool)
    .await?;

    build_event_nodes_from_rows(rows)
}

fn build_event_nodes_from_rows(rows: Vec<sqlx::postgres::PgRow>) -> Result<Vec<EventNode>, sqlx::Error> {
    let mut grouped: HashMap<String, EventNode> = HashMap::new();
    for row in rows {
        let event_id: String = row.try_get("event_concept_id")?;
        let dst_concept_id: String = row.try_get("dst_concept_id")?;
        let dst_name: String = row.try_get("dst_name")?;
        let predicate: String = row.try_get("predicate")?;
        let role: String = row.try_get("role")?;
        let source_event_id: String = row.try_get("event_id")?;
        let sent_index: i32 = row.try_get("sent_index")?;
        let sentence_pk: String = row.try_get("event_sentence_pk")?;

        let node = grouped
            .entry(event_id.clone())
            .or_insert_with(|| EventNode {
                event_concept_id: event_id.clone(),
                event_name: row.try_get::<String, _>("event_name").unwrap_or_default(),
                source_event_id: source_event_id.clone(),
                sent_index,
                participants: vec![],
                locations: vec![],
                objects: vec![],
                causes_to: vec![],
                evidence_sentence_keys: vec![],
            });

        if node.source_event_id.is_empty() {
            node.source_event_id = source_event_id;
        }
        if sent_index < node.sent_index {
            node.sent_index = sent_index;
        }
        if !sentence_pk.is_empty() {
            node.evidence_sentence_keys.push(sentence_pk);
        }

        match predicate.as_str() {
            "has_actor" => node.participants.push(EventParticipant {
                concept_id: dst_concept_id,
                canonical_name: dst_name,
                role,
            }),
            "occurs_at" => node.locations.push(dst_concept_id),
            "has_object" => node.objects.push(dst_concept_id),
            "causes" => node.causes_to.push(dst_concept_id),
            _ => {}
        }
    }

    let mut out: Vec<EventNode> = grouped.into_values().collect();
    for ev in &mut out {
        ev.participants
            .sort_by(|a, b| a.concept_id.cmp(&b.concept_id));
        ev.participants
            .dedup_by(|a, b| a.concept_id == b.concept_id && a.role == b.role);
        ev.locations.sort();
        ev.locations.dedup();
        ev.objects.sort();
        ev.objects.dedup();
        ev.causes_to.sort();
        ev.causes_to.dedup();
        ev.evidence_sentence_keys.sort();
        ev.evidence_sentence_keys.dedup();
    }

    out.sort_by(|a, b| {
        a.source_event_id
            .cmp(&b.source_event_id)
            .then(a.sent_index.cmp(&b.sent_index))
            .then(a.event_concept_id.cmp(&b.event_concept_id))
    });
    Ok(out)
}

fn legacy_projection_statuses(filters: &ProjectionFilters) -> Vec<String> {
    match (filters.include_candidate, filters.include_accepted) {
        (true, true) => vec!["candidate".to_string(), "accepted".to_string()],
        (true, false) => vec!["candidate".to_string()],
        (false, true) => vec!["accepted".to_string()],
        (false, false) => vec!["accepted".to_string()],
    }
}

fn semantic_projection_statuses(filters: &ProjectionFilters) -> Vec<String> {
    match (filters.include_candidate, filters.include_accepted) {
        (true, true) => vec!["extracted".to_string(), "accepted".to_string()],
        (true, false) => vec!["extracted".to_string()],
        (false, true) => vec!["accepted".to_string()],
        (false, false) => vec!["accepted".to_string()],
    }
}

pub fn project_state_from_events(
    stream_id: &str,
    as_of: OffsetDateTime,
    events: &[EventNode],
) -> Value {
    let mut character_location: BTreeMap<String, String> = BTreeMap::new();
    let mut inventory: BTreeMap<String, i64> = BTreeMap::new();
    let mut hostility: BTreeMap<String, i64> = BTreeMap::new();

    for ev in events {
        let event_name = ev.event_name.as_str();
        let is_eating = event_name.contains('吃') || event_name.contains("ate");
        let is_accuse = contains_any(event_name, &["指控", "怪罪", "责", "诬", "accus"]);
        let is_conflict = contains_any(event_name, &["打", "斗", "冲突", "fought", "战"]);

        if !ev.locations.is_empty() {
            let location_id = ev.locations[0].clone();
            for p in &ev.participants {
                if ["traveler", "subject", "actor", "eater"].contains(&p.role.as_str()) {
                    character_location.insert(p.concept_id.clone(), location_id.clone());
                }
            }
        }

        if is_eating {
            for obj in &ev.objects {
                *inventory.entry(obj.clone()).or_insert(0) -= 1;
            }
        }

        if is_accuse || is_conflict {
            let actors: Vec<&EventParticipant> = ev
                .participants
                .iter()
                .filter(|p| ["accuser", "actor", "attacker", "subject"].contains(&p.role.as_str()))
                .collect();
            let targets: Vec<&EventParticipant> = ev
                .participants
                .iter()
                .filter(|p| ["target", "accused", "defender", "object"].contains(&p.role.as_str()))
                .collect();

            for a in &actors {
                for t in &targets {
                    if a.concept_id == t.concept_id {
                        continue;
                    }
                    let key = format!("{}->{}", a.concept_id, t.concept_id);
                    *hostility.entry(key).or_insert(0) += 1;
                }
            }
        }
    }

    let as_of_text = as_of
        .format(&time::format_description::well_known::Rfc3339)
        .unwrap_or_default();

    json!({
        "stream_id": stream_id,
        "as_of": as_of_text,
        "event_count": events.len(),
        "character_location": character_location,
        "inventory": inventory,
        "hostility": hostility,
    })
}

pub fn state_diff(before: &Value, after: &Value) -> Value {
    json!({
        "character_location": diff_object(before.get("character_location"), after.get("character_location")),
        "inventory": diff_object(before.get("inventory"), after.get("inventory")),
        "hostility": diff_object(before.get("hostility"), after.get("hostility")),
    })
}

fn diff_object(before: Option<&Value>, after: Option<&Value>) -> Value {
    let mut keys = HashSet::new();
    if let Some(b) = before.and_then(|v| v.as_object()) {
        keys.extend(b.keys().cloned());
    }
    if let Some(a) = after.and_then(|v| v.as_object()) {
        keys.extend(a.keys().cloned());
    }

    let mut out = serde_json::Map::new();
    for k in keys {
        let b = before.and_then(|v| v.get(&k));
        let a = after.and_then(|v| v.get(&k));
        if b != a {
            out.insert(
                k,
                json!({
                    "before": b.cloned().unwrap_or(Value::Null),
                    "after": a.cloned().unwrap_or(Value::Null)
                }),
            );
        }
    }
    Value::Object(out)
}

fn contains_any(s: &str, needles: &[&str]) -> bool {
    needles.iter().any(|n| s.contains(n))
}
