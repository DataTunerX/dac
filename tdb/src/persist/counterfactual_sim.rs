use std::collections::{HashMap, HashSet, VecDeque};
use std::error::Error;

use serde::Serialize;
use serde_json::{Value, json};
use sqlx::{PgPool, Row};

type DynError = Box<dyn Error + Send + Sync>;

#[derive(Debug, Clone, Serialize)]
pub struct RemovedEventItem {
    pub concept_id: String,
    pub canonical_name: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct SimulationResult {
    pub stream_id: String,
    pub mode: String,
    pub remove_event: String,
    pub removed_event_count: usize,
    pub removed_events: Vec<RemovedEventItem>,
    pub impacted_facts: u64,
    pub evidence_pointers: Vec<String>,
}

pub async fn simulate_ablation(
    database_url: &str,
    stream_id: &str,
    remove_event_concept_id: &str,
) -> Result<SimulationResult, DynError> {
    let pool = PgPool::connect(database_url).await?;
    let removed_set = collect_removed_by_causes(&pool, remove_event_concept_id).await?;

    let mut removed_ids: Vec<String> = removed_set.iter().cloned().collect();
    removed_ids.sort();

    let mut removed_events = Vec::new();
    for concept_id in &removed_ids {
        let row = sqlx::query(
            r#"
            SELECT canonical_name
            FROM ontology_concept
            WHERE concept_id = $1
            "#,
        )
        .bind(concept_id)
        .fetch_optional(&pool)
        .await?;
        let canonical_name = row
            .and_then(|r| r.try_get::<String, _>("canonical_name").ok())
            .unwrap_or_default();
        removed_events.push(RemovedEventItem {
            concept_id: concept_id.clone(),
            canonical_name,
        });
    }

    let slot_fact_count: i64 = sqlx::query_scalar(
        r#"
        SELECT COUNT(*)::BIGINT
        FROM ontology_fact f
        JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
        WHERE fe.stream_id = $1
          AND f.src_concept_id = ANY($2)
          AND f.predicate IN ('has_actor', 'has_object', 'occurs_at')
        "#,
    )
    .bind(stream_id)
    .bind(&removed_ids)
    .fetch_one(&pool)
    .await?;

    let evidence_rows = sqlx::query(
        r#"
        SELECT DISTINCT COALESCE(fe.evidence_json->>'event_sentence_pk', '') AS event_sentence_pk
        FROM ontology_fact f
        JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
        WHERE fe.stream_id = $1
          AND f.src_concept_id = ANY($2)
          AND COALESCE(fe.evidence_json->>'event_sentence_pk', '') <> ''
        ORDER BY event_sentence_pk ASC
        LIMIT 200
        "#,
    )
    .bind(stream_id)
    .bind(&removed_ids)
    .fetch_all(&pool)
    .await?;
    let evidence_pointers = evidence_rows
        .into_iter()
        .filter_map(|r| r.try_get::<String, _>("event_sentence_pk").ok())
        .collect::<Vec<_>>();

    Ok(SimulationResult {
        stream_id: stream_id.to_string(),
        mode: "ablation".to_string(),
        remove_event: remove_event_concept_id.to_string(),
        removed_event_count: removed_events.len(),
        removed_events,
        impacted_facts: slot_fact_count.max(0) as u64,
        evidence_pointers,
    })
}

pub async fn simulate_swap(
    _database_url: &str,
    _stream_id: &str,
    _from_event_id: &str,
    _action_key: &str,
) -> Result<SimulationResult, DynError> {
    Err("swap mode is reserved for next iteration; use mode=ablation in MVP".into())
}

async fn collect_removed_by_causes(
    pool: &PgPool,
    root_event: &str,
) -> Result<HashSet<String>, sqlx::Error> {
    let cause_rows = sqlx::query(
        r#"
        SELECT src_concept_id, dst_concept_id
        FROM ontology_fact
        WHERE predicate = 'causes'
          AND status IN ('accepted', 'candidate')
        "#,
    )
    .fetch_all(pool)
    .await?;

    let mut graph: HashMap<String, Vec<String>> = HashMap::new();
    for row in cause_rows {
        let src: String = row.try_get("src_concept_id")?;
        let dst: String = row.try_get("dst_concept_id")?;
        graph.entry(src).or_default().push(dst);
    }

    let mut removed = HashSet::new();
    let mut q = VecDeque::new();
    removed.insert(root_event.to_string());
    q.push_back(root_event.to_string());

    while let Some(cur) = q.pop_front() {
        if let Some(nexts) = graph.get(&cur) {
            for n in nexts {
                if removed.insert(n.clone()) {
                    q.push_back(n.clone());
                }
            }
        }
    }
    Ok(removed)
}

pub fn result_to_trace(result: &SimulationResult) -> Value {
    json!({
      "stream_id": result.stream_id,
      "mode": result.mode,
      "remove_event": result.remove_event,
      "removed_event_count": result.removed_event_count,
      "removed_events": result.removed_events,
      "impacted_facts": result.impacted_facts,
      "evidence_pointers": result.evidence_pointers,
    })
}
