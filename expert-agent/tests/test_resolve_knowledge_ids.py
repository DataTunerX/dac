"""Unit tests for LLM knowledge-id validation / near-miss correction."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.dataservices_client import MetadataValuesResult


REAL_ID = "1eb3f81a-7c0b-4282-b762-dafb11280653"
TYPO_ID = "1eb3f81a-7c0c-4282-b762-dafb11280653"  # b -> c


def _result(item_id: str = REAL_ID, text: str = "orders schema"):
    return MetadataValuesResult(
        status="success",
        data={
            "default_order_management_mysql": [
                {
                    "id": item_id,
                    "text": text,
                    "metadata_value": "order summary",
                }
            ]
        },
    )


def test_resolve_keeps_exact_id():
    blocks = _result()
    assert blocks.resolve_knowledge_ids([REAL_ID]) == [REAL_ID]


def test_resolve_corrects_one_char_typo():
    blocks = _result()
    assert blocks.resolve_knowledge_ids([TYPO_ID]) == [REAL_ID]


def test_resolve_is_case_insensitive():
    blocks = _result()
    assert blocks.resolve_knowledge_ids([REAL_ID.upper()]) == [REAL_ID]


def test_resolve_drops_unrelated_id():
    blocks = _result()
    assert blocks.resolve_knowledge_ids(["00000000-0000-0000-0000-000000000000"]) == []


def test_get_text_by_ids_works_with_typo():
    blocks = _result(text="full schema body")
    text = blocks.get_text_by_ids([TYPO_ID])
    assert "full schema body" in text
    assert REAL_ID in text


def test_resolve_ambiguous_near_miss_is_dropped():
    blocks = MetadataValuesResult(
        status="success",
        data={
            "c": [
                {"id": "aaaa", "text": "a", "metadata_value": "a"},
                {"id": "aaab", "text": "b", "metadata_value": "b"},
            ]
        },
    )
    # "aaac" is hamming=1 from both aaaa and aaab → ambiguous → drop
    assert blocks.resolve_knowledge_ids(["aaac"]) == []
