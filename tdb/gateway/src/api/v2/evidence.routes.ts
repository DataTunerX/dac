import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  EvidenceClassificationGetRouteSchema,
  EvidenceClassificationUpsertRouteSchema,
  EvidenceDerivationListRouteSchema,
  EvidenceDerivationUpsertRouteSchema,
  EvidenceGetRouteSchema,
  EvidenceLocatorListRouteSchema,
  EvidenceLocatorUpsertRouteSchema,
  EvidenceStatementsRouteSchema,
  EvidenceSearchRouteSchema,
  EvidenceUpsertRouteSchema
} from '../../schema/v2/evidence.js';
import { EvidenceService } from '../../services/evidence.service.js';

const evidenceRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): EvidenceService => new EvidenceService(app.gatewayBackend);

  app.post('/ledger/evidence/upsert', { schema: EvidenceUpsertRouteSchema }, async (req, reply) => {
    const evidence = await ensureService().upsertEvidence(req.body);
    reply.status(201).send(evidence as never);
  });

  app.get('/ledger/evidence/get', { schema: EvidenceGetRouteSchema }, async (req) => {
    return { evidence: await ensureService().getEvidence(req.query) } as never;
  });

  app.get('/ledger/evidence/search', { schema: EvidenceSearchRouteSchema }, async (req) => {
    return { evidence: await ensureService().searchEvidence(req.query) } as never;
  });

  app.get('/ledger/evidence/statements', { schema: EvidenceStatementsRouteSchema }, async (req) => {
    return { references: await ensureService().getEvidenceStatements(req.query) } as never;
  });

  app.post(
    '/ledger/evidence/locator/upsert',
    { schema: EvidenceLocatorUpsertRouteSchema },
    async (req, reply) => {
      const locator = await ensureService().upsertEvidenceLocator(req.body);
      reply.status(201).send(locator as never);
    }
  );

  app.get('/ledger/evidence/locator/list', { schema: EvidenceLocatorListRouteSchema }, async (req) => {
    return { locators: await ensureService().listEvidenceLocators(req.query) } as never;
  });

  app.post(
    '/ledger/evidence/derivation/upsert',
    { schema: EvidenceDerivationUpsertRouteSchema },
    async (req, reply) => {
      const derivation = await ensureService().upsertEvidenceDerivation(req.body);
      reply.status(201).send(derivation as never);
    }
  );

  app.get(
    '/ledger/evidence/derivation/list',
    { schema: EvidenceDerivationListRouteSchema },
    async (req) => {
      return { derivations: await ensureService().listEvidenceDerivations(req.query) } as never;
    }
  );

  app.post(
    '/ledger/evidence/classification/upsert',
    { schema: EvidenceClassificationUpsertRouteSchema },
    async (req, reply) => {
      const classification = await ensureService().upsertEvidenceClassification(req.body);
      reply.status(201).send(classification as never);
    }
  );

  app.get(
    '/ledger/evidence/classification/get',
    { schema: EvidenceClassificationGetRouteSchema },
    async (req) => {
      return { classification: await ensureService().getEvidenceClassification(req.query) } as never;
    }
  );
};

export default evidenceRoutes;
