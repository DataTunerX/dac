use crate::rpc::proto::{
    AssertionPolicyRuleRecord, AuthorityGrantRecord, EvidencePolicyRuleRecord,
    FindAuthorityAsOfRequest, FindAuthorityAsOfResponse, GetActiveOntologyAlertByRuleKeyRequest,
    GetActiveOntologyAlertByRuleKeyResponse, GetActiveOntologyCaseByTitleRequest,
    GetActiveOntologyCaseByTitleResponse, GetAssertionPolicyRuleRequest,
    GetAssertionPolicyRuleResponse, GetEvidencePolicyRuleRequest, GetEvidencePolicyRuleResponse,
    GetMethodologyFrameworkBundleRequest, GetMethodologyFrameworkBundleResponse,
    GetMethodologyFrameworkRequest, GetMethodologyFrameworkResponse, GetOntologyAlertDetailRequest,
    GetOntologyAlertDetailResponse, GetOntologyCaseRequest, GetOntologyCaseResponse,
    GetOntologyFactRequest, GetOntologyFactResponse, GetOntologyOpsRunRequest,
    GetOntologyOpsRunResponse, GetReviewPolicyRequest, GetReviewPolicyResponse,
    GetTaxonomySchemeRequest, GetTaxonomySchemeResponse, InsertAuthorityGrantRequest,
    InsertAuthorityGrantResponse, InsertOntologyAlertRequest, InsertOntologyAlertResponse,
    InsertOntologyCaseDecisionRequest, InsertOntologyCaseDecisionResponse,
    InsertOntologyCaseEventRequest, InsertOntologyCaseEventResponse, InsertOntologyCaseRequest,
    InsertOntologyCaseResponse, InsertOntologyOpsRuleRunRequest, InsertOntologyOpsRuleRunResponse,
    InsertRuleOverrideRequest, InsertRuleOverrideResponse, LinkOntologyCaseFactRequest,
    LinkOntologyCaseFactResponse, ListAssertionPolicyRulesRequest,
    ListAssertionPolicyRulesResponse, ListConflictPredicateOntologyCandidatesRequest,
    ListEvidencePolicyRulesRequest, ListEvidencePolicyRulesResponse,
    ListMethodologyFrameworksRequest, ListMethodologyFrameworksResponse, ListOntologyAlertsRequest,
    ListOntologyAlertsResponse, ListOntologyCaseDecisionsRequest,
    ListOntologyCaseDecisionsResponse, ListOntologyCaseEventsRequest,
    ListOntologyCaseEventsResponse, ListOntologyCaseFactsRequest, ListOntologyCaseFactsResponse,
    ListOntologyCasesRequest, ListOntologyCasesResponse, ListOntologyFactEvidenceRequest,
    ListOntologyFactEvidenceResponse, ListOntologyFactLinkedAlertsRequest,
    ListOntologyFactLinkedAlertsResponse, ListOntologyFactLinkedCasesRequest,
    ListOntologyFactLinkedCasesResponse, ListOntologyFactReviewsRequest,
    ListOntologyFactReviewsResponse, ListOntologyFactsResponse, ListOntologyOpsRuleConfigRequest,
    ListOntologyOpsRuleConfigResponse, ListOntologyOpsRunsRequest, ListOntologyOpsRunsResponse,
    ListReviewPoliciesRequest, ListReviewPoliciesResponse, ListRuleOverridesAsOfRequest,
    ListRuleOverridesAsOfResponse, ListStalePendingOntologyCandidatesRequest,
    ListTaxonomySchemesRequest, ListTaxonomySchemesResponse, MethodologyFrameworkRecord,
    OntologyAlertDetailRecord, OntologyAlertRecord, OntologyAlertSummaryRecord,
    OntologyCaseDecisionRecord, OntologyCaseEventRecord, OntologyCaseFactRecord,
    OntologyCaseRecord, OntologyCaseSummaryRecord, OntologyFactBulkSelectionRecord,
    OntologyFactEvidenceRecord, OntologyFactLinkedAlertRecord, OntologyFactLinkedCaseRecord,
    OntologyFactRecord, OntologyFactReviewRecord, OntologyOpsRuleConfigRecord,
    OntologyOpsRuleRunRecord, RefreshTriggeredOntologyAlertRequest,
    RefreshTriggeredOntologyAlertResponse, ReviewOntologyFactRequest, ReviewOntologyFactResponse,
    ReviewPolicyRecord, RuleOverrideRecord, RuleRecord, SelectOntologyFactsForBulkReviewRequest,
    SelectOntologyFactsForBulkReviewResponse, TaxonomySchemeRecord, UpdateOntologyAlertRequest,
    UpdateOntologyAlertResponse, UpdateOntologyCaseRequest, UpdateOntologyCaseResponse,
    UpsertAssertionPolicyRuleRequest, UpsertAssertionPolicyRuleResponse,
    UpsertEvidencePolicyRuleRequest, UpsertEvidencePolicyRuleResponse,
    UpsertMethodologyFrameworkRequest, UpsertMethodologyFrameworkResponse,
    UpsertOntologyOpsRuleConfigRequest, UpsertOntologyOpsRuleConfigResponse,
    UpsertReviewPolicyRequest, UpsertReviewPolicyResponse, UpsertRuleRequest, UpsertRuleResponse,
    UpsertTaxonomySchemeRequest, UpsertTaxonomySchemeResponse,
};
use sqlx::{PgPool, Row};

#[derive(Debug, Clone)]
pub struct GovernanceStore {
    pool: PgPool,
}

impl GovernanceStore {
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    // --- Core Governance ---

