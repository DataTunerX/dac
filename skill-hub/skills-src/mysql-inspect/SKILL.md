---
name: mysql-inspect
description: "Read-only inspection of the DAC MySQL server — list databases, list tables with row counts, show a table's schema, and run read-only SELECT queries. Use when the user wants to look inside MySQL: browse databases/tables, see a table structure, or query data. Never writes or modifies data."
---

# mysql-inspect

Inspect a MySQL server **read-only** via `mysql-inspect.py` (uses `pymysql`,
already in the skill-agent image). Only ever runs `SHOW`, `DESCRIBE`, `SELECT`,
and `EXPLAIN` — never `INSERT`/`UPDATE`/`DELETE`/`DDL`.

## When to use

- Browse the DAC MySQL: databases `dac_db`, `fingerprint`, `history`.
- List tables and their approximate row counts / size.
- Inspect a table's columns and `CREATE TABLE` DDL.
- Run an ad-hoc read-only `SELECT`.

## Connection

Per flag -> env -> default. In-cluster the service is `mysql:3306`, user `root`.
Supply the password (or set `MYSQL_PASSWORD`).

| Flag | Env | Default |
|------|-----|---------|
| `--host` | `MYSQL_HOST` | `mysql` |
| `--port` | `MYSQL_PORT` | `3306` |
| `--user` | `MYSQL_USER` | `root` |
| `--password` | `MYSQL_PASSWORD` | (none) |
| `--database` | `MYSQL_DATABASE` | (none; required by `tables`/`schema`) |

## Subcommands

```bash
python3 mysql_inspect.py --password <pw> databases
python3 mysql_inspect.py --password <pw> --database dac_db tables
python3 mysql_inspect.py --password <pw> --database dac_db schema --table <table>
python3 mysql_inspect.py --password <pw> --database dac_db query --sql "SELECT * FROM <table>" --limit 20
```

## Output

Single JSON object:
- `databases` -> `{databases: [...]}`
- `tables` -> `{database, tables: [{name, approx_rows, data_mb}]}`
- `schema` -> `{table, columns: [{field,type,null,key,default,extra}], create_table}`
- `query` -> `{columns, row_count, rows: [ {...} ], note}`

On error: `{"error": "..."}` and exit 1. The `query` command refuses anything
that isn't a single read statement (no `;`, no write/DDL keywords).

## Recommended workflow

1. `databases` to see what's there.
2. `tables --database <db>` to find tables of interest.
3. `schema --table <t>` before querying so you know the columns.
4. `query --sql "SELECT ..." --limit N`; summarize results. On `error`, report
   the cause (auth, wrong db, bad SQL) — don't fabricate rows.

## Must not

- No writes/DDL — inspection only. If the user needs to modify data, say it's out of scope.
- Do not guess the password; discover it from the environment/values.
- Do not run unbounded `SELECT *` on huge tables without a `--limit`.
