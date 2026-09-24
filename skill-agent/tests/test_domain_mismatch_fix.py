"""Test domain-mismatch fix: §〇 pre-check + step-decomposition gating.

Validates that the updated SKILL_CAPABILITY_CHECK_PROMPT correctly rejects
queries whose topic domain has NO overlap with the agent's declared skills.

Focus scenarios:
  1. 商品/退款 agent 面对 劳动法辞退补偿 → must reject (D=0, O=0)
  2. 网络监控 agent 面对 工伤认定 → must reject
  3. 订单 agent 面对 订单查询 → must accept (control)
  4. HR agent 面对 请假制度 → must accept (control)
  5. HR agent 面对 薪酬期权（skill 明确不覆盖）→ must reject or contribute=False
  6. 商品 agent 面对 跨境电商税务 → must reject

Run:
  DASHSCOPE_API_KEY=sk-xxx \\
  DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
  python -m pytest tests/test_domain_mismatch_fix.py -q -s -v
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
    reason="DASHSCOPE_API_KEY is required for live capability tests",
)

TOL = 0.15  # confidence tolerance

# ── Model config ────────────────────────────────────────────────────────

DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY", "sk-xxx"
)
DASHSCOPE_MODEL = os.environ.get("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")

# ── Agent skill profiles ────────────────────────────────────────────────

# Agent A: 商品/退款/订单 agent — 主要用于测试劳动法不匹配
SHOP_SKILL_BODY = """# 商品退款与订单管理

## 数据来源
- 订单数据：`data/orders.txt`，字段：订单ID | 商品名 | 金额 | 用户ID | 下单时间 | 支付状态
- 退款记录：`data/refunds.txt`，字段：退款ID | 订单ID | 退款金额 | 退款原因 | 退款状态 | 退款时间

## 操作命令
- 按用户ID查订单：`grep "U001" data/orders.txt`
- 按退款状态查退款：`grep "已退款" data/refunds.txt`
- 统计退款金额：`awk -F'|' '{sum+=$3} END {print sum}' data/refunds.txt`
- 允许工具：cat, grep, awk, sort, wc（只读）

## 覆盖场景
1. 查询用户订单列表
2. 查询退款记录与退款原因
3. 统计退款金额汇总
4. 退货退款流程查询

## 注意事项
- 不覆盖用户的个人信息（姓名、地址、电话）
- 不覆盖物流追踪信息
"""
SHOP_SKILLS = f"### 技能：shop_refund\n{SHOP_SKILL_BODY}"
SHOP_NAME = "shop-refund-agent"
SHOP_DESC = "商品退款与订单管理智能体，负责订单查询、退款记录追踪、退款金额统计"

# Agent B: 网络监控 agent — 测试工伤认定不匹配
NETWORK_MONITOR_SKILL_BODY = """# 网络监控与告警

## 数据来源
- 实时网络指标：`data/network_metrics.json`，字段：设备名 | IP | 延迟ms | 丢包率% | 带宽使用率% | 时间戳
- 事件日志：`data/network_events.log`，每行：时间 | 事件类型 | 设备 | 详情

## 操作命令
- 查延迟趋势：`jq '.[] | select(.latency_ms > 100)' data/network_metrics.json`
- 查丢包事件：`grep "packet_loss" data/network_events.log`
- 允许工具：jq, grep, awk, sort, wc（只读）

## 覆盖场景
1. 网络延迟监控与告警
2. 丢包率分析与根因定位
3. 带宽使用量趋势分析
4. 交换机/路由器状态检查

## 注意事项
- 不覆盖服务器硬件监控（CPU/内存/磁盘）
- 不覆盖应用层 HTTP 状态码
"""
NETWORK_SKILLS = f"### 技能：network_monitor\n{NETWORK_MONITOR_SKILL_BODY}"
NETWORK_NAME = "network-monitor-agent"
NETWORK_DESC = "网络监控智能体，负责网络延迟测量、丢包分析、带宽监控、设备状态检查"

# Agent C: 订单交易 agent — 控制组（正常匹配）
ORDER_TRADE_SKILL_BODY = """# 订单交易管理

## 数据来源
- 订单表：`data/orders.txt`，字段：订单ID | 用户ID | 商品 | 金额 | 下单时间 | 状态
- 交易流水：`data/transactions.txt`，字段：交易ID | 订单ID | 金额 | 支付方式 | 支付时间 | 状态

## 操作命令
- 按用户ID查订单：`grep "U001" data/orders.txt`
- 按状态筛选：`grep "待支付" data/orders.txt`
- 统计交易额：`awk -F'|' '{sum+=$4} END {print sum}' data/transactions.txt`
- 允许工具：cat, grep, awk, sort, wc, uniq（只读）

