import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  DecisionCreateRouteSchema,
  DecisionEvidenceAttachRouteSchema,
  DecisionExplainRouteSchema,
  DecisionGetRouteSchema,
  DecisionTraceRouteSchema
} from '../../schema/v2/decision.js';
import { DecisionService } from '../../services/decision.service.js';

const decisionRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): DecisionService => new DecisionService(app.gatewayBackend);

  app.post('/decision/create', { schema: DecisionCreateRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const decision = await service.createDecision(req.body);
    reply.status(201).send(decision);
  });

  app.post('/decision/evidence/attach', { schema: DecisionEvidenceAttachRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const evidence = await service.attachEvidence(req.body);
    reply.status(201).send(evidence);
  });

  app.get('/decision/get', { schema: DecisionGetRouteSchema }, async (req) => {
    const service = ensureService();
    return service.getDecision(req.query);
  });

  app.get('/decision/trace', { schema: DecisionTraceRouteSchema }, async (req) => {
    const service = ensureService();
    return service.traceDecision(req.query);
  });

  app.get('/decision/explain', { schema: DecisionExplainRouteSchema }, async (req) => {
    const service = ensureService();
    return service.explainDecision(req.query);
  });
};

export default decisionRoutes;
