"""
Test script for target_sgs stability and correctness in mid_exec_detect.
Tests 30 cases specifically designed to probe whether target_sgs aligns
with the domain described in reason text.

Environment variables:
    DASHSCOPE_API_KEY  -- API key for DashScope (required)
    DASHSCOPE_BASE_URL -- Base URL (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    DASHSCOPE_MODEL    -- Model name (default: deepseek-v4-flash-0731)

Usage:
    cd /Users/james/daocloud/code/dac/skill-agent
    DASHSCOPE_API_KEY=sk-xxx python tests/test_target_sgs_stability.py
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_sdk import ModelManager
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from agent.skill_agent import DelegationDetectionResult
from agent.tool_call_utils import invoke_llm_with_tool


API_KEY = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL = os.environ.get("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")


def _build_llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


# ─── 与生产代码一致的 prompt 模板 ───────────────────────────────────────────
PROMPT_TEMPLATE = (
    "你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，"
    "判断是否还需要其他领域的补充数据。\n\n"
    "核心判断逻辑：\n"
    "1）首先分析本层自身执行结果，判断当前结果是否足以完整回答原始问题。\n"
    "2）如果本层结果是空结果（如 'not found'、'查询结果为空'、'0 条记录'、'no records'），"
    "不能因此直接拒绝委派。需要进一步判断：\n"
    "   a) 本层 skill 说明或结果中是否提到了其他可用的技能/数据源/agent？\n"
    "   b) 原始问题中是否包含可以传递给下游的实体信息（如姓名、关键词、ID、自然语言描述）？\n"
    "   c) 下游 agent 是否有可能通过自身数据独立完成查询（即使没有精确的 join_key）？\n"
    "   如果 a/b/c 任一为真，仍应返回 needs_help=true。\n"
    "3）当本层有具体标识符（join_keys）时，synthesized_query 必须包含这些标识符。\n"
    "   当本层没有具体标识符时，synthesized_query 应包含原始问题中的实体信息"
    "   （如姓名、描述、关键词）作为查询线索，下游 agent 可自行完成映射或查询。\n"
    "4）部分成功也要委派：若结果写了 task fail / 无法确认，但正文或 "
    "structured_control 里已有可传递的关联键，且明确缺外域字段，"
    "应 needs_help=true，synthesized_query 必须带上这些关联键。\n"
    "5）outcome=partial 或 reason_code=data_sovereignty_gap 时，一律 needs_help=true。\n"
    "6）只有当本层结果明确表示：原始问题中的实体或概念在自身数据域中确实不存在，"
    "且没有任何其他 agent 可能拥有该数据时，才返回 needs_help=false。\n\n"
    "synthesized_query 书写规则（强制）：\n"
    "- 只写下游 SG 本轮需要交付的子问题：关联键 + 缺失字段；\n"
    "- 当没有关联键时，传递原始问题中的实体信息（姓名、ID、关键词等）作为查询线索；\n"
    "- 禁止复述完整原题；禁止写入其它域目标或整题扩写；\n"
    "- 禁止要求下游去计算本层已有或本层负责的指标；\n"
    "- 下游拿到这句话应能直接执行并结束，无需理解整题其它部分。\n\n"
    "重要约束：\n"
    "- 不要依据 SG 的自描述文案选择目标；最终远程 SG 由后续标准 "
    "capability_check 全量广播（成员能力证据）决定；\n"
    "- 即使下方 SG 名称列表为空，只要存在数据缺口，仍应 needs_help=true；\n"
    "- 当 needs_help=true 时，target_sgs 应填写你认为可补充数据的 SG 名称。\n"
    "  最终远程 SG 由后续标准 capability_check 全量广播决定，此处的 target_sgs 用于辅助性提示。\n\n"
    "注意: 如果已有结果已经能完整回答原始问题，应返回 needs_help=false。\n\n"
    "原始问题（仅供判断缺口，勿整段写入 synthesized_query）：{query}\n\n"
    "本层自身执行结果：\n{own_text}\n\n"
    "已完成委托结果：\n{del_text}\n\n"
    "可委托的 SG 名称列表（仅供参考，非选人依据）：\n{sg_options}\n\n"
    "请调用 detect_delegation_needs 工具来输出结果。"
    "当 needs_help=true 时，reason 字段必须说明具体缺了什么数据、为什么需要补充。"
)


# ─── 10 个 target_sgs 稳定性测试用例 ──────────────────────────────────────
# 每个用例的 expected_target_domain 描述的是 reason 文本中明确提到的数据域
# 测试会验证：target_sgs 是否与 reason 中描述的数据域一致

TEST_CASES = [
    # ═══════════════════════════════════════════════════════════════════════
    # Case 1: reason 中明确提到 "user-agent"，target_sgs 应该包含 user-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 1,
        "desc": "reason明确提到user-agent，target_sgs应包含user-agent",
        "query": "郑十买了哪些东西",
        "own": "[Task#1]: 无法查询用户郑十的订单。订单数据中用户ID是U001~U008格式，不包含姓名。搜索郑十无匹配。建议：需使用user_query技能查询郑十对应的用户ID。",
        "del": "",
        "sg": "- user-agent\n- product-agent\n- order-agent",
        "expected_domain": "user-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 2: reason 中明确提到 "product-agent"，target_sgs 应该包含 product-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 2,
        "desc": "reason明确提到商品数据域，target_sgs应包含product-agent",
        "query": "U001买了哪些商品，这些商品的价格是多少",
        "own": "[Task#1]: U001的订单：ORD-001|已发货|iPhone 15 Pro|U001, ORD-003|已完成|AirPods Pro|U001",
        "del": "",
        "sg": "- product-agent\n- order-agent",
        "expected_domain": "product-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 3: reason 中明确提到 "supplier-agent"，target_sgs 应该包含 supplier-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 3,
        "desc": "reason明确提到supplier-agent，target_sgs应包含supplier-agent",
        "query": "iPhone 15 Pro的供应商是谁，库存还有多少",
        "own": "[Task#1]: iPhone 15 Pro库存：商品ID PROD-001, 库存150, 价格7999。供应商信息：当前skill不包含供应商数据。",
        "del": "",
        "sg": "- supplier-agent\n- inventory-agent\n- product-agent",
        "expected_domain": "supplier-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 4: reason 中明确提到 "user-agent"（用户数据域），target_sgs 应包含 user-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 4,
        "desc": "reason明确提到用户数据域，target_sgs应包含user-agent",
        "query": "最近一周下单的活跃用户有哪些，他们的联系方式是什么",
        "own": "[Task#1]: 活跃用户ID：U001,U003,U005,U008,U012 共23笔订单。用户联系方式：订单数据中不包含。",
        "del": "",
        "sg": "- user-agent\n- order-agent",
        "expected_domain": "user-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 5: reason 中明确提到 "hr-agent"（HR系统），target_sgs 应该包含 hr-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 5,
        "desc": "reason明确提到HR系统，target_sgs应包含hr-agent",
        "query": "张三的考勤记录和薪资情况",
        "own": "[Task#1]: 无法查询张三的考勤。当前order_query仅支持订单数据，不含员工数据。建议：需使用hr_query技能查询HR系统。",
        "del": "",
        "sg": "- hr-agent\n- order-agent",
        "expected_domain": "hr-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 6: reason 中明确提到 "logistics-agent"（物流），target_sgs 应该包含 logistics-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 6,
        "desc": "reason明确提到物流数据域，target_sgs应包含logistics-agent",
        "query": "ORD-001的订单详情、物流状态和预计送达时间",
        "own": "[Task#1]: ORD-001详情：iPhone 15 Pro, 金额7999, 下单时间2024-08-15。物流信息：当前订单数据不含物流跟踪信息。",
        "del": "",
        "sg": "- logistics-agent\n- order-agent\n- product-agent",
        "expected_domain": "logistics-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 7: reason 中明确提到 "support-agent"（客服），target_sgs 应该包含 support-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 7,
        "desc": "reason明确提到客服，target_sgs应包含support-agent",
        "query": "ORD-888为什么被取消了，能恢复吗",
        "own": "[Task#1]: ORD-888状态：已取消，取消原因：风控审核未通过。订单数据中无详细风控记录。关于恢复订单，请联系客服部门处理。",
        "del": "",
        "sg": "- risk-agent\n- support-agent\n- order-agent",
        "expected_domain": "support-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 8: reason 中明确提到 "review-agent"（评价），target_sgs 应该包含 review-agent
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 8,
        "desc": "reason明确提到用户评价，target_sgs应包含review-agent",
        "query": "PROD-001这个商品的完整信息：规格、库存、供应商、用户评价",
        "own": "[Task#1]: PROD-001(iPhone 15 Pro)：库存150, 价格7999。规格和用户评价：当前订单系统不包含商品详细规格参数和用户评价数据。",
        "del": "",
        "sg": "- product-agent\n- review-agent\n- supplier-agent\n- order-agent",
        "expected_domain": "review-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 9: reason 中明确提到多个数据域，target_sgs 应正确反映
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 9,
        "desc": "reason提到多个数据域，target_sgs应包含多个agent",
        "query": "2024年全年用户增长趋势和留存率",
        "own": "[Task#1]: 订单系统可统计2024年有下单行为的用户数：Q1 1200, Q2 1500, Q3 1800, Q4 2100。但注册用户总数、未下单用户、留存率等指标订单数据不包含。",
        "del": "",
        "sg": "- user-agent\n- analytics-agent\n- growth-agent\n- order-agent",
        "expected_domain": "user-agent",
        "expected_needs_help": True,
    },

    # ═══════════════════════════════════════════════════════════════════════
    # Case 10: 不需要委派，验证 target_sgs 应该为空
    # ═══════════════════════════════════════════════════════════════════════
    {
        "id": 10,
        "desc": "无需委派的情况，target_sgs应为空",
        "query": "U001买了哪些商品",
        "own": "[Task#1]: U001购买的商品：1.iPhone 15 Pro(ORD-001) 2.AirPods Pro(ORD-003) 共2条。",
        "del": "",
        "sg": "- product-agent\n- order-agent",
        "expected_domain": None,
        "expected_needs_help": False,
    },

    # ═══════════════════════════════════════════════════════════════════════════
    # 20 个复杂用例 — 多域缺口、歧义场景、已部分委派、跨轮次等
    # ═══════════════════════════════════════════════════════════════════════════

    # ── 多域缺口，明确缺多个 agent ──────────────────────────────────────────
    {
        "id": 11,
        "desc": "同时缺支付和物流两个域",
        "query": "ORD-001的支付状态和物流跟踪信息",
        "own": "[Task#1]: ORD-001订单详情：iPhone 15 Pro, 金额7999, 下单2024-08-15。订单数据不含支付状态和物流跟踪。",
        "del": "",
        "sg": "- payment-agent\n- logistics-agent\n- order-agent",
        "expected_domain": "payment-agent, logistics-agent",
        "expected_needs_help": True,
    },
    {
        "id": 12,
        "desc": "同时缺用户、商品、评价三个域",
        "query": "U005的订单详情、商品规格和用户评价分析",
        "own": "[Task#1]: U005订单：ORD-010 MacBook Pro。订单数据不包含商品规格参数和用户评价反馈。",
        "del": "",
        "sg": "- user-agent\n- product-agent\n- review-agent\n- order-agent",
        "expected_domain": "product-agent, review-agent",
        "expected_needs_help": True,
    },

    # ── 已部分委派，第二轮需要新域 ─────────────────────────────────────────
    {
        "id": 13,
        "desc": "已从user-agent拿到数据，还需物流和支付",
        "query": "郑十的订单ORD-020的物流状态和付款情况",
        "own": "[Task#1]: ORD-020订单：WD Black SN850X 2TB, 金额2999, 状态已发货。物流状态和付款信息：订单数据中不包含。",
        "del": "[user-agent]: 用户郑十对应的用户ID为U008。",
        "sg": "- logistics-agent\n- payment-agent\n- order-agent",
        "expected_domain": "logistics-agent, payment-agent",
        "expected_needs_help": True,
    },
    {
        "id": 14,
        "desc": "已从product-agent拿到数据，还需法律审查",
        "query": "iPhone 15 Pro的规格参数和销售合规性审核",
        "own": "[Task#1]: iPhone 15 Pro规格参数已获取，但合规性审核需要法务部门确认。",
        "del": "[product-agent]: iPhone 15 Pro规格：6.1英寸OLED, A17 Pro芯片, 48MP主摄, 钛金属边框。",
        "sg": "- legal-agent\n- compliance-agent\n- order-agent",
        "expected_domain": "legal-agent",
        "expected_needs_help": True,
    },
    {
        "id": 15,
        "desc": "已从supplier-agent拿到数据，还需financial-agent",
        "query": "PROD-001的供应商信息和采购成本分析",
        "own": "[Task#1]: PROD-001 iPhone 15 Pro。供应商信息已获取，但采购成本分析需要财务数据。",
        "del": "[supplier-agent]: PROD-001供应商：富士康（深圳），合同编号 SUP-2024-001，批次采购价7500元。",
        "sg": "- finance-agent\n- analytics-agent\n- order-agent",
        "expected_domain": "finance-agent",
        "expected_needs_help": True,
    },

    # ── 歧义场景：SG 列表中有误导性 agent ──────────────────────────────────
    {
        "id": 16,
        "desc": "SG列表含多个无关agent，应只选缺口的那个",
        "query": "2024年双11大促期间退货率最高的商品品类",
        "own": "[Task#1]: 双11期间订单数据：电子产品退货率12%, 服装退货率28%, 家居退货率8%。但退货原因分析需要客服/售后数据。",
        "del": "",
        "sg": "- support-agent\n- music-agent\n- game-agent\n- weather-agent\n- order-agent",
        "expected_domain": "support-agent",
        "expected_needs_help": True,
    },
    {
        "id": 17,
        "desc": "SG列表全是无关agent，要靠推理选正确域",
        "query": "张三的社保缴纳记录和公积金余额",
        "own": "[Task#1]: 无法查询张三的社保数据。当前order_query仅支持订单查询，不包含员工社保/公积金信息。",
        "del": "",
        "sg": "- weather-agent\n- news-agent\n- music-agent\n- hr-agent\n- order-agent",
        "expected_domain": "hr-agent",
        "expected_needs_help": True,
    },
    {
        "id": 18,
        "desc": "缺口明显但SG列表无精确匹配，需推理",
        "query": "审查一下UserService.java中是否存在并发安全问题",
        "own": "[Task#1]: 无法审查UserService.java。当前order_query仅支持订单数据查询，无代码仓库访问权限，不具备代码审查能力。",
        "del": "",
        "sg": "- code-analyzer\n- security-scanner\n- order-agent",
        "expected_domain": "code-analyzer",
        "expected_needs_help": True,
    },

    # ── 多轮委派后的收尾场景 ───────────────────────────────────────────────
    {
        "id": 19,
        "desc": "两轮后只剩最后一个缺口",
        "query": "郑十的订单总金额、用户等级和推荐商品",
        "own": "[Task#1]: U008(郑十)订单：ORD-014 Anker充电器129元, ORD-020 WD Black 2999元, 合计3128元。",
        "del": "[user-agent]: 郑十(U008)用户等级：黄金会员，注册2022-03-15。\n[product-agent]: 暂无推荐数据。",
        "sg": "- recommendation-agent\n- order-agent",
        "expected_domain": "recommendation-agent",
        "expected_needs_help": True,
    },
    {
        "id": 20,
        "desc": "三轮后所有数据已完整，应不再委派",
        "query": "PROD-001的完整信息：规格、库存、供应商、评价、合规状态",
        "own": "[Task#1]: PROD-001(iPhone 15 Pro)：库存150, 价格7999。",
        "del": "[product-agent]: iPhone 15 Pro规格：6.1英寸OLED, A17 Pro, 48MP, 钛金属。\n[review-agent]: 用户评分4.8/5, 好评率92%。\n[supplier-agent]: 富士康深圳, 合同SUP-2024-001。\n[legal-agent]: 国内销售合规，已通过3C认证。",
        "sg": "- product-agent\n- review-agent\n- supplier-agent\n- legal-agent\n- order-agent",
        "expected_domain": None,
        "expected_needs_help": False,
    },

    # ── 模糊缺口：数据域不明确，需合理推断 ─────────────────────────────────
    {
        "id": 21,
        "desc": "缺口模糊，SG列表也不精确，需推理最可能的域",
        "query": "分析一下为什么最近用户流失率上升了",
        "own": "[Task#1]: 最近30天订单数据：活跃用户数从1200降至950，订单量下降21%。但流失原因分析需要用户行为数据和反馈。",
        "del": "",
        "sg": "- user-agent\n- analytics-agent\n- feedback-agent\n- order-agent",
        "expected_domain": "user-agent, analytics-agent",
        "expected_needs_help": True,
    },
    {
        "id": 22,
        "desc": "缺口需要跨域关联，SG列表给出全量候选",
        "query": "对比一下Q2和Q3的营销活动ROI",
        "own": "[Task#1]: 订单数据：Q2营销活动期间订单量+15% (GMV 234万), Q3营销活动期间订单量+8% (GMV 180万)。但营销成本数据和活动详情不在订单系统中。",
        "del": "",
        "sg": "- marketing-agent\n- finance-agent\n- analytics-agent\n- crm-agent\n- order-agent",
        "expected_domain": "marketing-agent, finance-agent",
        "expected_needs_help": True,
    },

    # ── 部分成功但关键字段缺失 ─────────────────────────────────────────────
    {
        "id": 23,
        "desc": "本层有成果但缺关键字段，需明确委派",
        "query": "ORD-999的退款金额、退款时间和退款原因",
        "own": "[Task#1]: outcome=partial ORD-999退款记录：金额599元，退款时间2024-08-20。退款原因：订单数据中未记录。reason_code=data_sovereignty_gap",
        "del": "",
        "sg": "- support-agent\n- payment-agent\n- order-agent",
        "expected_domain": "support-agent",
        "expected_needs_help": True,
    },
    {
        "id": 24,
        "desc": "outcome=partial + 明确缺外域字段",
        "query": "张三的部门、职级和2024年绩效评分",
        "own": "[Task#1]: outcome=partial 张三工号E2018，部门：技术部。职级和绩效评分：当前skill不包含人事数据。reason_code=data_sovereignty_gap",
        "del": "",
        "sg": "- hr-agent\n- performance-agent\n- order-agent",
        "expected_domain": "hr-agent",
        "expected_needs_help": True,
    },

    # ── 空结果但实体信息可传递 ─────────────────────────────────────────────
    {
        "id": 25,
        "desc": "空结果但实体是邮箱，需要user-agent解析",
        "query": "查找zhangsan@example.com的所有订单和联系方式",
        "own": "[Task#1]: 查询zhangsan@example.com无匹配。订单数据中客户字段为U001~U020格式，不含邮箱。搜索邮箱无结果。",
        "del": "",
        "sg": "- user-agent\n- order-agent",
        "expected_domain": "user-agent",
        "expected_needs_help": True,
    },
    {
        "id": 26,
        "desc": "空结果但实体是设备序列号，需要device-agent或maintenance-agent",
        "query": "设备SN-2024-XJ-0881的维修记录和保修状态",
        "own": "[Task#1]: 查询SN-2024-XJ-0881无匹配。订单系统仅含订单数据，不包含设备维修和保修信息。",
        "del": "",
        "sg": "- iot-agent\n- device-agent\n- maintenance-agent\n- order-agent",
        "expected_domain": "device-agent",  # LLM 应从 SG 列表中合理选择一个
        "expected_needs_help": True,
    },

    # ── 需要数据聚合/分析 ──────────────────────────────────────────────────
    {
        "id": 27,
        "desc": "本层有原始数据，但需要分析agent做聚合",
        "query": "生成2024年Q1-Q4各品类销售趋势的可视化报告",
        "own": "[Task#1]: 已获取Q1-Q4各品类原始销售数据共4500条记录。但未进行趋势分析和报告生成，当前skill不具备数据可视化和报告生成能力。",
        "del": "",
        "sg": "- analytics-agent\n- report-agent\n- visualization-agent\n- order-agent",
        "expected_domain": "analytics-agent, report-agent",
        "expected_needs_help": True,
    },
    {
        "id": 28,
        "desc": "本层有明细数据，需要DBA做性能分析",
        "query": "分析orders表近一周慢查询趋势并给出索引优化建议",
        "own": "[Task#1]: 慢查询日志已获取，近7天共23条慢查询。EXPLAIN结果：type=ALL, rows=523401。未进行根因分析和索引优化建议。",
        "del": "",
        "sg": "- dba-agent\n- performance-agent\n- monitoring-agent\n- order-agent",
        "expected_domain": "dba-agent",
        "expected_needs_help": True,
    },

    # ── 跨系统数据关联 ─────────────────────────────────────────────────────
    {
        "id": 29,
        "desc": "需要CRM和ERP两个系统数据关联",
        "query": "大客户U008的信用额度、历史订单和应收账款",
        "own": "[Task#1]: U008历史订单：共12笔订单，总金额45,600元。信用额度和应收账款：订单数据不包含，可能存在于CRM或ERP系统。",
        "del": "",
        "sg": "- crm-agent\n- erp-agent\n- finance-agent\n- order-agent",
        "expected_domain": "crm-agent, erp-agent",
        "expected_needs_help": True,
    },
    {
        "id": 30,
        "desc": "需要安全agent和合规agent联合审查",
        "query": "新上线的支付接口是否满足PCI-DSS安全标准",
        "own": "[Task#1]: 支付接口技术文档已获取：使用HTTPS+JWT, 接入第三方支付网关。但PCI-DSS合规审查和安全评估不在订单数据域内，需要专业安全审计。",
        "del": "",
        "sg": "- security-agent\n- compliance-agent\n- audit-agent\n- order-agent",
        "expected_domain": "security-agent, compliance-agent",
        "expected_needs_help": True,
    },
]


# ─── 评估函数 ──────────────────────────────────────────────────────────────

def extract_agents_from_reason(reason: str) -> set[str]:
    """从 reason 文本中提取 xxx-agent 模式（仅限 ASCII 单词字符，避免匹配中文）。"""
    if not reason:
        return set()
    return set(re.findall(r'[a-zA-Z0-9-]+-agent', reason, re.IGNORECASE))


def check_target_sgs_consistency(
    target_sgs: list[str],
    reason: str,
    expected_domain: str | None,
    needs_help: bool,
) -> dict:
    """检查 target_sgs 与 reason 的一致性。"""
    issues = []
    target_set = set(s.lower() for s in (target_sgs or []))

    # 1. 如果不需要委派，target_sgs 应该为空
    if not needs_help:
        if target_sgs:
            issues.append(f"No delegation needed but target_sgs non-empty: {target_sgs}")
        return {
            "consistent": len(issues) == 0,
            "issues": issues,
            "score": 1.0 if not target_sgs else 0.0,
            "extracted_from_reason": [],
        }

    # 2. 需要委派：检查 target_sgs 是否为空
    if not target_sgs:
        issues.append("Delegation needed but target_sgs is empty")

    # 3. 从 reason 中提取提到的 agent 名称
    reason_agents = extract_agents_from_reason(reason)
    reason_agents_lower = set(a.lower() for a in reason_agents)

    # 4. 检查 target_sgs 与 reason 中提到的 agent 是否有交集
    #    注意：reason 可能提到已完成的 agent（来自 del 文本），
    #    当 expected_domain 已匹配时此项不作为硬性判断依据。
    if reason_agents_lower and target_set:
        overlap = reason_agents_lower & target_set
        if not overlap:
            issues.append(
                f"reason_agents={reason_agents_lower}, target_sgs={target_set}, no overlap"
            )
        elif overlap != reason_agents_lower:
            missing = reason_agents_lower - target_set
            extra = target_set - reason_agents_lower
            if missing:
                issues.append(f"reason mentions but target_sgs missing: {missing}")
            if extra:
                issues.append(f"target_sgs extra but reason didn't mention: {extra}")

    # 5. 如果 expected_domain 存在，检查 target_sgs 是否包含它
    #    支持逗号分隔的多值，如 "payment-agent, logistics-agent"
    expected_ok = True
    if expected_domain:
        expected_list = [d.strip().lower() for d in expected_domain.split(",")]
        for exp in expected_list:
            if exp not in target_set:
                issues.append(f"expected {exp} but target_sgs={target_set}")
                expected_ok = False

    # 6. 计算得分
    #    优先以 expected_domain 为准；如果 expected_domain 匹配，则得满分。
    score = 1.0
    if not target_sgs:
        score = 0.0
    elif expected_domain:
        expected_list = [d.strip().lower() for d in expected_domain.split(",")]
        matches = sum(1 for exp in expected_list if exp in target_set)
        score = matches / len(expected_list) if expected_list else 0.7
    elif reason_agents_lower and target_set:
        overlap = reason_agents_lower & target_set
        score = len(overlap) / max(len(reason_agents_lower), len(target_set))
    else:
        score = 0.7

    # 7. 一致性判定：expected_domain 匹配即视为一致
    #    reason_agents 的差异仅作为信息提示，不影响最终判定
    consistent = expected_ok if expected_domain else (len(issues) == 0)

    return {
        "consistent": consistent,
        "issues": issues,
        "score": score,
        "extracted_from_reason": sorted(reason_agents_lower),
    }


# ─── 主流程 ────────────────────────────────────────────────────────────────

async def call_llm(llm, prompt: str) -> dict:
    detect_tool = StructuredTool(
        name="detect_delegation_needs",
        description=(
            "检测是否仍有数据缺口需要跨 SG 补充；输出 synthesized_query 与原因。"
            "当 needs_help=true 时应填写 target_sgs，最终选人由 capability_check 完成。"
        ),
        args_schema=DelegationDetectionResult,
        func=None,
        coroutine=None,
    )
    data = await invoke_llm_with_tool(
        llm=llm,
        tool=detect_tool,
        messages=[HumanMessage(content=prompt)],
        metadata={
            "run_id": "test-target-sgs",
            "trace_id": "d" * 32,
            "user_id": "test-target-sgs",
        },
        tool_choice="detect_delegation_needs",
        span_name="test-target-sgs-stability",
    )
    if data is None:
        raise RuntimeError("LLM did not call detect_delegation_needs tool")
    return data


async def main():
    if not API_KEY:
        print("ERROR: DASHSCOPE_API_KEY environment variable is required.")
        print("Usage: DASHSCOPE_API_KEY=sk-xxx python tests/test_target_sgs_stability.py")
        sys.exit(1)

    print("=" * 80)
    print(f"TARGET_SGS STABILITY TEST - {len(TEST_CASES)} Cases | Model: {MODEL}")
    print("=" * 80)

    llm = _build_llm()
    results = []
    total_score = 0.0
    passed = 0
    failed = 0

    for tc in TEST_CASES:
        prompt = PROMPT_TEMPLATE.format(
            query=tc["query"],
            own_text=tc["own"],
            del_text=tc.get("del") or "(none)",
            sg_options=tc.get("sg") or "(none)",
        )

        print(f"\n{'─' * 80}")
        print(f"[#{tc['id']}] {tc['desc']}")
        print(f"  Query: {tc['query']}")
        print(f"  Expected domain: {tc['expected_domain']}")

        try:
            r = await call_llm(llm, prompt)
        except Exception as e:
            print(f"  ERROR: {e}")
            failed += 1
            results.append({
                "id": tc["id"],
                "desc": tc["desc"],
                "error": str(e),
            })
            continue

        needs_help = r.get("needs_help", False)
        target_sgs = list(r.get("target_sgs") or [])
        reason = r.get("reason", "")
        synthesized_query = r.get("synthesized_query", "")

        print(f"  needs_help: {needs_help} (expected: {tc['expected_needs_help']})")
        print(f"  target_sgs: {target_sgs}")
        print(f"  reason: {reason[:200]}")
        if synthesized_query:
            print(f"  synthesized_query: {synthesized_query[:200]}")

        needs_help_ok = needs_help == tc["expected_needs_help"]
        if not needs_help_ok:
            print(f"  WARNING: needs_help mismatch: expected={tc['expected_needs_help']}, actual={needs_help}")

        check = check_target_sgs_consistency(
            target_sgs=target_sgs,
            reason=reason,
            expected_domain=tc["expected_domain"],
            needs_help=needs_help,
        )
        total_score += check["score"]

        print(f"  --- target_sgs consistency ---")
        print(f"  Score: {check['score']:.2f}")
        print(f"  Agents in reason: {check['extracted_from_reason']}")
        if check["issues"]:
            for issue in check["issues"]:
                print(f"  ISSUE: {issue}")
        else:
            print(f"  OK: consistent")

        if check["consistent"] and needs_help_ok:
            passed += 1
        else:
            failed += 1

        results.append({
            "id": tc["id"],
            "desc": tc["desc"],
            "query": tc["query"],
            "expected_domain": tc["expected_domain"],
            "expected_needs_help": tc["expected_needs_help"],
            "actual_needs_help": needs_help,
            "needs_help_ok": needs_help_ok,
            "target_sgs": target_sgs,
            "reason": reason,
            "synthesized_query": synthesized_query,
            "check": check,
        })

    print(f"\n{'=' * 80}")
    print(f"SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total: {len(TEST_CASES)} | Passed: {passed} | Failed: {failed}")
    avg_score = total_score / len(TEST_CASES) if TEST_CASES else 0
    print(f"Average target_sgs consistency score: {avg_score:.2f}")

    empty_target_sgs = sum(1 for r in results if r.get("check") and not r["target_sgs"])
    mismatch_target_sgs = sum(
        1 for r in results
        if r.get("check") and r["check"].get("issues") and "expected" in str(r["check"]["issues"])
    )
    print(f"\nProblem breakdown:")
    print(f"  target_sgs empty: {empty_target_sgs}/{len(TEST_CASES)}")
    print(f"  target_sgs mismatch: {mismatch_target_sgs}/{len(TEST_CASES)}")

    print(f"\n{'─' * 80}")
    print(f"DETAILED ANALYSIS")
    print(f"{'─' * 80}")
    for r in results:
        if r.get("check"):
            c = r["check"]
            status = "OK" if c["consistent"] else "ISSUE"
            print(f"\n[#{r['id']}] {status} | {r['desc']}")
            print(f"  target_sgs={r['target_sgs']}")
            print(f"  reason_agents={c['extracted_from_reason']}")
            print(f"  score={c['score']:.2f}")
            if c["issues"]:
                for issue in c["issues"]:
                    print(f"  -> {issue}")

    out = os.path.join(os.path.dirname(__file__), "target_sgs_stability_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to: {out}")


if __name__ == "__main__":
    asyncio.run(main())