// tdb/query/context_builder.rs
#![allow(dead_code)]

use crate::core::asset::{AssetId, AssetType, AssetVersion, CognitiveAsset, Intent};
use crate::policy::type_rules::{
    PolicyDecision, PolicyViolation, evaluate_type_policy, is_asset_allowed_as_evidence,
    require_asset_allowed_as_evidence,
};
use crate::time::bitemporal::{AsOf, resolve_effective_versions};
use crate::trace::event::TraceEvent;

use crate::trace::snapshot::DecisionSnapshot;

/// Output of context building.
/// The key semantic separation is:
/// - reasoning_assets: what may participate in reasoning
/// - persona_assets: allowed only for presentation/orchestration (never evidence)
/// - evidence_assets: what may be cited as authoritative evidence
#[derive(Clone, Debug)]
pub struct CognitiveContext {
    pub intent: Intent,
    pub as_of: AsOf,

    pub reasoning_assets: Vec<AssetVersion>,
    pub persona_assets: Vec<AssetVersion>,
    pub evidence_assets: Vec<AssetVersion>,

    pub trace: Vec<TraceEvent>,
}

/// Controls how a cognitive context is constructed.
///
/// - Auto: the system assembles evidence opportunistically; illegal evidence is excluded.
/// - Explicit: the caller provides an explicit evidence list; any illegal evidence is hard-rejected.
#[derive(Clone, Debug)]
pub enum ContextBuildMode {
    Auto,
    Explicit { evidence_ids: Vec<AssetId> },
}

/// Context builder that composes a bounded, auditable context from a pool of versions.
///
/// This PoC implementation is in-memory and deterministic:
/// 1) bitemporal resolution per asset_id
/// 2) intent/type policy gating
/// 3) persona separation (non-evidence channel)
/// 4) evidence gating (KB-only in current rules)
pub struct ContextBuilder;