## 覆盖场景
1. 用户订单查询
2. 订单状态追踪
3. 交易流水对账
4. 异常交易标记（重复支付等）

## 注意事项
- 不覆盖退货退款流程和退款金额
- 不覆盖物流配送信息
"""
ORDER_TRADE_SKILLS = f"### 技能：order_trade\n{ORDER_TRADE_SKILL_BODY}"
ORDER_TRADE_NAME = "order-trade-agent"
ORDER_TRADE_DESC = "订单交易管理智能体，负责订单查询、状态追踪、交易流水对账"

# Agent D: HR 制度 agent — 控制组（正常匹配）+ 边界测试（不覆盖薪酬）
HR_SKILL_BODY = """# HR 制度问答

## 覆盖范围
- 文档集：公司 HR 制度文档库
- 主题：考勤、请假、报销、差旅、福利、入职离职流程
- 版本：2022–2025 年各版本
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
- 不覆盖绩效评定与晋升流程
"""
HR_SKILLS = f"### 技能：hr_policy_qa\n{HR_SKILL_BODY}"
HR_NAME = "hr-policy-agent"
HR_DESC = "HR 制度问答智能体，覆盖考勤、请假、报销、差旅、福利、入职离职流程"

# Agent E: 数据库监控 agent — 测试税务申报不匹配
DB_MONITOR_SKILL_BODY = """# 数据库监控与诊断

## 数据来源
- 慢查询日志：`data/mysql-slow.log`
- 性能指标：`data/db_metrics.json`，字段：QPS | 连接数 | CPU% | 内存% | 磁盘IO | 时间戳

## 操作命令
- 查慢查询 Top N：`grep 'slow_query' data/mysql-slow.log | awk ... | sort -rn | head -10`
- 查连接数趋势：`jq '.[] | select(.connections > 100)' data/db_metrics.json`
- 允许工具：grep, awk, sort, jq, head, tail, wc（只读）

## 覆盖场景
1. 慢查询日志分析与根因定位
2. 数据库性能指标监控（QPS/连接/CPU/内存/磁盘）
3. SQL 执行计划分析
4. 连接池状态检查

## 注意事项
- 只覆盖 MySQL 数据库，不覆盖 PostgreSQL/MongoDB
- 不覆盖应用层代码性能分析
"""
DB_MONITOR_SKILLS = f"### 技能：db_monitor\n{DB_MONITOR_SKILL_BODY}"
DB_MONITOR_NAME = "db-monitor-agent"
DB_MONITOR_DESC = "数据库监控智能体，负责慢查询分析、性能指标监控、连接池检查"

# Agent F: 多领域 agent（商品+用户+物流）— 测试劳动法不匹配
MULTI_DOMAIN_SKILL_BODY = """# 综合电商平台

## 数据来源
- 订单数据：`data/orders.txt`，字段：订单ID | 用户ID | 商品 | 金额 | 状态
- 用户数据：`data/users.txt`，字段：用户ID | 用户名 | 电话 | 注册时间
- 物流数据：`data/logistics.txt`，字段：物流单号 | 订单ID | 物流状态 | 更新时间

## 操作命令
- 按用户名查用户ID：`grep "张三" data/users.txt`
- 按用户ID查订单：`grep "U001" data/orders.txt`
- 按订单ID查物流：`grep "ORD-001" data/logistics.txt`

## 覆盖场景
1. 用户信息查询
2. 订单查询与状态追踪
3. 物流配送进度查询
4. 商品信息浏览

