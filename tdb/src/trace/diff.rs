// src/trace/diff.rs
#![allow(dead_code)]

use std::collections::HashMap;

use crate::trace::snapshot::{AssetRef, DecisionSnapshot};

/// Difference between two ref sets.
///
/// Semantics:
/// - added: present in B but not in A
/// - removed: present in A but not in B
/// - changed: same asset_id, different version (A -> B)
#[derive(Debug, Default)]
pub struct RefSetDiff {
    pub added: Vec<AssetRef>,
    pub removed: Vec<AssetRef>,
    pub changed: Vec<(AssetRef, AssetRef)>,
}

/// Diff for all three channels.
#[derive(Debug, Default)]
pub struct SnapshotDiffAll {
    pub evidence: RefSetDiff,
    pub reasoning: RefSetDiff,
    pub persona: RefSetDiff,
}

/// Diff evidence only (kept for convenience / backward compatibility).
pub fn diff_snapshots(a: &DecisionSnapshot, b: &DecisionSnapshot) -> RefSetDiff {
    diff_ref_sets(&a.evidence_refs, &b.evidence_refs)
}

/// Diff evidence + reasoning + persona.
pub fn diff_all(a: &DecisionSnapshot, b: &DecisionSnapshot) -> SnapshotDiffAll {
    SnapshotDiffAll {
        evidence: diff_ref_sets(&a.evidence_refs, &b.evidence_refs),
        reasoning: diff_ref_sets(&a.reasoning_refs, &b.reasoning_refs),
        persona: diff_ref_sets(&a.persona_refs, &b.persona_refs),
    }
}

/// Core diff implementation for a pair of ref lists.
/// The output is deterministically sorted for stable demos/tests.
pub fn diff_ref_sets(a_refs: &[AssetRef], b_refs: &[AssetRef]) -> RefSetDiff {
    let a_map = to_map(a_refs);
    let b_map = to_map(b_refs);

    let mut added = Vec::new();
    let mut removed = Vec::new();
    let mut changed = Vec::new();

    // Present in A
    for (asset_id, a_ref) in a_map.iter() {
        match b_map.get(asset_id) {
            None => removed.push(a_ref.clone()),
            Some(b_ref) => {
                if a_ref.version_number != b_ref.version_number {
                    changed.push((a_ref.clone(), b_ref.clone()));
                }
            }
        }
    }

    // Newly added in B
    for (asset_id, b_ref) in b_map.iter() {
        if !a_map.contains_key(asset_id) {
            added.push(b_ref.clone());
        }
    }

    sort_refs(&mut added);
    sort_refs(&mut removed);
    sort_changed(&mut changed);

    RefSetDiff {
        added,
        removed,
        changed,
    }
}

fn to_map(refs: &[AssetRef]) -> HashMap<String, AssetRef> {
    let mut m = HashMap::new();
    for r in refs.iter() {
        m.insert(r.asset_id.clone(), r.clone());
    }
    m
}

fn sort_refs(refs: &mut Vec<AssetRef>) {
    refs.sort_by(|a, b| match a.asset_id.cmp(&b.asset_id) {
        std::cmp::Ordering::Equal => a.version_number.cmp(&b.version_number),
        other => other,
    });
}

fn sort_changed(changed: &mut Vec<(AssetRef, AssetRef)>) {
    changed.sort_by(|(a1, b1), (a2, b2)| match a1.asset_id.cmp(&a2.asset_id) {
        std::cmp::Ordering::Equal => b1.version_number.cmp(&b2.version_number),
        other => other,
    });
}
