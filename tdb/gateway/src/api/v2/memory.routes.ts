import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { TdbError } from '../../errors/tdb_error.js';
import {
  MemoryGetEntityStateRouteSchema,
  MemoryGetRelationsRouteSchema,
  MemoryGetTaskContextRouteSchema,
  MemoryRecallAnswerArtifactsRouteSchema,
  MemoryRecordAnswerArtifactRouteSchema,
  MemoryRecordAnswerValidationRouteSchema,
  MemoryRecordEpisodeSummaryRouteSchema,
  MemoryRecordDecisionRouteSchema,
  MemoryRecordRelationRouteSchema,
  MemoryUpsertEntityStateRouteSchema,
} from '../../schema/v2/memory.js';
import { MemoryService } from '../../services/memory.service.js';

const memoryRoutes: FastifyPluginAsyncTypebox = async (app) => {
  const ensureService = (): MemoryService => {
    if (!app.hasDecorator('gatewayBackend')) {
      throw new TdbError('GATEWAY_BACKEND_NOT_CONFIGURED', 500, 'Gateway Backend Client is not configured');
    }
    return new MemoryService(app.gatewayBackend);
  };

  app.post('/memory/decision/record', { schema: MemoryRecordDecisionRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const decision = await service.recordDecision(req.body);
    reply.status(201).send(decision);
  });

  app.post('/memory/episode/summary/record', { schema: MemoryRecordEpisodeSummaryRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const summary = await service.recordEpisodeSummary(req.body);
    reply.status(201).send(summary);
  });

  app.post('/memory/answer/artifact/record', { schema: MemoryRecordAnswerArtifactRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const artifact = await service.recordAnswerArtifact(req.body);
    reply.status(201).send(artifact);
  });

  app.post('/memory/answer/artifact/recall', { schema: MemoryRecallAnswerArtifactsRouteSchema }, async (req) => {
    const service = ensureService();
    return service.recallAnswerArtifacts(req.body);
  });

  app.post('/memory/answer/validation/record', { schema: MemoryRecordAnswerValidationRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const validation = await service.recordAnswerValidation(req.body);
    reply.status(201).send(validation);
  });

  app.post('/memory/entity/state/get', { schema: MemoryGetEntityStateRouteSchema }, async (req) => {
    const service = ensureService();
    return service.getEntityState(req.body);
  });

  app.post('/memory/relation/record', { schema: MemoryRecordRelationRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const relation = await service.recordRelation(req.body);
    reply.status(201).send(relation);
  });

  app.post('/memory/relation/get', { schema: MemoryGetRelationsRouteSchema }, async (req) => {
    const service = ensureService();
    return service.getRelations(req.body);
  });

  app.post('/memory/entity/state/upsert', { schema: MemoryUpsertEntityStateRouteSchema }, async (req, reply) => {
    const service = ensureService();
    const entity = await service.upsertEntityState(req.body);
    reply.status(201).send(entity);
  });

  app.post('/memory/task/context/get', { schema: MemoryGetTaskContextRouteSchema }, async (req) => {
    const service = ensureService();
    return service.getTaskContext(req.body);
  });
};

export default memoryRoutes;
