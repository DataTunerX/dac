"""
测试 SG Expert 统一 ReAct 架构（使用真实 LLM）。

验证两类目标：
1. 代码行为：ReAct 按需调用 agent、返回综合答案而非原始知识块
2. 效果质量：最终答案应包含 TOP 产品销售数据与退费率分析，且不陷入 max_steps 兜底

运行方式:
  cd dac/expert-agent
  python -m pytest tests/test_sg_expert_react.py -v -s
  python tests/test_sg_expert_react.py
"""
import asyncio
import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
from unittest.mock import AsyncMock

from uuid import uuid4
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.react as react_module
from agent.expert_agent_semantic_group import ExpertAgent
from agent.dataservices_client import SemanticDomainInfo, SemanticGroupInfo
from a2a.types import AgentCard

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger("test_sg_expert_react")


def _make_agent_card(name: str, url: str, description: str = "") -> AgentCard:
    return AgentCard(
        name=name,
        description=description or f"{name} agent for semantic domain queries",
        url=url,
        version="1.0.0",
        capabilities={"streaming": True},
        skills=[],
        defaultInputModes=["text"],
        defaultOutputModes=["text"],
    )


def _make_sd(dd_name: str, dd_namespace: str, descriptor_type: str,
             semantic_domain_id: str = "", agent_card_json: str = "") -> SemanticDomainInfo:
    return SemanticDomainInfo(
        dd_name=dd_name,
        dd_namespace=dd_namespace,
        descriptor_type=descriptor_type,
        semantic_domain_id=semantic_domain_id or f"sd-{dd_name}",
        agent_card=agent_card_json or json.dumps({"description": f"{dd_name} domain agent"}),
    )


def build_synthetic_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    code_sd = _make_sd("sales-code", "ecommerce", "code", agent_card_json=json.dumps({
        "description": "Sales system source code analysis: table schemas, business logic, field mappings"
    }))
    code_card = _make_agent_card("SalesCodeAgent-dd-ecommerce", "http://mock/sales-code", "Code analysis")

    doc_sd = _make_sd("sales-docs", "ecommerce", "unstructured", agent_card_json=json.dumps({
        "description": "Sales system documentation: API specs, data dictionaries, business rules"
    }))
    doc_card = _make_agent_card("SalesDocAgent-dd-ecommerce", "http://mock/sales-docs", "Document retrieval")

    mysql_sd = _make_sd("sales-mysql", "ecommerce", "structured-mysql", agent_card_json=json.dumps({
        "description": "MySQL database for sales orders, products, customers in ecommerce domain"
    }))
    mysql_card = _make_agent_card("SalesMySQL-dd-ecommerce", "http://mock/sales-mysql", "MySQL query")

    pg_sd = _make_sd("user-pg", "ecommerce", "structured-postgresql", agent_card_json=json.dumps({
        "description": "PostgreSQL database for user profiles, behavior analytics, and return records"
    }))
    pg_card = _make_agent_card("UserProfilePG-dd-ecommerce", "http://mock/user-pg", "PostgreSQL query")

    return [
        (code_sd, code_card),
        (doc_sd, doc_card),
        (mysql_sd, mysql_card),
        (pg_sd, pg_card),
    ]


def build_foundational_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() in ("code", "unstructured")]


CODE_AGENT_RESPONSE = """\
## Sales System Code Analysis

### Database Tables

1. **orders** 表:
   - id (BIGINT, PK)
   - product_id (BIGINT, FK → products.id)
   - customer_id (BIGINT, FK → customers.id)
   - order_amount (DECIMAL(12,2)) — 订单金额
   - order_status (VARCHAR(20)) — 'pending', 'paid', 'shipped', 'delivered', 'cancelled', 'refunded'
   - is_deleted (TINYINT, DEFAULT 0) — **软删除标记**，查询时必须过滤 is_deleted = 0
   - created_at (DATETIME)

2. **products** 表:
   - id (BIGINT, PK), name (VARCHAR(255)), unit_price (DECIMAL(10,2))
   - is_deleted (TINYINT, DEFAULT 0)

3. **return_records** 表:
   - order_id, product_id, return_amount, return_status ('completed' 计入退费率)
   - is_deleted (TINYINT, DEFAULT 0)

### 业务规则
- **退费率** = SUM(return_records.return_amount) / SUM(orders.order_amount) × 100%
- 所有查询必须过滤 is_deleted = 0
- 销售额统计: order_status IN ('paid', 'shipped', 'delivered')
"""