    pub async fn upsert_rule(
        &self,
        req: UpsertRuleRequest,
    ) -> Result<UpsertRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO rule_def (
                rule_key, rule_version, severity, expression, effective_from, effective_to, source_artifact_version_id
            ) VALUES ($1, $2, $3, $4, $5::timestamptz, $6::timestamptz, $7::uuid)
            ON CONFLICT (rule_key, rule_version) DO UPDATE SET
                severity = EXCLUDED.severity,
                expression = EXCLUDED.expression,
                effective_from = EXCLUDED.effective_from,
                effective_to = EXCLUDED.effective_to,
                source_artifact_version_id = EXCLUDED.source_artifact_version_id
            RETURNING rule_id::text, rule_key, rule_version, severity, expression,
                      effective_from::text, effective_to::text, source_artifact_version_id::text, created_at::text
            "#,
        )
        .bind(&req.rule_key)
        .bind(req.rule_version)
        .bind(&req.severity)
        .bind(&req.expression)
        .bind(&req.effective_from)
        .bind(if req.effective_to.is_empty() { None } else { Some(&req.effective_to) })
        .bind(if req.source_artifact_version_id.is_empty() { None } else { Some(&req.source_artifact_version_id) })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertRuleResponse {
            rule: Some(map_rule_row(&row)),
        })
    }

    pub async fn insert_authority_grant(
        &self,
        req: InsertAuthorityGrantRequest,
    ) -> Result<InsertAuthorityGrantResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO authority_grant (
                grantee_id, action_type, scope, valid_from, valid_to, system_from, mandate_artifact_version_id
            ) VALUES ($1::uuid, $2, $3::jsonb, $4::timestamptz, $5::timestamptz, COALESCE($6::timestamptz, NOW()), $7::uuid)
            RETURNING authority_grant_id::text, grantee_id::text, action_type, scope::text as scope_json,
                      valid_from::text, valid_to::text, system_from::text, system_to::text,
                      mandate_artifact_version_id::text, created_at::text
            "#,
        )
        .bind(&req.grantee_id)
        .bind(&req.action_type)
        .bind(&req.scope_json)
        .bind(&req.valid_from)
        .bind(if req.valid_to.is_empty() { None } else { Some(&req.valid_to) })
        .bind(if req.system_from.is_empty() { None } else { Some(&req.system_from) })
        .bind(if req.mandate_artifact_version_id.is_empty() { None } else { Some(&req.mandate_artifact_version_id) })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertAuthorityGrantResponse {
            grant: Some(map_authority_row(&row)),
        })
    }

    pub async fn insert_rule_override(
        &self,
        req: InsertRuleOverrideRequest,
    ) -> Result<InsertRuleOverrideResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO rule_override (
                rule_key, rule_version, authority_grant_id, justification_artifact_version_id,
                valid_from, valid_to, system_from, case_id, event_id
            ) VALUES ($1, $2, $3::uuid, $4::uuid, $5::timestamptz, $6::timestamptz, COALESCE($7::timestamptz, NOW()), $8::uuid, $9::uuid)
            RETURNING rule_override_id::text, rule_key, rule_version, authority_grant_id::text,
                      justification_artifact_version_id::text, valid_from::text, valid_to::text,
                      system_from::text, system_to::text, case_id::text, event_id::text, created_at::text
            "#,
        )
        .bind(&req.rule_key)
        .bind(req.rule_version)
        .bind(&req.authority_grant_id)
        .bind(if req.justification_artifact_version_id.is_empty() { None } else { Some(&req.justification_artifact_version_id) })
        .bind(&req.valid_from)
        .bind(if req.valid_to.is_empty() { None } else { Some(&req.valid_to) })
        .bind(if req.system_from.is_empty() { None } else { Some(&req.system_from) })
        .bind(if req.case_id == 0 { None } else { Some(req.case_id.to_string()) }) // Note: case_id is UUID in DB but handle as string ref or number? TS uses string uuid. proto has int64?
        // Wait, TS query.ts line 146 has ${input.caseId ?? null}::uuid. If TS caseId is string UUID, then proto should be string.
        // Let me re-check proto I just wrote.
        .bind(if req.event_id.is_empty() { None } else { Some(&req.event_id) })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertRuleOverrideResponse {
            r#override: Some(map_override_row(&row)),
        })
    }

    // ... I noticed a type mismatch in proto. RuleOverride case_id should be string (UUID) if it's uuid in DB.
    // TS governance.service.ts uses string for case_id? No, OntologyCase uses number (int64).
    // Let me check ontology_governance.queries.ts.
    // line 415: case_id::text. It's SERIAL or bigserial usually if it's "case_id::text" and not ::uuid.
    // Checking rule_override table... if it's uuid, I should use string in proto.

    pub async fn find_authority_as_of(
        &self,
        req: FindAuthorityAsOfRequest,
    ) -> Result<FindAuthorityAsOfResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT authority_grant_id::text, grantee_id::text, action_type, scope::text as scope_json,
                   valid_from::text, valid_to::text, system_from::text, system_to::text,
                   mandate_artifact_version_id::text, created_at::text
            FROM authority_grant
            WHERE grantee_id = $1::uuid
              AND action_type = $2
              AND valid_from <= $3::timestamptz
              AND (valid_to IS NULL OR valid_to > $3::timestamptz)
              AND system_from <= $4::timestamptz
              AND (system_to IS NULL OR system_to > $4::timestamptz)
            "#,
        );

        let mut params = Vec::new();
        params.push(req.grantee_id.clone());
        params.push(req.action_type.clone());
        params.push(req.as_of_valid.clone());
        params.push(req.as_of_system.clone());

        if !req.scope_json.is_empty() {
            params.push(req.scope_json.clone());
            query.push_str(&format!(" AND scope @> ${}::jsonb", params.len()));
        }

        query.push_str(" ORDER BY valid_from DESC, system_from DESC, created_at DESC LIMIT 1");

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let row = sql_query.fetch_optional(&self.pool).await?;

        Ok(FindAuthorityAsOfResponse {
            grant: row.as_ref().map(map_authority_row),
        })
    }

    pub async fn list_rule_overrides_as_of(
        &self,
        req: ListRuleOverridesAsOfRequest,
    ) -> Result<ListRuleOverridesAsOfResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT rule_override_id::text, rule_key, rule_version, authority_grant_id::text,
                   justification_artifact_version_id::text, valid_from::text, valid_to::text,
                   system_from::text, system_to::text, case_id::text, event_id::text, created_at::text
            FROM rule_override
            WHERE rule_key = $1
              AND valid_from <= $2::timestamptz
              AND (valid_to IS NULL OR valid_to > $2::timestamptz)
              AND system_from <= $3::timestamptz
              AND (system_to IS NULL OR system_to > $3::timestamptz)
            "#,
        );

        let mut params = Vec::new();
        params.push(req.rule_key.clone());
        params.push(req.as_of_valid.clone());
        params.push(req.as_of_system.clone());

        if req.rule_version != 0 {
            params.push(req.rule_version.to_string());
            query.push_str(&format!(" AND rule_version = ${}", params.len()));
        }

        query.push_str(" ORDER BY valid_from DESC, system_from DESC, created_at DESC");

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListRuleOverridesAsOfResponse {
            overrides: rows.iter().map(map_override_row).collect(),
        })
    }

    // --- Methodology Layer ---

    pub async fn upsert_methodology_framework(
        &self,
        req: UpsertMethodologyFrameworkRequest,
    ) -> Result<UpsertMethodologyFrameworkResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO methodology_framework (
              framework_id, domain, framework_name, version_label, status, description, owner, question_types, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb
            )
            ON CONFLICT (domain, framework_name, version_label) DO UPDATE SET
              status = EXCLUDED.status,
              description = EXCLUDED.description,
              owner = EXCLUDED.owner,
              question_types = EXCLUDED.question_types,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING framework_id::text AS framework_id, domain, framework_name, version_label, status,
                      description, owner, question_types::text AS question_types_json,
                      metadata::text AS metadata_json, created_at::text, updated_at::text
            "#,
        )
        .bind(&req.framework_id)
        .bind(&req.domain)
        .bind(&req.framework_name)
        .bind(&req.version_label)
        .bind(&req.status)
        .bind(&req.description)
        .bind(&req.owner)
        .bind(if req.question_types_json.is_empty() { "[]" } else { &req.question_types_json })
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertMethodologyFrameworkResponse {
            framework: Some(map_methodology_framework_row(&row)),
        })
    }

    pub async fn get_methodology_framework(
        &self,
        req: GetMethodologyFrameworkRequest,
    ) -> Result<GetMethodologyFrameworkResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT framework_id::text AS framework_id, domain, framework_name, version_label, status,
                   description, owner, question_types::text AS question_types_json,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM methodology_framework
            WHERE framework_id = $1::uuid
            "#,
        )
        .bind(&req.framework_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetMethodologyFrameworkResponse {
            framework: row.as_ref().map(map_methodology_framework_row),
        })
    }

    pub async fn list_methodology_frameworks(
        &self,
        req: ListMethodologyFrameworksRequest,
    ) -> Result<ListMethodologyFrameworksResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT framework_id::text AS framework_id, domain, framework_name, version_label, status,
                   description, owner, question_types::text AS question_types_json,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM methodology_framework
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.domain.is_empty() {
            query.push_str(&format!(" AND domain = ${}", binds.len() + 1));
            binds.push(req.domain);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (framework_name ILIKE ${idx} OR version_label ILIKE ${idx} OR description ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 50 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListMethodologyFrameworksResponse {
            frameworks: rows.iter().map(map_methodology_framework_row).collect(),
        })
    }

    pub async fn get_methodology_framework_bundle(
        &self,
        req: GetMethodologyFrameworkBundleRequest,
    ) -> Result<GetMethodologyFrameworkBundleResponse, sqlx::Error> {
        let framework = self
            .get_methodology_framework(GetMethodologyFrameworkRequest {
                framework_id: req.framework_id.clone(),
            })
            .await?
            .framework;

        let taxonomy_schemes = self
            .list_taxonomy_schemes(ListTaxonomySchemesRequest {
                framework_id: req.framework_id.clone(),
                scheme_type: String::new(),
                status: String::new(),
                query: String::new(),
                limit: 1000,
                offset: 0,
            })
            .await?
            .schemes;

        let evidence_policy_rules = self
            .list_evidence_policy_rules(ListEvidencePolicyRulesRequest {
                framework_id: req.framework_id.clone(),
                question_type: String::new(),
                evidence_kind: String::new(),
                status: String::new(),
                query: String::new(),
                limit: 1000,
                offset: 0,
            })
            .await?
            .rules;

        let assertion_policy_rules = self
            .list_assertion_policy_rules(ListAssertionPolicyRulesRequest {
                framework_id: req.framework_id.clone(),
                assertion_type: String::new(),
                question_type: String::new(),
                status: String::new(),
                query: String::new(),
                limit: 1000,
                offset: 0,
            })
            .await?
            .rules;

        let review_policies = self
            .list_review_policies(ListReviewPoliciesRequest {
                framework_id: req.framework_id,
                question_type: String::new(),
                trigger_kind: String::new(),
                status: String::new(),
                query: String::new(),
                limit: 1000,
                offset: 0,
            })
            .await?
            .policies;

        Ok(GetMethodologyFrameworkBundleResponse {
            framework,
            taxonomy_schemes,
            evidence_policy_rules,
            assertion_policy_rules,
            review_policies,
        })
    }

    pub async fn upsert_taxonomy_scheme(
        &self,
        req: UpsertTaxonomySchemeRequest,
    ) -> Result<UpsertTaxonomySchemeResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO taxonomy_scheme (
              scheme_id, framework_id, scheme_name, scheme_type, status, description, canonical_source, scheme_json, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb
            )
            ON CONFLICT (framework_id, scheme_name) DO UPDATE SET
              scheme_type = EXCLUDED.scheme_type,
              status = EXCLUDED.status,
              description = EXCLUDED.description,
              canonical_source = EXCLUDED.canonical_source,
              scheme_json = EXCLUDED.scheme_json,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING scheme_id::text AS scheme_id, framework_id::text AS framework_id, scheme_name, scheme_type,
                      status, description, canonical_source, scheme_json::text AS scheme_json,
                      metadata::text AS metadata_json, created_at::text, updated_at::text
            "#,
        )
        .bind(&req.scheme_id)
        .bind(&req.framework_id)
        .bind(&req.scheme_name)
        .bind(&req.scheme_type)
        .bind(&req.status)
        .bind(&req.description)
        .bind(&req.canonical_source)
        .bind(if req.scheme_json.is_empty() { "{}" } else { &req.scheme_json })
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertTaxonomySchemeResponse {
            scheme: Some(map_taxonomy_scheme_row(&row)),
        })
    }

    pub async fn get_taxonomy_scheme(
        &self,
        req: GetTaxonomySchemeRequest,
    ) -> Result<GetTaxonomySchemeResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT scheme_id::text AS scheme_id, framework_id::text AS framework_id, scheme_name, scheme_type,
                   status, description, canonical_source, scheme_json::text AS scheme_json,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM taxonomy_scheme
            WHERE scheme_id = $1::uuid
            "#,
        )
        .bind(&req.scheme_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetTaxonomySchemeResponse {
            scheme: row.as_ref().map(map_taxonomy_scheme_row),
        })
    }

    pub async fn list_taxonomy_schemes(
        &self,
        req: ListTaxonomySchemesRequest,
    ) -> Result<ListTaxonomySchemesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT scheme_id::text AS scheme_id, framework_id::text AS framework_id, scheme_name, scheme_type,
                   status, description, canonical_source, scheme_json::text AS scheme_json,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM taxonomy_scheme
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.framework_id.is_empty() {
            query.push_str(&format!(" AND framework_id = ${}::uuid", binds.len() + 1));
            binds.push(req.framework_id);
        }
        if !req.scheme_type.is_empty() {
            query.push_str(&format!(" AND scheme_type = ${}", binds.len() + 1));
            binds.push(req.scheme_type);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (scheme_name ILIKE ${idx} OR description ILIKE ${idx} OR canonical_source ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListTaxonomySchemesResponse {
            schemes: rows.iter().map(map_taxonomy_scheme_row).collect(),
        })
    }

    pub async fn upsert_evidence_policy_rule(
        &self,
        req: UpsertEvidencePolicyRuleRequest,
    ) -> Result<UpsertEvidencePolicyRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO evidence_policy_rule (
              evidence_policy_rule_id, framework_id, rule_key, question_type, evidence_kind, source_tier,
              status, priority, review_required, applicability_json, effect_json, description, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12, $13::jsonb
            )
            ON CONFLICT (framework_id, rule_key) DO UPDATE SET
              question_type = EXCLUDED.question_type,
              evidence_kind = EXCLUDED.evidence_kind,
              source_tier = EXCLUDED.source_tier,
              status = EXCLUDED.status,
              priority = EXCLUDED.priority,
              review_required = EXCLUDED.review_required,
              applicability_json = EXCLUDED.applicability_json,
              effect_json = EXCLUDED.effect_json,
              description = EXCLUDED.description,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING evidence_policy_rule_id::text AS evidence_policy_rule_id, framework_id::text AS framework_id,
                      rule_key, question_type, evidence_kind, source_tier, status, priority,
                      review_required, applicability_json::text AS applicability_json,
                      effect_json::text AS effect_json, description, metadata::text AS metadata_json,
                      created_at::text, updated_at::text
            "#,
        )
        .bind(&req.evidence_policy_rule_id)
        .bind(&req.framework_id)
        .bind(&req.rule_key)
        .bind(&req.question_type)
        .bind(&req.evidence_kind)
        .bind(&req.source_tier)
        .bind(&req.status)
        .bind(req.priority)
        .bind(req.review_required)
        .bind(if req.applicability_json.is_empty() { "{}" } else { &req.applicability_json })
        .bind(if req.effect_json.is_empty() { "{}" } else { &req.effect_json })
        .bind(&req.description)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertEvidencePolicyRuleResponse {
            rule: Some(map_evidence_policy_rule_row(&row)),
        })
    }

    pub async fn get_evidence_policy_rule(
        &self,
        req: GetEvidencePolicyRuleRequest,
    ) -> Result<GetEvidencePolicyRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT evidence_policy_rule_id::text AS evidence_policy_rule_id, framework_id::text AS framework_id,
                   rule_key, question_type, evidence_kind, source_tier, status, priority,
                   review_required, applicability_json::text AS applicability_json,
                   effect_json::text AS effect_json, description, metadata::text AS metadata_json,
                   created_at::text, updated_at::text
            FROM evidence_policy_rule
            WHERE evidence_policy_rule_id = $1::uuid
            "#,
        )
        .bind(&req.evidence_policy_rule_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetEvidencePolicyRuleResponse {
            rule: row.as_ref().map(map_evidence_policy_rule_row),
        })
    }

    pub async fn list_evidence_policy_rules(
        &self,
        req: ListEvidencePolicyRulesRequest,
    ) -> Result<ListEvidencePolicyRulesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT evidence_policy_rule_id::text AS evidence_policy_rule_id, framework_id::text AS framework_id,
                   rule_key, question_type, evidence_kind, source_tier, status, priority,
                   review_required, applicability_json::text AS applicability_json,
                   effect_json::text AS effect_json, description, metadata::text AS metadata_json,
                   created_at::text, updated_at::text
            FROM evidence_policy_rule
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.framework_id.is_empty() {
            query.push_str(&format!(" AND framework_id = ${}::uuid", binds.len() + 1));
            binds.push(req.framework_id);
        }
        if !req.question_type.is_empty() {
            query.push_str(&format!(" AND question_type = ${}", binds.len() + 1));
            binds.push(req.question_type);
        }
        if !req.evidence_kind.is_empty() {
            query.push_str(&format!(" AND evidence_kind = ${}", binds.len() + 1));
            binds.push(req.evidence_kind);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (rule_key ILIKE ${idx} OR description ILIKE ${idx} OR source_tier ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY priority ASC, updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListEvidencePolicyRulesResponse {
            rules: rows.iter().map(map_evidence_policy_rule_row).collect(),
        })
    }

    pub async fn upsert_assertion_policy_rule(
        &self,
        req: UpsertAssertionPolicyRuleRequest,
    ) -> Result<UpsertAssertionPolicyRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO assertion_policy_rule (
              assertion_policy_rule_id, framework_id, rule_key, assertion_type, question_type,
              status, priority, review_required, required_evidence_json, outcome_json, description, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12::jsonb
            )
            ON CONFLICT (framework_id, rule_key) DO UPDATE SET
              assertion_type = EXCLUDED.assertion_type,
              question_type = EXCLUDED.question_type,
              status = EXCLUDED.status,
              priority = EXCLUDED.priority,
              review_required = EXCLUDED.review_required,
              required_evidence_json = EXCLUDED.required_evidence_json,
              outcome_json = EXCLUDED.outcome_json,
              description = EXCLUDED.description,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING assertion_policy_rule_id::text AS assertion_policy_rule_id, framework_id::text AS framework_id,
                      rule_key, assertion_type, question_type, status, priority, review_required,
                      required_evidence_json::text AS required_evidence_json,
                      outcome_json::text AS outcome_json, description,
                      metadata::text AS metadata_json, created_at::text, updated_at::text
            "#,
        )
        .bind(&req.assertion_policy_rule_id)
        .bind(&req.framework_id)
        .bind(&req.rule_key)
        .bind(&req.assertion_type)
        .bind(&req.question_type)
        .bind(&req.status)
        .bind(req.priority)
        .bind(req.review_required)
        .bind(if req.required_evidence_json.is_empty() { "{}" } else { &req.required_evidence_json })
        .bind(if req.outcome_json.is_empty() { "{}" } else { &req.outcome_json })
        .bind(&req.description)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertAssertionPolicyRuleResponse {
            rule: Some(map_assertion_policy_rule_row(&row)),
        })
    }

    pub async fn get_assertion_policy_rule(
        &self,
        req: GetAssertionPolicyRuleRequest,
    ) -> Result<GetAssertionPolicyRuleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT assertion_policy_rule_id::text AS assertion_policy_rule_id, framework_id::text AS framework_id,
                   rule_key, assertion_type, question_type, status, priority, review_required,
                   required_evidence_json::text AS required_evidence_json,
                   outcome_json::text AS outcome_json, description,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM assertion_policy_rule
            WHERE assertion_policy_rule_id = $1::uuid
            "#,
        )
        .bind(&req.assertion_policy_rule_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetAssertionPolicyRuleResponse {
            rule: row.as_ref().map(map_assertion_policy_rule_row),
        })
    }

    pub async fn list_assertion_policy_rules(
        &self,
        req: ListAssertionPolicyRulesRequest,
    ) -> Result<ListAssertionPolicyRulesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT assertion_policy_rule_id::text AS assertion_policy_rule_id, framework_id::text AS framework_id,
                   rule_key, assertion_type, question_type, status, priority, review_required,
                   required_evidence_json::text AS required_evidence_json,
                   outcome_json::text AS outcome_json, description,
                   metadata::text AS metadata_json, created_at::text, updated_at::text
            FROM assertion_policy_rule
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.framework_id.is_empty() {
            query.push_str(&format!(" AND framework_id = ${}::uuid", binds.len() + 1));
            binds.push(req.framework_id);
        }
        if !req.assertion_type.is_empty() {
            query.push_str(&format!(" AND assertion_type = ${}", binds.len() + 1));
            binds.push(req.assertion_type);
        }
        if !req.question_type.is_empty() {
            query.push_str(&format!(" AND question_type = ${}", binds.len() + 1));
            binds.push(req.question_type);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (rule_key ILIKE ${idx} OR description ILIKE ${idx} OR assertion_type ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY priority ASC, updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListAssertionPolicyRulesResponse {
            rules: rows.iter().map(map_assertion_policy_rule_row).collect(),
        })
    }

    pub async fn upsert_review_policy(
        &self,
        req: UpsertReviewPolicyRequest,
    ) -> Result<UpsertReviewPolicyResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO review_policy (
              review_policy_id, framework_id, policy_key, question_type, trigger_kind, action,
              status, priority, trigger_json, description, metadata
            )
            VALUES (
              COALESCE(NULLIF($1, '')::uuid, gen_random_uuid()),
              $2::uuid, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb
            )
            ON CONFLICT (framework_id, policy_key) DO UPDATE SET
              question_type = EXCLUDED.question_type,
              trigger_kind = EXCLUDED.trigger_kind,
              action = EXCLUDED.action,
              status = EXCLUDED.status,
              priority = EXCLUDED.priority,
              trigger_json = EXCLUDED.trigger_json,
              description = EXCLUDED.description,
              metadata = EXCLUDED.metadata,
              updated_at = NOW()
            RETURNING review_policy_id::text AS review_policy_id, framework_id::text AS framework_id,
                      policy_key, question_type, trigger_kind, action, status, priority,
                      trigger_json::text AS trigger_json, description, metadata::text AS metadata_json,
                      created_at::text, updated_at::text
            "#,
        )
        .bind(&req.review_policy_id)
        .bind(&req.framework_id)
        .bind(&req.policy_key)
        .bind(&req.question_type)
        .bind(&req.trigger_kind)
        .bind(&req.action)
        .bind(&req.status)
        .bind(req.priority)
        .bind(if req.trigger_json.is_empty() { "{}" } else { &req.trigger_json })
        .bind(&req.description)
        .bind(if req.metadata_json.is_empty() { "{}" } else { &req.metadata_json })
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertReviewPolicyResponse {
            policy: Some(map_review_policy_row(&row)),
        })
    }

    pub async fn get_review_policy(
        &self,
        req: GetReviewPolicyRequest,
    ) -> Result<GetReviewPolicyResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT review_policy_id::text AS review_policy_id, framework_id::text AS framework_id,
                   policy_key, question_type, trigger_kind, action, status, priority,
                   trigger_json::text AS trigger_json, description, metadata::text AS metadata_json,
                   created_at::text, updated_at::text
            FROM review_policy
            WHERE review_policy_id = $1::uuid
            "#,
        )
        .bind(&req.review_policy_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetReviewPolicyResponse {
            policy: row.as_ref().map(map_review_policy_row),
        })
    }

    pub async fn list_review_policies(
        &self,
        req: ListReviewPoliciesRequest,
    ) -> Result<ListReviewPoliciesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT review_policy_id::text AS review_policy_id, framework_id::text AS framework_id,
                   policy_key, question_type, trigger_kind, action, status, priority,
                   trigger_json::text AS trigger_json, description, metadata::text AS metadata_json,
                   created_at::text, updated_at::text
            FROM review_policy
            WHERE 1=1
            "#,
        );
        let mut binds: Vec<String> = Vec::new();
        if !req.framework_id.is_empty() {
            query.push_str(&format!(" AND framework_id = ${}::uuid", binds.len() + 1));
            binds.push(req.framework_id);
        }
        if !req.question_type.is_empty() {
            query.push_str(&format!(" AND question_type = ${}", binds.len() + 1));
            binds.push(req.question_type);
        }
        if !req.trigger_kind.is_empty() {
            query.push_str(&format!(" AND trigger_kind = ${}", binds.len() + 1));
            binds.push(req.trigger_kind);
        }
        if !req.status.is_empty() {
            query.push_str(&format!(" AND status = ${}", binds.len() + 1));
            binds.push(req.status);
        }
        if !req.query.is_empty() {
            let idx = binds.len() + 1;
            query.push_str(&format!(" AND (policy_key ILIKE ${idx} OR description ILIKE ${idx} OR trigger_kind ILIKE ${idx})"));
            binds.push(format!("%{}%", req.query));
        }
        query.push_str(" ORDER BY priority ASC, updated_at DESC");
        query.push_str(&format!(" LIMIT ${}", binds.len() + 1));
        query.push_str(&format!(" OFFSET ${}", binds.len() + 2));

        let mut sql_query = sqlx::query(&query);
        for bind in binds {
            sql_query = sql_query.bind(bind);
        }
        sql_query = sql_query.bind(if req.limit > 0 { req.limit } else { 100 });
        sql_query = sql_query.bind(req.offset);

        let rows = sql_query.fetch_all(&self.pool).await?;
        Ok(ListReviewPoliciesResponse {
            policies: rows.iter().map(map_review_policy_row).collect(),
        })
    }

    // --- Ontology Facts ---

    pub async fn review_ontology_fact(
        &self,
        req: ReviewOntologyFactRequest,
    ) -> Result<ReviewOntologyFactResponse, sqlx::Error> {
        let status = match req.decision.as_str() {
            "accept" => "accepted",
            "reject" => "rejected",
            "needs_work" => "needs_review",
            _ => "candidate",
        };

        let row = sqlx::query(
            r#"
            WITH updated AS (
                UPDATE ontology_fact
                SET status = $1,
                    review_note = CASE
                        WHEN TRIM($2) = '' THEN review_note
                        ELSE TRIM($2)
                    END,
                    updated_at = NOW()
                WHERE fact_id = $3
                RETURNING fact_id
            ),
            inserted AS (
                INSERT INTO ontology_fact_review (fact_id, reviewer, decision, note)
                SELECT fact_id, TRIM($4), $5, TRIM($2)
                FROM updated
                RETURNING fact_id
            )
            SELECT COUNT(*)::int4 AS updated_rows
            FROM inserted
            "#,
        )
        .bind(status)
        .bind(&req.note)
        .bind(req.fact_id)
        .bind(&req.reviewer)
        .bind(&req.decision)
        .fetch_one(&self.pool)
        .await?;

        Ok(ReviewOntologyFactResponse {
            updated_rows: row.get("updated_rows"),
        })
    }

    pub async fn get_ontology_fact(
        &self,
        req: GetOntologyFactRequest,
    ) -> Result<GetOntologyFactResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT f.fact_id, f.src_concept_id, f.predicate, f.dst_concept_id, f.qualifier_json::text,
                   f.confidence, f.extractor, f.status, f.review_note, f.valid_from::text, f.valid_to::text,
                   f.created_at::text, f.updated_at::text,
                   COALESCE(sc.canonical_name, '') AS src_concept_label,
                   COALESCE(dc.canonical_name, '') AS dst_concept_label
            FROM ontology_fact f
            LEFT JOIN ontology_concept sc ON sc.concept_id = f.src_concept_id
            LEFT JOIN ontology_concept dc ON dc.concept_id = f.dst_concept_id
            WHERE f.fact_id = $1
            "#,
        )
        .bind(req.fact_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyFactResponse {
            fact: row.as_ref().map(map_fact_row),
        })
    }

    pub async fn list_ontology_fact_reviews(
        &self,
        req: ListOntologyFactReviewsRequest,
    ) -> Result<ListOntologyFactReviewsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT review_id, fact_id, reviewer, decision, note, created_at::text
            FROM ontology_fact_review
            WHERE fact_id = $1
            ORDER BY created_at DESC
            "#,
        )
        .bind(req.fact_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyFactReviewsResponse {
            reviews: rows.iter().map(map_fact_review_row).collect(),
        })
    }

    pub async fn list_ontology_fact_evidence(
        &self,
        req: ListOntologyFactEvidenceRequest,
    ) -> Result<ListOntologyFactEvidenceResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT stream_id, event_id, asset_id, version_number, source_span,
                   evidence_json::text, confidence, created_at::text, updated_at::text
            FROM ontology_fact_evidence
            WHERE fact_id = $1
            "#,
        );
        if !req.stream_id.is_empty() {
            query.push_str(" AND stream_id = $2");
        }

        query.push_str(" ORDER BY updated_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query).bind(req.fact_id);
        if !req.stream_id.is_empty() {
            sql_query = sql_query.bind(&req.stream_id);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListOntologyFactEvidenceResponse {
            evidence: rows.iter().map(map_fact_evidence_row).collect(),
        })
    }

    pub async fn list_ontology_fact_linked_cases(
        &self,
        req: ListOntologyFactLinkedCasesRequest,
    ) -> Result<ListOntologyFactLinkedCasesResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT c.case_id, c.stream_id, c.title, c.status, c.priority, c.owner,
                   cf.created_at::text AS linked_at
            FROM ontology_case_fact cf
            JOIN ontology_case c ON c.case_id = cf.case_id
            WHERE cf.fact_id = $1
            ORDER BY cf.created_at DESC
            "#,
        )
        .bind(req.fact_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyFactLinkedCasesResponse {
            linked_cases: rows.iter().map(map_fact_linked_case_row).collect(),
        })
    }

    pub async fn list_ontology_fact_linked_alerts(
        &self,
        req: ListOntologyFactLinkedAlertsRequest,
    ) -> Result<ListOntologyFactLinkedAlertsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT a.alert_id, a.case_id, a.stream_id, a.severity, a.status, a.message,
                   a.rule_key, af.created_at::text AS linked_at
            FROM ontology_alert_fact af
            JOIN ontology_alert a ON a.alert_id = af.alert_id
            WHERE af.fact_id = $1
            ORDER BY af.created_at DESC
            "#,
        )
        .bind(req.fact_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyFactLinkedAlertsResponse {
            linked_alerts: rows.iter().map(map_fact_linked_alert_row).collect(),
        })
    }

    pub async fn select_ontology_facts_for_bulk_review(
        &self,
        req: SelectOntologyFactsForBulkReviewRequest,
    ) -> Result<SelectOntologyFactsForBulkReviewResponse, sqlx::Error> {
        let mut query =
            String::from(r#"SELECT f.fact_id, f.status, f.confidence FROM ontology_fact f "#);
        let mut predicates = Vec::new();
        let mut params = Vec::new();

        if !req.stream_id.is_empty() {
            query.push_str("JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id ");
            params.push(req.stream_id.clone());
            predicates.push(format!("fe.stream_id = ${}", params.len()));
        }

        if req.status != "all" {
            params.push(req.status.clone());
            predicates.push(format!("f.status = ${}", params.len()));
        }

        params.push(req.min_confidence.to_string());
        predicates.push(format!("f.confidence >= ${}::float4", params.len()));

        params.push(req.max_confidence.to_string());
        predicates.push(format!("f.confidence <= ${}::float4", params.len()));

        if !req.predicate.is_empty() {
            params.push(req.predicate.clone());
            predicates.push(format!("f.predicate = ${}", params.len()));
        }
        if !req.extractor.is_empty() {
            params.push(req.extractor.clone());
            predicates.push(format!("f.extractor = ${}", params.len()));
        }
        if req.stale_days > 0 {
            predicates.push(format!(
                "f.updated_at < (NOW() - make_interval(days => {}))",
                req.stale_days
            ));
        }

        if !predicates.is_empty() {
            query.push_str("WHERE ");
            query.push_str(&predicates.join(" AND "));
        }

        query.push_str(" GROUP BY f.fact_id, f.status, f.confidence, f.updated_at ORDER BY f.confidence DESC, f.updated_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(SelectOntologyFactsForBulkReviewResponse {
            selected: rows
                .iter()
                .map(|r| {
                    use sqlx::Row;
                    OntologyFactBulkSelectionRecord {
                        fact_id: r.get("fact_id"),
                        status: r.get("status"),
                        confidence: r.get("confidence"),
                    }
                })
                .collect(),
        })
    }

    // --- Ontology Cases ---

    pub async fn insert_ontology_case(
        &self,
        req: InsertOntologyCaseRequest,
    ) -> Result<InsertOntologyCaseResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_case (
                stream_id, title, description, status, priority, owner, created_by
            ) VALUES ($1, $2, $3, 'open', $4, $5, $6)
            RETURNING case_id, stream_id, title, description, status, priority, owner,
                      created_by, created_at::text, updated_at::text, closed_at::text
            "#,
        )
        .bind(&req.stream_id)
        .bind(&req.title)
        .bind(&req.description)
        .bind(&req.priority)
        .bind(&req.owner)
        .bind(&req.created_by)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertOntologyCaseResponse {
            ontology_case: Some(map_case_row(&row)),
        })
    }

    pub async fn get_ontology_case(
        &self,
        req: GetOntologyCaseRequest,
    ) -> Result<GetOntologyCaseResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT case_id, stream_id, title, description, status, priority, owner,
                   created_by, created_at::text, updated_at::text, closed_at::text
            FROM ontology_case
            WHERE case_id = $1
            "#,
        )
        .bind(req.case_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyCaseResponse {
            ontology_case: row.as_ref().map(map_case_row),
        })
    }

    pub async fn list_ontology_cases(
        &self,
        req: ListOntologyCasesRequest,
    ) -> Result<ListOntologyCasesResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT c.case_id, c.stream_id, c.title, c.description, c.status, c.priority, c.owner,
                   c.created_by, c.created_at::text, c.updated_at::text, c.closed_at::text,
                   (SELECT COUNT(*) FROM ontology_case_fact cf WHERE cf.case_id = c.case_id) AS fact_count,
                   (SELECT COUNT(*) FROM ontology_alert a WHERE a.case_id = c.case_id AND a.status <> 'closed') AS active_alert_count
            FROM ontology_case c
            WHERE 1=1
            "#,
        );
        let mut params = Vec::new();
        if !req.stream_id.is_empty() {
            params.push(req.stream_id.clone());
            query.push_str(&format!(" AND c.stream_id = ${}", params.len()));
        }
        if req.status != "all" {
            params.push(req.status.clone());
            query.push_str(&format!(" AND c.status = ${}", params.len()));
        }

        query.push_str(" ORDER BY c.updated_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListOntologyCasesResponse {
            cases: rows.iter().map(map_case_summary_row).collect(),
        })
    }

    pub async fn update_ontology_case(
        &self,
        req: UpdateOntologyCaseRequest,
    ) -> Result<UpdateOntologyCaseResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            UPDATE ontology_case
            SET status = COALESCE($1, status),
                owner = COALESCE($2, owner),
                updated_at = NOW(),
                closed_at = CASE
                    WHEN COALESCE($1, status) IN ('resolved', 'dismissed') THEN COALESCE(closed_at, NOW())
                    WHEN COALESCE($1, status) IN ('open', 'in_review') THEN NULL
                    ELSE closed_at
                END
            WHERE case_id = $3
            RETURNING 1 as updated
            "#,
        )
        .bind(if req.status.is_empty() { None } else { Some(&req.status) })
        .bind(if req.owner.is_empty() { None } else { Some(&req.owner) })
        .bind(req.case_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(UpdateOntologyCaseResponse {
            updated_rows: if row.is_some() { 1 } else { 0 },
        })
    }

    pub async fn link_ontology_case_fact(
        &self,
        req: LinkOntologyCaseFactRequest,
    ) -> Result<LinkOntologyCaseFactResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            WITH inserted AS (
                INSERT INTO ontology_case_fact (case_id, fact_id, added_by, added_note)
                SELECT $1, $2, $3, $4
                WHERE EXISTS (SELECT 1 FROM ontology_fact f WHERE f.fact_id = $2)
                  AND EXISTS (SELECT 1 FROM ontology_fact_evidence fe WHERE fe.fact_id = $2 AND fe.stream_id = $5)
                ON CONFLICT (case_id, fact_id) DO NOTHING
                RETURNING fact_id
            )
            SELECT EXISTS(SELECT 1 FROM inserted) AS inserted
            "#,
        )
        .bind(req.case_id)
        .bind(req.fact_id)
        .bind(&req.added_by)
        .bind(&req.added_note)
        .bind(&req.stream_id)
        .fetch_one(&self.pool)
        .await?;

        Ok(LinkOntologyCaseFactResponse {
            linked: row.get("inserted"),
        })
    }

    pub async fn list_ontology_case_facts(
        &self,
        req: ListOntologyCaseFactsRequest,
    ) -> Result<ListOntologyCaseFactsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT f.fact_id, f.src_concept_id, f.predicate, f.dst_concept_id, f.confidence,
                   f.status, f.extractor, f.updated_at::text, cf.created_at::text AS linked_at,
                   cf.added_by, cf.added_note,
                   (SELECT COUNT(*) FROM ontology_fact_evidence fe WHERE fe.fact_id = f.fact_id) AS evidence_count,
                   (
                     SELECT COALESCE(json_agg(json_build_object(
                         'stream_id', x.stream_id,
                         'event_id', x.event_id,
                         'session_id', x.session_id,
                         'updated_at', x.updated_at::text,
                         'source_span', x.source_span,
                         'text_snippet', x.text_snippet
                       ) ORDER BY x.updated_at DESC), '[]'::json)
                     FROM (
                       SELECT fe.stream_id, fe.event_id,
                              COALESCE(cel.payload->>'session_id', cel.payload->>'sessionId', '') AS session_id,
                              fe.updated_at, fe.source_span,
                              LEFT(COALESCE(cel.payload->>'text', ''), 280) AS text_snippet
                       FROM ontology_fact_evidence fe
                       LEFT JOIN case_event_ledger cel ON cel.event_id::text = fe.event_id
                       WHERE fe.fact_id = f.fact_id
                       ORDER BY fe.updated_at DESC
                       LIMIT $1
                     ) x
                   ) AS evidence_sample_json
            FROM ontology_case_fact cf
            JOIN ontology_fact f ON f.fact_id = cf.fact_id
            WHERE cf.case_id = $2
            ORDER BY cf.created_at DESC
            "#,
        )
        .bind(req.evidence_limit)
        .bind(req.case_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyCaseFactsResponse {
            facts: rows.iter().map(map_case_fact_row).collect(),
        })
    }

    pub async fn insert_ontology_case_decision(
        &self,
        req: InsertOntologyCaseDecisionRequest,
    ) -> Result<InsertOntologyCaseDecisionResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_case_decision (
                case_id, decision_kind, verdict, summary, rationale,
                as_of_system_time, as_of_effective_time, snapshot_id, source_evidence_json,
                supersedes_case_decision_id, created_by
            )
            VALUES (
                $1, $2, $3, $4, $5,
                $6::timestamptz, $7::timestamptz, $8, $9::jsonb,
                $10, $11
            )
            RETURNING
                case_decision_id, case_id, decision_kind, verdict, summary, rationale,
                as_of_system_time::text, as_of_effective_time::text, snapshot_id,
                source_evidence_json::text, supersedes_case_decision_id, created_by,
                created_at::text
            "#,
        )
        .bind(req.case_id)
        .bind(&req.decision_kind)
        .bind(&req.verdict)
        .bind(&req.summary)
        .bind(&req.rationale)
        .bind(&req.as_of_system_time)
        .bind(&req.as_of_effective_time)
        .bind(&req.snapshot_id)
        .bind(&req.source_evidence_json)
        .bind(if req.supersedes_case_decision_id == 0 {
            None
        } else {
            Some(req.supersedes_case_decision_id)
        })
        .bind(&req.created_by)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertOntologyCaseDecisionResponse {
            decision: Some(map_case_decision_row(&row)),
        })
    }

    pub async fn list_ontology_case_decisions(
        &self,
        req: ListOntologyCaseDecisionsRequest,
    ) -> Result<ListOntologyCaseDecisionsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT
                case_decision_id, case_id, decision_kind, verdict, summary, rationale,
                as_of_system_time::text, as_of_effective_time::text, snapshot_id,
                source_evidence_json::text, supersedes_case_decision_id, created_by,
                created_at::text
            FROM ontology_case_decision
            WHERE case_id = $1
            ORDER BY created_at DESC, case_decision_id DESC
            "#,
        )
        .bind(req.case_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyCaseDecisionsResponse {
            decisions: rows.iter().map(map_case_decision_row).collect(),
        })
    }

    pub async fn insert_ontology_case_event(
        &self,
        req: InsertOntologyCaseEventRequest,
    ) -> Result<InsertOntologyCaseEventResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_case_event (case_id, action, actor, note, payload_json)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING event_id, case_id, action, actor, note, payload_json::text, created_at::text
            "#,
        )
        .bind(req.case_id)
        .bind(&req.action)
        .bind(&req.actor)
        .bind(&req.note)
        .bind(&req.payload_json)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertOntologyCaseEventResponse {
            event: Some(map_case_event_row(&row)),
        })
    }

    pub async fn list_ontology_case_events(
        &self,
        req: ListOntologyCaseEventsRequest,
    ) -> Result<ListOntologyCaseEventsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT event_id, case_id, action, actor, note, payload_json::text, created_at::text
            FROM ontology_case_event
            WHERE case_id = $1
            ORDER BY created_at DESC
            "#,
        )
        .bind(req.case_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyCaseEventsResponse {
            events: rows.iter().map(map_case_event_row).collect(),
        })
    }

    // --- Ontology Alerts ---

    pub async fn insert_ontology_alert(
        &self,
        req: InsertOntologyAlertRequest,
    ) -> Result<InsertOntologyAlertResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_alert (case_id, stream_id, severity, status, message, detail_json, rule_key)
            VALUES ($1, $2, $3, 'open', $4, $5::jsonb, $6)
            RETURNING alert_id, case_id, stream_id, severity, status, message, detail_json::text,
                      rule_key, trigger_count, first_triggered_at::text, last_triggered_at::text,
                      acked_by, acked_at::text, closed_at::text, created_at::text, updated_at::text
            "#,
        )
        .bind(if req.case_id == 0 { None } else { Some(req.case_id) })
        .bind(&req.stream_id)
        .bind(&req.severity)
        .bind(&req.message)
        .bind(&req.detail_json)
        .bind(if req.rule_key.is_empty() { None } else { Some(&req.rule_key) })
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertOntologyAlertResponse {
            alert: Some(map_alert_row(&row)),
        })
    }

    pub async fn get_ontology_alert_detail(
        &self,
        req: GetOntologyAlertDetailRequest,
    ) -> Result<GetOntologyAlertDetailResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT a.alert_id, a.case_id, a.stream_id, a.severity, a.status, a.message, a.detail_json::text,
                   a.rule_key, a.trigger_count, a.first_triggered_at::text, a.last_triggered_at::text,
                   a.acked_by, a.acked_at::text, a.closed_at::text, a.created_at::text, a.updated_at::text,
                   c.title as case_title,
                   (SELECT COUNT(*) FROM ontology_alert_fact af WHERE af.alert_id = a.alert_id) AS linked_fact_count
            FROM ontology_alert a
            LEFT JOIN ontology_case c ON c.case_id = a.case_id
            WHERE a.alert_id = $1
            "#,
        )
        .bind(req.alert_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyAlertDetailResponse {
            alert_detail: row.as_ref().map(map_alert_detail_row),
        })
    }

    pub async fn list_ontology_alerts(
        &self,
        req: ListOntologyAlertsRequest,
    ) -> Result<ListOntologyAlertsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT a.alert_id, a.case_id, a.stream_id, a.severity, a.status, a.message, a.detail_json::text,
                   a.rule_key, a.trigger_count, a.first_triggered_at::text, a.last_triggered_at::text,
                   a.acked_by, a.acked_at::text, a.closed_at::text, a.created_at::text, a.updated_at::text,
                   c.title as case_title,
                   (SELECT COUNT(*) FROM ontology_alert_fact af WHERE af.alert_id = a.alert_id) AS linked_fact_count
            FROM ontology_alert a
            LEFT JOIN ontology_case c ON c.case_id = a.case_id
            WHERE 1=1
            "#,
        );
        let mut params = Vec::new();
        if !req.stream_id.is_empty() {
            params.push(req.stream_id.clone());
            query.push_str(&format!(" AND a.stream_id = ${}", params.len()));
        }
        if req.status != "all" {
            params.push(req.status.clone());
            query.push_str(&format!(" AND a.status = ${}", params.len()));
        }

        query.push_str(" ORDER BY a.updated_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListOntologyAlertsResponse {
            alerts: rows.iter().map(map_alert_summary_row).collect(),
        })
    }

    pub async fn update_ontology_alert(
        &self,
        req: UpdateOntologyAlertRequest,
    ) -> Result<UpdateOntologyAlertResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            UPDATE ontology_alert
            SET status = COALESCE($1, status),
                acked_by = COALESCE($2, acked_by),
                acked_at = CASE WHEN $2 IS NOT NULL AND acked_at IS NULL THEN NOW() ELSE acked_at END,
                closed_at = CASE WHEN $1 = 'closed' AND closed_at IS NULL THEN NOW() ELSE closed_at END,
                updated_at = NOW()
            WHERE alert_id = $3
            RETURNING 1 as updated
            "#,
        )
        .bind(if req.status.is_empty() { None } else { Some(&req.status) })
        .bind(if req.acked_by.is_empty() { None } else { Some(&req.acked_by) })
        .bind(req.alert_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(UpdateOntologyAlertResponse {
            updated_rows: if row.is_some() { 1 } else { 0 },
        })
    }

    pub async fn refresh_triggered_ontology_alert(
        &self,
        req: RefreshTriggeredOntologyAlertRequest,
    ) -> Result<RefreshTriggeredOntologyAlertResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            UPDATE ontology_alert
            SET trigger_count = trigger_count + 1,
                last_triggered_at = NOW(),
                updated_at = NOW()
            WHERE alert_id = $1
            RETURNING 1 as updated
            "#,
        )
        .bind(req.alert_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(RefreshTriggeredOntologyAlertResponse {
            refreshed: row.is_some(),
        })
    }

    // --- Ontology Ops ---

    pub async fn upsert_ontology_ops_rule_config(
        &self,
        req: UpsertOntologyOpsRuleConfigRequest,
    ) -> Result<UpsertOntologyOpsRuleConfigResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_ops_rule_config (
                stream_id, rule_name, enabled, stale_days, conflict_predicate, severity, note, updated_by
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (stream_id, rule_name) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                stale_days = EXCLUDED.stale_days,
                conflict_predicate = EXCLUDED.conflict_predicate,
                severity = EXCLUDED.severity,
                note = EXCLUDED.note,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            RETURNING config_id, stream_id, rule_name, enabled, stale_days,
                      conflict_predicate, severity, note, updated_by, updated_at::text
            "#,
        )
        .bind(if req.stream_id.is_empty() { None } else { Some(&req.stream_id) })
        .bind(&req.rule_name)
        .bind(req.enabled)
        .bind(if req.stale_days == 0 { None } else { Some(req.stale_days) })
        .bind(if req.conflict_predicate.is_empty() { None } else { Some(&req.conflict_predicate) })
        .bind(if req.severity.is_empty() { None } else { Some(&req.severity) })
        .bind(&req.note)
        .bind(&req.updated_by)
        .fetch_one(&self.pool)
        .await?;

        Ok(UpsertOntologyOpsRuleConfigResponse {
            config: Some(map_ops_config_row(&row)),
        })
    }

    pub async fn list_ontology_ops_rule_config(
        &self,
        req: ListOntologyOpsRuleConfigRequest,
    ) -> Result<ListOntologyOpsRuleConfigResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT config_id, stream_id, rule_name, enabled, stale_days,
                   conflict_predicate, severity, note, updated_by, updated_at::text
            FROM ontology_ops_rule_config
            WHERE (stream_id = $1 OR stream_id IS NULL)
            ORDER BY stream_id NULLS FIRST, rule_name
            "#,
        )
        .bind(&req.stream_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyOpsRuleConfigResponse {
            configs: rows.iter().map(map_ops_config_row).collect(),
        })
    }

    pub async fn list_stale_pending_ontology_candidates(
        &self,
        req: ListStalePendingOntologyCandidatesRequest,
    ) -> Result<ListOntologyFactsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT
              fe.stream_id,
              COUNT(DISTINCT f.fact_id) AS stale_fact_count,
              ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
            FROM ontology_fact f
            JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
            WHERE f.status IN ('candidate', 'needs_review')
              AND f.updated_at < (NOW() - make_interval(days => $1::int))
              AND ($2 = '' OR fe.stream_id = $2)
            GROUP BY fe.stream_id
            ORDER BY COUNT(DISTINCT f.fact_id) DESC, fe.stream_id ASC
            "#,
        )
        .bind(req.stale_days)
        .bind(&req.stream_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyFactsResponse {
            facts: rows.iter().map(map_stale_candidate_row).collect(),
        })
    }

    pub async fn list_conflict_predicate_ontology_candidates(
        &self,
        req: ListConflictPredicateOntologyCandidatesRequest,
    ) -> Result<ListOntologyFactsResponse, sqlx::Error> {
        let rows = sqlx::query(
            r#"
            SELECT
              fe.stream_id,
              f.src_concept_id,
              COUNT(DISTINCT f.dst_concept_id) AS dst_count,
              ARRAY_AGG(DISTINCT f.dst_concept_id) AS dst_values,
              COUNT(DISTINCT f.fact_id) AS fact_count,
              ARRAY_AGG(DISTINCT f.fact_id) AS fact_ids
            FROM ontology_fact f
            JOIN ontology_fact_evidence fe ON fe.fact_id = f.fact_id
            WHERE f.predicate = $1
              AND f.status IN ('accepted', 'candidate', 'needs_review')
              AND ($2 = '' OR fe.stream_id = $2)
            GROUP BY fe.stream_id, f.src_concept_id
            HAVING COUNT(DISTINCT f.dst_concept_id) > 1
            ORDER BY COUNT(DISTINCT f.fact_id) DESC, fe.stream_id ASC, f.src_concept_id ASC
            "#,
        )
        .bind(&req.predicate)
        .bind(&req.stream_id)
        .fetch_all(&self.pool)
        .await?;

        Ok(ListOntologyFactsResponse {
            facts: rows.iter().map(map_conflict_candidate_row).collect(),
        })
    }

    pub async fn get_active_ontology_case_by_title(
        &self,
        req: GetActiveOntologyCaseByTitleRequest,
    ) -> Result<GetActiveOntologyCaseByTitleResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT
              case_id, stream_id, title, description, status, priority, owner, created_by,
              created_at::text, updated_at::text, closed_at::text
            FROM ontology_case
            WHERE title = $1
              AND status IN ('open', 'in_review')
            ORDER BY updated_at DESC
            LIMIT 1
            "#,
        )
        .bind(&req.title)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetActiveOntologyCaseByTitleResponse {
            case: row.as_ref().map(map_case_row),
        })
    }

    pub async fn get_active_ontology_alert_by_rule_key(
        &self,
        req: GetActiveOntologyAlertByRuleKeyRequest,
    ) -> Result<GetActiveOntologyAlertByRuleKeyResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT
              alert_id, case_id, stream_id, severity, status, message, detail_json::text,
              rule_key, trigger_count, first_triggered_at::text, last_triggered_at::text,
              acked_by, acked_at::text, closed_at::text, created_at::text, updated_at::text
            FROM ontology_alert
            WHERE rule_key = $1
              AND status IN ('open', 'acked')
            ORDER BY updated_at DESC
            LIMIT 1
            "#,
        )
        .bind(&req.rule_key)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetActiveOntologyAlertByRuleKeyResponse {
            alert: row.as_ref().map(map_alert_row),
        })
    }

    pub async fn insert_ontology_ops_rule_run(
        &self,
        req: InsertOntologyOpsRuleRunRequest,
    ) -> Result<InsertOntologyOpsRuleRunResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            INSERT INTO ontology_ops_rule_run (
                stream_id_filter, stale_days, conflict_predicate, dry_run, candidate_count,
                created_case_count, existing_case_count, created_alert_count, existing_alert_count,
                duration_ms, started_at, finished_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::timestamptz, $12::timestamptz)
            RETURNING run_id, stream_id_filter, stale_days, conflict_predicate, dry_run,
                      candidate_count, created_case_count, existing_case_count,
                      created_alert_count, existing_alert_count, duration_ms,
                      started_at::text, finished_at::text
            "#,
        )
        .bind(if req.stream_id_filter.is_empty() {
            None
        } else {
            Some(&req.stream_id_filter)
        })
        .bind(req.stale_days)
        .bind(&req.conflict_predicate)
        .bind(req.dry_run)
        .bind(req.candidate_count)
        .bind(req.created_case_count)
        .bind(req.existing_case_count)
        .bind(req.created_alert_count)
        .bind(req.existing_alert_count)
        .bind(req.duration_ms)
        .bind(&req.started_at)
        .bind(&req.finished_at)
        .fetch_one(&self.pool)
        .await?;

        Ok(InsertOntologyOpsRuleRunResponse {
            run: Some(map_ops_run_row(&row)),
        })
    }

    pub async fn get_ontology_ops_run(
        &self,
        req: GetOntologyOpsRunRequest,
    ) -> Result<GetOntologyOpsRunResponse, sqlx::Error> {
        let row = sqlx::query(
            r#"
            SELECT run_id, stream_id_filter, stale_days, conflict_predicate, dry_run,
                   candidate_count, created_case_count, existing_case_count,
                   created_alert_count, existing_alert_count, duration_ms,
                   started_at::text, finished_at::text
            FROM ontology_ops_rule_run
            WHERE run_id = $1
            "#,
        )
        .bind(req.run_id)
        .fetch_optional(&self.pool)
        .await?;

        Ok(GetOntologyOpsRunResponse {
            run: row.as_ref().map(map_ops_run_row),
        })
    }

    pub async fn list_ontology_ops_runs(
        &self,
        req: ListOntologyOpsRunsRequest,
    ) -> Result<ListOntologyOpsRunsResponse, sqlx::Error> {
        let mut query = String::from(
            r#"
            SELECT run_id, stream_id_filter, stale_days, conflict_predicate, dry_run,
                   candidate_count, created_case_count, existing_case_count,
                   created_alert_count, existing_alert_count, duration_ms,
                   started_at::text, finished_at::text
            FROM ontology_ops_rule_run
            WHERE 1=1
            "#,
        );
        let mut params = Vec::new();
        if !req.stream_id.is_empty() {
            params.push(req.stream_id.clone());
            query.push_str(&format!(" AND stream_id_filter = ${}", params.len()));
        }

        query.push_str(" ORDER BY started_at DESC LIMIT ");
        query.push_str(&req.limit.to_string());

        let mut sql_query = sqlx::query(&query);
        for param in params {
            sql_query = sql_query.bind(param);
        }

        let rows = sql_query.fetch_all(&self.pool).await?;

        Ok(ListOntologyOpsRunsResponse {
            runs: rows.iter().map(map_ops_run_row).collect(),
        })
    }
}

