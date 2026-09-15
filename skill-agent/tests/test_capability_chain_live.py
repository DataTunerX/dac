"""Live LLM tests for the capability-chain judge (SKILL_CAPABILITY_CHECK_PROMPT).

Replays the six worked examples of CAPABILITY_EVALUATION_SCORING_DESIGN.md
section 12 against a real model and checks that the LLM's per-dimension
ratios, once aggregated by ``agent.capability_chain.aggregate``, reproduce the
documented conclusions (can_handle / can_contribute / confidence band /
evidence grade / step count).

Requires:
  DASHSCOPE_API_KEY  (Aliyun DashScope API key)
  DASHSCOPE_MODEL    (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=sk-... \\
    python -m pytest tests/test_capability_chain_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import capability_chain  # noqa: E402
from agent import skill_agent as sa  # noqa: E402
from agent.tool_call_utils import invoke_llm_with_tool  # noqa: E402
from model_sdk.api.model_manager import ModelManager  # noqa: E402


pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live capability chain tests",
)

TOL = 0.15  # documented tolerance for per-dimension ratios


def _skill_md(name: str) -> str:
    body = (ROOT / "tests" / "test_skills" / name / "SKILL.md").read_text(encoding="utf-8")
    # Strip frontmatter; the judge sees the SKILL.md body as AgentSkill.description.
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) == 3:
            body = parts[2]
    return body.strip()


def _skills_block(name: str, body: str) -> str:
    return f"### 技能：{name}\n{body}"


USER_SKILLS = _skills_block("user_query", _skill_md("user-query"))

# The design doc's order skill carries 商品名 / 金额 / 下单时间 / 支付状态; the
# bundled test skill only has 订单号|订单状态|商品ID|用户ID. Use the doc's version
# so the cases line up with the documented ratios.
ORDER_SKILL_BODY = """# 订单查询能力

## 数据来源
订单数据存储在 `data/orders.txt` 文件中，每日凌晨同步一次（非实时），每行一条记录，字段以 `|` 分隔：
- 字段1：订单ID（如 ORD-001）
- 字段2：用户ID（如 U001）
- 字段3：商品名
- 字段4：金额
- 字段5：下单时间（YYYY-MM-DD HH:MM:SS）
- 字段6：支付状态（未付款、已付款、已退款）