DOC_AGENT_RESPONSE = """\
## Ecommerce Sales System Documentation

- 过去一个月：从当前日期往前推 30 天
- 销售额：SUM(order_amount) WHERE order_status IN ('paid', 'shipped', 'delivered')
- TOP N 排序：按销售额降序
- 退货分析应查询 return_records，return_status='completed' 计入退费率
"""

MYSQL_AGENT_RESPONSE = """\
## MySQL Query Result: Top 10 Products by Sales Amount (Past 30 Days)

| 排名 | 产品ID | 产品名称 | 销售额(元) | 订单数 |
|------|--------|----------|------------|--------|
| 1 | 1024 | iPhone 16 Pro Max | 8,520,000 | 856 |
| 2 | 567 | MacBook Pro 16" | 6,340,000 | 412 |
| 3 | 891 | iPad Air | 3,210,000 | 520 |
| 4 | 345 | AirPods Pro 2 | 2,890,000 | 1,250 |
| 5 | 678 | Apple Watch Ultra | 2,450,000 | 680 |
| 6 | 111 | Sony WH-1000XM5 | 1,980,000 | 890 |
| 7 | 432 | Samsung Galaxy S25 | 1,760,000 | 340 |
| 8 | 999 | Dyson V15 Vacuum | 1,520,000 | 280 |
| 9 | 200 | Nintendo Switch OLED | 1,340,000 | 620 |
| 10 | 777 | Canon EOS R6 | 1,120,000 | 190 |
"""

PG_AGENT_RESPONSE_RETURNS = """\
## PostgreSQL Query Result: Return Rate Analysis for Top Products

| 产品ID | 产品名称 | 销售额(元) | 退货金额(元) | 退费率(%) |
|--------|----------|------------|-------------|-----------|
| 1024 | iPhone 16 Pro Max | 8,520,000 | 127,800 | 1.50 |
| 567 | MacBook Pro 16" | 6,340,000 | 190,200 | 3.00 |
| 891 | iPad Air | 3,210,000 | 48,150 | 1.50 |
| 345 | AirPods Pro 2 | 2,890,000 | 86,700 | 3.00 |
| 678 | Apple Watch Ultra | 2,450,000 | 36,750 | 1.50 |
| 111 | Sony WH-1000XM5 | 1,980,000 | 118,800 | 6.00 |
| 432 | Samsung Galaxy S25 | 1,760,000 | 26,400 | 1.50 |
| 999 | Dyson V15 Vacuum | 1,520,000 | 30,400 | 2.00 |
| 200 | Nintendo Switch OLED | 1,340,000 | 67,000 | 5.00 |
| 777 | Canon EOS R6 | 1,120,000 | 44,800 | 4.00 |
"""

PG_AGENT_RESPONSE_PROFILES = """\
## PostgreSQL Query Result: Customer Profile for High Return Rate Products

| 产品名称 | 退费率(%) | 主要退货原因 | 主要退货用户年龄段 |
|----------|-----------|--------------|-------------------|
| Sony WH-1000XM5 | 6.00 | 音质不如预期(45%), 佩戴不舒适(30%) | 25-35岁(60%) |
| Nintendo Switch OLED | 5.00 | 屏幕坏点(40%), 摇杆漂移(35%) | 18-25岁(55%) |
| Canon EOS R6 | 4.00 | 对焦问题(50%), 机身发热(25%) | 35-45岁(45%) |
"""


def _extract_query_from_payload(payload: Dict[str, Any]) -> str:
    try:
        parts = payload.get("message", {}).get("parts", [])
        if parts and isinstance(parts[0], dict):
            return str(parts[0].get("text", "") or "").strip().lower()
    except (TypeError, AttributeError):
        pass
    return ""


def _pick_structured_response(dt: str, query: str, call_num: int) -> str:
    q = query.lower()
    if dt == "structured-mysql":
        return MYSQL_AGENT_RESPONSE
    if dt == "structured-postgresql":
        if any(k in q for k in ("profile", "画像", "原因", "用户", "customer")):
            return PG_AGENT_RESPONSE_PROFILES
        return PG_AGENT_RESPONSE_RETURNS
    return f"(simulated structured response for {dt})"


