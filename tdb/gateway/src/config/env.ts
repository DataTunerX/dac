import dotenv from 'dotenv';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const defaultRootEnvPath = path.resolve(moduleDir, '../../../.env');
dotenv.config({ path: process.env.TDB_ENV_PATH ?? defaultRootEnvPath });

export type GatewayBackendConfig = {
  address: string;
  timeoutMs: number;
};

export type GatewayEnv = {
  nodeEnv: string;
  host: string;
  port: number;
  databaseUrl: string;
  logLevel: string;
  otelServiceName: string;
  otelExporterOtlpEndpoint?: string;
  configPath: string;
  backend: GatewayBackendConfig;
  bodyLimit: number;
};

export function loadEnv(): GatewayEnv {
  const configPath = process.env.GATEWAY_CONFIG_PATH ?? path.resolve(process.cwd(), 'config/gateway.config.json');
  const fileConfig = loadGatewayConfigFile(configPath);

  const portRaw = firstEnv('TDB_GATEWAY_PORT', 'PORT') ?? asString(fileConfig.port) ?? '8080';
  const port = Number(portRaw);
  if (!Number.isInteger(port) || port <= 0) {
    throw new Error(`Invalid TDB_GATEWAY_PORT/PORT: ${portRaw}`);
  }

  return {
    nodeEnv: firstEnv('TDB_GATEWAY_NODE_ENV', 'NODE_ENV') ?? asString(fileConfig.nodeEnv) ?? 'development',
    host: firstEnv('TDB_GATEWAY_HOST', 'HOST') ?? asString(fileConfig.host) ?? '0.0.0.0',
    port,
    databaseUrl:
      process.env.DATABASE_URL ??
      asString(fileConfig.databaseUrl) ??
      'postgres://tdb:tdb@localhost:5432/DataV2',
    logLevel: firstEnv('TDB_GATEWAY_LOG_LEVEL', 'LOG_LEVEL') ?? asString(fileConfig.logLevel) ?? 'info',
    otelServiceName:
      firstEnv('TDB_GATEWAY_OTEL_SERVICE_NAME', 'OTEL_SERVICE_NAME') ??
      asString(fileConfig.otelServiceName) ??
      'tdb-gateway',
    otelExporterOtlpEndpoint:
      firstEnv('TDB_GATEWAY_OTEL_EXPORTER_OTLP_ENDPOINT', 'OTEL_EXPORTER_OTLP_ENDPOINT') ??
      asOptionalString(fileConfig.otelExporterOtlpEndpoint),
    configPath,
    backend: loadGatewayBackendConfig(fileConfig),
    bodyLimit: toPositiveInt(
      process.env.TDB_GATEWAY_BODY_LIMIT_BYTES ?? fileConfig.bodyLimitBytes,
      10 * 1024 * 1024
    )
  };
}

function loadGatewayConfigFile(configPath: string): Record<string, unknown> {
  if (!fs.existsSync(configPath)) {
    return {};
  }
  const raw = fs.readFileSync(configPath, 'utf-8');
  const parsed = JSON.parse(raw);
  if (!isObject(parsed)) {
    throw new Error(`Invalid gateway config file: ${configPath}`);
  }
  return parsed;
}

function loadGatewayBackendConfig(raw: Record<string, unknown>): GatewayBackendConfig {
  return {
    address:
      process.env.TDB_GATEWAY_BACKEND_ADDR ??
      asString(raw.gatewayBackendAddress) ??
      '127.0.0.1:50051',
    timeoutMs: toPositiveInt(
      process.env.TDB_GATEWAY_BACKEND_TIMEOUT_MS ?? raw.gatewayBackendTimeoutMs,
      3000
    )
  };
}

function firstEnv(...names: string[]): string | undefined {
  for (const name of names) {
    const value = process.env[name];
    if (value !== undefined && value.trim() !== '') {
      return value;
    }
  }
  return undefined;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | undefined {
  if (typeof value !== 'string') {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function asOptionalString(value: unknown): string | undefined {
  return asString(value);
}

function toPositiveInt(raw: unknown, fallback: number): number {
  if (raw === undefined || raw === null || raw === '') {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) {
    return fallback;
  }
  return value;
}

function toPositiveNumber(raw: unknown, fallback: number): number {
  if (raw === undefined || raw === null || raw === '') {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    return fallback;
  }
  return value;
}

function toBoolean(raw: unknown, fallback: boolean): boolean {
  if (typeof raw === 'boolean') {
    return raw;
  }
  if (raw === undefined || raw === null || raw === '') {
    return fallback;
  }
  const normalized = String(raw).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(normalized)) {
    return true;
  }
  if (['0', 'false', 'no', 'off'].includes(normalized)) {
    return false;
  }
  return fallback;
}