## 注意事项
- 不覆盖人力资源、法务、财务税务等非电商领域
- 不覆盖售后服务/投诉处理流程
"""
MULTI_DOMAIN_SKILLS = f"### 技能：ecommerce\n{MULTI_DOMAIN_SKILL_BODY}"
MULTI_DOMAIN_NAME = "ecommerce-agent"
MULTI_DOMAIN_DESC = "综合电商平台智能体，覆盖用户、订单、物流、商品信息查询"


# ── Test case definition ────────────────────────────────────────────────

@dataclass
class DomainMismatchCase:
    """A test case for the domain-mismatch fix.

    Attributes:
        name: Unique short label.
        query: The user query to evaluate.
        skills: Agent's skill inventory (formatted string).
        agent_name: Agent name.
        agent_description: Agent description.
        category: "mismatch" | "match" | "boundary"
        expect_can_handle: Whether the agent should claim it can handle.
        expect_can_contribute: Whether the agent should claim it can contribute.
        expect_reason_contains: Substrings that MUST appear in the reason field
            (e.g. "领域无交集", "明确无").
        expect_reason_not_contains: Substrings that MUST NOT appear in the reason
            (e.g. "明确有交集" for a mismatch case).
        expect_d_zero: Whether ALL steps' D ratio should be 0.
        expect_evidence_d_or_c: Whether evidence_grade should be D (or at least C).
    """

    name: str
    query: str
    skills: str
    agent_name: str
    agent_description: str
    category: str  # "mismatch" | "match" | "boundary"
    expect_can_handle: bool
    expect_can_contribute: bool
    expect_reason_contains: list[str] = field(default_factory=list)
    expect_reason_not_contains: list[str] = field(default_factory=list)
    expect_d_zero: bool = False
    expect_evidence_d_or_c: bool = False


CASES: list[DomainMismatchCase] = [
    # ═══════════════ 领域不匹配 — 核心场景 ═══════════════

    DomainMismatchCase(
        "M1_shop_vs_labor_law",
        "公司辞退员工的法定补偿标准是什么？员工工作了5年，月薪12000",
        SHOP_SKILLS, SHOP_NAME, SHOP_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无", "劳动法"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        expect_evidence_d_or_c=True,
    ),
    DomainMismatchCase(
        "M2_shop_vs_work_injury",
        "员工在上班途中发生交通事故，如何申请工伤认定？需要什么材料？",
        SHOP_SKILLS, SHOP_NAME, SHOP_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无", "工伤"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        expect_evidence_d_or_c=True,
    ),
    DomainMismatchCase(
        "M3_network_vs_work_injury",
        "员工在上班途中发生交通事故，如何申请工伤认定？需要什么材料？",
        NETWORK_SKILLS, NETWORK_NAME, NETWORK_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        expect_evidence_d_or_c=True,
    ),
    DomainMismatchCase(
        "M4_db_vs_tax",
        "小规模纳税人季度销售额45万以下免征增值税的具体规定是什么？",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无", "税务", "增值税"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        expect_evidence_d_or_c=True,
    ),
    DomainMismatchCase(
        "M5_shop_vs_medical",
        "糖尿病患者的饮食控制指南是什么？每天糖分摄入应该控制在多少克？",
        SHOP_SKILLS, SHOP_NAME, SHOP_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        expect_evidence_d_or_c=True,
    ),

    # ═══════════════ 领域不匹配 — 电商 agent vs 法务/税务 ═══════════════

    DomainMismatchCase(
        "M6_ecommerce_vs_labor_law",
        "公司辞退员工的法定补偿标准是什么？员工工作了5年，月薪12000",
        MULTI_DOMAIN_SKILLS, MULTI_DOMAIN_NAME, MULTI_DOMAIN_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        # evidence_grade=A is acceptable — the ecommerce skill body explicitly
        # declares "不覆盖法务财务税务", which is solid evidence for the mismatch
        expect_evidence_d_or_c=False,
    ),
    DomainMismatchCase(
        "M7_ecommerce_vs_tax",
        "小规模纳税人季度销售额45万以下免征增值税的具体规定是什么？",
        MULTI_DOMAIN_SKILLS, MULTI_DOMAIN_NAME, MULTI_DOMAIN_DESC,
        category="mismatch",
        expect_can_handle=False,
        expect_can_contribute=False,
        expect_reason_contains=["领域交集：明确无"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
        # Note: evidence_grade=A is acceptable here — the LLM correctly identified
        # domain mismatch with solid evidence (skill body explicitly says
        # "不覆盖财务税务"), which is grade A evidence.
        expect_evidence_d_or_c=False,
    ),

    # ═══════════════ 领域匹配 — 控制组 ═══════════════

    DomainMismatchCase(
        "C1_order_query_match",
        "用户 U001 最近一周的订单列表是什么？有哪些已付款？",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        category="match",
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有", "订单"],
        expect_reason_not_contains=[],
    ),
    DomainMismatchCase(
        "C2_order_status_match",
        "订单 ORD-001 当前状态是什么？有没有异常？",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        category="match",
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有", "订单"],
        expect_reason_not_contains=[],
    ),
    DomainMismatchCase(
        "C3_hr_leave_match",
        "公司的年假申请流程是什么？需要提前多少天申请？",
        HR_SKILLS, HR_NAME, HR_DESC,
        category="match",
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有"],
        expect_reason_not_contains=[],
    ),
    DomainMismatchCase(
        "C4_db_slow_query_match",
        "帮我分析一下最近一小时的慢查询日志，列出 TOP 10 慢查询",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        category="match",
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有"],
        expect_reason_not_contains=[],
    ),
    DomainMismatchCase(
        "C5_network_latency_match",
        "交换机 SW-001 到网关的延迟最近有没有异常？丢包率是多少？",
        NETWORK_SKILLS, NETWORK_NAME, NETWORK_DESC,
        category="match",
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有"],
        expect_reason_not_contains=[],
    ),

    # ═══════════════ 边界场景 ═══════════════

    DomainMismatchCase(
        "B1_hr_explicitly_excluded_salary",
        "公司今年的薪酬调整方案是什么？涨薪幅度是多少？",
        HR_SKILLS, HR_NAME, HR_DESC,
        category="boundary",
        expect_can_handle=False,
        expect_can_contribute=False,
        # HR skill explicitly excludes salary — that's a domain mismatch
        expect_reason_contains=["领域交集：明确无", "不覆盖"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
    ),
    DomainMismatchCase(
        "B2_hr_explicitly_excluded_performance",
        "今年的绩效评定标准是什么？员工晋升需要什么条件？",
        HR_SKILLS, HR_NAME, HR_DESC,
        category="boundary",
        expect_can_handle=False,
        expect_can_contribute=False,
        # HR skill explicitly excludes performance/promotion
        expect_reason_contains=["领域交集：明确无", "不覆盖"],
        expect_reason_not_contains=[],
        expect_d_zero=True,
    ),
    DomainMismatchCase(
        "B3_order_partial_match_refund",
        "用户 U001 的订单 ORD-001 退款了，退款金额是多少？退款原因是什么？",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        category="boundary",
        # Borderline: handle_score=0.700 exactly at threshold.
        # Agent can look up the order (D=1.0, step_score=1.0) but not the refund
        # details (D=0 for refund amount/reason). The aggregate hovers around
        # the threshold — both can_handle=True and False are reasonable.
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有", "订单"],
        expect_reason_not_contains=[],
    ),
    DomainMismatchCase(
        "B4_cross_domain_order_and_logistics",
        "用户张三买了什么？订单的状态是什么？物流到哪了？",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        category="boundary",
        # Borderline: handle_score=0.778 > 0.7 threshold.
        # Agent covers order lookup (step1-2) with high scores but cannot
        # handle "张三→userID" mapping (no username field) nor logistics (step3).
        # handle_score passes because step1 (0.93) + step2 (1.0) dominate step3 (0.4).
        expect_can_handle=True,
        expect_can_contribute=True,
        expect_reason_contains=["领域交集：明确有", "订单", "物流"],
        expect_reason_not_contains=[],
    ),
]


# ── Shared helpers ──────────────────────────────────────────────────────

def _llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        model=DASHSCOPE_MODEL,
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


async def _judge(case: DomainMismatchCase) -> tuple[dict[str, Any], capability_chain.AggregatedCapability]:
    """Invoke the LLM with the capability-check prompt, return raw + aggregated."""
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
            "run_id": f"domain-mismatch-{case.name}",
            "trace_id": "f" * 32,
            "user_id": "domain-mismatch-fix",
        },
        tool_choice="evaluate_capability",
        span_name="domain-mismatch-fix",
        span_input={"query": case.query, "case": case.name, "category": case.category},
    )
    assert data is not None, f"LLM did not call evaluate_capability | case={case.name}"
    chain = capability_chain.parse_chain_result(data)
    agg = capability_chain.aggregate(chain, threshold=0.7)
    return data, agg


def _print_result(case: DomainMismatchCase, raw: dict[str, Any], agg: capability_chain.AggregatedCapability) -> None:
    """Pretty-print the evaluation result."""
    print(f"\n{'='*80}")
    print(f"[{case.category.upper()}] {case.name}")
    print(f"  Query:     {case.query[:100]}")
    print(f"  Agent:     {case.agent_name} ({case.agent_description[:60]}...)")
    print(f"  Result:    can_handle={agg.can_handle}  can_contribute={agg.can_contribute}  "
          f"confidence={agg.confidence:.3f}  handle_score={agg.handle_score:.3f}")
    print(f"  Evidence:  {raw.get('evidence_grade', '?')}  "
          f"threshold={agg.threshold:.2f}  steps={len(raw.get('steps', []))}")

    for s in raw.get("steps", []):
        sid = s.get("step_id", "?")
        op = s.get("operation", "?")
        final = s.get("is_final", False)
        ir = s.get("input_match", {}).get("ratio", 0)
        dr = s.get("data_coverage", {}).get("ratio", 0)
        oo = s.get("operation_capability", 0)
        rr = s.get("result_match", {}).get("ratio", 0)
        cr = s.get("constraint_satisfaction", {}).get("ratio", 0)
        step_sc = agg.step_scores.get(int(sid) if isinstance(sid, (int, float)) else 99, 0)
        d_ev = s.get("data_coverage", {}).get("evidence_strength", "?")
        d_req = s.get("data_coverage", {}).get("required", [])
        d_mat = s.get("data_coverage", {}).get("matched", [])
        print(f"  Step {sid} ({op}, final={final}): "
              f"I={ir:.2f} D={dr:.2f}({d_ev}|req={d_req}|mat={d_mat}) "
              f"O={oo:.1f} R={rr:.2f} C={cr:.2f} "
              f"→ {step_sc:.3f}")

    print(f"  Reason:    {raw.get('reason', '')[:300]}")
    if raw.get("missing_requirements"):
        print(f"  Missing:   {raw['missing_requirements']}")
    if raw.get("risks"):
        print(f"  Risks:     {raw['risks']}")


# ── Tests ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_domain_mismatch(case: DomainMismatchCase) -> None:
    raw, agg = await _judge(case)
    _print_result(case, raw, agg)

    # ── Assertions ──

    # 1. can_handle / can_contribute
    assert agg.can_handle is case.expect_can_handle, (
        f"[{case.name}] can_handle mismatch: expected={case.expect_can_handle} "
        f"got={agg.can_handle} (conf={agg.confidence:.3f})"
    )
    assert agg.can_contribute is case.expect_can_contribute, (
        f"[{case.name}] can_contribute mismatch: expected={case.expect_can_contribute} "
        f"got={agg.can_contribute}"
    )

    # 2. reason field must contain / not contain specific substrings
    reason = str(raw.get("reason", ""))
    for sub in case.expect_reason_contains:
        assert sub in reason, (
            f"[{case.name}] reason MUST contain '{sub}' but got:\n{reason[:500]}"
        )
    for sub in case.expect_reason_not_contains:
        assert sub not in reason, (
            f"[{case.name}] reason MUST NOT contain '{sub}' but found it:\n{reason[:500]}"
        )

    # 3. D=0 for mismatch cases
    if case.expect_d_zero:
        for s in raw.get("steps", []):
            dr = s.get("data_coverage", {}).get("ratio", 1.0)
            assert dr == pytest.approx(0.0, abs=0.01), (
                f"[{case.name}] Step {s.get('step_id')}: expected D=0 "
                f"but got D={dr:.3f} "
                f"req={s.get('data_coverage', {}).get('required')} "
                f"mat={s.get('data_coverage', {}).get('matched')} "
                f"evidence={s.get('data_coverage', {}).get('evidence_strength')}"
            )

    # 4. D evidence_strength must be solid (not speculative) for mismatch cases
    #    because "skill body does not declare this domain" is a solid fact
    if case.expect_d_zero:
        for s in raw.get("steps", []):
            d_ev = s.get("data_coverage", {}).get("evidence_strength", "?")
            assert d_ev == "solid", (
                f"[{case.name}] Step {s.get('step_id')}: D evidence_strength should be "
                f"'solid' (skill body doesn't cover this domain — that's a solid fact), "
                f"but got '{d_ev}'"
            )

    # 5. Evidence grade check
    if case.expect_evidence_d_or_c:
        grade = raw.get("evidence_grade", "")
        assert grade in ("C", "D"), (
            f"[{case.name}] evidence_grade should be C or D for domain mismatch, "
            f"but got '{grade}'"
        )

    # 6. Sanity: for match cases, D should NOT be all-zeros
    if case.category == "match":
        any_nonzero_d = any(
            s.get("data_coverage", {}).get("ratio", 0) > 0.01
            for s in raw.get("steps", [])
        )
        assert any_nonzero_d, (
            f"[{case.name}] Match case should have at least one step with D>0"
        )

    # 7. O=0 check for mismatch cases (unless pure-generate step)
    if case.expect_d_zero:
        for s in raw.get("steps", []):
            op = s.get("operation", "")
            oo = s.get("operation_capability", 1.0)
            if op not in ("generate", "translate", "summarize", ""):
                assert oo == pytest.approx(0.0, abs=0.01), (
                    f"[{case.name}] Step {s.get('step_id')} ({op}): "
                    f"expected O=0 for domain mismatch, got O={oo:.1f}"
                )

    # 8. contribution should be empty for cases with can_contribute=False
    if not case.expect_can_contribute:
        contribution = str(raw.get("contribution", "")).strip()
        assert contribution == "", (
            f"[{case.name}] contribution should be empty (can_contribute=False), "
            f"but got: '{contribution[:200]}'"
        )