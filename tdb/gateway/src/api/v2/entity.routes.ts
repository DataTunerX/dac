import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  EntityGetRouteSchema,
  EntityListRouteSchema,
  EntityUpsertRouteSchema
} from '../../schema/v2/entity.js';
import { EntityService } from '../../services/entity.service.js';

const entityRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): EntityService => {
    return new EntityService(app.gatewayBackend);
  };

  app.post('/entity/upsert', { schema: EntityUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const entity = await service.upsert(req.body);
    reply.status(201).send(entity);
  });

  app.get('/entity/get', { schema: EntityGetRouteSchema }, async (req) => {
    const service = ensureService();
    const entity = await service.get(req.query);
    return { entity };
  });

  app.get('/entity/list', { schema: EntityListRouteSchema }, async (req) => {
    const service = ensureService();
    const entities = await service.list(req.query);
    return { entities };
  });
};

export default entityRoutes;