impl ContextBuilder {
    pub fn build(
        intent: Intent,
        as_of: AsOf,
        all_versions: &[AssetVersion],
        mode: ContextBuildMode,
    ) -> Result<CognitiveContext, PolicyViolation> {
        use std::collections::{HashMap, HashSet};

        let mut trace: Vec<TraceEvent> = Vec::new();

        // Step 1: resolve the single effective version per asset_id under bitemporal as-of.
        let resolved_list = resolve_effective_versions(all_versions, as_of, &mut trace);

        // Build a map for fast lookup by AssetId.
        let mut resolved_map: HashMap<AssetId, AssetVersion> = HashMap::new();
        for v in resolved_list.iter().cloned() {
            resolved_map.insert(v.asset_id.clone(), v);
        }

        // Step 2: evidence handling (the only mode fork).
        let mut evidence_assets: Vec<AssetVersion> = Vec::new();

        match mode {
            ContextBuildMode::Auto => {
                // Auto mode: opportunistic evidence selection.
                // Illegal evidence is excluded (soft behavior).
                for v in resolved_map.values().cloned() {
                    match is_asset_allowed_as_evidence(intent, &v) {
                        Ok(()) => {
                            trace.push(TraceEvent {
                                asset_id: v.asset_id.as_str().to_string(),
                                asset_type: v.asset_type,
                                version_number: v.version_number,
                                action: "evidence_included".to_string(),
                                reason:
                                    "Asset is allowed as evidence under policy and asset semantics"
                                        .to_string(),
                            });
                            evidence_assets.push(v);
                        }
                        Err(reason) => {
                            trace.push(TraceEvent {
                                asset_id: v.asset_id.as_str().to_string(),
                                asset_type: v.asset_type,
                                version_number: v.version_number,
                                action: "evidence_excluded".to_string(),
                                reason: reason.to_string(),
                            });
                        }
                    }
                }
            }

            ContextBuildMode::Explicit { evidence_ids } => {
                // Explicit mode: caller-provided evidence list.
                // Any illegal request is hard-rejected.
                let mut seen: HashSet<AssetId> = HashSet::new();

                for id in evidence_ids {
                    if !seen.insert(id.clone()) {
                        continue; // dedupe while preserving first occurrence order
                    }

                    let v = match resolved_map.get(&id) {
                        Some(v) => v.clone(),
                        None => {
                            return Err(PolicyViolation {
                                code: "EVIDENCE_NOT_RESOLVABLE_AS_OF",
                                message: "Explicit evidence asset has no effective version at the requested as-of time",
                                intent,
                                // Unknown because it cannot be resolved at this as-of.
                                asset_type: AssetType::Ledger,
                                asset_id: id.as_str().to_string(),
                                version_number: 0,
                            });
                        }
                    };

                    // HARD GATE: must be legal as evidence, or fail immediately.
                    require_asset_allowed_as_evidence(intent, &v)?;

                    trace.push(TraceEvent {
                        asset_id: v.asset_id.as_str().to_string(),
                        asset_type: v.asset_type,
                        version_number: v.version_number,
                        action: "evidence_required_ok".to_string(),
                        reason: "Explicit evidence request passed hard policy gate".to_string(),
                    });

                    evidence_assets.push(v);
                }
            }
        }

        // Step 3: apply type policy by intent and split into channels.
        let mut reasoning_assets: Vec<AssetVersion> = Vec::new();
        let mut persona_assets: Vec<AssetVersion> = Vec::new();

        for v in resolved_map.values().cloned() {
            let policy = evaluate_type_policy(intent, v.asset_type());

            match policy.decision {
                PolicyDecision::Deny => {
                    trace.push(TraceEvent {
                        asset_id: v.asset_id.as_str().to_string(),
                        asset_type: v.asset_type,
                        version_number: v.version_number,
                        action: "excluded".to_string(),
                        reason: policy.reason.to_string(),
                    });
                }

                PolicyDecision::Allow => {
                    trace.push(TraceEvent {
                        asset_id: v.asset_id.as_str().to_string(),
                        asset_type: v.asset_type,
                        version_number: v.version_number,
                        action: "included".to_string(),
                        reason: policy.reason.to_string(),
                    });
                    reasoning_assets.push(v);
                }

                PolicyDecision::AllowNonEvidenceOnly => {
                    trace.push(TraceEvent {
                        asset_id: v.asset_id.as_str().to_string(),
                        asset_type: v.asset_type,
                        version_number: v.version_number,
                        action: "persona_only".to_string(),
                        reason: policy.reason.to_string(),
                    });
                    persona_assets.push(v.clone());
                    reasoning_assets.push(v);
                }
            }
        }

        // Stable ordering for deterministic outputs.
        sort_assets_stably(&mut reasoning_assets);
        sort_assets_stably(&mut persona_assets);

        // Evidence ordering:
        // - Auto: currently inherits HashMap iteration order (not stable).
        // - Explicit: preserves caller order (deduped).
        //
        // If you prefer stable evidence ordering for Auto, uncomment:
        // sort_assets_stably(&mut evidence_assets);

        Ok(CognitiveContext {
            intent,
            as_of,
            reasoning_assets,
            persona_assets,
            evidence_assets,
            trace,
        })
    }

    /// Freeze a replayable, deterministic snapshot of what was used
    /// to construct this cognitive context.
    ///
    /// This is the core of the "Decision Time Machine":
    /// given the same inputs, this snapshot ID is guaranteed to be identical.
    pub fn freeze_snapshot(ctx: &CognitiveContext) -> DecisionSnapshot {
        DecisionSnapshot::from_versions(
            ctx.intent,
            ctx.as_of,
            &ctx.evidence_assets,
            &ctx.reasoning_assets,
            &ctx.persona_assets,
        )
    }
}

/// Stable sort for outputs (for deterministic demos).
/// Order by:
/// 1) asset_type (string-ish via manual rank)
/// 2) asset_id
/// 3) version_number (descending)
fn sort_assets_stably(assets: &mut Vec<AssetVersion>) {
    assets.sort_by(|a, b| {
        let ra = asset_type_rank(a.asset_type);
        let rb = asset_type_rank(b.asset_type);

        match ra.cmp(&rb) {
            std::cmp::Ordering::Equal => match a.asset_id.as_str().cmp(b.asset_id.as_str()) {
                std::cmp::Ordering::Equal => b.version_number.cmp(&a.version_number),
                other => other,
            },
            other => other,
        }
    });
}

fn asset_type_rank(t: AssetType) -> u8 {
    match t {
        AssetType::KnowledgeBase => 0,
        AssetType::Ledger => 1,
        AssetType::Persona => 2,
    }
}