## 数据查询方式
- 读取全部订单：`cat data/orders.txt`
- 按用户ID查询：`grep "U001" data/orders.txt`
- 按订单ID查询：`grep "ORD-001" data/orders.txt`
- 按支付状态查询：`grep "未付款" data/orders.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 查询某个用户的全部订单
2. 查询某个订单的详细信息
3. 按支付状态筛选订单
4. 统计用户的订单数量

## 注意事项
- 按用户ID查询，不含用户名；如需按用户名查找，请先使用 user_query 技能获取用户ID
- 本技能只读，不提供订单的修改、删除或状态变更
"""
ORDER_SKILLS = _skills_block("order_query", ORDER_SKILL_BODY)

HR_SKILL_BODY = """# HR 制度问答

## 覆盖范围
- 文档集：公司 HR 制度文档库
- 主题：考勤、请假、报销、差旅、福利
- 版本：2022–2025 年各版本，每季度更新
- 语言：中文

## 处理流程
1. 根据问题在制度文档中检索相关章节
2. 对检索到的章节做摘要，形成回答
3. 回答附带出处（文档名、章节）

## 输入 / 输出
- 输入：中文问题文本
- 输出：文本回答 + 出处

## 注意事项
- 不覆盖薪酬体系与期权相关内容
"""
HR_SKILLS = _skills_block("hr_policy_qa", HR_SKILL_BODY)

CONTRACT_SKILL_BODY = """# 合同审查

## 输入
- 合同文件：PDF 或 Docx
- 语言：支持中文与英文合同

## 能力
- 条款抽取：识别并抽取合同条款
- 风险标注：对照风险规则库标注风险条款；规则库覆盖采购合同、劳动合同、租赁合同
- 允许使用的工具：文本抽取、文本处理（diff、grep、awk）

## 输出
- 风险条款列表：条款号、原文、风险等级、说明

## 注意事项
- 不提供合同归档检索，历史版本需由调用方提供
- 不做翻译
"""
CONTRACT_SKILLS = _skills_block("contract_review", CONTRACT_SKILL_BODY)


@dataclass(frozen=True)
class ChainCase:
    name: str
    query: str
    agent_name: str
    agent_description: str
    skills: str
    expect_can_handle: bool
    expect_can_contribute: bool
    expect_confidence: float
    expect_steps: tuple[int, ...]
    expect_evidence: tuple[str, ...] = ("A",)
    expect_contributing_steps: tuple[int, ...] = ()
    expect_missing_substrings: tuple[str, ...] = field(default_factory=tuple)


CASES = [
    ChainCase(
        "doc_12_1_user_agent_zhangsan_purchases",
        "张三买了哪些东西",
        "user-agent",
        "用户信息查询智能体",
        USER_SKILLS,
        expect_can_handle=False,
        expect_can_contribute=True,
        expect_confidence=1.0,
        expect_steps=(2,),
        expect_contributing_steps=(1,),
        expect_missing_substrings=("订单",),
    ),
    ChainCase(
        "doc_12_2_order_agent_zhangsan_purchases",
        "张三买了哪些东西",
        "order-agent",
        "订单查询智能体",
        ORDER_SKILLS,
        expect_can_handle=False,
        expect_can_contribute=True,
        expect_confidence=1.0,
        expect_steps=(2,),
        expect_contributing_steps=(2,),
        expect_missing_substrings=("user_id", "用户ID"),
    ),
    ChainCase(
        "doc_12_3_order_agent_monthly_ranking",
        "统计上个月每个商品的销量排名",
        "order-agent",
        "订单查询智能体",
        ORDER_SKILLS,
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_confidence=0.7,
        expect_steps=(1, 2),
        expect_contributing_steps=(1,),
    ),
    ChainCase(
        "doc_12_4_order_agent_realtime_delete",
        "查一下张三最近 30 天的实时订单，删除其中未付款的",
        "order-agent",
        "订单查询智能体",
        ORDER_SKILLS,
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_confidence=0.0,
        expect_steps=(2, 3),
    ),
    ChainCase(
        "doc_12_5_hr_agent_annual_leave_and_options",
        "去年入职的员工今年能休几天年假？期权归属规则是什么？",
        "hr-policy-agent",
        "HR 制度问答智能体",
        HR_SKILLS,
        expect_can_handle=False,
        expect_can_contribute=True,
        expect_confidence=1.0,
        expect_steps=(2,),
        expect_evidence=("A", "B"),
        expect_contributing_steps=(1,),
        expect_missing_substrings=("期权",),
    ),
    ChainCase(
        "doc_12_6_contract_agent_risks_and_diff",
        "总结这份英文采购合同的风险点，并对比去年版本的变化（附件：合同 PDF）",
        "contract-review-agent",
        "合同审查智能体",
        CONTRACT_SKILLS,
        expect_can_handle=False,
        expect_can_contribute=True,
        expect_confidence=1.0,
        expect_steps=(3, 4),
        expect_contributing_steps=(1,),
        expect_missing_substrings=("去年", "历史"),
    ),
]


def _llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731"),
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


async def _judge(case: ChainCase) -> dict[str, Any]:
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=case.agent_name,
        agent_description=case.agent_description,
        agent_skills=case.skills,
        history="(none)",
        query=case.query,
    )
    tool = StructuredTool(
        name="evaluate_capability",
        description="按步骤链与 I/D/O/R/C 五个维度评估本智能体对用户问题的能力",
        args_schema=capability_chain.CapabilityChainResult,
        func=None,
        coroutine=None,
    )
    data = await invoke_llm_with_tool(
        llm=_llm(),
        tool=tool,
        messages=[HumanMessage(content=prompt)],
        metadata={
            "run_id": f"chain-live-{case.name}",
            "trace_id": "e" * 32,
            "user_id": "capability-chain-live",
        },
        tool_choice="evaluate_capability",
        span_name="capability-chain-live",
        span_input={"query": case.query, "case": case.name},
    )
    assert data is not None, "LLM did not call evaluate_capability"
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_capability_chain_live(case: ChainCase):
    raw = await _judge(case)
    chain = capability_chain.parse_chain_result(raw)
    agg = capability_chain.aggregate(chain, threshold=0.7)

    print(f"\n[{case.name}] handle={agg.can_handle} contribute={agg.can_contribute} "
          f"conf={agg.confidence} handle_score={agg.handle_score} evidence={chain.evidence_grade}")
    for s in chain.steps:
        print(f"  step {s.step_id} ({s.operation}, final={s.is_final}): "
              f"I={s.input_match.ratio:.2f} D={s.data_coverage.ratio:.2f} O={s.operation_capability:.1f} "
              f"R={s.result_match.ratio:.2f} C={s.constraint_satisfaction.ratio:.2f} "
              f"-> {agg.step_scores[s.step_id]:.2f}  inputs={[i.model_dump() for i in s.inputs]}")
    print(f"  contribution={chain.contribution!r} complete={chain.contribution_complete}")
    print(f"  missing={chain.missing_requirements} risks={chain.risks}")
    print(f"  reason={chain.reason[:400]}")

    # Every ratio dimension must carry a checklist (or be an explicit "no requirement").
    for s in chain.steps:
        for dim in (s.input_match, s.data_coverage, s.result_match, s.constraint_satisfaction):
            if dim.required:
                assert 0.0 <= dim.ratio <= 1.0
            else:
                assert dim.ratio == pytest.approx(1.0), "empty checklist must mean ratio 1.0"
        assert s.operation_capability in capability_chain.OPERATION_LEVELS

    assert len(chain.steps) in case.expect_steps
    assert agg.can_handle is case.expect_can_handle
    assert agg.can_contribute is case.expect_can_contribute
    assert agg.confidence == pytest.approx(case.expect_confidence, abs=TOL)
    assert chain.evidence_grade in case.expect_evidence
    for sid in case.expect_contributing_steps:
        assert sid in agg.contributing_steps, agg.contributing_steps
    if case.expect_missing_substrings:
        blob = " ".join(chain.missing_requirements)
        assert any(sub in blob for sub in case.expect_missing_substrings), blob
    if agg.can_contribute and not agg.can_handle:
        # contribution_complete may come from the heuristic fallback in
        # parse_chain_result / aggregate, not explicitly from the LLM.
        assert (chain.contribution_complete is True) or chain.contribution_complete is None
        assert len(chain.contribution) >= 10
