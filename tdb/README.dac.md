# TDB service in DAC

This directory contains the minimal online TDB runtime ported from `eis/tdb`:

- Rust gRPC backend (`tdb_gateway_backend`)
- TypeScript/Fastify HTTP gateway
- protobuf contracts
- V2 PostgreSQL migrations

The optional ingestion pipeline, evaluation suites, MCP server, and standalone
frontends are intentionally not included in this first DAC service port.

The Helm chart deploys the combined gateway/backend container as a stateless
Deployment. It uses a dedicated logical `tdb` database on DAC's pgvector server
by default. An init container creates that database when necessary and applies
new migrations before the online container starts. Applied filenames are kept
in `tdb_schema_migrations`, so Pod restarts do not replay the full schema.

Agents should use the HTTP service URL published as `tdb-url` in the
`dac-configuration` ConfigMap. The API root is `/v2`; liveness is `/health`.

## Build

```bash
docker build --platform linux/amd64 \
  -f docker/Dockerfile.gateway \
  -t tdb-gateway:12-amd64 .
```

## Test

```bash
cargo test
cd gateway && npm ci && npm test
```
