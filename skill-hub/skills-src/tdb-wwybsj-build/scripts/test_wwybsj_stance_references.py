#!/usr/bin/env python3

from __future__ import annotations

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from wwybsj_stance import reference_for_upsert  # noqa: E402


class WwybsjStanceReferenceTests(unittest.TestCase):
    def test_reference_for_upsert_preserves_remote_passage(self):
        ref = {
            "property_id": "wwybsj.ref.remote_passage",
            "value": {
                "gateway": "http://source",
                "domain": "archeology",
                "stream_id": "stream-1",
                "event_id": "event-1",
                "source": "chapter.md",
            },
            "source_span": "原文片段",
            "ordinal": 2,
        }

        self.assertEqual(reference_for_upsert("statement-key", ref), {
            "statement_key": "statement-key",
            "property_id": "wwybsj.ref.remote_passage",
            "value_type": "json",
            "value_json": {
                "gateway": "http://source",
                "domain": "archeology",
                "stream_id": "stream-1",
                "event_id": "event-1",
                "source": "chapter.md",
            },
            "source_span": "原文片段",
            "ordinal": 2,
        })


if __name__ == "__main__":
    unittest.main()
