import { diag, DiagConsoleLogger, DiagLogLevel } from '@opentelemetry/api';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { NodeSDK } from '@opentelemetry/sdk-node';

export type OTelConfig = {
  serviceName: string;
  exporterOtlpEndpoint?: string;
};

export async function initOpenTelemetry(config: OTelConfig): Promise<NodeSDK | undefined> {
  if (!config.exporterOtlpEndpoint) {
    return undefined;
  }
  if (!process.env.OTEL_SERVICE_NAME) {
    process.env.OTEL_SERVICE_NAME = config.serviceName;
  }

  diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.ERROR);

  const traceExporter = new OTLPTraceExporter({
    url: config.exporterOtlpEndpoint
  });

  const sdk = new NodeSDK({ traceExporter });

  await sdk.start();
  return sdk;
}
