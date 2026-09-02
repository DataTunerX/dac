import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { EventAppendRouteSchema, EventReadRouteSchema, EventSentencesRouteSchema } from '../../schema/v2/event.js';
import { EventService } from '../../services/event.service.js';

const eventRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): EventService => new EventService(app.gatewayBackend);

  app.post('/event/append', { schema: EventAppendRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const result = await service.appendEvent(req.body);
    reply.status(201).send(result);
  });

  app.get('/event/read', { schema: EventReadRouteSchema }, async (req) => {
    const service = ensureService();
    const events = await service.readEvents(req.query);
    return { events };
  });

  app.get('/event/sentences', { schema: EventSentencesRouteSchema }, async (req) => {
    const { stream_id, limit } = req.query;
    const sentences = await app.gatewayBackend.getEventSentences({ stream_id, limit });
    return { sentences };
  });
};

export default eventRoutes;
