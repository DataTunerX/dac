"""Drift guard for the mid-exec delegation-detection prompt contract.

The detection prompt exists in one production copy plus four test copies that
are kept in sync by hand.  Nothing used to fail when they drifted apart, so a
contract change could silently leave the test copies asserting the *old* rule
(that is exactly what happened with the unstructured-gap rule: the copies still
blessed an open-ended, non-executable sub-query).

This module asserts that the key contract markers of 步骤 1b are present in
every copy, so any future edit must touch all of them.
"""

from __future__ import annotations

import pathlib

import pytest

_HERE = pathlib.Path(__file__).resolve().parent
_REPO = _HERE.parent

# The production prompt is a concatenation of string literals; the test copies
# are plain text.  Search the raw file text in both cases.
_PROMPT_SOURCES = {
    "production": _REPO / "agent" / "skill_agent.py",
    "test_mid_exec_accuracy": _HERE / "test_mid_exec_accuracy.py",
    "test_mid_exec_accuracy_round2": _HERE / "test_mid_exec_accuracy_round2.py",
    "test_mid_exec_detect_prompt": _HERE / "test_mid_exec_detect_prompt.py",
    "test_task_type_detect": _HERE / "test_task_type_detect.py",
}

# Markers that encode the unstructured-gap contract fixed in this change.
_REQUIRED_MARKERS = (
    # Pre-condition: an executable sub-query is a NECESSARY condition.
    "必须先能写出一个下游 SG 用其自身技能可直接执行的具体子问题",
    "写不出明确子问题，就等于没有缺口",
    # synthesized_query is mandatory for unstructured tasks.
    "synthesized_query 是 needs_help=true 的**必要条件**",
    # The 泛指 vs 已点名 distinction (#38).
    "泛指（不委派）",
    "已点名（委派）",
)

# Markers for 步骤 0 task_type classification (capability-gap disambiguation).
# Deliberately generic wording — no benchmark case text.
_CLASSIFICATION_MARKERS = (
    "分类方法（按此程序执行，不要靠关键词或题型印象判断）",
    "写出答案模板",
    "是不是已经存在、只等取回",
    "不等于答案存在",
)


@pytest.mark.parametrize("name", sorted(_PROMPT_SOURCES))
def test_step_0_classification_markers_present(name: str) -> None:
    text = _PROMPT_SOURCES[name].read_text(encoding="utf-8")
    missing = [m for m in _CLASSIFICATION_MARKERS if m not in text]
    assert not missing, (
        f"{name} is out of sync with the 步骤 0 classification rule. "
        f"Missing markers: {missing}"
    )


@pytest.mark.parametrize("name", sorted(_PROMPT_SOURCES))
def test_step_1b_contract_markers_present(name: str) -> None:
    src_path = _PROMPT_SOURCES[name]
    assert src_path.exists(), f"prompt source missing: {src_path}"
    text = src_path.read_text(encoding="utf-8")

    # Sanity: this file really carries a 步骤 1b block.
    assert "步骤 1b" in text, f"{name}: no 步骤 1b block found"

    missing = [m for m in _REQUIRED_MARKERS if m not in text]
    assert not missing, (
        f"{name} is out of sync with the 步骤 1b contract. "
        f"Missing markers: {missing}"
    )


@pytest.mark.parametrize("name", sorted(_PROMPT_SOURCES))
def test_old_open_ended_subquery_rule_fully_removed(name: str) -> None:
    """The previous rule explicitly allowed an empty synthesized_query."""
    text = _PROMPT_SOURCES[name].read_text(encoding="utf-8")
    forbidden = (
        "synthesized_query 可为空",
        "难以精确化为单个查询",
    )
    present = [f for f in forbidden if f in text]
    assert not present, (
        f"{name} still contains the superseded open-ended rule: {present}"
    )