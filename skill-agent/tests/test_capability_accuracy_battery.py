"""能力检查准确性全面测试 — 目标 100% 准确率

用法:
  DASHSCOPE_API_KEY=sk-xxx \
  DASHSCOPE_MODEL=deepseek-v4-flash-0731 \
  python -m pytest tests/test_capability_accuracy_battery.py -q -s -v --timeout 120
"""

from __future__ import annotations

import asyncio
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

API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-xxx")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
CONCURRENCY = 4

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ModelManager().get_llm(
            provider="openai_compatible",
            api_key=API_KEY,
            base_url=BASE_URL,
            model=MODEL,
            temperature=0.01,
            stream=False,
            extra_body={"enable_thinking": False},
        )
    return _llm


# ============================================================
# Agent Definitions
# ============================================================

AGENTS = {
    "product-agent": {
        "name": "product-agent",
        "description": u"商品信息查询智能体，负责商品详情、分类、品牌、价格、规格参数查询",
        "skills": u"""### skill: product_query

# 商品查询

## 数据来源
商品数据 `data/products.txt`，字段以 `|` 分隔：
商品ID | 商品名称 | 分类(服装/食品/电子/家居/美妆) | 品牌 | 价格(元) | 规格参数 | 上架时间 | 上下架状态

## 查询方式
- 按商品ID：`grep "PROD-001" data/products.txt`
- 按分类：`grep "电子" data/products.txt`
- 按品牌：`grep "华为" data/products.txt`
- 允许工具：cat、grep、awk、sort、wc（只读）

## 覆盖场景
1. 按商品ID查商品详情
2. 按分类浏览商品列表
3. 按品牌筛选商品
4. 按价格区间筛选
5. 统计各分类商品数量

## 注意事项
- 不包含库存数量信息
- 不包含用户评价和销量排名
- 不包含商品图片和详细描述文本""",
    },
    "order-agent": {
        "name": "order-agent",
        "description": u"订单查询智能体，管理订单信息、状态跟踪、订单统计",
        "skills": u"""### skill: order_query

# 订单查询

## 数据来源
订单数据 `data/orders.txt`，字段以 `|` 分隔：
订单号 | 用户ID | 商品ID | 商品名称 | 数量 | 订单金额 | 下单时间 | 订单状态(待支付/已支付/待发货/已发货/已完成/已取消) | 支付方式(微信/支付宝/银行卡)

## 查询方式
- 按订单号：`grep "ORD-001" data/orders.txt`
- 按用户ID：`grep "U001" data/orders.txt`
- 按状态筛选：`grep "已取消" data/orders.txt`
- 统计金额：`awk -F'|' '{sum+=$6} END {print sum}' data/orders.txt`
- 允许工具：cat、grep、awk、sort、wc（只读）

## 覆盖场景
1. 查询用户全部订单
2. 查询订单详情
3. 按状态筛选
4. 按支付方式统计
5. 统计订单量和金额

## 注意事项
- 只读，不提供修改/删除/创建
- 不包含商品详细规格和库存
- 订单数据每日凌晨同步，非实时
- 不包含物流配送信息""",
    },
    "user-agent": {
        "name": "user-agent",
        "description": u"用户信息查询智能体，管理用户基本信息、会员等级、注册信息",
        "skills": u"""### skill: user_query

# 用户查询

## 数据来源
用户数据 `data/users.txt`，字段以 `|` 分隔：
用户ID | 用户名 | 电话 | 邮箱 | 注册日期 | 会员等级(普通/银卡/金卡/钻石)

## 查询方式
- 按用户ID：`grep "U001" data/users.txt`
- 按用户名：`grep "张三" data/users.txt`
- 按会员等级：`grep "金卡" data/users.txt`
- 允许工具：cat、grep、awk、sort、wc（只读）

## 覆盖场景
1. 按用户ID查用户详情
2. 按用户名查用户信息
3. 按会员等级统计
4. 查某时间段注册的用户

## 注意事项
- 不包含订单信息，如需订单请用 order_query
- 不包含支付信息
- 不包含收货地址""",
    },
    "inventory-agent": {
        "name": "inventory-agent",
        "description": u"库存管理智能体，管理商品库存、入库出库记录、库存预警",
        "skills": u"""### skill: inventory_query

# 库存查询

## 数据来源
库存数据 `data/inventory.txt`，字段以 `|` 分隔：
仓库ID | 商品ID | 商品名称 | 当前库存量 | 安全库存阈值 | 最近入库时间 | 最近出库时间

## 查询方式
- 按商品ID：`grep "PROD-001" data/inventory.txt`
- 按仓库ID：`grep "WH-001" data/inventory.txt`
- 低于阈值：`awk -F'|' '$4<$5' data/inventory.txt`
- 允许工具：cat、grep、awk、sort、wc（只读）

## 覆盖场景
1. 查商品在各仓库的库存
2. 列出库存低于安全阈值的商品
3. 按仓库统计商品总量

## 注意事项
- 库存数据每15分钟更新，非实时
- 不包含订单和用户数据""",
    },
    "network-monitor-agent": {
        "name": "network-monitor-agent",
        "description": u"网络监控智能体，负责网络延迟、丢包分析、带宽监控、设备状态检查",
        "skills": u"""### skill: network_monitor

# 网络监控与告警

## 数据来源
- 实时指标：`data/network_metrics.json`，字段：设备名 | IP | 延迟ms | 丢包率% | 带宽使用率% | 时间戳
- 事件日志：`data/network_events.log`，每行：时间 | 事件类型 | 设备 | 详情

## 操作命令
- 查延迟：`jq '.[] | select(.latency_ms > 100)' data/network_metrics.json`
- 查丢包：`grep "packet_loss" data/network_events.log`
- 允许工具：jq、grep、awk、sort、wc（只读）

## 覆盖场景
1. 网络延迟监控与告警
2. 丢包率分析与根因定位
3. 带宽使用量趋势分析
4. 交换机/路由器状态检查

## 注意事项
- 不覆盖服务器硬件监控（CPU/内存/磁盘）
- 不覆盖应用层 HTTP 状态码
- 不覆盖安全入侵检测""",
    },
    "hr-agent": {
        "name": "hr-agent",
        "description": u"HR 制度问答智能体，覆盖考勤、请假、报销、差旅、福利、入职离职流程",
        "skills": u"""### skill: hr_policy_qa

# HR 制度问答

## 覆盖范围
- 文档集：公司 HR 制度文档库
- 主题：考勤、请假、报销、差旅、福利、入职离职流程
- 版本：2022-2025
- 语言：中文

## 处理流程
1. 在制度文档中检索相关章节
2. 对检索到的章节做摘要形成回答
3. 回答附带出处（文档名、章节）

## 注意事项
- 不覆盖薪酬体系与期权
- 不覆盖绩效评定与晋升流程""",
    },
    "db-monitor-agent": {
        "name": "db-monitor-agent",
        "description": u"数据库监控智能体，负责慢查询分析、性能指标监控、连接池检查",
        "skills": u"""### skill: db_monitor

# 数据库监控与诊断

## 数据来源
- 慢查询日志：`data/mysql-slow.log`
- 性能指标：`data/db_metrics.json`，字段：QPS | 连接数 | CPU% | 内存% | 磁盘IO | 时间戳

## 操作命令
- 慢查询 Top N：`grep 'slow_query' data/mysql-slow.log | sort -rn | head -10`
- 连接数趋势：`jq '.[] | select(.connections > 100)' data/db_metrics.json`
- 允许工具：grep、awk、sort、jq、head、wc（只读）

## 覆盖场景
1. 慢查询日志分析与根因定位
2. 数据库性能指标监控（QPS/连接/CPU/内存/磁盘）
3. SQL 执行计划分析
4. 连接池状态检查

## 注意事项
- 只覆盖 MySQL，不覆盖 PostgreSQL/MongoDB
- 不覆盖应用层代码性能分析""",
    },
}


