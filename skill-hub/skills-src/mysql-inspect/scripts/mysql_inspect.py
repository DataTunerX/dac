#!/usr/bin/env python3
"""Read-only inspection of a MySQL server.

Subcommands:
  databases            list databases (SHOW DATABASES)
  tables               list tables in a database, with row-count estimates
  schema  --table T    columns of one table (DESCRIBE) + SHOW CREATE TABLE
  query   --sql "..."  run a single read-only SELECT/SHOW/DESCRIBE/EXPLAIN

Connection resolves per flag -> env -> default:
  --host      / MYSQL_HOST      / mysql
  --port      / MYSQL_PORT      / 3306
  --user      / MYSQL_USER      / root
  --password  / MYSQL_PASSWORD  / (none)
  --database  / MYSQL_DATABASE  / (none; required by tables/schema)

READ-ONLY: `query` rejects anything that isn't a single SELECT/SHOW/DESCRIBE/
EXPLAIN statement. Output is one JSON object; errors -> {"error": ...} + exit 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import pymysql
except ImportError:
    print(json.dumps({"error": "pymysql is not installed in this runtime"}))
    sys.exit(1)

_READ_ONLY_PREFIXES = ("select", "show", "describe", "desc", "explain", "with")
_FORBIDDEN = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "replace", "call", "set ", "lock", "load", "rename",
)


def _conn(args):
    return pymysql.connect(
        host=args.host or os.getenv("MYSQL_HOST") or "mysql",
        port=int(args.port or os.getenv("MYSQL_PORT") or 3306),
        user=args.user or os.getenv("MYSQL_USER") or "root",
        password=args.password or os.getenv("MYSQL_PASSWORD") or "",
        database=args.database or os.getenv("MYSQL_DATABASE") or None,
        connect_timeout=5,
        read_timeout=15,
        cursorclass=pymysql.cursors.Cursor,
    )


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
    cur.execute("SHOW DATABASES")
    return {"databases": [r[0] for r in cur.fetchall()]}


def cmd_tables(cur, args) -> dict:
    db = args.database or os.getenv("MYSQL_DATABASE")
    if not db:
        return {"error": "tables requires --database"}
    cur.execute(
        "SELECT table_name, table_rows, ROUND(data_length/1024/1024, 2) AS mb "
        "FROM information_schema.tables WHERE table_schema=%s ORDER BY table_name",
        (db,),
    )
    return {
        "database": db,
        "tables": [
            {"name": r[0], "approx_rows": r[1], "data_mb": float(r[2]) if r[2] is not None else None}
            for r in cur.fetchall()
        ],
    }


def cmd_schema(cur, args) -> dict:
    if not args.table:
        return {"error": "schema requires --table"}
    cur.execute(f"DESCRIBE `{args.table}`")
    cols = [
        {"field": r[0], "type": r[1], "null": r[2], "key": r[3], "default": r[4], "extra": r[5]}
        for r in cur.fetchall()
    ]
    cur.execute(f"SHOW CREATE TABLE `{args.table}`")
    ddl = cur.fetchone()
    return {"table": args.table, "columns": cols, "create_table": ddl[1] if ddl else None}


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
    p = argparse.ArgumentParser(description="Read-only MySQL inspection.")
    p.add_argument("--host")
    p.add_argument("--port")
    p.add_argument("--user")
    p.add_argument("--password")
    p.add_argument("--database")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("databases")
    sub.add_parser("tables")
    ps = sub.add_parser("schema"); ps.add_argument("--table", required=True)
    pq = sub.add_parser("query")
    pq.add_argument("--sql", required=True)
    pq.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    handlers = {"databases": cmd_databases, "tables": cmd_tables,
                "schema": cmd_schema, "query": cmd_query}
    conn = None
    try:
        conn = _conn(args)
        with conn.cursor() as cur:
            result = handlers[args.cmd](cur, args)
    except pymysql.err.OperationalError as exc:
        print(json.dumps({"error": f"connection/auth error: {exc}"}))
        return 1
    except pymysql.MySQLError as exc:
        print(json.dumps({"error": f"mysql error: {exc}"}))
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
