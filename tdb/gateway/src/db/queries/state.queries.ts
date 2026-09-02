import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type PropertyUpsertInput = {
  objectId: string;
  key: string;
  value: Record<string, unknown>;
  validFrom: string;
  systemFrom?: string;
  sourceEventId?: string;
  confidence?: number;
};

export type PropertyRow = {
  property_state_id: string;
  object_id: string;
  prop_key: string;
  prop_value: Record<string, unknown>;
  valid_from: string;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  source_event_id: string | null;
  confidence: number | null;
};

export async function closeOpenPropertyIntervals(
  tx: DatabaseTransactionConnection,
  input: PropertyUpsertInput,
  effectiveSystemFrom: string
): Promise<void> {
  await tx.query(sql.typeAlias('void')`
    UPDATE property_state
    SET valid_to = CASE
          WHEN valid_from < ${input.validFrom}::timestamptz
          THEN ${input.validFrom}::timestamptz
          ELSE valid_to
        END,
        system_to = ${effectiveSystemFrom}::timestamptz
    WHERE object_id = ${input.objectId}::uuid
      AND prop_key = ${input.key}
      AND valid_to IS NULL
      AND system_to IS NULL
  `);
}

export async function getLatestOpenPropertySystemFrom(
  tx: DatabaseTransactionConnection,
  input: { objectId: string; key: string }
): Promise<string | undefined> {
  const row = await tx.maybeOne(sql.typeAlias('record')`
    SELECT MAX(system_from)::text AS system_from
    FROM property_state
    WHERE object_id = ${input.objectId}::uuid
      AND prop_key = ${input.key}
      AND system_to IS NULL
  `);
  const value = (row as { system_from?: string | null } | null)?.system_from;
  return value ?? undefined;
}

export async function insertPropertyState(
  tx: DatabaseTransactionConnection,
  input: PropertyUpsertInput,
  effectiveSystemFrom: string
): Promise<PropertyRow> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO property_state (
      object_id,
      prop_key,
      prop_value,
      valid_from,
      system_from,
      source_event_id,
      confidence
    ) VALUES (
      ${input.objectId}::uuid,
      ${input.key},
      ${JSON.stringify(input.value)}::jsonb,
      ${input.validFrom}::timestamptz,
      ${effectiveSystemFrom}::timestamptz,
      ${input.sourceEventId ?? null}::uuid,
      ${input.confidence ?? null}
    )
    RETURNING
      property_state_id::text,
      object_id::text,
      prop_key,
      prop_value,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      source_event_id::text,
      confidence
  `);

  return row as unknown as PropertyRow;
}

export async function getPropertyAsOf(
  db: Queryable,
  input: { objectId: string; key: string; asOfValid: string; asOfSystem: string }
): Promise<PropertyRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      property_state_id::text,
      object_id::text,
      prop_key,
      prop_value,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      source_event_id::text,
      confidence
    FROM property_state
    WHERE object_id = ${input.objectId}::uuid
      AND prop_key = ${input.key}
      AND ${bitemporalPredicate(input.asOfValid, input.asOfSystem)}
    ORDER BY valid_from DESC, system_from DESC, created_at DESC
    LIMIT 2
  `);

  return rows as unknown as PropertyRow[];
}

export async function listPropertyRowsForExplain(
  db: Queryable,
  input: { objectId: string; key: string; limit: number }
): Promise<PropertyRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      property_state_id::text,
      object_id::text,
      prop_key,
      prop_value,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      source_event_id::text,
      confidence
    FROM property_state
    WHERE object_id = ${input.objectId}::uuid
      AND prop_key = ${input.key}
    ORDER BY valid_from DESC, system_from DESC, created_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as PropertyRow[];
}

export type EdgeUpsertInput = {
  srcId: string;
  predicate: string;
  dstId: string;
  validFrom: string;
  systemFrom?: string;
  sourceEventId?: string;
  confidence?: number;
};

