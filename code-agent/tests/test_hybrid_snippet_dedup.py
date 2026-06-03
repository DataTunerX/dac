"""Tests for hybrid search snippet line-range deduplication."""

from __future__ import annotations

from agent.tools.snippet_dedup import (
    merge_hybrid_code_snippets,
    parse_line_range,
    range_contains,
    ranges_overlap,
    should_skip_grep_snippet,
)


def _lines(n: int, prefix: str = "line") -> str:
    return "\n".join(f"{prefix}{i}" for i in range(1, n + 1))


def _snippet(
    *,
    file_path: str = "code.py",
    name: str = "code_block",
    line_no: str = "",
    source: str = "skill_read_code",
    relevance_reason: str = "",
    business_meaning: str = "",
    code_content: str = "",
) -> dict:
    parsed = parse_line_range(line_no)
    if parsed and not code_content:
        start, end = parsed
        code_content = _lines(end - start + 1, prefix=f"{name}:")
    return {
        "file_path": file_path,
        "name": name,
        "line_no": line_no,
        "source": source,
        "relevance_reason": relevance_reason,
        "business_meaning": business_meaning,
        "code_content": code_content,
    }


def _expand_range(line_no: str) -> set[int]:
    parsed = parse_line_range(line_no)
    if not parsed:
        return set()
    start, end = parsed
    return set(range(start, end + 1))


def _covered_lines(snippets: list[dict]) -> set[int]:
    covered: set[int] = set()
    for snippet in snippets:
        covered |= _expand_range(snippet.get("line_no", ""))
    return covered


def _production_semantic_snippets() -> list[dict]:
    return [
        _snippet(name="get_order_total_amount", line_no="361-365", source="semantic"),
        _snippet(name="get_order_items", line_no="341-349", source="semantic"),
        _snippet(name="get_all_orders", line_no="307-315", source="semantic"),
        _snippet(name="get_orders_by_user", line_no="296-305", source="semantic"),
        _snippet(name="fetch_one", line_no="73-86", source="semantic"),
        _snippet(name="fetch_all", line_no="58-71", source="semantic"),
    ]


def _production_grep_snippets() -> list[dict]:
    return [
        _snippet(name="ProductService", line_no="194-270", source="skill_read_code"),
        _snippet(name="OrderItemService", line_no="327-365", source="skill_read_code"),
        _snippet(name="ECommerceService", line_no="367-414", source="skill_read_code"),
        _snippet(name="DatabaseManager", line_no="11-86", source="skill_read_code"),
        _snippet(name="imports", line_no="1-10", source="skill_read_code"),
        _snippet(name="main", line_no="417-449", source="skill_read_code"),
        _snippet(name="OrderService", line_no="272-325", source="skill_read_code"),
    ]


def test_parse_line_range_range_and_single():
    assert parse_line_range("341-349") == (341, 349)
    assert parse_line_range("365") == (365, 365)
    assert parse_line_range(" 361-365 ") == (361, 365)
    assert parse_line_range("365-361") == (361, 365)
    assert parse_line_range("") is None
    assert parse_line_range("abc") is None


def test_range_contains_and_overlap():
    outer = (327, 365)
    inner = (341, 349)
    assert range_contains(outer, inner)
    assert not range_contains(inner, outer)
    assert ranges_overlap((327, 365), (367, 414)) is False
    assert ranges_overlap((360, 370), (365, 375)) is True


