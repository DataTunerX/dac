// src/main.rs

use std::time::{Duration, SystemTime};

use tdb::core::asset::{AssetId, AssetType, AssetVersion, Bitemporal, Intent};
use tdb::query::context_builder::{ContextBuildMode, ContextBuilder};
use tdb::time::bitemporal::AsOf;
use tdb::trace::explain::explain_snapshot_text;

fn main() {
    println!("=== TDB PoC: Decision Time Machine Demo ===");

    // Base time
    let t0 = SystemTime::now();

    // --------------------------------------------------
    // Create demo assets (in memory)
    // --------------------------------------------------

    // KB: ROI definition v1
    let roi_v1 = AssetVersion::new(
        AssetId::new("kb:metric:roi"),
        AssetType::KnowledgeBase,
        1,
        Bitemporal::new(t0, t0, None),
        None,
        "ROI = (Profit / Investment)".to_string(),
    );

    // KB: ROI definition v2 (effective later, ingested later)
    let roi_v2 = AssetVersion::new(
        AssetId::new("kb:metric:roi"),
        AssetType::KnowledgeBase,
        2,
        Bitemporal::new(
            t0 + Duration::from_secs(10),
            t0 + Duration::from_secs(5),
            None,
        ),
        Some(1),
        "ROI = (Net Profit / Total Investment)".to_string(),
    );

    // Ledger: past decision
    let decision = AssetVersion::new(
        AssetId::new("ledger:decision:project-x"),
        AssetType::Ledger,
        1,
        Bitemporal::new(
            t0 + Duration::from_secs(2),
            t0 + Duration::from_secs(2),
            None,
        ),
        None,
        "Project X was rejected due to low ROI".to_string(),
    );

    // Persona: committee chair preference
    let persona = AssetVersion::new(
        AssetId::new("persona:chair:risk"),
        AssetType::Persona,
        1,
        Bitemporal::new(t0, t0, None),
        None,
        "Risk-averse investment style".to_string(),
    );

    let all_versions = vec![roi_v1, roi_v2, decision, persona];

    // --------------------------------------------------
    // Build context AS OF an earlier time
    // --------------------------------------------------
    let as_of_early = AsOf {
        system_as_of: t0 + Duration::from_secs(3),
        effective_as_of: t0 + Duration::from_secs(3),
    };

    let context_early = ContextBuilder::build(
        Intent::DecisionSupport,
        as_of_early,
        &all_versions,
        ContextBuildMode::Auto,
    )
    .unwrap();

    println!("\n--- Context AS OF early time ---");
    println!("Evidence assets:");
    for a in &context_early.evidence_assets {
        println!(
            "- {} v{}: {}",
            a.asset_id.as_str(),
            a.version_number,
            a.content
        );
    }

    // --------------------------------------------------
    // Build context AS OF a later time
    // --------------------------------------------------
    let as_of_late = AsOf {
        system_as_of: t0 + Duration::from_secs(20),
        effective_as_of: t0 + Duration::from_secs(20),
    };

    let context_late = ContextBuilder::build(
        Intent::DecisionSupport,
        as_of_late,
        &all_versions,
        ContextBuildMode::Auto,
    )
    .unwrap();

    println!("\n--- Context AS OF later time ---");
    println!("Evidence assets:");
    for a in &context_late.evidence_assets {
        println!(
            "- {} v{}: {}",
            a.asset_id.as_str(),
            a.version_number,
            a.content
        );
    }

    println!("\n--- Freeze Context AS OF late time as a snapshot ---");
    let snapshot = ContextBuilder::freeze_snapshot(&context_late);
    let replayed = snapshot.replay_and_verify(&all_versions).unwrap();
    println!(
        "snapshot and replay ok: snapshot_id={}",
        replayed.snapshot_id
    );

    println!("\n--- Explain Snapshot ---");
    let explanation = explain_snapshot_text(&snapshot, &context_late.trace);
    println!("{}", explanation);

    use tdb::trace::diff::diff_all;
    let snap1 = ContextBuilder::freeze_snapshot(&context_early);

    let diff = diff_all(&snap1, &snapshot);

    println!("=== SNAPSHOT DIFF ===");
    println!("Evidence changes:");
    for x in diff.evidence.added {
        println!("+ {}@v{}", x.asset_id, x.version_number);
    }
    for x in diff.evidence.removed {
        println!("- {}@v{}", x.asset_id, x.version_number);
    }
    for (o, n) in diff.evidence.changed {
        println!(
            "~ {} v{} -> v{}",
            o.asset_id, o.version_number, n.version_number
        );
    }

    println!("Reasoning changes:");
    for x in diff.reasoning.added {
        println!("+ {}@v{}", x.asset_id, x.version_number);
    }
    for x in diff.reasoning.removed {
        println!("- {}@v{}", x.asset_id, x.version_number);
    }
    for (o, n) in diff.reasoning.changed {
        println!(
            "~ {} v{} -> v{}",
            o.asset_id, o.version_number, n.version_number
        );
    }

    println!("Persona changes:");
    for x in diff.persona.added {
        println!("+ {}@v{}", x.asset_id, x.version_number);
    }
    for x in diff.persona.removed {
        println!("- {}@v{}", x.asset_id, x.version_number);
    }
    for (o, n) in diff.persona.changed {
        println!(
            "~ {} v{} -> v{}",
            o.asset_id, o.version_number, n.version_number
        );
    }

    // --------------------------------------------------
    // Show trace (what happened and why)
    // --------------------------------------------------
    println!("\n--- Trace (later context) ---");
    for event in &context_late.trace {
        println!(
            "[{:?}] {} v{} -> {} ({})",
            event.asset_type, event.asset_id, event.version_number, event.action, event.reason
        );
    }
}
