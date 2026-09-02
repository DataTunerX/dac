import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type RuleRow = {
  rule_id: string;
  rule_key: string;
  rule_version: number;
  severity: string;
  expression: string;
  effective_from: string;
  effective_to: string | null;
  source_artifact_version_id: string | null;
  created_at: string;
};

export async function upsertRule(
  db: Queryable,
  input: {
    ruleKey: string;
    ruleVersion: number;
    severity: string;
    expression: string;
    effectiveFrom: string;
    effectiveTo?: string;
    sourceArtifactVersionId?: string;
  }
): Promise<RuleRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO rule_def (
      rule_key, rule_version, severity, expression, effective_from, effective_to, source_artifact_version_id
    ) VALUES (
      ${input.ruleKey}, ${input.ruleVersion}, ${input.severity}, ${input.expression},
      ${input.effectiveFrom}::timestamptz, ${input.effectiveTo ?? null}::timestamptz,
      ${input.sourceArtifactVersionId ?? null}::uuid
    )
    ON CONFLICT (rule_key, rule_version) DO UPDATE SET
      severity = EXCLUDED.severity,
      expression = EXCLUDED.expression,
      effective_from = EXCLUDED.effective_from,
      effective_to = EXCLUDED.effective_to,
      source_artifact_version_id = EXCLUDED.source_artifact_version_id
    RETURNING
      rule_id::text, rule_key, rule_version, severity, expression,
      effective_from::text, effective_to::text, source_artifact_version_id::text, created_at::text
  `);

  return row as unknown as RuleRow;
}

export type AuthorityGrantRow = {
  authority_grant_id: string;
  grantee_id: string;
  action_type: string;
  scope: Record<string, unknown>;
  valid_from: string;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  mandate_artifact_version_id: string | null;
  created_at: string;
};

export async function insertAuthorityGrant(
  db: Queryable,
  input: {
    granteeId: string;
    actionType: string;
    scope: Record<string, unknown>;
    validFrom: string;
    validTo?: string;
    systemFrom?: string;
    mandateArtifactVersionId?: string;
  }
): Promise<AuthorityGrantRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO authority_grant (
      grantee_id, action_type, scope, valid_from, valid_to, system_from, mandate_artifact_version_id
    ) VALUES (
      ${input.granteeId}::uuid,
      ${input.actionType},
      ${JSON.stringify(input.scope)}::jsonb,
      ${input.validFrom}::timestamptz,
      ${input.validTo ?? null}::timestamptz,
      COALESCE(${input.systemFrom ?? null}::timestamptz, NOW()),
      ${input.mandateArtifactVersionId ?? null}::uuid
    )
    RETURNING
      authority_grant_id::text,
      grantee_id::text,
      action_type,
      scope,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      mandate_artifact_version_id::text,
      created_at::text
  `);

  return row as unknown as AuthorityGrantRow;
}

export type RuleOverrideRow = {
  rule_override_id: string;
  rule_key: string;
  rule_version: number;
  authority_grant_id: string;
  justification_artifact_version_id: string | null;
  valid_from: string;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  case_id: string | null;
  event_id: string | null;
  created_at: string;
};

export async function insertRuleOverride(
  db: Queryable,
  input: {
    ruleKey: string;
    ruleVersion: number;
    authorityGrantId: string;
    justificationArtifactVersionId?: string;
    validFrom: string;
    validTo?: string;
    systemFrom?: string;
    caseId?: string;
    eventId?: string;
  }
): Promise<RuleOverrideRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO rule_override (
      rule_key, rule_version, authority_grant_id, justification_artifact_version_id,
      valid_from, valid_to, system_from, case_id, event_id
    ) VALUES (
      ${input.ruleKey},
      ${input.ruleVersion},
      ${input.authorityGrantId}::uuid,
      ${input.justificationArtifactVersionId ?? null}::uuid,
      ${input.validFrom}::timestamptz,
      ${input.validTo ?? null}::timestamptz,
      COALESCE(${input.systemFrom ?? null}::timestamptz, NOW()),
      ${input.caseId ?? null}::uuid,
      ${input.eventId ?? null}::uuid
    )
    RETURNING
      rule_override_id::text,
      rule_key,
      rule_version,
      authority_grant_id::text,
      justification_artifact_version_id::text,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      case_id::text,
      event_id::text,
      created_at::text
  `);

  return row as unknown as RuleOverrideRow;
}

export async function findAuthorityAsOf(
  db: Queryable,
  input: {
    granteeId: string;
    actionType: string;
    scope?: Record<string, unknown>;
    asOfValid: string;
    asOfSystem: string;
  }
): Promise<AuthorityGrantRow | undefined> {
  const predicates = [
    sql.fragment`grantee_id = ${input.granteeId}::uuid`,
    sql.fragment`action_type = ${input.actionType}`,
    sql.fragment`valid_from <= ${input.asOfValid}::timestamptz`,
    sql.fragment`(valid_to IS NULL OR valid_to > ${input.asOfValid}::timestamptz)`,
    sql.fragment`system_from <= ${input.asOfSystem}::timestamptz`,
    sql.fragment`(system_to IS NULL OR system_to > ${input.asOfSystem}::timestamptz)`
  ];
  if (input.scope) {
    predicates.push(sql.fragment`scope @> ${JSON.stringify(input.scope)}::jsonb`);
  }

  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      authority_grant_id::text,
      grantee_id::text,
      action_type,
      scope,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      mandate_artifact_version_id::text,
      created_at::text
    FROM authority_grant
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY valid_from DESC, system_from DESC, created_at DESC
    LIMIT 1
  `);

  return row ? (row as unknown as AuthorityGrantRow) : undefined;
}

export async function listRuleOverridesAsOf(
  db: Queryable,
  input: {
    ruleKey: string;
    ruleVersion?: number;
    asOfValid: string;
    asOfSystem: string;
  }
): Promise<RuleOverrideRow[]> {
  const predicates = [sql.fragment`rule_key = ${input.ruleKey}`];
  if (typeof input.ruleVersion === 'number') {
    predicates.push(sql.fragment`rule_version = ${input.ruleVersion}`);
  }
  predicates.push(sql.fragment`valid_from <= ${input.asOfValid}::timestamptz`);
  predicates.push(sql.fragment`(valid_to IS NULL OR valid_to > ${input.asOfValid}::timestamptz)`);
  predicates.push(sql.fragment`system_from <= ${input.asOfSystem}::timestamptz`);
  predicates.push(sql.fragment`(system_to IS NULL OR system_to > ${input.asOfSystem}::timestamptz)`);

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      rule_override_id::text,
      rule_key,
      rule_version,
      authority_grant_id::text,
      justification_artifact_version_id::text,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      case_id::text,
      event_id::text,
      created_at::text
    FROM rule_override
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY valid_from DESC, system_from DESC, created_at DESC
  `);

  return rows as unknown as RuleOverrideRow[];
}
