import 'fastify';
import type { GatewayBackendClient } from '../clients/gateway_backend.types.js';

declare module 'fastify' {
  interface FastifyInstance {
    gatewayBackend: GatewayBackendClient;
  }
}