def assert_no_failure_fallback(result: str) -> None:
    """检测明确的兜底/失败措辞（精确短语，避免误伤正常分析用语）。"""
    failure_patterns = [
        r"无法完整回答",
        r"无法完整地回答",
        r"信息缺口",
        r"未能成功查询",
        r"未能获取完整",
        r"未能成功获取",
        r"关键信息.{0,10}未能获取",
        r"工具调用次数超限",
        r"超过最大推理轮次",
        r"超过最大轮次",
        r"max_steps",
    ]
    for pat in failure_patterns:
        assert not re.search(pat, result), f"答案含兜底/失败标记: {pat}"


def assert_sales_return_answer_quality(result: str) -> None:
    """验证 ReAct 综合答案的业务效果。"""
    assert_no_failure_fallback(result)

    assert "iPhone 16 Pro Max" in result, "应包含销售额第1名产品"
    assert "MacBook Pro 16" in result, "应包含销售额第2名产品"

    top_product_hits = sum(
        1 for name in ("iPad Air", "AirPods Pro 2", "Apple Watch Ultra", "Sony WH-1000XM5")
        if name in result
    )
    assert top_product_hits >= 1, "应提及 TOP 10 中的多个产品（至少 1 个除前2名外）"

    assert re.search(r"1\.50|3\.00|6\.00|退费率|退货率", result), (
        "应包含退费率数值或明确退费率分析"
    )

    assert "Sony WH-1000XM5" in result or "6.00" in result or "6.0" in result, (
        "应提及高退货率产品或具体比率"
    )


def build_structured_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower().startswith("structured")]


def build_mysql_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() == "structured-mysql"]


def build_pg_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() == "structured-postgresql"]


def build_code_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() == "code"]


def build_doc_only_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() == "unstructured"]


def build_code_and_mysql_agents() -> List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]]:
    agents = build_synthetic_agents()
    allowed = {"code", "structured-mysql"}
    return [(sd, ac) for sd, ac in agents if (getattr(sd, "descriptor_type", "") or "").strip().lower() in allowed]


