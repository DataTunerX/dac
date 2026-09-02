import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  ArtifactCreateRouteSchema,
  ArtifactVersionAsOfRouteSchema,
  ArtifactVersionCreateRouteSchema
} from '../../schema/v2/artifact.js';
import { ArtifactService } from '../../services/artifact.service.js';

const artifactRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): ArtifactService => new ArtifactService(app.gatewayBackend);

  app.post('/artifact/create', { schema: ArtifactCreateRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const artifact = await service.createArtifact(req.body);
    reply.status(201).send(artifact);
  });

  app.post('/artifact/version/create', { schema: ArtifactVersionCreateRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const artifactVersion = await service.createArtifactVersion(req.body);
    reply.status(201).send(artifactVersion);
  });

  app.get('/artifact/version/asof', { schema: ArtifactVersionAsOfRouteSchema }, async (req) => {
    const service = ensureService();
    const artifactVersion = await service.getArtifactVersionAsOf(req.query);
    return { artifact_version: artifactVersion };
  });
};

export default artifactRoutes;
