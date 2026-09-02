// src/trace/snapshot.rs
#![allow(dead_code)]

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::time::{Duration, SystemTime};

use serde::{Deserialize, Serialize};

use crate::core::asset::{AssetId, AssetVersion, Intent};
use crate::time::bitemporal::AsOf;

use crate::query::context_builder::{ContextBuildMode, ContextBuilder};

/// Replay failure with a human-readable reason (PoC).
#[derive(Clone, Debug)]
pub struct ReplayError {
    pub message: String,
}

impl ReplayError {
    fn new(msg: impl Into<String>) -> Self {
        Self {
            message: msg.into(),
        }
    }
}

impl std::fmt::Display for ReplayError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl std::error::Error for ReplayError {}

/// Minimal reference to a specific asset version used in a decision/context.
#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct AssetRef {
    pub asset_id: String,
    pub version_number: u64,
}

impl AssetRef {
    pub fn new(asset_id: String, version_number: u64) -> Self {
        Self {
            asset_id,
            version_number,
        }
    }
}

/// A frozen, replayable snapshot of what the system used at decision time.
///
/// PoC semantics:
/// - snapshot_id is deterministic given the same inputs (intent/as_of/refs).
/// - refs are stored as versioned pointers (asset_id + version_number).

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DecisionSnapshot {
    pub snapshot_id: String,
    pub intent: Intent,
    pub as_of: AsOf,

    pub evidence_refs: Vec<AssetRef>,
    pub reasoning_refs: Vec<AssetRef>,
    pub persona_refs: Vec<AssetRef>,
}

impl DecisionSnapshot {
    /// Create a snapshot from lists of resolved asset versions.
    ///
    /// This function:
    /// 1) converts versions to refs
    /// 2) sorts refs deterministically
    /// 3) computes a deterministic snapshot_id
    pub fn from_versions(
        intent: Intent,
        as_of: AsOf,
        evidence_assets: &[AssetVersion],
        reasoning_assets: &[AssetVersion],
        persona_assets: &[AssetVersion],
    ) -> Self {
        let mut evidence_refs = versions_to_refs(evidence_assets);
        let mut reasoning_refs = versions_to_refs(reasoning_assets);
        let mut persona_refs = versions_to_refs(persona_assets);

        sort_refs_stably(&mut evidence_refs);
        sort_refs_stably(&mut reasoning_refs);
        sort_refs_stably(&mut persona_refs);

        let snapshot_id = compute_snapshot_id(
            intent,
            as_of,
            &evidence_refs,
            &reasoning_refs,
            &persona_refs,
        );

        Self {
            snapshot_id,
            intent,
            as_of,
            evidence_refs,
            reasoning_refs,
            persona_refs,
        }
    }
}

impl DecisionSnapshot {
    /// Rebuild a context at the snapshot's intent/as_of and verify it reproduces the same snapshot.
    ///
    /// PoC semantics:
    /// - Uses Explicit evidence mode to ensure we replay against the same evidence set.
    /// - Compares snapshot_id and all ref lists.
    pub fn replay_and_verify(
        &self,
        all_versions: &[AssetVersion],
    ) -> Result<DecisionSnapshot, ReplayError> {
        // Rebuild using the snapshot’s evidence list as an explicit constraint.
        let evidence_ids = self
            .evidence_refs
            .iter()
            .map(|r| AssetId::new(&r.asset_id))
            .collect::<Vec<_>>();

        let ctx = ContextBuilder::build(
            self.intent,
            self.as_of,
            all_versions,
            ContextBuildMode::Explicit {
                evidence_ids: evidence_ids.clone(),
            },
        )
        .map_err(|v| {
            ReplayError::new(format!(
                "Replay build hard-rejected by policy: code={} message={} asset_id={} version={}",
                v.code, v.message, v.asset_id, v.version_number
            ))
        })?;

        let replayed = ContextBuilder::freeze_snapshot(&ctx);

        // Verify deterministic identity.
        if replayed.snapshot_id != self.snapshot_id {
            return Err(ReplayError::new(format!(
                "Snapshot ID mismatch: expected={} got={}",
                self.snapshot_id, replayed.snapshot_id
            )));
        }

        // Verify exact refs (these should already be deterministically sorted in from_versions()).
        if replayed.evidence_refs != self.evidence_refs {
            return Err(ReplayError::new("Evidence refs mismatch"));
        }
        if replayed.reasoning_refs != self.reasoning_refs {
            return Err(ReplayError::new("Reasoning refs mismatch"));
        }
        if replayed.persona_refs != self.persona_refs {
            return Err(ReplayError::new("Persona refs mismatch"));
        }

        Ok(replayed)
    }
}

/// Convert versions to minimal refs.
fn versions_to_refs(versions: &[AssetVersion]) -> Vec<AssetRef> {
    versions
        .iter()
        .map(|v| AssetRef::new(v.asset_id.as_str().to_string(), v.version_number))
        .collect()
}

/// Deterministic sorting for stable IDs and outputs.
fn sort_refs_stably(refs: &mut Vec<AssetRef>) {
    refs.sort_by(|a, b| match a.asset_id.cmp(&b.asset_id) {
        std::cmp::Ordering::Equal => a.version_number.cmp(&b.version_number),
        other => other,
    });
}

