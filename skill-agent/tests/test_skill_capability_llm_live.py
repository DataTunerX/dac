"""Live LLM tests for SkillAgent capability check.

Requires:
  DASHSCOPE_API_KEY
  DASHSCOPE_MODEL (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=... DASHSCOPE_MODEL=deepseek-v4-flash-0731 \\
    python -m pytest tests/test_skill_capability_llm_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import skill_agent as sa
from agent.tool_call_utils import invoke_llm_with_tool
from model_sdk.api.model_manager import ModelManager


pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live skill capability tests",
)

WEATHER_SKILLS = (
    "- weather: query city forecast and temperature (tags: weather)"
)
CALC_SKILLS = (
    "- calculator: evaluate arithmetic expressions (tags: math, calc)"
)
SEARCH_SKILLS = (
    "- web_search: general web search via retrieval API (tags: search)"
)


@dataclass(frozen=True)
class SkillCapCase:
    name: str
    query: str
    skills: str
    agent_name: str
    agent_description: str
    expect_can_handle: bool
    expect_can_contribute: bool


CASES = [
    SkillCapCase(
        "weather_reject_inventory_payment",
        "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        False,
        False,
    ),
    SkillCapCase(
        "weather_reject_order_lookup",
        "查询订单 ORD-2025-00001 的支付状态和支付流水号",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        False,
        False,
    ),
    SkillCapCase(
        "weather_reject_user_profile",
        "查询用户张三的手机号和注册日期",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        False,
        False,
    ),
    SkillCapCase(
        "weather_handle_beijing_forecast",
        "北京明天天气怎么样",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        True,
        True,
    ),
    SkillCapCase(
        "weather_handle_shanghai_temp",
        "上海今天气温多少度",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        True,
        True,
    ),
    SkillCapCase(
        "calc_handle_arithmetic",
        "计算 (128 + 64) * 3 / 2",
        CALC_SKILLS,
        "calc-skill-agent",
        "Local calculator skill agent",
        True,
        True,
    ),
    SkillCapCase(
        "calc_reject_live_invoice",
        "发票号 INV-9001 的开票金额是多少",
        CALC_SKILLS,
        "calc-skill-agent",
        "Local calculator skill agent",
        False,
        False,
    ),
    SkillCapCase(
        "search_reject_proprietary_inventory",
        "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
        SEARCH_SKILLS,
        "search-skill-agent",
        "General web search skill agent",
        False,
        False,
    ),
    SkillCapCase(
        "weather_reject_peer_business_and_weather_as_handle",
        "请分别独立查询以下两项（对等主题）：(1) 启用中的营销活动列表 (2) 北京明天是否下雨",
        WEATHER_SKILLS,
        "weather-skill-agent",
        "Local weather skill agent",
        False,
        True,
    ),
]


def _llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731"),
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


async def _judge(case: SkillCapCase) -> dict[str, Any]:
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=case.agent_name,
        agent_description=case.agent_description,
        agent_skills=case.skills,
        history="(none)",
        query=case.query,
    )
    tool = StructuredTool(
        name="evaluate_capability",
        description="Evaluate whether this skill agent can handle the query.",
        args_schema=sa.CapabilityCheckToolResult,
        func=None,
        coroutine=None,
    )
    data = await invoke_llm_with_tool(
        llm=_llm(),
        tool=tool,
        messages=[HumanMessage(content=prompt)],
        metadata={
            "run_id": f"skill-live-{case.name}",
            "trace_id": "d" * 32,
            "user_id": "skill-capability-live",
        },
        tool_choice="evaluate_capability",
        span_name="skill-capability-live",
        span_input={"query": case.query, "case": case.name},
    )
    assert data is not None, "LLM did not call evaluate_capability"
    return data


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_skill_capability_live(case: SkillCapCase):
    data = await _judge(case)
    can_handle = bool(data.get("can_handle"))
    can_contribute = bool(data.get("can_contribute"))
    reason = str(data.get("reason") or "")
    print(
        f"\n[{case.name}] handle={can_handle} contribute={can_contribute} "
        f"conf={data.get('confidence')} reason={reason[:220]}"
    )
    assert can_handle is case.expect_can_handle
    assert can_contribute is case.expect_can_contribute
