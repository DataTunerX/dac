import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type SnapshotRow = {
  snapshot_id: string;
  case_id: string;
  event_seq: number;
  projection_version: string;
  state_blob: Record<string, unknown>;
  state_hash: string | null;
  created_at: string;
};

export async function upsertProjectionVersion(
  db: Queryable,
  projectionVersion: string
): Promise<void> {
  await db.query(sql.typeAlias('void')`
    INSERT INTO projection_version (projection_version)
    VALUES (${projectionVersion})
    ON CONFLICT (projection_version) DO NOTHING
  `);
}

export async function upsertSnapshot(
  db: Queryable,
  input: {
    caseId: string;
    eventSeq: number;
    projectionVersion: string;
    stateBlob: Record<string, unknown>;
    stateHash?: string;
  }
): Promise<SnapshotRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO state_snapshot (
      case_id, event_seq, projection_version, state_blob, state_hash
    ) VALUES (
      ${input.caseId}::uuid,
      ${input.eventSeq},
      ${input.projectionVersion},
      ${JSON.stringify(input.stateBlob)}::jsonb,
      ${input.stateHash ?? null}
    )
    ON CONFLICT (case_id, event_seq, projection_version) DO UPDATE SET
      state_blob = EXCLUDED.state_blob,
      state_hash = EXCLUDED.state_hash
    RETURNING
      snapshot_id::text,
      case_id::text,
      event_seq,
      projection_version,
      state_blob,
      state_hash,
      created_at::text
  `);

  return row as unknown as SnapshotRow;
}

export async function findLatestSnapshot(
  db: Queryable,
  input: { caseId: string; projectionVersion: string; targetSeq: number }
): Promise<SnapshotRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      snapshot_id::text,
      case_id::text,
      event_seq,
      projection_version,
      state_blob,
      state_hash,
      created_at::text
    FROM state_snapshot
    WHERE case_id = ${input.caseId}::uuid
      AND projection_version = ${input.projectionVersion}
      AND event_seq <= ${input.targetSeq}
    ORDER BY event_seq DESC
    LIMIT 1
  `);

  return row ? (row as unknown as SnapshotRow) : undefined;
}