/// Compute a deterministic snapshot id from intent/as_of and the three ref lists.
///
/// PoC approach:
/// - Use the standard library hasher (not cryptographic).
/// - Output a readable hex string.
///
/// Later (product):
/// - Use a cryptographic hash (SHA-256 / BLAKE3) and stable serialization.
fn compute_snapshot_id(
    intent: Intent,
    as_of: AsOf,
    evidence_refs: &[AssetRef],
    reasoning_refs: &[AssetRef],
    persona_refs: &[AssetRef],
) -> String {
    let mut h = DefaultHasher::new();

    // Intent participates in identity.
    // If Intent is not Hash, change this to `format!("{:?}", intent)` and hash the string.
    intent.hash(&mut h);

    // AsOf participates in identity (system/effective time).
    // SystemTime is not Hash, so we derive a stable primitive.
    let sys_ns = system_time_to_nanos(as_of.system_as_of);
    let eff_ns = system_time_to_nanos(as_of.effective_as_of);
    sys_ns.hash(&mut h);
    eff_ns.hash(&mut h);

    // Ref lists participate in identity.
    // (Already sorted deterministically by caller.)
    evidence_refs.hash(&mut h);
    reasoning_refs.hash(&mut h);
    persona_refs.hash(&mut h);

    let v = h.finish();
    format!("{:016x}", v)
}

/// Convert SystemTime to a stable numeric value for hashing.
///
/// PoC rule:
/// - duration since UNIX_EPOCH in nanoseconds (u128 truncated to u64 via folding).
///
/// If SystemTime is before UNIX_EPOCH, fall back to 0 (rare for this PoC).
fn system_time_to_nanos(t: SystemTime) -> u64 {
    use std::time::UNIX_EPOCH;

    match t.duration_since(UNIX_EPOCH) {
        Ok(d) => duration_to_u64_nanos(d),
        Err(_) => 0,
    }
}

/// Fold Duration into a u64 nanosecond value.
/// (u128 nanos are folded to avoid overflow risk.)
fn duration_to_u64_nanos(d: Duration) -> u64 {
    let nanos: u128 = (d.as_secs() as u128) * 1_000_000_000u128 + (d.subsec_nanos() as u128);

    // Fold u128 into u64 deterministically.
    (nanos as u64) ^ ((nanos >> 64) as u64)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::asset::{AssetId, AssetType, Bitemporal};
    use std::time::{Duration, UNIX_EPOCH};

    fn mk_version(asset_id: &str, version_number: u64) -> AssetVersion {
        AssetVersion::new(
            AssetId::new(asset_id),
            AssetType::KnowledgeBase,
            version_number,
            Bitemporal::new(
                UNIX_EPOCH + Duration::from_secs(10),
                UNIX_EPOCH + Duration::from_secs(10),
                None,
            ),
            None,
            format!("content-{asset_id}-{version_number}"),
        )
    }

    #[test]
    fn snapshot_id_is_deterministic_across_input_order() {
        let as_of = AsOf {
            system_as_of: UNIX_EPOCH + Duration::from_secs(100),
            effective_as_of: UNIX_EPOCH + Duration::from_secs(100),
        };

        let a1 = mk_version("kb:a", 1);
        let a2 = mk_version("kb:a", 2);
        let b1 = mk_version("kb:b", 1);

        let s1 = DecisionSnapshot::from_versions(
            Intent::DecisionSupport,
            as_of,
            &[b1.clone(), a1.clone()],
            &[a2.clone(), b1.clone()],
            &[a1.clone()],
        );
        let s2 = DecisionSnapshot::from_versions(
            Intent::DecisionSupport,
            as_of,
            &[a1.clone(), b1.clone()],
            &[b1.clone(), a2.clone()],
            &[a1],
        );

        assert_eq!(s1.snapshot_id, s2.snapshot_id);
        assert_eq!(s1.evidence_refs, s2.evidence_refs);
        assert_eq!(s1.reasoning_refs, s2.reasoning_refs);
        assert_eq!(s1.persona_refs, s2.persona_refs);
    }

    #[test]
    fn snapshot_id_changes_when_as_of_changes() {
        let v = mk_version("kb:a", 1);

        let s1 = DecisionSnapshot::from_versions(
            Intent::DecisionSupport,
            AsOf {
                system_as_of: UNIX_EPOCH + Duration::from_secs(100),
                effective_as_of: UNIX_EPOCH + Duration::from_secs(100),
            },
            std::slice::from_ref(&v),
            std::slice::from_ref(&v),
            &[],
        );

        let s2 = DecisionSnapshot::from_versions(
            Intent::DecisionSupport,
            AsOf {
                system_as_of: UNIX_EPOCH + Duration::from_secs(101),
                effective_as_of: UNIX_EPOCH + Duration::from_secs(100),
            },
            std::slice::from_ref(&v),
            std::slice::from_ref(&v),
            &[],
        );

        assert_ne!(s1.snapshot_id, s2.snapshot_id);
    }
}
