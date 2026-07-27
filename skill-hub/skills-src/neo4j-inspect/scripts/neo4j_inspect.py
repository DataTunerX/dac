#!/usr/bin/env python3
"""Read-only inspection of a Neo4j database via its HTTP Cypher API.

Uses the transactional HTTP endpoint (POST /db/{database}/tx/commit) with
basic auth, so it needs no neo4j driver — only `requests`.

Subcommands:
  labels               list node labels (CALL db.labels())
  reltypes             list relationship types (CALL db.relationshipTypes())
  counts               node count, relationship count, and per-label counts
  query   --cypher "…" run a single read-only Cypher (MATCH/RETURN/CALL/SHOW)

Connection resolves per flag -> env -> default:
  --host       / NEO4J_HOST      / neo4j
  --http-port  / NEO4J_HTTP_PORT / 7474
  --user       / NEO4J_USER      / neo4j
  --password   / NEO4J_PASSWORD  / (none)
  --database   / NEO4J_DATABASE  / neo4j

READ-ONLY: `query` rejects Cypher containing write clauses (CREATE, MERGE,
DELETE, SET, REMOVE, DROP, DETACH, etc.). Output is one JSON object; errors ->
{"error": ...} + exit 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import requests
except ImportError:
    print(json.dumps({"error": "requests is not installed in this runtime"}))
    sys.exit(1)

_WRITE_CLAUSES = (
    "create", "merge", "delete", "detach", "set", "remove", "drop",
    "foreach", "load csv", "call apoc.create", "call apoc.merge",
)


def _endpoint(args) -> tuple[str, tuple[str, str]]:
    host = args.host or os.getenv("NEO4J_HOST") or "neo4j"
    port = int(args.http_port or os.getenv("NEO4J_HTTP_PORT") or 7474)
    db = args.database or os.getenv("NEO4J_DATABASE") or "neo4j"
    user = args.user or os.getenv("NEO4J_USER") or "neo4j"
    pw = args.password or os.getenv("NEO4J_PASSWORD") or ""
    url = f"http://{host}:{port}/db/{db}/tx/commit"
    return url, (user, pw)


def _run(url, auth, statements: list[dict]) -> dict:
    resp = requests.post(
        url,
        auth=auth,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={"statements": statements},
        timeout=15,
    )
    if resp.status_code == 401:
        raise RuntimeError("authentication failed — check --user / --password")
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        msgs = "; ".join(e.get("message", str(e)) for e in body["errors"])
        raise RuntimeError(f"cypher error: {msgs}")
    return body


def _rows(result_block) -> list:
    return [row.get("row") for row in result_block.get("data", [])]


def _guard_read_only(cypher: str) -> str | None:
    low = " " + cypher.lower().replace("\n", " ") + " "
    for clause in _WRITE_CLAUSES:
        if f" {clause} " in low or low.strip().startswith(clause):
            return f"write clause '{clause.upper()}' is not permitted (read-only tool)"
    return None


def cmd_labels(url, auth, args) -> dict:
    body = _run(url, auth, [{"statement": "CALL db.labels()"}])
    return {"labels": [r[0] for r in _rows(body["results"][0])]}


def cmd_reltypes(url, auth, args) -> dict:
    body = _run(url, auth, [{"statement": "CALL db.relationshipTypes()"}])
    return {"relationship_types": [r[0] for r in _rows(body["results"][0])]}


def cmd_counts(url, auth, args) -> dict:
    body = _run(url, auth, [
        {"statement": "MATCH (n) RETURN count(n) AS c"},
        {"statement": "MATCH ()-[r]->() RETURN count(r) AS c"},
        {"statement": "MATCH (n) RETURN labels(n) AS labels, count(*) AS c ORDER BY c DESC LIMIT 50"},
    ])
    nodes = _rows(body["results"][0])[0][0]
    rels = _rows(body["results"][1])[0][0]
    per_label = [{"labels": r[0], "count": r[1]} for r in _rows(body["results"][2])]
    return {"nodes": nodes, "relationships": rels, "per_label": per_label}


def cmd_query(url, auth, args) -> dict:
    if not args.cypher:
        return {"error": "query requires --cypher"}
    err = _guard_read_only(args.cypher)
    if err:
        return {"error": err}
    stmt = args.cypher.strip()
    low = stmt.lower()
    if " limit " not in low and not low.endswith("limit") and "call" not in low:
        stmt = f"{stmt} LIMIT {args.limit}"
    body = _run(url, auth, [{"statement": stmt}])
    block = body["results"][0]
    return {
        "columns": block.get("columns", []),
        "rows": _rows(block),
        "note": f"read-only; auto-capped at {args.limit} rows unless you set LIMIT/CALL",
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only Neo4j inspection (HTTP API).")
    p.add_argument("--host")
    p.add_argument("--http-port", dest="http_port")
    p.add_argument("--user")
    p.add_argument("--password")
    p.add_argument("--database")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("labels")
    sub.add_parser("reltypes")
    sub.add_parser("counts")
    pq = sub.add_parser("query")
    pq.add_argument("--cypher", required=True)
    pq.add_argument("--limit", type=int, default=50)
    args = p.parse_args()

    handlers = {"labels": cmd_labels, "reltypes": cmd_reltypes,
                "counts": cmd_counts, "query": cmd_query}
    try:
        url, auth = _endpoint(args)
        result = handlers[args.cmd](url, auth, args)
    except requests.exceptions.RequestException as exc:
        print(json.dumps({"error": f"connection error: {exc}"}))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
