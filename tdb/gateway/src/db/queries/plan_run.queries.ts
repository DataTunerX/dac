import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';

import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type PlanRunRow = {
  plan_id: string;
  execution_kind: 'execute' | 'dry_run' | 'replay';
  replay_of_plan_id: string | null;
  goal: string;
  execution_mode: 'safe' | 'best_effort';
  success: boolean;
  request_json: Record<string, unknown>;
  response_json: Record<string, unknown>;
  trace_json: unknown;
  started_at: string;
  finished_at: string;
  created_at: string;
};

export async function insertPlanRun(
  db: Queryable,
  input: {
    planId: string;
    executionKind: 'execute' | 'dry_run' | 'replay';
    replayOfPlanId?: string;
    goal?: string;
    executionMode: 'safe' | 'best_effort';
    success: boolean;
    requestJson: Record<string, unknown>;
    responseJson: Record<string, unknown>;
    traceJson: unknown[];
    startedAt: string;
    finishedAt: string;
  }
): Promise<void> {
  await db.query(sql.typeAlias('void')`
    INSERT INTO plan_run_ledger (
      plan_id,
      execution_kind,
      replay_of_plan_id,
      goal,
      execution_mode,
      success,
      request_json,
      response_json,
      trace_json,
      started_at,
      finished_at
    ) VALUES (
      ${input.planId}::uuid,
      ${input.executionKind},
      ${input.replayOfPlanId ?? null}::uuid,
      ${input.goal ?? ''},
      ${input.executionMode},
      ${input.success},
      ${JSON.stringify(input.requestJson)}::jsonb,
      ${JSON.stringify(input.responseJson)}::jsonb,
      ${JSON.stringify(input.traceJson)}::jsonb,
      ${input.startedAt}::timestamptz,
      ${input.finishedAt}::timestamptz
    )
  `);
}

export async function getPlanRun(db: Queryable, planId: string): Promise<PlanRunRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      plan_id::text,
      execution_kind,
      replay_of_plan_id::text,
      goal,
      execution_mode,
      success,
      request_json,
      response_json,
      trace_json,
      started_at::text,
      finished_at::text,
      created_at::text
    FROM plan_run_ledger
    WHERE plan_id = ${planId}::uuid
    LIMIT 1
  `);

  return row ? (row as unknown as PlanRunRow) : undefined;
}

export async function listPlanRuns(
  db: Queryable,
  input: {
    executionKind?: 'execute' | 'dry_run' | 'replay';
    success?: boolean;
    goalQuery?: string;
    replayOfPlanId?: string;
    limit: number;
  }
): Promise<PlanRunRow[]> {
  const predicates = [sql.fragment`TRUE`];
  if (input.executionKind) {
    predicates.push(sql.fragment`execution_kind = ${input.executionKind}`);
  }
  if (typeof input.success === 'boolean') {
    predicates.push(sql.fragment`success = ${input.success}`);
  }
  if (input.goalQuery) {
    predicates.push(sql.fragment`goal ILIKE ${`%${input.goalQuery}%`}`);
  }
  if (input.replayOfPlanId) {
    predicates.push(sql.fragment`replay_of_plan_id = ${input.replayOfPlanId}::uuid`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      plan_id::text,
      execution_kind,
      replay_of_plan_id::text,
      goal,
      execution_mode,
      success,
      request_json,
      response_json,
      trace_json,
      started_at::text,
      finished_at::text,
      created_at::text
    FROM plan_run_ledger
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY created_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as PlanRunRow[];
}
