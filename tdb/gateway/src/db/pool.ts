import { createPool, type DatabasePool } from 'slonik';

import { sql } from './sql.js';

export async function createDbPool(databaseUrl: string): Promise<DatabasePool> {
  const pool = await createPool(databaseUrl);
  await pool.one(sql.typeAlias('record')`SELECT 1`);
  return pool;
}
