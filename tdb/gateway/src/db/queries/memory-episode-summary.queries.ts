import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type MemoryEpisodeSummaryRow = {
  episode_summary_id: string;
  episode_label?: string;
  task_id?: string;
  run_id?: string;
  session_id?: string;
  summary_text: string;
  outcomes: string[];
  key_facts: Array<Record<string, unknown>>;
  decisions: string[];
  unresolved_questions: string[];
  source_evidence: Array<Record<string, unknown>>;
  entity_ids: string[];
  confidence?: number;
  author: Record<string, unknown>;
  summary_timestamp: string;
  metadata: Record<string, unknown>;
  idempotency_key?: string;
  created_at: string;
};

type InsertInput = {
  episodeLabel?: string;
  taskId?: string;
  runId?: string;
  sessionId?: string;
  summaryText: string;
  outcomes: string[];
  keyFacts: Array<Record<string, unknown>>;
  decisions: string[];
  unresolvedQuestions: string[];
  sourceEvidence: Array<Record<string, unknown>>;
  entityIds: string[];
  confidence?: number;
  author: Record<string, unknown>;
  summaryTimestamp?: string;
  metadata: Record<string, unknown>;
  idempotencyKey?: string;
};

function mapRow(row: Record<string, unknown>): MemoryEpisodeSummaryRow {
  return {
    episode_summary_id: String(row.episode_summary_id),
    episode_label: typeof row.episode_label === 'string' ? row.episode_label : undefined,
    task_id: typeof row.task_id === 'string' ? row.task_id : undefined,
    run_id: typeof row.run_id === 'string' ? row.run_id : undefined,
    session_id: typeof row.session_id === 'string' ? row.session_id : undefined,
    summary_text: String(row.summary_text),
    outcomes: Array.isArray(row.outcomes) ? (row.outcomes as string[]) : [],
    key_facts: Array.isArray(row.key_facts) ? (row.key_facts as Array<Record<string, unknown>>) : [],
    decisions: Array.isArray(row.decisions) ? (row.decisions as string[]) : [],
    unresolved_questions: Array.isArray(row.unresolved_questions) ? (row.unresolved_questions as string[]) : [],
    source_evidence: Array.isArray(row.source_evidence) ? (row.source_evidence as Array<Record<string, unknown>>) : [],
    entity_ids: Array.isArray(row.entity_ids) ? (row.entity_ids as string[]) : [],
    confidence: typeof row.confidence === 'number' ? row.confidence : undefined,
    author: row.author && typeof row.author === 'object' ? (row.author as Record<string, unknown>) : {},
    summary_timestamp: String(row.summary_timestamp),
    metadata: row.metadata && typeof row.metadata === 'object' ? (row.metadata as Record<string, unknown>) : {},
    idempotency_key: typeof row.idempotency_key === 'string' ? row.idempotency_key : undefined,
    created_at: String(row.created_at),
  };
}

export async function findMemoryEpisodeSummaryByIdempotencyKey(
  db: Queryable,
  idempotencyKey: string,
): Promise<MemoryEpisodeSummaryRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      episode_summary_id::text,
      episode_label,
      task_id,
      run_id,
      session_id,
      summary_text,
      outcomes,
      key_facts,
      decisions,
      unresolved_questions,
      source_evidence,
      entity_ids,
      confidence,
      author,
      summary_timestamp::text,
      metadata,
      idempotency_key,
      created_at::text
    FROM memory_episode_summary
    WHERE idempotency_key = ${idempotencyKey}
    LIMIT 1
  `);

  return row ? mapRow(row as Record<string, unknown>) : undefined;
}

export async function insertMemoryEpisodeSummary(
  db: Queryable,
  input: InsertInput,
): Promise<MemoryEpisodeSummaryRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO memory_episode_summary (
      episode_label,
      task_id,
      run_id,
      session_id,
      summary_text,
      outcomes,
      key_facts,
      decisions,
      unresolved_questions,
      source_evidence,
      entity_ids,
      confidence,
      author,
      summary_timestamp,
      metadata,
      idempotency_key
    ) VALUES (
      ${input.episodeLabel ?? null},
      ${input.taskId ?? null},
      ${input.runId ?? null},
      ${input.sessionId ?? null},
      ${input.summaryText},
      ${JSON.stringify(input.outcomes)}::jsonb,
      ${JSON.stringify(input.keyFacts)}::jsonb,
      ${JSON.stringify(input.decisions)}::jsonb,
      ${JSON.stringify(input.unresolvedQuestions)}::jsonb,
      ${JSON.stringify(input.sourceEvidence)}::jsonb,
      ${JSON.stringify(input.entityIds)}::jsonb,
      ${input.confidence ?? null},
      ${JSON.stringify(input.author)}::jsonb,
      COALESCE(${input.summaryTimestamp ?? null}::timestamptz, NOW()),
      ${JSON.stringify(input.metadata)}::jsonb,
      ${input.idempotencyKey ?? null}
    )
    RETURNING
      episode_summary_id::text,
      episode_label,
      task_id,
      run_id,
      session_id,
      summary_text,
      outcomes,
      key_facts,
      decisions,
      unresolved_questions,
      source_evidence,
      entity_ids,
      confidence,
      author,
      summary_timestamp::text,
      metadata,
      idempotency_key,
      created_at::text
  `);

  return mapRow(row as Record<string, unknown>);
}

export async function listRecentMemoryEpisodeSummariesForTask(
  db: Queryable,
  input: {
    taskId: string;
    runId?: string;
    asOf?: string;
    limit: number;
  }
): Promise<MemoryEpisodeSummaryRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      episode_summary_id::text,
      episode_label,
      task_id,
      run_id,
      session_id,
      summary_text,
      outcomes,
      key_facts,
      decisions,
      unresolved_questions,
      source_evidence,
      entity_ids,
      confidence,
      author,
      summary_timestamp::text,
      metadata,
      idempotency_key,
      created_at::text
    FROM memory_episode_summary
    WHERE task_id = ${input.taskId}
      AND (${input.runId ?? null}::text IS NULL OR run_id = ${input.runId ?? null})
      AND (${input.asOf ?? null}::timestamptz IS NULL OR summary_timestamp <= ${input.asOf ?? null}::timestamptz)
    ORDER BY summary_timestamp DESC, created_at DESC
    LIMIT ${input.limit}
  `);

  return rows.map((row) => mapRow(row as Record<string, unknown>));
}
