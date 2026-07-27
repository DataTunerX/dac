#!/usr/bin/env python3
"""Read-only inspection of a PostgreSQL / pgvector server.

Subcommands:
  databases            list databases (SELECT datname FROM pg_database)
  extensions           installed extensions (flags whether 'vector' is present)
  tables               list tables in a schema, with row-count estimates
  schema  --table T    columns of one table (from information_schema.columns)
  query   --sql "..."  run a single read-only SELECT/WITH/SHOW/EXPLAIN

Connection resolves per flag -> env -> default:
  --host      / PGHOST       / pgvector
  --port      / PGPORT       / 5432
  --user      / PGUSER       / postgres
  --password  / PGPASSWORD   / (none)
  --database  / PGDATABASE   / postgres
  --schema    / (n/a)        / public   (for tables/schema)

READ-ONLY: the session is set to read-only, and `query` rejects anything that
isn't a single SELECT/WITH/SHOW/EXPLAIN. Output is one JSON object; errors ->
{"error": ...} + exit 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import psycopg2
except ImportError:
    print(json.dumps({"error": "psycopg2 is not installed in this runtime"}))
    sys.exit(1)

_READ_ONLY_PREFIXES = ("select", "with", "show", "explain", "table")
_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "call", "set ", "copy", "vacuum", "reindex",
)


def _conn(args):
    conn = psycopg2.connect(
        host=args.host or os.getenv("PGHOST") or "pgvector",
        port=int(args.port or os.getenv("PGPORT") or 5432),
        user=args.user or os.getenv("PGUSER") or "postgres",
        password=args.password or os.getenv("PGPASSWORD") or "",
        dbname=args.database or os.getenv("PGDATABASE") or "postgres",
        connect_timeout=5,
    )
    conn.set_session(readonly=True, autocommit=True)
    return conn


def _guard_read_only(sql: str) -> str | None:
    s = sql.strip().rstrip(";").lstrip()
    low = s.lower()
    if ";" in s:
        return "only a single statement is allowed (no ';')"
    if not low.startswith(_READ_ONLY_PREFIXES):
        return f"only read statements allowed ({', '.join(_READ_ONLY_PREFIXES)})"
    for bad in _FORBIDDEN:
        if low.startswith(bad):
            return f"statement '{bad.strip()}' is not permitted (read-only tool)"
    return None


def cmd_databases(cur, args) -> dict:
    cur.execute("SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY datname")
    return {"databases": [r[0] for r in cur.fetchall()]}


def cmd_extensions(cur, args) -> dict:
    cur.execute("SELECT extname, extversion FROM pg_extension ORDER BY extname")
    exts = [{"name": r[0], "version": r[1]} for r in cur.fetchall()]
    return {"extensions": exts, "has_vector": any(e["name"] == "vector" for e in exts)}


def cmd_tables(cur, args) -> dict:
    schema = args.schema or "public"
    cur.execute(
        "SELECT c.relname, c.reltuples::bigint AS approx_rows, "
        "pg_size_pretty(pg_total_relation_size(c.oid)) AS size "
        "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname=%s AND c.relkind='r' ORDER BY c.relname",
        (schema,),
    )
    return {
        "schema": schema,
        "tables": [{"name": r[0], "approx_rows": r[1], "size": r[2]} for r in cur.fetchall()],
    }


def cmd_schema(cur, args) -> dict:
    if not args.table:
        return {"error": "schema requires --table"}
    schema = args.schema or "public"
    cur.execute(
        "SELECT column_name, data_type, is_nullable, column_default "
        "FROM information_schema.columns WHERE table_schema=%s AND table_name=%s "
        "ORDER BY ordinal_position",
        (schema, args.table),
    )
    cols = [
        {"column": r[0], "type": r[1], "nullable": r[2], "default": r[3]}
        for r in cur.fetchall()
    ]
    if not cols:
        return {"error": f"table {schema}.{args.table} not found (or no columns)"}
    return {"schema": schema, "table": args.table, "columns": cols}


def cmd_query(cur, args) -> dict:
    if not args.sql:
        return {"error": "query requires --sql"}
    err = _guard_read_only(args.sql)
    if err:
        return {"error": err}
    cur.execute(args.sql)
    headers = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchmany(args.limit)
    return {
        "columns": headers,
        "row_count": len(rows),
        "rows": [dict(zip(headers, r)) for r in rows],
        "note": f"showing up to {args.limit} rows",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only PostgreSQL/pgvector inspection.")
    p.add_argument("--host")
    p.add_argument("--port")
    p.add_argument("--user")
    p.add_argument("--password")
    p.add_argument("--database")
    p.add_argument("--schema", default="public")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("databases")
    sub.add_parser("extensions")
    sub.add_parser("tables")
    ps = sub.add_parser("schema"); ps.add_argument("--table", required=True)
    pq = sub.add_parser("query")
    pq.add_argument("--sql", required=True)
    pq.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    handlers = {"databases": cmd_databases, "extensions": cmd_extensions,
                "tables": cmd_tables, "schema": cmd_schema, "query": cmd_query}
    conn = None
    try:
        conn = _conn(args)
        with conn.cursor() as cur:
            result = handlers[args.cmd](cur, args)
    except psycopg2.OperationalError as exc:
        print(json.dumps({"error": f"connection/auth error: {exc}"}))
        return 1
    except psycopg2.Error as exc:
        print(json.dumps({"error": f"postgres error: {exc}"}))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    finally:
        if conn is not None:
            conn.close()

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
