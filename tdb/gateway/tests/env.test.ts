import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { loadEnv } from '../src/config/env.js';

const originalEnv = { ...process.env };

afterEach(() => {
  process.env = { ...originalEnv };
});

describe('env loader', () => {
  it('uses config/default values when env overrides are absent', () => {
    delete process.env.DATABASE_URL;
    delete process.env.TDB_GATEWAY_BACKEND_ADDR;

    const env = loadEnv();
    expect(env.databaseUrl).toBe('postgres://tdb:tdb@localhost:5432/tdb');
    expect(env.backend.address).toBe('127.0.0.1:50051');
  });

  it('loads config file and allows env override', () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gateway-config-test-'));
    const configPath = path.join(dir, 'gateway.config.json');
    fs.writeFileSync(
      configPath,
      JSON.stringify({
        databaseUrl: 'postgres://tdb:tdb@localhost:5432/TestFromFile'
      }),
      'utf-8'
    );

    process.env.GATEWAY_CONFIG_PATH = configPath;
    delete process.env.DATABASE_URL;
    process.env.TDB_GATEWAY_BACKEND_ADDR = '127.0.0.1:50091';
    const env = loadEnv();

    expect(env.databaseUrl).toBe('postgres://tdb:tdb@localhost:5432/TestFromFile');
    expect(env.backend.address).toBe('127.0.0.1:50091');
  });

  it('prefers gateway-prefixed env vars over generic env vars', () => {
    process.env.PORT = '9090';
    process.env.TDB_GATEWAY_PORT = '8088';
    process.env.LOG_LEVEL = 'warn';
    process.env.TDB_GATEWAY_LOG_LEVEL = 'debug';

    const env = loadEnv();

    expect(env.port).toBe(8088);
    expect(env.logLevel).toBe('debug');
  });
});
