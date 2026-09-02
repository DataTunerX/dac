import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  SearchDomainStreamBindingListRouteSchema,
  SearchDomainStreamBindingUpsertRouteSchema,
  SearchQueryRouteSchema
} from '../../schema/v2/search.js';
import { SearchService } from '../../services/search.service.js';

const searchRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): SearchService => new SearchService(app.gatewayBackend);

  app.post('/search/query', { schema: SearchQueryRouteSchema }, async (req) => {
    const traceIdHeader = req.headers['x-request-id'];
    const traceId = typeof traceIdHeader === 'string' ? traceIdHeader : '';
    const result = await app.gatewayBackend.searchQuery(req.body, traceId);
    return {
      query: req.body.query,
      resolved_stream_ids: result.resolved_stream_ids,
      hits: result.hits
    };
  });

  app.post('/search/domain-stream/bind', { schema: SearchDomainStreamBindingUpsertRouteSchema }, async (req, reply) => {
    const binding = await ensureService().upsertDomainStreamBinding(req.body);
    reply.status(201).send(binding);
  });

  app.post('/search/domain-stream/unbind', { schema: SearchDomainStreamBindingUpsertRouteSchema }, async (req, reply) => {
    const binding = await ensureService().upsertDomainStreamBinding({
      ...req.body,
      status: 'inactive'
    });
    reply.status(201).send(binding);
  });

  app.get('/search/domain-stream/list', { schema: SearchDomainStreamBindingListRouteSchema }, async (req) => ({
    bindings: await ensureService().listDomainStreamBindings(req.query)
  }));
};

export default searchRoutes;
