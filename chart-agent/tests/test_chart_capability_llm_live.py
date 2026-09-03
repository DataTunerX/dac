"""Live LLM tests for ChartAgent capability check (50 adversarial cases).

Design principles:
1) Trap false-positives: 分布/分组/占比/趋势/排行 without explicit 画图 → F/F
2) Trap false-contribute: "if DB returns data I could plot" → F/F
3) True handle: explicit viz verb + plottable data already in query
4) Missing data: explicit viz but proprietary series absent → F/F
5) Peer: only chart half with data → handle F, contribute T
6) Controls: same word "分布" with 画饼图+data → handle

Stability:
  CHART_CAP_LIVE_STABILITY_RUNS=2  (default 1) requires identical flags across runs

Requires DASHSCOPE_API_KEY (+ optional DASHSCOPE_MODEL=deepseek-v4-flash-0731)
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

from agent import chart_agent as ca
from agent.tool_call_utils import invoke_llm_with_tool
from model_sdk.api.model_manager import ModelManager


CHART_SKILLS = (
    "- echarts: generate ECharts option JSON from tabular/series data "
    "(tags: chart, visualization)\n"
    "- mermaid: generate Mermaid diagrams from structural descriptions "
    "(tags: diagram, mermaid)"
)


@dataclass(frozen=True)
class ChartCapCase:
    name: str
    category: str
    query: str
    expect_can_handle: bool
    expect_can_contribute: Optional[bool]
    note: str = ""


CASES: list[ChartCapCase] = [
    # ========== T traps: stats/distribution WITHOUT viz (20) ==========
    ChartCapCase("T01_beijing_product_distribution_group_stats", "trap_stats",
                 "查询北京用户购买的商品分布（分组统计）", False, False,
                 "用户原话复现"),
    ChartCapCase("T02_shanghai_order_amount_distribution", "trap_stats",
                 "统计上海门店的订单金额分布", False, False, "分布无画图"),
    ChartCapCase("T03_category_sales_group_by", "trap_stats",
                 "按商品类目分组统计本月销售额", False, False, "分组统计"),
    ChartCapCase("T04_refund_reason_ratio", "trap_stats",
                 "查询各类退款原因的占比", False, False, "占比无画饼图"),
    ChartCapCase("T05_order_volume_trend_colloquial", "trap_stats",
                 "看一下最近一周用户下单量的趋势", False, False, "口语趋势"),
    ChartCapCase("T06_top10_products", "trap_stats",
                 "查出购买次数最多的前10个商品", False, False, "排行"),
    ChartCapCase("T07_guangzhou_member_spend_distribution", "trap_stats",
                 "帮我查一下广州会员的消费金额分布情况", False, False, "分布情况"),
    ChartCapCase("T08_channel_active_users_group", "trap_stats",
                 "按渠道分组统计活跃用户数", False, False, "分组计数"),
    ChartCapCase("T09_payment_method_share", "trap_stats",
                 "统计各支付方式的使用份额", False, False, "份额≠画图"),
    ChartCapCase("T10_store_gmv_ranking", "trap_stats",
                 "列出本月 GMV 最高的 5 家门店", False, False, "榜单"),
    ChartCapCase("T11_coupon_redeem_distribution", "trap_stats",
                 "查询优惠券核销次数的分布", False, False, "分布查询"),
    ChartCapCase("T12_age_bucket_user_count", "trap_stats",
                 "按年龄段分组统计注册用户数", False, False, "年龄段分组"),
    ChartCapCase("T13_hourly_order_histogram_word", "trap_stats",
                 "统计今天每小时的下单量", False, False, "直方图语义但无画图"),
    ChartCapCase("T14_inventory_sku_share", "trap_stats",
                 "查一下各 SKU 库存占比", False, False, "占比查询"),
    ChartCapCase("T15_campaign_conversion_compare", "trap_stats",
                 "对比各营销活动的转化率", False, False, "对比≠柱状图请求"),
    ChartCapCase("T16_region_sales_summary", "trap_stats",
                 "汇总华北、华东、华南的销售额", False, False, "汇总表"),
    ChartCapCase("T17_repeat_purchase_rate", "trap_stats",
                 "计算最近 30 天复购率", False, False, "指标计算"),
    ChartCapCase("T18_device_online_ratio", "trap_stats",
                 "统计在线设备与离线设备的比例", False, False, "比例无画图"),
    ChartCapCase("T19_ticket_priority_breakdown", "trap_stats",
                 "按优先级统计打开中的工单数量", False, False, "breakdown 查询"),
    ChartCapCase("T20_flight_delay_distribution", "trap_stats",
                 "查询延误航班按航司的分布", False, False, "分布+航司"),
    # ========== T traps: live lookup / non-viz (8) ==========
    ChartCapCase("T21_inventory_payment_join", "trap_live",
                 "查询库存变化记录中涉及销售的商品及对应订单的支付状态",
                 False, False, "跨域 live"),
    ChartCapCase("T22_order_payment_by_id", "trap_live",
                 "查询订单 ORD-2025-00001 的支付状态和支付流水号",
                 False, False, "订单 live"),
    ChartCapCase("T23_user_profile", "trap_live",
                 "查询用户张三的手机号和注册日期", False, False, "用户档案"),
    ChartCapCase("T24_invoice_amount", "trap_live",
                 "发票号 INV-9001 的开票金额是多少", False, False, "发票 live"),
    ChartCapCase("T25_pure_math", "trap_nonviz",
                 "计算 (128 + 64) * 3 / 2", False, False, "纯计算"),
    ChartCapCase("T26_weather", "trap_nonviz",
                 "北京明天天气怎么样", False, False, "天气"),
    ChartCapCase("T27_policy", "trap_nonviz",
                 "差旅报销需要哪些审批节点？", False, False, "制度"),
    ChartCapCase("T28_code_qa", "trap_nonviz",
                 "支付网关超时重试逻辑在哪个类里实现？", False, False, "代码"),
    # ========== H handle: viz + data (12) ==========
    ChartCapCase("H01_line_monthly", "handle",
                 "请根据以下数据画折线图：一月 10，二月 15，三月 12，四月 20",
                 True, None, "折线+数据"),
    ChartCapCase("H02_pie_percents", "handle",
                 "用饼图展示：A 类 30%，B 类 45%，C 类 25%",
                 True, None, "饼图+占比"),
    ChartCapCase("H03_bar_cities", "handle",
                 "画柱状图对比：上海 120、北京 98、广州 85、深圳 110",
                 True, None, "柱状+数值"),
    ChartCapCase("H04_table_to_bar", "handle",
                 "把这张表画成柱状图：产品,销量\nP1,40\nP2,55\nP3,33",
                 True, None, "表→柱状"),
    ChartCapCase("H05_mermaid_flow", "handle",
                 "用 Mermaid 画一个：用户下单 -> 支付 -> 发货 的流程图",
                 True, None, "Mermaid 流程"),
    ChartCapCase("H06_echarts_radar", "handle",
                 "请用 ECharts 画雷达图，维度：速度 80、力量 60、耐力 90、技巧 70",
                 True, None, "雷达+维度"),
    ChartCapCase("H07_distribution_word_but_pie_with_data", "handle",
                 "请画一张饼图展示商品分布：手机 40%、耳机 25%、充电器 35%",
                 True, None, "对照 T01：有分布词但明确画饼+数据"),
    ChartCapCase("H08_trend_word_with_series", "handle",
                 "画趋势折线图，数据：D1=3,D2=5,D3=4,D4=8,D5=6",
                 True, None, "对照口语趋势：有画+序列"),
    ChartCapCase("H09_share_word_with_pie_data", "handle",
                 "用饼图画各支付方式份额：微信 50%，支付宝 35%，银行卡 15%",
                 True, None, "对照份额查询"),
    ChartCapCase("H10_mermaid_sequence", "handle",
                 "用 Mermaid 画时序图：客户端请求网关，网关调用库存服务，库存返回成功",
                 True, None, "时序图"),
    ChartCapCase("H11_stacked_bar_with_matrix", "handle",
                 "画堆叠柱状图：华北 食品=20 百货=30；华东 食品=25 百货=40",
                 True, None, "堆叠+矩阵数据"),
    ChartCapCase("H12_scatter_with_points", "handle",
                 "画散点图：点 (1,2) (2,3) (3,5) (4,4) (5,7)",
                 True, None, "散点+坐标"),
    # ========== M missing proprietary data despite viz (6) ==========
    ChartCapCase("M01_bar_store_sales_no_data", "missing",
                 "请画一张本月各门店销售额对比柱状图", False, False,
                 "明确画图缺序列"),
    ChartCapCase("M02_line_gmv_no_data", "missing",
                 "帮我画一下最近 30 天 GMV 趋势折线图", False, False,
                 "缺逐日 GMV"),
    ChartCapCase("M03_pie_refund_no_data", "missing",
                 "画饼图展示各类退款原因占比", False, False,
                 "缺退款占比"),
    ChartCapCase("M04_pie_beijing_distribution_no_data", "missing",
                 "请把北京用户购买的商品分布画成饼图", False, False,
                 "对照 T01：加了画饼仍无数据"),
    ChartCapCase("M05_heatmap_region_hour_no_data", "missing",
                 "画热力图展示各区域每小时下单量", False, False,
                 "缺区域×小时矩阵"),
    ChartCapCase("M06_funnel_conversion_no_data", "missing",
                 "画漏斗图展示从曝光到下单的转化", False, False,
                 "缺漏斗各步数值"),
    # ========== P peer (4) ==========
    ChartCapCase("P01_peer_order_and_line_with_data", "peer",
                 "请分别独立完成两项（对等主题）：(1) 查询订单 ORD-2025-00001 支付状态 "
                 "(2) 用已给数据画折线图：一月 10，二月 15，三月 12",
                 False, True, "仅贡献图表半边"),
    ChartCapCase("P02_peer_weather_and_pie_with_data", "peer",
                 "请分别独立完成两项（对等主题）：(1) 北京明天是否下雨 "
                 "(2) 用饼图展示：红 40%，蓝 60%",
                 False, True, "仅贡献饼图半边"),
    ChartCapCase("P03_peer_two_business_distributions", "peer",
                 "请分别独立查询以下两项（对等主题）：(1) 北京用户购买商品分布 "
                 "(2) 上海门店订单金额分布",
                 False, False, "双业务统计，Chart 两边都不能产出"),
    ChartCapCase("P04_peer_stats_and_chart_missing_data", "peer",
                 "请分别独立完成两项（对等主题）：(1) 按类目分组统计销售额 "
                 "(2) 画柱状图展示本月各门店销售额",
                 False, False, "两边都缺可绘图数据/非图表职责"),
]


def _stability_runs() -> int:
    raw = os.getenv("CHART_CAP_LIVE_STABILITY_RUNS", "1").strip()
    try:
        return max(1, min(5, int(raw)))
    except ValueError:
        return 1


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


async def _judge(case: ChartCapCase) -> dict[str, Any]:
    prompt = ca.CHART_CAPABILITY_CHECK_PROMPT.format(
        agent_name="chart-agent",
        agent_description="Generate ECharts/Mermaid charts from provided data",
        agent_skills=CHART_SKILLS,
        history="(none)",
        query=case.query,
    )
    tool = StructuredTool(
        name="evaluate_capability",
        description="Evaluate whether this chart agent can handle the query.",
        args_schema=ca.CapabilityCheckToolResult,
        func=None,
        coroutine=None,
    )
    data = await invoke_llm_with_tool(
        llm=_llm(),
        tool=tool,
        messages=[HumanMessage(content=prompt)],
        metadata={
            "run_id": f"chart-live-{case.name}",
            "trace_id": "e" * 32,
            "user_id": "chart-capability-live",
        },
        tool_choice="evaluate_capability",
        span_name="chart-capability-live",
        span_input={"query": case.query, "case": case.name},
    )
    assert data is not None, "LLM did not call evaluate_capability"
    return data


def _flags(data: dict[str, Any]) -> tuple[bool, bool]:
    return bool(data.get("can_handle")), bool(data.get("can_contribute"))


def test_chart_prompt_guards_distribution_false_positive():
    prompt = ca.CHART_CAPABILITY_CHECK_PROMPT
    assert "D1)" in prompt and "D3)" in prompt
    assert "分布/统计/分组" in prompt
    assert "hypothetical future chart" in prompt or "if another agent fetches" in prompt
    assert "Call evaluate_capability" in prompt
    for banned in ("ORD-2025", "张三", "步骤 1 - 用户意图"):
        assert banned not in prompt


def test_suite_design_invariants():
    assert len(CASES) == 50
    names = [c.name for c in CASES]
    assert len(names) == len(set(names)), "duplicate case names"
    assert "T01_beijing_product_distribution_group_stats" in names
    assert "H07_distribution_word_but_pie_with_data" in names
    assert "M04_pie_beijing_distribution_no_data" in names
    traps = [c for c in CASES if c.category.startswith("trap")]
    handles = [c for c in CASES if c.category == "handle"]
    missing = [c for c in CASES if c.category == "missing"]
    peers = [c for c in CASES if c.category == "peer"]
    assert len(traps) == 28
    assert len(handles) == 12
    assert len(missing) == 6
    assert len(peers) == 4
    for c in traps + missing:
        assert c.expect_can_handle is False
        assert c.expect_can_contribute is False
    for c in handles:
        assert c.expect_can_handle is True


@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live chart capability tests",
)
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_chart_capability_live(case: ChartCapCase):
    runs = _stability_runs()
    outcomes: list[tuple[bool, bool]] = []
    last: dict[str, Any] = {}
    for i in range(runs):
        last = await _judge(case)
        outcomes.append(_flags(last))

    can_handle, can_contribute = outcomes[0]
    reason = str(last.get("reason") or "")
    print(
        f"\n[{case.category}/{case.name}] runs={outcomes} "
        f"conf={last.get('confidence')} | note={case.note} | "
        f"reason={reason[:160]}"
    )
    assert len(set(outcomes)) == 1, f"unstable across {runs} runs: {outcomes}"
    assert can_handle is case.expect_can_handle, (
        f"{case.name}: handle expected {case.expect_can_handle}, got {can_handle}; "
        f"reason={reason[:350]}"
    )
    if case.expect_can_contribute is not None:
        assert can_contribute is case.expect_can_contribute, (
            f"{case.name}: contribute expected {case.expect_can_contribute}, "
            f"got {can_contribute}; reason={reason[:350]}"
        )
