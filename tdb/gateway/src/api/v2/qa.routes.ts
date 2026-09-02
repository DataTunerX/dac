import type { FastifyPluginAsyncTypebox } from '@fastify/type-provider-typebox';

import { QaEvidencePackRouteSchema } from '../../schema/v2/qa.js';
import { QaEvidencePackService } from '../../services/qa_evidence_pack.service.js';

const qaRoutes: FastifyPluginAsyncTypebox = async (app) => {
  app.post('/qa/evidence-pack', { schema: QaEvidencePackRouteSchema }, async (req) => {
    const service = new QaEvidencePackService(app.gatewayBackend);
    return (await service.buildPack(req.body)) as never;
  });
};

export default qaRoutes;
