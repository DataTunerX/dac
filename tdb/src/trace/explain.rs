// src/trace/explain.rs
#![allow(dead_code)]

use std::time::{SystemTime, UNIX_EPOCH};

use crate::trace::event::TraceEvent;
use crate::trace::snapshot::{AssetRef, DecisionSnapshot};

/// Produce a human-readable explanation for a snapshot.
/// PoC goal: clear, auditable, demo-friendly output.
pub fn explain_snapshot_text(snapshot: &DecisionSnapshot, trace: &[TraceEvent]) -> String {
    let mut out = String::new();

    out.push_str("=== EXPLAIN SNAPSHOT ===\n");
    out.push_str(&format!("snapshot_id: {}\n", snapshot.snapshot_id));
    out.push_str(&format!("intent: {:?}\n", snapshot.intent));
    out.push_str(&format!(
        "as_of.system: {}\n",
        format_system_time(snapshot.as_of.system_as_of)
    ));
    out.push_str(&format!(
        "as_of.effective: {}\n",
        format_system_time(snapshot.as_of.effective_as_of)
    ));
    out.push('\n');

    // Lists (refs are already deterministic in snapshot)
    out.push_str("Evidence (authoritative):\n");
    write_refs(&mut out, &snapshot.evidence_refs);

    out.push_str("\nPersona (non-evidence):\n");
    write_refs(&mut out, &snapshot.persona_refs);

    out.push_str("\nReasoning context:\n");
    write_refs(&mut out, &snapshot.reasoning_refs);

    out.push('\n');

    // Key trace events: for PoC, we filter to the most meaningful actions.
    out.push_str("Key trace:\n");
    let mut any = false;
    for e in trace.iter() {
        if is_key_action(&e.action) {
            any = true;
            out.push_str(&format!(
                "- {} {}@v{} ({})\n",
                e.action, e.asset_id, e.version_number, e.reason
            ));
        }
    }
    if !any {
        out.push_str("- (no key trace events)\n");
    }

    out
}

fn write_refs(out: &mut String, refs: &[AssetRef]) {
    if refs.is_empty() {
        out.push_str("- (none)\n");
        return;
    }

    for r in refs.iter() {
        out.push_str(&format!("- {}@v{}\n", r.asset_id, r.version_number));
    }
}

/// Decide which trace actions are most useful in a demo/audit readout.
fn is_key_action(action: &str) -> bool {
    matches!(
        action,
        "resolved_effective"
            | "included"
            | "excluded"
            | "persona_only"
            | "evidence_included"
            | "evidence_excluded"
            | "evidence_required_ok"
            | "no_effective_version"
    )
}

/// Simple, dependency-free time formatting for PoC.
/// Uses seconds since UNIX_EPOCH to avoid external crates.
fn format_system_time(t: SystemTime) -> String {
    match t.duration_since(UNIX_EPOCH) {
        Ok(d) => format!("{}s", d.as_secs()),
        Err(_) => "pre-epoch".to_string(),
    }
}
