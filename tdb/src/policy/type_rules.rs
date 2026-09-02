// src/policy/type_rules.rs
#![allow(dead_code)]

use crate::core::asset::{AssetType, CognitiveAsset, Intent};

/// Policy decision for an asset under a given intent.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDecision {
    /// Asset is fully allowed and may participate in reasoning.
    Allow,

    /// Asset may be used, but only for non-evidential purposes
    /// (e.g. tone, prioritization, orchestration).
    AllowNonEvidenceOnly,

    /// Asset is completely disallowed for this intent.
    Deny,
}

/// Result of policy evaluation with an explanation.
#[derive(Clone, Debug)]
pub struct PolicyResult {
    pub decision: PolicyDecision,
    pub reason: &'static str,
}

impl PolicyResult {
    pub fn allow(reason: &'static str) -> Self {
        Self {
            decision: PolicyDecision::Allow,
            reason,
        }
    }

    pub fn allow_non_evidence(reason: &'static str) -> Self {
        Self {
            decision: PolicyDecision::AllowNonEvidenceOnly,
            reason,
        }
    }

    pub fn deny(reason: &'static str) -> Self {
        Self {
            decision: PolicyDecision::Deny,
            reason,
        }
    }
}

/// A structured, auditable policy violation.
///
/// This is used for "hard rejection" paths:
/// when a caller explicitly requests an illegal action, the system must fail.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicyViolation {
    pub code: &'static str,
    pub message: &'static str,
    pub intent: Intent,
    pub asset_type: AssetType,
    pub asset_id: String,
    pub version_number: u64,
}

impl PolicyViolation {
    pub fn new<A: CognitiveAsset>(
        code: &'static str,
        message: &'static str,
        intent: Intent,
        asset: &A,
    ) -> Self {
        Self {
            code,
            message,
            intent,
            asset_type: asset.asset_type(),
            asset_id: asset.asset_id().as_str().to_string(),
            version_number: asset.version_number(),
        }
    }
}

impl std::fmt::Display for PolicyViolation {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "{}: {} (intent={:?} asset_type={:?} asset_id={} version={})",
            self.code,
            self.message,
            self.intent,
            self.asset_type,
            self.asset_id,
            self.version_number
        )
    }
}

impl std::error::Error for PolicyViolation {}

/// Core type-based policy enforcement.
///
/// This is the single authoritative place where
/// asset type × intent rules are defined.
pub fn evaluate_type_policy(intent: Intent, asset_type: AssetType) -> PolicyResult {
    match intent {
        // --------------------------------------------------
        // Fact lookup: only authoritative knowledge is valid
        // --------------------------------------------------
        Intent::FactLookup => match asset_type {
            AssetType::KnowledgeBase => {
                PolicyResult::allow("Knowledge Base assets are authoritative for fact lookup")
            }
            AssetType::Ledger => {
                PolicyResult::deny("Ledger assets are historical records, not factual authority")
            }
            AssetType::Persona => {
                PolicyResult::deny("Persona assets must never be used for factual answers")
            }
        },

        // --------------------------------------------------
        // Decision support: knowledge + history + persona
        // --------------------------------------------------
        Intent::DecisionSupport => match asset_type {
            AssetType::KnowledgeBase => {
                PolicyResult::allow("Knowledge Base assets provide authoritative guidance")
            }
            AssetType::Ledger => {
                PolicyResult::allow("Ledger assets provide accountable historical context")
            }
            AssetType::Persona => PolicyResult::allow_non_evidence(
                "Persona assets may influence presentation and prioritization only",
            ),
        },

        // --------------------------------------------------
        // Reflection / learning: broad but still governed
        // --------------------------------------------------
        Intent::Reflection => match asset_type {
            AssetType::KnowledgeBase => {
                PolicyResult::allow("Knowledge Base assets may be reviewed during reflection")
            }
            AssetType::Ledger => {
                PolicyResult::allow("Ledger assets are primary inputs for reflection and learning")
            }
            AssetType::Persona => PolicyResult::allow_non_evidence(
                "Persona assets may be examined, but never treated as evidence",
            ),
        },
    }
}

/// Higher-level check: can this specific asset instance participate in reasoning?
pub fn is_asset_allowed_for_intent<A: CognitiveAsset>(intent: Intent, asset: &A) -> PolicyResult {
    let base_result = evaluate_type_policy(intent, asset.asset_type());

    match base_result.decision {
        PolicyDecision::Allow => base_result,

        PolicyDecision::AllowNonEvidenceOnly => {
            if asset.can_be_evidence() {
                // Defensive check: should never happen if asset semantics are correct.
                PolicyResult::deny("Asset claims evidential capability but policy forbids it")
            } else {
                base_result
            }
        }

        PolicyDecision::Deny => base_result,
    }
}

