"""
稳定性测试：验证 mid-exec 检测 Prompt 的任务类型分类能力 + 缺口判定准确性。

分别针对结构化（5 个 case）和非结构化（5 个 case），每个 case 运行多轮
（默认 5 轮），统计：
  1. task_type 分类准确率（是否能正确判断 structured vs unstructured）
  2. needs_help 判定准确率（结构化保留原逻辑，非结构化降低误判）
  3. 跨轮一致性（多次运行结果是否稳定）

Usage:
    cd /Users/james/daocloud/code/dac/skill-agent
    python tests/test_task_type_detect.py
"""

import asyncio
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_sdk import ModelManager
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from agent.skill_agent import DelegationDetectionResult
from agent.tool_call_utils import invoke_llm_with_tool

# ── API 配置 ──
API_KEY = "sk-xxx"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-flash-0731"
RUNS_PER_CASE = 5  # 每个 case 跑几轮

# ═══════════════════════════════════════════════════════════════════════════
# Prompt Template（与生产环境 _detect_delegation_needs 中的 Prompt 保持一致）
# ═══════════════════════════════════════════════════════════════════════════
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
- 【关键】synthesized_query 必须从下游 SG 的视角编写，而非本层视角：
  本层（delegator）的视角是「我需要什么数据」，下游 SG 的视角是「我能用自己的技能回答什么问题」。
  synthesized_query 必须采用下游 SG 的视角：描述一个下游 SG 能用自己的技能独立完成的子问题。
  自检方法：如果本层自己就能回答 synthesized_query 描述的问题，
  → 说明写错了域，这是本层域内的问题，下游 SG 没有对应的技能。
  正确做法：先看下方「SG 技能列表」中 target_sgs 的技能，确认它们能处理什么类型的问题，
  然后 synthesized_query 只写这些技能能直接处理的内容。

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
- 【关键】如果「已完成委托结果」中显示某个 SG 返回了空结果或标记为 EMPTY，说明该 SG 无法为此问题提供数据。此时 target_sgs 不要再次包含该 SG 名称，应尝试委托给列表中其他不同的 SG（agent）。

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

