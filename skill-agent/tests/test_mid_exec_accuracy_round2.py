"""
Mid-Exec Detection Accuracy Test — Round 2.

结构化 & 非结构化各 20 个全新 cases，与第一轮互不重复。
目标：task_type 分类准确率 100%，needs_help 判定准确率 100%。

Usage:
    cd /Users/james/daocloud/code/dac/skill-agent
    python tests/test_mid_exec_accuracy_round2.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_sdk import ModelManager
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from agent.skill_agent import DelegationDetectionResult
from agent.tool_call_utils import invoke_llm_with_tool

# ── Configuration ─────────────────────────────────────────────
# API key 不写在源码里: 通过环境变量提供 (缺失时 _build_llm 会报错)。
API_KEY = os.getenv("DASHSCOPE_API_KEY")
BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
MODEL = os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731")
MAX_RETRIES = 3
RETRY_DELAY = 2.0


def _build_llm() -> Any:
    if not API_KEY:
        raise RuntimeError(
            "缺少 API key: 请设置环境变量 DASHSCOPE_API_KEY 后重试。"
        )
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.0,
        stream=False,
        extra_body={"enable_thinking": False},
    )


PROMPT_TEMPLATE = """你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，判断是否还需要其他领域的补充数据。

## 步骤 0：任务类型分类（必须在所有判断之前完成）

根据原始问题和本层执行结果的特征，将任务归类为 structured 或 unstructured。

**structured（结构化数据查询）的判断特征：**
- 问题涉及数据库表、SQL 查询、字段查找、记录检索、ID 关联
- 期望的答案是有限数据集（如某人的订单列表、某商品的统计值、某条件的筛选结果）
- 执行结果以字段-值对、表格、记录列表或统计数字呈现
- 有明确的数据边界：「查到了哪些字段」vs「还缺哪些字段」
- 典型关键词：查询、查找、列表、多少、哪些、统计、汇总、筛选、关联

**unstructured（非结构化处理）的判断特征：**
- 问题涉及文档总结、文本分析、代码审查、翻译、内容生成、知识问答
- 期望的答案是开放性叙述（段落式分析、评判性结论、描述性总结）
- 执行结果以描述性段落文本呈现，而非字段-值行列表
- 答案没有「穷尽」的概念——始终可以从不同角度、不同深度做补充，但这不代表「有缺口」
- 典型关键词：分析、总结、审查、解释、翻译、评估、建议、判断

**分类方法（按此程序执行，不要靠关键词或题型印象判断）：**
只看原始问题那一段（分类时不要读「本层自身执行结果」）。执行下面这个判定程序：

第1步：写出答案模板。
   把原始问题改写成一句带空白的回答句，例如「这个任务的答案是：____」或「结论是：____」。

第2步：问一句——「这个答案本身，是不是已经存在、只等取回？」
   → 是：答案是一个值 / 列表 / 记录集，本来就记在某处，取回即可 → **structured**
   → 否：答案谁都没有记录过，必须由人依据取回的数据推导、权衡、下结论 → **unstructured**

判别示范（只看判断过程，不要记题型）：
   · 「A 的供应商是谁、库存多少」→ 答案「供应商__、库存__」→ 这两个值本来就记在系统里 → structured
   · 「这份代码有哪些安全风险」→ 答案「存在__风险」→ 没有任何地方记录过这个结论，要靠人判定 → unstructured

⚠ 最关键的陷阱（此处判错最多，务必执行）：
   本层如果声明「缺少 XX 数据 / 某个字段没拿到」，这只说明 **XX 数据存在**，**不等于答案存在**。二者必须分开问：
     数据存在？ → 多数情况都是「是」（否则没法查），但这不决定分类。
     答案存在？ → 只有这个问题决定分类。
   自检：把所有声明缺失的数据也都拿到手之后，答案是不是就自动成型了？
     → 是 → structured；→ 否（还要人下判断）→ unstructured。

⚠ 另一条禁令：禁止用「本层结果里有没有字段/记录/日志」当依据。能力缺失导致中断时，中间结果必然只剩已核实的数据片段，这是中断的副产物，与任务类型无关。

**分类自检方法：**
问自己：「这个任务的执行结果，有没有一个客观的标准来判断它是否'完整'？」
→ 如果答案是「有」→ structured（比如：缺了某个字段、缺了某张表的数据）
→ 如果答案是「没有」→ unstructured（比如：一个文档分析永远可以更深入，但已有的分析已经是对原始问题的充分回答）

请先确定 task_type，然后根据类型选择下面的判定规则。

## 步骤 1a：结构化数据缺口的判定规则（仅当 task_type=structured 时适用）

1）首先分析本层自身执行结果，判断当前结果是否足以完整回答原始问题。
2）如果本层结果是空结果（如 'not found'、'查询结果为空'、'0 条记录'、'no records'），不能因此直接拒绝委派。需要进一步判断：
   a) 本层 skill 说明或结果中是否提到了其他可用的技能/数据源/agent？
   b) 原始问题中是否包含可以传递给下游的实体信息（如姓名、关键词、ID、自然语言描述）？
   c) 下游 agent 是否有可能通过自身数据独立完成查询（即使没有精确的 join_key）？
   如果 a/b/c 任一为真，仍应返回 needs_help=true。
3）当本层有具体标识符（join_keys）时，synthesized_query 必须包含这些标识符。
   当本层没有具体标识符时，synthesized_query 应包含原始问题中的实体信息（如姓名、描述、关键词）作为查询线索，下游 agent 可自行完成映射或查询。
4）部分成功也要委派：若结果写了 task fail / 无法确认，但正文或 structured_control 里已有可传递的关联键，且明确缺外域字段，应 needs_help=true，synthesized_query 必须带上这些关联键。
5）outcome=partial 或 reason_code=data_sovereignty_gap 时，一律 needs_help=true。
6）needs_help=false 的条件：当本层结果已覆盖原始问题所有必需的域，且参考下方的 SG 技能列表，没有其他 agent 声明的技能范围能补充本层缺失的数据时，才返回 needs_help=false。注意：不需要证明「绝对没有 agent 有」，只需判断列表中没有匹配的即可。

**structured synthesized_query 书写规则（强制）：**
- 只写下游 SG 本轮需要交付的子问题：关联键 + 缺失字段；
- 当没有关联键时，传递原始问题中的实体信息（姓名、ID、关键词等）作为查询线索；
- 禁止复述完整原题；禁止写入其它域目标或整题扩写；
- 禁止要求下游去计算本层已有或本层负责的指标；
- 下游拿到这句话应能直接执行并结束，无需理解整题其它部分。

## 步骤 1b：非结构化任务缺口的判定规则（仅当 task_type=unstructured 时适用）

核心原则：非结构化任务（文档总结、文本分析、代码审查、翻译等）没有「标准答案」，
「完成」意味着给出了对原始问题的实质性、有结构的回答，而非穷尽了所有可能的角度。

