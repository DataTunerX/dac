import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import {
  PlanDryRunRouteSchema,
  PlanExecuteRouteSchema,
  PlanExplainRouteSchema,
  PlanReplayByIdRouteSchema,
  PlanReplayRouteSchema,
  PlanRunGetRouteSchema,
  PlanRunListRouteSchema,
  PlanValidateRouteSchema
} from '../../schema/v2/plan.js';
import { PlanService } from '../../services/plan.service.js';

const planRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const buildService = () =>
    new PlanService({
      gatewayBackend: app.gatewayBackend
    });

  app.post('/plan/validate', { schema: PlanValidateRouteSchema }, async (req) => {
    return buildService().validate(req.body);
  });

  app.post('/plan/explain', { schema: PlanExplainRouteSchema }, async (req) => {
    return buildService().explain(req.body);
  });

  app.post('/plan/dry-run', { schema: PlanDryRunRouteSchema }, async (req) => {
    return buildService().dryRun(req.body);
  });

  app.post('/plan/execute', { schema: PlanExecuteRouteSchema }, async (req) => {
    return buildService().execute(req.body);
  });

  app.post('/plan/replay', { schema: PlanReplayRouteSchema }, async (req) => {
    return buildService().replay(req.body);
  });

  app.get('/plan/run/get', { schema: PlanRunGetRouteSchema }, async (req) => {
    return buildService().getRun(req.query);
  });

  app.get('/plan/run/list', { schema: PlanRunListRouteSchema }, async (req) => {
    return buildService().listRuns(req.query);
  });

  app.post('/plan/replay/by-id', { schema: PlanReplayByIdRouteSchema }, async (req) => {
    return buildService().replayById(req.body);
  });
};

export default planRoutes;
