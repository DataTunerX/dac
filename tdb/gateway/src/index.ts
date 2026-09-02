import { buildApp } from './app.js';
import { loadEnv } from './config/env.js';
import { initOpenTelemetry } from './observability/otel.js';

async function main(): Promise<void> {
  const env = loadEnv();
  const otel = await initOpenTelemetry({
    serviceName: env.otelServiceName,
    exporterOtlpEndpoint: env.otelExporterOtlpEndpoint
  });
  const app = await buildApp({
    logLevel: env.logLevel,
    backend: env.backend,
    bodyLimit: env.bodyLimit
  });

  await app.listen({
    host: env.host,
    port: env.port
  });

  const shutdown = async (): Promise<void> => {
    await app.close();
    if (otel) {
      await otel.shutdown();
    }
  };

  process.on('SIGINT', () => {
    void shutdown().finally(() => process.exit(0));
  });
  process.on('SIGTERM', () => {
    void shutdown().finally(() => process.exit(0));
  });
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});