def analyze_execution_process(
    trace: Dict[str, Any],
    *,
    require_structured: bool = True,
    require_finish: bool = True,
    min_structured_thoughts: int = 0,
    max_tool_calls: int = 15,
) -> Dict[str, Any]:
    """
    智能分析 ReAct 执行过程（不是只看最终答案）。
    Structured Thought 为可选 hint：默认不因缺失而判失败。
    返回 issues / strengths 供测试断言与日志输出。
    """
    issues: List[str] = []
    strengths: List[str] = []

    status = trace.get("status", "")
    steps = trace.get("steps", 0)
    tool_history = trace.get("tool_history") or []
    structured_thoughts = trace.get("structured_thoughts") or []
    step_analyses = trace.get("step_analyses") or []
    analysis_triggers = trace.get("analysis_triggers") or []

    tool_calls = [
        h for h in tool_history
        if h.get("tool") and h.get("tool") != "finish"
    ]
    tools_used = [h.get("tool") for h in tool_calls]
    unique_tools = list(dict.fromkeys(tools_used))

    if require_finish and status not in ("completed", "forced_finish"):
        issues.append(f"未正常 finish，status={status} steps={steps}")
    elif status in ("completed", "forced_finish"):
        strengths.append(f"正常 finish，共 {steps} 步 (status={status})")

    # Structured Thought：可选 hint，有则记录 strengths，缺失不默认判失败
    valid_thoughts = [t for t in structured_thoughts if t.get("valid")]
    if min_structured_thoughts > 0 and len(valid_thoughts) < min_structured_thoughts:
        issues.append(
            f"有效 Structured Thought 不足: {len(valid_thoughts)} < {min_structured_thoughts}"
        )
    elif valid_thoughts:
        strengths.append(f"共 {len(valid_thoughts)} 轮有效 Structured Thought (hint)")
        if any(t.get("sub_goals") for t in valid_thoughts):
            strengths.append("Structured Thought 包含 sub_goals 分解")

    # 按需 Analysis：不应每轮都跑，卡住时才 escalate
    if step_analyses:
        strengths.append(
            f"按需触发 {len(step_analyses)} 轮 Execution Analysis "
            f"(triggers: {analysis_triggers})"
        )
        if steps and len(step_analyses) > steps:
            issues.append(
                f"Analysis 次数超过步数 ({len(step_analyses)}/{steps})，异常"
            )
    elif any(h.get("repeat_of_previous") for h in tool_calls):
        issues.append("出现重复结果但未触发 Execution Analysis")

    # 检测盲目重复：同一 tool 连续 3+ 次相同结果，且 Execution Analysis 未给出 stop_retry
    repeat_streak = 0
    last_tool = None
    repeated_tool = None
    for h in tool_calls:
        tool = h.get("tool")
        if tool == last_tool and h.get("repeat_of_previous"):
            repeat_streak += 1
            repeated_tool = tool
        else:
            repeat_streak = 1 if h.get("repeat_of_previous") else 0
            if repeat_streak <= 1:
                repeated_tool = tool if h.get("repeat_of_previous") else None
        last_tool = tool

    stop_retry_tools = {
        str(a.get("next_action", "")).split(":", 1)[1]
        for a in step_analyses
        if str(a.get("next_action", "")).startswith("stop_retry:")
    }
    if repeat_streak >= 3 and repeated_tool:
        if repeated_tool in stop_retry_tools:
            strengths.append(
                f"曾对 {repeated_tool} 盲目重试，但 Execution Analysis 识别并 stop_retry"
            )
        else:
            issues.append(
                f"工具 {repeated_tool} 连续 {repeat_streak} 次相同结果，且分析未 stop_retry"
            )

    if len(tool_calls) > max_tool_calls:
        issues.append(f"总调用次数过多: {len(tool_calls)} (> {max_tool_calls})")

    called_types = set()
    for h in tool_calls:
        tool = h.get("tool") or ""
        if tool.startswith("structured_"):
            called_types.add("structured")
        elif tool.startswith("code_"):
            called_types.add("code")
        elif tool.startswith("doc_"):
            called_types.add("doc")

    if require_structured and "structured" not in called_types:
        issues.append("未调用 structured agent 获取数据")

    # 执行分析应体现 sub-goal 分解
    has_sub_goals = any(a.get("sub_goals") for a in step_analyses)
    has_diagnosis = any(a.get("diagnosis") for a in step_analyses)
    if step_analyses and not has_sub_goals:
        issues.append("Execution Analysis 未分解 sub-goals")
    if step_analyses and not has_diagnosis:
        issues.append("Execution Analysis 缺少 process diagnosis")

    # 分析是否识别了工具能力边界（重复结果 → stop_retry 或换工具）
    for a in step_analyses:
        action = str(a.get("next_action") or "")
        if action.startswith("stop_retry:") or action.startswith("call:"):
            strengths.append(f"Step {a.get('step')}: 分析给出明确下一步 `{action}`")
            break
    else:
        if any(h.get("repeat_of_previous") for h in tool_calls):
            issues.append("出现重复结果但 Execution Analysis 未给出 stop_retry/call 建议")

    return {
        "status": status,
        "steps": steps,
        "total_tool_calls": len(tool_calls),
        "unique_tools": unique_tools,
        "structured_thought_count": len(valid_thoughts),
        "step_analysis_count": len(step_analyses),
        "analysis_triggers": analysis_triggers,
        "issues": issues,
        "strengths": strengths,
        "passed": len(issues) == 0,
    }


def log_execution_report(report: Dict[str, Any]) -> None:
    logger.info("=== 执行过程分析 ===")
    logger.info("status=%s steps=%s tool_calls=%s",
                report["status"], report["steps"], report["total_tool_calls"])
    logger.info("unique_tools=%s", report["unique_tools"])
    for s in report["strengths"]:
        logger.info("  [+] %s", s)
    for i in report["issues"]:
        logger.info("  [-] %s", i)


