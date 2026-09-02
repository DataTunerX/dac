import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type AppendEventInput = {
  caseId: string;
  streamId?: string;
  eventType: string;
  actorId?: string;
  subjectId?: string;
  objectId?: string;
  payload: Record<string, unknown>;
  validTime: string;
  systemTime?: string;
};

export type EventRow = {
  event_id: string;
  case_id: string;
  event_seq: number;
  event_type: string;
  actor_id: string | null;
  subject_id: string | null;
  object_id: string | null;
  payload: Record<string, unknown>;
  valid_time: string;
  system_time: string;
};

export async function resolveCaseId(
  db: Queryable,
  input: { caseId?: string; streamId?: string }
): Promise<string> {
  if (input.caseId) {
    return input.caseId;
  }
  const row = await db.one(sql.typeAlias('record')`
    SELECT uuid_generate_v5(
      '6ba7b811-9dad-11d1-80b4-00c04fd430c8'::uuid,
      ${input.streamId ?? ''}::text
    )::text AS case_id
  `);
  return String((row as Record<string, unknown>).case_id);
}

export async function upsertCaseContext(
  db: Queryable,
  input: { caseId: string; streamId: string }
): Promise<boolean> {
  const row = await db.one(sql.typeAlias('record')`
    WITH upserted AS (
      INSERT INTO case_context (case_id, stream_id, updated_at)
      VALUES (${input.caseId}::uuid, ${input.streamId}, NOW())
      ON CONFLICT (case_id) DO UPDATE SET
        updated_at = NOW()
      WHERE case_context.stream_id = EXCLUDED.stream_id
      RETURNING case_id
    )
    SELECT EXISTS(SELECT 1 FROM upserted) AS applied
  `);

  return Boolean((row as Record<string, unknown>).applied);
}

export async function getCaseContextStreamId(
  db: Queryable,
  caseId: string
): Promise<string | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT stream_id
    FROM case_context
    WHERE case_id = ${caseId}::uuid
    LIMIT 1
  `);
  if (!row) {
    return undefined;
  }
  return (row as Record<string, unknown>).stream_id as string | undefined;
}

export async function allocateNextEventSeq(
  tx: DatabaseTransactionConnection,
  caseId: string
): Promise<number> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO case_seq (case_id, next_event_seq, updated_at)
    VALUES (${caseId}::uuid, 1, NOW())
    ON CONFLICT (case_id) DO UPDATE
      SET next_event_seq = case_seq.next_event_seq + 1,
          updated_at = NOW()
    RETURNING next_event_seq
  `);

  return Number((row as Record<string, unknown>).next_event_seq);
}

export async function insertEvent(
  tx: DatabaseTransactionConnection,
  input: AppendEventInput,
  eventSeq: number
): Promise<EventRow> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO case_event_ledger (
      case_id,
      event_seq,
      event_type,
      actor_id,
      subject_id,
      object_id,
      payload,
      valid_time,
      system_time
    ) VALUES (
      ${input.caseId}::uuid,
      ${eventSeq},
      ${input.eventType},
      ${input.actorId ?? null}::uuid,
      ${input.subjectId ?? null}::uuid,
      ${input.objectId ?? null}::uuid,
      ${JSON.stringify(input.payload)}::jsonb,
      ${input.validTime}::timestamptz,
      COALESCE(${input.systemTime ?? null}::timestamptz, NOW())
    )
    RETURNING
      event_id::text,
      case_id::text,
      event_seq,
      event_type,
      actor_id::text,
      subject_id::text,
      object_id::text,
      payload,
      valid_time::text,
      system_time::text
  `);

  return row as unknown as EventRow;
}

export type ReadEventsInput = {
  caseId: string;
  fromSeq?: number;
  toSeq?: number;
  limit: number;
};

export async function readEvents(db: Queryable, input: ReadEventsInput): Promise<EventRow[]> {
  const predicates = [sql.fragment`case_id = ${input.caseId}::uuid`];

  if (typeof input.fromSeq === 'number') {
    predicates.push(sql.fragment`event_seq >= ${input.fromSeq}`);
  }
  if (typeof input.toSeq === 'number') {
    predicates.push(sql.fragment`event_seq <= ${input.toSeq}`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      event_id::text,
      case_id::text,
      event_seq,
      event_type,
      actor_id::text,
      subject_id::text,
      object_id::text,
      payload,
      valid_time::text,
      system_time::text
    FROM case_event_ledger
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY event_seq ASC
    LIMIT ${input.limit}
  `);

  return rows as unknown as EventRow[];
}