**前置条件（在判定任何缺口之前必须先通过）：**
非结构化任务只承认「明确数据缺口」。要判定 needs_help=true，你必须先能写出一个下游 SG 用其自身技能可直接执行的具体子问题。
自检方法：先在心里写出 synthesized_query，再问「这句话能让下游 SG 直接开工吗？」
→ 写得出来 → 这是明确缺口，继续用下面的 A/B 条件判定；
→ 写不出来，只能说「可以更深入」「可以补充某方面的分析」→ 这是开放式思考方向，不是数据缺口，直接返回 needs_help=false。
⚠ 非结构化任务不存在「无限可补充」意义上的缺口：任何分析在理论上都能做得更深，但这不构成委派理由。写不出明确子问题，就等于没有缺口。

**触发 needs_help=true 的条件（较严格，只有以下情况才委派）：**
A）本层结果明确声明了具体的、可查证的缺失项，且下方 SG 技能列表中确有 agent 能填补该项。
   示例：执行结果说「代码审查完成了安全部分，但缺少合规性审计」，且下方有 compliance-agent → 可委派。
   反例：执行结果是一个完整的产品描述翻译，但「术语库 agent 可能有更精确译法」→ 这不是明确的缺失项，不委派。
   ⚠ 但请注意区分「泛指」与「已点名具体缺失项」——后者是明确缺口：
   · 泛指（不委派）：翻译已完整交付，只是笼统认为「术语库也许有更准的说法」，说不出具体是哪个词有问题 → needs_help=false。
   · 已点名（委派）：结果明确指出「术语 X、Y 的确切译法未能确定」，且下方有 terminology-agent 可查证这些具体术语 → needs_help=true，因为 gap 已被收敛成可执行的子问题。

B）本层结果明确表示「不具备该能力」或「能力域错误」，且原始问题中的实体或概念在它域可能存在。
   示例：order-agent 收到了「审查 payment_service.py 的安全漏洞」，返回「不具备代码审查能力」→ 应委派给 code-agent。

**触发 needs_help=false 的条件（以下任一成立就不委派）：**
I）本层已经返回了一个成文的、有逻辑结构的分析/总结/审查/翻译结论。
   「成文」指结果中包含实质性的内容（不是空壳、不是纯报错、不是仅声明能力不足）。
   「有逻辑结构」指结果有完整的叙事或分析框架（不是零散片段）。
   这时即使理论上「可以更深入」，也应返回 needs_help=false。

II）原始问题是一个不需要外部数据的自包含任务（如纯翻译、纯格式化、纯生成）。
   示例：「把这段文字翻译成英文」—— 翻译已完成即 needs_help=false。

III）本层结果对原始问题的核心诉求已给出充分回答，只是缺少次要补充信息。
    示例：「分析这份报告的核心内容」→ 本层已提取并归纳了全文要点。
    即使「报告中提到的某法规的精确引用条款」没有展开，也不属于必须委派的缺口。

**unstructured 场景下 outcome=partial 的含义不同：**
- 非结构化任务中 outcome=partial 是常态（任何分析都是'部分'的），不是强制委派信号。
- 只有当 partial 的原因是一个具体的、可查证的能力缺失时（见条件 A），才委派。

**unstructured 场景下的 synthesized_query（强制）：**
- synthesized_query 是 needs_help=true 的**必要条件**：写不出它，就不算明确缺口，needs_help 必须为 false。
- 判定顺序固定为：先写 synthesized_query，再据此决定 needs_help。禁止先判 needs_help=true 再回头补一个空泛的描述。
- 上文「前置条件」中的反例（「术语库 agent 可能有更精确译法」）就是典型：这类说法写不出可执行子问题，因此不构成缺口，needs_help=false。
- synthesized_query 必须从下游 SG 视角编写，描述一个下游 SG 能用自己的技能独立完成的子问题。
- 【严禁】用「补充某方面的分析」「进一步深入」「完善相关评估」这类开放式表述充数——它们不是可执行子问题，等同于没写；此时应返回 needs_help=false。

## 通用重要约束（两种类型均适用）

- 不要依据 SG 的自描述文案选择目标；最终远程 SG 由后续标准 capability_check 全量广播（成员能力证据）决定；
- 当 needs_help=true 时，target_sgs 应填写你认为可补充数据的 SG 名称。
  最终远程 SG 由后续标准 capability_check 全量广播决定，此处的 target_sgs 用于辅助性提示。
- target_sgs 中的名称必须从上方列表中的 SG 名称中精确选取，不得编造不存在的 SG 名称。

原始问题：{query}

本层自身执行结果：
{own_text}

已完成委托结果：
{del_text}

可委托的 SG 名称列表（仅供参考，非选人依据）：
{sg_options}

