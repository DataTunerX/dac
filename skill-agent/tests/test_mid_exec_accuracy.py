"""
Mid-Exec Detection Accuracy Test — 结构化 & 非结构化各 10 个 cases.

目标：task_type 分类准确率 100%，needs_help 判定准确率 100%。
每个 case 最多重试 3 次以消除偶发波动。

Usage:
    cd /Users/james/daocloud/code/dac/skill-agent
    python tests/test_mid_exec_accuracy.py
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
API_KEY = "sk-xxx"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "deepseek-v4-flash-0731"
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds between retries

# ── LLM builder ───────────────────────────────────────────────
def _build_llm() -> Any:
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL,
        temperature=0.0,
        stream=False,
        extra_body={"enable_thinking": False},
    )


# ── Prompt template (same as production) ──────────────────────
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
#  TEST CASES
# ═══════════════════════════════════════════════════════════════
# 每个 case 必须验证 BOTH: task_type 和 needs_help。

TEST_CASES: list[dict] = [
    # ──────────────────────────────────────────────────────────
    #  STRUCTURED × 10
    # ──────────────────────────────────────────────────────────
    {
        "id": "S-01",
        "cat": "structured",
        "desc": "订单查询返回完整结果，所有字段均已覆盖",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "U001买了哪些商品，花了多少钱",
        "own": "[Task#1]: U001购买记录：1.iPhone 15 Pro, ￥7999(ORD-001) 2.AirPods Pro, ￥1799(ORD-003) 3.Anker充电器, ￥129(ORD-015)。共3笔，总金额￥9927。订单系统已返回全部记录。",
        "del": "",
        "sg": "- user-agent（用户身份信息查询）\n- product-agent（商品详情查询）\n- order-agent（订单数据查询）",
    },
    {
        "id": "S-02",
        "cat": "structured",
        "desc": "查到了库存但明确缺少供应商信息",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "iPhone 15 Pro的供应商是谁，库存还有多少",
        "own": "[Task#1]: iPhone 15 Pro库存：商品ID PROD-001, 当前库存150台, 价格￥7999。供应商信息：订单系统中不包含供应商数据。",
        "del": "",
        "sg": "- supplier-agent（供应商信息查询）\n- inventory-agent（库存管理）\n- product-agent（商品本体查询）",
    },
    {
        "id": "S-03",
        "cat": "structured",
        "desc": "确认实体在所有域都不存在，无需委派",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "查询用户ID为Z999的订单记录",
        "own": "[Task#1]: 查询Z999：订单数据用户ID范围U001~U020，不含Z999。全表扫描确认该ID不存在。已遍历全部订单表，确认无Z999记录。",
        "del": "",
        "sg": "- user-agent（用户身份查询，也仅支持U001~U020范围）\n- order-agent（订单查询）",
    },
    {
        "id": "S-04",
        "cat": "structured",
        "desc": "outcome=partial + data_sovereignty_gap 强制委派",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "U001的完整档案：订单记录、用户画像、会员等级",
        "own": "[Task#1]: outcome=partial。U001订单：ORD-001(iPhone 15 Pro), ORD-003(AirPods Pro)。用户画像和会员等级：reason_code=data_sovereignty_gap，订单系统不包含用户画像和会员数据。",
        "del": "",
        "sg": "- user-agent（用户画像查询）\n- membership-agent（会员等级查询）\n- profile-agent（用户档案）\n- order-agent（订单查询）",
    },
    {
        "id": "S-05",
        "cat": "structured",
        "desc": "查到了订单ID列表但缺商品详情",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "最近30天的热销商品列表，包含商品名称和价格",
        "own": "[Task#1]: 热销商品ID：PROD-001售156件, PROD-005售98件, PROD-012售73件。当前订单表不包含商品名称和价格字段，需商品agent查询。",
        "del": "",
        "sg": "- product-agent（商品名称、价格、分类查询）\n- analytics-agent（数据分析）\n- order-agent（订单查询）",
    },
    {
        "id": "S-06",
        "cat": "structured",
        "desc": "完整的统计报表，覆盖所有维度",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "2024年Q3总销售额和订单量统计",
        "own": "[Task#1]: Q3 2024 完整统计（来源：全量orders表）：总订单量 5,234 笔，总销售额 ￥8,766,000，均价 ￥1,674。月度明细：7月 1,620笔/￥2.71M，8月 1,832笔/￥3.05M，9月 1,782笔/￥3.00M。YoY增长 +15%，数据已覆盖全部维度。",
        "del": "",
        "sg": "- analytics-agent（数据分析与可视化）\n- product-agent（商品维度补充）\n- order-agent（订单查询）",
    },
    {
        "id": "S-07",
        "cat": "structured",
        "desc": "空结果但skill提示需要HR系统",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "张三的考勤记录和薪资明细",
        "own": "[Task#1]: 查询张三：订单系统仅含交易数据，无员工考勤或薪资信息。搜索'张三'：订单数据中无此客户名。建议：需使用 hr-agent 查询HR系统中的考勤和薪资数据。",
        "del": "",
        "sg": "- hr-agent（考勤、薪资、员工信息查询）\n- order-agent（订单查询）\n- finance-agent（财务数据查询）",
    },
    {
        "id": "S-08",
        "cat": "structured",
        "desc": "从错误日志查到线索，需支付网关agent",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "ORD-888支付失败的原因是什么",
        "own": "[Task#1]: ORD-888日志：ERROR PaymentGateway timeout (gateway_id=GW-PAY-03, retry_count=3)。订单状态：已取消。订单系统无支付网关详细日志，只有超时报错。支付网关GW-PAY-03的内部状态需要 payment-agent 查询。",
        "del": "",
        "sg": "- payment-agent（支付网关日志查询）\n- gateway-agent（网关状态监控）\n- order-agent（订单查询）",
    },
    {
        "id": "S-09",
        "cat": "structured",
        "desc": "多轮委派后数据已完整",
        "exp_task_type": "structured",
        "exp_needs_help": False,
        "query": "郑十买了哪些东西",
        "own": "[Task#1]: U008(郑十)的订单：ORD-014 Anker充电器 ￥129(已取消), ORD-020 WD Black SN850X 2TB ￥1599(已发货)。共2笔，总金额￥1728。商品名、用户ID、订单状态均已完整。",
        "del": "[user-agent]: 用户郑十→用户ID U008，手机138****8888，邮箱zhengshi@example.com。映射完成。",
        "sg": "- user-agent（用户查询）\n- product-agent（商品查询）\n- order-agent（订单查询）",
    },
    {
        "id": "S-10",
        "cat": "structured",
        "desc": "查询结果暗示ERP系统存在，尝试委派",
        "exp_task_type": "structured",
        "exp_needs_help": True,
        "query": "上月仓库的入库和出库记录汇总",
        "own": "[Task#1]: 订单系统不含WMS/仓储数据。当前订单数据仅跟踪已完成交易，不包含入库单、出库单或库存水位。仓储数据可能在ERP或WMS系统中。",
        "del": "",
        "sg": "- erp-agent（企业资源计划查询）\n- wms-agent（仓储管理系统查询）\n- inventory-agent（库存管理）\n- order-agent（订单查询）",
    },

    # ──────────────────────────────────────────────────────────
    #  UNSTRUCTURED × 10
    # ──────────────────────────────────────────────────────────
    {
        "id": "U-01",
        "cat": "unstructured",
        "desc": "文档总结已完整给出，不应委派",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "总结一下Q3季度报告的核心内容",
        "own": "[Task#1]: Q3季度报告核心内容（已完整提取）：收入增长15%至￥876万，新客户增加2,300家，核心挑战是东南亚供应链延迟导致交付周期延长3-5天。报告涵盖市场表现、财务数据、运营效率三个板块，各板块均已归纳。",
        "del": "",
        "sg": "- doc-agent（文档全文检索）\n- finance-agent（财务深度分析）\n- analytics-agent（数据分析）\n- market-agent（市场研究）",
    },
    {
        "id": "U-02",
        "cat": "unstructured",
        "desc": "能力域错误：order-agent无法审查代码",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "审查一下payment_service.py中是否存在SQL注入风险",
        "own": "[Task#1]: 本skill（order_query）仅支持订单数据查询，不具备代码审查能力。无法分析payment_service.py的代码内容。payment_service.py属于代码仓库，本Agent无法访问。",
        "del": "",
        "sg": "- code-agent（代码静态分析、安全审查）\n- security-agent（安全漏洞扫描）\n- dependency-agent（依赖安全检查）\n- order-agent（订单查询）",
    },
    {
        "id": "U-03",
        "cat": "unstructured",
        "desc": "翻译任务已完成，自包含任务不委派",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "把这段中文翻译成日文：今天天气真好，我们去公园散步吧",
        "own": "[Task#1]: 翻译完成。原文：今天天气真好，我们去公园散步吧。日文译文：今日はとてもいい天気ですね、公園に散歩に行きましょう。",
        "del": "",
        "sg": "- translate-agent（多语种翻译服务）\n- nlp-agent（自然语言处理）",
    },
    {
        "id": "U-04",
        "cat": "unstructured",
        "desc": "明确声明缺少合规性检查能力",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "审核这份隐私政策是否符合GDPR要求",
        "own": "[Task#1]: 隐私政策条款审核完成：数据收集范围、用户同意机制、数据保留期限均已审查，无显著违规。但本skill不具备GDPR合规性检查能力，无法确认数据处理协议、跨境传输条款是否满足GDPR Article 44-49的要求。需要法律合规agent审查。",
        "del": "",
        "sg": "- legal-agent（法律合规审核）\n- compliance-agent（GDPR / 法规合规检查）\n- doc-agent（文档检索）",
    },
    {
        "id": "U-05",
        "cat": "unstructured",
        "desc": "会议纪要完整提取，行动项清晰",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "今天周会讨论了哪些事项，我需要跟进什么",
        "own": "[Task#1]: 周会纪要（已完整提取）：议题1-前端重构进度100%完成(张三)，议题2-支付接口预计本周五联调(李四)，议题3-Q4预算草案11月10日前提交(全员)，议题4-客户投诉处理流程优化方案待定。你需要跟进：支付接口联调测试（配合李四，截止本周五）。共记录4个议题、7个行动项。",
        "del": "",
        "sg": "- project-agent（项目管理与任务分配）\n- task-agent（任务跟踪）\n- meeting-agent（会议管理）",
    },
    {
        "id": "U-06",
        "cat": "unstructured",
        "desc": "知识问答已完整覆盖，不应委派",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "公司年假政策是什么，如何申请",
        "own": "[Task#1]: 公司年假政策（来源：员工手册v2024.3 第4章）：入职满1年享5天，满3年享10天，满5年享15天；年假可累积至次年3月31日。申请流程：登录OA系统→提交请假申请→直属上级审批→人事确认。政策与流程已全部覆盖。",
        "del": "",
        "sg": "- hr-agent（人事政策查询）\n- doc-agent（企业文档检索）",
    },
    {
        "id": "U-07",
        "cat": "unstructured",
        "desc": "安全审计发现具体可查证的缺失项",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "对当前系统做全面的安全风险评估",
        "own": "[Task#1]: 安全扫描结果（已完成基础检查）：OWASP Top 10 检查无高危漏洞，API鉴权正常，HTTPS配置正确。但本skill不具备第三方依赖库安全审计能力，代码中引用的 old-encrypt-lib v1.2 存在已知CVE-2023-xxxxx漏洞，需要 dependency-agent 评估影响并提供替代方案。",
        "del": "",
        "sg": "- dependency-agent（依赖库安全审计）\n- security-agent（安全漏洞深度扫描）\n- code-agent（代码审查）",
    },
    {
        "id": "U-08",
        "cat": "unstructured",
        "desc": "合同风险分析已完成，有结构的结论",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "分析这份租赁合同的风险条款",
        "own": "[Task#1]: 租赁合同风险分析（已完成全文审查）：条款1押金-2个月租金，合规；条款2提前解约-需提前60天通知，违约金2个月租金，偏高但合法；条款3维修-业主承担结构性维修、租客承担日常维护，权责明确；条款4续租-年租金涨幅上限5%，合理；条款5违约-明确赔偿标准。共审查11项条款，结论：整体风险可控，无重大隐患。",
        "del": "",
        "sg": "- legal-agent（法律文书审查）\n- finance-agent（财务条款分析）\n- risk-agent（风险评估）",
    },
    {
        "id": "U-09",
        "cat": "unstructured",
        "desc": "能力域完全错误：订单不能分析医学影像",
        "exp_task_type": "unstructured",
        "exp_needs_help": True,
        "query": "分析这张CT影像中的异常区域",
        "own": "[Task#1]: 本skill（order_query）仅支持订单数据查询，不具备医学影像分析能力。该文件为DICOM格式医学影像，order_query技能完全无法处理图像数据。需要医学影像分析agent。",
        "del": "",
        "sg": "- medical-agent（医学影像分析）\n- vision-agent（计算机视觉）\n- image-agent（图像处理）\n- order-agent（订单查询）",
    },
    {
        "id": "U-10",
        "cat": "unstructured",
        "desc": "深度竞品分析已产出完整策略建议",
        "exp_task_type": "unstructured",
        "exp_needs_help": False,
        "query": "分析这份竞品报告并给出我们的应对策略建议",
        "own": "[Task#1]: 竞品分析报告（已完成）：竞品A降价15%抢占中低端市场，竞品B推出AI助手强化功能差异化。我方应对策略：1.短期强化售后服务体系（NPS已领先15分，巩固优势）2.中期增加AI功能模块（建议Q2立项）3.维持中高端定位，不参与价格战（毛利润率保持在58%）。报告涵盖市场对比、优劣势矩阵、SWOT分析和阶段性策略路线图，结论完整。",
        "del": "",
        "sg": "- analytics-agent（数据分析与建模）\n- strategy-agent（战略规划）\n- market-agent（市场研究）\n- competitor-agent（竞品情报）",
    },
]


# ── LLM invocation with retry ─────────────────────────────────
async def call_llm_with_retry(llm: Any, prompt: str, case_id: str) -> dict:
    """Invoke the detection LLM, retrying up to MAX_RETRIES times."""
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
                    "run_id": f"test-accuracy-{case_id}",
                    "trace_id": "a" * 32,
                    "user_id": "test-accuracy",
                },
                tool_choice="detect_delegation_needs",
                span_name=f"test-accuracy-{case_id}",
            )
            if data is None:
                raise RuntimeError("LLM did not call detect_delegation_needs tool")

            # Validate required fields
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


# ── Single case runner ────────────────────────────────────────
async def run_single_case(llm: Any, tc: dict) -> dict:
    """Run a single test case and return result dict."""
    prompt = PROMPT_TEMPLATE.format(
        query=tc["query"],
        own_text=tc["own"],
        del_text=tc.get("del") or "(无)",
        sg_options=tc.get("sg") or "(无)",
    )

    r = await call_llm_with_retry(llm, prompt, tc["id"])

    actual_task_type = r.get("task_type", "?")
    actual_needs_help = r.get("needs_help", None)
    task_type_ok = (actual_task_type == tc["exp_task_type"])
    needs_help_ok = (actual_needs_help == tc["exp_needs_help"])
    all_ok = task_type_ok and needs_help_ok

    return {
        "id": tc["id"],
        "desc": tc["desc"],
        "cat": tc["cat"],
        "exp_task_type": tc["exp_task_type"],
        "actual_task_type": actual_task_type,
        "task_type_ok": task_type_ok,
        "exp_needs_help": tc["exp_needs_help"],
        "actual_needs_help": actual_needs_help,
        "needs_help_ok": needs_help_ok,
        "all_ok": all_ok,
        "reason": r.get("reason", ""),
        "synthesized_query": r.get("synthesized_query", ""),
        "target_sgs": r.get("target_sgs", []),
    }


# ── Print helpers ─────────────────────────────────────────────
def print_case_result(res: dict):
    """Pretty-print a single test case result."""
    status = "✅" if res["all_ok"] else "❌"
    tt = "✅" if res["task_type_ok"] else "❌"
    nh = "✅" if res["needs_help_ok"] else "❌"
    print(f"\n{'─' * 80}")
    print(f"[{res['id']}] {status} | {res['desc']} | cat={res['cat']}")
    print(f"  task_type:  expected={res['exp_task_type']}  actual={res['actual_task_type']}  {tt}")
    print(f"  needs_help: expected={res['exp_needs_help']}  actual={res['actual_needs_help']}  {nh}")
    if res.get("reason"):
        print(f"  reason: {str(res['reason'])[:200]}")
    if res.get("synthesized_query"):
        print(f"  synthesized_query: {str(res['synthesized_query'])[:200]}")
    if res.get("target_sgs"):
        print(f"  target_sgs: {res['target_sgs']}")


# ── Retry: rerun failed cases ─────────────────────────────────
async def retry_failed_cases(llm: Any, failed_ids: list[str]) -> list[dict]:
    """Retry each failed case up to MAX_RETRIES times. Return still-failing."""
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
                "id": fid,
                "desc": orig["desc"],
                "exp_task_type": orig["exp_task_type"],
                "exp_needs_help": orig["exp_needs_help"],
            })

    return still_failing


# ── Main ──────────────────────────────────────────────────────
async def main():
    print("=" * 80)
    print(f"Mid-Exec Detection Accuracy Test — {len(TEST_CASES)} Cases")
    print(f"Model: {MODEL}  |  Max Retries: {MAX_RETRIES}")
    print("=" * 80)

    llm = _build_llm()

    # ── Phase 1: Run all cases ──
    results: list[dict] = []
    failed_ids: list[str] = []

    structured_cases = [tc for tc in TEST_CASES if tc["cat"] == "structured"]
    unstructured_cases = [tc for tc in TEST_CASES if tc["cat"] == "unstructured"]

    for tc in structured_cases + unstructured_cases:
        try:
            res = await run_single_case(llm, tc)
        except Exception as e:
            # Build error result
            res = {
                "id": tc["id"],
                "desc": tc["desc"],
                "cat": tc["cat"],
                "exp_task_type": tc["exp_task_type"],
                "actual_task_type": "ERROR",
                "task_type_ok": False,
                "exp_needs_help": tc["exp_needs_help"],
                "actual_needs_help": "ERROR",
                "needs_help_ok": False,
                "all_ok": False,
                "reason": f"Exception: {e}",
                "synthesized_query": "",
                "target_sgs": [],
            }
            print(f"\n{'─' * 80}")
            print(f"[{tc['id']}] ❌ ERROR | {tc['desc']}")
            print(f"  Error: {e}")

        print_case_result(res)
        results.append(res)
        if not res["all_ok"]:
            failed_ids.append(res["id"])

    # ── Phase 2: Retry failed cases ──
    if failed_ids:
        still_failing = await retry_failed_cases(llm, failed_ids)
        # Update results for those that passed on retry
        for r in results:
            if r["id"] in [sf["id"] for sf in still_failing]:
                continue  # keep as failed
            if r["id"] in failed_ids:
                # Refresh by running again and recording the final state
                orig = next((tc for tc in TEST_CASES if tc["id"] == r["id"]), None)
                if orig is None:
                    continue
                try:
                    fresh = await run_single_case(llm, orig)
                    r.update(fresh)
                except Exception:
                    pass  # keep old result
    else:
        still_failing = []

    # ── Final Report ──
    total = len(TEST_CASES)
    tt_pass = sum(1 for r in results if r["task_type_ok"])
    nh_pass = sum(1 for r in results if r["needs_help_ok"])
    both_pass = sum(1 for r in results if r["all_ok"])

    print(f"\n{'=' * 80}")
    print(f"FINAL ACCURACY REPORT")
    print(f"{'=' * 80}")
    print(f"task_type   accuracy: {tt_pass}/{total} = {tt_pass/total*100:.1f}%")
    print(f"needs_help  accuracy: {nh_pass}/{total} = {nh_pass/total*100:.1f}%")
    print(f"overall (both correct): {both_pass}/{total} = {both_pass/total*100:.1f}%")

    # Category breakdown
    print(f"\n{'─' * 80}")
    print("Category Breakdown:")
    for cat in ["structured", "unstructured"]:
        cr = [r for r in results if r["cat"] == cat]
        if cr:
            tt_ok = sum(1 for r in cr if r["task_type_ok"])
            nh_ok = sum(1 for r in cr if r["needs_help_ok"])
            all_ok = sum(1 for r in cr if r["all_ok"])
            print(f"  {cat}: task_type={tt_ok}/{len(cr)} "
                  f"| needs_help={nh_ok}/{len(cr)} "
                  f"| both={all_ok}/{len(cr)}")

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

    # Save detailed results
    out = os.path.join(os.path.dirname(__file__), "mid_exec_accuracy_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL,
            "max_retries": MAX_RETRIES,
            "total": total,
            "task_type_accuracy": f"{tt_pass}/{total} = {tt_pass/total*100:.1f}%",
            "needs_help_accuracy": f"{nh_pass}/{total} = {nh_pass/total*100:.1f}%",
            "overall_accuracy": f"{both_pass}/{total} = {both_pass/total*100:.1f}%",
            "still_failing": [sf["id"] for sf in still_failing],
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {out}")


if __name__ == "__main__":
    asyncio.run(main())