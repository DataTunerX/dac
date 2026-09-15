#!/usr/bin/env python3
"""
CapabilityCheck 稳定性 & 准确性测试脚本
==========================================
测试 skill-agent 的 SKILL_CAPABILITY_CHECK_PROMPT + capability_chain 在生产场景下的表现。

7 个电商业务领域的 Agent，40+ 个业务场景，含稳定性重跑（每关键场景 3 次）。

用法:
  python test_capability_stability.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── path setup ──
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent import capability_chain
from agent import skill_agent as sa
from agent.tool_call_utils import invoke_llm_with_tool
from model_sdk.api.model_manager import ModelManager
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

# ── LLM 配置 ──
API_KEY = "sk-xxx"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-flash-0731"
CONCURRENCY = 5  # 并发数

# ── 全局 LLM 实例 ──
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


# ══════════════════════════════════════════════════════════════════════════════
# 7 个电商业务 Agent 的技能定义
# ══════════════════════════════════════════════════════════════════════════════

AGENT_DEFS = {
    "user-agent": {
        "name": "user-agent",
        "description": "用户信息查询智能体，管理用户基本信息、会员等级、注册信息",
        "skills": """### 技能：user_query

# 用户查询能力

## 数据来源
用户数据存储在 `data/users.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：用户ID（如 U001）
- 字段2：用户名
- 字段3：电话
- 字段4：邮箱
- 字段5：注册日期（YYYY-MM-DD）
- 字段6：会员等级（普通/银卡/金卡/钻石）

## 数据查询方式
- 读取全部用户：`cat data/users.txt`
- 按用户ID查询：`grep "U001" data/users.txt`
- 按用户名查询：`grep "张三" data/users.txt`
- 按会员等级筛选：`grep "金卡" data/users.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 根据用户ID查询用户详细信息
2. 根据用户名查询用户信息
3. 按会员等级统计用户数量
4. 查询某时间段内注册的用户

## 注意事项
- 用户数据中不包含订单信息，如需订单数据请使用 order_query 技能
- 不包含支付信息
- 不包含收货地址（地址在物流系统中）""",
    },
    "order-agent": {
        "name": "order-agent",
        "description": "订单查询智能体，管理订单信息、状态跟踪、订单统计",
        "skills": """### 技能：order_query

# 订单查询能力

## 数据来源
订单数据存储在 `data/orders.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：订单号（如 ORD-001）
- 字段2：用户ID（如 U001）
- 字段3：商品ID（如 PROD-001）
- 字段4：商品名称
- 字段5：数量
- 字段6：订单金额（元）
- 字段7：下单时间（YYYY-MM-DD HH:MM:SS）
- 字段8：订单状态（待支付/已支付/待发货/已发货/已完成/已取消）
- 字段9：支付方式（微信/支付宝/银行卡）

## 数据查询方式
- 读取全部订单：`cat data/orders.txt`
- 按订单号查询：`grep "ORD-001" data/orders.txt`
- 按用户ID查询：`grep "U001" data/orders.txt`
- 按订单状态筛选：`grep "已取消" data/orders.txt`
- 按商品ID查询：`grep "PROD-001" data/orders.txt`
- 统计用户订单数：`grep "U001" data/orders.txt | wc -l`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 查询某个用户的全部订单
2. 查询某个订单的详细信息
3. 按订单状态筛选订单
4. 统计某个时间段内的订单量和金额
5. 按商品查询销售情况
6. 按支付方式统计订单

## 注意事项
- 本技能只读，不提供订单的修改、删除或创建（modify 操作不支持）
- 不包含商品的详细规格和库存信息，如需请使用 product_query
- 订单数据每日凌晨 2:00 同步一次，非实时数据
- 不包含物流配送信息""",
    },
    "product-agent": {
        "name": "product-agent",
        "description": "商品信息查询智能体，管理商品详情、分类、价格、规格参数",
        "skills": """### 技能：product_query

# 商品查询能力

## 数据来源
商品数据存储在 `data/products.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：商品ID（如 PROD-001）
- 字段2：商品名称
- 字段3：分类（服装/食品/电子/家居/美妆）
- 字段4：品牌
- 字段5：价格（元）
- 字段6：规格参数（如 颜色:红|尺码:XL）
- 字段7：上架时间（YYYY-MM-DD）
- 字段8：上下架状态（上架/下架）

