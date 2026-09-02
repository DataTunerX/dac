// src/time/bitemporal.rs

use crate::core::asset::{AssetId, AssetType, AssetVersion};
use crate::trace::event::TraceEvent;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::SystemTime;

/// Bitemporal "as-of" point:
/// - system_as_of: what the system knew at that time (recorded by then)
/// - effective_as_of: what was valid in reality at that time
#[derive(Clone, Copy, Debug, Serialize, Deserialize)]
pub struct AsOf {
    pub system_as_of: SystemTime,
    pub effective_as_of: SystemTime,
}

/// -----------------------------
/// Bitemporal resolution (PoC)
/// -----------------------------

pub fn resolve_effective_versions(
    all_versions: &[AssetVersion],
    as_of: AsOf,
    trace: &mut Vec<TraceEvent>,
) -> Vec<AssetVersion> {
    let mut by_id: HashMap<AssetId, Vec<AssetVersion>> = HashMap::new();

    for v in all_versions.iter().cloned() {
        by_id.entry(v.asset_id.clone()).or_default().push(v);
    }

    let mut resolved: Vec<AssetVersion> = Vec::new();

    for (asset_id, mut versions) in by_id {
        // Filter by system visibility and effective validity.
        versions.retain(|v| is_visible_under_system_time(v, as_of.system_as_of));
        versions.retain(|v| is_valid_under_effective_time(v, as_of.effective_as_of));

        if versions.is_empty() {
            // Nothing eligible for this asset_id at this as-of point.
            // Trace a single synthetic event for observability.
            trace.push(TraceEvent {
                asset_id: asset_id.as_str().to_string(),
                asset_type: AssetType::Ledger,
                version_number: 0,
                action: "no_effective_version".to_string(),
                reason: "No version is visible under system time and valid under effective time"
                    .to_string(),
            });
            continue;
        }

        // Deterministic winner selection.
        versions.sort_by(compare_candidates_desc);
        let winner = versions[0].clone();

        trace.push(TraceEvent {
            asset_id: winner.asset_id.as_str().to_string(),
            asset_type: winner.asset_type,
            version_number: winner.version_number,
            action: "resolved_effective".to_string(),
            reason: "Selected by bitemporal resolution tie-breakers".to_string(),
        });

        resolved.push(winner);
    }

    resolved
}

fn is_visible_under_system_time(v: &AssetVersion, system_as_of: SystemTime) -> bool {
    v.bitemporal.system_time <= system_as_of
}

fn is_valid_under_effective_time(v: &AssetVersion, effective_as_of: SystemTime) -> bool {
    let from = v.bitemporal.effective_from;
    let to = v.bitemporal.effective_to;
    effective_as_of >= from
        && match to {
            None => true,
            Some(t) => effective_as_of < t,
        }
}

/// Tie-breakers (descending priority):
/// 1) later effective_from wins
/// 2) later system_time wins
/// 3) higher version_number wins
fn compare_candidates_desc(a: &AssetVersion, b: &AssetVersion) -> std::cmp::Ordering {
    match b
        .bitemporal
        .effective_from
        .cmp(&a.bitemporal.effective_from)
    {
        std::cmp::Ordering::Equal => {
            match b.bitemporal.system_time.cmp(&a.bitemporal.system_time) {
                std::cmp::Ordering::Equal => b.version_number.cmp(&a.version_number),
                other => other,
            }
        }
        other => other,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::asset::Bitemporal;
    use std::time::{Duration, UNIX_EPOCH};

    fn mk_version(
        asset_id: &str,
        version_number: u64,
        system_secs: u64,
        effective_from_secs: u64,
        effective_to_secs: Option<u64>,
    ) -> AssetVersion {
        AssetVersion::new(
            AssetId::new(asset_id),
            AssetType::KnowledgeBase,
            version_number,
            Bitemporal::new(
                UNIX_EPOCH + Duration::from_secs(system_secs),
                UNIX_EPOCH + Duration::from_secs(effective_from_secs),
                effective_to_secs.map(|s| UNIX_EPOCH + Duration::from_secs(s)),
            ),
            None,
            format!("content-v{version_number}"),
        )
    }

    #[test]
    fn resolves_only_versions_visible_and_effective_as_of() {
        let versions = vec![
            mk_version("kb:roi", 1, 10, 10, Some(20)),
            mk_version("kb:roi", 2, 30, 30, None),
        ];

        let as_of = AsOf {
            system_as_of: UNIX_EPOCH + Duration::from_secs(15),
            effective_as_of: UNIX_EPOCH + Duration::from_secs(15),
        };

        let mut trace = Vec::new();
        let resolved = resolve_effective_versions(&versions, as_of, &mut trace);

        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].version_number, 1);
    }

    #[test]
    fn prefers_later_effective_from_first() {
        let versions = vec![
            mk_version("kb:roi", 1, 50, 10, None),
            mk_version("kb:roi", 2, 20, 30, None),
        ];

        let as_of = AsOf {
            system_as_of: UNIX_EPOCH + Duration::from_secs(100),
            effective_as_of: UNIX_EPOCH + Duration::from_secs(100),
        };

        let mut trace = Vec::new();
        let resolved = resolve_effective_versions(&versions, as_of, &mut trace);

        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].version_number, 2);
    }

    #[test]
    fn tie_breaks_by_system_time_then_version_number() {
        let versions = vec![
            mk_version("kb:roi", 1, 10, 10, None),
            mk_version("kb:roi", 2, 20, 10, None),
            mk_version("kb:roi", 3, 20, 10, None),
        ];

        let as_of = AsOf {
            system_as_of: UNIX_EPOCH + Duration::from_secs(100),
            effective_as_of: UNIX_EPOCH + Duration::from_secs(100),
        };

        let mut trace = Vec::new();
        let resolved = resolve_effective_versions(&versions, as_of, &mut trace);

        assert_eq!(resolved.len(), 1);
        assert_eq!(resolved[0].version_number, 3);
    }
}
