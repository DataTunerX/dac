// src/trace/event.rs

use crate::core::asset::AssetType;
use serde::{Deserialize, Serialize};

/// A minimal trace event for audit/debug.
/// Keep it simple in PoC: record what happened and why.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TraceEvent {
    pub asset_id: String,
    pub asset_type: AssetType,
    pub version_number: u64,
    pub action: String, // "included", "excluded", "persona_only", "evidence_included", ...
    pub reason: String,
}
