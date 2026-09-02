// tdb/core/asset.rs
#![allow(dead_code)]

use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use std::time::SystemTime;

/// Top-level classification of all cognitive assets.
///
/// This enum is intentionally small.
/// Expanding it is a governance decision, not a convenience change.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum AssetType {
    KnowledgeBase,
    Ledger,
    Persona,
}

/// Strongly typed asset identifier.
/// Prevents accidental mixing of unrelated IDs.
#[derive(Clone, Debug, Eq, PartialEq, Hash)]
pub struct AssetId(String);

impl AssetId {
    pub fn new<S: Into<String>>(value: S) -> Self {
        Self(value.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Bitemporal model:
/// - system_time: when the system learned or recorded this asset
/// - effective_from / effective_to: when the asset is valid in reality
#[derive(Clone, Debug)]
pub struct Bitemporal {
    pub system_time: SystemTime,
    pub effective_from: SystemTime,
    pub effective_to: Option<SystemTime>,
}

impl Bitemporal {
    pub fn new(
        system_time: SystemTime,
        effective_from: SystemTime,
        effective_to: Option<SystemTime>,
    ) -> Self {
        Self {
            system_time,
            effective_from,
            effective_to,
        }
    }
}

/// Asset payload representation.
///
/// For PoC, this is plain text.
/// Later versions may replace this with structured or typed content.
pub type AssetContent = String;

/// Concrete versioned asset instance.
///
/// This struct represents a single immutable version of an asset.
#[derive(Clone, Debug)]
pub struct AssetVersion {
    pub asset_id: AssetId,
    pub asset_type: AssetType,
    pub version_number: u64,
    pub bitemporal: Bitemporal,
    pub supersedes_version: Option<u64>,
    pub content: AssetContent,
}

impl AssetVersion {
    pub fn new(
        asset_id: AssetId,
        asset_type: AssetType,
        version_number: u64,
        bitemporal: Bitemporal,
        supersedes_version: Option<u64>,
        content: AssetContent,
    ) -> Self {
        Self {
            asset_id,
            asset_type,
            version_number,
            bitemporal,
            supersedes_version,
            content,
        }
    }
}

/// Core trait implemented by all cognitive asset versions.
///
/// This is the semantic contract that all downstream systems rely on.
pub trait CognitiveAsset {
    fn asset_id(&self) -> &AssetId;
    fn asset_type(&self) -> AssetType;
    fn version_number(&self) -> u64;
    fn bitemporal(&self) -> &Bitemporal;
    fn content(&self) -> &str;

    /// Indicates whether this asset type may be used as authoritative evidence.
    ///
    /// **Hard rule:** Persona assets must never be used as evidence.
    fn can_be_evidence(&self) -> bool;
}

impl CognitiveAsset for AssetVersion {
    fn asset_id(&self) -> &AssetId {
        &self.asset_id
    }

    fn asset_type(&self) -> AssetType {
        self.asset_type
    }

    fn version_number(&self) -> u64 {
        self.version_number
    }

    fn bitemporal(&self) -> &Bitemporal {
        &self.bitemporal
    }

    fn content(&self) -> &str {
        &self.content
    }

    fn can_be_evidence(&self) -> bool {
        // Only Knowledge Base assets are authoritative evidence.
        // Ledger assets are accountable records.
        // Persona assets are behavioral hints.
        matches!(self.asset_type, AssetType::KnowledgeBase)
    }
}

/// Reasoning intent used by policy and query layers.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub enum Intent {
    FactLookup,
    DecisionSupport,
    Reflection,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ParseIntentError {
    value: String,
}

impl fmt::Display for ParseIntentError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "invalid intent value: {}", self.value)
    }
}

impl std::error::Error for ParseIntentError {}

impl Intent {
    pub fn as_str(self) -> &'static str {
        match self {
            Intent::FactLookup => "fact_lookup",
            Intent::DecisionSupport => "decision_support",
            Intent::Reflection => "reflection",
        }
    }
}

impl fmt::Display for Intent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl FromStr for Intent {
    type Err = ParseIntentError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "fact_lookup" => Ok(Intent::FactLookup),
            "decision_support" => Ok(Intent::DecisionSupport),
            "reflection" => Ok(Intent::Reflection),
            _ => Err(ParseIntentError {
                value: s.to_string(),
            }),
        }
    }
}

/// Determines whether an asset type may participate in reasoning
/// for a given intent.
pub fn is_allowed_in_reasoning(intent: Intent, asset_type: AssetType) -> bool {
    match intent {
        Intent::FactLookup => matches!(asset_type, AssetType::KnowledgeBase),
        Intent::DecisionSupport => matches!(
            asset_type,
            AssetType::KnowledgeBase | AssetType::Ledger | AssetType::Persona
        ),
        Intent::Reflection => matches!(
            asset_type,
            AssetType::KnowledgeBase | AssetType::Ledger | AssetType::Persona
        ),
    }
}

/// Determines whether an asset type may be used as evidence.
pub fn is_allowed_as_evidence(asset_type: AssetType) -> bool {
    matches!(asset_type, AssetType::KnowledgeBase)
}

#[cfg(test)]
mod tests {
    use super::Intent;
    use std::str::FromStr;

    #[test]
    fn intent_round_trips_with_stable_strings() {
        let intents = [
            Intent::FactLookup,
            Intent::DecisionSupport,
            Intent::Reflection,
        ];

        for intent in intents {
            let s = intent.as_str();
            let parsed = Intent::from_str(s).expect("intent should parse from stable string");
            assert_eq!(parsed, intent);
        }
    }

    #[test]
    fn intent_parse_rejects_unknown_values() {
        assert!(Intent::from_str("DecisionSupport").is_err());
        assert!(Intent::from_str("unknown").is_err());
    }
}
