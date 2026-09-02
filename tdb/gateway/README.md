# TDB Gateway (V2)

Schema-first TypeScript REST gateway for TDB v2.

## Authority Boundaries

- `gateway` is the only online write control plane for TDB V2.
- `db/migrations_v2` is the only schema authority.
- Rust bridge commands are offline/admin tools and must not perform runtime DDL.

## Stack
- Fastify
- TypeBox + `@fastify/type-provider-typebox`
- Slonik (parameterized SQL only)
- Vitest

## Run
```bash
cd /Users/ningwu/eis/tdb/gateway
npm install
npm run dev
```

## Unified Config
Gateway runtime config is centralized in:
- `/Users/ningwu/eis/tdb/gateway/config/gateway.config.json`

Default embedding settings in that file follow your previous ingest setup:
- `embedding.baseUrl`: `http://10.124.48.50:11434/v1`
- `embedding.model`: `qwen3-embedding:8b`

Config override order:
1. `GATEWAY_CONFIG_PATH` file (default: `config/gateway.config.json`)
2. environment variables (`DATABASE_URL`, `TDB_EMBED_*`, etc.)

## GatewayBackend Trial

The Rust online backend trial server is started via:

```bash
cargo run --bin tdb_gateway_backend
```

Or if you have everything configured in the tdb/.env file, then you can use the following scripts to start the Rust backend server: 

```bash
./scripts/start_gateway_backend.sh 
```


`/v2/search/query` now calls the Rust backend over gRPC.

Gateway-side runtime knobs for the search route:

```bash
TDB_GATEWAY_BACKEND_ADDR=127.0.0.1:50051
TDB_GATEWAY_BACKEND_TIMEOUT_MS=3000
```

For local acceptance and dev runs without embedding config, start the Rust backend with:

```bash
TDB_ENABLE_PGVECTOR=false cargo run --bin tdb_gateway_backend
```

## Current gateway scope
- Project skeleton
- Unified error envelope
- DB pool plugin (Slonik)
- OTel bootstrap scaffold (optional, via `OTEL_EXPORTER_OTLP_ENDPOINT`)
- `/health`, `/v2/health`, `/v2/health/db`
- `/v2/event/append` and `/v2/event/read` routes wired to DB query layer
- `/v2/state/property/upsert`, `/v2/state/property/asof`, `/v2/state/property/diff`, `/v2/state/property/why`
- `/v2/state/edge/upsert`, `/v2/state/edge/asof`, `/v2/state/edge/diff`
- `/v2/artifact/create`, `/v2/artifact/version/create`, `/v2/artifact/version/asof`
- `/v2/entity/upsert`, `/v2/entity/get`, `/v2/entity/list`
- `/v2/rule/upsert`, `/v2/authority/grant`, `/v2/rule/override`
- `/v2/authority/check`, `/v2/rule/override/asof`
- `/v2/ontology/fact/review`, `/v2/ontology/fact/history`, `/v2/ontology/fact/provenance`, `/v2/ontology/fact/review/bulk`
- `/v2/ontology/case/open`, `/v2/ontology/case/list`, `/v2/ontology/case/detail`, `/v2/ontology/case/explain`, `/v2/ontology/case/update`
- `/v2/ontology/alert/open`, `/v2/ontology/alert/list`, `/v2/ontology/alert/explain`, `/v2/ontology/alert/update`
- `/v2/ontology/ops/config`, `/v2/ontology/ops/config/upsert`
- `/v2/ontology/ops/rules/run`, `/v2/ontology/ops/runs`, `/v2/ontology/ops/run/explain`
- `/v2/ontology/concept/evidence`, `/v2/wiki/page/evidence`, `/v2/qa/evidence-pack`
- `/v2/wiki/page`, `/v2/wiki/search`, `/v2/wiki/index`, `/v2/wiki/pages`, `/v2/wiki/link`, `/v2/wiki/log`, `/v2/wiki/lint`, `/v2/wiki/export`, `/v2/wiki/reinforce`
- `/v2/ontology/concept-type-assignment/*`
- `/v2/ontology/semantic/upsert-batch`
- `/v2/ontology/term-mapping/registry/*`, `/v2/ontology/term-mapping/rule/*`, `/v2/ontology/term-mapping/rule-evidence/*`, `/v2/ontology/term-mapping/interpret*`
- `/v2/ontology/normalized-term/*`, `/v2/ontology/normalized-term/cluster*`, `/v2/ontology/normalized-term/raw-term-mapping/*`
- `/v2/ontology/raw-term/*`, `/v2/ontology/raw-term/candidate/*`, `/v2/ontology/relation-candidate/*`
- `/v2/decision/create`, `/v2/decision/evidence/attach`, `/v2/decision/get`, `/v2/decision/trace`, `/v2/decision/explain`
- `/v2/snapshot/write`, `/v2/snapshot/latest`
- `/v2/search/query` (BM25 + optional vector hybrid on V2 projection tables)
- `/v2/context/pack`, `/v2/object/360`, `/v2/exception/feed`, `/v2/decision/brief`, `/v2/action/propose`, `/v2/action/simulate` (enterprise frontend intelligence APIs backed by semantic read model)
- `/v2/ingest/entities`, `/v2/ingest/artifacts`, `/v2/ingest/events`, `/v2/ingest/text`
- `/v2/ingest/bundle` (server-side phased bundle ingest with defaults + ref resolution)
- `/v2/ingest/property`, `/v2/ingest/edge`
- `/v2/plan/validate`, `/v2/plan/explain`, `/v2/plan/dry-run`, `/v2/plan/execute`, `/v2/plan/replay`, `/v2/plan/run/get`, `/v2/plan/run/list`, `/v2/plan/replay/by-id` (client-side query-plan validation/explain/dry-run/execution/replay on gateway, with `${context.*}` / `${vars.*}` templating)

