#!/usr/bin/env python3
"""Read-only inspection of a Redis instance.

Subcommands:
  info    server + keyspace summary (version, memory, clients, keys-per-db)
  scan    iterate keys matching a pattern (uses SCAN, never KEYS)
  get     read one key's value, auto-detecting its type
  key     type + TTL + size metadata for one key (no full value dump)

Connection is resolved from flags, falling back to env vars, falling back to
localhost defaults:
  --host      / REDIS_HOST      / 127.0.0.1
  --port      / REDIS_PORT      / 6379
  --db        / REDIS_DB        / 0
  --password  / REDIS_PASSWORD  / (none)

This tool is READ-ONLY. It never writes, deletes, expires, or flushes.
All output is a single JSON object on stdout; failures print {"error": ...}
and exit non-zero.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import redis  # provided by the skill-agent image (redis-py)
except ImportError:
    print(json.dumps({"error": "redis-py is not installed in this runtime"}))
    sys.exit(1)


def _client(args) -> "redis.Redis":
    host = args.host or os.getenv("REDIS_HOST") or "127.0.0.1"
    port = int(args.port or os.getenv("REDIS_PORT") or 6379)
    db = int(args.db if args.db is not None else (os.getenv("REDIS_DB") or 0))
    password = args.password or os.getenv("REDIS_PASSWORD") or None
    return redis.Redis(
        host=host,
        port=port,
        db=db,
        password=password,
        socket_connect_timeout=5,
        socket_timeout=5,
        decode_responses=True,
    )


def _clip(value, limit: int):
    """Clip a string (or each element) so we never dump unbounded payloads."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"...(+{len(value) - limit} chars)"
    return value


def cmd_info(client, args) -> dict:
    info = client.info()
    keyspace = {k: v for k, v in info.items() if k.startswith("db")}
    return {
        "server": {
            "redis_version": info.get("redis_version"),
            "uptime_seconds": info.get("uptime_in_seconds"),
            "connected_clients": info.get("connected_clients"),
            "used_memory_human": info.get("used_memory_human"),
            "maxmemory_human": info.get("maxmemory_human"),
            "role": info.get("role"),
        },
        "keyspace": keyspace,
    }


def cmd_scan(client, args) -> dict:
    pattern = args.pattern or "*"
    limit = max(1, args.limit)
    keys: list[str] = []
    cursor = 0
    while True:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=200)
        keys.extend(batch)
        if cursor == 0 or len(keys) >= limit:
            break
    truncated = len(keys) > limit
    keys = keys[:limit]
    typed = [{"key": k, "type": client.type(k), "ttl": client.ttl(k)} for k in keys]
    return {
        "pattern": pattern,
        "returned": len(typed),
        "truncated": truncated,
        "keys": typed,
    }


def cmd_key(client, args) -> dict:
    key = args.key
    if not client.exists(key):
        return {"key": key, "exists": False}
    ktype = client.type(key)
    size_fn = {
        "string": client.strlen,
        "list": client.llen,
        "set": client.scard,
        "hash": client.hlen,
        "zset": client.zcard,
    }.get(ktype)
    return {
        "key": key,
        "exists": True,
        "type": ktype,
        "ttl": client.ttl(key),
        "size": size_fn(key) if size_fn else None,
    }


def cmd_get(client, args) -> dict:
    key = args.key
    if not client.exists(key):
        return {"key": key, "exists": False}
    ktype = client.type(key)
    limit = args.max_chars
    count = args.max_elements
    out: dict = {"key": key, "type": ktype, "ttl": client.ttl(key)}
    if ktype == "string":
        out["value"] = _clip(client.get(key), limit)
    elif ktype == "list":
        out["length"] = client.llen(key)
        out["value"] = [_clip(v, limit) for v in client.lrange(key, 0, count - 1)]
    elif ktype == "set":
        members = list(client.sscan_iter(key, count=200))
        out["cardinality"] = len(members)
        out["value"] = [_clip(v, limit) for v in members[:count]]
    elif ktype == "hash":
        h = client.hgetall(key)
        out["fields"] = len(h)
        out["value"] = {k: _clip(v, limit) for k, v in list(h.items())[:count]}
    elif ktype == "zset":
        out["cardinality"] = client.zcard(key)
        out["value"] = [
            {"member": _clip(m, limit), "score": s}
            for m, s in client.zrange(key, 0, count - 1, withscores=True)
        ]
    else:
        out["value"] = None
        out["note"] = f"type '{ktype}' not rendered by this tool"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Redis inspection.")
    parser.add_argument("--host")
    parser.add_argument("--port")
    parser.add_argument("--db", type=int, default=None)
    parser.add_argument("--password")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="Server + keyspace summary")

    p_scan = sub.add_parser("scan", help="List keys matching a pattern (SCAN)")
    p_scan.add_argument("--pattern", default="*")
    p_scan.add_argument("--limit", type=int, default=100)

    p_key = sub.add_parser("key", help="Type/TTL/size metadata for one key")
    p_key.add_argument("--key", required=True)

    p_get = sub.add_parser("get", help="Read one key's value (type-aware)")
    p_get.add_argument("--key", required=True)
    p_get.add_argument("--max-chars", type=int, default=2000)
    p_get.add_argument("--max-elements", type=int, default=50)

    args = parser.parse_args()
    handlers = {"info": cmd_info, "scan": cmd_scan, "key": cmd_key, "get": cmd_get}

    try:
        client = _client(args)
        client.ping()
        result = handlers[args.cmd](client, args)
    except redis.exceptions.AuthenticationError:
        print(json.dumps({"error": "authentication failed — check --password / REDIS_PASSWORD"}))
        return 1
    except redis.exceptions.RedisError as exc:
        print(json.dumps({"error": f"redis error: {exc}"}))
        return 1
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
