---
name: pgvector-inspect
description: "Read-only inspection of the DAC PostgreSQL/pgvector server — list databases, list installed extensions (incl. pgvector), list tables with row counts, show a table's schema, and run read-only SELECT queries. Use when the user wants to look inside Postgres/pgvector: browse databases/tables, check the vector extension, or query data. Never writes or modifies data."
---

# pgvector-inspect

Inspect a PostgreSQL / pgvector server **read-only** via `pgvector-inspect.py`
(uses `psycopg2`, already in the skill-agent image). The DB session is opened
read-only and `query` only accepts `SELECT`/`WITH`/`SHOW`/`EXPLAIN`.

## When to use

- Browse the DAC pgvector: databases `knowledge_vector`, `agent_memory`.
- Confirm the `vector` extension is installed (`extensions`).
- List tables + row counts / sizes; inspect a table's columns.
- Run an ad-hoc read-only `SELECT` (including vector similarity queries).

## Connection

Per flag -> env -> default. In-cluster the service is `pgvector:5432`, user
`postgres`. Postgres connects to one database at a time — pick it with
`--database` (default `postgres`).

| Flag | Env | Default |
|------|-----|---------|
| `--host` | `PGHOST` | `pgvector` |
| `--port` | `PGPORT` | `5432` |
| `--user` | `PGUSER` | `postgres` |
| `--password` | `PGPASSWORD` | (none) |
| `--database` | `PGDATABASE` | `postgres` |
| `--schema` | (n/a) | `public` |

## Subcommands

```bash
python3 pgvector_inspect.py --password <pw> databases
python3 pgvector_inspect.py --password <pw> --database knowledge_vector extensions
python3 pgvector_inspect.py --password <pw> --database knowledge_vector tables
python3 pgvector_inspect.py --password <pw> --database knowledge_vector schema --table <table>
python3 pgvector_inspect.py --password <pw> --database knowledge_vector query --sql "SELECT ..." --limit 20
```

## Output

Single JSON object:
- `databases` -> `{databases: [...]}`
- `extensions` -> `{extensions: [{name,version}], has_vector: true|false}`
- `tables` -> `{schema, tables: [{name, approx_rows, size}]}`
- `schema` -> `{schema, table, columns: [{column,type,nullable,default}]}`
- `query` -> `{columns, row_count, rows: [ {...} ], note}`

On error: `{"error": "..."}` and exit 1. `query` refuses non-read statements.

## Recommended workflow

1. `databases` to list DBs, then reconnect with `--database <db>` (Postgres is per-DB).
2. `extensions` to confirm `vector` is available if doing similarity work.
3. `tables` / `schema --table <t>` to understand structure.
4. `query --sql "SELECT ..." --limit N`; summarize. On `error`, report the cause.

## Must not

- No writes/DDL — inspection only.
- Do not guess the password; discover it from the environment/values.
- Remember Postgres is per-database: to inspect a different DB you must set `--database`.
