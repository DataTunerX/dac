import Fastify, { type FastifyInstance } from 'fastify';
import { TypeBoxTypeProvider } from '@fastify/type-provider-typebox';

import { createGatewayBackendClient } from './clients/gateway_backend.client.js';
import type { GatewayBackendConfig } from './config/env.js';
import { TdbError, type ErrorResponse } from './errors/tdb_error.js';
import v2Routes from './api/v2/index.js';

export type BuildAppOptions = {
  logLevel: string;
  databaseUrl?: string; // retained for backwards compatibility, no longer used
  enableDb?: boolean;   // retained for backwards compatibility, no longer used
  backend?: GatewayBackendConfig;
  bodyLimit?: number;
};

export async function buildApp(opts: BuildAppOptions): Promise<FastifyInstance> {
  const app = Fastify({
    bodyLimit: opts.bodyLimit,
    logger: {
      level: opts.logLevel
    }
  }).withTypeProvider<TypeBoxTypeProvider>();
  app.decorate('gatewayBackend', createGatewayBackendClient(opts.backend ?? {
    address: '127.0.0.1:50051',
    timeoutMs: 3000
  }));

  app.setErrorHandler((err, _req, reply) => {
    const fastifyErr = err as {
      validation?: unknown;
      code?: string;
      statusCode?: number;
      message?: string;
    };
    if (err instanceof TdbError) {
      const payload: ErrorResponse = {
        error: {
          code: err.code,
          message: err.message,
          details: err.details
        }
      };
      reply.status(err.statusCode).send(payload);
      return;
    }
    if (fastifyErr.validation) {
      const payload: ErrorResponse = {
        error: {
          code: 'BAD_REQUEST',
          message: 'Invalid request',
          details: fastifyErr.validation
        }
      };
      reply.status(400).send(payload);
      return;
    }
    if (fastifyErr.code === 'FST_ERR_CTP_BODY_TOO_LARGE' || fastifyErr.statusCode === 413) {
      const payload: ErrorResponse = {
        error: {
          code: 'BODY_TOO_LARGE',
          message: fastifyErr.message ?? 'Request body too large'
        }
      };
      reply.status(413).send(payload);
      return;
    }

    app.log.error({ err }, 'Unhandled error');
    const payload: ErrorResponse = {
      error: {
        code: 'INTERNAL_ERROR',
        message: 'Internal server error'
      }
    };
    reply.status(500).send(payload);
  });

  app.get('/health', async () => ({
    status: 'ok',
    service: 'tdb-gateway',
    version: 'v2'
  }));

  await app.register(v2Routes, { prefix: '/v2' });

  app.addHook('onClose', async () => {
    app.gatewayBackend.close();
  });

  return app;
}
