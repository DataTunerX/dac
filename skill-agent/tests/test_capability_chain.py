"""Unit tests for capability_chain scoring and aggregation.

Arithmetic-mean scoring (post-refactor)
=======================================
step_score  = (I + D + O + R + C) / 5          # arithmetic mean, no zero gating
handle_score = mean(step_scores)                # arithmetic mean across steps
"""

import pytest
import os
from dataclasses import field
from typing import Any

from agent.capability_chain import (
    CapabilityChainResult,
    StepEvaluation,
    RatioCheck,
    AggregatedCapability,
    aggregate,
    step_score,
    parse_chain_result,
    get_threshold,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FULL = {"required": ["x"], "matched": ["x"], "ratio": 1.0}


def rc(required: list[str], matched: list[str]) -> RatioCheck:
    n = len(required)
    return RatioCheck(required=required, matched=matched, ratio=len(matched) / n if n else 1.0)


def step(
    step_id: int,
    *,
    is_final: bool = True,
    operation: str = "lookup",
    inputs: list[tuple[str, str]] | None = None,
    outputs: list[str] | None = None,
    constraints: list[str] | None = None,
    I: RatioCheck | None = None,
    D: RatioCheck | None = None,
    O: float = 1.0,
    R: RatioCheck | None = None,
    C: RatioCheck | None = None,
) -> StepEvaluation:
    return StepEvaluation.model_validate(
        {
            "step_id": step_id,
            "description": "",
            "operation": operation,
            "is_final": is_final,
            "inputs": [
                {"name": name, "source": src}
                for name, src in (inputs or [])
            ],
            "outputs": list(outputs or []),
            "constraints": list(constraints or []),
            "input_match": (I or rc(["x"], ["x"])).model_dump(),
            "data_coverage": (D or rc(["x"], ["x"])).model_dump(),
            "operation_capability": O,
            "result_match": (R or I or rc(["x"], ["x"])).model_dump(),
            "constraint_satisfaction": (C or rc(["x"], ["x"])).model_dump(),
            "evidence": [],
        }
    )


def result(
    steps: list[StepEvaluation],
    *,
    contribution: str = "",
    grade: str = "A",
    missing: list[str] | None = None,
) -> CapabilityChainResult:
    return CapabilityChainResult(
        steps=steps,
        evidence_grade=grade,
        contribution=contribution,
        missing_requirements=list(missing or []),
        risks=[],
        reason="test",
    )


# ── helper: arithmetic mean ──
def am(*vals: float) -> float:
    return sum(vals) / len(vals) if vals else 0.0


# ---------------------------------------------------------------------------
# Basic step_score
# ---------------------------------------------------------------------------

def test_step_score_is_arithmetic_mean_of_five_dimensions():
    # I=0.5 D=1.0 O=0.7 R=1.0 C=0.5 → (3.7/5) = 0.74
    s = step(1, is_final=True, I=rc(["a", "b"], ["a"]), D=rc(["x"], ["x"]), O=0.7,
             R=rc(["r"], ["r"]), C=rc(["c1", "c2"], ["c1"]))
    assert step_score(s) == pytest.approx(0.74)


def test_zero_dimension_does_not_zero_step():
    """Arithmetic mean: a single zero dimension pulls the score down but not to zero."""
    s = step(1, is_final=True, D=rc(["订单"], []))
    # I=1 D=0 O=1 R=1 C=1 → 4/5 = 0.8
    assert step_score(s) == pytest.approx(0.8)


def test_operation_capability_snaps_to_allowed_levels():
    assert StepEvaluation.model_validate(
        {**step(1, is_final=True).model_dump(), "operation_capability": 0.65}
    ).operation_capability == 0.7
    assert StepEvaluation.model_validate(
        {**step(1, is_final=True).model_dump(), "operation_capability": 0.2}
    ).operation_capability == 0.0
    assert StepEvaluation.model_validate(
        {**step(1, is_final=True).model_dump(), "operation_capability": 1}
    ).operation_capability == 1.0


def test_ratio_is_clamped():
    assert RatioCheck(required=["a"], matched=["a"], ratio=1.4).ratio == 1.0
    assert RatioCheck(required=["a"], matched=[], ratio=-0.2).ratio == 0.0


# ---------------------------------------------------------------------------
# Design doc case 12.1: user-agent, "张三买了哪些东西"
# ---------------------------------------------------------------------------

def case_user_agent() -> CapabilityChainResult:
    s1 = step(1, is_final=False, inputs=[("username", "query")], outputs=["user_id"],
              I=rc(["username"], ["username"]), D=rc(["用户名", "用户ID"], ["用户名", "用户ID"]),
              O=1.0, R=rc(["user_id"], ["user_id"]))
    s2 = step(2, is_final=True, inputs=[("user_id", "upstream")], outputs=["商品列表"],
              I=rc(["user_id"], ["user_id"]), D=rc(["订单", "商品"], []), O=1.0, R=rc(["商品列表"], []))
    return result([s1, s2], contribution="输入 username=张三，输出 user_id，供步骤 2 查询订单使用",
                  missing=["订单/购买记录数据（步骤 2）"])


def test_case_12_1_user_agent_contributes_step_1_with_full_confidence():
    agg = aggregate(case_user_agent(), threshold=0.7)
    # s1: (1+1+1+1+1)/5=1.0   s2: (1+0+1+0+1)/5=0.6   handle = 0.8 > 0.7
    assert agg.handle_score == pytest.approx(0.8)
    assert agg.can_handle is True  # both steps avg above threshold, no external dep
    assert agg.can_contribute is True
    assert agg.confidence == pytest.approx(0.8)
    assert agg.contributing_steps == [1]  # s2=0.6 < 0.7
    assert agg.has_external_dependency is False
    assert agg.contribution.startswith("输入 username=张三")
    assert agg.missing_requirements == ["订单/购买记录数据（步骤 2）"]


# ---------------------------------------------------------------------------
# Design doc case 12.2: order-agent, "张三买了哪些东西"
# ---------------------------------------------------------------------------

def case_order_agent() -> CapabilityChainResult:
    s1 = step(1, is_final=False, inputs=[("username", "query")], outputs=["user_id"],
              I=rc(["username"], ["username"]), D=rc(["用户名", "用户ID"], []), R=rc(["user_id"], []))
    s2 = step(2, is_final=True, inputs=[("user_id", "upstream")], outputs=["商品列表"],
              I=rc(["user_id"], ["user_id"]), D=rc(["订单", "商品名"], ["订单", "商品名"]),
              O=1.0, R=rc(["商品列表"], ["商品列表"]))
    return result([s1, s2], contribution="需补齐 user_id，输出该用户的商品列表，对应最终结果",
                  missing=["user_id"])


def test_case_12_2_order_agent_contributes_final_step_but_depends_on_user_id():
    agg = aggregate(case_order_agent(), threshold=0.7)
    # s1: (1+0+1+0+1)/5=0.6   s2: (1+1+1+1+1)/5=1.0   handle=0.8≥0.7
    assert agg.handle_score == pytest.approx(0.8)
    assert agg.can_handle is True  # arithmetic mean passes, no external dep (upstream from internal step)
    assert agg.can_contribute is True
    assert agg.confidence == pytest.approx(0.8)  # handle_score when can_handle=True
    assert agg.contributing_steps == [2]  # s1=0.6 < 0.7 excluded
    assert agg.missing_requirements == ["user_id"]


# ---------------------------------------------------------------------------
# Design doc case 12.3: composable operation O=0.7
# ---------------------------------------------------------------------------

def test_case_12_3_composable_operation_yields_high_handle():
    s = step(1, operation="aggregate", is_final=True, inputs=[("时间范围", "query")],
             outputs=["商品", "销量", "排名"], I=rc(["时间范围"], ["时间范围"]),
             D=rc(["商品名", "下单时间"], ["商品名", "下单时间"]), O=0.7,
             R=rc(["商品", "销量", "排名"], ["商品", "销量", "排名"]), C=rc(["上个月"], ["上个月"]))
    agg = aggregate(result([s]), threshold=0.7)
    # (1 + 1 + 0.7 + 1 + 1) / 5 = 0.94
    assert agg.handle_score == pytest.approx(0.94)
    assert agg.can_handle is True
    assert agg.can_contribute is True
    assert agg.confidence == pytest.approx(0.94)
    assert agg.contributing_steps == [1]


# ---------------------------------------------------------------------------
# Design doc case 12.4: constraints not satisfied + modify unsupported
# ---------------------------------------------------------------------------

def test_case_12_4_constraint_failure_contributing():
    s1 = step(1, operation="filter", is_final=False,
              inputs=[("user_id", "upstream"), ("时间范围", "query")], outputs=["未付款订单列表"],
              I=rc(["user_id", "时间范围"], ["user_id", "时间范围"]),
              D=rc(["下单时间", "支付状态", "订单ID"], ["下单时间", "支付状态", "订单ID"]),
              O=1.0, R=rc(["订单列表"], ["订单列表"]), C=rc(["实时", "近30天"], ["近30天"]))
    s2 = step(2, operation="modify", is_final=True, inputs=[("未付款订单列表", "upstream")],
              outputs=["删除结果"], O=0.0, C=rc(["可写"], []))
    agg = aggregate(result([s1, s2], contribution=""), threshold=0.7)
    # s1: (1+1+1+1+0.5)/5 = 0.9  s2: (1+1+0+1+0)/5 = 0.6
    assert agg.step_scores[1] == pytest.approx(0.9)
    assert agg.step_scores[2] == pytest.approx(0.6)
    # s1.inputs has source="upstream" at step_id=1 → external dependency → can_handle=False
    assert agg.has_external_dependency is True
    assert agg.can_handle is False
    assert agg.can_contribute is True  # s1=0.9 ≥ 0.7, s2 excluded
    assert agg.confidence == pytest.approx(0.9)  # max contributing: s1=0.9
    assert agg.contributing_steps == [1]
    assert agg.contribution == ""


# ---------------------------------------------------------------------------
# Design doc case 12.5: unstructured HR QA, two independent final steps
# ---------------------------------------------------------------------------

def test_case_12_5_unstructured_qa_contributes_first_final_step():
    s1 = step(1, operation="retrieve", is_final=True, inputs=[("入职时间", "query")], outputs=["年假天数"],
              I=rc(["入职时间"], ["入职时间"]), D=rc(["年假天数规则", "入职年限换算"], ["年假天数规则", "入职年限换算"]),
              O=1.0, R=rc(["天数"], ["天数"]), C=rc(["今年"], ["今年"]))
    s2 = step(2, operation="retrieve", is_final=True, outputs=["归属规则"],
              D=rc(["期权归属规则"], []), O=1.0, R=rc(["规则说明"], ["规则说明"]))
    agg = aggregate(result([s1, s2], grade="B",
                           contribution="输入 入职时间=去年，输出 年假天数及出处，对应最终结果的年假部分"),
                    threshold=0.7)
    # s1: (1+1+1+1+1)/5=1.0  s2: (1+0+1+1+1)/5=0.8  handle=0.9≥0.7
    assert agg.can_handle is True  # arithmetic mean passes
    assert agg.can_contribute is True
    assert agg.confidence == pytest.approx(0.9)  # handle_score when can_handle=True
    assert agg.contributing_steps == [1, 2]  # both ≥ 0.7


# ---------------------------------------------------------------------------
# Design doc case 12.6: unstructured multi-step with cross-agent dependency
# ---------------------------------------------------------------------------

def test_case_12_6_contract_review_contributes_steps_1_and_3():
    s1 = step(1, operation="extract", is_final=True, inputs=[("合同PDF", "query")], outputs=["风险条款列表"],
              I=rc(["合同PDF"], ["合同PDF"]), D=rc(["采购合同风险规则"], ["采购合同风险规则"]),
              O=1.0, R=rc(["风险条款列表"], ["风险条款列表"]), C=rc(["英文"], ["英文"]))
    s2 = step(2, operation="retrieve", is_final=False, inputs=[("合同名称", "query")], outputs=["去年版本文本"],
              I=rc(["合同名称"], ["合同名称"]), D=rc(["合同归档库"], []), O=1.0, R=rc(["去年版本文本"], []))
    s3 = step(3, operation="compare", is_final=True,
              inputs=[("风险条款列表", "upstream"), ("去年版本文本", "upstream")], outputs=["变化说明"],
              I=rc(["风险条款列表", "去年版本文本"], ["风险条款列表", "去年版本文本"]),
              D=rc(["x"], ["x"]), O=0.7, R=rc(["变化说明"], ["变化说明"]))
    agg = aggregate(result([s1, s2, s3], contribution="输入 合同PDF，输出 风险条款列表（风险部分）；补齐 去年版本文本 后可输出 两版差异说明",
                           missing=["去年版本合同文本（步骤 2）"]), threshold=0.7)
    # s1: (1+1+1+1+1)/5=1.0  s2: (1+0+1+0+1)/5=0.6  s3: (1+1+0.7+1+1)/5=0.94
    assert agg.step_scores[1] == pytest.approx(1.0)
    assert agg.step_scores[2] == pytest.approx(0.6)
    assert agg.step_scores[3] == pytest.approx(0.94)
    # handle = (1.0+0.6+0.94)/3 = 0.847 ≥ 0.7
    # external_dep: s3 inputs have source="upstream" at step_id=3, prior steps exist → not external
    assert agg.can_handle is True  # arithmetic mean passes, no external dep
    assert agg.can_contribute is True
    assert agg.contributing_steps == [1, 3]  # s2=0.6 < 0.7 excluded
    assert agg.confidence == pytest.approx(0.85)  # handle_score rounded to 2dp
    assert agg.has_external_dependency is False


# ---------------------------------------------------------------------------
# Rule details
# ---------------------------------------------------------------------------

def test_can_handle_requires_no_unresolved_upstream_input():
    # step_id=1 with source="upstream" → external dependency → can_handle=False
    s = step(1, is_final=True, inputs=[("user_id", "upstream")], outputs=["商品列表"],
             I=rc(["user_id"], ["user_id"]), D=rc(["订单"], ["订单"]), R=rc(["商品列表"], ["商品列表"]))
    agg = aggregate(result([s], contribution="需补齐 user_id，输出商品列表，对应最终结果"),
                    threshold=0.7)
    assert agg.handle_score == pytest.approx(1.0)  # all 1.0s
    assert agg.has_external_dependency is True
    assert agg.can_handle is False
    assert agg.can_contribute is True
    assert agg.confidence == pytest.approx(1.0)


def test_missing_input_source_blocks_handle():
    s = step(1, is_final=True, inputs=[("订单号", "missing")], I=rc(["订单号"], []))
    # I=0 D=1 O=1 R=1 C=1 → 0.8. source="missing" → external. can_handle=False
    agg = aggregate(result([s]), threshold=0.7)
    assert agg.can_handle is False
    # contributing: step score 0.8 ≥ 0.7 → contributing=[1]
    # But R is defaulted (same as I which is rc(["x"],["x"]) for no R provided, so R=1.0)
    # Actually the `step()` helper uses `R=I` as fallback. I=rc(["订单号"],[]) → ratio=0
    # So: I=0 D=1 O=1 R=0 C=1 → (0+1+1+0+1)/5 = 0.6 < 0.7
    # contributing=[] → can_contribute=False
    assert agg.can_contribute is False


def test_empty_contribution_still_allows_contribute():
    """即使 contribution 为空，只要 contributing steps 非空就判 can_contribute=True。

    contribution 字段是 LLM 的元信息输出，LLM 经常忘记填。can_contribute 的核心信号
    是 contributing_steps（纯算术计算），不依赖 contribution 是否非空。
    """
    r = case_user_agent()
    r.contribution = ""
    agg = aggregate(r, threshold=0.7)
    assert agg.contributing_steps == [1]
    assert agg.can_contribute is True


def test_can_handle_implies_can_contribute_even_without_contribution_text():
    s = step(1, is_final=True, inputs=[("x", "query")], I=rc(["x"], ["x"]), D=rc(["f"], ["f"]),
             R=rc(["y"], ["y"]))
    agg = aggregate(result([s], contribution=""), threshold=0.7)
    assert agg.can_handle is True
    assert agg.can_contribute is True


def test_any_step_with_sufficient_score_is_contributing():
    """任何步骤能力分 ≥ 阈值就是贡献者，不验证下游是否真的需要。"""
    s1 = step(1, is_final=False, outputs=["orphan"], inputs=[("a", "query")], I=rc(["a"], ["a"]))
    s2 = step(2, is_final=True, inputs=[("b", "missing")], I=rc(["b"], []), outputs=["answer"])
    # s1: (1+1+1+1+1)/5 = 1.0  s2: (0+1+1+0+1)/5 = 0.6
    agg = aggregate(result([s1, s2], contribution="输入 a，输出 orphan，无人使用"), threshold=0.7)
    assert agg.contributing_steps == [1]  # s2=0.6 < 0.7 excluded
    assert agg.can_contribute is True


def test_threshold_boundaries():
    s = step(1, is_final=True, O=0.7)
    # (1+1+0.7+1+1)/5 = 0.94
    assert aggregate(result([s]), threshold=0.7).can_handle is True
    assert aggregate(result([s]), threshold=0.95).can_handle is False


def test_threshold_env_default_and_override(monkeypatch):
    monkeypatch.delenv("CAPABILITY_CHAIN_THRESHOLD", raising=False)
    assert get_threshold() == 0.7
    monkeypatch.setenv("CAPABILITY_CHAIN_THRESHOLD", "0.9")
    assert get_threshold() == 0.9
    monkeypatch.setenv("CAPABILITY_CHAIN_THRESHOLD", "abc")
    assert get_threshold() == 0.7


def test_empty_steps_yield_zero():
    agg = aggregate(result([]), threshold=0.7)
    assert agg.can_handle is False
    assert agg.can_contribute is False
    assert agg.confidence == 0.0
    assert agg.handle_score == 0.0


def test_evidence_grade_does_not_change_confidence():
    a = aggregate(case_user_agent(), threshold=0.7)
    b = aggregate(CapabilityChainResult(**{**case_user_agent().model_dump(), "evidence_grade": "D"}), threshold=0.7)
    assert a.confidence == b.confidence


def test_parse_chain_result_accepts_raw_tool_args_and_ignores_extras():
    raw = {
        "evidence_grade": "A",
        "steps": [
            {
                "step_id": 1,
                "description": "lookup user",
                "operation": "lookup",
                "is_final": True,
                "inputs": [{"name": "username", "source": "query"}],
                "outputs": ["user_id"],
                "constraints": [],
                "evidence": ["技能正文：grep 张三 data/users.txt"],
                "input_match": {"required": ["username"], "matched": ["username"], "ratio": 1.0},
                "data_coverage": {"required": ["用户名"], "matched": ["用户名"], "ratio": "1.0"},
                "operation_capability": 1,
                "result_match": {"required": ["user_id"], "matched": ["user_id"], "ratio": 1.0},
                "constraint_satisfaction": {"required": [], "matched": [], "ratio": 1.0},
            }
        ],
        "contribution": "",
        "contribution_complete": False,
        "missing_requirements": [],
        "risks": [],
        "reason": "ok",
        "confidence": 0.3,
        "can_handle": True,
    }
    parsed = parse_chain_result(raw)
    agg = aggregate(parsed, threshold=0.7)
    assert agg.can_handle is True
    assert agg.confidence == pytest.approx(1.0)


def test_steps_payload_contains_scores_and_checklists():
    r = case_user_agent()
    agg = aggregate(r, threshold=0.7)
    payload = agg.steps_payload(r)
    assert [p["step_id"] for p in payload] == [1, 2]
    assert payload[0]["scores"] == {"I": 1.0, "D": 1.0, "O": 1.0, "R": 1.0, "C": 1.0}
    # s2: I=1.0 D=0 R=0 → (1+0+1+0+1)/5 = 0.6
    assert payload[1]["step_score"] == pytest.approx(0.6)
    assert payload[1]["checklists"]["D"]["required"] == ["订单", "商品"]