# ═══════════════════════════════════════════════════════════════════════════
# Test Cases（5 结构化 + 5 非结构化）
# ═══════════════════════════════════════════════════════════════════════════
TEST_CASES = [
    # ── 结构化（structured） ──────────────────────────────────────────
    {
        "id": "S1",
        "desc": "订单查询空结果，skill提示需user_query做姓名→ID映射",
        "exp_needs_help": True,
        "exp_task_type": "structured",
        "query": "郑十买了哪些东西",
        "own": (
            "[Task#1]: 无法查询用户郑十的订单。订单数据中用户ID是U001~U008格式，"
            "不包含姓名。搜索'郑十'无匹配记录。"
            "建议：根据 skill 说明，需使用 user_query 技能查询郑十对应的用户ID。"
        ),
        "del": "",
        "sg": "- user-agent：提供用户姓名到ID的映射查询\n- product-agent：商品静态信息查询\n- order-agent：订单数据查询",
    },
    {
        "id": "S2",
        "desc": "已查到完整结果，所有字段均已覆盖",
        "exp_needs_help": False,
        "exp_task_type": "structured",
        "query": "U001买了哪些商品",
        "own": (
            "[Task#1]: U001购买的商品清单：\n"
            "1. iPhone 15 Pro (ORD-001, 金额7999, 已发货)\n"
            "2. AirPods Pro (ORD-003, 金额1899, 已完成)\n"
            "共2笔订单，上述信息已覆盖用户U001的全部购买记录。"
        ),
        "del": "",
        "sg": "- product-agent：商品静态信息查询\n- order-agent：订单数据查询",
    },
    {
        "id": "S3",
        "desc": "部分成功，查到了商品库存但缺供应商信息",
        "exp_needs_help": True,
        "exp_task_type": "structured",
        "query": "iPhone 15 Pro的供应商是谁，库存还有多少",
        "own": (
            "[Task#1]: iPhone 15 Pro 库存信息：\n"
            "商品ID: PROD-001, 库存数量: 150台, 价格: 7999元。\n"
            "供应商信息：当前 order_query skill 不包含供应商数据，"
            "无法查询该商品的供应商名称和联系方式。"
        ),
        "del": "",
        "sg": "- supplier-agent：查询商品的供应商信息\n- inventory-agent：库存水位与周转数据\n- order-agent：订单数据查询",
    },
    {
        "id": "S4",
        "desc": "空结果但确认实体ID在系统中不存在",
        "exp_needs_help": False,
        "exp_task_type": "structured",
        "query": "查询用户ID为Z999的订单",
        "own": (
            "[Task#1]: 查询结果为空。搜索Z999无匹配。"
            "订单系统中用户ID范围为 U001~U050，不含 Z999。"
            "经全表扫描确认该ID不存在于用户表中。"
        ),
        "del": "",
        "sg": "- user-agent：用户信息查询\n- order-agent：订单数据查询",
    },
    {
        "id": "S5",
        "desc": "多表关联查询，查到了订单但缺物流跟踪信息",
        "exp_needs_help": True,
        "exp_task_type": "structured",
        "query": "ORD-001的订单详情、物流状态和预计送达时间",
        "own": (
            "[Task#1]: ORD-001 订单详情：\n"
            "商品: iPhone 15 Pro, 金额: 7999元, 下单时间: 2024-08-15, 状态: 已发货。\n"
            "物流信息：当前 order_query skill 不包含物流跟踪数据，"
            "无法获取物流单号、当前位置和预计送达时间。"
        ),
        "del": "",
        "sg": "- logistics-agent：查询订单物流状态和预计送达时间\n- order-agent：订单数据查询",
    },

    # ── 非结构化（unstructured） ──────────────────────────────────────
    {
        "id": "U1",
        "desc": "翻译任务已完整完成",
        "exp_needs_help": False,
        "exp_task_type": "unstructured",
        "query": "把这段中文翻译成英文：今天天气真好，适合出去走走。",
        "own": (
            "[Task#1]: 翻译结果：\n"
            "原文：今天天气真好，适合出去走走。\n"
            "译文：The weather is really nice today, perfect for going out for a walk.\n"
            "翻译已完成，语义准确，语气恰当。"
        ),
        "del": "",
        "sg": "- translate-agent：多语言翻译服务\n- nlp-agent：自然语言处理\n- order-agent：订单数据查询",
    },
    {
        "id": "U2",
        "desc": "文档总结已完成，返回了结构化的归纳结果",
        "exp_needs_help": False,
        "exp_task_type": "unstructured",
        "query": "请总结一下Q3季度报告的核心内容",
        "own": (
            "[Task#1]: Q3季度报告核心内容总结：\n\n"
            "一、营收情况：Q3总营收1200万，同比增长15%，电商渠道占比62%。\n"
            "二、重点项目进展：供应链优化项目已完成二期上线，物流成本降低8%。\n"
            "三、风险与挑战：原材料价格波动、竞品价格战加剧。\n"
            "四、Q4展望：预计营收目标1500万，计划上线新品类X。\n\n"
            "以上已覆盖报告的全部主要章节。"
        ),
        "del": "",
        "sg": "- doc-agent：文档检索与摘要\n- analytics-agent：数据分析\n- order-agent：订单数据查询",
    },
    {
        "id": "U3",
        "desc": "order-agent收到代码审查需求，明确不具备该能力",
        "exp_needs_help": True,
        "exp_task_type": "unstructured",
        "query": "审查一下 payment_service.py 中的安全漏洞",
        "own": (
            "[Task#1]: 无法审查 payment_service.py。"
            "当前 order_query skill 仅支持订单数据查询（订单ID、商品、金额等），"
            "不具备代码审查能力，无代码仓库访问权限。"
            "该 task 属于代码审计领域，与订单数据查询无关。"
        ),
        "del": "",
        "sg": "- code-agent：代码审查与静态分析\n- security-agent：安全漏洞扫描\n- order-agent：订单数据查询",
    },
    {
        "id": "U4",
        "desc": "代码审查完成安全部分但明确缺合规审计",
        "exp_needs_help": True,
        "exp_task_type": "unstructured",
        "query": "审查 payment_service.py 的安全性和合规性",
        "own": (
            "[Task#1]: payment_service.py 审查结果（安全性部分）：\n"
            "已通过 SQL注入风险：已使用参数化查询，无风险。\n"
            "已通过 XSS防护：输出已做转义处理。\n"
            "已通过 认证鉴权：JWT token 验证逻辑正确。\n"
            "需关注 第三方依赖 payment-gateway-sdk 版本3.2.1 未做漏洞扫描。\n\n"
            "合规性审计：当前 skill 不包含 GDPR/PCI-DSS 等法规合规检查能力，"
            "需要专门的合规审计 agent 进行补充审查。"
        ),
        "del": "",
        "sg": "- compliance-agent：GDPR/PCI-DSS 合规审计\n- security-agent：安全漏洞检测\n- code-agent：代码审查",
    },
    {
        "id": "U5",
        "desc": "知识库问答已查到完整答案",
        "exp_needs_help": False,
        "exp_task_type": "unstructured",
        "query": "公司年假政策是什么",
        "own": (
            "[Task#1]: 公司年假政策（来源：员工手册v2024，第3章）：\n\n"
            "1. 入职满1年：5天年假\n"
            "2. 入职满3年：10天年假\n"
            "3. 入职满5年：15天年假\n"
            "4. 年假可累积至次年3月31日，逾期清零。\n"
            "5. 离职时未休年假按日工资折算补偿。\n\n"
            "以上信息完整覆盖了员工手册中年假章节的全部内容。"
        ),
        "del": "",
        "sg": "- doc-agent：文档检索\n- hr-agent：人力资源信息查询\n- order-agent：订单数据查询",
    },
]


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