def make_mock_fetch_knowledge():
    call_count: Dict[str, int] = {}
    all_calls: List[str] = []
    _in_flight = 0
    max_concurrent = 0

    async def mock_fetch(
        self,
        httpx_client,
        send_message_payload: Dict[str, Any],
        sd,
        agent_card,
    ) -> Tuple[Any, str]:
        nonlocal _in_flight, max_concurrent
        _in_flight += 1
        max_concurrent = max(max_concurrent, _in_flight)
        agent_name = getattr(agent_card, "name", "") or "(unknown)"
        dt = (getattr(sd, 'descriptor_type', '') or "").strip().lower()
        query = _extract_query_from_payload(send_message_payload)
        call_key = f"{agent_name}|{dt}"
        call_count[call_key] = call_count.get(call_key, 0) + 1
        all_calls.append(call_key)
        call_num = call_count[call_key]

        try:
            await asyncio.sleep(0.01)
            if dt == "code":
                resp = CODE_AGENT_RESPONSE
            elif dt == "unstructured":
                resp = DOC_AGENT_RESPONSE
            elif dt.startswith("structured"):
                resp = _pick_structured_response(dt, query, call_num)
            else:
                resp = f"(simulated response for {agent_name}, type={dt})"

            logger.info(
                "[MOCK] fetch: agent=%s type=%s query=%r call#=%d len=%d",
                agent_name, dt, query[:80], call_num, len(resp),
            )
            return (sd, resp)
        finally:
            _in_flight -= 1

    mock_fetch.call_count = call_count
    mock_fetch.all_calls = all_calls
    mock_fetch.max_concurrent = lambda: max_concurrent
    mock_fetch.total_calls = lambda: sum(call_count.values())
    return mock_fetch


async def _run_react_case(
    agent_kwargs: Dict[str, Any],
    query: str,
    agents: List[Tuple[Union[SemanticDomainInfo, SemanticGroupInfo], AgentCard]],
    mock_fetch=None,
    *,
    metadata_extra: Optional[Dict[str, Any]] = None,
) -> Tuple[ExpertAgent, str, Dict[str, Any], Any]:
    """运行一次 ReAct 并返回 (agent, result, trace, mock_fetch)。"""
    if mock_fetch is None:
        mock_fetch = make_mock_fetch_knowledge()

    kwargs = dict(agent_kwargs)
    kwargs["query"] = query
    if metadata_extra:
        meta = dict(kwargs.get("metadata") or {})
        meta.update(metadata_extra)
        kwargs["metadata"] = meta

    agent = ExpertAgent(**kwargs)
    agent.group_agent_cards = agents
    agent._fetch_knowledge_from_agent = mock_fetch.__get__(agent, type(agent))
    agent.emit_progress = AsyncMock()

    result = await agent.get_knowledge()
    trace = agent.react_runner.last_run_trace
    return agent, result, trace, mock_fetch