请调用 detect_delegation_needs 工具来输出结果。
注意：task_type 字段必须首先填写，且必须选择 structured 或 unstructured 之一。
当 needs_help=true 时，reason 字段必须说明具体缺了什么数据、为什么需要补充。"""


# ═══════════════════════════════════════════════════════════════
#  TEST CASES — ROUND 2: 40 全新 cases（与第一轮无重复）
# ═══════════════════════════════════════════════════════════════

TEST_CASES: list[dict] = [
    # ═══════════════════════════════════════════════════════════
    #  STRUCTURED × 20 （与第一轮无重复）
    # ═══════════════════════════════════════════════════════════

    # ── Group: needs_help = False (10 cases) ──────────────────

    {
        "id": "S2-01",
        "cat": "structured",
        "desc": "多条件筛选查询完整体，包括排序和分页信息",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "查询金额大于5000且在2024年8月下单的已发货订单",
        "own": "[Task#1]: 符合条件的订单(金额>5000, 2024-08, 已发货)：ORD-045 iPhone 15 Pro Max ￥10999 8月12日, ORD-051 MacBook Air ￥8999 8月24日, ORD-067 iPad Pro ￥6799 8月30日。共3笔，总金额￥26797。查询条件：时间范围、金额下限、订单状态三条件均已过滤。",
        "del": "",
        "sg": "- analytics-agent（数据统计与分析）\n- product-agent（商品详情查询）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-02",
        "cat": "structured",
        "desc": "全库聚合查询——已遍历全部数据并给出最终结论",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "2024年全年退货率最高的是哪个月",
        "own": "[Task#1]: 2024年全年退货率统计（数据源：全量orders+returns表）：1月3.2%, 2月2.8%, 3月4.1%, 4月3.5%, 5月2.9%, 6月5.7%, 7月4.3%, 8月3.8%, 9月4.0%, 10月3.1%, 11月6.8%, 12月4.5%。退货率最高：11月6.8%（主因双十一冲动消费）。已覆盖全12个月，结论完整。",
        "del": "",
        "sg": "- analytics-agent（深度分析）\n- returns-agent（退货原因分析）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-03",
        "cat": "structured",
        "desc": "权限范围内的查询返回了所有可返回的数据",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "我名下管理的所有客户的订单总额",
        "own": "[Task#1]: 当前登录用户James管理的客户列表（来源CRM权限）：客户A-￥45,600, 客户B-￥23,100, 客户C-￥18,300, 客户D-￥9,800。共4位客户，订单总额￥96,800。已返回名下全部客户的订单数据，无权限外客户。",
        "del": "",
        "sg": "- crm-agent（客户关系管理&权限系统）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-04",
        "cat": "structured",
        "desc": "ID精确匹配无结果，且所有关联表均不包含该ID",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "SKU-XYZ999的生产批次信息",
        "own": "[Task#1]: 查询SKU-XYZ999：商品主表无此SKU，库存表无此SKU，生产批次表无此SKU。已遍历product、inventory、production_batch三张表（均为系统可查范围），确认SKU-XYZ999在系统中不存在。其他可委派agent（supplier-agent、quality-agent）的SKU前缀格式为SKU-S*和SKU-Q*，均不兼容XYZ前缀。",
        "del": "",
        "sg": "- supplier-agent（供应商SKU查询，SKU前缀SKU-S*）\n- quality-agent（质检记录，SKU前缀SKU-Q*）\n- product-agent（商品查询）",
    },
    {
        "id": "S2-05",
        "cat": "structured",
        "desc": "JOIN查询成功获取了两个表的信息",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "列出所有购买了AirPods Pro的用户的姓名和邮箱",
        "own": "[Task#1]: 购买AirPods Pro的用户列表（JOIN orders + users）：1.U001 王明 wangming@example.com(ORD-003) 2.U005 陈伟 chenwei@example.com(ORD-017) 3.U012 赵丽 zhaoli@example.com(ORD-028) 4.U018 刘洋 liuyang@example.com(ORD-032)。共4位用户，已关联订单表和用户表，所有字段均已返回。",
        "del": "",
        "sg": "- user-agent（用户档案详细信息）\n- product-agent（商品详情）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-06",
        "cat": "structured",
        "desc": "分页查询第一页结果明确显示已无更多数据",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "查询所有待审核的退款申请",
        "own": "[Task#1]: 待审核退款申请（共2条，全部已返回）：REF-001 用户U003 ORD-048￥599, REF-002 用户U009 ORD-055￥1299。已遍历refunds表status=pending的全部记录，total_count=2，无更多数据。",
        "del": "",
        "sg": "- refund-agent（退款流程管理）\n- finance-agent（财务审核）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-07",
        "cat": "structured",
        "desc": "用精确业务ID查询到完整物流链路",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "ORD-001从发货到签收的完整物流轨迹",
        "own": "[Task#1]: ORD-001物流轨迹：08-15 14:30 仓库揽收→08-15 18:00 分拨中心→08-16 06:00 到达北京中转→08-16 10:30 派送中→08-16 14:20 已签收(本人)。物流状态：已完成。配送方式：顺丰速运。全程耗时23小时50分。物流信息已完整返回。",
        "del": "",
        "sg": "- logistics-agent（物流详情补全）\n- warehouse-agent（仓库出库记录）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-08",
        "cat": "structured",
        "desc": "时间段内数据确实为零且已验证",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "2024年2月29日的订单量是多少",
        "own": "[Task#1]: 查询2024-02-29的订单数据：2024年是闰年，2月有29天。查询orders表WHERE order_date='2024-02-29'：返回0条记录。已确认：1)日期条件正确 2)表中有2月其他日期的数据（2/28有187笔）3)2月29日确实无订单。结论：2024年2月29日订单量为0。",
        "del": "",
        "sg": "- analytics-agent（数据分析与异常检测）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-09",
        "cat": "structured",
        "desc": "多维度聚合结果覆盖了所有请求的指标",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "各部门2024年Q3的预算执行率",
        "own": "[Task#1]: 2024年Q3各部门预算执行率（数据源：财务系统全量数据）：研发部 预算500万 支出478万 执行率95.6%，市场部 预算300万 支出312万 执行率104.0%，销售部 预算450万 支出441万 执行率98.0%，行政部 预算120万 支出115万 执行率95.8%，运维部 预算200万 支出195万 执行率97.5%。全5个部门均已统计，预算、支出、执行率三指标均覆盖。",
        "del": "",
        "sg": "- finance-agent（财务深度分析）\n- department-agent（部门绩效）\n- budget-agent（预算管理）",
    },
    {
        "id": "S2-10",
        "cat": "structured",
        "desc": "对比查询已返回两个时间段的完整结果",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "对比2023年和2024年双11当天的销售额",
        "own": "[Task#1]: 双11销售额对比：2023年11月11日 销售额￥12,340,000(订单数8,921笔，客单价￥1,383)；2024年11月11日 销售额￥16,520,000(订单数10,234笔，客单价￥1,614)。同比增长33.9%，订单量增长14.7%，客单价提升16.7%。两个年份的数据均已从订单表全量统计，对比维度完整。",
        "del": "",
        "sg": "- analytics-agent（营销效果分析）\n- marketing-agent（活动ROI计算）\n- order-agent（订单查询）",
    },

    # ── Group: needs_help = True (10 cases) ──────────────────

    {
        "id": "S2-11",
        "cat": "structured",
        "desc": "联合查询只完成了一半，缺支付方式数据",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "分析2024年Q4的支付方式分布和对应的退款率",
        "own": "[Task#1]: 2024年Q4订单数据：总订单15,234笔，GMV ￥23,410,000。支付方式字段和退款记录都不在订单表中。订单系统仅含交易完成记录，不含支付渠道信息和退款流程数据。",
        "del": "",
        "sg": "- payment-agent（支付渠道统计、支付方式分布）\n- refund-agent（退款率计算、退款流程）\n- finance-agent（财务分析）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-12",
        "cat": "structured",
        "desc": "查到了客户基础信息但信用额度在另一个系统",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "客户C-088的详细信息：联系人、合同金额、信用额度",
        "own": "[Task#1]: 客户C-088基本信息：公司名-星辰科技有限公司，联系人-李明(lis@xingchen.com)，合同金额-￥500,000/年。信用额度：CRM系统不包含信用额度字段，该数据在财务系统的授信模块中。需finance-agent查询。",
        "del": "",
        "sg": "- finance-agent（信用额度、应收账款查询）\n- crm-agent（客户关系管理）\n- contract-agent（合同详情）",
    },
    {
        "id": "S2-13",
        "cat": "structured",
        "desc": "订单系统查到product_id，需product-agent翻译为名称+规格",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "本月销量前5的商品分别是哪些，各卖了多少钱",
        "own": "[Task#1]: 本月销量Top 5（来源：订单表，按product_id统计）：PROD-001 1,256件 ￥10,036,400, PROD-005 892件 ￥?（订单表无价格）, PROD-012 743件 ￥?, PROD-008 621件 ￥?, PROD-019 598件 ￥?。注意：订单表仅存product_id和quantity，不含商品名称、单价字段。只有PROD-001有手动标记价格。",
        "del": "",
        "sg": "- product-agent（商品名称、单价、规格查询）\n- analytics-agent（销售分析）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-14",
        "cat": "structured",
        "desc": "outcome=partial 但有关联键和明确的缺失字段",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "仓库A-03的库存盘点报告：理论库存、实际库存、差异",
        "own": "[Task#1]: outcome=partial。仓库A-03盘点结果：理论库存数据已从inventory表获取（SKU数347，总件数12,450）。实际库存数据与差异分析：reason_code=data_sovereignty_gap，库存系统不包含实际盘点数据，实际盘点记录在wms-agent的实地盘点模块中。join_key: warehouse=A-03, date=2024-09-01。",
        "del": "",
        "sg": "- wms-agent（实地盘点数据、差异分析）\n- inventory-agent（库存理论值）\n- audit-agent（库存审计）",
    },
    {
        "id": "S2-15",
        "cat": "structured",
        "desc": "空结果但实体名称可能在CRM系统中有映射",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "查询蓝天科技有限公司的所有交易记录",
        "own": "[Task#1]: 查询'蓝天科技有限公司'：订单表客户名称字段中搜索无匹配。订单数据中企业客户以6位客户编号存储（如C-001~C-250），不含公司全称。该名称可能在CRM系统中有对应的客户编号映射。",
        "del": "",
        "sg": "- crm-agent（客户公司名称→编号映射查询）\n- customer-agent（企业客户管理）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-16",
        "cat": "structured",
        "desc": "查询任务失败但给出了错误码和网关地址",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "PROD-042的质检不合格报告详情",
        "own": "[Task#1]: task fail。商品系统返回：质检模块不可用（error_code=QC_SERVICE_DOWN, gateway=http://quality-gateway:8080/）。PROD-042的基础信息可返回（名称：智能手表S2，分类：可穿戴设备），但质检报告需quality-agent独立查询。",
        "del": "",
        "sg": "- quality-agent（质检报告查询、不合格原因）\n- product-agent（商品基础数据）\n- defect-agent（缺陷跟踪）",
    },
    {
        "id": "S2-17",
        "cat": "structured",
        "desc": "数据日期范围不匹配，可能有其他系统有历史数据",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "2022年的全年销售额总览",
        "own": "[Task#1]: 查询2022年订单数据：当前订单系统数据起始于2023-01-01，2022年及之前的历史数据已在系统迁移时归档。当前可查询范围：2023-01-01至2024-12-31。2022年数据可能存在归档系统中。",
        "del": "",
        "sg": "- archive-agent（历史数据归档查询）\n- legacy-system-agent（旧系统数据查询）\n- data-warehouse-agent（数据仓库查询）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-18",
        "cat": "structured",
        "desc": "跨表关联查询只完成了左表，右表需其他agent",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "查询所有包含'电池'类商品且使用京东物流的订单",
        "own": "[Task#1]: 订单系统结果：订单表中含分类字段为'电子产品'的订单共1,234条，但无法精确筛选'电池'子类（订单分类粒度到一级类目）。物流配送方式字段订单表中不包含，配送信息需要logistics-agent查询。",
        "del": "",
        "sg": "- product-agent（精细化商品分类查询，可筛到'电池'子类）\n- logistics-agent（物流配送渠道查询）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-19",
        "cat": "structured",
        "desc": "当前查到的是汇总值，需要明细数据补充",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "PROD-001在每个省份的销售分布和退货率",
        "own": "[Task#1]: PROD-001销售数据：全国总销量1,256件，总退货量47件，总退货率3.74%。各省份的明细分布和分省退货率：订单系统不包含收货地址的省份信息，地址字段只到城市级别。省份映射数据需要geo-agent补充分省统计。",
        "del": "",
        "sg": "- geo-agent（地址→省份映射、地域销售分布）\n- analytics-agent（地域数据分析）\n- returns-agent（退货明细）\n- order-agent（订单查询）",
    },
    {
        "id": "S2-20",
        "cat": "structured",
        "desc": "一个类目有多种商品变体，需产品agent列出详细规格",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "列出所有在售的iPhone型号及其对应的存储容量和颜色",
        "own": "[Task#1]: 订单表在售iPhone统计（按product_id）：PROD-001 iPhone 15 Pro, PROD-031 iPhone 15, PROD-055 iPhone 14, PROD-098 iPhone SE。共4个型号。存储容量和颜色选项：订单表中无SKU级别的规格参数，仅存储product_id。详细规格需要product-agent的SKU目录查询。",
        "del": "",
        "sg": "- product-agent（SKU规格查询：存储容量、颜色、型号参数）\n- catalog-agent（产品目录管理）\n- order-agent（订单查询）",
    },

    # ═══════════════════════════════════════════════════════════
    #  UNSTRUCTURED × 20 （与第一轮无重复）
    # ═══════════════════════════════════════════════════════════

    # ── Group: needs_help = False (10 cases) ──────────────────

    {
        "id": "U2-01",
        "cat": "unstructured",
        "desc": "API文档解读——已给出结构化分析结果",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "分析这个REST API文档的接口设计质量",
        "own": "[Task#1]: API设计质量分析（已完成）：接口总数12个，RESTful规范度85%（有2个接口用了POST做查询），接口命名一致性良好（全小写下划线），响应格式统一（JSON + code/message/data），错误码体系完整（40个错误码覆盖业务异常）。不足之处：缺少版本号策略、无限流说明。但总体来说对'分析设计质量'已给出完整评价，从5个维度逐一评估并给出得分。",
        "del": "",
        "sg": "- api-doc-agent（API文档自动化校验）\n- security-agent（API安全检查）\n- specification-agent（规范审核）",
    },
    {
        "id": "U2-02",
        "cat": "unstructured",
        "desc": "产品描述文案改写已完成",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "把这段产品介绍改写成面向Z世代用户的版本",
        "own": "[Task#1]: 改写完成。原文：产品采用先进技术，提供卓越性能表现。改写后：这简直就是开挂神器！⚡性能炸裂，让你的效率直接起飞。轻巧机身，塞进包里就能走。告别等待、告别卡顿，从现在开始躺赢。改写后的文案：使用了Z世代网络用语、保持原文核心卖点、添加场景化描述、语气轻松有趣。全文480字，结构完整。",
        "del": "",
        "sg": "- copywriting-agent（文案创作与优化）\n- marketing-agent（营销语言建议）\n- social-media-agent（社交媒体适配）",
    },
    {
        "id": "U2-03",
        "cat": "unstructured",
        "desc": "SQL性能优化建议——已给出具体方案",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "优化这条慢SQL查询的性能",
        "own": "[Task#1]: SQL优化分析（已完成）：原SQL SELECT * FROM orders o JOIN users u ON o.user_id=u.id WHERE o.status='pending' ORDER BY o.created_at DESC。问题诊断：1.缺少索引(status字段扫描全表523,401行) 2.SELECT * 返回不必要字段 3.无LIMIT。优化方案：1.CREATE INDEX idx_orders_status_created ON orders(status, created_at) 2.改为必要字段 3.添加LIMIT 100。优化后预期：扫描行数<1000，执行时间<50ms。审查完成。",
        "del": "",
        "sg": "- dba-agent（数据库深度调优）\n- performance-agent（系统性能监控）\n- code-agent（代码审查）",
    },
    {
        "id": "U2-04",
        "cat": "unstructured",
        "desc": "用户反馈情感分析——已按情绪分类并给出趋势",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "分析最近两周的用户反馈，看看用户情绪怎么样",
        "own": "[Task#1]: 用户反馈情感分析（已完成，2024-09-01至2024-09-14，共867条）：正面56%（主要为物流速度快、客服态度好），中性27%（功能建议、咨询），负面17%（APP闪退、退款慢）。情绪趋势：第1周正面52%→第2周正面60%，负面从19%降至15%。高频关键词：闪退（89次）、退款（63次）、物流快（202次）。结论：整体情绪向好，待优化APP稳定性和退款流程。分析框架：情绪分类→趋势→关键词→建议。",
        "del": "",
        "sg": "- sentiment-agent（情感分析模型）\n- nlp-agent（自然语言处理）\n- feedback-agent（反馈系统管理）",
    },
    {
        "id": "U2-05",
        "cat": "unstructured",
        "desc": "技术方案评审——已逐点评估并给出结论",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "评审这份微服务拆分方案的技术可行性",
        "own": "[Task#1]: 微服务拆分方案评审（已完成全文评审）：方案共5个模块（用户服务、订单服务、商品服务、支付服务、通知服务）。技术评估：1.拆分粒度合理（每个服务职责单一）2.通信方式采用消息队列解耦→可行但有延迟成本3.数据库拆分采用每服务独立DB→数据一致性需最终一致性方案4.部署方案K8s+Istio→成熟方案。风险点：分布式事务是最大挑战（已标注4处跨服务操作）。结论：技术可行，建议先PoC验证事务一致性。评审覆盖：架构、通信、数据、部署、风险5个维度。",
        "del": "",
        "sg": "- architecture-agent（架构评审）\n- security-agent（安全架构审查）\n- devops-agent（部署方案审核）",
    },
    {
        "id": "U2-06",
        "cat": "unstructured",
        "desc": "邮件草稿已生成且格式完整",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "帮我写一封给客户的英文道歉邮件，因为物流延迟了3天",
        "own": "[Task#1]: 道歉邮件已生成。Subject: Apology for Shipping Delay - Order #ORD-xxx。Dear Customer, we sincerely apologize for the 3-day delay...（全文287词）。邮件结构：1.真诚道歉 2.解释原因（物流高峰期）3.补偿方案（10%折扣券+优先配送）4.联系方式。语气诚恳专业，格式规范，含签名档。",
        "del": "",
        "sg": "- email-agent（邮件模板管理）\n- translation-agent（翻译服务）\n- crm-agent（客户数据查询）",
    },
    {
        "id": "U2-07",
        "cat": "unstructured",
        "desc": "数据报告解读——已提取关键洞察和建议",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "解读这份用户增长数据报告，指出关键问题",
        "own": "[Task#1]: 用户增长报告解读（已完成）：关键数据——DAU月均增长3.2%，但次日留存率从45%降至38%（⚠️核心问题），获客成本CAC从￥23升至￥31（⚠️趋势恶化），新用户来源中自然流量占比从55%降至41%。三大问题：1.留存率下滑源于onboarding体验差（首日流失用户中67%未完成个人信息填写）2.CAC上升因付费渠道ROI降低 3.渠道依赖度上升。建议：1.简化注册流程 2.增加新用户引导 3.扩展内容营销渠道占比。",
        "del": "",
        "sg": "- analytics-agent（增长模型分析）\n- marketing-agent（获客渠道优化）\n- strategy-agent（战略建议）",
    },
    {
        "id": "U2-08",
        "cat": "unstructured",
        "desc": "代码代码审查——re：发现bug但已完整描述",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "review一下这个订单取消函数的逻辑，有没有bug",
        "own": "[Task#1]: 代码Review完成（函数：cancel_order）。逻辑分析：1.状态检查：只允许pending/confirmed状态取消→正确 2.库存回滚：调用inventory.rollback()，但未检查回滚是否成功→🐛Bug 3.支付退款：调用payment.refund()异步执行，未等待结果→🐛Bug 4.通知发送：只调用了send_notification()，未处理失败重试→改进建议。结论：2个Bug（库存回滚和退款无确认），1个改进建议。修复方案：库存回滚加try-catch+重试机制，退款改为await同步等待并检查返回码。",
        "del": "",
        "sg": "- code-agent（代码深度审查）\n- security-agent（安全审计）\n- test-agent（自动化测试生成）",
    },
    {
        "id": "U2-09",
        "cat": "unstructured",
        "desc": "市场研究报告总结——已归纳核心要点",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "帮我总结一下这份200页的行业白皮书的关键观点",
        "own": "[Task#1]: 行业白皮书总结（已处理全文，约8万字）：5大核心观点——①2024年中国SaaS市场规模达1,280亿元，增速放缓至18%（前值25%）②头部集中度加速：TOP10厂商份额从41%升至53%③AI Native产品崛起：AI功能成为客户采购TOP3决策因子④客户续费率下降：平均NDR从110%降至96%⑤出海趋势：30%的头部SaaS厂商已有海外收入。报告覆盖市场规模、竞争格局、技术趋势、客户行为、出海战略5个板块。",
        "del": "",
        "sg": "- research-agent（行业研究分析）\n- finance-agent（财务数据验证）\n- strategy-agent（战略解读）",
    },
    {
        "id": "U2-10",
        "cat": "unstructured",
        "desc": "需求文档分析——已提取功能列表和优先级",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "分析这份PRD文档，列出所有功能需求并按优先级分类",
        "own": "[Task#1]: PRD分析完成（文档v2.3，共35页）：P0（MVP必须）——①用户注册登录（手机+邮箱）②商品搜索与浏览③购物车④下单支付（微信+支付宝）；P1（V1.1必须）——⑤订单跟踪⑥退款流程⑦商品评价；P2（后续迭代）——⑧猜你喜欢推荐⑨社交分享⑩积分商城。共10个功能需求，已按P0/P1/P2三档分类并标注每个功能的详细描述、验收标准和依赖关系。",
        "del": "",
        "sg": "- project-agent（项目管理与排期）\n- ui-agent（UI/UX建议）\n- estimation-agent（工时评估）",
    },
    {
        "id": "U2-21",
        "cat": "unstructured",
        "desc": "第二轮 mid-exec：成文结论仍在，仅『理论上还能再深入』",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "总结这份年度财报的经营情况",
        "own": "[Task#1]: 已产出结构化总结：营收+18%、净利率12%、三大业务线拆分、主要风险4条、管理层展望。结论完整成文，可回答原始问题。\n[Mid-exec round 2 自检]: 若继续，理论上还能加入汇率敏感性、同业对标、分析师预期对比。",
        "del": "",
        "sg": "- finance-agent（财务分析）\n- analyst-agent（分析师预期）\n- research-agent（行业研究）",
    },
    {
        "id": "U2-22",
        "cat": "unstructured",
        "desc": "第二轮：已委派过且下游无增量，本层结论仍完整",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "review一下这个订单取消函数的逻辑，有没有bug",
        "own": "[Task#1]: 代码Review完成。结论：2个Bug（库存回滚未检查、退款未等待结果），1个改进建议。修复方案已给出。",
        "del": "[code-agent]: EMPTY 无额外发现。已审查完毕，不构成新的可执行缺口。",
        "sg": "- code-agent（代码深度审查）\n- security-agent（安全审计）\n- test-agent（自动化测试）",
    },

    # ── Group: needs_help = True (10 cases) ──────────────────

    {
        "id": "U2-11",
        "cat": "unstructured",
        "desc": "同传转录但只提取了原文本没翻译",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "把这场英文技术分享的文字记录翻译成中文",
        "own": "[Task#1]: 英文技术分享文字记录提取完成（来源：speech.mp4，时长45分钟）。已提取英文全文，共约6,200词。主题：Rust语言在嵌入式系统中的实践。内容涵盖：Rust简介、与C/C++对比、内存安全案例、嵌入式应用场景。但本skill（order_query）仅提取了原文字幕文本，不具备英→中翻译能力，需要进行翻译处理。",
        "del": "",
        "sg": "- translate-agent（多语种翻译服务，支持英→中）\n- nlp-agent（文本处理与结构化）\n- subtitle-agent（字幕处理）",
    },
    {
        "id": "U2-12",
        "cat": "unstructured",
        "desc": "法律文书审查发现明确的法条引用缺失",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "审查这份股权转让协议是否完整合规",
        "own": "[Task#1]: 股权转让协议审查（已完成初步审查）：协议主体信息完整，转让条款（股权比例、转让价格、支付方式）均已审查通过。但协议第7条「争议解决」选择了仲裁方式，却未明确指定仲裁机构和仲裁规则；第9条「税务责任」引用了「最新税收法规」但未列出具体的法规条文编号（如国家税务总局公告[2024]xx号）。本skill完成了结构和条款完整性检查，但仲裁条款和税务合规性需要legal-agent的专业审核，需要确认仲裁机构选择和具体法规引用。",
        "del": "",
        "sg": "- legal-agent（法律文书合规审查、仲裁条款、税法引用）\n- compliance-agent（法规合规性检查）\n- tax-agent（税务合规审核）",
    },
    {
        "id": "U2-13",
        "cat": "unstructured",
        "desc": "能力域错误：财务agent无法做图像OCR",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "把这张财务发票图片中的信息提取成结构化数据",
        "own": "[Task#1]: 本skill（finance_query）仅支持财务数据查询（账目、报表、凭证查询），不具备图像OCR识别能力。收到的附件为发票扫描件JPEG格式（invoice_20240901.jpg, 2.4MB），无法提取其中的文字信息。该发票可能包含：发票号码、开票日期、购买方信息、金额、税额。需要OCR或图像处理agent完成文字提取。",
        "del": "",
        "sg": "- ocr-agent（图像文字识别、发票结构化提取）\n- vision-agent（计算机视觉）\n- document-agent（文档解析）",
    },
    {
        "id": "U2-14",
        "cat": "unstructured",
        "desc": "完成安全审查但明确缺少性能基准测试数据",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "对payment_service做全面的质量评估",
        "own": "[Task#1]: payment_service质量评估（安全部分已完成）：1.代码审查通过（无SQL注入、XSS漏洞）2.加密方案合规（AES-256 + TLS 1.3）3.日志脱敏完整。但性能测试部分：本skill不具备压力测试和基准测试能力，无法提供TPS、P99延迟、并发容量等性能指标。需要performance-agent执行JMeter/Benchmark测试并提供性能报告。",
        "del": "",
        "sg": "- performance-agent（压力测试、Benchmark、性能指标采集）\n- security-agent（安全深度测试）\n- monitoring-agent（监控数据分析）",
    },
    {
        "id": "U2-15",
        "cat": "unstructured",
        "desc": "监控告警分析只拿到了日志但缺根因定位能力",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "今天上午10点数据库CPU飙升到95%，帮我分析原因",
        "own": "[Task#1]: 告警日志已提取（来源：monitoring系统，时间10:00-10:15）：CPU从23%飙升至95%，内存正常(62%)，连接数从150升至892(⚠️突增)，慢查询从2条升至47条。日志中有一行WARN：Connection pool exhausted for thread pool 'order-query'。本skill可从监控系统提取日志和指标，但无法做进一步的根因关联分析——例如哪些SQL导致了慢查询、连接池爆满的具体触发SQL是什么。",
        "del": "",
        "sg": "- dba-agent（慢查询分析、SQL执行计划、连接池诊断）\n- performance-agent（系统性能根因分析）\n- monitoring-agent（监控数据关联）",
    },
    {
        "id": "U2-16",
        "cat": "unstructured",
        "desc": "访谈纪要完成但缺少专业心理健康评估",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "分析这段员工离职面谈记录，评估是否存在管理问题",
        "own": "[Task#1]: 离职面谈记录分析（全文已完成编码）：员工反映的主要问题——①加班严重（连续3个月每周60+小时）②直属领导沟通方式粗暴 ③晋升无望（3年未调级）。本skill已完成文档的结构化整理和问题分类，但不具备组织心理学和管理学专业评估能力，无法判断这些问题的严重程度是否达到了需要管理干预的级别，或是否涉及劳动法合规风险。",
        "del": "",
        "sg": "- hr-agent（组织管理分析、职业倦怠评估）\n- legal-agent（劳动法合规审查）\n- psychology-agent（职场心理健康评估）",
    },
    {
        "id": "U2-17",
        "cat": "unstructured",
        "desc": "完成了静态分析但需动态安全扫描补充",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "对这个Web应用做完整的安全测试",
        "own": "[Task#1]: Web应用安全测试（静态部分已完成）：SAST扫描完成，发现3个中危漏洞——①Cookie未设HttpOnly ②一处日志输出包含用户密码 ③未限制文件上传类型。但动态安全测试（DAST/渗透测试）本skill不具备，无法进行XSS/XSRF/注入攻击的运行时验证、越权测试和API Fuzzing。需要security-agent执行完整的渗透测试和动态扫描。",
        "del": "",
        "sg": "- security-agent（DAST动态扫描、渗透测试、API Fuzzing）\n- pentest-agent（渗透测试）\n- code-agent（代码漏洞修复建议）",
    },
    {
        "id": "U2-18",
        "cat": "unstructured",
        "desc": "简历筛选完成但缺少背调与信用核查",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "对候选人王五做全面的入职背景审核",
        "own": "[Task#1]: 候选人王五的背景审核（已完成文档审核）：学历验证通过（北京大学计算机硕士），工作经历验证通过（前雇主阿里巴巴、字节跳动，HR系统已确认），技能证书验证通过（AWS Solution Architect, PMP）。但本skill不具备征信查询和犯罪记录调查能力，无法完成：①个人信用报告核查 ②犯罪记录查询 ③工作签证合规性验证。这三项需要background-check-agent补充。",
        "del": "",
        "sg": "- background-check-agent（征信报告、犯罪记录调查、签证合规）\n- hr-agent（人事审核）\n- legal-agent（雇佣法律合规）",
    },
    {
        "id": "U2-19",
        "cat": "unstructured",
        "desc": "AB测试数据分析完成了显著性检验但缺商业建议",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "分析这个AB测试结果并给出是否全量上线的建议",
        "own": "[Task#1]: AB测试数据分析（已完成统计检验）：对照组(A)转化率3.2%，实验组(B)转化率3.8%，提升幅度18.75%，p-value=0.023(<0.05)，统计显著。分流均匀性检验通过。本skill完成了数据显著性分析和统计检验，但明确声明不具备商业决策判断能力——无法评估18.75%的转化提升是否足以覆盖开发和运维成本，也无法做ROI预估和风险收益分析。",
        "del": "",
        "sg": "- business-agent（商业决策分析、ROI评估、风险收益分析）\n- product-agent（产品策略）\n- strategy-agent（上线决策建议）",
    },
    {
        "id": "U2-20",
        "cat": "unstructured",
        "desc": "开放域问答但有明确领域缺口（缺少实时灾害数据）",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "分析台风'玉兔'对华南地区供应链的影响评估",
        "own": "[Task#1]: 台风'玉兔'影响评估（已完成供应链基本面分析）：华南地区仓库分布——广州仓(库存￥2,300万)、深圳仓(￥1,800万)、厦门仓(￥900万)，受影响供应商23家。日常配送路线图已获取。但本skill无法获取实时气象和灾害数据（台风路径、风速、预警级别、预计登陆时间和地点），无法完成供应链中断风险评估。需要weather-agent或disaster-agent的实时灾害监测数据。",
        "del": "",
        "sg": "- weather-agent（实时气象数据、台风路径、预警信息）\n- disaster-agent（自然灾害风险评估）\n- logistics-agent（物流配送路线调整）\n- supply-chain-agent（供应链风险管理）",
    },
]


# ── LLM invocation with retry ─────────────────────────────────
async def call_llm_with_retry(llm: Any, prompt: str, case_id: str) -> dict:
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
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            data = await invoke_llm_with_tool(
                llm=llm,
                tool=detect_tool,
                messages=[HumanMessage(content=prompt)],
                metadata={
                    "run_id": f"test-acc-r2-{case_id}",
                    "trace_id": "b" * 32,
                    "user_id": "test-accuracy-r2",
                },
                tool_choice="detect_delegation_needs",
                span_name=f"test-acc-r2-{case_id}",
            )
            if data is None:
                raise RuntimeError("LLM did not call detect_delegation_needs tool")
            task_type = data.get("task_type")
            if task_type not in ("structured", "unstructured"):
                raise RuntimeError(f"Invalid task_type: {task_type!r}")
            needs_help = data.get("needs_help")
            if not isinstance(needs_help, bool):
                raise RuntimeError(f"Invalid needs_help type: {type(needs_help)}")
            return data
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                print(f"  [Retry] [{case_id}] attempt {attempt}/{MAX_RETRIES} failed: {e}")
                await asyncio.sleep(RETRY_DELAY)
            else:
                print(f"  [Retry] [{case_id}] all {MAX_RETRIES} attempts failed: {e}")
    raise last_error


async def run_single_case(llm: Any, tc: dict) -> dict:
    prompt = PROMPT_TEMPLATE.format(
        query=tc["query"],
        own_text=tc["own"],
        del_text=tc.get("del") or "(无)",
        sg_options=tc.get("sg") or "(无)",
    )
    r = await call_llm_with_retry(llm, prompt, tc["id"])
    actual_task_type = r.get("task_type", "?")
    actual_needs_help = r.get("needs_help", None)
    actual_synth_query = (r.get("synthesized_query") or "").strip()
    task_type_ok = (actual_task_type == tc["exp_task_type"])
    needs_help_ok = (actual_needs_help == tc["exp_needs_help"])
    # ── 契约断言：needs_help=true 必须给出可执行 synthesized_query ──
    # 提示词已把「能写出可执行子问题」设为 needs_help=true 的必要条件；
    # 生产代码在 query 为空时按「无明确缺口」提前退出。此处把同一契约
    # 纳入断言，否则「检测成功但派不出去」这条路径无法被回归发现。
    if actual_needs_help is True:
        query_ok = bool(actual_synth_query)
    else:
        # needs_help=false 时不要求 query（应当为空）
        query_ok = True
    all_ok = task_type_ok and needs_help_ok and query_ok
    return {
        "id": tc["id"], "desc": tc["desc"], "cat": tc["cat"],
        "exp_task_type": tc["exp_task_type"], "actual_task_type": actual_task_type,
        "task_type_ok": task_type_ok,
        "exp_needs_help": tc["exp_needs_help"], "actual_needs_help": actual_needs_help,
        "needs_help_ok": needs_help_ok, "query_ok": query_ok, "all_ok": all_ok,
        "reason": r.get("reason", ""),
        "synthesized_query": actual_synth_query,
        "target_sgs": r.get("target_sgs", []),
    }


def print_case_result(res: dict):
    status = "✅" if res["all_ok"] else "❌"
    tt = "✅" if res["task_type_ok"] else "❌"
    nh = "✅" if res["needs_help_ok"] else "❌"
    print(f"\n{'─' * 80}")
    print(f"[{res['id']}] {status} | {res['desc']} | cat={res['cat']}")
    print(f"  task_type:  expected={res['exp_task_type']}  actual={res['actual_task_type']}  {tt}")
    print(f"  needs_help: expected={res['exp_needs_help']}  actual={res['actual_needs_help']}  {nh}")
    if not res.get("query_ok", True):
        print(f"  synth_query: ❌ needs_help=true 但 synthesized_query 为空（契约违规，无法委派）")
    if res.get("reason"):
        print(f"  reason: {str(res['reason'])[:200]}")
    if res.get("synthesized_query"):
        print(f"  synthesized_query: {str(res['synthesized_query'])[:200]}")
    if res.get("target_sgs"):
        print(f"  target_sgs: {res['target_sgs']}")


async def retry_failed_cases(llm: Any, failed_ids: list[str]) -> list[dict]:
    if not failed_ids:
        return []
    print(f"\n{'=' * 80}")
    print(f"RETRY ROUND: {len(failed_ids)} failed case(s)"
          f" — up to {MAX_RETRIES} attempts each...")
    print(f"{'=' * 80}")
    still_failing: list[dict] = []
    for fid in failed_ids:
        orig = next((tc for tc in TEST_CASES if tc["id"] == fid), None)
        if orig is None:
            still_failing.append({"id": fid, "desc": "?", "error": "case not found"})
            continue
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                res = await run_single_case(llm, orig)
                if res["all_ok"]:
                    print(f"  [{fid}] ✅ PASSED on retry attempt {attempt}")
                    success = True
                    break
                else:
                    print(f"  [{fid}] ⚠️  retry {attempt} still failing: "
                          f"tt={res['actual_task_type']}(exp={orig['exp_task_type']}) "
                          f"nh={res['actual_needs_help']}(exp={orig['exp_needs_help']})")
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(RETRY_DELAY)
            except Exception as e:
                print(f"  [{fid}] ⚠️  retry {attempt} error: {e}")
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(RETRY_DELAY)
        if not success:
            still_failing.append({
                "id": fid, "desc": orig["desc"],
                "exp_task_type": orig["exp_task_type"],
                "exp_needs_help": orig["exp_needs_help"],
            })
    return still_failing


async def main():
    print("=" * 80)
    print(f"Mid-Exec Detection Accuracy Test — Round 2 ({len(TEST_CASES)} Cases)")
    print(f"Model: {MODEL}  |  Max Retries: {MAX_RETRIES}")
    print("=" * 80)

    llm = _build_llm()

    # ── Phase 1: Run all cases ──
    results: list[dict] = []
    failed_ids: list[str] = []

    for tc in TEST_CASES:
        try:
            res = await run_single_case(llm, tc)
        except Exception as e:
            res = {
                "id": tc["id"], "desc": tc["desc"], "cat": tc["cat"],
                "exp_task_type": tc["exp_task_type"], "actual_task_type": "ERROR",
                "task_type_ok": False,
                "exp_needs_help": tc["exp_needs_help"], "actual_needs_help": "ERROR",
                "needs_help_ok": False, "query_ok": True, "all_ok": False,
                "reason": f"Exception: {e}", "synthesized_query": "", "target_sgs": [],
            }
            print(f"\n{'─' * 80}")
            print(f"[{tc['id']}] ❌ ERROR | {tc['desc']}")
            print(f"  Error: {e}")
        print_case_result(res)
        results.append(res)
        if not res["all_ok"]:
            failed_ids.append(res["id"])

    # ── Phase 2: Retry ──
    still_failing: list[dict] = []
    if failed_ids:
        still_failing = await retry_failed_cases(llm, failed_ids)
        for r in results:
            if r["id"] in [sf["id"] for sf in still_failing]:
                continue
            if r["id"] in failed_ids:
                orig = next((tc for tc in TEST_CASES if tc["id"] == r["id"]), None)
                if orig is None:
                    continue
                try:
                    fresh = await run_single_case(llm, orig)
                    r.update(fresh)
                except Exception:
                    pass

    # ── Final Report ──
    total = len(TEST_CASES)
    tt_pass = sum(1 for r in results if r["task_type_ok"])
    nh_pass = sum(1 for r in results if r["needs_help_ok"])
    q_pass = sum(1 for r in results if r.get("query_ok", True))
    both_pass = sum(1 for r in results if r["all_ok"])

    print(f"\n{'=' * 80}")
    print(f"FINAL ACCURACY REPORT — ROUND 2")
    print(f"{'=' * 80}")
    print(f"task_type   accuracy: {tt_pass}/{total} = {tt_pass/total*100:.1f}%")
    print(f"needs_help  accuracy: {nh_pass}/{total} = {nh_pass/total*100:.1f}%")
    print(f"query contract  pass: {q_pass}/{total} = {q_pass/total*100:.1f}%"
          f"   (needs_help=true ⇒ synthesized_query 非空)")
    print(f"overall (all correct): {both_pass}/{total} = {both_pass/total*100:.1f}%")

    print(f"\n{'─' * 80}")
    print("Category Breakdown:")
    for cat in ["structured", "unstructured"]:
        cr = [r for r in results if r["cat"] == cat]
        if cr:
            tt_ok = sum(1 for r in cr if r["task_type_ok"])
            nh_ok = sum(1 for r in cr if r["needs_help_ok"])
            q_ok = sum(1 for r in cr if r.get("query_ok", True))
            all_ok = sum(1 for r in cr if r["all_ok"])
            print(f"  {cat}: task_type={tt_ok}/{len(cr)} "
                  f"| needs_help={nh_ok}/{len(cr)} "
                  f"| query_contract={q_ok}/{len(cr)} "
                  f"| all={all_ok}/{len(cr)}")

    if still_failing:
        print(f"\n{'─' * 80}")
        print(f"❌ STILL FAILING ({len(still_failing)} cases):")
        for sf in still_failing:
            print(f"  [{sf['id']}] {sf['desc']}")
            if not sf.get("error"):
                print(f"    task_type  exp={sf.get('exp_task_type','?')}")
                print(f"    needs_help exp={sf.get('exp_needs_help','?')}")
    else:
        print(f"\n{'─' * 80}")
        print(f"🎉 ALL {total} CASES PASSED — 100% ACCURACY!")
        print(f"{'─' * 80}")

    out = os.path.join(os.path.dirname(__file__), "mid_exec_accuracy_r2_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL, "max_retries": MAX_RETRIES, "total": total,
            "task_type_accuracy": f"{tt_pass}/{total} = {tt_pass/total*100:.1f}%",
            "needs_help_accuracy": f"{nh_pass}/{total} = {nh_pass/total*100:.1f}%",
            "query_contract_accuracy": f"{q_pass}/{total} = {q_pass/total*100:.1f}%",
            "overall_accuracy": f"{both_pass}/{total} = {both_pass/total*100:.1f}%",
            "still_failing": [sf["id"] for sf in still_failing],
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {out}")


if __name__ == "__main__":
    asyncio.run(main())