export type EdgeRow = {
  edge_state_id: string;
  src_id: string;
  predicate: string;
  dst_id: string;
  valid_from: string;
  valid_to: string | null;
  system_from: string;
  system_to: string | null;
  source_event_id: string | null;
  confidence: number | null;
};

export async function closeOpenEdgeIntervals(
  tx: DatabaseTransactionConnection,
  input: EdgeUpsertInput,
  effectiveSystemFrom: string
): Promise<void> {
  await tx.query(sql.typeAlias('void')`
    UPDATE edge_state
    SET valid_to = CASE
          WHEN valid_from < ${input.validFrom}::timestamptz
          THEN ${input.validFrom}::timestamptz
          ELSE valid_to
        END,
        system_to = ${effectiveSystemFrom}::timestamptz
    WHERE src_id = ${input.srcId}::uuid
      AND predicate = ${input.predicate}
      AND dst_id = ${input.dstId}::uuid
      AND valid_to IS NULL
      AND system_to IS NULL
  `);
}

export async function getLatestOpenEdgeSystemFrom(
  tx: DatabaseTransactionConnection,
  input: { srcId: string; predicate: string; dstId: string }
): Promise<string | undefined> {
  const row = await tx.maybeOne(sql.typeAlias('record')`
    SELECT MAX(system_from)::text AS system_from
    FROM edge_state
    WHERE src_id = ${input.srcId}::uuid
      AND predicate = ${input.predicate}
      AND dst_id = ${input.dstId}::uuid
      AND system_to IS NULL
  `);
  const value = (row as { system_from?: string | null } | null)?.system_from;
  return value ?? undefined;
}

export async function insertEdgeState(
  tx: DatabaseTransactionConnection,
  input: EdgeUpsertInput,
  effectiveSystemFrom: string
): Promise<EdgeRow> {
  const row = await tx.one(sql.typeAlias('record')`
    INSERT INTO edge_state (
      src_id,
      predicate,
      dst_id,
      valid_from,
      system_from,
      source_event_id,
      confidence
    ) VALUES (
      ${input.srcId}::uuid,
      ${input.predicate},
      ${input.dstId}::uuid,
      ${input.validFrom}::timestamptz,
      ${effectiveSystemFrom}::timestamptz,
      ${input.sourceEventId ?? null}::uuid,
      ${input.confidence ?? null}
    )
    RETURNING
      edge_state_id::text,
      src_id::text,
      predicate,
      dst_id::text,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      source_event_id::text,
      confidence
  `);

  return row as unknown as EdgeRow;
}

export async function getEdgesAsOf(
  db: Queryable,
  input: {
    srcId: string;
    predicate?: string;
    asOfValid: string;
    asOfSystem: string;
    limit: number;
  }
): Promise<EdgeRow[]> {
  const predicates = [sql.fragment`src_id = ${input.srcId}::uuid`];
  if (input.predicate) {
    predicates.push(sql.fragment`predicate = ${input.predicate}`);
  }
  predicates.push(bitemporalPredicate(input.asOfValid, input.asOfSystem));

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      edge_state_id::text,
      src_id::text,
      predicate,
      dst_id::text,
      valid_from::text,
      valid_to::text,
      system_from::text,
      system_to::text,
      source_event_id::text,
      confidence
    FROM edge_state
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY valid_from DESC, system_from DESC, created_at DESC
    LIMIT ${input.limit}
  `);

  return rows as unknown as EdgeRow[];
}

function bitemporalPredicate(asOfValid: string, asOfSystem: string) {
  return sql.fragment`
    valid_from <= ${asOfValid}::timestamptz
    AND (valid_to IS NULL OR valid_to > ${asOfValid}::timestamptz)
    AND system_from <= ${asOfSystem}::timestamptz
    AND (system_to IS NULL OR system_to > ${asOfSystem}::timestamptz)
  `;
}
