import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  EdgeAsOfRouteSchema,
  EdgeDiffRouteSchema,
  EdgeUpsertRouteSchema,
  PropertyAsOfRouteSchema,
  PropertyDiffRouteSchema,
  PropertyWhyRouteSchema,
  PropertyUpsertRouteSchema
} from '../../schema/v2/state.js';
import { StateService } from '../../services/state.service.js';

const stateRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): StateService => {
    return new StateService(app.gatewayBackend);
  };

  app.post('/state/property/upsert', { schema: PropertyUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const property = await service.upsertProperty(req.body);
    reply.status(201).send(property);
  });

  app.get('/state/property/asof', { schema: PropertyAsOfRouteSchema }, async (req) => {
    const service = ensureService();
    const property = await service.getPropertyAsOf(req.query);
    return { property };
  });

  app.get('/state/property/diff', { schema: PropertyDiffRouteSchema }, async (req) => {
    const service = ensureService();
    return service.diffProperty(req.query);
  });

  app.get('/state/property/why', { schema: PropertyWhyRouteSchema }, async (req) => {
    const service = ensureService();
    return service.explainProperty(req.query);
  });

  app.post('/state/edge/upsert', { schema: EdgeUpsertRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const edge = await service.upsertEdge(req.body);
    reply.status(201).send(edge);
  });

  app.get('/state/edge/asof', { schema: EdgeAsOfRouteSchema }, async (req) => {
    const service = ensureService();
    const edges = await service.getEdgesAsOf(req.query);
    return { edges };
  });

  app.get('/state/edge/diff', { schema: EdgeDiffRouteSchema }, async (req) => {
    const service = ensureService();
    return service.diffEdges(req.query);
  });
};

export default stateRoutes;
