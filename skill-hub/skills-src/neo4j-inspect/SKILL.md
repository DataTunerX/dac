---
name: neo4j-inspect
description: "Read-only inspection of the DAC Neo4j graph database — list node labels and relationship types, count nodes/relationships (per label), and run read-only Cypher queries. Use when the user wants to look inside Neo4j: explore the graph schema, count entities, or query nodes/relationships. Never writes or modifies the graph."
---

# neo4j-inspect

Inspect a Neo4j database **read-only** via `neo4j-inspect.py`. It talks to
Neo4j's transactional **HTTP Cypher API** (`POST /db/{db}/tx/commit`) using
`requests`, so no neo4j driver is needed. `query` rejects any write clause
(`CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, `DROP`, `DETACH`, …).

## When to use

- Explore the DAC graph schema: what node **labels** and **relationship types** exist.
- Count nodes / relationships, and node counts per label.
- Run an ad-hoc read-only Cypher (`MATCH ... RETURN ...`).

## Connection

Per flag -> env -> default. In-cluster the service is `neo4j` with HTTP on
`7474` (Bolt `7687` is not used by this tool), user `neo4j`.

| Flag | Env | Default |
|------|-----|---------|
| `--host` | `NEO4J_HOST` | `neo4j` |
| `--http-port` | `NEO4J_HTTP_PORT` | `7474` |
| `--user` | `NEO4J_USER` | `neo4j` |
| `--password` | `NEO4J_PASSWORD` | (none) |
| `--database` | `NEO4J_DATABASE` | `neo4j` |

## Subcommands

```bash
python3 neo4j_inspect.py --password <pw> labels
python3 neo4j_inspect.py --password <pw> reltypes
python3 neo4j_inspect.py --password <pw> counts
python3 neo4j_inspect.py --password <pw> query --cypher "MATCH (n) RETURN n LIMIT 10" --limit 25
```

## Output

Single JSON object:
- `labels` -> `{labels: [...]}`
- `reltypes` -> `{relationship_types: [...]}`
- `counts` -> `{nodes, relationships, per_label: [{labels, count}]}`
- `query` -> `{columns, rows: [...], note}`

On error: `{"error": "..."}` and exit 1. If the Cypher has no `LIMIT` (and isn't
a `CALL`), the tool appends `LIMIT <--limit>` so large graphs don't flood output.

## Recommended workflow

1. `labels` and `reltypes` to learn the graph schema.
2. `counts` to gauge size (total nodes/rels + per-label breakdown).
3. `query --cypher "MATCH ... RETURN ..."` for specifics; summarize results.
4. On `error`, report the cause (auth, connection, bad Cypher) — don't invent data.

## Must not

- No write Cypher — inspection only; if the user needs to mutate the graph, say it's out of scope.
- Do not guess the password; discover it from the environment/values.
- Prefer bounded queries; rely on the auto-`LIMIT` or set one explicitly.