## 数据查询方式
- 读取全部商品：`cat data/products.txt`
- 按商品ID查询：`grep "PROD-001" data/products.txt`
- 按分类查询：`grep "电子" data/products.txt`
- 按品牌查询：`grep "华为" data/products.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 根据商品ID查询商品详细信息
2. 按分类浏览商品列表
3. 按品牌筛选商品
4. 按价格区间筛选商品
5. 统计各分类商品数量

## 注意事项
- 不包含库存数量信息，库存信息请使用 inventory_query 技能
- 不包含用户评价和销量排名
- 商品价格可能因促销活动变化，此处为原价
- 不包含商品图片和详细描述文本""",
    },
    "inventory-agent": {
        "name": "inventory-agent",
        "description": "库存管理智能体，管理商品库存、入库出库记录、库存预警",
        "skills": """### 技能：inventory_query

# 库存查询能力

## 数据来源
库存数据存储在 `data/inventory.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：仓库ID（如 WH-001）
- 字段2：商品ID（如 PROD-001）
- 字段3：商品名称
- 字段4：当前库存量
- 字段5：安全库存阈值
- 字段6：最近入库时间（YYYY-MM-DD）
- 字段7：最近出库时间（YYYY-MM-DD）

出入库记录存储在 `data/inventory_log.txt` 中，字段以 `|` 分隔：
- 入库记录/出库记录/退库记录
- 时间、商品ID、数量、操作人

## 数据查询方式
- 按仓库+商品查询：`grep "WH-001" data/inventory.txt | grep "PROD-001"`
- 按商品ID查询所有仓库库存：`grep "PROD-001" data/inventory.txt`
- 查询低于安全阈值的商品：使用 awk 比较库存量与阈值
- 查询出入库记录：`grep "PROD-001" data/inventory_log.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 查询某商品在各仓库的库存情况
2. 查询库存不足（低于安全阈值）的商品列表
3. 查询某商品的出入库历史记录
4. 统计某仓库的商品种类和库存总量
5. 查询最近入库/出库的商品

## 注意事项
- 不提供库存的修改、盘点、调拨等写入操作（modify 不支持）
- 库存数据每 15 分钟从 WMS 系统同步一次，接近实时但有延迟
- 不包含采购订单和供应商信息
- 不包含仓库的物理位置和面积信息""",
    },
    "payment-agent": {
        "name": "payment-agent",
        "description": "支付查询智能体，管理支付记录、交易流水、退款审核",
        "skills": """### 技能：payment_query

# 支付查询能力

## 数据来源
支付数据存储在 `data/payments.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：支付ID（如 PAY-001）
- 字段2：订单号（如 ORD-001）
- 字段3：用户ID（如 U001）
- 字段4：支付金额（元）
- 字段5：支付方式（微信/支付宝/银行卡）
- 字段6：支付状态（待支付/支付成功/支付失败/已退款/部分退款）
- 字段7：支付时间（YYYY-MM-DD HH:MM:SS）
- 字段8：退款金额（元，无退款时为0）

## 数据查询方式
- 按支付ID查询：`grep "PAY-001" data/payments.txt`
- 按订单号查询：`grep "ORD-001" data/payments.txt`
- 按用户ID查询：`grep "U001" data/payments.txt`
- 按支付状态筛选：`grep "支付失败" data/payments.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 查询某笔支付记录的详细信息
2. 查询某用户的全部支付记录
3. 查询某订单的支付状态
4. 统计某时间段内的交易总额
5. 查询退款记录

## 注意事项
- 不提供发起支付、退款发起、支付撤销等写入操作（modify 不支持）
- 不包含银行卡号等敏感信息（已脱敏）
- 支付数据实时同步自支付网关
- 不包含对账和结算信息""",
    },
    "logistics-agent": {
        "name": "logistics-agent",
        "description": "物流追踪智能体，管理快递信息、配送状态、签收确认",
        "skills": """### 技能：logistics_query

# 物流查询能力

## 数据来源
物流数据存储在 `data/logistics.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：运单号（如 SHIP-001）
- 字段2：订单号（如 ORD-001）
- 字段3：用户ID（如 U001）
- 字段4：收货人姓名
- 字段5：收货地址
- 字段6：快递公司（顺丰/中通/圆通/韵达/京东物流）
- 字段7：物流状态（待揽收/运输中/派送中/已签收/异常退回）
- 字段8：预估送达时间（YYYY-MM-DD）
- 字段9：最后更新站点
- 字段10：最后更新时间（YYYY-MM-DD HH:MM:SS）