/// Soft gate: can this asset be cited as evidence?
///
/// Returns a simple error string for "exclude from evidence list" behavior.
pub fn is_asset_allowed_as_evidence<A: CognitiveAsset>(
    intent: Intent,
    asset: &A,
) -> Result<(), &'static str> {
    let policy = evaluate_type_policy(intent, asset.asset_type());

    if policy.decision == PolicyDecision::Deny {
        return Err("Asset type is not allowed for this intent");
    }

    if !asset.can_be_evidence() {
        return Err("Asset is not permitted to act as evidence");
    }

    Ok(())
}

/// Hard gate: require that this asset is allowed as evidence.
///
/// Use this when a caller explicitly requests "use this as evidence".
/// If the request is illegal, return a structured PolicyViolation.
pub fn require_asset_allowed_as_evidence<A: CognitiveAsset>(
    intent: Intent,
    asset: &A,
) -> Result<(), PolicyViolation> {
    let policy = evaluate_type_policy(intent, asset.asset_type());

    if policy.decision == PolicyDecision::Deny {
        return Err(PolicyViolation::new(
            "ASSET_TYPE_DENIED_FOR_INTENT",
            "Asset type is denied for this intent",
            intent,
            asset,
        ));
    }

    if !asset.can_be_evidence() {
        // This is the key PoC safety property.
        // Persona and Ledger must never be cited as authoritative evidence.
        let code = match asset.asset_type() {
            AssetType::Persona => "PERSONA_AS_EVIDENCE",
            AssetType::Ledger => "LEDGER_AS_EVIDENCE",
            AssetType::KnowledgeBase => "NON_EVIDENCE_AS_EVIDENCE",
        };

        return Err(PolicyViolation::new(
            code,
            "Asset is not permitted to act as evidence",
            intent,
            asset,
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::core::asset::{AssetId, AssetVersion, Bitemporal};
    use std::time::{Duration, UNIX_EPOCH};

    fn mk_asset(asset_id: &str, asset_type: AssetType) -> AssetVersion {
        AssetVersion::new(
            AssetId::new(asset_id),
            asset_type,
            1,
            Bitemporal::new(
                UNIX_EPOCH + Duration::from_secs(10),
                UNIX_EPOCH + Duration::from_secs(10),
                None,
            ),
            None,
            "demo".to_string(),
        )
    }

    #[test]
    fn fact_lookup_denies_ledger_and_persona() {
        assert_eq!(
            evaluate_type_policy(Intent::FactLookup, AssetType::Ledger).decision,
            PolicyDecision::Deny
        );
        assert_eq!(
            evaluate_type_policy(Intent::FactLookup, AssetType::Persona).decision,
            PolicyDecision::Deny
        );
    }

    #[test]
    fn decision_support_allows_persona_non_evidence_only() {
        assert_eq!(
            evaluate_type_policy(Intent::DecisionSupport, AssetType::Persona).decision,
            PolicyDecision::AllowNonEvidenceOnly
        );
    }

    #[test]
    fn soft_evidence_gate_rejects_ledger_and_persona() {
        let ledger = mk_asset("ledger:one", AssetType::Ledger);
        let persona = mk_asset("persona:one", AssetType::Persona);

        assert!(is_asset_allowed_as_evidence(Intent::DecisionSupport, &ledger).is_err());
        assert!(is_asset_allowed_as_evidence(Intent::DecisionSupport, &persona).is_err());
    }

    #[test]
    fn hard_evidence_gate_returns_structured_codes() {
        let ledger = mk_asset("ledger:one", AssetType::Ledger);
        let persona = mk_asset("persona:one", AssetType::Persona);

        let ledger_err =
            require_asset_allowed_as_evidence(Intent::DecisionSupport, &ledger).unwrap_err();
        let persona_err =
            require_asset_allowed_as_evidence(Intent::DecisionSupport, &persona).unwrap_err();

        assert_eq!(ledger_err.code, "LEDGER_AS_EVIDENCE");
        assert_eq!(persona_err.code, "PERSONA_AS_EVIDENCE");
    }

    #[test]
    fn knowledge_base_is_allowed_as_evidence() {
        let kb = mk_asset("kb:one", AssetType::KnowledgeBase);
        assert!(is_asset_allowed_as_evidence(Intent::FactLookup, &kb).is_ok());
        assert!(require_asset_allowed_as_evidence(Intent::FactLookup, &kb).is_ok());
    }
}