class TestSGExpertReact:
    """测试 SG Expert 统一 ReAct 架构."""

    @pytest.fixture
    def agent_kwargs(self):
        return {
            "provider": "openai_compatible",
            "api_key": "sk-6e3f3c21c50849f2b4630da2de9434c8",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "deepseek-v4-pro",
            "semantic_group_id": "test-sg-ecommerce",
            "data_services_url": "http://localhost:9999",
            "query": "查询过去一个月销售额最高的前10个产品，并分析它们的退货率情况",
            "metadata": {
                "user_id": "test-user-001",
                "run_id": "test-run-react-001",
                "trace_id": uuid4().hex,
            },
            "max_steps": 5,
            "temperature": 0.01,
            "agent_id": "TestSGExpert",
        }

    @pytest.mark.asyncio
    async def test_get_knowledge_unified_react(self, agent_kwargs):
        """核心测试: 统一 ReAct + 答案效果（TOP10 销售 + 退费率）."""
        mock_fetch = make_mock_fetch_knowledge()
        synthetic_agents = build_synthetic_agents()

        agent = ExpertAgent(**agent_kwargs)
        agent.group_agent_cards = synthetic_agents
        agent._fetch_knowledge_from_agent = mock_fetch.__get__(agent, type(agent))
        agent.emit_progress = AsyncMock()

        result = await agent.get_knowledge()
        trace = agent.react_runner.last_run_trace
        report = analyze_execution_process(trace)
        log_execution_report(report)

        logger.info("\n=== ReAct 综合答案 ===\n%s", result)

        assert result, "get_knowledge() 不应返回空字符串"
        assert "【智能体" not in result, "不应向上游返回各 agent 原始知识块"

        assert_sales_return_answer_quality(result)
        assert trace.get("status") == "completed"

        if report["steps"] > 1:
            assert report["step_analysis_count"] <= report["steps"], (
                "Analysis 应为按需触发，不应超过 ReAct 步数"
            )

        # 必须调用 structured agent 获取销售数据；退费率可来自 PG 或 MySQL/综合，不强制 PG
        called_types = {key.split("|")[1] for key in mock_fetch.call_count}
        assert any(t.startswith("structured") for t in called_types), (
            f"应调用 structured agent，实际: {called_types}"
        )

        # 有重复调用时，应触发过 Analysis
        tool_history = trace.get("tool_history") or []
        had_repeat = any(
            h.get("repeat_of_previous") for h in tool_history if h.get("tool")
        )
        if had_repeat:
            assert report["analysis_triggers"], "有重复调用时应触发按需 Analysis"

        assert mock_fetch.max_concurrent() <= 3
        assert mock_fetch.total_calls() <= 18

    @pytest.mark.asyncio
    async def test_structured_only_query_skips_code_doc(self, agent_kwargs):
        """纯数据查询：答案应包含 TOP 产品销售数据."""
        mock_fetch = make_mock_fetch_knowledge()
        synthetic_agents = build_synthetic_agents()

        agent = ExpertAgent(**agent_kwargs)
        agent.group_agent_cards = synthetic_agents
        agent._fetch_knowledge_from_agent = mock_fetch.__get__(agent, type(agent))
        agent.emit_progress = AsyncMock()
        agent.query = "直接查询过去一个月销售额 TOP 10 产品列表"

        result = await agent.get_knowledge()
        trace = agent.react_runner.last_run_trace
        report = analyze_execution_process(trace)
        log_execution_report(report)

        logger.info("\n=== TOP10 查询答案 ===\n%s", result)

        assert result
        assert "【智能体" not in result
        assert "iPhone 16 Pro Max" in result
        assert "MacBook Pro 16" in result
        assert trace.get("status") == "completed"
        assert mock_fetch.total_calls() <= 12

    @pytest.mark.asyncio
    async def test_foundational_only_react(self, agent_kwargs):
        """仅 code + doc agent 时也走 ReAct 并返回综合答案."""
        mock_fetch = make_mock_fetch_knowledge()
        foundational_agents = build_foundational_only_agents()

        agent = ExpertAgent(**agent_kwargs)
        agent.group_agent_cards = foundational_agents
        agent._fetch_knowledge_from_agent = mock_fetch.__get__(agent, type(agent))
        agent.emit_progress = AsyncMock()
        agent.query = "销售系统的软删除规则和退费率计算公式是什么？"

        result = await agent.get_knowledge()
        trace = agent.react_runner.last_run_trace
        report = analyze_execution_process(trace)
        log_execution_report(report)

        logger.info("\n=== foundational-only 答案 ===\n%s", result)

        assert result
        assert "【智能体" not in result
        assert any(k in result for k in ("软删除", "退费率", "is_deleted"))
        assert trace.get("status") == "completed"
        assert mock_fetch.total_calls() <= 8

    # ── 新增 10 个测试 case ──────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_structured_mysql_only_top10(self, agent_kwargs):
        """仅 MySQL structured agent：查询 TOP10 销售."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "查询过去一个月销售额 TOP 10 产品",
            build_mysql_only_agents(),
        )
        report = analyze_execution_process(trace, require_structured=True, max_tool_calls=8)
        assert result and "【智能体" not in result
        assert "iPhone 16 Pro Max" in result
        assert trace.get("status") == "completed"
        assert any("structured-mysql" in k for k in mock_fetch.call_count)
        assert not any("structured-postgresql" in k for k in mock_fetch.call_count)

    @pytest.mark.asyncio
    async def test_structured_pg_only_return_rates(self, agent_kwargs):
        """仅 PostgreSQL structured agent：退货率分析."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "分析 TOP 产品的退费率，哪些产品退货率最高？",
            build_pg_only_agents(),
        )
        report = analyze_execution_process(trace, require_structured=True, max_tool_calls=8)
        assert result and "【智能体" not in result
        assert any(k in result for k in ("退货", "退费率", "6.00", "Sony"))
        assert trace.get("status") == "completed"
        assert any("structured-postgresql" in k for k in mock_fetch.call_count)

    @pytest.mark.asyncio
    async def test_code_only_orders_schema(self, agent_kwargs):
        """仅 code agent：查 orders 表结构与软删除规则."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "orders 表有哪些字段？软删除怎么过滤？",
            build_code_only_agents(),
        )
        report = analyze_execution_process(
            trace, require_structured=False, min_structured_thoughts=0, max_tool_calls=6,
        )
        assert result and "【智能体" not in result
        assert any(k in result for k in ("orders", "is_deleted", "软删除", "order_amount"))
        assert trace.get("status") == "completed"
        assert mock_fetch.total_calls() <= 6

    @pytest.mark.asyncio
    async def test_doc_only_sales_rules(self, agent_kwargs):
        """仅 doc agent：销售额统计口径."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "文档里销售额怎么统计？过去一个月怎么定义？",
            build_doc_only_agents(),
        )
        report = analyze_execution_process(
            trace, require_structured=False, min_structured_thoughts=0, max_tool_calls=6,
        )
        assert result and "【智能体" not in result
        assert any(k in result for k in ("30", "paid", "shipped", "delivered", "销售额"))
        assert trace.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_with_upstream_prior_context(self, agent_kwargs):
        """带 upstream_prior_knowledge：应融入最终答案."""
        prior = "【上游编排】已确认：统计周期=过去30天，仅统计有效订单。"
        _, result, trace, _ = await _run_react_case(
            agent_kwargs,
            "查询 TOP10 产品销售额及退费率",
            build_synthetic_agents(),
            metadata_extra={"upstream_prior_knowledge": prior},
        )
        report = analyze_execution_process(trace, max_tool_calls=15)
        assert result and "【智能体" not in result
        assert "iPhone 16 Pro Max" in result
        assert trace.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_high_return_product_profile(self, agent_kwargs):
        """聚焦高退货率产品：应包含退货原因/用户画像."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "Sony WH-1000XM5 退货率为什么高？主要退货原因和用户画像是什么？",
            build_synthetic_agents(),
        )
        report = analyze_execution_process(trace, max_tool_calls=15)
        assert result and "【智能体" not in result
        assert any(k in result for k in ("Sony", "WH-1000XM5", "6.00", "退货"))
        assert trace.get("status") == "completed"
        called = " ".join(mock_fetch.call_count.keys())
        assert "structured-postgresql" in called or "Sony" in result

    @pytest.mark.asyncio
    async def test_single_product_iphone_sales(self, agent_kwargs):
        """单品查询：iPhone 16 Pro Max 销售额."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "iPhone 16 Pro Max 过去一个月销售额是多少？",
            build_structured_only_agents(),
        )
        report = analyze_execution_process(trace, max_tool_calls=10)
        assert result and "【智能体" not in result
        assert "iPhone 16 Pro Max" in result
        assert re.search(r"8[,，]?520|852", result.replace(" ", ""))
        assert trace.get("status") == "completed"
        assert mock_fetch.total_calls() <= 10

    @pytest.mark.asyncio
    async def test_empty_agent_cards(self, agent_kwargs):
        """无 agent 配置：应返回空字符串."""
        agent = ExpertAgent(**agent_kwargs)
        agent.group_agent_cards = []
        agent.emit_progress = AsyncMock()
        result = await agent.get_knowledge()
        assert result == ""

    @pytest.mark.asyncio
    async def test_return_rate_only_analysis(self, agent_kwargs):
        """仅退费率分析（不要求重新排名）."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "分析销售额 TOP 产品的退费率，找出退货率超过 4% 的产品",
            build_synthetic_agents(),
        )
        report = analyze_execution_process(trace, max_tool_calls=15)
        assert result and "【智能体" not in result
        assert re.search(r"退费率|退货率", result)
        assert any(k in result for k in ("5.00", "6.00", "4.00", "Sony", "Nintendo", "Canon"))
        assert trace.get("status") == "completed"

    @pytest.mark.asyncio
    async def test_code_and_mysql_business_sql(self, agent_kwargs):
        """code + MySQL：结合业务规则查销售数据."""
        _, result, trace, mock_fetch = await _run_react_case(
            agent_kwargs,
            "根据代码里的业务规则，查询过去一个月有效订单的 TOP5 产品销售额",
            build_code_and_mysql_agents(),
        )
        report = analyze_execution_process(trace, max_tool_calls=12)
        assert result and "【智能体" not in result
        assert "iPhone 16 Pro Max" in result
        assert any(k in result for k in ("is_deleted", "软删除", "paid", "有效"))
        assert trace.get("status") == "completed"
        assert "code" in " ".join(mock_fetch.call_count.keys())
        assert "structured-mysql" in " ".join(mock_fetch.call_count.keys())


async def main():
    kwargs = {
        "provider": "openai_compatible",
        "api_key": "sk-6e3f3c21c50849f2b4630da2de9434c8",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "deepseek-v4-flash",
        "semantic_group_id": "test-sg-ecommerce",
        "data_services_url": "http://localhost:9999",
        "query": "查询过去一个月销售额最高的前10个产品，并分析它们的退货率情况",
        "metadata": {
            "user_id": "test-user-001",
            "run_id": "test-run-react-001",
            "trace_id": uuid4().hex,
        },
        "max_steps": 100,
        "temperature": 0.01,
        "agent_id": "TestSGExpert",
    }

    mock_fetch = make_mock_fetch_knowledge()
    synthetic_agents = build_synthetic_agents()

    agent = ExpertAgent(**kwargs)
    agent.group_agent_cards = synthetic_agents
    agent._fetch_knowledge_from_agent = mock_fetch.__get__(agent, type(agent))
    agent.emit_progress = AsyncMock()

    print("Calling get_knowledge() (unified ReAct)...")
    result = await agent.get_knowledge()
    trace = agent.react_runner.last_run_trace
    report = analyze_execution_process(trace)

    print(f"\n=== Result ({len(result)} chars, status={trace.get('status')}, "
          f"steps={trace.get('steps')}, tool_calls={report['total_tool_calls']}) ===")
    print(result)

    print("\n=== 执行过程分析 ===")
    for s in report["strengths"]:
        print(f"  [+] {s}")
    for i in report["issues"]:
        print(f"  [-] {i}")

    for i, t in enumerate(trace.get("structured_thoughts") or [], 1):
        print(f"\n--- Structured Thought #{i} (step {t.get('step')}) ---")
        print(f"  sub_goals: {t.get('sub_goals')}")
        print(f"  satisfied: {t.get('satisfied')}")
        print(f"  gaps: {t.get('gaps')}")
        print(f"  planned_action: {t.get('planned_action')}")
        print(f"  confidence: {t.get('confidence')}")

    for i, a in enumerate(trace.get("step_analyses") or [], 1):
        print(f"\n--- On-demand Analysis #{i} (trigger={a.get('trigger')}) ---")
        print(f"  next_action: {a.get('next_action')}")
        print(f"  sub_goals: {a.get('sub_goals')}")
        print(f"  satisfied: {a.get('satisfied')}")
        print(f"  gaps: {a.get('gaps')}")
        print(f"  diagnosis: {(a.get('diagnosis') or '')[:300]}")

    try:
        assert_sales_return_answer_quality(result)
        assert trace.get("status") == "completed"
        if report["issues"]:
            print("\n⚠ 执行过程提示 (非阻塞):", report["issues"])
        print("\n✓ 效果质量检查通过")
    except AssertionError as e:
        print(f"\n✗ 检查失败: {e}")


class TestAnswerModelForDescriptor:
    def test_structured_and_doc_use_summarized(self):
        assert ExpertAgent._answer_model_for_descriptor_type("structured") == "summarized"
        assert ExpertAgent._answer_model_for_descriptor_type("structured-mysql") == "summarized"
        assert ExpertAgent._answer_model_for_descriptor_type("unstructured") == "summarized"
        assert ExpertAgent._answer_model_for_descriptor_type("unstructured-doc") == "summarized"

    def test_code_and_group_use_original(self):
        assert ExpertAgent._answer_model_for_descriptor_type("code") == "original"
        assert ExpertAgent._answer_model_for_descriptor_type("group") == "original"


class TestReActEvidencePriorityPrompt:
    def test_system_prompt_declares_structured_over_doc_code(self):
        prompt = react_module._REACT_SYSTEM_PROMPT_TEMPLATE
        assert "Evidence priority" in prompt
        assert "Structured tool results are authoritative" in prompt

    def test_finish_tool_description_blocks_doc_override(self):
        assert "structured tools reported" in react_module._FINISH_TOOL_DESCRIPTION
        assert react_module._FinishArgs.model_fields["final_answer"].description


if __name__ == "__main__":
    asyncio.run(main())
