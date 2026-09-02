import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type MemoryDecisionRow = {
  memory_decision_id: string;
  task_id: string;
  run_id?: string;
  decision_text: string;
  rationale_text: string;
  alternatives_considered: string[];
  source_evidence: Array<Record<string, unknown>>;
  entity_ids: string[];
  confidence?: number;
  author: Record<string, unknown>;
  decision_timestamp: string;
  consequences: string[];
  metadata: Record<string, unknown>;
  idempotency_key?: string;
  created_at: string;
};

type InsertInput = {
  taskId: string;
  runId?: string;
  decisionText: string;
  rationaleText: string;
  alternativesConsidered: string[];
  sourceEvidence: Array<Record<string, unknown>>;
  entityIds: string[];
  confidence?: number;
  author: Record<string, unknown>;
  decisionTimestamp?: string;
  consequences: string[];
  metadata: Record<string, unknown>;
  idempotencyKey?: string;
};

function mapRow(row: Record<string, unknown>): MemoryDecisionRow {
  return {
    memory_decision_id: String(row.memory_decision_id),
    task_id: String(row.task_id),
    run_id: typeof row.run_id === 'string' ? row.run_id : undefined,
    decision_text: String(row.decision_text),
    rationale_text: String(row.rationale_text),
    alternatives_considered: Array.isArray(row.alternatives_considered) ? (row.alternatives_considered as string[]) : [],
    source_evidence: Array.isArray(row.source_evidence) ? (row.source_evidence as Array<Record<string, unknown>>) : [],
    entity_ids: Array.isArray(row.entity_ids) ? (row.entity_ids as string[]) : [],
    confidence: typeof row.confidence === 'number' ? row.confidence : undefined,
    author: row.author && typeof row.author === 'object' ? (row.author as Record<string, unknown>) : {},
    decision_timestamp: String(row.decision_timestamp),
    consequences: Array.isArray(row.consequences) ? (row.consequences as string[]) : [],
    metadata: row.metadata && typeof row.metadata === 'object' ? (row.metadata as Record<string, unknown>) : {},
    idempotency_key: typeof row.idempotency_key === 'string' ? row.idempotency_key : undefined,
    created_at: String(row.created_at),
  };
}

export async function findMemoryDecisionByIdempotencyKey(db: Queryable, idempotencyKey: string): Promise<MemoryDecisionRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      memory_decision_id::text,
      task_id,
      run_id,
      decision_text,
      rationale_text,
      alternatives_considered,
      source_evidence,
      entity_ids,
      confidence,
      author,
      decision_timestamp::text,
      consequences,
      metadata,
      idempotency_key,
      created_at::text
    FROM memory_decision_record
    WHERE idempotency_key = ${idempotencyKey}
    LIMIT 1
  `);
  return row ? mapRow(row as Record<string, unknown>) : undefined;
}

export async function insertMemoryDecision(db: Queryable, input: InsertInput): Promise<MemoryDecisionRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO memory_decision_record (
      task_id,
      run_id,
      decision_text,
      rationale_text,
      alternatives_considered,
      source_evidence,
      entity_ids,
      confidence,
      author,
      decision_timestamp,
      consequences,
      metadata,
      idempotency_key
    ) VALUES (
      ${input.taskId},
      ${input.runId ?? null},
      ${input.decisionText},
      ${input.rationaleText},
      ${JSON.stringify(input.alternativesConsidered)}::jsonb,
      ${JSON.stringify(input.sourceEvidence)}::jsonb,
      ${JSON.stringify(input.entityIds)}::jsonb,
      ${input.confidence ?? null},
      ${JSON.stringify(input.author)}::jsonb,
      COALESCE(${input.decisionTimestamp ?? null}::timestamptz, NOW()),
      ${JSON.stringify(input.consequences)}::jsonb,
      ${JSON.stringify(input.metadata)}::jsonb,
      ${input.idempotencyKey ?? null}
    )
    RETURNING
      memory_decision_id::text,
      task_id,
      run_id,
      decision_text,
      rationale_text,
      alternatives_considered,
      source_evidence,
      entity_ids,
      confidence,
      author,
      decision_timestamp::text,
      consequences,
      metadata,
      idempotency_key,
      created_at::text
  `);

  return mapRow(row as Record<string, unknown>);
}

export async function listRecentMemoryDecisionsForEntity(
  db: Queryable,
  input: {
    entityIds: string[];
    asOf?: string;
    limit: number;
  }
): Promise<MemoryDecisionRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      memory_decision_id::text,
      task_id,
      run_id,
      decision_text,
      rationale_text,
      alternatives_considered,
      source_evidence,
      entity_ids,
      confidence,
      author,
      decision_timestamp::text,
      consequences,
      metadata,
      idempotency_key,
      created_at::text
    FROM memory_decision_record
    WHERE entity_ids ?| ${sql.array(input.entityIds, 'text')}
      AND (${input.asOf ?? null}::timestamptz IS NULL OR decision_timestamp <= ${input.asOf ?? null}::timestamptz)
    ORDER BY decision_timestamp DESC, created_at DESC
    LIMIT ${input.limit}
  `);

  return rows.map((row) => mapRow(row as Record<string, unknown>));
}

export async function listRecentMemoryDecisionsForTask(
  db: Queryable,
  input: {
    taskId: string;
    runId?: string;
    asOf?: string;
    limit: number;
  }
): Promise<MemoryDecisionRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      memory_decision_id::text,
      task_id,
      run_id,
      decision_text,
      rationale_text,
      alternatives_considered,
      source_evidence,
      entity_ids,
      confidence,
      author,
      decision_timestamp::text,
      consequences,
      metadata,
      idempotency_key,
      created_at::text
    FROM memory_decision_record
    WHERE task_id = ${input.taskId}
      AND (${input.runId ?? null}::text IS NULL OR run_id = ${input.runId ?? null})
      AND (${input.asOf ?? null}::timestamptz IS NULL OR decision_timestamp <= ${input.asOf ?? null}::timestamptz)
    ORDER BY decision_timestamp DESC, created_at DESC
    LIMIT ${input.limit}
  `);

  return rows.map((row) => mapRow(row as Record<string, unknown>));
}
