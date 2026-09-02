use std::env;
use std::fs;
use std::process::{Command, Stdio};
use std::time::Instant;

use serde::{Deserialize, Serialize};
use serde_json::json;
use sqlx::Row;
use tdb::persist::bridge_log::log_info;
use tdb::persist::counterfactual_sim::result_to_trace;
use tdb::persist::counterfactual_sim::{simulate_ablation, simulate_swap};
use tdb::persist::event_ontology::{
    build_event_ontology_from_triples, default_projection_predicates,
};
use tdb::persist::ontology_fact_history::load_fact_history_payload;
use tdb::persist::event_sentence_store::EventSentenceStore;
use tdb::persist::ontology_store::{OntologyFactReviewInput, OntologyStore};
use tdb::persist::state_projector::{ProjectionFilters, project_state};
use tdb::rpc::ontology::OntologyRpcStore;
use tdb::rpc::proto::ListOntologyFactsRequest;

fn usage() -> String {
    [
        "Usage:",
        "  (optional) append --log-file <path> to write INFO/DEBUG logs to file",
        "  cargo run --bin tdb_agent_bridge -- segment_event_sentences [--stream-id <id>] [--limit <n>] [--seg-version <v>]",
        "  cargo run --bin tdb_agent_bridge -- locate_event_span --stream-id <id> --event-id <id> --start-char <n> --end-char <n>",
        "  cargo run --bin tdb_agent_bridge -- ontology_governance_report [--stream-id <id>] [--review-limit <n>] [--stale-days <n>]",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_facts [--status <accepted|candidate|needs_review|rejected|all>] [--stream-id <id>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- review_ontology_fact --fact-id <id> --decision <accept|reject|needs_work> [--reviewer <name>] [--note <text>]",
        "  cargo run --bin tdb_agent_bridge -- review_ontology_facts_bulk --decision <accept|reject|needs_work> [--status <candidate|needs_review|accepted|rejected|all>] [--stream-id <id>] [--predicate <p>] [--extractor <x>] [--stale-days <n>] [--min-confidence <f>] [--max-confidence <f>] [--limit <n>] [--reviewer <name>] [--note <text>] [--dry-run]",
        "  cargo run --bin tdb_agent_bridge -- backfill_semantic_kernel_legacy_ontology [--fact-id <id>] [--fact-ids <id1,id2>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- fact_history --fact-id <id> [--stream-id <id>] [--evidence-limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- open_ontology_case --stream-id <id> --title <text> [--description <text>] [--priority <p1|p2|p3>] [--owner <name>] [--fact-id <id>] [--fact-ids <id1,id2>] [--note <text>]",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_cases [--stream-id <id>] [--status <open|in_review|resolved|dismissed|all>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- record_ontology_case_decision --case-id <id> --decision-kind <kind> --verdict <verdict> --summary <text> [--rationale <text>] --as-of-system-time <ts> [--as-of-effective-time <ts>] [--snapshot-id <id>] [--source-evidence-json <json>] [--supersedes-case-decision-id <id>] [--created-by <name>]",
        "  cargo run --bin tdb_agent_bridge -- case_detail --case-id <id> [--evidence-limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- update_ontology_case --case-id <id> [--status <open|in_review|resolved|dismissed>] [--owner <name>] [--note <text>]",
        "  cargo run --bin tdb_agent_bridge -- open_ontology_alert [--stream-id <id>] [--case-id <id>] --message <text> [--severity <low|medium|high|critical>]",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_alerts [--stream-id <id>] [--status <open|acked|closed|all>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- update_ontology_alert --alert-id <id> --status <open|acked|closed> [--note <text>]",
        "  cargo run --bin tdb_agent_bridge -- run_ontology_ops_rules [--stream-id <id>] [--stale-days <n>] [--conflict-predicate <p>] [--dry-run]",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_ops_runs [--stream-id <id>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_ops_rule_config [--stream-id <id>]",
        "  cargo run --bin tdb_agent_bridge -- upsert_ontology_ops_rule_config --rule-name <default|stale_pending|conflict_predicate> [--stream-id <id>] [--enabled <true|false>] [--stale-days <n>] [--conflict-predicate <p>] [--severity <low|medium|high|critical>] [--note <text>]",
        "  cargo run --bin tdb_agent_bridge -- load_ontology_registry --file <path>",
        "  cargo run --bin tdb_agent_bridge -- list_ontology_registry_loads [--registry-name <name>] [--limit <n>]",
        "  cargo run --bin tdb_agent_bridge -- build_event_ontology_from_triples --stream-id <id> [--predicate <p1,p2,p3>] [--dry-run]",
        "  cargo run --bin tdb_agent_bridge -- simulate_counterfactual --stream-id <id> --mode <ablation|swap> [--remove-event <event_id>] [--from-event <event_id>] [--action <action_key>]",
        "  cargo run --bin tdb_agent_bridge -- project_world_state --stream-id <id> [--accepted-only]",
    ]
    .join("\n")
}

#[derive(Debug, Deserialize, Serialize, Default, Clone)]
struct RegistryPromotionCfg {
    auto_promote: Option<bool>,
    min_confidence: Option<f64>,
    min_evidence_count: Option<i32>,
    min_distinct_event_count: Option<i32>,
    allow_cross_sentence: Option<bool>,
}

#[derive(Debug, Deserialize, Serialize, Default, Clone)]
struct RegistryEvidenceCfg {
    require_span_contract: Option<bool>,
    require_located: Option<bool>,
    min_overlap_chars: Option<i32>,
    max_covered_sentence_count: Option<i32>,
}

#[derive(Debug, Deserialize, Serialize, Default, Clone)]
struct RegistryConflictCfg {
    conflict_key: Option<String>,
    conflict_policy: Option<String>,
    create_case: Option<bool>,
    case_priority: Option<String>,
    alert_severity: Option<String>,
}

#[derive(Debug, Deserialize, Serialize, Default, Clone)]
struct RegistryDefaults {
    enabled: Option<bool>,
    src_type_id: Option<String>,
    dst_type_id: Option<String>,
    promotion: Option<RegistryPromotionCfg>,
    evidence: Option<RegistryEvidenceCfg>,
    conflict: Option<RegistryConflictCfg>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
struct RegistryPredicate {
    predicate: String,
    display_name: Option<String>,
    description: Option<String>,
    src_type_id: Option<String>,
    dst_type_id: Option<String>,
    enabled: Option<bool>,
    promotion: Option<RegistryPromotionCfg>,
    evidence: Option<RegistryEvidenceCfg>,
    conflict: Option<RegistryConflictCfg>,
}

#[derive(Debug, Deserialize, Serialize)]
struct OntologyRegistryFile {
    version: Option<i32>,
    registry_name: Option<String>,
    defaults: Option<RegistryDefaults>,
    predicates: Vec<RegistryPredicate>,
}

fn pick_opt<T: Clone>(specific: &Option<T>, default: &Option<T>, fallback: T) -> T {
    specific
        .clone()
        .or_else(|| default.clone())
        .unwrap_or(fallback)
}

fn parse_registry_file(raw: &str) -> Result<OntologyRegistryFile, String> {
    if let Ok(v) = serde_json::from_str::<OntologyRegistryFile>(raw) {
        return Ok(v);
    }
    let py = r#"
import json, sys
try:
    import yaml
except Exception as e:
    print(f"missing_pyyaml:{e}", file=sys.stderr)
    sys.exit(2)
obj = yaml.safe_load(sys.stdin.read())
print(json.dumps(obj, ensure_ascii=False))
"#;
    let mut child = Command::new("python3")
        .arg("-c")
        .arg(py)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to launch python3: {e}"))?;
    if let Some(mut stdin) = child.stdin.take() {
        use std::io::Write as _;
        stdin
            .write_all(raw.as_bytes())
            .map_err(|e| format!("failed to send yaml to python3: {e}"))?;
    }
    let out = child
        .wait_with_output()
        .map_err(|e| format!("failed to wait python3: {e}"))?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr).to_string();
        return Err(format!("yaml parse failed: {err}"));
    }
    let json_raw = String::from_utf8_lossy(&out.stdout).to_string();
    serde_json::from_str::<OntologyRegistryFile>(&json_raw)
        .map_err(|e| format!("invalid registry structure: {e}"))
}

fn arg_value(args: &[String], flag: &str) -> Option<String> {
    args.windows(2)
        .find_map(|w| (w[0] == flag).then(|| w[1].clone()))
}

fn parse_i64_csv(raw: &str) -> Vec<i64> {
    raw.split(',')
        .filter_map(|s| s.trim().parse::<i64>().ok())
        .filter(|v| *v > 0)
        .collect()
}

fn parse_text_csv(raw: &str) -> Vec<String> {
    raw.split(',')
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn parse_boolish(raw: &str) -> Option<bool> {
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Some(true),
        "0" | "false" | "no" | "off" => Some(false),
        _ => None,
    }
}

fn severity_rank(level: &str) -> i32 {
    match level {
        "critical" => 4,
        "high" => 3,
        "medium" => 2,
        "low" => 1,
        _ => 0,
    }
}

fn max_severity(a: &str, b: &str) -> String {
    if severity_rank(a) >= severity_rank(b) {
        a.to_string()
    } else {
        b.to_string()
    }
}

async fn resolve_persona_ref_for_stream(
    _database_url: &str,
    _stream_id: &str,
) -> Result<serde_json::Value, String> {
    Ok(json!({}))
}

async fn write_state_snapshot_row(
    pool: &sqlx::PgPool,
    intent: &str,
    stream_id: &str,
    persona_refs: serde_json::Value,
    trace: serde_json::Value,
) -> Result<String, sqlx::Error> {
    let now = time::OffsetDateTime::now_utc();
    let event_seq = now.unix_timestamp() * 1000 + i64::from(now.nanosecond() / 1_000_000);
    let case_key = format!("trace:{intent}:{stream_id}");
    let state_blob = json!({
        "intent": intent,
        "persona_refs": persona_refs,
        "trace": trace
    });
    let row = sqlx::query(
        r#"
        INSERT INTO state_snapshot (
          case_id, event_seq, projection_version, state_blob, state_hash
        )
        VALUES (
          (
            substr(md5($1), 1, 8) || '-' ||
            substr(md5($1), 9, 4) || '-4' ||
            substr(md5($1), 14, 3) || '-a' ||
            substr(md5($1), 18, 3) || '-' ||
            substr(md5($1), 21, 12)
          )::uuid,
          $2,
          'trace.v2',
          $3,
          NULL
        )
        ON CONFLICT (case_id, event_seq, projection_version) DO UPDATE SET
          state_blob = EXCLUDED.state_blob
        RETURNING snapshot_id::text AS snapshot_id
        "#,
    )
    .bind(case_key)
    .bind(event_seq)
    .bind(state_blob)
    .fetch_one(pool)
    .await?;
    row.try_get::<String, _>("snapshot_id")
}

async fn upsert_registry_predicate(
    tx: &mut sqlx::Transaction<'_, sqlx::Postgres>,
    registry_load_id: i64,
    defaults: &RegistryDefaults,
    p: &RegistryPredicate,
) -> Result<(), sqlx::Error> {
    let default_promotion = defaults.promotion.clone().unwrap_or_default();
    let default_evidence = defaults.evidence.clone().unwrap_or_default();
    let default_conflict = defaults.conflict.clone().unwrap_or_default();
    let promotion = p.promotion.clone().unwrap_or_default();
    let evidence = p.evidence.clone().unwrap_or_default();
    let conflict = p.conflict.clone().unwrap_or_default();

    let src_type_id = p
        .src_type_id
        .clone()
        .or_else(|| defaults.src_type_id.clone())
        .unwrap_or_else(|| "entity".to_string());
    let dst_type_id = p
        .dst_type_id
        .clone()
        .or_else(|| defaults.dst_type_id.clone())
        .unwrap_or_else(|| "entity".to_string());
    let enabled = p.enabled.or(defaults.enabled).unwrap_or(true);
    let display_name = p
        .display_name
        .clone()
        .unwrap_or_else(|| p.predicate.clone());
    let description = p.description.clone().unwrap_or_default();

    let auto_promote = pick_opt(
        &promotion.auto_promote,
        &default_promotion.auto_promote,
        false,
    );
    let min_confidence = promotion
        .min_confidence
        .or(default_promotion.min_confidence);
    let min_evidence_count = pick_opt(
        &promotion.min_evidence_count,
        &default_promotion.min_evidence_count,
        1,
    );
    let min_distinct_event_count = pick_opt(
        &promotion.min_distinct_event_count,
        &default_promotion.min_distinct_event_count,
        1,
    );
    let allow_cross_sentence = pick_opt(
        &promotion.allow_cross_sentence,
        &default_promotion.allow_cross_sentence,
        false,
    );

    let require_span_contract = pick_opt(
        &evidence.require_span_contract,
        &default_evidence.require_span_contract,
        true,
    );
    let require_located = pick_opt(
        &evidence.require_located,
        &default_evidence.require_located,
        true,
    );
    let min_overlap_chars = pick_opt(
        &evidence.min_overlap_chars,
        &default_evidence.min_overlap_chars,
        0,
    );
    let max_covered_sentence_count = pick_opt(
        &evidence.max_covered_sentence_count,
        &default_evidence.max_covered_sentence_count,
        999_999,
    );

    let conflict_key = pick_opt(
        &conflict.conflict_key,
        &default_conflict.conflict_key,
        "src_predicate".to_string(),
    );
    let conflict_policy = pick_opt(
        &conflict.conflict_policy,
        &default_conflict.conflict_policy,
        "block_promotion".to_string(),
    );
    let conflict_create_case = pick_opt(&conflict.create_case, &default_conflict.create_case, true);
    let conflict_case_priority = pick_opt(
        &conflict.case_priority,
        &default_conflict.case_priority,
        "p2".to_string(),
    );
    let conflict_alert_severity = pick_opt(
        &conflict.alert_severity,
        &default_conflict.alert_severity,
        "medium".to_string(),
    );

    sqlx::query(
        r#"
        INSERT INTO ontology_relation_type (
          predicate, src_type_id, dst_type_id, display_name, description,
          registry_load_id, managed_by_registry,
          enabled,
          min_confidence, auto_promote, min_evidence_count, min_distinct_event_count, allow_cross_sentence,
          require_span_contract, require_located, min_overlap_chars, max_covered_sentence_count,
          conflict_key, conflict_policy, conflict_create_case, conflict_case_priority, conflict_alert_severity
        )
        VALUES (
          $1, $2, $3, $4, $5,
          $6, $7,
          $8,
          $9, $10, $11, $12, $13,
          $14, $15, $16, $17,
          $18, $19, $20, $21, $22
        )
        ON CONFLICT (predicate) DO UPDATE SET
          src_type_id = EXCLUDED.src_type_id,
          dst_type_id = EXCLUDED.dst_type_id,
          display_name = EXCLUDED.display_name,
          description = EXCLUDED.description,
          registry_load_id = EXCLUDED.registry_load_id,
          managed_by_registry = EXCLUDED.managed_by_registry,
          enabled = EXCLUDED.enabled,
          min_confidence = EXCLUDED.min_confidence,
          auto_promote = EXCLUDED.auto_promote,
          min_evidence_count = EXCLUDED.min_evidence_count,
          min_distinct_event_count = EXCLUDED.min_distinct_event_count,
          allow_cross_sentence = EXCLUDED.allow_cross_sentence,
          require_span_contract = EXCLUDED.require_span_contract,
          require_located = EXCLUDED.require_located,
          min_overlap_chars = EXCLUDED.min_overlap_chars,
          max_covered_sentence_count = EXCLUDED.max_covered_sentence_count,
          conflict_key = EXCLUDED.conflict_key,
          conflict_policy = EXCLUDED.conflict_policy,
          conflict_create_case = EXCLUDED.conflict_create_case,
          conflict_case_priority = EXCLUDED.conflict_case_priority,
          conflict_alert_severity = EXCLUDED.conflict_alert_severity,
          updated_at = NOW()
        "#,
    )
    .bind(&p.predicate)
    .bind(src_type_id)
    .bind(dst_type_id)
    .bind(display_name)
    .bind(description)
    .bind(registry_load_id)
    .bind(true)
    .bind(enabled)
    .bind(min_confidence)
    .bind(auto_promote)
    .bind(min_evidence_count)
    .bind(min_distinct_event_count)
    .bind(allow_cross_sentence)
    .bind(require_span_contract)
    .bind(require_located)
    .bind(min_overlap_chars)
    .bind(max_covered_sentence_count)
    .bind(conflict_key)
    .bind(conflict_policy)
    .bind(conflict_create_case)
    .bind(conflict_case_priority)
    .bind(conflict_alert_severity)
    .execute(&mut **tx)
    .await?;
    Ok(())
}

async fn ensure_schema_relations(
    pool: &sqlx::PgPool,
    required_relations: &[&str],
    label: &str,
    hint: &str,
) -> Result<(), sqlx::Error> {
    let mut missing: Vec<&str> = Vec::new();

    for relation in required_relations {
        let row = sqlx::query("SELECT to_regclass($1)::text AS relation_name")
            .bind(relation)
            .fetch_one(pool)
            .await?;
        let relation_name = row.try_get::<Option<String>, _>("relation_name")?;
        if relation_name.is_none() {
            missing.push(relation);
        }
    }

    if missing.is_empty() {
        return Ok(());
    }

    Err(sqlx::Error::Protocol(format!(
        "missing required {label}: {}. {hint}",
        missing.join(", "),
    )))
}

async fn ensure_ontology_extension_schema(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    ensure_schema_relations(
        pool,
        &[
            "public.ontology_concept",
            "public.ontology_edge",
            "public.event_concept_link",
            "public.concept_alias",
            "public.ontology_object_type",
            "public.ontology_relation_type",
            "public.ontology_fact",
            "public.ontology_fact_evidence",
            "public.ontology_fact_review",
            "public.ontology_registry_load",
        ],
        "ontology extension schema objects",
        "Apply db/migrations_v2 with the full migration profile; bridge no longer performs runtime DDL.",
    )
    .await
}

async fn ensure_ontology_ops_schema(pool: &sqlx::PgPool) -> Result<(), sqlx::Error> {
    ensure_ontology_extension_schema(pool).await?;
    ensure_schema_relations(
        pool,
        &[
            "public.ontology_case",
            "public.ontology_case_fact",
            "public.ontology_case_decision",
            "public.ontology_case_event",
            "public.ontology_alert",
            "public.ontology_alert_fact",
            "public.ontology_ops_rule_config",
            "public.ontology_ops_rule_run",
        ],
        "ontology ops schema objects",
        "Apply db/migrations_v2 with the full migration profile; bridge no longer performs runtime DDL.",
    )
    .await
}

#[tokio::main]
async fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("{}", usage());
        std::process::exit(2);
    }
    if let Some(log_file) = arg_value(&args, "--log-file") {
        if !log_file.trim().is_empty() {
            // Set once at startup before any worker threads are spawned.
            unsafe { env::set_var("TDB_BRIDGE_LOG_FILE", log_file) };
        }
    }

    match args[1].as_str() {
        "segment_event_sentences" => {
            let stream_id = arg_value(&args, "--stream-id");
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .filter(|v| *v > 0);
            let seg_version =
                arg_value(&args, "--seg-version").unwrap_or_else(|| "v2_rule_zh_punct".to_string());

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let store = match EventSentenceStore::new(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            let started_at = Instant::now();
            let stats = match store
                .segment_events(stream_id.as_deref(), limit, &seg_version)
                .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("sentence segmentation failed: {e}");
                    std::process::exit(1);
                }
            };
            log_info(&format!(
                "segment_event_sentences_done stream_id={} scanned={} updated_events={} inserted_sentences={} deleted_sentences={} skipped_empty_text={} elapsed_ms={} seg_version={}",
                stream_id.clone().unwrap_or_else(|| "*".to_string()),
                stats.scanned,
                stats.updated_events,
                stats.inserted_sentences,
                stats.deleted_sentences,
                stats.skipped_empty_text,
                started_at.elapsed().as_millis(),
                seg_version
            ));
            let payload = json!({
                "stream_id": stream_id,
                "limit": limit,
                "seg_version": seg_version,
                "stats": stats,
                "elapsed_ms": started_at.elapsed().as_millis()
            });
            println!("{payload}");
        }
        "locate_event_span" => {
            let stream_id = match arg_value(&args, "--stream-id") {
                Some(v) => v,
                None => {
                    eprintln!("--stream-id is required");
                    std::process::exit(2);
                }
            };
            let event_id = match arg_value(&args, "--event-id") {
                Some(v) => v,
                None => {
                    eprintln!("--event-id is required");
                    std::process::exit(2);
                }
            };
            let start_char =
                match arg_value(&args, "--start-char").and_then(|v| v.parse::<i32>().ok()) {
                    Some(v) if v >= 0 => v,
                    _ => {
                        eprintln!("--start-char must be a non-negative integer");
                        std::process::exit(2);
                    }
                };
            let end_char = match arg_value(&args, "--end-char").and_then(|v| v.parse::<i32>().ok())
            {
                Some(v) if v > start_char => v,
                _ => {
                    eprintln!("--end-char must be an integer greater than --start-char");
                    std::process::exit(2);
                }
            };
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let store = match EventSentenceStore::new(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            let rows = match store
                .locate_span(&stream_id, &event_id, start_char, end_char)
                .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("locate span failed: {e}");
                    std::process::exit(1);
                }
            };
            let payload = json!({
                "stream_id": stream_id,
                "event_id": event_id,
                "start_char": start_char,
                "end_char": end_char,
                "sentences": rows
            });
            println!("{payload}");
        }
        "ontology_governance_report" => {
            let stream_id_filter = arg_value(&args, "--stream-id");
            let review_limit = arg_value(&args, "--review-limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(50)
                .clamp(1, 1000);
            let stale_days = arg_value(&args, "--stale-days")
                .and_then(|v| v.parse::<i64>().ok())
                .unwrap_or(7)
                .max(1);

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }

            let status_rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT f.status, COUNT(DISTINCT f.fact_id)::BIGINT AS c
                    FROM ontology_fact f
                    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                    WHERE fe.stream_id = $1
                    GROUP BY f.status
                    ORDER BY c DESC, f.status ASC
                    "#,
                )
                .bind(stream_id)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT status, COUNT(*)::BIGINT AS c
                    FROM ontology_fact
                    GROUP BY status
                    ORDER BY c DESC, status ASC
                    "#,
                )
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let predicate_rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT f.predicate, COUNT(DISTINCT f.fact_id)::BIGINT AS c
                    FROM ontology_fact f
                    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                    WHERE fe.stream_id = $1
                    GROUP BY f.predicate
                    ORDER BY c DESC, f.predicate ASC
                    "#,
                )
                .bind(stream_id)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT predicate, COUNT(*)::BIGINT AS c
                    FROM ontology_fact
                    GROUP BY predicate
                    ORDER BY c DESC, predicate ASC
                    "#,
                )
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let extractor_rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT f.extractor, COUNT(DISTINCT f.fact_id)::BIGINT AS c
                    FROM ontology_fact f
                    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                    WHERE fe.stream_id = $1
                    GROUP BY f.extractor
                    ORDER BY c DESC, f.extractor ASC
                    "#,
                )
                .bind(stream_id)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT extractor, COUNT(*)::BIGINT AS c
                    FROM ontology_fact
                    GROUP BY extractor
                    ORDER BY c DESC, extractor ASC
                    "#,
                )
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let recent_reviews = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT
                      r.review_id,
                      r.fact_id,
                      r.reviewer,
                      r.decision,
                      r.note,
                      r.created_at
                    FROM ontology_fact_review r
                    WHERE EXISTS (
                      SELECT 1
                      FROM ontology_fact_evidence fe
                      WHERE fe.fact_id = r.fact_id
                        AND fe.stream_id = $1
                    )
                    ORDER BY r.created_at DESC
                    LIMIT $2
                    "#,
                )
                .bind(stream_id)
                .bind(review_limit as i64)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT review_id, fact_id, reviewer, decision, note, created_at
                    FROM ontology_fact_review
                    ORDER BY created_at DESC
                    LIMIT $1
                    "#,
                )
                .bind(review_limit as i64)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let stale_rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT COUNT(DISTINCT f.fact_id)::BIGINT AS c
                    FROM ontology_fact f
                    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                    WHERE fe.stream_id = $1
                      AND f.status IN ('candidate', 'needs_review')
                      AND f.updated_at < (NOW() - make_interval(days => $2::int))
                    "#,
                )
                .bind(stream_id)
                .bind(stale_days as i32)
                .fetch_one(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT COUNT(*)::BIGINT AS c
                    FROM ontology_fact
                    WHERE status IN ('candidate', 'needs_review')
                      AND updated_at < (NOW() - make_interval(days => $1::int))
                    "#,
                )
                .bind(stale_days as i32)
                .fetch_one(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let review_decision_rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT r.decision, COUNT(*)::BIGINT AS c
                    FROM ontology_fact_review r
                    WHERE EXISTS (
                      SELECT 1
                      FROM ontology_fact_evidence fe
                      WHERE fe.fact_id = r.fact_id
                        AND fe.stream_id = $1
                    )
                    GROUP BY r.decision
                    ORDER BY c DESC, r.decision ASC
                    "#,
                )
                .bind(stream_id)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT decision, COUNT(*)::BIGINT AS c
                    FROM ontology_fact_review
                    GROUP BY decision
                    ORDER BY c DESC, decision ASC
                    "#,
                )
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let status_counts: Vec<serde_json::Value> = status_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "status": r.try_get::<String, _>("status").unwrap_or_default(),
                        "count": r.try_get::<i64, _>("c").unwrap_or(0),
                    })
                })
                .collect();
            let predicate_counts: Vec<serde_json::Value> = predicate_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "predicate": r.try_get::<String, _>("predicate").unwrap_or_default(),
                        "count": r.try_get::<i64, _>("c").unwrap_or(0),
                    })
                })
                .collect();
            let extractor_counts: Vec<serde_json::Value> = extractor_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "extractor": r.try_get::<String, _>("extractor").unwrap_or_default(),
                        "count": r.try_get::<i64, _>("c").unwrap_or(0),
                    })
                })
                .collect();
            let reviews: Vec<serde_json::Value> = recent_reviews
                .into_iter()
                .map(|r| {
                    json!({
                        "review_id": r.try_get::<i64, _>("review_id").unwrap_or(0),
                        "fact_id": r.try_get::<i64, _>("fact_id").unwrap_or(0),
                        "reviewer": r.try_get::<String, _>("reviewer").unwrap_or_default(),
                        "decision": r.try_get::<String, _>("decision").unwrap_or_default(),
                        "note": r.try_get::<String, _>("note").unwrap_or_default(),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();
            let review_decision_counts: Vec<serde_json::Value> = review_decision_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "decision": r.try_get::<String, _>("decision").unwrap_or_default(),
                        "count": r.try_get::<i64, _>("c").unwrap_or(0),
                    })
                })
                .collect();
            let total_facts: i64 = status_counts
                .iter()
                .map(|x| x.get("count").and_then(|v| v.as_i64()).unwrap_or(0))
                .sum();
            let stale_pending_count = stale_rows.try_get::<i64, _>("c").unwrap_or(0);

            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "status_counts": status_counts,
                "predicate_counts": predicate_counts,
                "extractor_counts": extractor_counts,
                "review_decision_counts": review_decision_counts,
                "recent_reviews": reviews,
                "review_limit": review_limit,
                "stale_days": stale_days,
                "total_facts": total_facts,
                "stale_pending_count": stale_pending_count,
            });
            println!("{payload}");
        }
        "list_ontology_facts" => {
            let status = arg_value(&args, "--status")
                .unwrap_or_else(|| "candidate".to_string())
                .to_lowercase();
            let stream_id_filter = arg_value(&args, "--stream-id");
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(50)
                .clamp(1, 500);

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };

            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let ontology = OntologyRpcStore::new(pool.clone());
            let listed = match ontology
                .list_facts(ListOntologyFactsRequest {
                    status: status.clone(),
                    stream_id: stream_id_filter.clone().unwrap_or_default(),
                    predicate: String::new(),
                    extractor: String::new(),
                    limit: limit as i32,
                    offset: 0,
                    src_concept_id: String::new(),
                    dst_concept_id: String::new(),
                    stream_prefix: false,
                })
                .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };

            let facts: Vec<serde_json::Value> = listed
                .facts
                .into_iter()
                .map(|fact| {
                    json!({
                        "fact_id": fact.fact_id,
                        "src_concept_id": fact.src_concept_id,
                        "predicate": fact.predicate,
                        "dst_concept_id": fact.dst_concept_id,
                        "confidence": fact.confidence,
                        "status": fact.status,
                        "extractor": fact.extractor,
                        "review_note": fact.review_note,
                        "updated_at": fact.updated_at,
                        "evidence_count": serde_json::Value::Null,
                        "latest_event_id": serde_json::Value::Null,
                    })
                })
                .collect();

            let payload = json!({
                "status_filter": status,
                "stream_id_filter": stream_id_filter,
                "limit": limit,
                "facts": facts,
            });
            println!("{payload}");
        }
        "review_ontology_fact" => {
            let fact_id = match arg_value(&args, "--fact-id").and_then(|v| v.parse::<i64>().ok()) {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--fact-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let decision = match arg_value(&args, "--decision") {
                Some(v) => v.to_lowercase(),
                None => {
                    eprintln!("--decision is required: accept|reject|needs_work");
                    std::process::exit(2);
                }
            };
            if decision != "accept" && decision != "reject" && decision != "needs_work" {
                eprintln!("--decision must be one of: accept|reject|needs_work");
                std::process::exit(2);
            }
            let reviewer = arg_value(&args, "--reviewer")
                .or_else(|| env::var("USER").ok())
                .unwrap_or_else(|| "system".to_string());
            let note = arg_value(&args, "--note").unwrap_or_default();

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let store = match OntologyStore::new(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("ontology store init failed: {e}");
                    std::process::exit(1);
                }
            };

            let updated = match store
                .review_fact(
                    fact_id,
                    &OntologyFactReviewInput {
                        reviewer: reviewer.clone(),
                        decision: decision.clone(),
                        note: note.clone(),
                    },
                )
                .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("review fact failed: {e}");
                    std::process::exit(1);
                }
            };
            let payload = json!({
                "fact_id": fact_id,
                "decision": decision,
                "reviewer": reviewer,
                "note": note,
                "updated_rows": updated,
            });
            println!("{payload}");
        }
        "review_ontology_facts_bulk" => {
            let decision = match arg_value(&args, "--decision") {
                Some(v) => v.to_lowercase(),
                None => {
                    eprintln!("--decision is required: accept|reject|needs_work");
                    std::process::exit(2);
                }
            };
            if decision != "accept" && decision != "reject" && decision != "needs_work" {
                eprintln!("--decision must be one of: accept|reject|needs_work");
                std::process::exit(2);
            }
            let status = arg_value(&args, "--status")
                .unwrap_or_else(|| "candidate".to_string())
                .to_lowercase();
            let stream_id_filter = arg_value(&args, "--stream-id");
            let predicate_filter = arg_value(&args, "--predicate").and_then(|v| {
                let t = v.trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t.to_string())
                }
            });
            let extractor_filter = arg_value(&args, "--extractor").and_then(|v| {
                let t = v.trim();
                if t.is_empty() {
                    None
                } else {
                    Some(t.to_string())
                }
            });
            let stale_days_filter = arg_value(&args, "--stale-days")
                .and_then(|v| v.parse::<i64>().ok())
                .filter(|v| *v > 0);
            let min_conf = arg_value(&args, "--min-confidence")
                .and_then(|v| v.parse::<f64>().ok())
                .unwrap_or(0.0)
                .clamp(0.0, 1.0);
            let max_conf = arg_value(&args, "--max-confidence")
                .and_then(|v| v.parse::<f64>().ok())
                .unwrap_or(1.0)
                .clamp(0.0, 1.0);
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(100)
                .clamp(1, 5000);
            let reviewer = arg_value(&args, "--reviewer")
                .or_else(|| env::var("USER").ok())
                .unwrap_or_else(|| "system".to_string());
            let note = arg_value(&args, "--note").unwrap_or_default();
            let dry_run = args.iter().any(|a| a == "--dry-run");

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let store = match OntologyStore::new(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("ontology store init failed: {e}");
                    std::process::exit(1);
                }
            };

            let rows = if let Some(stream_id) = stream_id_filter.clone() {
                match sqlx::query(
                    r#"
                    SELECT
                      f.fact_id,
                      f.status,
                      f.confidence,
                      MAX(f.updated_at) AS last_updated_at
                    FROM ontology_fact f
                    JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                    WHERE ($1::text = 'all' OR f.status = $1)
                      AND fe.stream_id = $2
                      AND ($3::text IS NULL OR f.predicate = $3)
                      AND ($4::text IS NULL OR f.extractor = $4)
                      AND ($5::int IS NULL OR f.updated_at < (NOW() - make_interval(days => $5::int)))
                      AND f.confidence >= $6
                      AND f.confidence <= $7
                    GROUP BY f.fact_id, f.status, f.confidence
                    ORDER BY f.confidence DESC, last_updated_at DESC
                    LIMIT $8
                    "#,
                )
                .bind(&status)
                .bind(&stream_id)
                .bind(predicate_filter.as_deref())
                .bind(extractor_filter.as_deref())
                .bind(stale_days_filter.map(|v| v as i32))
                .bind(min_conf)
                .bind(max_conf)
                .bind(limit as i64)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    SELECT f.fact_id, f.status, f.confidence
                    FROM ontology_fact f
                    WHERE ($1::text = 'all' OR f.status = $1)
                      AND ($2::text IS NULL OR f.predicate = $2)
                      AND ($3::text IS NULL OR f.extractor = $3)
                      AND ($4::int IS NULL OR f.updated_at < (NOW() - make_interval(days => $4::int)))
                      AND f.confidence >= $5
                      AND f.confidence <= $6
                    ORDER BY f.confidence DESC, f.updated_at DESC
                    LIMIT $7
                    "#,
                )
                .bind(&status)
                .bind(predicate_filter.as_deref())
                .bind(extractor_filter.as_deref())
                .bind(stale_days_filter.map(|v| v as i32))
                .bind(min_conf)
                .bind(max_conf)
                .bind(limit as i64)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let selected: Vec<serde_json::Value> = rows
                .iter()
                .map(|row| {
                    json!({
                        "fact_id": row.try_get::<i64, _>("fact_id").unwrap_or(0),
                        "status": row.try_get::<String, _>("status").unwrap_or_default(),
                        "confidence": row.try_get::<f64, _>("confidence").unwrap_or(0.0),
                    })
                })
                .collect();

            let mut updated = 0u64;
            if !dry_run {
                for row in &rows {
                    let fact_id = row.try_get::<i64, _>("fact_id").unwrap_or(0);
                    if fact_id <= 0 {
                        continue;
                    }
                    match store
                        .review_fact(
                            fact_id,
                            &OntologyFactReviewInput {
                                reviewer: reviewer.clone(),
                                decision: decision.clone(),
                                note: note.clone(),
                            },
                        )
                        .await
                    {
                        Ok(v) => updated += v,
                        Err(e) => {
                            eprintln!("bulk review failed on fact_id={fact_id}: {e}");
                            std::process::exit(1);
                        }
                    }
                }
            }

            let payload = json!({
                "decision": decision,
                "status_filter": status,
                "stream_id_filter": stream_id_filter,
                "predicate_filter": predicate_filter,
                "extractor_filter": extractor_filter,
                "stale_days_filter": stale_days_filter,
                "min_confidence": min_conf,
                "max_confidence": max_conf,
                "limit": limit,
                "dry_run": dry_run,
                "reviewer": reviewer,
                "note": note,
                "selected_count": selected.len(),
                "updated_rows": updated,
                "selected_facts": selected,
            });
            println!("{payload}");
        }
        "backfill_semantic_kernel_legacy_ontology" => {
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let store = match OntologyStore::new(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("ontology store init failed: {e}");
                    std::process::exit(1);
                }
            };

            let fact_id = arg_value(&args, "--fact-id").and_then(|value| value.parse::<i64>().ok());
            let fact_ids_csv = arg_value(&args, "--fact-ids");
            let parsed_fact_ids: Vec<i64> = fact_ids_csv
                .as_deref()
                .map(|csv| {
                    csv.split(',')
                        .filter_map(|value| value.trim().parse::<i64>().ok())
                        .filter(|value| *value > 0)
                        .collect()
                })
                .unwrap_or_default();
            let limit = arg_value(&args, "--limit")
                .and_then(|value| value.parse::<usize>().ok())
                .filter(|value| *value > 0);

            let report = if let Some(single_fact_id) = fact_id.filter(|value| *value > 0) {
                match store
                    .backfill_semantic_kernel_for_legacy_fact_ids(&[single_fact_id])
                    .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("semantic kernel fact backfill failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else if !parsed_fact_ids.is_empty() {
                match store
                    .backfill_semantic_kernel_for_legacy_fact_ids(&parsed_fact_ids)
                    .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("semantic kernel fact backfill failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match store.backfill_semantic_kernel_from_legacy_ontology(limit).await {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("semantic kernel legacy backfill failed: {e}");
                        std::process::exit(1);
                    }
                }
            };

            let payload = json!({
                "fact_id": fact_id,
                "fact_ids": parsed_fact_ids,
                "limit": limit,
                "concepts_synced": report.concepts_synced,
                "aliases_synced": report.aliases_synced,
                "facts_synced": report.facts_synced,
            });
            println!("{payload}");
        }
        "fact_history" => {
            let fact_id = match arg_value(&args, "--fact-id").and_then(|v| v.parse::<i64>().ok()) {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--fact-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let evidence_limit = arg_value(&args, "--evidence-limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(200)
                .clamp(1, 2000);
            let stream_id_filter = arg_value(&args, "--stream-id");

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let payload = match load_fact_history_payload(
                &pool,
                fact_id,
                stream_id_filter.as_deref(),
                evidence_limit,
            )
            .await
            {
                Ok(Some(v)) => v,
                Ok(None) => {
                    eprintln!("fact not found: {fact_id}");
                    std::process::exit(1);
                }
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            println!("{payload}");
        }
        "open_ontology_case" => {
            let stream_id = match arg_value(&args, "--stream-id") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--stream-id is required");
                    std::process::exit(2);
                }
            };
            let title = match arg_value(&args, "--title") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--title is required");
                    std::process::exit(2);
                }
            };
            let description = arg_value(&args, "--description").unwrap_or_default();
            let priority = arg_value(&args, "--priority")
                .unwrap_or_else(|| "p2".to_string())
                .to_lowercase();
            if !matches!(priority.as_str(), "p1" | "p2" | "p3") {
                eprintln!("--priority must be p1|p2|p3");
                std::process::exit(2);
            }
            let owner = arg_value(&args, "--owner").unwrap_or_default();
            let note = arg_value(&args, "--note").unwrap_or_default();
            let created_by = env::var("USER").unwrap_or_else(|_| "system".to_string());
            let mut fact_ids: Vec<i64> = vec![];
            if let Some(v) = arg_value(&args, "--fact-id").and_then(|x| x.parse::<i64>().ok()) {
                if v > 0 {
                    fact_ids.push(v);
                }
            }
            if let Some(v) = arg_value(&args, "--fact-ids") {
                fact_ids.extend(parse_i64_csv(&v));
            }
            fact_ids.sort_unstable();
            fact_ids.dedup();

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }

            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let case_row = match sqlx::query(
                r#"
                INSERT INTO ontology_case (
                  stream_id, title, description, status, priority, owner, created_by
                )
                VALUES ($1, $2, $3, 'open', $4, $5, $6)
                RETURNING case_id, stream_id, title, description, status, priority, owner, created_by, created_at, updated_at
                "#,
            )
            .bind(&stream_id)
            .bind(title.trim())
            .bind(description.trim())
            .bind(&priority)
            .bind(owner.trim())
            .bind(created_by.trim())
            .fetch_one(&mut *tx)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("open case failed: {e}");
                    std::process::exit(1);
                }
            };
            let case_id = case_row.try_get::<i64, _>("case_id").unwrap_or(0);

            let _ = sqlx::query(
                r#"
                INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                VALUES ($1, 'open', $2, $3, $4)
                "#,
            )
            .bind(case_id)
            .bind(created_by.trim())
            .bind(note.trim())
            .bind(json!({
              "title": title.trim(),
              "priority": priority,
              "owner": owner.trim(),
            }))
            .execute(&mut *tx)
            .await;

            let mut linked_fact_ids: Vec<i64> = vec![];
            let mut skipped_fact_ids: Vec<i64> = vec![];
            for fact_id in &fact_ids {
                let inserted = match sqlx::query(
                    r#"
                    INSERT INTO ontology_case_fact (case_id, fact_id, added_by, added_note)
                    SELECT $1, $2, $3, $4
                    WHERE EXISTS (SELECT 1 FROM ontology_fact f WHERE f.fact_id = $2)
                      AND EXISTS (
                        SELECT 1
                        FROM ontology_fact_evidence fe
                        WHERE fe.fact_id = $2
                          AND fe.stream_id = $5
                      )
                    ON CONFLICT (case_id, fact_id) DO NOTHING
                    "#,
                )
                .bind(case_id)
                .bind(*fact_id)
                .bind(created_by.trim())
                .bind(note.trim())
                .bind(&stream_id)
                .execute(&mut *tx)
                .await
                {
                    Ok(v) => v.rows_affected(),
                    Err(e) => {
                        eprintln!("link fact failed fact_id={fact_id}: {e}");
                        std::process::exit(1);
                    }
                };
                if inserted > 0 {
                    linked_fact_ids.push(*fact_id);
                    let _ = sqlx::query(
                        r#"
                        INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                        VALUES ($1, 'fact_link', $2, $3, $4)
                        "#,
                    )
                    .bind(case_id)
                    .bind(created_by.trim())
                    .bind(note.trim())
                    .bind(json!({ "fact_id": fact_id }))
                    .execute(&mut *tx)
                    .await;
                } else {
                    skipped_fact_ids.push(*fact_id);
                }
            }

            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }

            let payload = json!({
                "case_id": case_id,
                "stream_id": case_row.try_get::<String, _>("stream_id").unwrap_or_default(),
                "title": case_row.try_get::<String, _>("title").unwrap_or_default(),
                "description": case_row.try_get::<String, _>("description").unwrap_or_default(),
                "status": case_row.try_get::<String, _>("status").unwrap_or_default(),
                "priority": case_row.try_get::<String, _>("priority").unwrap_or_default(),
                "owner": case_row.try_get::<String, _>("owner").unwrap_or_default(),
                "created_by": case_row.try_get::<String, _>("created_by").unwrap_or_default(),
                "created_at": case_row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                "updated_at": case_row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                "linked_fact_ids": linked_fact_ids,
                "skipped_fact_ids": skipped_fact_ids,
            });
            println!("{payload}");
        }
        "list_ontology_cases" => {
            let stream_id_filter = arg_value(&args, "--stream-id");
            let status = arg_value(&args, "--status")
                .unwrap_or_else(|| "open".to_string())
                .to_lowercase();
            if !matches!(
                status.as_str(),
                "open" | "in_review" | "resolved" | "dismissed" | "all"
            ) {
                eprintln!("--status must be open|in_review|resolved|dismissed|all");
                std::process::exit(2);
            }
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(100)
                .clamp(1, 1000);
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let rows = match sqlx::query(
                r#"
                SELECT
                  c.case_id,
                  c.stream_id,
                  c.title,
                  c.description,
                  c.status,
                  c.priority,
                  c.owner,
                  c.created_by,
                  c.created_at,
                  c.updated_at,
                  c.closed_at,
                  (SELECT COUNT(*)::BIGINT FROM ontology_case_fact cf WHERE cf.case_id = c.case_id) AS fact_count,
                  (SELECT COUNT(*)::BIGINT FROM ontology_alert a WHERE a.case_id = c.case_id AND a.status <> 'closed') AS active_alert_count
                FROM ontology_case c
                WHERE ($1::text IS NULL OR c.stream_id = $1)
                  AND ($2::text = 'all' OR c.status = $2)
                ORDER BY c.updated_at DESC
                LIMIT $3
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .bind(&status)
            .bind(limit as i64)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let cases: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|r| {
                    json!({
                        "case_id": r.try_get::<i64, _>("case_id").unwrap_or(0),
                        "stream_id": r.try_get::<String, _>("stream_id").unwrap_or_default(),
                        "title": r.try_get::<String, _>("title").unwrap_or_default(),
                        "description": r.try_get::<String, _>("description").unwrap_or_default(),
                        "status": r.try_get::<String, _>("status").unwrap_or_default(),
                        "priority": r.try_get::<String, _>("priority").unwrap_or_default(),
                        "owner": r.try_get::<String, _>("owner").unwrap_or_default(),
                        "created_by": r.try_get::<String, _>("created_by").unwrap_or_default(),
                        "fact_count": r.try_get::<i64, _>("fact_count").unwrap_or(0),
                        "active_alert_count": r.try_get::<i64, _>("active_alert_count").unwrap_or(0),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                        "updated_at": r.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                        "closed_at": r.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
                    })
                })
                .collect();
            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "status_filter": status,
                "limit": limit,
                "count": cases.len(),
                "cases": cases,
            });
            println!("{payload}");
        }
        "record_ontology_case_decision" => {
            let case_id = match arg_value(&args, "--case-id").and_then(|v| v.parse::<i64>().ok()) {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--case-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let decision_kind = match arg_value(&args, "--decision-kind") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--decision-kind is required");
                    std::process::exit(2);
                }
            };
            let verdict = match arg_value(&args, "--verdict") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--verdict is required");
                    std::process::exit(2);
                }
            };
            let summary = match arg_value(&args, "--summary") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--summary is required");
                    std::process::exit(2);
                }
            };
            let rationale = arg_value(&args, "--rationale").unwrap_or_default();
            let as_of_system_time = match arg_value(&args, "--as-of-system-time") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--as-of-system-time is required");
                    std::process::exit(2);
                }
            };
            let as_of_effective_time = arg_value(&args, "--as-of-effective-time")
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| as_of_system_time.clone());
            let snapshot_id = arg_value(&args, "--snapshot-id").unwrap_or_default();
            let source_evidence_json =
                arg_value(&args, "--source-evidence-json").unwrap_or_else(|| "[]".to_string());
            let supersedes_case_decision_id = arg_value(&args, "--supersedes-case-decision-id")
                .and_then(|v| v.parse::<i64>().ok())
                .unwrap_or(0);
            let created_by = arg_value(&args, "--created-by")
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| env::var("USER").unwrap_or_else(|_| "system".to_string()));

            if serde_json::from_str::<serde_json::Value>(&source_evidence_json).is_err() {
                eprintln!("--source-evidence-json must be valid JSON");
                std::process::exit(2);
            }

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }

            let row = match sqlx::query(
                r#"
                INSERT INTO ontology_case_decision (
                  case_id,
                  decision_kind,
                  verdict,
                  summary,
                  rationale,
                  as_of_system_time,
                  as_of_effective_time,
                  snapshot_id,
                  source_evidence_json,
                  supersedes_case_decision_id,
                  created_by
                )
                VALUES (
                  $1, $2, $3, $4, $5,
                  $6::timestamptz, $7::timestamptz, $8, $9::jsonb, $10, $11
                )
                RETURNING
                  case_decision_id,
                  case_id,
                  decision_kind,
                  verdict,
                  summary,
                  rationale,
                  as_of_system_time,
                  as_of_effective_time,
                  snapshot_id,
                  source_evidence_json,
                  supersedes_case_decision_id,
                  created_by,
                  created_at
                "#,
            )
            .bind(case_id)
            .bind(decision_kind.trim())
            .bind(verdict.trim())
            .bind(summary.trim())
            .bind(rationale.trim())
            .bind(&as_of_system_time)
            .bind(&as_of_effective_time)
            .bind(snapshot_id.trim())
            .bind(&source_evidence_json)
            .bind(if supersedes_case_decision_id > 0 {
                Some(supersedes_case_decision_id)
            } else {
                None
            })
            .bind(created_by.trim())
            .fetch_one(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("insert case decision failed: {e}");
                    std::process::exit(1);
                }
            };

            let payload = json!({
                "case_decision_id": row.try_get::<i64, _>("case_decision_id").unwrap_or(0),
                "case_id": row.try_get::<i64, _>("case_id").unwrap_or(0),
                "decision_kind": row.try_get::<String, _>("decision_kind").unwrap_or_default(),
                "verdict": row.try_get::<String, _>("verdict").unwrap_or_default(),
                "summary": row.try_get::<String, _>("summary").unwrap_or_default(),
                "rationale": row.try_get::<String, _>("rationale").unwrap_or_default(),
                "as_of_system_time": row.try_get::<time::OffsetDateTime, _>("as_of_system_time").map(|t| t.to_string()).unwrap_or_default(),
                "as_of_effective_time": row.try_get::<time::OffsetDateTime, _>("as_of_effective_time").map(|t| t.to_string()).unwrap_or_default(),
                "snapshot_id": row.try_get::<String, _>("snapshot_id").unwrap_or_default(),
                "source_evidence_json": row.try_get::<serde_json::Value, _>("source_evidence_json").unwrap_or(json!([])),
                "supersedes_case_decision_id": row.try_get::<Option<i64>, _>("supersedes_case_decision_id").ok().flatten(),
                "created_by": row.try_get::<String, _>("created_by").unwrap_or_default(),
                "created_at": row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
            });
            println!("{payload}");
        }
        "case_detail" => {
            let case_id = match arg_value(&args, "--case-id").and_then(|v| v.parse::<i64>().ok()) {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--case-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let evidence_limit = arg_value(&args, "--evidence-limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(50)
                .clamp(1, 500);
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let case_row = match sqlx::query(
                r#"
                SELECT
                  case_id, stream_id, title, description, status, priority, owner, created_by, created_at, updated_at, closed_at
                FROM ontology_case
                WHERE case_id = $1
                "#,
            )
            .bind(case_id)
            .fetch_optional(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let Some(case_row) = case_row else {
                eprintln!("case not found: {case_id}");
                std::process::exit(1);
            };

            let facts_rows = match sqlx::query(
                r#"
                SELECT
                  f.fact_id,
                  f.src_concept_id,
                  f.predicate,
                  f.dst_concept_id,
                  f.confidence,
                  f.status,
                  f.extractor,
                  f.updated_at,
                  cf.created_at AS linked_at,
                  cf.added_by,
                  cf.added_note,
                  (
                    SELECT COUNT(*)::BIGINT
                    FROM ontology_fact_evidence fe
                    WHERE fe.fact_id = f.fact_id
                  ) AS evidence_count,
                  (
                    SELECT COALESCE(json_agg(
                      json_build_object(
                        'stream_id', x.stream_id,
                        'event_id', x.event_id,
                        'session_id', x.session_id,
                        'updated_at', x.updated_at::text,
                        'source_span', x.source_span,
                        'text_snippet', x.text_snippet
                      )
                      ORDER BY x.updated_at DESC
                    ), '[]'::json)
                    FROM (
                      SELECT
                        fe.stream_id,
                        fe.event_id,
                        COALESCE(
                          cel.payload->>'session_id',
                          cel.payload->>'sessionId',
                          ''
                        ) AS session_id,
                        fe.updated_at,
                        fe.source_span,
                        LEFT(COALESCE(cel.payload->>'text', ''), 280) AS text_snippet
                      FROM ontology_fact_evidence fe
                      LEFT JOIN case_event_ledger cel
                        ON cel.event_id::text = fe.event_id
                      WHERE fe.fact_id = f.fact_id
                      ORDER BY fe.updated_at DESC
                      LIMIT $2
                    ) x
                  ) AS evidence_sample
                FROM ontology_case_fact cf
                JOIN ontology_fact f ON f.fact_id = cf.fact_id
                WHERE cf.case_id = $1
                ORDER BY cf.created_at DESC
                "#,
            )
            .bind(case_id)
            .bind(evidence_limit as i64)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let facts: Vec<serde_json::Value> = facts_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "fact_id": r.try_get::<i64, _>("fact_id").unwrap_or(0),
                        "src_concept_id": r.try_get::<String, _>("src_concept_id").unwrap_or_default(),
                        "predicate": r.try_get::<String, _>("predicate").unwrap_or_default(),
                        "dst_concept_id": r.try_get::<String, _>("dst_concept_id").unwrap_or_default(),
                        "confidence": r.try_get::<f64, _>("confidence").unwrap_or(0.0),
                        "status": r.try_get::<String, _>("status").unwrap_or_default(),
                        "extractor": r.try_get::<String, _>("extractor").unwrap_or_default(),
                        "updated_at": r.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                        "linked_at": r.try_get::<time::OffsetDateTime, _>("linked_at").map(|t| t.to_string()).unwrap_or_default(),
                        "added_by": r.try_get::<String, _>("added_by").unwrap_or_default(),
                        "added_note": r.try_get::<String, _>("added_note").unwrap_or_default(),
                        "evidence_count": r.try_get::<i64, _>("evidence_count").unwrap_or(0),
                        "evidence_sample": r.try_get::<serde_json::Value, _>("evidence_sample").unwrap_or(json!([])),
                    })
                })
                .collect();

            let events_rows = match sqlx::query(
                r#"
                SELECT event_id, action, actor, note, payload_json, created_at
                FROM ontology_case_event
                WHERE case_id = $1
                ORDER BY created_at DESC
                "#,
            )
            .bind(case_id)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let events: Vec<serde_json::Value> = events_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "event_id": r.try_get::<i64, _>("event_id").unwrap_or(0),
                        "action": r.try_get::<String, _>("action").unwrap_or_default(),
                        "actor": r.try_get::<String, _>("actor").unwrap_or_default(),
                        "note": r.try_get::<String, _>("note").unwrap_or_default(),
                        "payload_json": r.try_get::<serde_json::Value, _>("payload_json").unwrap_or(json!({})),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();

            let decisions_rows = match sqlx::query(
                r#"
                SELECT
                  case_decision_id,
                  case_id,
                  decision_kind,
                  verdict,
                  summary,
                  rationale,
                  as_of_system_time,
                  as_of_effective_time,
                  snapshot_id,
                  source_evidence_json,
                  supersedes_case_decision_id,
                  created_by,
                  created_at
                FROM ontology_case_decision
                WHERE case_id = $1
                ORDER BY created_at DESC, case_decision_id DESC
                "#,
            )
            .bind(case_id)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let decisions: Vec<serde_json::Value> = decisions_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "case_decision_id": r.try_get::<i64, _>("case_decision_id").unwrap_or(0),
                        "case_id": r.try_get::<i64, _>("case_id").unwrap_or(0),
                        "decision_kind": r.try_get::<String, _>("decision_kind").unwrap_or_default(),
                        "verdict": r.try_get::<String, _>("verdict").unwrap_or_default(),
                        "summary": r.try_get::<String, _>("summary").unwrap_or_default(),
                        "rationale": r.try_get::<String, _>("rationale").unwrap_or_default(),
                        "as_of_system_time": r.try_get::<time::OffsetDateTime, _>("as_of_system_time").map(|t| t.to_string()).unwrap_or_default(),
                        "as_of_effective_time": r.try_get::<time::OffsetDateTime, _>("as_of_effective_time").map(|t| t.to_string()).unwrap_or_default(),
                        "snapshot_id": r.try_get::<String, _>("snapshot_id").unwrap_or_default(),
                        "source_evidence_json": r.try_get::<serde_json::Value, _>("source_evidence_json").unwrap_or(json!([])),
                        "supersedes_case_decision_id": r.try_get::<Option<i64>, _>("supersedes_case_decision_id").ok().flatten(),
                        "created_by": r.try_get::<String, _>("created_by").unwrap_or_default(),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();

            let alerts_rows = match sqlx::query(
                r#"
                SELECT
                  a.alert_id,
                  a.severity,
                  a.status,
                  a.message,
                  a.detail_json,
                  a.rule_key,
                  a.trigger_count,
                  a.first_triggered_at,
                  a.last_triggered_at,
                  a.acked_by,
                  a.acked_at,
                  a.closed_at,
                  a.created_at,
                  a.updated_at,
                  COALESCE(
                    (
                      SELECT json_agg(af.fact_id ORDER BY af.fact_id)
                      FROM ontology_alert_fact af
                      WHERE af.alert_id = a.alert_id
                    ),
                    '[]'::json
                  ) AS linked_fact_ids
                FROM ontology_alert
                a
                WHERE a.case_id = $1
                ORDER BY a.updated_at DESC
                "#,
            )
            .bind(case_id)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let alerts: Vec<serde_json::Value> = alerts_rows
                .into_iter()
                .map(|r| {
                    json!({
                        "alert_id": r.try_get::<i64, _>("alert_id").unwrap_or(0),
                        "severity": r.try_get::<String, _>("severity").unwrap_or_default(),
                        "status": r.try_get::<String, _>("status").unwrap_or_default(),
                        "message": r.try_get::<String, _>("message").unwrap_or_default(),
                        "detail_json": r.try_get::<serde_json::Value, _>("detail_json").unwrap_or(json!({})),
                        "rule_key": r.try_get::<Option<String>, _>("rule_key").ok().flatten(),
                        "trigger_count": r.try_get::<i32, _>("trigger_count").unwrap_or(1),
                        "first_triggered_at": r.try_get::<time::OffsetDateTime, _>("first_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                        "last_triggered_at": r.try_get::<time::OffsetDateTime, _>("last_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                        "linked_fact_ids": r.try_get::<serde_json::Value, _>("linked_fact_ids").unwrap_or(json!([])),
                        "acked_by": r.try_get::<Option<String>, _>("acked_by").ok().flatten(),
                        "acked_at": r.try_get::<Option<time::OffsetDateTime>, _>("acked_at").ok().flatten().map(|t| t.to_string()),
                        "closed_at": r.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                        "updated_at": r.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();

            let payload = json!({
                "case": {
                  "case_id": case_row.try_get::<i64, _>("case_id").unwrap_or(0),
                  "stream_id": case_row.try_get::<String, _>("stream_id").unwrap_or_default(),
                  "title": case_row.try_get::<String, _>("title").unwrap_or_default(),
                  "description": case_row.try_get::<String, _>("description").unwrap_or_default(),
                  "status": case_row.try_get::<String, _>("status").unwrap_or_default(),
                  "priority": case_row.try_get::<String, _>("priority").unwrap_or_default(),
                  "owner": case_row.try_get::<String, _>("owner").unwrap_or_default(),
                  "created_by": case_row.try_get::<String, _>("created_by").unwrap_or_default(),
                  "created_at": case_row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                  "updated_at": case_row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                  "closed_at": case_row.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
                },
                "facts": facts,
                "decisions": decisions,
                "events": events,
                "alerts": alerts,
                "evidence_limit": evidence_limit,
            });
            println!("{payload}");
        }
        "update_ontology_case" => {
            let case_id = match arg_value(&args, "--case-id").and_then(|v| v.parse::<i64>().ok()) {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--case-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let status = arg_value(&args, "--status").map(|v| v.to_lowercase());
            if let Some(v) = status.as_deref() {
                if !matches!(v, "open" | "in_review" | "resolved" | "dismissed") {
                    eprintln!("--status must be open|in_review|resolved|dismissed");
                    std::process::exit(2);
                }
            }
            let owner = arg_value(&args, "--owner");
            let note = arg_value(&args, "--note").unwrap_or_default();
            if status.is_none() && owner.is_none() && note.trim().is_empty() {
                eprintln!("at least one of --status, --owner, --note is required");
                std::process::exit(2);
            }
            let actor = env::var("USER").unwrap_or_else(|_| "system".to_string());
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let row = match sqlx::query(
                r#"
                UPDATE ontology_case
                SET
                  status = COALESCE($2, status),
                  owner = COALESCE($3, owner),
                  updated_at = NOW(),
                  closed_at = CASE
                    WHEN COALESCE($2, status) IN ('resolved', 'dismissed') THEN COALESCE(closed_at, NOW())
                    WHEN COALESCE($2, status) IN ('open', 'in_review') THEN NULL
                    ELSE closed_at
                  END
                WHERE case_id = $1
                RETURNING case_id, stream_id, title, status, priority, owner, updated_at, closed_at
                "#,
            )
            .bind(case_id)
            .bind(status.as_deref())
            .bind(owner.as_deref())
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("update failed: {e}");
                    std::process::exit(1);
                }
            };
            let Some(row) = row else {
                eprintln!("case not found: {case_id}");
                std::process::exit(1);
            };
            if let Some(v) = status.as_deref() {
                let _ = sqlx::query(
                    r#"
                    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                    VALUES ($1, 'status_change', $2, $3, $4)
                    "#,
                )
                .bind(case_id)
                .bind(actor.trim())
                .bind(note.trim())
                .bind(json!({ "status": v }))
                .execute(&mut *tx)
                .await;
            }
            if let Some(v) = owner.as_deref() {
                let _ = sqlx::query(
                    r#"
                    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                    VALUES ($1, 'owner_change', $2, $3, $4)
                    "#,
                )
                .bind(case_id)
                .bind(actor.trim())
                .bind(note.trim())
                .bind(json!({ "owner": v }))
                .execute(&mut *tx)
                .await;
            }
            if !note.trim().is_empty() {
                let _ = sqlx::query(
                    r#"
                    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                    VALUES ($1, 'note', $2, $3, $4)
                    "#,
                )
                .bind(case_id)
                .bind(actor.trim())
                .bind(note.trim())
                .bind(json!({}))
                .execute(&mut *tx)
                .await;
            }
            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }
            let payload = json!({
                "case_id": row.try_get::<i64, _>("case_id").unwrap_or(0),
                "stream_id": row.try_get::<String, _>("stream_id").unwrap_or_default(),
                "title": row.try_get::<String, _>("title").unwrap_or_default(),
                "status": row.try_get::<String, _>("status").unwrap_or_default(),
                "priority": row.try_get::<String, _>("priority").unwrap_or_default(),
                "owner": row.try_get::<String, _>("owner").unwrap_or_default(),
                "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                "closed_at": row.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
            });
            println!("{payload}");
        }
        "open_ontology_alert" => {
            let mut stream_id = arg_value(&args, "--stream-id").unwrap_or_default();
            let case_id = arg_value(&args, "--case-id").and_then(|v| v.parse::<i64>().ok());
            let severity = arg_value(&args, "--severity")
                .unwrap_or_else(|| "medium".to_string())
                .to_lowercase();
            if !matches!(severity.as_str(), "low" | "medium" | "high" | "critical") {
                eprintln!("--severity must be low|medium|high|critical");
                std::process::exit(2);
            }
            let message = match arg_value(&args, "--message") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--message is required");
                    std::process::exit(2);
                }
            };
            let actor = env::var("USER").unwrap_or_else(|_| "system".to_string());
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }

            if stream_id.trim().is_empty() {
                if let Some(cid) = case_id {
                    let row =
                        match sqlx::query("SELECT stream_id FROM ontology_case WHERE case_id = $1")
                            .bind(cid)
                            .fetch_optional(&pool)
                            .await
                        {
                            Ok(v) => v,
                            Err(e) => {
                                eprintln!("query failed: {e}");
                                std::process::exit(1);
                            }
                        };
                    if let Some(r) = row {
                        stream_id = r.try_get::<String, _>("stream_id").unwrap_or_default();
                    }
                }
            }
            if stream_id.trim().is_empty() {
                eprintln!("either --stream-id or --case-id (with valid case) is required");
                std::process::exit(2);
            }

            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let row = match sqlx::query(
                r#"
                INSERT INTO ontology_alert (case_id, stream_id, severity, status, message, detail_json)
                VALUES ($1, $2, $3, 'open', $4, $5)
                RETURNING alert_id, case_id, stream_id, severity, status, message, rule_key, trigger_count, first_triggered_at, last_triggered_at, created_at, updated_at
                "#,
            )
            .bind(case_id)
            .bind(stream_id.trim())
            .bind(&severity)
            .bind(message.trim())
            .bind(json!({ "source": "manual", "actor": actor.trim() }))
            .fetch_one(&mut *tx)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("open alert failed: {e}");
                    std::process::exit(1);
                }
            };
            let alert_id = row.try_get::<i64, _>("alert_id").unwrap_or(0);
            if let Some(cid) = case_id {
                let _ = sqlx::query(
                    r#"
                    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                    VALUES ($1, 'alert_link', $2, $3, $4)
                    "#,
                )
                .bind(cid)
                .bind(actor.trim())
                .bind(message.trim())
                .bind(json!({ "alert_id": alert_id, "severity": severity }))
                .execute(&mut *tx)
                .await;
            }
            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }
            let payload = json!({
                "alert_id": alert_id,
                "case_id": row.try_get::<Option<i64>, _>("case_id").ok().flatten(),
                "stream_id": row.try_get::<String, _>("stream_id").unwrap_or_default(),
                "severity": row.try_get::<String, _>("severity").unwrap_or_default(),
                "status": row.try_get::<String, _>("status").unwrap_or_default(),
                "message": row.try_get::<String, _>("message").unwrap_or_default(),
                "rule_key": row.try_get::<Option<String>, _>("rule_key").ok().flatten(),
                "trigger_count": row.try_get::<i32, _>("trigger_count").unwrap_or(1),
                "first_triggered_at": row.try_get::<time::OffsetDateTime, _>("first_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                "last_triggered_at": row.try_get::<time::OffsetDateTime, _>("last_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                "created_at": row.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
            });
            println!("{payload}");
        }
        "list_ontology_alerts" => {
            let stream_id_filter = arg_value(&args, "--stream-id");
            let status = arg_value(&args, "--status")
                .unwrap_or_else(|| "open".to_string())
                .to_lowercase();
            if !matches!(status.as_str(), "open" | "acked" | "closed" | "all") {
                eprintln!("--status must be open|acked|closed|all");
                std::process::exit(2);
            }
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(100)
                .clamp(1, 1000);
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let rows = match sqlx::query(
                r#"
                SELECT
                  a.alert_id,
                  a.case_id,
                  a.stream_id,
                  a.severity,
                  a.status,
                  a.message,
                  a.rule_key,
                  a.trigger_count,
                  a.first_triggered_at,
                  a.last_triggered_at,
                  a.acked_by,
                  a.acked_at,
                  a.closed_at,
                  a.created_at,
                  a.updated_at,
                  c.title AS case_title,
                  (SELECT COUNT(*)::BIGINT FROM ontology_alert_fact af WHERE af.alert_id = a.alert_id) AS linked_fact_count
                FROM ontology_alert a
                LEFT JOIN ontology_case c ON c.case_id = a.case_id
                WHERE ($1::text IS NULL OR a.stream_id = $1)
                  AND ($2::text = 'all' OR a.status = $2)
                ORDER BY
                  CASE a.severity
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    ELSE 4
                  END ASC,
                  a.updated_at DESC
                LIMIT $3
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .bind(&status)
            .bind(limit as i64)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let alerts: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|r| {
                    json!({
                        "alert_id": r.try_get::<i64, _>("alert_id").unwrap_or(0),
                        "case_id": r.try_get::<Option<i64>, _>("case_id").ok().flatten(),
                        "case_title": r.try_get::<Option<String>, _>("case_title").ok().flatten(),
                        "stream_id": r.try_get::<String, _>("stream_id").unwrap_or_default(),
                        "severity": r.try_get::<String, _>("severity").unwrap_or_default(),
                        "status": r.try_get::<String, _>("status").unwrap_or_default(),
                        "message": r.try_get::<String, _>("message").unwrap_or_default(),
                        "rule_key": r.try_get::<Option<String>, _>("rule_key").ok().flatten(),
                        "trigger_count": r.try_get::<i32, _>("trigger_count").unwrap_or(1),
                        "first_triggered_at": r.try_get::<time::OffsetDateTime, _>("first_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                        "last_triggered_at": r.try_get::<time::OffsetDateTime, _>("last_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                        "linked_fact_count": r.try_get::<i64, _>("linked_fact_count").unwrap_or(0),
                        "acked_by": r.try_get::<Option<String>, _>("acked_by").ok().flatten(),
                        "acked_at": r.try_get::<Option<time::OffsetDateTime>, _>("acked_at").ok().flatten().map(|t| t.to_string()),
                        "closed_at": r.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
                        "created_at": r.try_get::<time::OffsetDateTime, _>("created_at").map(|t| t.to_string()).unwrap_or_default(),
                        "updated_at": r.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();
            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "status_filter": status,
                "limit": limit,
                "count": alerts.len(),
                "alerts": alerts,
            });
            println!("{payload}");
        }
        "update_ontology_alert" => {
            let alert_id = match arg_value(&args, "--alert-id").and_then(|v| v.parse::<i64>().ok())
            {
                Some(v) if v > 0 => v,
                _ => {
                    eprintln!("--alert-id must be a positive integer");
                    std::process::exit(2);
                }
            };
            let status = match arg_value(&args, "--status").map(|v| v.to_lowercase()) {
                Some(v) if matches!(v.as_str(), "open" | "acked" | "closed") => v,
                _ => {
                    eprintln!("--status must be open|acked|closed");
                    std::process::exit(2);
                }
            };
            let note = arg_value(&args, "--note").unwrap_or_default();
            let actor = env::var("USER").unwrap_or_else(|_| "system".to_string());
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let row = match sqlx::query(
                r#"
                UPDATE ontology_alert
                SET
                  status = $2,
                  updated_at = NOW(),
                  acked_by = CASE WHEN $2 = 'acked' THEN $3 ELSE acked_by END,
                  acked_at = CASE WHEN $2 = 'acked' THEN NOW() ELSE acked_at END,
                  closed_at = CASE WHEN $2 = 'closed' THEN NOW() ELSE NULL END
                WHERE alert_id = $1
                RETURNING alert_id, case_id, stream_id, severity, status, message, rule_key, trigger_count, first_triggered_at, last_triggered_at, acked_by, acked_at, closed_at, updated_at
                "#,
            )
            .bind(alert_id)
            .bind(&status)
            .bind(actor.trim())
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("update failed: {e}");
                    std::process::exit(1);
                }
            };
            let Some(row) = row else {
                eprintln!("alert not found: {alert_id}");
                std::process::exit(1);
            };
            let case_id = row.try_get::<Option<i64>, _>("case_id").ok().flatten();
            if let Some(cid) = case_id {
                let _ = sqlx::query(
                    r#"
                    INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                    VALUES ($1, 'alert_link', $2, $3, $4)
                    "#,
                )
                .bind(cid)
                .bind(actor.trim())
                .bind(note.trim())
                .bind(json!({
                    "alert_id": alert_id,
                    "status": status,
                }))
                .execute(&mut *tx)
                .await;
            }
            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }
            let payload = json!({
                "alert_id": row.try_get::<i64, _>("alert_id").unwrap_or(0),
                "case_id": case_id,
                "stream_id": row.try_get::<String, _>("stream_id").unwrap_or_default(),
                "severity": row.try_get::<String, _>("severity").unwrap_or_default(),
                "status": row.try_get::<String, _>("status").unwrap_or_default(),
                "message": row.try_get::<String, _>("message").unwrap_or_default(),
                "rule_key": row.try_get::<Option<String>, _>("rule_key").ok().flatten(),
                "trigger_count": row.try_get::<i32, _>("trigger_count").unwrap_or(1),
                "first_triggered_at": row.try_get::<time::OffsetDateTime, _>("first_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                "last_triggered_at": row.try_get::<time::OffsetDateTime, _>("last_triggered_at").map(|t| t.to_string()).unwrap_or_default(),
                "acked_by": row.try_get::<Option<String>, _>("acked_by").ok().flatten(),
                "acked_at": row.try_get::<Option<time::OffsetDateTime>, _>("acked_at").ok().flatten().map(|t| t.to_string()),
                "closed_at": row.try_get::<Option<time::OffsetDateTime>, _>("closed_at").ok().flatten().map(|t| t.to_string()),
                "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
            });
            println!("{payload}");
        }
        "run_ontology_ops_rules" => {
            let run_started = Instant::now();
            let stream_id_filter = arg_value(&args, "--stream-id");
            let stale_days_cli = arg_value(&args, "--stale-days")
                .and_then(|v| v.parse::<i64>().ok())
                .unwrap_or(7)
                .max(1);
            let conflict_predicate_cli = arg_value(&args, "--conflict-predicate")
                .unwrap_or_else(|| "has_home_country".to_string());
            let dry_run = args.iter().any(|a| a == "--dry-run");
            let actor = env::var("USER").unwrap_or_else(|_| "system".to_string());

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }

            let mut rule_stale_enabled = true;
            let mut rule_conflict_enabled = true;
            let mut effective_stale_days = stale_days_cli;
            let mut effective_conflict_predicate = conflict_predicate_cli.clone();
            let mut stale_rule_severity = "medium".to_string();
            let mut conflict_rule_severity = "high".to_string();

            let cfg_rows = match sqlx::query(
                r#"
                SELECT
                  stream_id,
                  rule_name,
                  enabled,
                  stale_days,
                  conflict_predicate,
                  severity
                FROM ontology_ops_rule_config
                WHERE ($1::text IS NULL AND stream_id IS NULL)
                   OR ($1::text IS NOT NULL AND (stream_id = $1 OR stream_id IS NULL))
                ORDER BY
                  CASE
                    WHEN $1::text IS NOT NULL AND stream_id = $1 THEN 1
                    ELSE 0
                  END ASC,
                  updated_at ASC
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query config failed: {e}");
                    std::process::exit(1);
                }
            };
            for r in cfg_rows {
                let rule_name = r
                    .try_get::<String, _>("rule_name")
                    .unwrap_or_else(|_| "default".to_string());
                let enabled = r.try_get::<bool, _>("enabled").unwrap_or(true);
                let stale_days_cfg = r.try_get::<Option<i32>, _>("stale_days").ok().flatten();
                let conflict_pred_cfg = r
                    .try_get::<Option<String>, _>("conflict_predicate")
                    .ok()
                    .flatten();
                let severity_cfg = r.try_get::<Option<String>, _>("severity").ok().flatten();
                match rule_name.as_str() {
                    "default" => {
                        rule_stale_enabled = enabled;
                        rule_conflict_enabled = enabled;
                        if let Some(v) = stale_days_cfg {
                            if v > 0 {
                                effective_stale_days = v as i64;
                            }
                        }
                        if let Some(v) = conflict_pred_cfg {
                            if !v.trim().is_empty() {
                                effective_conflict_predicate = v;
                            }
                        }
                        if let Some(v) = severity_cfg {
                            stale_rule_severity = v.clone();
                            conflict_rule_severity = v;
                        }
                    }
                    "stale_pending" => {
                        rule_stale_enabled = enabled;
                        if let Some(v) = stale_days_cfg {
                            if v > 0 {
                                effective_stale_days = v as i64;
                            }
                        }
                        if let Some(v) = severity_cfg {
                            stale_rule_severity = v;
                        }
                    }
                    "conflict_predicate" => {
                        rule_conflict_enabled = enabled;
                        if let Some(v) = conflict_pred_cfg {
                            if !v.trim().is_empty() {
                                effective_conflict_predicate = v;
                            }
                        }
                        if let Some(v) = severity_cfg {
                            conflict_rule_severity = v;
                        }
                    }
                    _ => {}
                }
            }

            let stale_rows = if rule_stale_enabled {
                match sqlx::query(
                    r#"
                SELECT
                  fe.stream_id,
                  COUNT(DISTINCT f.fact_id)::BIGINT AS stale_fact_count,
                  ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
                FROM ontology_fact f
                JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                WHERE f.status IN ('candidate', 'needs_review')
                  AND f.updated_at < (NOW() - make_interval(days => $2::int))
                  AND ($1::text IS NULL OR fe.stream_id = $1)
                GROUP BY fe.stream_id
                ORDER BY stale_fact_count DESC, fe.stream_id ASC
                "#,
                )
                .bind(stream_id_filter.as_deref())
                .bind(effective_stale_days as i32)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                vec![]
            };
            let conflict_rows = if rule_conflict_enabled {
                match sqlx::query(
                    r#"
                SELECT
                  fe.stream_id,
                  f.src_concept_id,
                  COUNT(DISTINCT f.dst_concept_id)::BIGINT AS dst_count,
                  ARRAY_AGG(DISTINCT f.dst_concept_id) AS dst_values,
                  COUNT(DISTINCT f.fact_id)::BIGINT AS fact_count,
                  ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
                FROM ontology_fact f
                JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
                WHERE f.predicate = $2
                  AND f.status IN ('accepted', 'candidate', 'needs_review')
                  AND ($1::text IS NULL OR fe.stream_id = $1)
                GROUP BY fe.stream_id, f.src_concept_id
                HAVING COUNT(DISTINCT f.dst_concept_id) > 1
                ORDER BY fact_count DESC, fe.stream_id ASC, f.src_concept_id ASC
                "#,
                )
                .bind(stream_id_filter.as_deref())
                .bind(&effective_conflict_predicate)
                .fetch_all(&pool)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("query failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                vec![]
            };

            let mut created_cases: Vec<serde_json::Value> = vec![];
            let mut created_alerts: Vec<serde_json::Value> = vec![];
            let mut existing_cases: Vec<serde_json::Value> = vec![];
            let mut existing_alerts: Vec<serde_json::Value> = vec![];
            let mut candidates: Vec<serde_json::Value> = vec![];

            for row in stale_rows {
                let stream_id = row.try_get::<String, _>("stream_id").unwrap_or_default();
                let stale_fact_count = row.try_get::<i64, _>("stale_fact_count").unwrap_or(0);
                let fact_ids = row
                    .try_get::<Vec<i64>, _>("fact_ids")
                    .unwrap_or_else(|_| vec![]);
                if stream_id.is_empty() || stale_fact_count <= 0 {
                    continue;
                }
                let rule_key = format!("stale_pending:{stream_id}:{effective_stale_days}");
                let title =
                    format!("Rule stale_pending for {stream_id} (> {effective_stale_days}d)");
                let message = format!(
                    "Detected {stale_fact_count} stale pending ontology facts in {stream_id}"
                );
                candidates.push(json!({
                  "rule": "stale_pending",
                  "rule_key": rule_key,
                  "stream_id": stream_id,
                  "stale_fact_count": stale_fact_count,
                  "severity": stale_rule_severity,
                  "fact_ids": fact_ids,
                  "title": title,
                  "message": message,
                }));
            }
            for row in conflict_rows {
                let stream_id = row.try_get::<String, _>("stream_id").unwrap_or_default();
                let src_concept_id = row
                    .try_get::<String, _>("src_concept_id")
                    .unwrap_or_default();
                let dst_count = row.try_get::<i64, _>("dst_count").unwrap_or(0);
                let fact_count = row.try_get::<i64, _>("fact_count").unwrap_or(0);
                let dst_values = row
                    .try_get::<Vec<String>, _>("dst_values")
                    .unwrap_or_else(|_| vec![]);
                let fact_ids = row
                    .try_get::<Vec<i64>, _>("fact_ids")
                    .unwrap_or_else(|_| vec![]);
                if stream_id.is_empty() || src_concept_id.is_empty() || dst_count <= 1 {
                    continue;
                }
                let rule_key =
                    format!("conflict:{effective_conflict_predicate}:{stream_id}:{src_concept_id}");
                let title =
                    format!("Rule conflict {effective_conflict_predicate} for {src_concept_id}");
                let message = format!(
                    "Detected conflicting {} values for {} ({} distinct values, {} facts)",
                    effective_conflict_predicate, src_concept_id, dst_count, fact_count
                );
                candidates.push(json!({
                  "rule": "conflict_predicate",
                  "rule_key": rule_key,
                  "stream_id": stream_id,
                  "src_concept_id": src_concept_id,
                  "predicate": effective_conflict_predicate,
                  "severity": conflict_rule_severity,
                  "dst_values": dst_values,
                  "dst_count": dst_count,
                  "fact_count": fact_count,
                  "fact_ids": fact_ids,
                  "title": title,
                  "message": message,
                }));
            }

            if !dry_run {
                for c in &candidates {
                    let stream_id = c
                        .get("stream_id")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default();
                    let title = c.get("title").and_then(|v| v.as_str()).unwrap_or_default();
                    let message = c
                        .get("message")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default();
                    let rule_key = c
                        .get("rule_key")
                        .and_then(|v| v.as_str())
                        .unwrap_or_default();
                    if stream_id.is_empty() || title.is_empty() || rule_key.is_empty() {
                        continue;
                    }
                    let existing_case_row = match sqlx::query(
                        r#"
                        SELECT case_id
                        FROM ontology_case
                        WHERE stream_id = $1
                          AND title = $2
                          AND status IN ('open', 'in_review')
                        ORDER BY updated_at DESC
                        LIMIT 1
                        "#,
                    )
                    .bind(stream_id)
                    .bind(title)
                    .fetch_optional(&pool)
                    .await
                    {
                        Ok(v) => v,
                        Err(e) => {
                            eprintln!("query failed: {e}");
                            std::process::exit(1);
                        }
                    };
                    let case_id = if let Some(r) = existing_case_row {
                        let id = r.try_get::<i64, _>("case_id").unwrap_or(0);
                        existing_cases
                            .push(json!({"case_id": id, "stream_id": stream_id, "title": title}));
                        id
                    } else {
                        let row = match sqlx::query(
                            r#"
                            INSERT INTO ontology_case (stream_id, title, description, status, priority, owner, created_by)
                            VALUES ($1, $2, $3, 'open', 'p2', '', $4)
                            RETURNING case_id
                            "#,
                        )
                        .bind(stream_id)
                        .bind(title)
                        .bind(message)
                        .bind(actor.trim())
                        .fetch_one(&pool)
                        .await
                        {
                            Ok(v) => v,
                            Err(e) => {
                                eprintln!("insert case failed: {e}");
                                std::process::exit(1);
                            }
                        };
                        let id = row.try_get::<i64, _>("case_id").unwrap_or(0);
                        created_cases
                            .push(json!({"case_id": id, "stream_id": stream_id, "title": title}));
                        let _ = sqlx::query(
                            r#"
                            INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                            VALUES ($1, 'open', $2, $3, $4)
                            "#,
                        )
                        .bind(id)
                        .bind(actor.trim())
                        .bind(message)
                        .bind(c.clone())
                        .execute(&pool)
                        .await;
                        id
                    };

                    let fact_ids: Vec<i64> = c
                        .get("fact_ids")
                        .and_then(|v| v.as_array())
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|x| x.as_i64())
                                .filter(|x| *x > 0)
                                .collect()
                        })
                        .unwrap_or_default();
                    let rule_severity =
                        c.get("severity")
                            .and_then(|v| v.as_str())
                            .unwrap_or_else(|| {
                                if c.get("rule").and_then(|v| v.as_str())
                                    == Some("conflict_predicate")
                                {
                                    "high"
                                } else {
                                    "medium"
                                }
                            });
                    let existing_alert_row = match sqlx::query(
                        r#"
                        SELECT alert_id, severity, trigger_count
                        FROM ontology_alert
                        WHERE stream_id = $1
                          AND status IN ('open', 'acked')
                          AND rule_key = $2
                        ORDER BY updated_at DESC
                        LIMIT 1
                        "#,
                    )
                    .bind(stream_id)
                    .bind(rule_key)
                    .fetch_optional(&pool)
                    .await
                    {
                        Ok(v) => v,
                        Err(e) => {
                            eprintln!("query failed: {e}");
                            std::process::exit(1);
                        }
                    };
                    let alert_id = if let Some(r) = existing_alert_row {
                        let id = r.try_get::<i64, _>("alert_id").unwrap_or(0);
                        let old_sev = r
                            .try_get::<String, _>("severity")
                            .unwrap_or_else(|_| "low".to_string());
                        let old_trigger = r.try_get::<i32, _>("trigger_count").unwrap_or(1);
                        let new_sev = max_severity(&old_sev, rule_severity);
                        let _ = sqlx::query(
                            r#"
                            UPDATE ontology_alert
                            SET
                              case_id = COALESCE(case_id, $2),
                              severity = $3,
                              message = $4,
                              detail_json = $5,
                              trigger_count = GREATEST(trigger_count + 1, 1),
                              last_triggered_at = NOW(),
                              updated_at = NOW()
                            WHERE alert_id = $1
                            "#,
                        )
                        .bind(id)
                        .bind(case_id)
                        .bind(&new_sev)
                        .bind(message)
                        .bind(c.clone())
                        .execute(&pool)
                        .await;
                        existing_alerts.push(json!({
                          "alert_id": id,
                          "stream_id": stream_id,
                          "rule_key": rule_key,
                          "severity_before": old_sev,
                          "severity_after": new_sev,
                          "trigger_count_before": old_trigger,
                          "trigger_count_after": old_trigger + 1,
                        }));
                        id
                    } else {
                        let row = match sqlx::query(
                            r#"
                            INSERT INTO ontology_alert (
                              case_id, stream_id, severity, status, message, detail_json, rule_key,
                              trigger_count, first_triggered_at, last_triggered_at
                            )
                            VALUES ($1, $2, $3, 'open', $4, $5, $6, 1, NOW(), NOW())
                            RETURNING alert_id
                            "#,
                        )
                        .bind(case_id)
                        .bind(stream_id)
                        .bind(rule_severity)
                        .bind(message)
                        .bind(c.clone())
                        .bind(rule_key)
                        .fetch_one(&pool)
                        .await
                        {
                            Ok(v) => v,
                            Err(e) => {
                                eprintln!("insert alert failed: {e}");
                                std::process::exit(1);
                            }
                        };
                        let id = row.try_get::<i64, _>("alert_id").unwrap_or(0);
                        created_alerts.push(json!({
                          "alert_id": id,
                          "case_id": case_id,
                          "stream_id": stream_id,
                          "rule_key": rule_key,
                          "severity": rule_severity,
                          "trigger_count": 1,
                        }));
                        let _ = sqlx::query(
                            r#"
                            INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
                            VALUES ($1, 'alert_link', $2, $3, $4)
                            "#,
                        )
                        .bind(case_id)
                        .bind(actor.trim())
                        .bind(message)
                        .bind(json!({
                          "alert_id": id,
                          "rule_key": rule_key,
                          "severity": rule_severity,
                        }))
                        .execute(&pool)
                        .await;
                        id
                    };
                    for fact_id in &fact_ids {
                        let _ = sqlx::query(
                            r#"
                            INSERT INTO ontology_alert_fact (alert_id, fact_id, linked_by, linked_note)
                            VALUES ($1, $2, $3, $4)
                            ON CONFLICT (alert_id, fact_id) DO NOTHING
                            "#,
                        )
                        .bind(alert_id)
                        .bind(*fact_id)
                        .bind(actor.trim())
                        .bind(rule_key)
                        .execute(&pool)
                        .await;
                    }
                }
            }

            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "stale_days": effective_stale_days,
                "conflict_predicate": effective_conflict_predicate,
                "rules_enabled": {
                  "stale_pending": rule_stale_enabled,
                  "conflict_predicate": rule_conflict_enabled,
                },
                "rule_severity": {
                  "stale_pending": stale_rule_severity,
                  "conflict_predicate": conflict_rule_severity,
                },
                "dry_run": dry_run,
                "candidate_count": candidates.len(),
                "candidates": candidates,
                "created_cases": created_cases,
                "existing_cases": existing_cases,
                "created_alerts": created_alerts,
                "existing_alerts": existing_alerts,
            });
            let duration_ms = run_started.elapsed().as_millis() as i64;
            if let Err(e) = sqlx::query(
                r#"
                INSERT INTO ontology_ops_rule_run (
                  stream_id_filter,
                  stale_days,
                  conflict_predicate,
                  dry_run,
                  candidate_count,
                  created_case_count,
                  existing_case_count,
                  created_alert_count,
                  existing_alert_count,
                  payload_json,
                  started_at,
                  finished_at,
                  duration_ms
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW(), $11)
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .bind(effective_stale_days as i32)
            .bind(&effective_conflict_predicate)
            .bind(dry_run)
            .bind(candidates.len() as i32)
            .bind(created_cases.len() as i32)
            .bind(existing_cases.len() as i32)
            .bind(created_alerts.len() as i32)
            .bind(existing_alerts.len() as i32)
            .bind(payload.clone())
            .bind(duration_ms)
            .execute(&pool)
            .await
            {
                eprintln!("insert ops run failed: {e}");
                std::process::exit(1);
            }
            println!("{payload}");
        }
        "list_ontology_ops_runs" => {
            let stream_id_filter = arg_value(&args, "--stream-id");
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(50)
                .clamp(1, 1000);
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let rows = match sqlx::query(
                r#"
                SELECT
                  run_id,
                  stream_id_filter,
                  stale_days,
                  conflict_predicate,
                  dry_run,
                  candidate_count,
                  created_case_count,
                  existing_case_count,
                  created_alert_count,
                  existing_alert_count,
                  duration_ms,
                  started_at,
                  finished_at
                FROM ontology_ops_rule_run
                WHERE ($1::text IS NULL OR stream_id_filter = $1)
                ORDER BY started_at DESC
                LIMIT $2
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .bind(limit as i64)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let runs: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|r| {
                    json!({
                        "run_id": r.try_get::<i64, _>("run_id").unwrap_or(0),
                        "stream_id_filter": r.try_get::<Option<String>, _>("stream_id_filter").ok().flatten(),
                        "stale_days": r.try_get::<i32, _>("stale_days").unwrap_or(0),
                        "conflict_predicate": r.try_get::<String, _>("conflict_predicate").unwrap_or_default(),
                        "dry_run": r.try_get::<bool, _>("dry_run").unwrap_or(true),
                        "candidate_count": r.try_get::<i32, _>("candidate_count").unwrap_or(0),
                        "created_case_count": r.try_get::<i32, _>("created_case_count").unwrap_or(0),
                        "existing_case_count": r.try_get::<i32, _>("existing_case_count").unwrap_or(0),
                        "created_alert_count": r.try_get::<i32, _>("created_alert_count").unwrap_or(0),
                        "existing_alert_count": r.try_get::<i32, _>("existing_alert_count").unwrap_or(0),
                        "duration_ms": r.try_get::<i64, _>("duration_ms").unwrap_or(0),
                        "started_at": r.try_get::<time::OffsetDateTime, _>("started_at").map(|t| t.to_string()).unwrap_or_default(),
                        "finished_at": r.try_get::<time::OffsetDateTime, _>("finished_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();
            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "limit": limit,
                "count": runs.len(),
                "runs": runs,
            });
            println!("{payload}");
        }
        "list_ontology_ops_rule_config" => {
            let stream_id_filter = arg_value(&args, "--stream-id");
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let rows = match sqlx::query(
                r#"
                SELECT
                  config_id,
                  stream_id,
                  rule_name,
                  enabled,
                  stale_days,
                  conflict_predicate,
                  severity,
                  note,
                  updated_by,
                  updated_at
                FROM ontology_ops_rule_config
                WHERE ($1::text IS NULL OR stream_id = $1 OR stream_id IS NULL)
                ORDER BY
                  CASE WHEN stream_id IS NULL THEN 1 ELSE 0 END,
                  stream_id ASC NULLS LAST,
                  rule_name ASC
                "#,
            )
            .bind(stream_id_filter.as_deref())
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let configs: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|r| {
                    json!({
                        "config_id": r.try_get::<i64, _>("config_id").unwrap_or(0),
                        "stream_id": r.try_get::<Option<String>, _>("stream_id").ok().flatten(),
                        "rule_name": r.try_get::<String, _>("rule_name").unwrap_or_default(),
                        "enabled": r.try_get::<bool, _>("enabled").unwrap_or(true),
                        "stale_days": r.try_get::<Option<i32>, _>("stale_days").ok().flatten(),
                        "conflict_predicate": r.try_get::<Option<String>, _>("conflict_predicate").ok().flatten(),
                        "severity": r.try_get::<Option<String>, _>("severity").ok().flatten(),
                        "note": r.try_get::<String, _>("note").unwrap_or_default(),
                        "updated_by": r.try_get::<String, _>("updated_by").unwrap_or_default(),
                        "updated_at": r.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();
            let payload = json!({
                "stream_id_filter": stream_id_filter,
                "count": configs.len(),
                "configs": configs,
            });
            println!("{payload}");
        }
        "upsert_ontology_ops_rule_config" => {
            let rule_name = match arg_value(&args, "--rule-name") {
                Some(v) => v.to_ascii_lowercase(),
                None => {
                    eprintln!("--rule-name is required");
                    std::process::exit(2);
                }
            };
            if !matches!(
                rule_name.as_str(),
                "default" | "stale_pending" | "conflict_predicate"
            ) {
                eprintln!("--rule-name must be default|stale_pending|conflict_predicate");
                std::process::exit(2);
            }
            let stream_id = arg_value(&args, "--stream-id").and_then(|v| {
                let t = v.trim().to_string();
                if t.is_empty() { None } else { Some(t) }
            });
            let enabled = arg_value(&args, "--enabled")
                .as_deref()
                .and_then(parse_boolish)
                .unwrap_or(true);
            let stale_days = arg_value(&args, "--stale-days").and_then(|v| v.parse::<i32>().ok());
            if let Some(v) = stale_days {
                if v <= 0 {
                    eprintln!("--stale-days must be positive");
                    std::process::exit(2);
                }
            }
            let conflict_predicate = arg_value(&args, "--conflict-predicate").and_then(|v| {
                let t = v.trim().to_string();
                if t.is_empty() { None } else { Some(t) }
            });
            let severity = arg_value(&args, "--severity").map(|v| v.to_ascii_lowercase());
            if let Some(ref v) = severity {
                if !matches!(v.as_str(), "low" | "medium" | "high" | "critical") {
                    eprintln!("--severity must be low|medium|high|critical");
                    std::process::exit(2);
                }
            }
            let note = arg_value(&args, "--note").unwrap_or_default();
            let updated_by = env::var("USER").unwrap_or_else(|_| "system".to_string());

            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_ops_schema(&pool).await {
                eprintln!("ensure ops schema failed: {e}");
                std::process::exit(1);
            }
            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let existing = match sqlx::query(
                r#"
                SELECT config_id
                FROM ontology_ops_rule_config
                WHERE rule_name = $1
                  AND COALESCE(stream_id, '') = COALESCE($2, '')
                LIMIT 1
                "#,
            )
            .bind(&rule_name)
            .bind(stream_id.as_deref())
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query config failed: {e}");
                    std::process::exit(1);
                }
            };
            let row = if let Some(existing_row) = existing {
                let config_id = existing_row.try_get::<i64, _>("config_id").unwrap_or(0);
                match sqlx::query(
                    r#"
                    UPDATE ontology_ops_rule_config
                    SET
                      enabled = $2,
                      stale_days = COALESCE($3, stale_days),
                      conflict_predicate = COALESCE($4, conflict_predicate),
                      severity = COALESCE($5, severity),
                      note = $6,
                      updated_by = $7,
                      updated_at = NOW()
                    WHERE config_id = $1
                    RETURNING
                      config_id,
                      stream_id,
                      rule_name,
                      enabled,
                      stale_days,
                      conflict_predicate,
                      severity,
                      note,
                      updated_by,
                      updated_at
                    "#,
                )
                .bind(config_id)
                .bind(enabled)
                .bind(stale_days)
                .bind(conflict_predicate.as_deref())
                .bind(severity.as_deref())
                .bind(note.trim())
                .bind(updated_by.trim())
                .fetch_one(&mut *tx)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("update config failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                match sqlx::query(
                    r#"
                    INSERT INTO ontology_ops_rule_config (
                      stream_id,
                      rule_name,
                      enabled,
                      stale_days,
                      conflict_predicate,
                      severity,
                      note,
                      updated_by
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING
                      config_id,
                      stream_id,
                      rule_name,
                      enabled,
                      stale_days,
                      conflict_predicate,
                      severity,
                      note,
                      updated_by,
                      updated_at
                    "#,
                )
                .bind(stream_id.as_deref())
                .bind(&rule_name)
                .bind(enabled)
                .bind(stale_days)
                .bind(conflict_predicate.as_deref())
                .bind(severity.as_deref())
                .bind(note.trim())
                .bind(updated_by.trim())
                .fetch_one(&mut *tx)
                .await
                {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("insert config failed: {e}");
                        std::process::exit(1);
                    }
                }
            };
            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }
            let payload = json!({
                "config_id": row.try_get::<i64, _>("config_id").unwrap_or(0),
                "stream_id": row.try_get::<Option<String>, _>("stream_id").ok().flatten(),
                "rule_name": row.try_get::<String, _>("rule_name").unwrap_or_default(),
                "enabled": row.try_get::<bool, _>("enabled").unwrap_or(true),
                "stale_days": row.try_get::<Option<i32>, _>("stale_days").ok().flatten(),
                "conflict_predicate": row.try_get::<Option<String>, _>("conflict_predicate").ok().flatten(),
                "severity": row.try_get::<Option<String>, _>("severity").ok().flatten(),
                "note": row.try_get::<String, _>("note").unwrap_or_default(),
                "updated_by": row.try_get::<String, _>("updated_by").unwrap_or_default(),
                "updated_at": row.try_get::<time::OffsetDateTime, _>("updated_at").map(|t| t.to_string()).unwrap_or_default(),
            });
            println!("{payload}");
        }
        "load_ontology_registry" => {
            let file_path = match arg_value(&args, "--file") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--file is required");
                    std::process::exit(2);
                }
            };
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let raw = match fs::read_to_string(&file_path) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("failed to read registry yaml: {e}");
                    std::process::exit(1);
                }
            };
            let registry: OntologyRegistryFile = match parse_registry_file(&raw) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("invalid registry file (yaml/json): {e}");
                    std::process::exit(1);
                }
            };
            let defaults = registry.defaults.clone().unwrap_or_default();
            let loaded_by = env::var("USER").unwrap_or_else(|_| "system".to_string());
            let payload_json = match serde_json::to_value(&registry) {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("failed to serialize registry payload: {e}");
                    std::process::exit(1);
                }
            };
            let planned_predicate_count = registry
                .predicates
                .iter()
                .filter(|p| !p.predicate.trim().is_empty())
                .count();
            let mut tx = match pool.begin().await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("tx begin failed: {e}");
                    std::process::exit(1);
                }
            };
            let load_id = match sqlx::query(
                r#"
                INSERT INTO ontology_registry_load (
                  registry_name,
                  registry_version,
                  source_path,
                  predicate_count,
                  payload_hash,
                  payload_json,
                  loaded_by
                )
                VALUES (
                  $1,
                  $2,
                  $3,
                  $4,
                  md5($5),
                  $6,
                  $7
                )
                RETURNING load_id
                "#,
            )
            .bind(
                registry
                    .registry_name
                    .clone()
                    .unwrap_or_else(|| "unnamed_registry".to_string()),
            )
            .bind(registry.version)
            .bind(&file_path)
            .bind(planned_predicate_count as i32)
            .bind(&raw)
            .bind(sqlx::types::Json(payload_json))
            .bind(&loaded_by)
            .fetch_one(&mut *tx)
            .await
            {
                Ok(v) => v.try_get::<i64, _>("load_id").unwrap_or(0),
                Err(e) => {
                    eprintln!("insert registry load failed: {e}");
                    std::process::exit(1);
                }
            };
            let mut loaded = 0usize;
            for p in &registry.predicates {
                if p.predicate.trim().is_empty() {
                    continue;
                }
                if let Err(e) = upsert_registry_predicate(&mut tx, load_id, &defaults, p).await {
                    eprintln!("upsert predicate failed predicate={}: {e}", p.predicate);
                    std::process::exit(1);
                }
                loaded += 1;
            }
            if let Err(e) = tx.commit().await {
                eprintln!("tx commit failed: {e}");
                std::process::exit(1);
            }
            let payload = json!({
                "load_id": load_id,
                "file": file_path,
                "version": registry.version,
                "registry_name": registry.registry_name,
                "loaded_predicates": loaded,
                "loaded_by": loaded_by,
            });
            println!("{payload}");
        }
        "list_ontology_registry_loads" => {
            let registry_name_filter = arg_value(&args, "--registry-name");
            let limit = arg_value(&args, "--limit")
                .and_then(|v| v.parse::<usize>().ok())
                .unwrap_or(20)
                .clamp(1, 500);
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let rows = match sqlx::query(
                r#"
                SELECT
                  load_id,
                  registry_name,
                  registry_version,
                  source_path,
                  predicate_count,
                  payload_hash,
                  loaded_by,
                  loaded_at
                FROM ontology_registry_load
                WHERE ($1::text IS NULL OR registry_name = $1)
                ORDER BY loaded_at DESC, load_id DESC
                LIMIT $2
                "#,
            )
            .bind(registry_name_filter.as_deref())
            .bind(limit as i64)
            .fetch_all(&pool)
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("query failed: {e}");
                    std::process::exit(1);
                }
            };
            let loads: Vec<serde_json::Value> = rows
                .into_iter()
                .map(|row| {
                    json!({
                        "load_id": row.try_get::<i64, _>("load_id").unwrap_or(0),
                        "registry_name": row.try_get::<String, _>("registry_name").unwrap_or_default(),
                        "registry_version": row.try_get::<Option<i32>, _>("registry_version").ok().flatten(),
                        "source_path": row.try_get::<String, _>("source_path").unwrap_or_default(),
                        "predicate_count": row.try_get::<i32, _>("predicate_count").unwrap_or(0),
                        "payload_hash": row.try_get::<String, _>("payload_hash").unwrap_or_default(),
                        "loaded_by": row.try_get::<String, _>("loaded_by").unwrap_or_default(),
                        "loaded_at": row.try_get::<time::OffsetDateTime, _>("loaded_at").map(|t| t.to_string()).unwrap_or_default(),
                    })
                })
                .collect();
            let payload = json!({
                "registry_name_filter": registry_name_filter,
                "limit": limit,
                "loads": loads,
            });
            println!("{payload}");
        }
        "build_event_ontology_from_triples" => {
            let stream_id = match arg_value(&args, "--stream-id") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--stream-id is required");
                    std::process::exit(2);
                }
            };
            let predicates = arg_value(&args, "--predicate")
                .map(|v| {
                    parse_text_csv(&v)
                        .into_iter()
                        .collect::<std::collections::HashSet<String>>()
                })
                .filter(|s| !s.is_empty())
                .unwrap_or_else(default_projection_predicates);
            let dry_run = args.iter().any(|a| a == "--dry-run");
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let started = Instant::now();
            let stats = match build_event_ontology_from_triples(
                &database_url,
                &stream_id,
                &predicates,
                dry_run,
            )
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("build_event_ontology_from_triples failed: {e}");
                    std::process::exit(1);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            let persona_refs = resolve_persona_ref_for_stream(&database_url, &stream_id)
                .await
                .unwrap_or_else(|_| json!({}));
            let trace = json!({
                "stream_id": stream_id,
                "predicates": predicates,
                "dry_run": dry_run,
                "stats": stats,
                "elapsed_ms": started.elapsed().as_millis()
            });
            let snapshot_id = match write_state_snapshot_row(
                &pool,
                "build_event_ontology",
                &stream_id,
                persona_refs,
                trace.clone(),
            )
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("write state_snapshot failed: {e}");
                    std::process::exit(1);
                }
            };
            let payload = json!({
                "stream_id": stream_id,
                "snapshot_id": snapshot_id,
                "trace": trace,
            });
            println!("{payload}");
        }
        "simulate_counterfactual" => {
            let stream_id = match arg_value(&args, "--stream-id") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--stream-id is required");
                    std::process::exit(2);
                }
            };
            let mode = match arg_value(&args, "--mode") {
                Some(v) => v,
                None => {
                    eprintln!("--mode is required: ablation|swap");
                    std::process::exit(2);
                }
            };
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let started = Instant::now();
            let result = if mode == "ablation" {
                let remove_event = match arg_value(&args, "--remove-event") {
                    Some(v) if !v.trim().is_empty() => v,
                    _ => {
                        eprintln!("--remove-event is required for mode=ablation");
                        std::process::exit(2);
                    }
                };
                match simulate_ablation(&database_url, &stream_id, &remove_event).await {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("simulate ablation failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else if mode == "swap" {
                let from_event = match arg_value(&args, "--from-event") {
                    Some(v) if !v.trim().is_empty() => v,
                    _ => {
                        eprintln!("--from-event is required for mode=swap");
                        std::process::exit(2);
                    }
                };
                let action_key = match arg_value(&args, "--action") {
                    Some(v) if !v.trim().is_empty() => v,
                    _ => {
                        eprintln!("--action is required for mode=swap");
                        std::process::exit(2);
                    }
                };
                match simulate_swap(&database_url, &stream_id, &from_event, &action_key).await {
                    Ok(v) => v,
                    Err(e) => {
                        eprintln!("simulate swap failed: {e}");
                        std::process::exit(1);
                    }
                }
            } else {
                eprintln!("invalid --mode: {mode}");
                std::process::exit(2);
            };

            let persona_refs = resolve_persona_ref_for_stream(&database_url, &stream_id)
                .await
                .unwrap_or_else(|_| json!({}));
            let sim_trace = result_to_trace(&result);
            let trace = json!({
                "stream_id": stream_id,
                "mode": mode,
                "simulation": sim_trace,
                "elapsed_ms": started.elapsed().as_millis()
            });
            let snapshot_id = match write_state_snapshot_row(
                &pool,
                "simulate_counterfactual",
                &stream_id,
                persona_refs,
                trace.clone(),
            )
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("write state_snapshot failed: {e}");
                    std::process::exit(1);
                }
            };
            let payload = json!({
                "stream_id": stream_id,
                "snapshot_id": snapshot_id,
                "trace": trace
            });
            println!("{payload}");
        }
        "project_world_state" => {
            let stream_id = match arg_value(&args, "--stream-id") {
                Some(v) if !v.trim().is_empty() => v,
                _ => {
                    eprintln!("--stream-id is required");
                    std::process::exit(2);
                }
            };
            let database_url = match env::var("DATABASE_URL") {
                Ok(v) => v,
                Err(_) => {
                    eprintln!("DATABASE_URL is required");
                    std::process::exit(2);
                }
            };
            let pool = match sqlx::PgPool::connect(&database_url).await {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("db connect failed: {e}");
                    std::process::exit(1);
                }
            };
            if let Err(e) = ensure_ontology_extension_schema(&pool).await {
                eprintln!("ontology schema check failed: {e}");
                std::process::exit(1);
            }
            let accepted_only = args.iter().any(|a| a == "--accepted-only");
            let filters = ProjectionFilters {
                include_candidate: !accepted_only,
                include_accepted: true,
            };
            let state = match project_state(
                &database_url,
                &stream_id,
                time::OffsetDateTime::now_utc(),
                filters,
            )
            .await
            {
                Ok(v) => v,
                Err(e) => {
                    eprintln!("project_world_state failed: {e}");
                    std::process::exit(1);
                }
            };
            println!("{state}");
        }
        _ => {
            eprintln!("{}", usage());
            std::process::exit(2);
        }
    }
}
