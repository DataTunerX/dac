"""Capability-chain scoring for ``capability_check``.

Implements the aggregation half of ``CAPABILITY_EVALUATION_SCORING_DESIGN.md``
and the weighted-dimension scoring defined in
``CAPABILITY_WEIGHTED_SCORING_DESIGN.md``:

* The LLM decomposes the query into a chain of steps and, for every step,
  scores five conjunctive dimensions (I / D / O / R / C) by listing the
  required items, the matched items, and the resulting ratio.  It also
  reports an evidence grade, a contribution statement, missing requirements
  and a structured reason.  The LLM does **not** output ``can_handle``,
  ``can_contribute`` or ``confidence``.
* This module only performs arithmetic and rule mapping on that output.
* Per-dimension evidence_strength (solid / speculative) determines
  dimension weights: solid=1.0, speculative=0.1.  The O dimension is
  always solid (its three-level scoring is always based on a clear
  declaration or lack thereof).

      step_score   = weighted-arithmetic-mean(I/D/O/R/C)
      handle_score = mean(step_scores)
      can_handle   = handle_score >= THRESHOLD and no unresolved upstream input
      can_contribute = can_handle or exists step with score >= THRESHOLD whose
                       output is needed (final or feeds a later step) and the
                       contribution statement is complete
      confidence   = handle_score | max contributing step score | 0

No content-based scoring lives here.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

SCORE_VERSION = "capability-chain-v1"

# Solid dimensions get full weight; speculative dimensions (D/R when
# the skill body lacks concrete field / topic lists) are down-weighted
# so that LLM guesswork on data coverage and result shape doesn't dominate
# the step score.  See ``CAPABILITY_WEIGHTED_SCORING_DESIGN.md``.
_DIMENSION_WEIGHT: dict[str, float] = {"solid": 1.0, "speculative": 0.1}
# O dimension is always solid — its three-level scoring (1.0/0.7/0.0) is
# always backed by a concrete declaration or a deliberate lack thereof.

# Allowed values of the O (operation capability) dimension.
OPERATION_LEVELS: tuple[float, ...] = (0.0, 0.7, 1.0)

OperationKind = Literal[
    "lookup",
    "filter",
    "aggregate",
    "retrieve",
    "extract",
    "summarize",
    "classify",
    "compare",
    "translate",
    "generate",
    "modify",
]


def get_threshold() -> float:
    """Return the step / handle threshold (env ``CAPABILITY_CHAIN_THRESHOLD``)."""
    raw = os.getenv("CAPABILITY_CHAIN_THRESHOLD", "0.7")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.7
    return max(0.0, min(1.0, value))


# ---------------------------------------------------------------------------
# LLM tool schema
# ---------------------------------------------------------------------------


class InputItem(BaseModel):
    model_config = {"extra": "ignore"}
    name: str = Field(description="输入项名称，如 username、user_id、合同PDF")
    source: Literal["query", "upstream", "missing"] = Field(
        description="来源：query=问题文本或用户附件已给出；upstream=需由上一步产出；missing=都没有"
    )


class RatioCheck(BaseModel):
    """A checklist-backed ratio score: list required items, list matched items, give ratio."""

    model_config = {"extra": "ignore"}
    required: list[str] = Field(default_factory=list, description="该维度所需项清单")
    matched: list[str] = Field(default_factory=list, description="所需项中已满足 / 命中的项")
    ratio: float = Field(description="命中项 / 所需项；所需项为空时为 1.0", ge=0.0, le=1.0)
    evidence_strength: Literal["solid", "speculative"] = Field(
        default="speculative",
        description=(
            "该维度评分的证据强度。solid=依据来自技能正文明确声明（字段列表、主题清单、"
            "输出格式、排除项、数据同步周期等）；speculative=依据来自 Agent 描述或技能短"
            "描述推断，正文中无对应具体声明。"
        ),
    )

    @field_validator("ratio", mode="before")
    @classmethod
    def _clamp_ratio(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))


class StepEvaluation(BaseModel):
    model_config = {"extra": "ignore"}
    step_id: int = Field(description="步骤顺序编号，从 1 开始")
    description: str = Field(default="", description="一句话描述该步骤：输入 → 数据/资源 → 操作 → 产出")
    operation: OperationKind = Field(description="操作类别")
    is_final: bool = Field(description="该步骤的产出是否就是用户要的最终结果（之一）")
    inputs: list[InputItem] = Field(default_factory=list, description="该步骤所需输入及来源")
    outputs: list[str] = Field(default_factory=list, description="该步骤产出项")
    constraints: list[str] = Field(default_factory=list, description="该步骤的限定条件；没有则为空")

    input_match: RatioCheck = Field(description="I 输入匹配")
    data_coverage: RatioCheck = Field(
        description="D 信息覆盖；required 为字段或信息项；步骤不需要外部数据时 required 为空、ratio=1.0"
    )
    operation_capability: float = Field(
        description="O 操作能力，只能取 1.0（正文明确描述 / 等价命令）、0.7（未明确描述但可用已声明工具组合完成）、0（不能做 / 明确不支持）"
    )
    result_match: RatioCheck = Field(description="R 结果匹配")
    constraint_satisfaction: RatioCheck = Field(
        description="C 约束满足；没有约束时 required 为空、ratio=1.0"
    )

    evidence: list[str] = Field(
        default_factory=list,
        description="打分依据：技能正文 / 技能短描述 / Agent 描述 / 问题原文中的原文引用，并注明来源类别",
    )

    @field_validator("operation_capability", mode="before")
    @classmethod
    def _snap_operation(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        f = max(0.0, min(1.0, f))
        return min(OPERATION_LEVELS, key=lambda lvl: abs(lvl - f))


class CapabilityChainResult(BaseModel):
    """Tool-call schema for the capability judge LLM output."""

    model_config = {"extra": "ignore"}
    steps: list[StepEvaluation] = Field(description="按顺序拆分的步骤及各维度评分")
    evidence_grade: Literal["A", "B", "C", "D"] = Field(
        description="证据等级：A=全部依据来自技能正文明确内容；B=主要来自正文、个别依赖短描述；C=主要依赖短描述或 Agent 描述；D=缺乏文本依据"
    )
    contribution: str = Field(
        default="",
        description="按三要素书写：输入（使用哪个已知值 / 需补齐哪个值）、输出（产出哪个具体项）、用途（对应哪个后续步骤的输入或最终结果的哪部分）。不能贡献时留空",
    )
    missing_requirements: list[str] = Field(
        default_factory=list,
        description="本 Agent 无法自行提供、需由请求方或其他 Agent 补齐的输入或数据，注明所属步骤",
    )
    risks: list[str] = Field(
        default_factory=list,
        description="不影响分值的风险提示，如结果唯一性、数据实例可能不存在",
    )
    reason: str = Field(
        description="固定结构：逐步骤列出 I/D/O/R/C 的比例与依据要点，最后一句给结论"
    )


# ---------------------------------------------------------------------------
# Aggregation (arithmetic + rule mapping only)
# ---------------------------------------------------------------------------


def _weight_for(dimension: str, strength: str) -> float:
    """Map ``evidence_strength`` to dimension weight.

    Returns ``_DIMENSION_WEIGHT["speculative"]`` (0.1) when the LLM produces an
    unrecognised or missing value, so malformed output never inflates the weight.
    """
    w = _DIMENSION_WEIGHT.get(strength)
    if w is None:
        logger.warning(
            "[CapabilityChain] dimension %s has invalid evidence_strength=%r, "
            "defaulting to speculative (weight=%.2f)",
            dimension, strength, _DIMENSION_WEIGHT.get("speculative", 0.1),
        )
        return _DIMENSION_WEIGHT.get("speculative", 0.1)
    return w


def step_score(step: StepEvaluation) -> float:
    """Weighted-arithmetic-mean of I/D/O/R/C.

    Solid dimensions carry full weight (1.0); speculative dimensions are
    down-weighted to 0.1 so that LLM guesswork on data coverage (D) and
    result shape (R) does not dominate the step score.

    O is always solid — its three-level scoring (1.0 / 0.7 / 0.0) is always
    backed by a concrete declaration or a deliberate lack thereof.
    """
    dims: list[tuple[float, float]] = [
        (step.input_match.ratio, _weight_for("I", step.input_match.evidence_strength)),
        (step.data_coverage.ratio, _weight_for("D", step.data_coverage.evidence_strength)),
        (step.operation_capability, 1.0),  # O always solid
        (step.result_match.ratio, _weight_for("R", step.result_match.evidence_strength)),
        (
            step.constraint_satisfaction.ratio,
            _weight_for("C", step.constraint_satisfaction.evidence_strength),
        ),
    ]
    weighted_sum = sum(val * w for val, w in dims)
    total_weight = sum(w for _, w in dims)
    return weighted_sum / total_weight if total_weight > 0 else 0.0


def _produced_by_earlier_step(name: str, current: StepEvaluation, steps: list[StepEvaluation]) -> bool:
    """True if a prior step exists that declared ``source="upstream"`` for this input.

    No string matching — trusts the LLM's declared chain topology.  A step with
    ``source="upstream"`` at step_id > 1 means the LLM decomposed the chain to
    produce this input earlier.  step_id == 1 with ``source="upstream"`` means
    the LLM said it depends on something this agent can't produce — external dep.

    Whether the prior step *actually* scores high enough to produce the data is
    handled by ``handle_score``, not here.
    """
    for s in steps:
        if s.step_id < current.step_id:
            return True
    return False


@dataclass
class AggregatedCapability:
    can_handle: bool
    can_contribute: bool
    confidence: float
    handle_score: float
    threshold: float
    contributing_steps: list[int] = field(default_factory=list)
    step_scores: dict[int, float] = field(default_factory=dict)
    has_external_dependency: bool = False
    contribution: str = ""
    missing_requirements: list[str] = field(default_factory=list)

    def steps_payload(self, result: CapabilityChainResult) -> list[dict[str, Any]]:
        """Serialisable per-step detail for the response ``steps`` field."""
        payload: list[dict[str, Any]] = []
        for s in result.steps:
            payload.append(
                {
                    "step_id": s.step_id,
                    "description": s.description,
                    "operation": s.operation,
                    "is_final": s.is_final,
                    "inputs": [i.model_dump() for i in s.inputs],
                    "outputs": list(s.outputs),
                    "constraints": list(s.constraints),
                    "scores": {
                        "I": round(s.input_match.ratio, 3),
                        "D": round(s.data_coverage.ratio, 3),
                        "O": round(s.operation_capability, 3),
                        "R": round(s.result_match.ratio, 3),
                        "C": round(s.constraint_satisfaction.ratio, 3),
                    },
                    "step_score": round(self.step_scores.get(s.step_id, 0.0), 3),
                    "checklists": {
                        "I": {
                            "required": s.input_match.required,
                            "matched": s.input_match.matched,
                            "evidence_strength": s.input_match.evidence_strength,
                        },
                        "D": {
                            "required": s.data_coverage.required,
                            "matched": s.data_coverage.matched,
                            "evidence_strength": s.data_coverage.evidence_strength,
                        },
                        "R": {
                            "required": s.result_match.required,
                            "matched": s.result_match.matched,
                            "evidence_strength": s.result_match.evidence_strength,
                        },
                        "C": {
                            "required": s.constraint_satisfaction.required,
                            "matched": s.constraint_satisfaction.matched,
                            "evidence_strength": s.constraint_satisfaction.evidence_strength,
                        },
                    },
                    "evidence": list(s.evidence),
                }
            )
        return payload


def aggregate(result: CapabilityChainResult, threshold: float | None = None) -> AggregatedCapability:
    """Map the LLM's per-dimension scores to ``can_handle`` / ``can_contribute`` / ``confidence``."""
    thr = get_threshold() if threshold is None else max(0.0, min(1.0, float(threshold)))
    steps = sorted(result.steps, key=lambda s: s.step_id)

    scores: dict[int, float] = {s.step_id: step_score(s) for s in steps}
    handle_score = (
        sum(scores.values()) / len(scores) if scores else 0.0
    )

    # An upstream / missing input that no earlier step of this agent produces
    # means the agent cannot finish the chain alone.
    # ``source="missing"`` → LLM explicitly says no step provides this.  Always external.
    # ``source="upstream"`` at step_id==1 → no prior step exists, external.
    # ``source="upstream"`` at step_id>1  → trust LLM chain topology.
    has_external_dependency = any(
        i.source == "missing"
        or (i.source == "upstream" and not _produced_by_earlier_step(i.name, s, steps))
        for s in steps
        for i in s.inputs
    )

    can_handle = bool(steps) and handle_score >= thr and not has_external_dependency

    # 任何步骤只要能力分达到阈值就能贡献，不区分 final / non-final。
    # LLM 已经通过链拆解决定了产出流向（is_final=true 的是最终答案，
    # is_final=false 是中间步骤）。不需要代码再验证名字是否匹配。
    contributing: list[StepEvaluation] = [
        s
        for s in steps
        if scores[s.step_id] >= thr
    ]

    contribution_text = (result.contribution or "").strip()

    # can_contribute 的两条路：
    # 1. can_handle       — 能独立完成，自然也能贡献
    # 2. contributing 非空 — 有步骤分数到达阈值（纯算术，不依赖 LLM 自评字段）
    #
    # 不再依赖 contribution 字段是否非空，因为 LLM 经常忘记在 tool call 中输出它。
    # contribution 文本作为元信息保留在 AggregatedCapability 中供下游消费。
    can_contribute = can_handle or bool(contributing)

    if can_handle:
        confidence = handle_score
    elif can_contribute:
        confidence = max(scores[s.step_id] for s in contributing)
    else:
        confidence = 0.0

    contributing_ids = [s.step_id for s in contributing]

    return AggregatedCapability(
        can_handle=can_handle,
        can_contribute=can_contribute,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        handle_score=round(handle_score, 3),
        threshold=thr,
        contributing_steps=contributing_ids,
        step_scores=scores,
        has_external_dependency=has_external_dependency,
        contribution=contribution_text if can_contribute else "",
        missing_requirements=[m for m in (result.missing_requirements or []) if str(m).strip()],
    )


def parse_chain_result(data: dict[str, Any]) -> CapabilityChainResult:
    """Validate raw tool-call args into ``CapabilityChainResult``.

    Strips fields that the LLM may inject (``can_handle``, ``confidence``,
    ``contribution_complete``) so validation doesn't fail.
    """
    # 过滤 LLM 可能注入但 schema 不需要的字段
    data = {k: v for k, v in data.items() if k not in ("can_handle", "confidence", "contribution_complete")}
    return CapabilityChainResult.model_validate(data)
