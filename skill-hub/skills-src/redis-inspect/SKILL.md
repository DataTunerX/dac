---
name: redis-inspect
description: "Read-only inspection of a Redis instance in the DAC cluster — server/keyspace summary, scan keys by pattern, and read a key's value (string/list/set/hash/zset). Use when the user wants to look inside Redis: check the agent registry, debug cached state, list or read keys, or see memory/keyspace stats. Never writes or deletes."
---

# redis-inspect

Inspect a Redis instance **read-only**. Wraps `redis-inspect.py`, which uses
redis-py (already in the skill-agent image) and only ever issues read commands
(`INFO`, `SCAN`, `TYPE`, `TTL`, `GET`/`LRANGE`/`HGETALL`/…). It never runs
`SET`, `DEL`, `EXPIRE`, or `FLUSH`.

## When to use

- Look inside the DAC Redis: inspect the **agent registry / heartbeats**, cached
  state, or session data.
- List keys matching a pattern, check a key's type/TTL/size, or read a value.
- Get server stats: version, memory, connected clients, keys-per-DB.

DAC layout hint: the in-cluster service is typically `<release>-redis:6379`
(password from `values.redis.password`, default `123`). Agents register on
**DB 2**; other components also use DB 0/2. Pick the DB with `--db`.

## Connection

Resolved per flag → env → default:

| Flag | Env | Default |
|------|-----|---------|
| `--host` | `REDIS_HOST` | `127.0.0.1` |
| `--port` | `REDIS_PORT` | `6379` |
| `--db` | `REDIS_DB` | `0` |
| `--password` | `REDIS_PASSWORD` | (none) |

If you don't know the host/password, first discover them with `plan_cmd`
(e.g. read the deployment/service, or a known env var) rather than guessing.

## Subcommands

```bash
# Server + keyspace summary (which DBs hold keys, memory, clients)
python3 redis_inspect.py --host <h> --password <pw> info

# List up to 50 keys matching a pattern on DB 2 (uses SCAN, safe on big DBs)
python3 redis_inspect.py --host <h> --password <pw> --db 2 scan --pattern "agent:*" --limit 50

# Metadata for one key (type, TTL, size) without dumping the whole value
python3 redis_inspect.py --host <h> --password <pw> --db 2 key --key "agent:SkillAgent"

# Read a key's value, type-aware (string/list/set/hash/zset), with output caps
python3 redis_inspect.py --host <h> --password <pw> --db 2 get --key "agent:SkillAgent" --max-elements 50 --max-chars 2000
```

## Output

Always a single JSON object on stdout:

- `info` → `{server: {redis_version, used_memory_human, connected_clients, ...}, keyspace: {db0: {...}, db2: {...}}}`
- `scan` → `{pattern, returned, truncated, keys: [{key, type, ttl}, ...]}`
- `key`  → `{key, exists, type, ttl, size}`
- `get`  → `{key, type, ttl, value | length/fields/cardinality + value}`

`ttl` is `-1` (no expiry) or `-2` (missing), per Redis convention. Values are
clipped by `--max-chars` / `--max-elements` so large keys never flood output.
On error: `{"error": "..."}` and a non-zero exit.

## Recommended workflow

1. Start with `info` to see which DBs actually hold keys.
2. `scan` with a specific `--pattern` on the right `--db` to find keys of interest
   (avoid `*` on large DBs — use a prefix like `agent:*`).
3. `key` to check type/size before dumping; then `get` to read the value.
4. Summarize findings for the user; if `error` is present, report the cause
   (auth, connection, wrong DB) instead of inventing data.

## Must not

- Do not attempt writes/deletes — this skill is inspection only; if the user
  needs to modify Redis, tell them that's out of scope.
- Do not run `scan --pattern "*"` on a large production DB without a limit.
- Do not hard-code or guess the password; discover it from the environment.