def test_should_not_skip_when_skill_class_contains_semantic_method():
    existing = [
        _snippet(name="get_order_items", line_no="341-349", source="semantic"),
    ]
    new = _snippet(line_no="327-365", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is False


def test_should_skip_when_grep_is_subset_of_existing():
    existing = [_snippet(line_no="327-365", source="semantic")]
    new = _snippet(line_no="341-349", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is True


def test_should_keep_non_overlapping_skill_block():
    existing = [
        _snippet(name="get_order_items", line_no="341-349", source="semantic"),
    ]
    new = _snippet(line_no="194-270", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is False


def test_should_keep_adjacent_non_overlapping_blocks():
    existing = [_snippet(line_no="327-365", source="semantic")]
    new = _snippet(line_no="367-414", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is False


def test_should_keep_partial_overlap_blocks_conservatively():
    existing = [_snippet(name="get_order_items", line_no="341-349", source="semantic")]
    new = _snippet(line_no="345-400", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is False


def test_merge_replaces_semantic_methods_with_complete_class_blocks():
    semantic = [
        _snippet(name="get_order_items", line_no="341-349", source="semantic"),
        _snippet(name="get_order_total_amount", line_no="361-365", source="semantic"),
        _snippet(name="get_orders_by_user", line_no="296-305", source="semantic"),
        _snippet(name="get_all_orders", line_no="307-315", source="semantic"),
        _snippet(name="fetch_all", line_no="58-71", source="semantic"),
        _snippet(name="fetch_one", line_no="73-86", source="semantic"),
    ]
    grep = [
        _snippet(line_no="194-270", source="skill_read_code"),
        _snippet(line_no="327-365", source="skill_read_code"),
        _snippet(line_no="367-414", source="skill_read_code"),
        _snippet(line_no="11-86", source="skill_read_code"),
        _snippet(line_no="1-10", source="skill_read_code"),
        _snippet(line_no="417-449", source="skill_read_code"),
        _snippet(line_no="272-325", source="skill_read_code"),
    ]

    merged, semantic_count, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = (
        merge_hybrid_code_snippets(semantic, grep)
    )

    assert semantic_count == 0
    assert grep_only_count == 7
    assert overlap_skipped == 0
    assert overlap_replaced == 6
    assert len(dedup_report["events"]) == 6
    assert len(merged) == 7
    assert {row["line_no"] for row in merged} == {
        "194-270",
        "327-365",
        "367-414",
        "11-86",
        "1-10",
        "417-449",
        "272-325",
    }


def test_merge_metadata_local_replaces_semantic_with_complete_block():
    semantic = [
        _snippet(name="fetch_one", line_no="73-86", source="semantic"),
    ]
    grep = [
        _snippet(name="fetch_one", line_no="73-86", source="metadata"),
        _snippet(name="DatabaseManager", line_no="11-86", source="metadata"),
    ]

    merged, semantic_count, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = (
        merge_hybrid_code_snippets(semantic, grep)
    )

    assert len(merged) == 1
    assert merged[0]["line_no"] == "11-86"
    assert semantic_count == 0
    assert grep_only_count == 1
    assert overlap_skipped == 1
    assert overlap_replaced == 1


def test_merge_overlap_sources_annotation_when_replacing():
    semantic = [
        _snippet(
            name="get_order_items",
            line_no="341-349",
            source="semantic",
            relevance_reason="method relevance",
        ),
    ]
    grep = [
        _snippet(line_no="327-365", source="skill_read_code"),
    ]

    merged, _, _, overlap_skipped, overlap_replaced, dedup_report = merge_hybrid_code_snippets(
        semantic,
        grep,
        merge_overlap_sources=True,
    )

    assert overlap_skipped == 0
    assert overlap_replaced == 1
    assert len(merged) == 1
    assert merged[0]["line_no"] == "327-365"
    assert merged[0]["also_found_by"] == ["semantic"]
    assert merged[0]["supersedes"] == [
        {"name": "get_order_items", "line_no": "341-349", "source": "semantic"}
    ]
    assert merged[0]["superseded_relevance"] == ["method relevance"]


def test_merge_keeps_both_on_partial_overlap():
    semantic = [
        _snippet(name="get_order_items", line_no="341-349", source="semantic"),
    ]
    grep = [
        _snippet(line_no="345-400", source="skill_read_code"),
    ]

    merged, semantic_count, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = (
        merge_hybrid_code_snippets(semantic, grep)
    )

    assert len(merged) == 2
    assert len(dedup_report["events"]) == 0
    assert semantic_count == 1
    assert grep_only_count == 1
    assert overlap_skipped == 0
    assert overlap_replaced == 0


def test_single_line_subset_is_skipped():
    existing = [
        _snippet(name="get_order_total_amount", line_no="361-365", source="semantic"),
    ]
    new = _snippet(line_no="365", source="skill_read_code")
    assert should_skip_grep_snippet(new, existing) is True


def test_production_fixture_merges_to_seven_without_line_loss():
    semantic = _production_semantic_snippets()
    grep = _production_grep_snippets()

    before_lines = _covered_lines(semantic + grep)
    merged, semantic_count, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = (
        merge_hybrid_code_snippets(semantic, grep)
    )
    after_lines = _covered_lines(merged)

    assert len(merged) == 7
    assert len([e for e in dedup_report["events"] if e["action"] == "replace_with_complete_block"]) == 6
    assert semantic_count == 0
    assert grep_only_count == 7
    assert overlap_skipped == 0
    assert overlap_replaced == 6
    assert before_lines.issubset(after_lines)
    assert after_lines == before_lines


def test_truncated_outer_block_does_not_replace_semantic_methods():
    semantic = [
        _snippet(
            name="fetch_one",
            line_no="73-86",
            source="semantic",
            code_content=_lines(14, "fetch_one:"),
        ),
    ]
    grep = [
        _snippet(
            name="DatabaseManager",
            line_no="11-86",
            source="skill_read_code",
            code_content=_lines(5, "truncated:"),
        ),
    ]

    merged, semantic_count, grep_only_count, _, overlap_replaced, dedup_report = merge_hybrid_code_snippets(
        semantic, grep
    )

    assert len(merged) == 2
    assert semantic_count == 1
    assert grep_only_count == 1
    assert overlap_replaced == 0
    assert any(row["name"] == "fetch_one" for row in merged)


def test_truncated_existing_does_not_skip_complete_grep_subset():
    existing = [
        _snippet(
            name="DatabaseManager",
            line_no="11-86",
            source="semantic",
            code_content=_lines(3, "truncated:"),
        ),
    ]
    new = _snippet(
        name="fetch_one",
        line_no="73-86",
        source="skill_read_code",
        code_content=_lines(14, "fetch_one:"),
    )

    assert should_skip_grep_snippet(new, existing) is False


def test_different_files_are_never_merged_by_range():
    semantic = [_snippet(file_path="a.py", name="foo", line_no="1-10", source="semantic")]
    grep = [_snippet(file_path="b.py", line_no="1-10", source="skill_read_code")]

    merged, semantic_count, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = (
        merge_hybrid_code_snippets(semantic, grep)
    )

    assert len(merged) == 2
    assert semantic_count == 1
    assert grep_only_count == 1
    assert overlap_skipped == 0
    assert overlap_replaced == 0


def test_grep_order_smaller_block_before_larger_class():
    semantic = [
        _snippet(name="fetch_one", line_no="73-86", source="semantic"),
        _snippet(name="fetch_all", line_no="58-71", source="semantic"),
    ]
    grep = [
        _snippet(name="fetch_one", line_no="73-86", source="skill_read_code"),
        _snippet(name="DatabaseManager", line_no="11-86", source="skill_read_code"),
    ]

    merged, _, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = merge_hybrid_code_snippets(
        semantic, grep
    )

    assert len(merged) == 1
    assert merged[0]["line_no"] == "11-86"
    assert grep_only_count == 1
    assert overlap_skipped == 1
    assert overlap_replaced == 2


def test_empty_line_no_does_not_trigger_range_dedup():
    semantic = [_snippet(name="unknown", line_no="", source="semantic", code_content="x")]
    grep = [_snippet(line_no="1-10", source="skill_read_code")]

    merged, _, grep_only_count, overlap_skipped, overlap_replaced, dedup_report = merge_hybrid_code_snippets(
        semantic, grep
    )

    assert len(merged) == 2
    assert grep_only_count == 1
    assert overlap_skipped == 0
    assert overlap_replaced == 0


def test_total_code_content_not_reduced_when_outer_is_truncated():
    semantic = [
        _snippet(
            name="get_order_items",
            line_no="341-349",
            source="semantic",
            code_content=_lines(9, "method:"),
        ),
    ]
    grep = [
        _snippet(
            name="OrderItemService",
            line_no="327-365",
            source="skill_read_code",
            code_content=_lines(8, "partial-class:"),
        ),
    ]

    merged, _, _, _, overlap_replaced, dedup_report = merge_hybrid_code_snippets(semantic, grep)
    total_content_lines = sum(
        len((row.get("code_content") or "").splitlines()) for row in merged
    )

    assert overlap_replaced == 0
    assert len(merged) == 2
    assert total_content_lines == 17