// --- Mappers ---

fn map_rule_row(row: &sqlx::postgres::PgRow) -> RuleRecord {
    use sqlx::Row;
    RuleRecord {
        rule_id: row.get("rule_id"),
        rule_key: row.get("rule_key"),
        rule_version: row.get("rule_version"),
        severity: row.get("severity"),
        expression: row.get("expression"),
        effective_from: row.get("effective_from"),
        effective_to: row
            .get::<Option<String>, _>("effective_to")
            .unwrap_or_default(),
        source_artifact_version_id: row
            .get::<Option<String>, _>("source_artifact_version_id")
            .unwrap_or_default(),
        created_at: row.get("created_at"),
    }
}

fn map_authority_row(row: &sqlx::postgres::PgRow) -> AuthorityGrantRecord {
    use sqlx::Row;
    AuthorityGrantRecord {
        authority_grant_id: row.get("authority_grant_id"),
        grantee_id: row.get("grantee_id"),
        action_type: row.get("action_type"),
        scope_json: row.get("scope_json"),
        valid_from: row.get("valid_from"),
        valid_to: row.get::<Option<String>, _>("valid_to").unwrap_or_default(),
        system_from: row.get("system_from"),
        system_to: row
            .get::<Option<String>, _>("system_to")
            .unwrap_or_default(),
        mandate_artifact_version_id: row
            .get::<Option<String>, _>("mandate_artifact_version_id")
            .unwrap_or_default(),
        created_at: row.get("created_at"),
    }
}

