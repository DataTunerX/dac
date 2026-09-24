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
    """Tool-call schema for the capability judge LLM output (Phase 2 only)."""

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


class DomainCheckResult(BaseModel):
    """Phase 1 domain-overlap check — output by DOMAIN_CHECK_PROMPT, consumed by code
    to decide whether to enter Phase 2 capability decomposition."""

    model_config = {"extra": "ignore"}
    domain_verdict: Literal["has", "none", "uncertain"] = Field(
        description="has=明确有交集，none=明确无交集，uncertain=不确定",
    )
    reason: str = Field(
        description="领域模型比对结论，格式：领域交集：[明确有/明确无/不确定] — 问题领域：[L1/L2/L3]；Agent 声明：[正文对应声明/正文无对应声明]",
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

    # ── 领域不匹配硬门槛 ──
    # 当所有步骤的 D 维度都是 ratio=0 且 evidence_strength=solid 时，
    # 说明 Agent 的所有技能都明确不覆盖该问题领域（skill 正文没有相关字段
    # /主题清单，或有明确的排除项声明）。
    # 这是硬中断：加权平均不应补偿 D=0，直接判不可处理。
    if steps and all(
        s.data_coverage.ratio == 0.0 and s.data_coverage.evidence_strength == "solid"
        for s in steps
    ):
        logger.info(
            "[CapabilityChain] Domain mismatch detected: all %d steps have "
            "D=0(solid). Short-circuit to cannot_handle.",
            len(steps),
        )
        return AggregatedCapability(
            can_handle=False,
            can_contribute=False,
            confidence=0.0,
            handle_score=0.0,
            threshold=thr,
        )

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

    # can_handle 要求 **每一个步骤** 都达到阈值，而不是均值。
    # 均值会掩盖个别低分步骤（如 step1=1.0, step2=0.4, thr=0.7，均值 0.7 过线但
    # step2 实际不可执行），导致 Agent 声称"能独立完成"但某步实际上做不了。
    can_handle = bool(steps) and all(s >= thr for s in scores.values()) and not has_external_dependency

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


def format_steps_detail(
    result: CapabilityChainResult,
    step_scores: dict[int, float],
    max_desc_len: int = 40,
    max_evidence_len: int = 80,
) -> str:
    """Build a one-line per-step dimension detail string for capability logs.

    Each step is rendered as::

        步骤{id}[{description}]={step_score} final={yes|no}
        I={matched}/{total} D={matched}/{total} O={val} R={matched}/{total} C={matched}/{total},
        依据: {evidence_text}

    Multiple steps are joined with ``; ``.

    Args:
        result: The capability chain result from the judge LLM.
        step_scores: Per-step weighted scores from :func:`aggregate`.
        max_desc_len: Truncate step descriptions to this length.
        max_evidence_len: Truncate evidence text to this length.

    Returns:
        Compact string suitable for a single-line log entry.
    """
    parts: list[str] = []
    for s in sorted(result.steps, key=lambda s_: s_.step_id):
        desc = (s.description or "").strip()
        if not desc and s.operation:
            desc = str(s.operation)
        if len(desc) > max_desc_len:
            desc = desc[:max_desc_len] + "..."

        step_score = step_scores.get(s.step_id, 0.0)
        final = "yes" if s.is_final else "no"

        # I — 输入匹配
        i_total = len(s.input_match.required) if s.input_match.required else 0
        i_matched = len(s.input_match.matched)

        # D — 数据覆盖
        d_total = len(s.data_coverage.required) if s.data_coverage.required else 0
        d_matched = len(s.data_coverage.matched)

        # O — 操作能力（单值）
        o_val = s.operation_capability

        # R — 结果匹配
        r_total = len(s.result_match.required) if s.result_match.required else 0
        r_matched = len(s.result_match.matched)

        # C — 约束满足
        c_total = len(s.constraint_satisfaction.required) if s.constraint_satisfaction.required else 0
        c_matched = len(s.constraint_satisfaction.matched)

        dim_str = (
            f"I={i_matched}/{i_total or '-'} "
            f"D={d_matched}/{d_total or '-'} "
            f"O={o_val:.1f} "
            f"R={r_matched}/{r_total or '-'} "
            f"C={c_matched}/{c_total or '-'}"
        )

        # Evidence citations
        ev_parts: list[str] = []
        for ev in s.evidence[:2]:
            ev_text = str(ev).strip()
            if len(ev_text) > max_evidence_len:
                ev_text = ev_text[:max_evidence_len] + "..."
            ev_parts.append(ev_text)
        ev_str = "; ".join(ev_parts)

        line = f"步骤{s.step_id}[{desc}]={step_score:.2f} final={final} {dim_str}"
        if ev_str:
            line += f", 依据: {ev_str}"
        parts.append(line)

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Markdown-formatted capability chain log (human-readable structured output)
# ---------------------------------------------------------------------------

# ── Labels for operation_kind values (used in markdown log) ──

def _operation_label(kind: str) -> str:
    """Return the raw operation_kind value as display label — no hardcoded mapping."""
    return str(kind)


def format_capability_chain_md(
    result: CapabilityChainResult,
    agg: AggregatedCapability,
    agent_name: str = "",
    query: str = "",
    domain_verdict: str = "",
    latency_ms: int = 0,
    max_evidence_len: int = 120,
) -> str:
    """Render a full capability-check result as structured markdown for logging.

    Args:
        result: Capability chain result from Phase 2 LLM.
        agg: Aggregated scores.
        agent_name: Agent display name.
        query: User query.
        domain_verdict: Phase 1 domain-overlap verdict ("has"/"none"/"uncertain").
        latency_ms: Total latency across both phases.
        max_evidence_len: Max evidence string length.

    Sections:
    1. 结论摘要（handle / contribute / confidence ...）
    2. §〇 领域交集前置检查
    3. 步骤拆解与逐维度打分（含每个维度的 required/matched 清单与依据）
    """
    lines: list[str] = []

    # ── Header ──
    lines.append("")
    lines.append(f"## Capability Check — agent=`{agent_name}`")
    if query:
        q = query[:200].replace("\n", " ")
        lines.append(f"> query: _{q}_")
    lines.append("")

    # ── 1. 结论摘要 ──
    handle_label = "✓ 能" if agg.can_handle else "✗ 不能"
    contribute_label = "✓ 能" if agg.can_contribute else "✗ 不能"

    lines.append("### 结论摘要")
    lines.append(f"- **独立处理**: {handle_label} (`can_handle={agg.can_handle}`)")
    lines.append(f"- **贡献步骤**: {contribute_label} (`can_contribute={agg.can_contribute}`)")
    lines.append(f"- **handle_score**: `{agg.handle_score:.3f}`  (threshold={agg.threshold:.2f})")
    lines.append(f"- **confidence**: `{agg.confidence:.2f}`")
    lines.append(f"- **evidence_grade**: `{result.evidence_grade}`")
    if domain_verdict:
        lines.append(f"- **domain_verdict**: `{domain_verdict}`")
    lines.append(f"- **has_external_dependency**: `{agg.has_external_dependency}`")
    if agg.contributing_steps:
        lines.append(f"- **contributing_steps**: `{agg.contributing_steps}`")
    else:
        lines.append("- **contributing_steps**: （无）")
    lines.append(f"- **latency_ms**: `{latency_ms}`")
    lines.append("")

    # ── 2. §〇 领域交集前置检查 ──
    if domain_verdict:
        lines.append("### §〇 前置检查：领域交集判定")
        lines.append(f"**结论**: `{domain_verdict}`")
    else:
        lines.append("### §〇 前置检查：领域交集判定")
        lines.append("**结论**: （未执行 — 无步骤时不检查领域交集）")
    # Show missing requirements if any
    if agg.missing_requirements:
        lines.append("**缺失项**:")
        for m in agg.missing_requirements:
            lines.append(f"- {m}")
    if agg.contribution:
        lines.append(f"**贡献声明**: {agg.contribution}")
    # Show risks
    if result.risks:
        lines.append("**风险提示**:")
        for r in result.risks:
            lines.append(f"- {r}")
    lines.append("")

    # ── 3. 步骤拆解与逐维度打分 ──
    steps = sorted(result.steps, key=lambda s: s.step_id)
    if not steps:
        lines.append("### 步骤拆解与逐维度打分")
        lines.append("> （无步骤 — 领域无交集或空结果）")
        lines.append("")
    else:
        lines.append(f"### 步骤拆解与逐维度打分（共 {len(steps)} 步）")
        lines.append("")

        for s in steps:
            step_s = agg.step_scores.get(s.step_id, 0.0)
            final_label = "✓ 最终产出" if s.is_final else "→ 中间步骤"
            desc = (s.description or "").strip() or str(s.operation)

            lines.append(f"#### 步骤 {s.step_id}: {desc}")
            lines.append(f"- **step_score**: `{step_s:.3f}`  |  **操作**: `{_operation_label(str(s.operation))}`  |  类型: {final_label}")
            lines.append("")

            # Inputs
            if s.inputs:
                lines.append("**输入**:")
                for inp in s.inputs:
                    src = {"query": "来自问题/附件", "upstream": "来自上一步", "missing": "缺失"}.get(str(inp.source), str(inp.source))
                    lines.append(f"  - `{inp.name}` ({src})")
                lines.append("")

            # Outputs
            if s.outputs:
                lines.append("**预期产出**:")
                for o in s.outputs:
                    lines.append(f"  - `{o}`")
                lines.append("")

            # Constraints
            if s.constraints:
                lines.append("**约束条件**:")
                for c in s.constraints:
                    lines.append(f"  - `{c}`")
                lines.append("")

            # Per-dimension scoring table
            lines.append("**维度打分**:")
            lines.append("")
            lines.append(
                "| 维度 | 说明 | 所需项 | 命中项 | 得分 | 证据 |\n"
                "|------|------|--------|--------|------|------|"
            )

            dims: list[tuple[str, str, 'RatioCheck | None', float]] = [
                ("I", "输入匹配", s.input_match, s.input_match.ratio),
                ("D", "信息覆盖", s.data_coverage, s.data_coverage.ratio),
                ("O", "操作能力", None, s.operation_capability),
                ("R", "结果匹配", s.result_match, s.result_match.ratio),
                ("C", "约束满足", s.constraint_satisfaction, s.constraint_satisfaction.ratio),
            ]
            for dim_name, dim_label, rc, score in dims:
                if rc is not None:
                    req = ", ".join(rc.required) if rc.required else "（无需）"
                    mat = ", ".join(rc.matched) if rc.matched else "（无命中）"
                    es = rc.evidence_strength
                    lines.append(
                        f"| **{dim_name}** | {dim_label} | {req} | {mat} "
                        f"| `{score:.1f}` | {es} |"
                    )
                else:
                    # O dimension — always solid
                    lines.append(
                        f"| **{dim_name}** | {dim_label} | — | — "
                        f"| `{score:.1f}` | solid ✓ |"
                    )
            lines.append("")

            # Evidence
            if s.evidence:
                lines.append("**打分依据**:")
                for ev in s.evidence[:4]:
                    ev_text = str(ev).strip()
                    if len(ev_text) > max_evidence_len:
                        ev_text = ev_text[:max_evidence_len] + "..."
                    lines.append(f"  - {ev_text}")
                lines.append("")

            lines.append("---")
            lines.append("")

    # ── LLM reason ──
    reason = (result.reason or "").strip()
    if reason:
        lines.append("### LLM 结构化理由（reason）")
        lines.append("```")
        lines.append(reason[:3000])
        lines.append("```")
        lines.append("")

    return "\n".join(lines)




def parse_chain_result(data: dict[str, Any]) -> CapabilityChainResult:
    """Validate raw tool-call args into ``CapabilityChainResult``.

    Strips fields that the LLM may inject (``can_handle``, ``confidence``,
    ``contribution_complete``) so validation doesn't fail.
    """
    # 过滤 LLM 可能注入但 schema 不需要的字段
    data = {k: v for k, v in data.items() if k not in ("can_handle", "confidence", "contribution_complete")}
    return CapabilityChainResult.model_validate(data)