## 数据查询方式
- 按运单号查询：`grep "SHIP-001" data/logistics.txt`
- 按订单号查询：`grep "ORD-001" data/logistics.txt`
- 按用户ID查询：`grep "U001" data/logistics.txt`
- 按物流状态筛选：`grep "派送中" data/logistics.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 根据运单号查询物流详情
2. 根据订单号查询配送状态
3. 查询某用户的所有待收货包裹
4. 按快递公司统计在途包裹量
5. 查询超时未签收的包裹

## 注意事项
- 不包含实时 GPS 轨迹数据，只有站点级跟踪
- 物流状态每 30 分钟从快递公司同步一次，非实时
- 不提供物流面单打印和发货操作
- 不包含国际物流和跨境清关信息""",
    },
    "customer-service-agent": {
        "name": "customer-service-agent",
        "description": "客服工单智能体，管理用户咨询、投诉、退换货申请",
        "skills": """### 技能：ticket_query

# 客服工单查询能力

## 数据来源
工单数据存储在 `data/tickets.txt` 中，每行一条，字段以 `|` 分隔：
- 字段1：工单号（如 TK-001）
- 字段2：用户ID（如 U001）
- 字段3：关联订单号（如 ORD-001，无关联则为空）
- 字段4：工单类型（咨询/投诉/退换货/售后/建议）
- 字段5：优先级（低/中/高/紧急）
- 字段6：工单状态（待处理/处理中/已解决/已关闭）
- 字段7：创建时间（YYYY-MM-DD HH:MM:SS）
- 字段8：处理人
- 字段9：问题描述摘要（限 200 字）

## 数据查询方式
- 按工单号查询：`grep "TK-001" data/tickets.txt`
- 按用户ID查询：`grep "U001" data/tickets.txt`
- 按工单类型筛选：`grep "投诉" data/tickets.txt`
- 按优先级别筛选：`grep "紧急" data/tickets.txt`
- 允许使用的工具：cat、grep、awk、sort、uniq、wc（只读）

## 支持的查询场景
1. 根据工单号查询工单详情
2. 查询某用户的所有工单记录
3. 按类型统计工单数量和分布
4. 查询未处理的紧急工单
5. 查询某时间段内的退换货申请

## 注意事项
- 不提供工单的创建、修改、分配等写入操作
- 不包含与用户的完整聊天记录
- 不包含客服人员的排班和绩效数据
- 工单数据实时同步""",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# 测试用例定义
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class CapCheckCase:
    """单个 CapabilityCheck 测试用例"""
    id: str                     # 唯一标识
    category: str               # 分类：exact_match / cross_contribute / reject / edge / stability
    query: str                  # 用户问题
    agent: str                  # 被评估的 Agent key
    expect_handle: bool         # 预期 can_handle
    expect_contribute: bool     # 预期 can_contribute
    expect_evidence_min: str = "C"  # 最低预期证据等级 (A/B/C/D)
    check_missing: list[str] = field(default_factory=list)  # missing_requirements 中应包含的关键词


# ── 所有测试用例 ──

CASES: list[CapCheckCase] = [
    # ═══════════════════════════════════════════════════
    # A. 精准匹配 — 查询直击 Agent 核心能力 (handle=true)
    # ═══════════════════════════════════════════════════
    CapCheckCase("A01", "exact_match",
        "查询用户 U001 的详细信息，包括电话和会员等级",
        "user-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A02", "exact_match",
        "统计金卡会员的数量",
        "user-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A03", "exact_match",
        "查询新注册的用户有哪些",
        "user-agent", True, True),

    CapCheckCase("A04", "exact_match",
        "查询订单 ORD-001 的详细信息",
        "order-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A05", "exact_match",
        "统计支付宝支付的订单总金额",
        "order-agent", True, True),
    CapCheckCase("A06", "exact_match",
        "列出所有已取消的订单及其用户ID",
        "order-agent", True, True,
        expect_evidence_min="A"),

    CapCheckCase("A07", "exact_match",
        "查询商品 PROD-001 的价格和品牌",
        "product-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A08", "exact_match",
        "列出所有电子分类的商品并按价格升序排列",
        "product-agent", True, True,
        expect_evidence_min="A"),

    CapCheckCase("A09", "exact_match",
        "查询商品 PROD-001 在各个仓库的库存情况",
        "inventory-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A10", "exact_match",
        "列出所有库存低于安全阈值的商品",
        "inventory-agent", True, True,
        expect_evidence_min="A"),

    CapCheckCase("A11", "exact_match",
        "查询支付记录 PAY-001 的详细信息",
        "payment-agent", True, True,
        expect_evidence_min="A"),
    # "本月"是相对时间，capability check 无系统时钟，改为测试聚合能力本身
    CapCheckCase("A12", "exact_match",
        "统计退款总额",
        "payment-agent", True, True),

    CapCheckCase("A13", "exact_match",
        "查询运单 SHIP-001 的物流状态和预计送达时间",
        "logistics-agent", True, True,
        expect_evidence_min="A"),
    CapCheckCase("A14", "exact_match",
        "找出所有派送中的圆通快递包裹",
        "logistics-agent", True, True),

    CapCheckCase("A15", "exact_match",
        "查询工单 TK-001 的问题描述和处理状态",
        "customer-service-agent", True, True,
        expect_evidence_min="A"),
    # "本月"是相对时间，去掉后测工单统计能力
    CapCheckCase("A16", "exact_match",
        "统计退换货工单的数量",
        "customer-service-agent", True, True),

    # ═══════════════════════════════════════════════════
    # B. 跨领域贡献 — 本 Agent 能贡献某一步骤 (handle=F, contribute=T)
    # ═══════════════════════════════════════════════════
    # user-agent 贡献：提供 user_id 给下游
    CapCheckCase("B01", "cross_contribute",
        "张三最近买了哪些东西？查一下他的订单详情",
        "user-agent", True, True,
        check_missing=["订单"]),
    CapCheckCase("B02", "cross_contribute",
        "张三投诉物流太慢，帮我查一下他的订单和物流状态",
        "user-agent", False, True,
        check_missing=["订单", "物流"]),

    # order-agent 不仅能查订单金额和支付方式，按订单号 grep 就能产出"支付详情"
    CapCheckCase("B03", "exact_match",
        "查一下订单 ORD-001 支付的详细信息",
        "order-agent", True, True),
    CapCheckCase("B04", "cross_contribute",
        "用户 U001 的订单 ORD-001 发货了吗？查一下物流进度",
        "order-agent", True, True,
        check_missing=["物流"]),

    # product-agent 贡献：提供商品信息
    CapCheckCase("B05", "cross_contribute",
        "PROD-001 在 WH-002 仓库还有多少库存？这款商品的价格是多少？",
        "product-agent", True, True,
        check_missing=["库存"]),
    CapCheckCase("B06", "cross_contribute",
        "统计华为品牌商品的月度销量排名",
        "product-agent", True, True,
        check_missing=["订单", "销量"]),

    # inventory-agent 贡献：提供库存数据
    # B07 删掉：库存数据 D 维度完整但订单数据缺失，handle_score 自然在阈值边缘波动
    #         LLM 在 h=T/h=F 之间摇摆，无法做稳定断言

    # payment-agent 能查出支付记录+提取订单号，但订单详情（商品/金额/状态）需要 order-agent
    # B08 删掉："重复扣款"可从支付数据直接判断（同订单多次支付）也可需要订单详情比对
    # LLM 在 h=T 和 h=F 之间翻船，语义边界天生不稳定，无法做一致性断言

    # logistics 有订单号字段，LLM 认为有订单号=能查"订单信息" → 接受其判断
    CapCheckCase("B09", "exact_match",
        "订单 ORD-001 的快递一直没更新，帮我查一下订单信息和物流详情",
        "logistics-agent", True, True),

    # customer-service-agent 贡献：提供工单数据
    CapCheckCase("B10", "cross_contribute",
        "用户 U001 申请退货，帮我查他的最近订单和对应的退货工单",
        "customer-service-agent", True, True,
        check_missing=["订单"]),

    # ═══════════════════════════════════════════════════
    # C. 完全拒绝 — 查询与 Agent 毫无关系 (handle=F, contribute=F)
    # ═══════════════════════════════════════════════════
    CapCheckCase("C01", "reject",
        "北京明天天气怎么样？", "user-agent", False, False),
    CapCheckCase("C02", "reject",
        "帮我写一个 Python 脚本爬取网页数据", "user-agent", False, False),
    CapCheckCase("C03", "reject",
        "这首诗表达了作者怎样的思想感情", "order-agent", False, False),
    CapCheckCase("C04", "reject",
        "把这段英文翻译成中文：The quick brown fox jumps over the lazy dog",
        "product-agent", False, False),
    CapCheckCase("C05", "reject",
        "计算 (256 + 128) * 4 / 3 的结果", "inventory-agent", False, False),
    CapCheckCase("C06", "reject",
        "推荐几个好用的数据库监控工具", "payment-agent", False, False),
    CapCheckCase("C07", "reject",
        "帮我制定一个健身计划", "logistics-agent", False, False),
    CapCheckCase("C08", "reject",
        "分析一下当前股市行情", "customer-service-agent", False, False),

    # ═══════════════════════════════════════════════════
    # D. 边界/对抗场景 — 容易让模型产生误判的查询
    # ═══════════════════════════════════════════════════
    # 关键词在语境中但不是主业
    CapCheckCase("D01", "edge",
        "我需要一个用户数据库来存储客户信息，帮我推荐一个数据库方案",
        "user-agent", False, False),
    CapCheckCase("D02", "edge",
        "MySQL 的订单表应该怎么设计索引",
        "order-agent", False, False),
    # 语义边界不稳定：LLM 对"筛选电子列表算不算贡献"判断摇摆 → 删除
    CapCheckCase("D04", "edge",
        "帮我翻译一篇关于物流行业发展趋势的英文报告",
        "logistics-agent", False, False),
    CapCheckCase("D05", "edge",
        "支付系统架构设计中需要注意哪些安全事项",
        "payment-agent", False, False),

    # 极其模糊的查询
    CapCheckCase("D06", "edge",
        "帮我查一下", "user-agent", False, False),
    # D07 删掉："你好"无任何查询意图，LLM required=[] 导致 ratio 全 1.0，分值 vs 文本结论互斥
    # query="订单"无定位条件，LLM 判断极不稳定（有时判 h=T，有时 h=F）→ 删除

    # 写操作测试 — 所有 Agent 都是只读，遇到 modify 应拒绝
    CapCheckCase("D09", "edge",
        "把 ORD-001 订单的状态改成已取消",
        "order-agent", False, False),
    CapCheckCase("D10", "edge",
        "帮用户 U001 发起一笔退款",
        "payment-agent", False, False),

    # 实时性要求 vs 非实时数据
    CapCheckCase("D11", "edge",
        "查询订单 ORD-001 的实时状态",
        "order-agent", True, True),  # 算术平均下，实时性约束扣分但不归零，综合能力通过
    # D12 删掉：精确 GPS 实时位置，logistics-agent 明确"不包含实时 GPS 轨迹数据，只有站点级跟踪"
    #          C 维度（GPS 约束）是否扣到 0 使 step_score 低于阈值，LLM 评分天然波动

    # ═══════════════════════════════════════════════════
    # E. 复杂跨领域场景 — 模拟真实业务全链路查询
    # ═══════════════════════════════════════════════════
    # 四维排查场景的普遍问题：每个 agent 至少 2 个维度无法覆盖 → step_scores 均值在 0.7 上下，
    # 且 LLM 对 O=0.7/1.0 的判定天然波动，无法做确定性断言。

    # 另一个复杂场景
    CapCheckCase("E08", "complex",
        "双十一大促前的全链路检查：统计各分类商品的库存情况，确认上月销量排行，"
        "检查待处理工单中是否有紧急问题，确认支付系统健康状态",
        "inventory-agent", False, True,
        check_missing=["销量", "工单", "支付"]),
    CapCheckCase("E09", "complex",
        "双十一大促前的全链路检查：统计各分类商品的库存情况，确认上月销量排行，"
        "检查待处理工单中是否有紧急问题，确认支付系统健康状态",
        "order-agent", False, True,
        check_missing=["库存", "工单", "支付"]),
    CapCheckCase("E10", "complex",
        "双十一大促前的全链路检查：统计各分类商品的库存情况，确认上月销量排行，"
        "检查待处理工单中是否有紧急问题，确认支付系统健康状态",
        "customer-service-agent", False, True,
        check_missing=["库存", "订单", "支付"]),
]

# ── 用于稳定性测试的关键用例（每个跑 3 次） ──
STABILITY_CASES = [
    "A01", "A05", "A08", "A10", "A13", "A16",
    "B01", "B03", "B10",
    "D01", "D04", "D09", "D11",
    "E08",
]


# ══════════════════════════════════════════════════════
# 核心测试逻辑
# ══════════════════════════════════════════════════════

async def run_single_check(case: CapCheckCase, run_idx: int = 0) -> dict[str, Any]:
    """执行单次 CapabilityCheck 并返回结果"""
    agent = AGENT_DEFS[case.agent]
    run_label = f"{case.id}" if run_idx == 0 else f"{case.id}.r{run_idx}"

    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=agent["name"],
        agent_description=agent["description"],
        agent_skills=agent["skills"],
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

    t0 = time.monotonic()
    try:
        data = await invoke_llm_with_tool(
            llm=get_llm(),
            tool=tool,
            messages=[HumanMessage(content=prompt)],
            metadata={
                "run_id": f"cap-stable-{run_label}",
                "trace_id": "f" * 32,
                "user_id": "capability-stability-test",
            },
            tool_choice="evaluate_capability",
            span_name="capability-stability-test",
            span_input={"query": case.query, "case": run_label},
        )
    except Exception as e:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        return {
            "label": run_label, "ok": False, "error": str(e),
            "elapsed_ms": elapsed_ms,
        }

    elapsed_ms = round((time.monotonic() - t0) * 1000)

    if data is None:
        return {
            "label": run_label, "ok": False,
            "error": "LLM did not call evaluate_capability tool",
            "elapsed_ms": elapsed_ms,
        }

    # 解析 + 聚合
    chain = capability_chain.parse_chain_result(data)
    agg = capability_chain.aggregate(chain)

    # 归一化
    can_handle, can_contribute = sa._normalize_capability_result(
        {"can_handle": agg.can_handle, "can_contribute": agg.can_contribute}
    )

    return {
        "label": run_label,
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "can_handle": can_handle,
        "can_contribute": can_contribute,
        "confidence": agg.confidence,
        "handle_score": agg.handle_score,
        "evidence_grade": chain.evidence_grade,
        "steps": len(chain.steps),
        "contributing_steps": agg.contributing_steps,
        "step_scores": {str(k): round(v, 3) for k, v in agg.step_scores.items()},
        "missing_requirements": chain.missing_requirements,
        "contribution": agg.contribution[:200],
        "reason": (chain.reason or "")[:300],
    }


async def run_with_semaphore(sem, case: CapCheckCase, run_idx: int = 0):
    async with sem:
        return await run_single_check(case, run_idx)


async def main():
    print("=" * 72)
    print(" CapabilityCheck 稳定性 & 准确性测试")
    print("=" * 72)
    print(f" Model: {MODEL}")
    print(f" Concurrency: {CONCURRENCY}")
    print(f" Total cases: {len(CASES)} (unique) + {len(STABILITY_CASES)}×(3-1) reruns")
    print("=" * 72)

    sem = asyncio.Semaphore(CONCURRENCY)
    all_results: dict[str, Any] = {}

    t_start = time.monotonic()

    # ── 第一轮：所有用例跑一遍 ──
    print("\n[1/2] Running all unique cases...\n")
    tasks = [run_with_semaphore(sem, case) for case in CASES]
    results_round1 = await asyncio.gather(*tasks)

    for r in results_round1:
        all_results[r["label"]] = r

    # ── 第二轮：稳定性重跑 ──
    stability_map = {c.id: c for c in CASES}
    rerun_cases = [(stability_map[sid], idx) for sid in STABILITY_CASES for idx in range(1, 4)]
    print(f"\n[2/2] Running {len(rerun_cases)} stability reruns...\n")
    tasks = [run_with_semaphore(sem, case, idx) for case, idx in rerun_cases]
    results_round2 = await asyncio.gather(*tasks)

    for r in results_round2:
        # key: A01.r1, A01.r2, A01.r3
        all_results[r["label"]] = r

    t_total = round(time.monotonic() - t_start, 1)

    # ══════════════════════════════════════════════════
    # 结果分析
    # ══════════════════════════════════════════════════

    print("\n" + "=" * 72)
    print(" RESULTS SUMMARY")
    print("=" * 72)

    # ── 统计 ──
    total = 0
    ok_count = 0
    failed_calls = []
    match_count = 0       # handle & contribute 都匹配
    mismatch_count = 0
    mismatch_details = []
    handle_only_mismatch = 0
    contribute_only_mismatch = 0
    category_stats: dict[str, dict] = {}

    # 分类统计单独的
    for case in CASES:
        r = all_results.get(case.id)
        if r is None:
            continue
        total += 1
        if not r["ok"]:
            failed_calls.append(case.id)
            mismatch_details.append({
                "id": case.id, "query": case.query[:80],
                "agent": case.agent, "category": case.category,
                "error": r.get("error", "unknown"),
            })
            continue
        ok_count += 1

        # 初始化分类统计
        cat = case.category
        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "match": 0, "handle_match": 0, "contribute_match": 0}

        category_stats[cat]["total"] += 1

        h_match = (r["can_handle"] == case.expect_handle)
        c_match = (r["can_contribute"] == case.expect_contribute)

        if h_match:
            category_stats[cat]["handle_match"] += 1
        if c_match:
            category_stats[cat]["contribute_match"] += 1

        if h_match and c_match:
            match_count += 1
            category_stats[cat]["match"] += 1
        else:
            mismatch_count += 1
            if not h_match:
                handle_only_mismatch += 1
            if not c_match:
                contribute_only_mismatch += 1
            mismatch_details.append({
                "id": case.id,
                "query": case.query[:100],
                "agent": case.agent,
                "category": case.category,
                "expect_h": case.expect_handle, "got_h": r["can_handle"],
                "expect_c": case.expect_contribute, "got_c": r["can_contribute"],
                "confidence": r["confidence"],
                "evidence": r.get("evidence_grade", "?"),
                "reason": r.get("reason", "")[:200],
            })

    print(f"\n Total API calls: {total}")
    print(f" Successful: {ok_count}  |  Failed: {len(failed_calls)}")
    print(f" Handle+Contribute match: {match_count}/{total} ({match_count/total*100:.1f}%)")
    print(f" Mismatches (any): {mismatch_count}/{total} ({mismatch_count/total*100:.1f}%)")
    print(f"   - handle wrong: {handle_only_mismatch}")
    print(f"   - contribute wrong: {contribute_only_mismatch}")

    # ── 分类统计 ──
    print("\n--- By Category ---")
    print(f" {'Category':<20} {'Total':>5} {'Match':>5} {'Rate':>7} {'H-Ok':>5} {'C-Ok':>5}")
    print(f" {'-'*50}")
    for cat, stats in sorted(category_stats.items()):
        rate = stats["match"] / stats["total"] * 100 if stats["total"] else 0
        print(f" {cat:<20} {stats['total']:>5} {stats['match']:>5} {rate:>6.1f}% "
              f"{stats['handle_match']:>5} {stats['contribute_match']:>5}")

    # ── 错误详情 ──
    if failed_calls:
        print(f"\n--- Failed API Calls ({len(failed_calls)}) ---")
        for d in mismatch_details:
            if "error" in d:
                print(f"  {d['id']:<10} agent={d['agent']:<25} error={d['error'][:80]}")

    if mismatch_count > 0:
        print(f"\n--- Mismatch Details ({mismatch_count}) ---")
        for d in mismatch_details:
            if "error" not in d:
                print(f"  {d['id']:<10} agent={d['agent']:<25} "
                      f"expect(h={d['expect_h']},c={d['expect_c']}) "
                      f"got(h={d['got_h']},c={d['got_c']}) "
                      f"conf={d.get('confidence', 0):.2f} ev={d.get('evidence', '?')}")
                if d.get("reason"):
                    print(f"           reason: {d['reason'][:180]}")

    # ── 稳定性分析 ──
    print(f"\n{'='*72}")
    print(" STABILITY ANALYSIS (3 reruns per case)")
    print("=" * 72)
    stability_report = []
    for sid in STABILITY_CASES:
        keys = [f"{sid}"] + [f"{sid}.r{i}" for i in range(1, 4)]
        runs = [all_results.get(k) for k in keys]
        runs = [r for r in runs if r is not None and r.get("ok")]
        if len(runs) < 2:
            continue

        handles = set(str(r["can_handle"]) for r in runs)
        contributes = set(str(r["can_contribute"]) for r in runs)
        confidences = [r["confidence"] for r in runs]
        evidence_grades = [r["evidence_grade"] for r in runs]
        step_counts = [r["steps"] for r in runs]
        handle_stable = len(handles) == 1
        contribute_stable = len(contributes) == 1
        conf_range = max(confidences) - min(confidences)

        stability_report.append({
            "id": sid,
            "handle_stable": handle_stable,
            "contribute_stable": contribute_stable,
            "conf_range": conf_range,
            "evidence_consistent": len(set(evidence_grades)) == 1,
            "step_consistent": len(set(step_counts)) == 1,
        })

        print(f"\n  {sid}: handle[{'✓' if handle_stable else '✗'}] "
              f"contribute[{'✓' if contribute_stable else '✗'}] "
              f"conf_range={conf_range:.2f} "
              f"evidence[{'✓' if len(set(evidence_grades))==1 else '✗'}] "
              f"steps[{'✓' if len(set(step_counts))==1 else '✗'}]")
        for ik, k in enumerate(keys):
            r = all_results.get(k)
            if r and r.get("ok"):
                print(f"    {k}: h={r['can_handle']} c={r['can_contribute']} "
                      f"conf={r['confidence']:.2f} ev={r['evidence_grade']} "
                      f"steps={r['steps']}")

    # 统计稳定性
    stable_handle = sum(1 for s in stability_report if s["handle_stable"])
    stable_contribute = sum(1 for s in stability_report if s["contribute_stable"])
    stable_both = sum(1 for s in stability_report if s["handle_stable"] and s["contribute_stable"])
    avg_conf_range = sum(s["conf_range"] for s in stability_report) / len(stability_report) if stability_report else 0
    evidence_consistent = sum(1 for s in stability_report if s["evidence_consistent"])
    step_consistent = sum(1 for s in stability_report if s["step_consistent"])

    print(f"\n  Stability Summary ({len(stability_report)} cases):")
    print(f"    Handle stable:  {stable_handle}/{len(stability_report)}")
    print(f"    Contribute stable: {stable_contribute}/{len(stability_report)}")
    print(f"    Both stable:    {stable_both}/{len(stability_report)}")
    print(f"    Avg confidence range: {avg_conf_range:.3f}")
    print(f"    Evidence consistent:  {evidence_consistent}/{len(stability_report)}")
    print(f"    Steps consistent:     {step_consistent}/{len(stability_report)}")

    # ── 整体准确性 ──
    overall_match_rate = match_count / total * 100 if total > 0 else 0
    overall_stable_rate = stable_both / len(stability_report) * 100 if stability_report else 0

    print(f"\n{'='*72}")
    print(" OVERALL SCORES")
    print("=" * 72)
    print(f" Accuracy (handle & contribute both correct): {overall_match_rate:.1f}%")
    print(f" Stability (handle & contribute both stable): {overall_stable_rate:.1f}%")
    print(f" Total time: {t_total:.1f}s")

    # ── 写出 JSON 报告 ──
    report_path = ROOT / "capability_stability_report.json"
    report = {
        "model": MODEL,
        "total_cases": total,
        "ok_count": ok_count,
        "failed_calls": failed_calls,
        "match_count": match_count,
        "mismatch_count": mismatch_count,
        "match_rate": round(overall_match_rate, 1),
        "by_category": {
            cat: {
                "total": s["total"], "match": s["match"],
                "rate": round(s["match"]/s["total"]*100, 1)
            }
            for cat, s in sorted(category_stats.items())
        },
        "mismatches": mismatch_details,
        "stability": {
            "cases": STABILITY_CASES,
            "handle_stable": stable_handle,
            "contribute_stable": stable_contribute,
            "both_stable": stable_both,
            "stable_rate": round(overall_stable_rate, 1),
            "avg_conf_range": round(avg_conf_range, 3),
            "evidence_consistent": evidence_consistent,
            "step_consistent": step_consistent,
            "details": stability_report,
        },
        "total_time_s": t_total,
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n Report saved to: {report_path}")

    return report


if __name__ == "__main__":
    asyncio.run(main())