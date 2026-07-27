#!/usr/bin/env python3
"""Emit a recognizable receipt proving the downloaded skill can execute."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", default="dynamic skill execution succeeded")
    args = parser.parse_args()

    print(
        json.dumps(
            {
                "skill": "dynamic-skill-demo",
                "version": "1.0.0",
                "dynamic_skill_loaded": True,
                "message": args.message,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
