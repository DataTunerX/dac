import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import { DbHealthRouteSchema, HealthRouteSchema } from '../../schema/v2/health.js';

const healthRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.get('/health', { schema: HealthRouteSchema }, async () => {
    return {
      status: 'ok',
      service: 'tdb-gateway',
      version: 'v2'
    } as const;
  });

  app.get('/health/db', { schema: DbHealthRouteSchema }, async () => {
    throw new TdbError('DB_NOT_CONFIGURED', 500, 'Gateway no longer exposes direct database health');
  });
};

export default healthRoutes;
