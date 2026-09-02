import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import artifactRoutes from './artifact.routes.js';
import assertionRoutes from './assertion.routes.js';
import decisionRoutes from './decision.routes.js';
import evidenceRoutes from './evidence.routes.js';
import entityRoutes from './entity.routes.js';
import eventRoutes from './event.routes.js';
import frontendRoutes from './frontend.routes.js';
import governanceRoutes from './governance.routes.js';
import healthRoutes from './health.routes.js';
import ingestRoutes from './ingest.routes.js';
import memoryRoutes from './memory.routes.js';
import ontologyRoutes from './ontology.routes.js';
import planRoutes from './plan.routes.js';
import qaRoutes from './qa.routes.js';
import searchRoutes from './search.routes.js';
import snapshotRoutes from './snapshot.routes.js';
import stateRoutes from './state.routes.js';
import wikiRoutes from './wiki.routes.js';

const v2Routes: FastifyPluginAsyncTypebox = async (app) => {
  await app.register(healthRoutes);
  await app.register(frontendRoutes);
  await app.register(artifactRoutes);
  await app.register(assertionRoutes);
  await app.register(evidenceRoutes);
  await app.register(entityRoutes);
  await app.register(ontologyRoutes);
  await app.register(governanceRoutes);
  await app.register(decisionRoutes);
  await app.register(memoryRoutes);
  await app.register(searchRoutes);
  await app.register(qaRoutes);
  await app.register(planRoutes);
  await app.register(snapshotRoutes);
  await app.register(eventRoutes);
  await app.register(stateRoutes);
  await app.register(ingestRoutes);
  await app.register(wikiRoutes);
};

export default v2Routes;
