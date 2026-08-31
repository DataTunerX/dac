#!/usr/bin/env python3
"""
wwybsj_ingest.py — Step 1: put the raw registry records into TDB as a
provenance stream, and bind that stream to the `wwybsj` domain.

Every artifact record becomes one `fact_observed` event on stream
`wwybsj.artifacts`. The returned (stream_id, event_id) pair is what later
lets each written fact carry real evidence instead of floating unsupported.

Usage:
  python3 wwybsj_ingest.py --id 8                 # one record (dry-run)
  python3 wwybsj_ingest.py --id 8 --execute
  python3 wwybsj_ingest.py --all --execute        # all 465
  python3 wwybsj_ingest.py --status               # what's already ingested
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wwybsj_common import (  # noqa: E402
    OUT_DIR, STREAM_ID, TARGET_DOMAIN,
    bianhao, get, load_records, post, record_text, title,
)

INDEX_PATH = OUT_DIR / "ingest_index.json"


def load_index() -> dict:
    if INDEX_PATH.exists():
        with open(INDEX_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"stream_id": STREAM_ID, "domain": TARGET_DOMAIN, "events": {}}


def save_index(idx: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def bind_domain() -> dict:
    return post("/search/domain-stream/bind",
                {"domain": TARGET_DOMAIN, "stream_id": STREAM_ID})


def append_record(rec: dict) -> dict:
    body = {
        "stream_id": STREAM_ID,
        "event_type": "fact_observed",
        "event_text": record_text(rec),
        "payload": {
            "source_name": "wwybsj.sql/jf_ww_demo",
            "record_id": rec["id"],
            "bianhao": bianhao(rec),
            "mingchen": rec.get("ww_mingchen", ""),
            "registry_row": rec,
        },
        "valid_time": datetime.now(timezone.utc).isoformat(),
    }
    return post("/event/append", body)


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id", type=int, help="Single record id")
    g.add_argument("--all", action="store_true", help="All records")
    g.add_argument("--status", action="store_true", help="Show ingest progress")
    p.add_argument("--execute", action="store_true", help="Actually write (default: dry-run)")
    p.add_argument("--force", action="store_true", help="Re-append even if already ingested")
    args = p.parse_args()

    idx = load_index()

    if args.status:
        bindings = get("/search/domain-stream/list", {"domain": TARGET_DOMAIN})
        print(f"domain   : {TARGET_DOMAIN}")
        print(f"stream   : {STREAM_ID}")
        print(f"bindings : {json.dumps(bindings, ensure_ascii=False)[:300]}")
        print(f"ingested : {len(idx['events'])} records")
        return 0

    records = load_records()
    targets = records if args.all else [r for r in records if r["id"] == args.id]
    if not targets:
        print(f"ERROR: no record matched id={args.id}")
        return 1

    dry = not args.execute
    print("DRY-RUN (pass --execute to write)" if dry else "EXECUTE — writing to TDB")

    if not dry:
        bind = bind_domain()
        print(f"[bind] {TARGET_DOMAIN} <- {STREAM_ID}: "
              f"{'error: ' + bind['error'] if 'error' in bind else 'ok'}")

    ok = skipped = errors = 0
    for rec in targets:
        key = str(rec["id"])
        if key in idx["events"] and not args.force:
            skipped += 1
            continue

        text = record_text(rec)
        if dry:
            print(f"\n[dry-run] id={rec['id']} {title(rec)}  ({len(text)} chars)")
            if len(targets) == 1:
                print("-" * 60)
                print(text)
                print("-" * 60)
            ok += 1
            continue

        resp = append_record(rec)
        if "error" in resp:
            print(f"  ✗ id={rec['id']}: {resp['error']}")
            errors += 1
            continue
        event_id = resp.get("event_id")
        idx["events"][key] = {
            "event_id": event_id,
            "stream_id": STREAM_ID,
            "bianhao": bianhao(rec),
            "title": title(rec),
        }
        save_index(idx)
        print(f"  ✓ id={rec['id']} {title(rec)} → event_id={event_id}")
        ok += 1

    print(f"\n{'='*60}\nok={ok} skipped={skipped} errors={errors}")
    if not dry:
        print(f"index: {INDEX_PATH}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