async def call_llm(llm, prompt: str) -> dict | None:
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
            "run_id": "test-task-type",
            "trace_id": "e" * 32,
            "user_id": "test-task-type",
        },
        tool_choice="detect_delegation_needs",
        span_name="test-task-type-detect",
    )
    return data


async def run_one_case(llm, tc: dict, run_idx: int) -> dict | None:
    prompt = PROMPT_TEMPLATE.format(
        query=tc["query"],
        own_text=tc["own"],
        del_text=tc.get("del") or "(无)",
        sg_options=tc.get("sg") or "(无)",
    )
    try:
        r = await call_llm(llm, prompt)
        return r
    except Exception as e:
        return {"_error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════
async def main():
    print("=" * 90)
    print(" Mid-Exec Task-Type Detection — Stability & Accuracy Test")
    print(f" Model: {MODEL}  |  Runs per case: {RUNS_PER_CASE}")
    print(" Structured cases: 5  |  Unstructured cases: 5")
    print("=" * 90)

    llm = _build_llm()

    all_results = []
    case_summaries = {}

    for tc in TEST_CASES:
        case_id = tc["id"]
        print(f"\n{'─' * 90}")
        print(f" [{case_id}] {tc['desc']}")
        print(f"       Expected: needs_help={tc['exp_needs_help']}, task_type={tc['exp_task_type']}")
        print(f"{'─' * 90}")

        case_rounds = []
        for run in range(1, RUNS_PER_CASE + 1):
            ts_start = time.monotonic()
            r = await run_one_case(llm, tc, run)
            elapsed = time.monotonic() - ts_start

            if r is None:
                print(f"  Run {run}/{RUNS_PER_CASE}: WARN LLM returned None (no tool call)")
                case_rounds.append({"run": run, "error": "None", "needs_help": None, "task_type": None, "elapsed_s": round(elapsed, 2)})
                continue
            if "_error" in r:
                print(f"  Run {run}/{RUNS_PER_CASE}: ERR {r['_error'][:120]}")
                case_rounds.append({"run": run, "error": r["_error"], "needs_help": None, "task_type": None, "elapsed_s": round(elapsed, 2)})
                continue

            actual_help = r.get("needs_help", False)
            actual_type = r.get("task_type", "?")
            reason = (r.get("reason") or "")[:150]

            help_ok = "OK" if actual_help == tc["exp_needs_help"] else "MIS"
            type_ok = "OK" if actual_type == tc["exp_task_type"] else "MIS"

            print(
                f"  Run {run}/{RUNS_PER_CASE}: "
                f"needs_help={str(actual_help):5s} [{help_ok}]  |  "
                f"task_type={actual_type:12s} [{type_ok}]  |  "
                f"{elapsed:.2f}s"
            )
            if reason:
                print(f"           reason: {reason}")

            all_results.append({
                "case_id": case_id, "run": run,
                "needs_help": actual_help, "exp_needs_help": tc["exp_needs_help"],
                "help_match": actual_help == tc["exp_needs_help"],
                "task_type": actual_type, "exp_task_type": tc["exp_task_type"],
                "type_match": actual_type == tc["exp_task_type"],
                "reason": reason,
                "synthesized_query": r.get("synthesized_query", "")[:200],
                "target_sgs": r.get("target_sgs", []),
                "elapsed_s": round(elapsed, 2),
            })
            case_rounds.append({
                "run": run, "needs_help": actual_help, "task_type": actual_type,
                "help_match": actual_help == tc["exp_needs_help"],
                "type_match": actual_type == tc["exp_task_type"],
                "reason": reason,
            })

        # case summary
        valid = [cr for cr in case_rounds if cr["needs_help"] is not None]
        total = len(valid)
        if total == 0:
            print(f"  SUM: All {RUNS_PER_CASE} runs failed.")
            case_summaries[case_id] = {"desc": tc["desc"], "category": tc["exp_task_type"], "runs": 0, "help_acc": 0, "type_acc": 0, "cons_help": True, "cons_type": True}
            continue

        h_correct = sum(1 for cr in valid if cr["help_match"])
        t_correct = sum(1 for cr in valid if cr["type_match"])
        h_vals = [cr["needs_help"] for cr in valid]
        t_vals = [cr["task_type"] for cr in valid]
        h_acc = h_correct / total
        t_acc = t_correct / total
        cons_h = len(set(h_vals)) == 1
        cons_t = len(set(t_vals)) == 1

        print(f"  SUM: needs_help {h_correct}/{total} ({h_acc:.0%})  |  task_type {t_correct}/{total} ({t_acc:.0%})  |  consistent help={'Y' if cons_h else 'N'} type={'Y' if cons_t else 'N'}")
        case_summaries[case_id] = {"desc": tc["desc"], "category": tc["exp_task_type"], "runs": total, "help_acc": h_acc, "type_acc": t_acc, "cons_help": cons_h, "cons_type": cons_t}

    # ═══════════════════════════════════════════════════════════════════
    # Overall Summary
    # ═══════════════════════════════════════════════════════════════════
    print(f"\n{'=' * 90}")
    print(" OVERALL SUMMARY")
    print("=" * 90)

    valid_all = [r for r in all_results if r["needs_help"] is not None]
    total_runs = len(valid_all)

    help_total = sum(1 for r in valid_all if r["help_match"])
    type_total = sum(1 for r in valid_all if r["type_match"])

    s_runs = [r for r in valid_all if r["exp_task_type"] == "structured"]
    u_runs = [r for r in valid_all if r["exp_task_type"] == "unstructured"]
    s_h = sum(1 for r in s_runs if r["help_match"])
    s_t = sum(1 for r in s_runs if r["type_match"])
    u_h = sum(1 for r in u_runs if r["help_match"])
    u_t = sum(1 for r in u_runs if r["type_match"])

    print(f"\n  Total valid runs: {total_runs} / {len(all_results)}")
    if s_runs and u_runs:
        print(f"  {'Metric':<24} {'Overall':<14} {'Structured':<14} {'Unstructured':<14}")
        print(f"  {'─'*24} {'─'*14} {'─'*14} {'─'*14}")
        print(f"  {'needs_help accuracy':<24} {help_total:>2}/{total_runs:<3} ({help_total/total_runs:.0%}){'':>4} {s_h:>2}/{len(s_runs):<3} ({s_h/len(s_runs):.0%}){'':>4} {u_h:>2}/{len(u_runs):<3} ({u_h/len(u_runs):.0%})")
        print(f"  {'task_type  accuracy':<24} {type_total:>2}/{total_runs:<3} ({type_total/total_runs:.0%}){'':>4} {s_t:>2}/{len(s_runs):<3} ({s_t/len(s_runs):.0%}){'':>4} {u_t:>2}/{len(u_runs):<3} ({u_t/len(u_runs):.0%})")

    # per-case table
    print(f"\n  Per-case detail:")
    print(f"  {'ID':<6} {'Category':<14} {'HelpAcc':<8} {'TypeAcc':<8} {'H-Cons':<7} {'T-Cons':<7} {'Desc'}")
    print(f"  {'─'*6} {'─'*14} {'─'*8} {'─'*8} {'─'*7} {'─'*7} {'─'*40}")
    for cid in sorted(case_summaries.keys()):
        cs = case_summaries[cid]
        print(f"  {cid:<6} {cs['category']:<14} {cs['help_acc']:.0%}{'':>4} {cs['type_acc']:.0%}{'':>4} {'Y' if cs['cons_help'] else 'N':>7} {'Y' if cs['cons_type'] else 'N':>7} {cs['desc'][:40]}")

    # mispredictions
    wrong_help = [r for r in valid_all if not r["help_match"]]
    if wrong_help:
        print(f"\n  MISMATCH needs_help ({len(wrong_help)}):")
        for w in wrong_help:
            print(f"    [{w['case_id']}] R{w['run']}: exp={w['exp_needs_help']} got={w['needs_help']} type={w['task_type']} | {w['reason'][:100]}")

    wrong_type = [r for r in valid_all if not r["type_match"]]
    if wrong_type:
        print(f"\n  MISMATCH task_type ({len(wrong_type)}):")
        for w in wrong_type:
            print(f"    [{w['case_id']}] R{w['run']}: exp={w['exp_task_type']} got={w['task_type']}")

    # latency
    times = [r["elapsed_s"] for r in valid_all if r.get("elapsed_s")]
    if times:
        print(f"\n  Latency: avg={sum(times)/len(times):.2f}s  min={min(times):.2f}s  max={max(times):.2f}s  p95={sorted(times)[int(len(times)*0.95)]:.2f}s")

    # save results
    out = os.path.join(os.path.dirname(__file__), "task_type_detect_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"config": {"model": MODEL, "runs_per_case": RUNS_PER_CASE, "total_cases": len(TEST_CASES)}, "summary": {"total_runs": total_runs, "help_accuracy": help_total/total_runs if total_runs else 0, "type_accuracy": type_total/total_runs if total_runs else 0, "by_case": {k: {x: v[x] for x in ("desc","category","help_acc","type_acc","cons_help","cons_type")} for k, v in case_summaries.items()}}, "runs": all_results}, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved: {out}")
    print(f"\n{'=' * 90}")


if __name__ == "__main__":
    asyncio.run(main())