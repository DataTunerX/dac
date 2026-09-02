import { createSqlTag } from 'slonik';
import { z } from 'zod';

// Shared SQL tag for runtime-safe row parsing aliases used across query modules.
export const sql = createSqlTag({
  typeAliases: {
    record: z.object({}).passthrough(),
    void: z.any()
  }
});