# ============================================================
# Test Cases
# ============================================================

@dataclass(frozen=True)
class CapCase:
    id: str
    category: str
    query: str
    agent: str
    expect_handle: bool
    expect_contribute: bool
    expect_d_zero_solid: bool = False
    expect_reason_has: list[str] = field(default_factory=list)
    expect_reason_not: list[str] = field(default_factory=list)
    expect_grade_max: str = ""


CASES: list[CapCase] = [
    # ========== 一、领域不匹配 — 绝对必须 reject ==========
    # product-agent vs 法律
    CapCase("R01", "reject", u"公司辞退员工的法定补偿标准是什么？员工工作了5年月薪12000",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R02", "reject", u"员工在上班途中发生交通事故如何申请工伤认定",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R03", "reject", u"劳动仲裁的申请流程和时效要求是什么",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 电商 vs 税务
    CapCase("R04", "reject", u"小规模纳税人季度销售额45万以下免征增值税的规定是什么",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R05", "reject", u"企业所得税汇算清缴的流程和截止日期",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R06", "reject", u"如何在报税系统里申报出口退税",
            "inventory-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 电商 vs 医疗
    CapCase("R07", "reject", u"糖尿病患者的饮食控制指南是什么？每天糖分摄入应控制多少克",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R08", "reject", u"高血压患者适合做什么运动？每周运动量建议是多少",
            "user-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 网络监控 vs 社保/人事
    CapCase("R09", "reject", u"养老保险的缴费基数和比例是多少？个人账户怎么计算",
            "network-monitor-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R10", "reject", u"员工产假的法定天数和工资标准是什么",
            "network-monitor-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # DB 监控 vs 非 IT 领域
    CapCase("R11", "reject", u"如何办理商标注册？需要准备哪些材料",
            "db-monitor-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("R12", "reject", u"二手房交易流程和税费计算方式是什么",
            "db-monitor-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # HR Agent 排除项
    CapCase("R13", "reject", u"公司今年的薪酬调整方案是什么？涨薪幅度是多少",
            "hr-agent", False, False, expect_d_zero_solid=True,
            expect_reason_has=[u"明确无", u"不覆盖"]),
    CapCase("R14", "reject", u"绩效评定标准和员工晋升条件是什么",
            "hr-agent", False, False, expect_d_zero_solid=True,
            expect_reason_has=[u"明确无", u"不覆盖"]),
    CapCase("R15", "reject", u"员工股票期权的行权条件和流程是什么",
            "hr-agent", False, False, expect_d_zero_solid=True,
            expect_reason_has=[u"明确无", u"不覆盖"]),
    # 纯翻译/生成 -> 这些 agent 不应 handle
    CapCase("R16", "reject", u"把这段英文翻译成中文 The quick brown fox jumps over the lazy dog",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D"),
    CapCase("R17", "reject", u"帮我写一首关于春天的小诗",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D"),

    # ========== 二、精准匹配 — 绝对必须 pass ==========
    CapCase("M01", "match", u"查询商品 PROD-001 的价格和品牌",
            "product-agent", True, True),
    CapCase("M02", "match", u"列出所有电子分类的商品",
            "product-agent", True, True),
    CapCase("M03", "match", u"查询订单 ORD-001 的详细信息，包括订单状态和支付方式",
            "order-agent", True, True),
    CapCase("M04", "match", u"统计所有已取消订单的数量",
            "order-agent", True, True),
    CapCase("M05", "match", u"查询用户 U001 的详细信息，包括电话和会员等级",
            "user-agent", True, True),
    CapCase("M06", "match", u"统计金卡会员的数量",
            "user-agent", True, True),
    CapCase("M07", "match", u"查询商品 PROD-001 在仓库 WH-001 的库存量",
            "inventory-agent", True, True),
    CapCase("M08", "match", u"列出所有库存低于安全阈值的商品",
            "inventory-agent", True, True),
    CapCase("M09", "match", u"交换机 SW-001 最近的延迟有没有异常？丢包率是多少",
            "network-monitor-agent", True, True),
    CapCase("M10", "match", u"列出最近一小时的丢包事件",
            "network-monitor-agent", True, True),
    CapCase("M11", "match", u"公司的年假申请流程是什么？需要提前多少天申请",
            "hr-agent", True, True),
    CapCase("M12", "match", u"出差报销需要提供哪些材料？审批流程是什么",
            "hr-agent", True, True),
    CapCase("M13", "match", u"帮我分析最近一小时的慢查询日志，列出 TOP 5 慢查询",
            "db-monitor-agent", True, True),
    CapCase("M14", "match", u"当前数据库连接数是否超过阈值？QPS 趋势如何",
            "db-monitor-agent", True, True),

    # ========== 三、跨领域贡献 — 能贡献但不能独立完成 ==========
    CapCase("C01", "contribute", u"张三最近买了哪些东西？查一下他的订单详情",
            "user-agent", False, True),
    CapCase("C02", "contribute", u"商品 PROD-001 在哪些仓库有库存？价格是多少",
            "product-agent", False, True),
    CapCase("C03", "contribute", u"用户 U001 订购的 ORD-001 发货了没有？物流进度查一下",
            "order-agent", False, True),

    # ========== 四、边界/对抗 ==========
    # 4.1 关键词在语境中但不是主业
    CapCase("E01", "edge", u"我需要一个用户数据库来存储客户信息，帮我推荐一个数据库方案",
            "user-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("E02", "edge", u"MySQL 的订单表应该怎么设计索引",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("E03", "edge", u"如何给商品数据表做分区优化",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 4.2 语义模糊但领域不匹配
    CapCase("E04", "edge", u"分析一下当前的行情",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 4.3 跨领域但有同名字段
    CapCase("E05", "edge", u"这个月的工资单上有哪些扣款项目",
            "order-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("E06", "edge", u"产品销售税率的计算公式是什么",
            "product-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    # 4.4 写入操作 — 同领域但 O=0 拒绝（数据仍在领域中，D 不应为 0）
    CapCase("E07", "edge", u"把 ORD-001 订单的状态改成已取消",
            "order-agent", False, False),
    CapCase("E08", "edge", u"在商品表里新增一个商品 PROD-999，价格 999",
            "product-agent", False, False),
    # 4.5 天气/体育/娱乐
    CapCase("E09", "edge", u"北京明天天气怎么样？会下雨吗",
            "user-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
    CapCase("E10", "edge", u"2024年奥运会中国获得多少枚金牌",
            "db-monitor-agent", False, False, expect_d_zero_solid=True, expect_grade_max="D",
            expect_reason_has=[u"明确无"]),
]


# ============================================================
# Runner
# ============================================================

async def _judge(case: CapCase) -> dict[str, Any]:
    agent = AGENTS[case.agent]
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=agent["name"],
        agent_description=agent["description"],
        agent_skills=agent["skills"],
        history="(none)",
        query=case.query,
    )
    tool = StructuredTool(
        name="evaluate_capability",
        description=u"按 I/D/O/R/C 五个维度评估 Agent 对用户问题的能力",
        args_schema=capability_chain.CapabilityChainResult,
        func=None, coroutine=None,
    )
    try:
        data = await invoke_llm_with_tool(
            llm=get_llm(),
            tool=tool,
            messages=[HumanMessage(content=prompt)],
            metadata={"run_id": f"acc-{case.id}", "trace_id": "f"*32, "user_id": "acc"},
            tool_choice="evaluate_capability",
            span_name="accuracy",
            span_input={"cid": case.id, "cat": case.category},
        )
    except Exception as e:
        return {"ok": False, "error": str(e)}

    if data is None:
        return {"ok": False, "error": "no tool call"}

    chain = capability_chain.parse_chain_result(data)
    agg = capability_chain.aggregate(chain)

    steps_d = []
    for s in chain.steps:
        steps_d.append({
            "id": s.step_id, "op": s.operation, "desc": s.description[:80],
            "Dr": s.data_coverage.ratio, "Dreq": s.data_coverage.required,
            "Dmat": s.data_coverage.matched, "Dev": s.data_coverage.evidence_strength,
            "O": s.operation_capability,
            "ss": round(agg.step_scores.get(s.step_id, 0), 3),
        })

    all_d0solid = all(
        s.data_coverage.ratio == 0.0 and s.data_coverage.evidence_strength == "solid"
        for s in chain.steps
    )

    return {
        "ok": True,
        "can_handle": agg.can_handle,
        "can_contribute": agg.can_contribute,
        "confidence": agg.confidence,
        "handle_score": agg.handle_score,
        "evidence_grade": chain.evidence_grade,
        "reason": (chain.reason or "")[:500],
        "steps_d": steps_d,
        "all_d0solid": all_d0solid,
    }


async def _run_with_sem(sem, case):
    async with sem:
        return await _judge(case)


# ============================================================
# Parametrized Test
# ============================================================

_global_results: dict[str, Any] = {}

@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
async def test_capability_accuracy(case: CapCase) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    result = await _run_with_sem(sem, case)

    assert result["ok"], f"[{case.id}] LLM call failed: {result.get('error')}"

    h, c = result["can_handle"], result["can_contribute"]
    score, conf, grade = result["handle_score"], result["confidence"], result["evidence_grade"]

    _global_results[case.id] = {
        "pass": True, "h": h, "c": c, "score": score, "grade": grade,
    }

    print(f"\n[{case.id}] {case.category.upper()} {case.agent} | {case.query[:60]}...")
    print(f"  h={h} c={c} score={score:.3f} conf={conf:.3f} grade={grade} steps={len(result['steps_d'])}")
    for sd in result["steps_d"]:
        print(f"    S{sd['id']}({sd['op']}): D={sd['Dr']:.2f}({sd['Dev']}|req={sd['Dreq']}|mat={sd['Dmat']}) O={sd['O']:.1f} -> {sd['ss']:.3f}")

    # 1. can_handle
    assert h is case.expect_handle, (
        f"[{case.id}] h mismatch: expected={case.expect_handle} got={h} score={score:.3f}"
    )
    # 2. can_contribute
    assert c is case.expect_contribute, (
        f"[{case.id}] c mismatch: expected={case.expect_contribute} got={c}"
    )
    # 3. D all zero solid
    if case.expect_d_zero_solid:
        assert result["all_d0solid"], (
            f"[{case.id}] expected all D=0(solid), got: " +
            " | ".join(f"S{s['id']}: D={s['Dr']}({s['Dev']})" for s in result["steps_d"])
        )
    # 4. reason checks
    reason = result.get("reason", "")
    for sub in case.expect_reason_has:
        assert sub in reason, f"[{case.id}] reason missing '{sub}': {reason[:200]}"
    for sub in case.expect_reason_not:
        assert sub not in reason, f"[{case.id}] reason has forbidden '{sub}': {reason[:200]}"
    # 5. evidence grade max
    if case.expect_grade_max:
        ranks = {"A": 1, "B": 2, "C": 3, "D": 4}
        assert ranks.get(grade, 99) >= ranks.get(case.expect_grade_max, 99), (
            f"[{case.id}] grade should be <= {case.expect_grade_max}, got '{grade}'"
        )


# ============================================================
# Summary (printed after all parametrized tests)
# ============================================================

def pytest_sessionfinish(session, exitstatus):
    if not _global_results:
        return
    total = len(_global_results)
    passed = sum(1 for v in _global_results.values() if v["pass"])
    print(f"\n{'='*60}")
    print(f" ACCURACY: {passed}/{total} ({passed/total*100:.1f}%)")
    print(f"{'='*60}")
    if passed < total:
        failed = [k for k, v in _global_results.items() if not v["pass"]]
        print(f" FAILED: {failed}")
    else:
        print(" ALL PASSED!")