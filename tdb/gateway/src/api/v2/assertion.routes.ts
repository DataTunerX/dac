import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  AssertionEvidenceLinkListRouteSchema,
  AssertionEvidenceLinkUpsertRouteSchema,
  AssertionGetRouteSchema,
  AssertionRelationListRouteSchema,
  AssertionRelationUpsertRouteSchema,
  AssertionSearchRouteSchema,
  AssertionUpsertRouteSchema
} from '../../schema/v2/assertion.js';
import { AssertionService } from '../../services/assertion.service.js';

const assertionRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): AssertionService => new AssertionService(app.gatewayBackend);

  app.post('/ledger/assertion/upsert', { schema: AssertionUpsertRouteSchema }, async (req, reply) => {
    const assertion = await ensureService().upsertAssertion(req.body);
    reply.status(201).send(assertion as never);
  });

  app.get('/ledger/assertion/get', { schema: AssertionGetRouteSchema }, async (req) => {
    return { assertion: await ensureService().getAssertion(req.query) } as never;
  });

  app.get('/ledger/assertion/search', { schema: AssertionSearchRouteSchema }, async (req) => {
    return { assertions: await ensureService().searchAssertions(req.query) } as never;
  });

  app.post(
    '/ledger/assertion/evidence/upsert',
    { schema: AssertionEvidenceLinkUpsertRouteSchema },
    async (req, reply) => {
      const evidenceLink = await ensureService().upsertAssertionEvidenceLink(req.body);
      reply.status(201).send(evidenceLink as never);
    }
  );

  app.get('/ledger/assertion/evidence/list', { schema: AssertionEvidenceLinkListRouteSchema }, async (req) => {
    return { evidence_links: await ensureService().listAssertionEvidenceLinks(req.query) } as never;
  });

  app.post(
    '/ledger/assertion/relation/upsert',
    { schema: AssertionRelationUpsertRouteSchema },
    async (req, reply) => {
      const relation = await ensureService().upsertAssertionRelation(req.body);
      reply.status(201).send(relation as never);
    }
  );

  app.get('/ledger/assertion/relation/list', { schema: AssertionRelationListRouteSchema }, async (req) => {
    return { relations: await ensureService().listAssertionRelations(req.query) } as never;
  });
};

export default assertionRoutes;