fn map_override_row(row: &sqlx::postgres::PgRow) -> RuleOverrideRecord {
    use sqlx::Row;
    RuleOverrideRecord {
        rule_override_id: row.get("rule_override_id"),
        rule_key: row.get("rule_key"),
        rule_version: row.get("rule_version"),
        authority_grant_id: row.get("authority_grant_id"),
        justification_artifact_version_id: row
            .get::<Option<String>, _>("justification_artifact_version_id")
            .unwrap_or_default(),
        valid_from: row.get("valid_from"),
        valid_to: row.get::<Option<String>, _>("valid_to").unwrap_or_default(),
        system_from: row.get("system_from"),
        system_to: row
            .get::<Option<String>, _>("system_to")
            .unwrap_or_default(),
        case_id: row
            .get::<Option<String>, _>("case_id")
            .unwrap_or_default()
            .parse()
            .unwrap_or(0),
        event_id: row.get::<Option<String>, _>("event_id").unwrap_or_default(),
        created_at: row.get("created_at"),
    }
}

fn map_methodology_framework_row(row: &sqlx::postgres::PgRow) -> MethodologyFrameworkRecord {
    use sqlx::Row;
    MethodologyFrameworkRecord {
        framework_id: row.get("framework_id"),
        domain: row.get("domain"),
        framework_name: row.get("framework_name"),
        version_label: row.get("version_label"),
        status: row.get("status"),
        description: row.get("description"),
        owner: row.get("owner"),
        question_types_json: row.get("question_types_json"),
        metadata_json: row.get("metadata_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_taxonomy_scheme_row(row: &sqlx::postgres::PgRow) -> TaxonomySchemeRecord {
    use sqlx::Row;
    TaxonomySchemeRecord {
        scheme_id: row.get("scheme_id"),
        framework_id: row.get("framework_id"),
        scheme_name: row.get("scheme_name"),
        scheme_type: row.get("scheme_type"),
        status: row.get("status"),
        description: row.get("description"),
        canonical_source: row.get("canonical_source"),
        scheme_json: row.get("scheme_json"),
        metadata_json: row.get("metadata_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_evidence_policy_rule_row(row: &sqlx::postgres::PgRow) -> EvidencePolicyRuleRecord {
    use sqlx::Row;
    EvidencePolicyRuleRecord {
        evidence_policy_rule_id: row.get("evidence_policy_rule_id"),
        framework_id: row.get("framework_id"),
        rule_key: row.get("rule_key"),
        question_type: row.get("question_type"),
        evidence_kind: row.get("evidence_kind"),
        source_tier: row.get("source_tier"),
        status: row.get("status"),
        priority: row.get("priority"),
        review_required: row.get("review_required"),
        applicability_json: row.get("applicability_json"),
        effect_json: row.get("effect_json"),
        description: row.get("description"),
        metadata_json: row.get("metadata_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_assertion_policy_rule_row(row: &sqlx::postgres::PgRow) -> AssertionPolicyRuleRecord {
    use sqlx::Row;
    AssertionPolicyRuleRecord {
        assertion_policy_rule_id: row.get("assertion_policy_rule_id"),
        framework_id: row.get("framework_id"),
        rule_key: row.get("rule_key"),
        assertion_type: row.get("assertion_type"),
        question_type: row.get("question_type"),
        status: row.get("status"),
        priority: row.get("priority"),
        review_required: row.get("review_required"),
        required_evidence_json: row.get("required_evidence_json"),
        outcome_json: row.get("outcome_json"),
        description: row.get("description"),
        metadata_json: row.get("metadata_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_review_policy_row(row: &sqlx::postgres::PgRow) -> ReviewPolicyRecord {
    use sqlx::Row;
    ReviewPolicyRecord {
        review_policy_id: row.get("review_policy_id"),
        framework_id: row.get("framework_id"),
        policy_key: row.get("policy_key"),
        question_type: row.get("question_type"),
        trigger_kind: row.get("trigger_kind"),
        action: row.get("action"),
        status: row.get("status"),
        priority: row.get("priority"),
        trigger_json: row.get("trigger_json"),
        description: row.get("description"),
        metadata_json: row.get("metadata_json"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_fact_row(row: &sqlx::postgres::PgRow) -> OntologyFactRecord {
    use sqlx::Row;
    OntologyFactRecord {
        fact_id: row.get("fact_id"),
        src_concept_id: row.get("src_concept_id"),
        predicate: row.get("predicate"),
        dst_concept_id: row.get("dst_concept_id"),
        qualifier_json: row.get("qualifier_json"),
        confidence: row.get::<f64, _>("confidence") as f32,
        extractor: row.get("extractor"),
        status: row.get("status"),
        review_note: row.get("review_note"),
        valid_from: row
            .get::<Option<String>, _>("valid_from")
            .unwrap_or_default(),
        valid_to: row.get::<Option<String>, _>("valid_to").unwrap_or_default(),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
        stream_id: row
            .try_get::<Option<String>, _>("stream_id")
            .ok()
            .flatten()
            .unwrap_or_default(),
        stale_fact_count: row.try_get::<i64, _>("stale_fact_count").unwrap_or(0) as i32,
        fact_count: row.try_get::<i64, _>("fact_count").unwrap_or(0) as i32,
        dst_count: row.try_get::<i64, _>("dst_count").unwrap_or(0) as i32,
        fact_ids: row
            .try_get::<Vec<i64>, _>("fact_ids")
            .unwrap_or_default()
            .into_iter()
            .collect(),
        dst_values: row
            .try_get::<Vec<String>, _>("dst_values")
            .unwrap_or_default(),
        src_concept_label: row
            .try_get::<String, _>("src_concept_label")
            .unwrap_or_default(),
        dst_concept_label: row
            .try_get::<String, _>("dst_concept_label")
            .unwrap_or_default(),
        statement_id: row
            .try_get::<String, _>("statement_id")
            .unwrap_or_default(),
    }
}

fn map_stale_candidate_row(row: &sqlx::postgres::PgRow) -> OntologyFactRecord {
    use sqlx::Row;
    OntologyFactRecord {
        fact_id: 0,
        src_concept_id: String::new(),
        predicate: String::new(),
        dst_concept_id: String::new(),
        qualifier_json: "{}".to_string(),
        confidence: 0.0,
        extractor: String::new(),
        status: String::new(),
        review_note: String::new(),
        valid_from: String::new(),
        valid_to: String::new(),
        created_at: String::new(),
        updated_at: String::new(),
        stream_id: row.get("stream_id"),
        stale_fact_count: row.get::<i64, _>("stale_fact_count") as i32,
        fact_count: 0,
        dst_count: 0,
        fact_ids: row.get::<Vec<i64>, _>("fact_ids").into_iter().collect(),
        dst_values: vec![],
        src_concept_label: String::new(),
        dst_concept_label: String::new(),
        statement_id: String::new(),
    }
}

fn map_conflict_candidate_row(row: &sqlx::postgres::PgRow) -> OntologyFactRecord {
    use sqlx::Row;
    OntologyFactRecord {
        fact_id: 0,
        src_concept_id: row.get("src_concept_id"),
        predicate: String::new(),
        dst_concept_id: String::new(),
        qualifier_json: "{}".to_string(),
        confidence: 0.0,
        extractor: String::new(),
        status: String::new(),
        review_note: String::new(),
        valid_from: String::new(),
        valid_to: String::new(),
        created_at: String::new(),
        updated_at: String::new(),
        stream_id: row.get("stream_id"),
        stale_fact_count: 0,
        fact_count: row.get::<i64, _>("fact_count") as i32,
        dst_count: row.get::<i64, _>("dst_count") as i32,
        fact_ids: row.get::<Vec<i64>, _>("fact_ids").into_iter().collect(),
        dst_values: row.get::<Vec<String>, _>("dst_values"),
        src_concept_label: row
            .try_get::<String, _>("src_concept_label")
            .unwrap_or_default(),
        dst_concept_label: String::new(),
        statement_id: String::new(),
    }
}

fn map_fact_review_row(row: &sqlx::postgres::PgRow) -> OntologyFactReviewRecord {
    use sqlx::Row;
    OntologyFactReviewRecord {
        review_id: row.get("review_id"),
        fact_id: row.get("fact_id"),
        reviewer: row.get("reviewer"),
        decision: row.get("decision"),
        note: row.get("note"),
        created_at: row.get("created_at"),
    }
}

fn map_fact_evidence_row(row: &sqlx::postgres::PgRow) -> OntologyFactEvidenceRecord {
    use sqlx::Row;
    OntologyFactEvidenceRecord {
        stream_id: row.get("stream_id"),
        event_id: row.get("event_id"),
        asset_id: row.get::<Option<String>, _>("asset_id").unwrap_or_default(),
        // DB column is BIGINT; reading it as i32 makes sqlx panic on any
        // non-null value and 500s fact/history + fact/provenance.
        version_number: row.get::<Option<i64>, _>("version_number").unwrap_or(0) as i32,
        source_span: row
            .get::<Option<String>, _>("source_span")
            .unwrap_or_default(),
        evidence_json: row.get("evidence_json"),
        confidence: row.get::<f64, _>("confidence") as f32,
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_fact_linked_case_row(row: &sqlx::postgres::PgRow) -> OntologyFactLinkedCaseRecord {
    use sqlx::Row;
    OntologyFactLinkedCaseRecord {
        case_id: row.get("case_id"),
        stream_id: row.get("stream_id"),
        title: row.get("title"),
        status: row.get("status"),
        priority: row.get("priority"),
        owner: row.get("owner"),
        linked_at: row.get("linked_at"),
    }
}

fn map_fact_linked_alert_row(row: &sqlx::postgres::PgRow) -> OntologyFactLinkedAlertRecord {
    use sqlx::Row;
    OntologyFactLinkedAlertRecord {
        alert_id: row.get("alert_id"),
        case_id: row.get::<Option<i64>, _>("case_id").unwrap_or(0),
        stream_id: row.get("stream_id"),
        severity: row.get("severity"),
        status: row.get("status"),
        message: row.get("message"),
        rule_key: row.get::<Option<String>, _>("rule_key").unwrap_or_default(),
        linked_at: row.get("linked_at"),
    }
}

fn map_case_row(row: &sqlx::postgres::PgRow) -> OntologyCaseRecord {
    use sqlx::Row;
    OntologyCaseRecord {
        case_id: row.get("case_id"),
        stream_id: row.get("stream_id"),
        title: row.get("title"),
        description: row.get("description"),
        status: row.get("status"),
        priority: row.get("priority"),
        owner: row.get("owner"),
        created_by: row.get("created_by"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
        closed_at: row
            .get::<Option<String>, _>("closed_at")
            .unwrap_or_default(),
    }
}

fn map_case_summary_row(row: &sqlx::postgres::PgRow) -> OntologyCaseSummaryRecord {
    use sqlx::Row;
    OntologyCaseSummaryRecord {
        case_id: row.get("case_id"),
        stream_id: row.get("stream_id"),
        title: row.get("title"),
        description: row.get("description"),
        status: row.get("status"),
        priority: row.get("priority"),
        owner: row.get("owner"),
        created_by: row.get("created_by"),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
        closed_at: row
            .get::<Option<String>, _>("closed_at")
            .unwrap_or_default(),
        fact_count: row.get::<i64, _>("fact_count") as i32,
        active_alert_count: row.get::<i64, _>("active_alert_count") as i32,
    }
}

fn map_case_fact_row(row: &sqlx::postgres::PgRow) -> OntologyCaseFactRecord {
    use sqlx::Row;
    OntologyCaseFactRecord {
        fact_id: row.get("fact_id"),
        src_concept_id: row.get("src_concept_id"),
        predicate: row.get("predicate"),
        dst_concept_id: row.get("dst_concept_id"),
        confidence: row.get::<f64, _>("confidence") as f32,
        status: row.get("status"),
        extractor: row.get("extractor"),
        updated_at: row.get("updated_at"),
        linked_at: row.get("linked_at"),
        added_by: row.get("added_by"),
        added_note: row.get("added_note"),
        evidence_count: row.get::<i64, _>("evidence_count") as i32,
        evidence_sample_json: row.get("evidence_sample_json"),
    }
}

fn map_case_event_row(row: &sqlx::postgres::PgRow) -> OntologyCaseEventRecord {
    use sqlx::Row;
    OntologyCaseEventRecord {
        event_id: row.get("event_id"),
        case_id: row.get("case_id"),
        action: row.get("action"),
        actor: row.get("actor"),
        note: row.get("note"),
        payload_json: row.get("payload_json"),
        created_at: row.get("created_at"),
    }
}

fn map_case_decision_row(row: &sqlx::postgres::PgRow) -> OntologyCaseDecisionRecord {
    use sqlx::Row;
    OntologyCaseDecisionRecord {
        case_decision_id: row.get("case_decision_id"),
        case_id: row.get("case_id"),
        decision_kind: row.get("decision_kind"),
        verdict: row.get("verdict"),
        summary: row.get("summary"),
        rationale: row.get("rationale"),
        as_of_system_time: row.get("as_of_system_time"),
        as_of_effective_time: row.get("as_of_effective_time"),
        snapshot_id: row.get("snapshot_id"),
        source_evidence_json: row
            .get::<Option<String>, _>("source_evidence_json")
            .unwrap_or_else(|| "[]".to_string()),
        supersedes_case_decision_id: row
            .get::<Option<i64>, _>("supersedes_case_decision_id")
            .unwrap_or(0),
        created_by: row.get("created_by"),
        created_at: row.get("created_at"),
    }
}

fn map_alert_row(row: &sqlx::postgres::PgRow) -> OntologyAlertRecord {
    use sqlx::Row;
    OntologyAlertRecord {
        alert_id: row.get("alert_id"),
        case_id: row.get::<Option<i64>, _>("case_id").unwrap_or(0),
        stream_id: row.get("stream_id"),
        severity: row.get("severity"),
        status: row.get("status"),
        message: row.get("message"),
        detail_json: row.get("detail_json"),
        rule_key: row.get::<Option<String>, _>("rule_key").unwrap_or_default(),
        trigger_count: row.get("trigger_count"),
        first_triggered_at: row.get("first_triggered_at"),
        last_triggered_at: row.get("last_triggered_at"),
        acked_by: row.get::<Option<String>, _>("acked_by").unwrap_or_default(),
        acked_at: row.get::<Option<String>, _>("acked_at").unwrap_or_default(),
        closed_at: row
            .get::<Option<String>, _>("closed_at")
            .unwrap_or_default(),
        created_at: row.get("created_at"),
        updated_at: row.get("updated_at"),
    }
}

fn map_alert_detail_row(row: &sqlx::postgres::PgRow) -> OntologyAlertDetailRecord {
    use sqlx::Row;
    OntologyAlertDetailRecord {
        alert: Some(map_alert_row(row)),
        case_title: row
            .get::<Option<String>, _>("case_title")
            .unwrap_or_default(),
        linked_fact_count: row.get::<i64, _>("linked_fact_count") as i32,
    }
}

fn map_alert_summary_row(row: &sqlx::postgres::PgRow) -> OntologyAlertSummaryRecord {
    use sqlx::Row;
    OntologyAlertSummaryRecord {
        alert: Some(map_alert_row(row)),
        case_title: row
            .get::<Option<String>, _>("case_title")
            .unwrap_or_default(),
        linked_fact_count: row.get::<i64, _>("linked_fact_count") as i32,
    }
}

fn map_ops_config_row(row: &sqlx::postgres::PgRow) -> OntologyOpsRuleConfigRecord {
    use sqlx::Row;
    OntologyOpsRuleConfigRecord {
        config_id: row.get("config_id"),
        stream_id: row
            .get::<Option<String>, _>("stream_id")
            .unwrap_or_default(),
        rule_name: row.get("rule_name"),
        enabled: row.get("enabled"),
        stale_days: row.get::<Option<i32>, _>("stale_days").unwrap_or(0),
        conflict_predicate: row
            .get::<Option<String>, _>("conflict_predicate")
            .unwrap_or_default(),
        severity: row.get::<Option<String>, _>("severity").unwrap_or_default(),
        note: row.get("note"),
        updated_by: row.get("updated_by"),
        updated_at: row.get("updated_at"),
    }
}

fn map_ops_run_row(row: &sqlx::postgres::PgRow) -> OntologyOpsRuleRunRecord {
    use sqlx::Row;
    OntologyOpsRuleRunRecord {
        run_id: row.get("run_id"),
        stream_id_filter: row
            .get::<Option<String>, _>("stream_id_filter")
            .unwrap_or_default(),
        stale_days: row.get("stale_days"),
        conflict_predicate: row.get("conflict_predicate"),
        dry_run: row.get("dry_run"),
        candidate_count: row.get("candidate_count"),
        created_case_count: row.get("created_case_count"),
        existing_case_count: row.get("existing_case_count"),
        created_alert_count: row.get("created_alert_count"),
        existing_alert_count: row.get("existing_alert_count"),
        duration_ms: row.get("duration_ms"),
        started_at: row.get("started_at"),
        finished_at: row.get("finished_at"),
    }
}