When DB is enabled, `execute` / `dry-run` / `replay` now persist a `plan_run_ledger` record with:
- original request JSON
- response JSON
- per-step execution trace
- optional `replay_of_plan_id` link for replay-by-id chains
- queryable execution history via `/v2/plan/run/list`

`/v2/ingest/text` now supports automatic embedding -> vector write for hybrid search.
Optional request fields:
- `generate_embedding` (bool, overrides config)
- `embedding_model` (string, overrides config model)
- `items[].embedding` (precomputed vector)

`/v2/search/query` now supports:
- `query` as text query field
- server-side auto query embedding (when `query_embedding` is omitted and embedding is enabled)
- compatibility fields `stream_ids` (first item used) and `mode`

## Semantic-kernel and Wikidata-style direction

Gateway is no longer only exposing a legacy `concept / fact / edge` surface.
It now contains two distinct but related API styles:

1. Legacy-compatible ontology governance APIs
   - `ontology/fact/*`
   - `ontology/concept/*`
   - `ontology/relation-type/*`
   - `ontology/object-type/*`
2. Statement-oriented semantic-kernel APIs
   - `ontology/semantic/upsert-batch`
   - term-mapping / normalized-term / raw-term / registry routes

The practical meaning:

- `ontology_fact` remains the main compatibility and review surface for many existing tools.
- `semantic/upsert-batch` starts exposing a more Wikidata-style write model:
  - entity
  - statement
  - qualifier
  - reference
- `reference` is property-value shaped and can carry `evidence_id` / `source_span`, rather than behaving like a single flat citation field.

If you are documenting or building new integrations, do not assume that the gateway is still only a “fact CRUD” layer.

## Evidence and provenance caveats

Recent evidence-oriented routes are powerful, but they have important behavior boundaries:

- `GET /v2/wiki/page/evidence` requires `domain + slug`, not `page_id`.
- `GET /v2/ontology/fact/provenance` requires a real `fact_id >= 1`.
- Legacy paths may still resolve to `fact_id = 0`; those can help navigation, but are not strong provenance-bearing fact handles.
- A successful provenance response is not automatically high-quality evidence:
  - some results are direct, usable local sentences
  - some are deterministic fallback sentences
  - some may be too broad to serve as main proof text

For user-facing answering systems, provenance success and evidence quality should be treated separately.

## DB migration
Run the repo migration script so the V2 core tables and constraints are created:
```bash
DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2 \
/Users/ningwu/eis/tdb/scripts/db_migrate.sh
```

If you only want the minimum gateway kernel, run:
```bash
DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2 \
TDB_MIGRATION_PROFILE=core \
/Users/ningwu/eis/tdb/scripts/db_migrate.sh
```

`full` remains the default profile and adds the ontology, governance, semantic, and newer aggregation-aware migrations on top of the core baseline.

In particular, recent gateway capabilities assume the full profile includes newer semantic-kernel tables and scope extensions beyond the original `002_v2_ontology_extension.sql` era. If a deployment only applies an older subset of migrations, the statement-oriented and term-mapping APIs may not behave as documented.

For one-time import / cutover / rollback procedure, see:
- `/Users/ningwu/eis/tdb/docs/data_v2_cutover_runbook.md`

## DB guarantees (P0)
- `case_event_ledger` is append-only (DB trigger rejects `UPDATE`/`DELETE`).
- `property_state` enforces bitemporal non-overlap for the same `(object_id, prop_key)`.
- `edge_state` enforces bitemporal non-overlap for the same `(src_id, predicate, dst_id)`.
- decision/rule/override evidence links use versioned references (`artifact_version`) to avoid drift.
- ingest writes directly into V2 and projects retrievable text/embedding into V2 search tables (`search_document`, `search_embedding`) without relying on V1 tables.

## P1 enhancements
- `authority/check` supports request scope filtering (`scope` query param as JSON string), matched by JSON containment (`grant.scope @> request.scope`).
- `/v2/event/append` supports `stream_id` without `case_id`; gateway derives deterministic `case_id` and upserts `case_context`.
- Added governance/state query indexes in `017_tdb_v2_p1_indexes.sql`:
  - `idx_rule_def_asof`
  - `idx_authority_grant_scope_gin`
  - `idx_edge_state_src_pred_asof`

## Acceptance tests
Use a **disposable** Postgres URL and run vitest.
The acceptance suite resets `public` schema in `beforeAll`.

```bash
cd /Users/ningwu/eis/tdb/gateway
TEST_DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2_verify npm test
```

If you need one command for migration + typecheck + acceptance, keep target DB and test DB separate:

```bash
cd /Users/ningwu/eis/tdb/gateway
DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2 \
TEST_DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2_verify \
npm run verify:p0
```

## Cutover modes
- Runtime is V2-only: write/read only V2 tables.
- Health checks: `GET /v2/health` and `GET /v2/health/db`.

## V2 search projection operations
Backfill search projection from V2 ledger payload text:
```bash
cd /Users/ningwu/eis/tdb/gateway
DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2 npm run search:backfill
```

Check projection consistency:
```bash
cd /Users/ningwu/eis/tdb/gateway
DATABASE_URL=postgres://tdb:tdb@localhost:5432/DataV2 npm run search:check
```

Optional filters for both scripts:
- `STREAM_ID_FILTER=<stream_id>`
- `CASE_ID_FILTER=<case_uuid>`
