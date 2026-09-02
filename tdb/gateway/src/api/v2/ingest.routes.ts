import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  IngestArtifactsRouteSchema,
  IngestBundleRouteSchema,
  IngestEdgeRouteSchema,
  IngestEntitiesRouteSchema,
  IngestEventsRouteSchema,
  IngestPropertyRouteSchema,
  IngestTextRouteSchema
} from '../../schema/v2/ingest.js';
import { IngestService } from '../../services/ingest.service.js';

const ingestRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): IngestService => new IngestService(app.gatewayBackend);

  app.post('/ingest/entities', { schema: IngestEntitiesRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestEntities(req.body);
  });

  app.post('/ingest/artifacts', { schema: IngestArtifactsRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestArtifacts(req.body);
  });

  app.post('/ingest/events', { schema: IngestEventsRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestEvents(req.body);
  });

  app.post('/ingest/text', { schema: IngestTextRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestText(req.body);
  });

  app.post('/ingest/bundle', { schema: IngestBundleRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestBundle(req.body);
  });

  app.post('/ingest/property', { schema: IngestPropertyRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestProperty(req.body);
  });

  app.post('/ingest/edge', { schema: IngestEdgeRouteSchema }, async (req) => {
    const service = ensureService();
    return service.ingestEdge(req.body);
  });
};

export default ingestRoutes;
