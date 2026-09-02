import { type DatabasePool, type DatabaseTransactionConnection } from 'slonik';
import { sql } from '../sql.js';

type Queryable = DatabasePool | DatabaseTransactionConnection;

export type EntityRow = {
  entity_id: string;
  entity_type: string;
  display_name: string;
  external_refs: Record<string, unknown>;
  status: 'active' | 'inactive' | 'deleted';
  created_at: string;
  updated_at: string;
};

export async function upsertEntity(
  db: Queryable,
  input: {
    entityId?: string;
    entityType: string;
    displayName: string;
    externalRefs: Record<string, unknown>;
    status: 'active' | 'inactive' | 'deleted';
  }
): Promise<EntityRow> {
  const row = await db.one(sql.typeAlias('record')`
    INSERT INTO entity (
      entity_id,
      entity_type,
      display_name,
      external_refs,
      status,
      updated_at
    ) VALUES (
      COALESCE(${input.entityId ?? null}::uuid, gen_random_uuid()),
      ${input.entityType},
      ${input.displayName},
      ${JSON.stringify(input.externalRefs)}::jsonb,
      ${input.status},
      NOW()
    )
    ON CONFLICT (entity_id) DO UPDATE SET
      entity_type = EXCLUDED.entity_type,
      display_name = EXCLUDED.display_name,
      external_refs = EXCLUDED.external_refs,
      status = EXCLUDED.status,
      updated_at = NOW()
    RETURNING
      entity_id::text,
      entity_type,
      display_name,
      external_refs,
      status,
      created_at::text,
      updated_at::text
  `);

  return row as unknown as EntityRow;
}

export async function getEntityById(db: Queryable, entityId: string): Promise<EntityRow | undefined> {
  const row = await db.maybeOne(sql.typeAlias('record')`
    SELECT
      entity_id::text,
      entity_type,
      display_name,
      external_refs,
      status,
      created_at::text,
      updated_at::text
    FROM entity
    WHERE entity_id = ${entityId}::uuid
    LIMIT 1
  `);
  return row ? (row as unknown as EntityRow) : undefined;
}

export async function resolveEntitiesByRef(
  db: Queryable,
  input: { entityType: string; name: string }
): Promise<EntityRow[]> {
  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      entity_id::text,
      entity_type,
      display_name,
      external_refs,
      status,
      created_at::text,
      updated_at::text
    FROM entity
    WHERE entity_type = ${input.entityType}
      AND (
        LOWER(display_name) = LOWER(${input.name})
        OR LOWER(COALESCE(external_refs->>'canonical_ref', '')) = LOWER(${input.name})
        OR LOWER(COALESCE(external_refs->>'canonical_ref', '')) = LOWER(${`${input.entityType}:${input.name}`})
      )
    ORDER BY updated_at DESC, created_at DESC
    LIMIT 10
  `);

  return rows as unknown as EntityRow[];
}

export async function listEntities(
  db: Queryable,
  input: {
    entityType?: string;
    status?: 'active' | 'inactive' | 'deleted';
    queryText?: string;
    limit: number;
    offset: number;
  }
): Promise<EntityRow[]> {
  const predicates = [sql.fragment`1 = 1`];
  if (input.entityType) {
    predicates.push(sql.fragment`entity_type = ${input.entityType}`);
  }
  if (input.status) {
    predicates.push(sql.fragment`status = ${input.status}`);
  }
  if (input.queryText) {
    predicates.push(sql.fragment`display_name ILIKE ${'%' + input.queryText + '%'}`);
  }

  const rows = await db.any(sql.typeAlias('record')`
    SELECT
      entity_id::text,
      entity_type,
      display_name,
      external_refs,
      status,
      created_at::text,
      updated_at::text
    FROM entity
    WHERE ${sql.join(predicates, sql.fragment` AND `)}
    ORDER BY updated_at DESC, created_at DESC
    LIMIT ${input.limit}
    OFFSET ${input.offset}
  `);

  return rows as unknown as EntityRow[];
}
