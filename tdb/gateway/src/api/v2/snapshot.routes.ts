import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import { SnapshotLatestRouteSchema, SnapshotWriteRouteSchema } from '../../schema/v2/snapshot.js';
import { SnapshotService } from '../../services/snapshot.service.js';

const snapshotRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): SnapshotService => new SnapshotService(app.gatewayBackend);

  app.post('/snapshot/write', { schema: SnapshotWriteRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const snapshot = await service.writeSnapshot(req.body);
    reply.status(201).send(snapshot);
  });

  app.get('/snapshot/latest', { schema: SnapshotLatestRouteSchema }, async (req) => {
    const service = ensureService();
    const snapshot = await service.latestSnapshot(req.query);
    return { snapshot };
  });
};

export default snapshotRoutes;
