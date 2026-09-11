"""Live DashScope tests for summarize-eval and agent-summarize prompts.

Requires DASHSCOPE_API_KEY. Model default: deepseek-v4-flash-0731.

Run:
  DASHSCOPE_API_KEY=sk-... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    python -m pytest tests/test_summarize_prompt_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from a2a.types import AgentCapabilities, AgentCard

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("LANGFUSE_FLUSH_TIMEOUT_SEC", "0")
os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)

from agent.skill_agent import (  # noqa: E402
    SkillAgentExecutor,
    _build_agent_summarize_prompt,
    _build_summarize_eval_prompt,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live summarize prompt tests",
)

DASHSCOPE_MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
STABILITY_RUNS = int(os.getenv("SUMMARIZE_STABILITY_RUNS", "3"))

ZHANGSAN_FAIL = (
    "## 查询结果\n\n"
    "无法直接通过用户名\"张三\"查询订单，原因如下：\n\n"
    "订单数据格式限制：订单数据（data/orders.txt）中的字段为 "
    "订单号|订单状态|商品名称|用户ID，只包含用户ID（如 U001、U002），"
    "不包含用户姓名。直接搜索\"张三\"未找到任何匹配结果。\n\n"
    "建议：需要先使用 user_query 技能查询\"张三\"对应的用户ID，"
    "然后再用该用户ID回到 order_query 技能查询订单。"
)

PREAMBLE_MARKERS = (
    "好的，作为",
    "我已收到",
    "我已整合",
    "以下是针对",
    "完整/综合回答",
    "作为汇总器",
)


def _ef_zhangsan_insufficient() -> list[dict]:
    return [
        {
            "execution_id": "own-1-order-agent-t1",
            "turn": 1,
            "stage": "pre_exec",
            "agent": "order-agent",
            "role": "initiator",
            "task": "查询用户张三购买的商品，按用户名'张三'进行过滤",
            "result": ZHANGSAN_FAIL,
            "reason": "订单数据只有用户ID，无法按姓名查询",
            "parent_execution_id": None,
            "delegated_by": None,
            "run_id": "summarize-live",
            "trace_id": "",
            "user_id": "live-test",
        }
    ]


def _ef_zhangsan_complete() -> list[dict]:
    return [
        *_ef_zhangsan_insufficient(),
        {
            "execution_id": "del-user-agent-t1",
            "turn": 1,
            "stage": "mid_exec_round_1",
            "agent": "user-agent",
            "role": "delegatee",
            "task": "查询用户张三对应的用户ID",
            "result": "张三对应的用户ID为 U001。",
            "reason": "需要用户名到用户ID的映射后才能查订单",
            "parent_execution_id": None,
            "delegated_by": "order-agent",
            "run_id": "summarize-live",
            "trace_id": "",
            "user_id": "live-test",
        },
        {
            "execution_id": "own-2-order-agent-t1",
            "turn": 1,
            "stage": "mid_exec_round_1",
            "agent": "order-agent",
            "role": "initiator",
            "task": "用用户ID U001 查询张三购买的商品",
            "result": (
                "U001 的订单商品：ORD-001 iPhone 15 Pro；"
                "ORD-003 AirPods Pro；ORD-016 小米 13 Ultra。"
            ),
            "reason": "已获得用户ID，补充查询订单",
            "parent_execution_id": None,
            "delegated_by": None,
            "run_id": "summarize-live",
            "trace_id": "",
            "user_id": "live-test",
        },
    ]


def _ef_sales_total() -> list[dict]:
    return [
        {
            "execution_id": "own-1-sales-t1",
            "turn": 1,
            "stage": "pre_exec",
            "agent": "order-agent",
            "role": "initiator",
            "task": "查询2024年1月的销售总额",
            "result": "已查询数据库，2024年1月销售总额为123456元。",
            "reason": "",
            "parent_execution_id": None,
            "delegated_by": None,
            "run_id": "summarize-live",
            "trace_id": "",
            "user_id": "live-test",
        }
    ]


def _ef_wangwu_dump_all() -> list[dict]:
    return [
        {
            "execution_id": "own-1-order-t1",
            "turn": 1,
            "stage": "pre_exec",
            "agent": "order-agent",
            "role": "initiator",
            "task": "查询王五购买的商品并显示商品名字",
            "result": (
                "订单数据中没有找到用户名为“王五”的记录，数据中只有用户ID，没有姓名。"
                "以下是所有用户的购买概览：U001买了A、B，U002买了C。"
                "请问您知道王五对应的用户ID吗？"
            ),
            "reason": "无法按姓名过滤",
            "parent_execution_id": None,
            "delegated_by": None,
            "run_id": "summarize-live",
            "trace_id": "",
            "user_id": "live-test",
        }
    ]


def _make_executor() -> SkillAgentExecutor:
    ex = SkillAgentExecutor(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=DASHSCOPE_BASE_URL,
        model=DASHSCOPE_MODEL,
        stream=False,
        temperature=0.01,
        data_services_url="http://127.0.0.1:9",
        agent_id="order-agent",
    )
    ex.agent_card = AgentCard(
        name="order-agent",
        description="查询订单与购买商品",
        url="http://local/order-agent",
        version="1.0.0",
        skills=[],
        capabilities=AgentCapabilities(),
        default_input_modes=["text", "text/plain"],
        default_output_modes=["text", "text/plain"],
    )
    ex.get_history = AsyncMock(return_value=[])
    return ex


def _dump_eval(label: str, result) -> None:
    print(f"\n===== {label} =====")
    print(f"satisfactory={result.satisfactory}")
    print(f"missing_info={result.missing_info!r}")
    print(f"rationale={result.rationale!r}")
    print(f"answer={result.answer!r}")


def _assert_no_preamble(text: str) -> None:
    for marker in PREAMBLE_MARKERS:
        assert marker not in text, f"answer has preamble {marker!r}: {text[:200]!r}"


@pytest.fixture(scope="module")
def executor():
    return _make_executor()


def test_eval_human_prompt_is_execution_flow_not_json():
    """Prompt shape check (no LLM): the messy JSON dump must be gone."""
    _, human = _build_summarize_eval_prompt(
        "张三买了哪些东西",
        execution_flow_tasks=_ef_zhangsan_insufficient(),
        task_results={1: ZHANGSAN_FAIL},
        current_agent="order-agent",
    )
    print("\n===== summarize-eval human prompt =====\n" + human)
    assert "## 执行流水账" in human
    assert "上游传入上下文" not in human
    assert "executed_tasks" not in human
    assert human.count("无法直接通过用户名") == 1


def test_agent_summarize_human_prompt_is_execution_flow_not_json():
    _, human = _build_agent_summarize_prompt(
        "张三买了哪些东西",
        execution_flow_tasks=_ef_zhangsan_complete(),
        current_agent="order-agent",
    )
    print("\n===== agent-summarize human prompt =====\n" + human)
    assert "## 执行流水账" in human
    assert "请直接输出答案" in human
    assert "上游传入上下文" not in human
    assert "user-agent" in human
    assert "U001" in human


@pytest.mark.asyncio
async def test_live_eval_zhangsan_insufficient(executor):
    result = await executor._summarize_with_evaluation(
        original_query="张三买了哪些东西",
        task_results={1: ZHANGSAN_FAIL},
        delegate_results={},
        execution_flow_tasks=_ef_zhangsan_insufficient(),
        user_id="live-test",
        run_id="summarize-eval-insufficient",
    )
    _dump_eval("eval/zhangsan-insufficient", result)
    assert result.satisfactory is False
    missing = result.missing_info + result.answer + result.rationale
    assert any(k in missing for k in ("用户ID", "user_query", "用户名", "映射")), missing
    _assert_no_preamble(result.answer)


@pytest.mark.asyncio
async def test_live_eval_zhangsan_complete(executor):
    result = await executor._summarize_with_evaluation(
        original_query="张三买了哪些东西",
        task_results={
            1: ZHANGSAN_FAIL,
            2: "U001 的订单商品：ORD-001 iPhone 15 Pro；ORD-003 AirPods Pro；ORD-016 小米 13 Ultra。",
        },
        delegate_results={"user-agent": "张三对应的用户ID为 U001。"},
        execution_flow_tasks=_ef_zhangsan_complete(),
        user_id="live-test",
        run_id="summarize-eval-complete",
    )
    _dump_eval("eval/zhangsan-complete", result)
    assert result.satisfactory is True
    answer = result.answer
    assert "iPhone" in answer or "AirPods" in answer or "小米" in answer
    _assert_no_preamble(answer)


@pytest.mark.asyncio
async def test_live_eval_sales_total(executor):
    result = await executor._summarize_with_evaluation(
        original_query="查询2024年1月的销售总额",
        task_results={1: "已查询数据库，2024年1月销售总额为123456元。"},
        delegate_results={},
        execution_flow_tasks=_ef_sales_total(),
        user_id="live-test",
        run_id="summarize-eval-sales",
    )
    _dump_eval("eval/sales-total", result)
    assert result.satisfactory is True
    assert "123456" in result.answer
    _assert_no_preamble(result.answer)


@pytest.mark.asyncio
async def test_live_eval_wangwu_dump_all(executor):
    result = await executor._summarize_with_evaluation(
        original_query="王五买了哪些商品，要显示商品名字",
        task_results={1: _ef_wangwu_dump_all()[0]["result"]},
        delegate_results={},
        execution_flow_tasks=_ef_wangwu_dump_all(),
        user_id="live-test",
        run_id="summarize-eval-wangwu",
    )
    _dump_eval("eval/wangwu-dump-all", result)
    assert result.satisfactory is False
    _assert_no_preamble(result.answer)


@pytest.mark.asyncio
async def test_live_agent_summarize_zhangsan_complete(executor):
    answer = await executor._summarize(
        original_query="张三买了哪些东西",
        task_results={
            1: "U001 的订单商品：ORD-001 iPhone 15 Pro；ORD-003 AirPods Pro；ORD-016 小米 13 Ultra。",
        },
        delegate_results={"user-agent": "张三对应的用户ID为 U001。"},
        execution_flow_tasks=_ef_zhangsan_complete(),
        user_id="live-test",
        run_id="agent-summarize-complete",
    )
    print(f"\n===== agent-summarize/zhangsan-complete =====\n{answer}")
    assert "iPhone" in answer or "AirPods" in answer or "小米" in answer
    _assert_no_preamble(answer)


@pytest.mark.asyncio
async def test_live_agent_summarize_zhangsan_insufficient(executor):
    answer = await executor._summarize(
        original_query="张三买了哪些东西",
        task_results={1: ZHANGSAN_FAIL},
        delegate_results={},
        execution_flow_tasks=_ef_zhangsan_insufficient(),
        user_id="live-test",
        run_id="agent-summarize-insufficient",
    )
    print(f"\n===== agent-summarize/zhangsan-insufficient =====\n{answer}")
    assert any(k in answer for k in ("无法", "没有", "缺少", "用户ID", "不能"))
    _assert_no_preamble(answer)


@pytest.mark.asyncio
async def test_live_eval_zhangsan_insufficient_stability(executor):
    """Same insufficient input must stay satisfactory=False across repeats."""
    outcomes: list[bool] = []
    for i in range(STABILITY_RUNS):
        result = await executor._summarize_with_evaluation(
            original_query="张三买了哪些东西",
            task_results={1: ZHANGSAN_FAIL},
            delegate_results={},
            execution_flow_tasks=_ef_zhangsan_insufficient(),
            user_id="live-test",
            run_id=f"summarize-eval-insufficient-stab-{i}",
        )
        _dump_eval(f"eval/insufficient-stab-{i+1}/{STABILITY_RUNS}", result)
        outcomes.append(result.satisfactory)
    assert outcomes == [False] * STABILITY_RUNS, outcomes


@pytest.mark.asyncio
async def test_live_eval_zhangsan_complete_stability(executor):
    """Same complete input must stay satisfactory=True across repeats."""
    outcomes: list[bool] = []
    for i in range(STABILITY_RUNS):
        result = await executor._summarize_with_evaluation(
            original_query="张三买了哪些东西",
            task_results={
                1: "U001 的订单商品：ORD-001 iPhone 15 Pro；ORD-003 AirPods Pro；ORD-016 小米 13 Ultra。",
            },
            delegate_results={"user-agent": "张三对应的用户ID为 U001。"},
            execution_flow_tasks=_ef_zhangsan_complete(),
            user_id="live-test",
            run_id=f"summarize-eval-complete-stab-{i}",
        )
        _dump_eval(f"eval/complete-stab-{i+1}/{STABILITY_RUNS}", result)
        outcomes.append(result.satisfactory)
        assert "iPhone" in result.answer or "AirPods" in result.answer or "小米" in result.answer
    assert outcomes == [True] * STABILITY_RUNS, outcomes
