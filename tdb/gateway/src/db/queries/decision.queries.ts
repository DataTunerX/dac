import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type DecisionRow = {
  decision_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  chosen_action: string;
  candidates: Array<Record<string, unknown>>;
  scores: Record<string, number>;
  constraints_hit: string[];
  detail: Record<string, unknown>;
  created_at: string;
};

export async function upsertDecision(
  db: Queryable,
  input: {
    caseId: string;
    eventSeq: number;
    projectionVersion: string;
    chosenAction: string;
    candidates: Array<Record<string, unknown>>;
    scores: Record<string, number>;
    constraintsHit: string[];
    detail: Record<string, unknown>;
  }
): Promise<DecisionRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO decision_record (
      case_id, event_seq, projection_version, chosen_action, candidates, scores, constraints_hit, detail
    ) VALUES (
      ${input.caseId}::uuid,
      ${input.eventSeq},
      ${input.projectionVersion},
      ${input.chosenAction},
      ${JSON.stringify(input.candidates)}::jsonb,
      ${JSON.stringify(input.scores)}::jsonb,
      ${JSON.stringify(input.constraintsHit)}::jsonb,
      ${JSON.stringify(input.detail)}::jsonb
    )
    ON CONFLICT (case_id, event_seq, projection_version) DO UPDATE SET
      chosen_action = EXCLUDED.chosen_action,
      candidates = EXCLUDED.candidates,
      scores = EXCLUDED.scores,
      constraints_hit = EXCLUDED.constraints_hit,
      detail = EXCLUDED.detail
    RETURNING
      decision_id::text,
      case_id::text,
      event_seq,
      projection_version,
      chosen_action,
      candidates,
      scores,
      constraints_hit,
      detail,
      created_at::text
  `);

  return row as unknown as DecisionRow;
}

export type DecisionEvidenceRow = {
  decision_evidence_id: string;
  decision_id: string;
  artifact_version_id: string;
  citation: Record<string, unknown>;
  created_at: string;
};

export async function insertDecisionEvidence(
  db: Queryable,
  input: { decisionId: string; artifactVersionId: string; citation: Record<string, unknown> }
): Promise<DecisionEvidenceRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO decision_evidence (decision_id, artifact_version_id, citation)
    VALUES (
      ${input.decisionId}::uuid,
      ${input.artifactVersionId}::uuid,
      ${JSON.stringify(input.citation)}::jsonb
    )
    RETURNING
      decision_evidence_id::text,
      decision_id::text,
      artifact_version_id::text,
      citation,
      created_at::text
  `);

  return row as unknown as DecisionEvidenceRow;
}

export async function findDecision(
  db: Queryable,
  input: { caseId: string; eventSeq: number; projectionVersion: string }
): Promise<DecisionRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      decision_id::text,
      case_id::text,
      event_seq,
      projection_version,
      chosen_action,
      candidates,
      scores,
      constraints_hit,
      detail,
      created_at::text
    FROM decision_record
    WHERE case_id = ${input.caseId}::uuid
      AND event_seq = ${input.eventSeq}
      AND projection_version = ${input.projectionVersion}
    LIMIT 1
  `);

  return row ? (row as unknown as DecisionRow) : undefined;
}

export async function listDecisionEvidence(
  db: Queryable,
  decisionId: string
): Promise<DecisionEvidenceRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      decision_evidence_id::text,
      decision_id::text,
      artifact_version_id::text,
      citation,
      created_at::text
    FROM decision_evidence
    WHERE decision_id = ${decisionId}::uuid
    ORDER BY created_at ASC
  `);

  return rows as unknown as DecisionEvidenceRow[];
}
