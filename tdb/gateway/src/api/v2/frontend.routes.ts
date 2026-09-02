import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  ActionProposeRouteSchema,
  ActionSimulateRouteSchema,
  ContextPackRouteSchema,
  DecisionBriefRouteSchema,
  ExceptionFeedRouteSchema,
  Object360RouteSchema
} from '../../schema/v2/frontend.js';
import { FrontendService } from '../../services/frontend.service.js';

const frontendRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): FrontendService => {
    throw new TdbError('DB_NOT_CONFIGURED', 500, 'Gateway frontend endpoints no longer access the database directly');
  };

  app.post('/context/pack', { schema: ContextPackRouteSchema }, async (req) => {
    return ensureService().contextPack(req.body);
  });

  app.post('/object/360', { schema: Object360RouteSchema }, async (req) => {
    return ensureService().object360(req.body);
  });

  app.post('/exception/feed', { schema: ExceptionFeedRouteSchema }, async (req) => {
    return ensureService().exceptionFeed(req.body);
  });

  app.post('/decision/brief', { schema: DecisionBriefRouteSchema }, async (req) => {
    return ensureService().decisionBrief(req.body);
  });

  app.post('/action/propose', { schema: ActionProposeRouteSchema }, async (req) => {
    return ensureService().actionPropose(req.body);
  });

  app.post('/action/simulate', { schema: ActionSimulateRouteSchema }, async (req) => {
    return ensureService().actionSimulate(req.body);
  });
};

export default frontendRoutes;
