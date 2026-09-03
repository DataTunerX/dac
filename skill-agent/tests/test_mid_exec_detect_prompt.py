"""
Test script for the new mid_exec_detect prompt.
Tests 45 cases covering structured DB, unstructured document, and edge cases.

Uses model_sdk (ModelManager) + invoke_llm_with_tool, matching the
production code path in SkillAgentExecutor._detect_delegation_needs.

Environment variables:
    DASHSCOPE_API_KEY  -- API key for DashScope (required)
    DASHSCOPE_BASE_URL -- Base URL (default: https://dashscope.aliyuncs.com/compatible-mode/v1)
    DASHSCOPE_MODEL    -- Model name (default: deepseek-v4-flash-0731)

Usage:
    cd /Users/james/daocloud/code/dac/skill-agent
    DASHSCOPE_API_KEY=sk-xxx python tests/test_mid_exec_detect_prompt.py
"""

import asyncio
import json
import os
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


PROMPT_TEMPLATE = """你是一个多 agent 协作的数据缺口检测器。基于已有的执行结果和原始问题，判断是否还需要其他领域的补充数据。

核心判断逻辑：
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
6）只有当本层结果明确表示：原始问题中的实体或概念在自身数据域中确实不存在，且没有任何其他 agent 可能拥有该数据时，才返回 needs_help=false。

synthesized_query 书写规则（强制）：
- 只写下游 SG 本轮需要交付的子问题：关联键 + 缺失字段；
- 当没有关联键时，传递原始问题中的实体信息（姓名、ID、关键词等）作为查询线索；
- 禁止复述完整原题；禁止写入其它域目标或整题扩写；
- 禁止要求下游去计算本层已有或本层负责的指标；
- 下游拿到这句话应能直接执行并结束，无需理解整题其它部分。

重要约束：
- 不要依据 SG 的自描述文案选择目标；最终远程 SG 由后续标准 capability_check 全量广播（成员能力证据）决定；
- 即使下方 SG 名称列表为空，只要存在数据缺口，仍应 needs_help=true；
- 当 needs_help=true 时，target_sgs 应填写你认为可补充数据的 SG 名称。
  最终远程 SG 由后续标准 capability_check 全量广播决定，此处的 target_sgs 用于辅助性提示。

注意: 如果已有结果已经能完整回答原始问题，应返回 needs_help=false。

原始问题（仅供判断缺口，勿整段写入 synthesized_query）：{query}

本层自身执行结果：
{own_text}

已完成委托结果：
{del_text}

可委托的 SG 名称列表（仅供参考，非选人依据）：
{sg_options}

请调用 detect_delegation_needs 工具来输出结果。当 needs_help=true 时，reason 字段必须说明具体缺了什么数据、为什么需要补充。"""

TEST_CASES = [
    # ==================== Structured DB ====================
    {"id":1,"cat":"structured_db","desc":"订单查询空结果，skill提到需user_query","exp":True,
     "query":"郑十买了哪些东西",
     "own":"[Task#1]: 无法查询用户郑十的订单。订单数据中用户ID是U001~U008格式，不包含姓名。搜索郑十无匹配。建议：根据skill说明，需使用user_query技能查询郑十对应的用户ID。",
     "del":"","sg":"- user-agent\n- product-agent\n- order-agent"},
    {"id":2,"cat":"structured_db","desc":"有明确用户ID，需查商品详情","exp":True,
     "query":"U001买了哪些商品，这些商品的价格是多少",
     "own":"[Task#1]: U001的订单：ORD-001|已发货|iPhone 15 Pro|U001, ORD-003|已完成|AirPods Pro|U001",
     "del":"","sg":"- product-agent\n- order-agent"},
    {"id":3,"cat":"structured_db","desc":"已查到完整结果无需委派","exp":False,
     "query":"U001买了哪些商品",
     "own":"[Task#1]: U001购买的商品：1.iPhone 15 Pro(ORD-001) 2.AirPods Pro(ORD-003) 共2条。",
     "del":"","sg":"- product-agent\n- order-agent"},
    {"id":4,"cat":"structured_db","desc":"空结果且确认实体不存在于任何域","exp":False,
     "query":"查询用户ID为Z999的订单",
     "own":"[Task#1]: 查询结果为空。搜索Z999无匹配。订单数据用户ID范围U001~U020，不含Z999。该ID不存在于系统中。",
     "del":"","sg":"- user-agent\n- order-agent"},
    {"id":5,"cat":"structured_db","desc":"部分成功，有商品ID但缺供应商信息","exp":True,
     "query":"iPhone 15 Pro的供应商是谁，库存还有多少",
     "own":"[Task#1]: iPhone 15 Pro库存：商品ID PROD-001, 库存150, 价格7999。供应商信息：当前skill不包含供应商数据。",
     "del":"","sg":"- supplier-agent\n- inventory-agent\n- product-agent"},
    {"id":6,"cat":"structured_db","desc":"SQL查询返回用户ID列表，需查用户详情","exp":True,
     "query":"最近一周下单的活跃用户有哪些，他们的联系方式是什么",
     "own":"[Task#1]: 活跃用户ID：U001,U003,U005,U008,U012 共23笔订单。用户联系方式：订单数据中不包含。",
     "del":"","sg":"- user-agent\n- order-agent"},
    {"id":7,"cat":"structured_db","desc":"查到错误日志，需要代码审查","exp":True,
     "query":"ORD-999订单为什么失败了，请分析原因",
     "own":"[Task#1]: ORD-999日志：ERROR PaymentService timeout, OrderService fallback triggered。订单状态：已取消。无详细堆栈。",
     "del":"","sg":"- code-agent\n- log-agent\n- order-agent"},
    {"id":8,"cat":"structured_db","desc":"完整结果已足够","exp":False,
     "query":"2024年8月销售额最高的商品是什么",
     "own":"[Task#1]: 8月销售统计：最高商品iPhone 15 Pro, 销售额1247000, 销量156台。数据来源：orders.txt全量统计。",
     "del":"","sg":"- product-agent\n- order-agent"},
    {"id":9,"cat":"structured_db","desc":"空结果，skill提到需要HR系统","exp":True,
     "query":"张三的考勤记录和薪资情况",
     "own":"[Task#1]: 无法查询张三的考勤。当前order_query仅支持订单数据，不含员工数据。建议：需使用hr_query技能查询HR系统。",
     "del":"","sg":"- hr-agent\n- order-agent"},
    {"id":10,"cat":"structured_db","desc":"有用户偏好数据，需要推荐引擎","exp":True,
     "query":"给U005推荐一些他可能喜欢的商品",
     "own":"[Task#1]: U005无历史订单。需要用户偏好数据或浏览行为数据进行推荐。",
     "del":"","sg":"- recommend-agent\n- user-agent\n- order-agent"},

    # ==================== Unstructured Document ====================
    {"id":11,"cat":"unstructured_doc","desc":"文档总结空结果，需文档agent","exp":True,
     "query":"请总结一下Q3季度报告的核心内容",
     "own":"[Task#1]: 无法找到Q3季度报告。当前order_query仅支持订单数据查询。搜索Q3季度报告无匹配。数据目录无文档或报告文件。",
     "del":"","sg":"- doc-agent\n- report-agent\n- order-agent"},
    {"id":12,"cat":"unstructured_doc","desc":"代码审查空结果，需代码agent","exp":True,
     "query":"审查一下payment_service.py中的安全漏洞",
     "own":"[Task#1]: 无法审查payment_service.py。当前order_query仅支持订单数据查询，不具备代码审查能力。无代码仓库访问权限。",
     "del":"","sg":"- code-agent\n- security-agent\n- order-agent"},
    {"id":13,"cat":"unstructured_doc","desc":"翻译任务已完成","exp":False,
     "query":"把这段中文翻译成英文：今天天气真好",
     "own":"[Task#1]: 翻译结果：原文：今天天气真好 译文：The weather is really nice today. 翻译完成。",
     "del":"","sg":"- translate-agent\n- order-agent"},
    {"id":14,"cat":"unstructured_doc","desc":"客服对话需要情感分析","exp":True,
     "query":"分析最近客服对话中用户的情绪趋势",
     "own":"[Task#1]: 客服对话文本：对话1:为什么订单还没发货！等了三天了！对话2:退货流程太复杂了。对话3:终于收到货了谢谢。当前仅提取了对话文本，未进行情感分析。",
     "del":"","sg":"- sentiment-agent\n- nlp-agent\n- order-agent"},
    {"id":15,"cat":"unstructured_doc","desc":"网页抓取有原始HTML，需内容提取","exp":True,
     "query":"提取京东iPhone 15 Pro的商品详情页中的规格参数",
     "own":"[Task#1]: 已获取https://item.jd.com/xxx.html的原始HTML约150KB。当前skill不具备HTML解析和结构化提取能力。",
     "del":"","sg":"- web-parser-agent\n- extract-agent\n- order-agent"},
    {"id":16,"cat":"unstructured_doc","desc":"会议录音文本，需提取行动项","exp":True,
     "query":"今天周会讨论了哪些事项，需要我做什么",
     "own":"[Task#1]: 周会转录文本约5000字。张三：上周完成了支付模块重构。李四：下周需要对接新物流接口。当前仅提取原始文本，未进行结构化分析和行动项提取。",
     "del":"","sg":"- meeting-agent\n- nlp-agent\n- order-agent"},
    {"id":17,"cat":"unstructured_doc","desc":"空结果需邮件agent","exp":True,
     "query":"帮我查一下上周发给王总的报价邮件",
     "own":"[Task#1]: 无法查询邮件。当前order_query仅支持订单数据查询，不具备邮件检索能力。数据目录无邮件数据。",
     "del":"","sg":"- email-agent\n- order-agent"},
    {"id":18,"cat":"unstructured_doc","desc":"知识库查询已查到完整答案","exp":False,
     "query":"公司年假政策是什么",
     "own":"[Task#1]: 公司年假政策：1.入职满1年5天 2.满3年10天 3.满5年15天 4.可累积至次年3月31日。来源：员工手册v2024。",
     "del":"","sg":"- hr-agent\n- doc-agent\n- order-agent"},
    {"id":19,"cat":"unstructured_doc","desc":"有政策文档需法律agent审核","exp":True,
     "query":"这份隐私政策是否符合GDPR要求",
     "own":"[Task#1]: 隐私政策摘要：我们收集用户的姓名、邮箱、地址用于订单配送。用户数据保留24个月。当前skill已提取文档全文，但不具备法律合规审查能力。需要专业GDPR合规检查。",
     "del":"","sg":"- legal-agent\n- compliance-agent\n- order-agent"},
    {"id":20,"cat":"unstructured_doc","desc":"图片描述需视觉agent","exp":True,
     "query":"这张产品图片中展示了哪些配件",
     "own":"[Task#1]: 图片URL: https://cdn.example.com/product-shot-001.jpg 大小2048x1536 JPEG。当前skill不具备图像识别能力。无法提取配件信息。",
     "del":"","sg":"- vision-agent\n- image-agent\n- order-agent"},

    # ==================== Edge Cases ====================
    {"id":21,"cat":"edge_case","desc":"空结果+确认实体在任何域都不存在","exp":False,
     "query":"查询火星基地的订单数据",
     "own":"[Task#1]: 查询结果为空。搜索火星基地无匹配。当前订单系统仅覆盖地球区域，不包含火星数据。确认该实体在系统中不存在，且无任何agent可能拥有该数据。",
     "del":"","sg":"- order-agent\n- product-agent\n- user-agent"},
    {"id":22,"cat":"edge_case","desc":"空结果但问题本身已回答完毕","exp":False,
     "query":"系统中是否有超过100万的订单",
     "own":"[Task#1]: 遍历所有订单数据，最大订单金额89999。系统中不存在超过100万的订单。问题已回答完毕。",
     "del":"","sg":"- order-agent\n- finance-agent"},
    {"id":23,"cat":"edge_case","desc":"outcome=partial强制委派","exp":True,
     "query":"U001的订单详情和用户画像",
     "own":"[Task#1]: outcome=partial U001订单：ORD-001 iPhone 15 Pro, ORD-003 AirPods Pro。用户画像：当前skill不包含。reason_code=data_sovereignty_gap",
     "del":"","sg":"- user-agent\n- profile-agent\n- order-agent"},
    {"id":24,"cat":"edge_case","desc":"空结果但关键词可能在别的agent域","exp":True,
     "query":"查找一下关于供应链优化的内部报告",
     "own":"[Task#1]: 查询结果为空。当前order_query仅支持订单数据查询。搜索供应链优化、内部报告均无匹配。订单数据不含报告文档。",
     "del":"","sg":"- doc-agent\n- report-agent\n- supply-chain-agent\n- order-agent"},
    {"id":25,"cat":"edge_case","desc":"多轮委托后数据已完整","exp":False,
     "query":"郑十买了哪些东西",
     "own":"[Task#1]: U008(郑十)购买的商品：1.Anker充电器(ORD-014,已取消) 2.WD Black SN850X 2TB(ORD-020,已发货) 共2条。",
     "del":"[user-agent]: 用户郑十对应的用户ID为U008。完整记录：U008|郑十|13800008888|zhengshi@example.com",
     "sg":"- user-agent\n- product-agent\n- order-agent"},

    # ==================== Complex Structured DB (26-33) ====================
    {"id":26,"cat":"complex_db","desc":"用户用昵称查询，订单系统查不到，可能user-agent有映射","exp":True,
     "query":"老王最近买了什么",
     "own":"[Task#1]: 查询老王无匹配。订单数据中客户名称字段为正式姓名，无昵称记录。搜索'老王'返回0条结果。",
     "del":"","sg":"- user-agent\n- order-agent\n- crm-agent"},
    {"id":27,"cat":"complex_db","desc":"查询结果部分返回但缺少物流信息，需物流agent","exp":True,
     "query":"ORD-001的订单详情、物流状态和预计送达时间",
     "own":"[Task#1]: ORD-001详情：iPhone 15 Pro, 金额7999, 下单时间2024-08-15。物流信息：当前订单数据不含物流跟踪信息。",
     "del":"","sg":"- logistics-agent\n- order-agent\n- product-agent"},
    {"id":28,"cat":"complex_db","desc":"查询结果提到'请联系客服部门'，可能存在客服agent","exp":True,
     "query":"ORD-888为什么被取消了，能恢复吗",
     "own":"[Task#1]: ORD-888状态：已取消，取消原因：风控审核未通过。订单数据中无详细风控记录。关于恢复订单，请联系客服部门处理。",
     "del":"","sg":"- risk-agent\n- support-agent\n- order-agent"},
    {"id":29,"cat":"complex_db","desc":"多实体关联，本层查到订单但商品规格和评价需其他agent","exp":True,
     "query":"PROD-001这个商品的完整信息：规格、库存、供应商、用户评价",
     "own":"[Task#1]: PROD-001(iPhone 15 Pro)：库存150, 价格7999。规格和用户评价：当前订单系统不包含商品详细规格参数和用户评价数据。",
     "del":"","sg":"- product-agent\n- review-agent\n- supplier-agent\n- order-agent"},
    {"id":30,"cat":"complex_db","desc":"查询结果暗示有ERP系统，尝试委派","exp":True,
     "query":"上月仓库的入库和出库记录汇总",
     "own":"[Task#1]: 订单数据中无仓库入库出库记录。当前订单系统仅跟踪已完成订单，不含仓储管理数据。该数据可能在ERP或WMS系统中。",
     "del":"","sg":"- erp-agent\n- wms-agent\n- inventory-agent\n- order-agent"},
    {"id":31,"cat":"complex_db","desc":"返回了原始数据但需要聚合分析，可能分析agent能帮忙","exp":True,
     "query":"哪些商品是滞销品，需要清仓处理",
     "own":"[Task#1]: 近90天订单数据：PROD-001售156台, PROD-002售12台, PROD-003售0台, PROD-004售3台。未做滞销分析和建议。",
     "del":"","sg":"- analytics-agent\n- inventory-agent\n- order-agent"},
    {"id":32,"cat":"complex_db","desc":"查询'相关'概念模糊，但可能有其他agent有相关数据","exp":True,
     "query":"查询与ORD-001相关的所有业务记录",
     "own":"[Task#1]: ORD-001直接关联：用户U001, 商品PROD-001, 金额7999。'相关'范围不明确，当前仅返回订单直接关联数据。",
     "del":"","sg":"- user-agent\n- product-agent\n- payment-agent\n- order-agent"},
    {"id":33,"cat":"complex_db","desc":"返回了SQL执行计划原始输出，需要DBA解读","exp":True,
     "query":"分析最近慢查询的根因并给出优化建议",
     "own":"[Task#1]: 慢查询日志：SELECT * FROM orders WHERE status='pending' ORDER BY created_at DESC，执行时间2.3s。EXPLAIN结果：type=ALL, rows=523401。未做根因分析和优化建议。",
     "del":"","sg":"- dba-agent\n- performance-agent\n- order-agent"},

    # ==================== Complex Unstructured (34-40) ====================
    {"id":34,"cat":"complex_doc","desc":"PDF扫描件需要OCR才能提取文字，本层无OCR能力","exp":True,
     "query":"把这份扫描版的合同中的关键条款提取出来",
     "own":"[Task#1]: 已获取contract_scan_v2.pdf文件1.2MB。该文件为扫描版PDF，当前skill无法对图片型PDF进行OCR文字识别。需要OCR能力。",
     "del":"","sg":"- ocr-agent\n- document-agent\n- legal-agent\n- order-agent"},
    {"id":35,"cat":"complex_doc","desc":"Mixed content: 文档中有表格和图表，需要多种能力","exp":True,
     "query":"分析这份年报中的财务数据和业务趋势",
     "own":"[Task#1]: 年报文本已提取约8000字，包含管理层讨论和业务描述。但财务表格和图表数据未结构化提取，趋势分析未做。",
     "del":"","sg":"- finance-agent\n- analytics-agent\n- chart-agent\n- order-agent"},
    {"id":36,"cat":"complex_doc","desc":"文档引用外部资料，可能需其他agent检索","exp":True,
     "query":"根据技术方案文档，评估项目风险",
     "own":"[Task#1]: 技术方案文档已提取：采用微服务架构，引用'公司安全规范v3.2'和'第三方依赖清单'。当前skill未获取安全规范和依赖清单的详细内容，无法评估合规性和依赖风险。",
     "del":"","sg":"- security-agent\n- compliance-agent\n- dependency-agent\n- order-agent"},
    {"id":37,"cat":"complex_doc","desc":"代码审查发现依赖第三方库，需检查第三方库安全","exp":True,
     "query":"审查payment_service.py的安全性和依赖风险",
     "own":"[Task#1]: payment_service.py审查结果：代码本身无SQL注入和XSS风险。但代码导入了未审查的第三方库 payment-gateway-sdk==3.2.1，该库的安全性未验证。",
     "del":"","sg":"- security-agent\n- dependency-agent\n- code-agent\n- order-agent"},
    {"id":38,"cat":"complex_doc","desc":"翻译文档中遇到专业术语，可能需要术语库agent","exp":True,
     "query":"把这份医疗设备说明书翻译成中文",
     "own":"[Task#1]: 说明书英文文本已提取1200字。翻译完成80%，但部分医学术语（如'endotracheal intubation'、'capnography'）无法确认准确中文译法。",
     "del":"","sg":"- medical-agent\n- terminology-agent\n- translate-agent\n- order-agent"},
    {"id":39,"cat":"complex_doc","desc":"会议纪要提到'待确认'事项，需要向其他系统确认","exp":True,
     "query":"今天项目会讨论了哪些需要跟进的事项",
     "own":"[Task#1]: 会议纪要提取：1.前端重构已完成(张三) 2.支付接口对接待确认(李四) 3.数据库迁移需审批(待确认)。当前仅提取文本，未对'待确认'事项进行状态查询。",
     "del":"","sg":"- project-agent\n- task-agent\n- approval-agent\n- order-agent"},
    {"id":40,"cat":"complex_doc","desc":"图片中既有产品又有文字标签，需要OCR+视觉识别","exp":True,
     "query":"这张产品展示图中包含了哪些产品型号和价格",
     "own":"[Task#1]: 图片URL已获取，分辨率2048x1536。当前skill不具备图像识别和OCR能力，无法提取图片中的产品型号和价格标签文字。",
     "del":"","sg":"- vision-agent\n- ocr-agent\n- image-agent\n- order-agent"},

    # ==================== Complex Edge Cases (41-45) ====================
    {"id":41,"cat":"complex_edge","desc":"查询结果为空，但提示'数据可能在其他系统'","exp":True,
     "query":"查询项目Alpha的预算和实际支出",
     "own":"[Task#1]: 查询项目Alpha无匹配。订单系统仅包含订单交易数据，不包含项目预算和支出数据。该数据可能存在于财务系统或项目管理系统中。",
     "del":"","sg":"- finance-agent\n- project-agent\n- budget-agent\n- order-agent"},
    {"id":42,"cat":"complex_edge","desc":"查询结果'无法确认'，但给出了可能的方向，尝试委派","exp":True,
     "query":"用户U999的会员等级和权益",
     "own":"[Task#1]: 无法确认U999的会员等级。订单系统中U999有3笔订单，但会员信息不在订单数据中。会员等级可能由CRM或会员系统管理。",
     "del":"","sg":"- crm-agent\n- membership-agent\n- user-agent\n- order-agent"},
    {"id":43,"cat":"complex_edge","desc":"问题涉及多领域，当前结果只覆盖部分，剩余部分尝试委派","exp":True,
     "query":"分析大促期间的销售表现、库存压力和物流时效",
     "own":"[Task#1]: 大促期间(11.1-11.11)销售数据：订单数5234, GMV 876万。库存压力和物流时效：订单数据中不包含库存水位和物流时效指标。",
     "del":"","sg":"- inventory-agent\n- logistics-agent\n- analytics-agent\n- order-agent"},
    {"id":44,"cat":"complex_edge","desc":"返回了汇总数据但缺少明细，可能下游有明细数据","exp":True,
     "query":"2024年Q3各品类的销售明细和退货原因",
     "own":"[Task#1]: Q3销售汇总：电子产品 234万, 家居 156万, 服装 89万。退货原因和订单明细：当前返回的是汇总数据，未包含逐笔订单的退货原因。",
     "del":"","sg":"- analytics-agent\n- product-agent\n- order-agent"},
    {"id":45,"cat":"complex_edge","desc":"查询涉及时间范围，本层只有部分数据，可能其他agent有更全数据","exp":True,
     "query":"2024年全年用户增长趋势和留存率",
     "own":"[Task#1]: 订单系统可统计2024年有下单行为的用户数：Q1 1200, Q2 1500, Q3 1800, Q4 2100。但注册用户总数、未下单用户、留存率等指标订单数据不包含。",
     "del":"","sg":"- user-agent\n- analytics-agent\n- growth-agent\n- order-agent"},
]


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
            "run_id": "test-mid-exec",
            "trace_id": "d" * 32,
            "user_id": "test-mid-exec",
        },
        tool_choice="detect_delegation_needs",
        span_name="test-mid-exec-detect",
    )
    if data is None:
        raise RuntimeError("LLM did not call detect_delegation_needs tool")
    return data


async def main():
    if not API_KEY:
        print("ERROR: DASHSCOPE_API_KEY environment variable is required.")
        print("Usage: DASHSCOPE_API_KEY=sk-xxx python tests/test_mid_exec_detect_prompt.py")
        sys.exit(1)

    print("=" * 80)
    print(f"Mid-Exec Detect Prompt Test - {len(TEST_CASES)} Cases | Model: {MODEL}")
    print("=" * 80)

    llm = _build_llm()
    results = []
    passed = 0
    failed = 0
    failed_cases = []

    for tc in TEST_CASES:
        prompt = PROMPT_TEMPLATE.format(
            query=tc["query"],
            own_text=tc["own"],
            del_text=tc.get("del") or "(无)",
            sg_options=tc.get("sg") or "(无)",
        )
        try:
            r = await call_llm(llm, prompt)
        except Exception as e:
            print(f"\n[#{tc['id']}] ERROR: {e}")
            failed += 1
            failed_cases.append((tc["id"], tc["desc"], str(e)))
            continue

        actual = r.get("needs_help", False)
        match = actual == tc["exp"]
        if match:
            passed += 1
        else:
            failed += 1
            failed_cases.append((tc["id"], tc["desc"], actual, tc["exp"]))

        s = "PASS" if match else "FAIL"
        print(f"\n{'─' * 80}")
        print(f"[#{tc['id']}] {s} | {tc['desc']} | cat={tc['cat']}")
        print(f"  Expected: {tc['exp']} | Actual: {actual}")
        print(f"  Reason: {str(r.get('reason', ''))[:200]}")
        if r.get("synthesized_query"):
            print(f"  Query: {str(r['synthesized_query'])[:200]}")
        if r.get("target_sgs"):
            print(f"  Targets: {r['target_sgs']}")
        results.append({
            "id": tc["id"],
            "desc": tc["desc"],
            "cat": tc["cat"],
            "exp": tc["exp"],
            "actual": actual,
            "match": match,
            "reason": r.get("reason", ""),
        })

    print(f"\n{'=' * 80}\nSUMMARY\n{'=' * 80}")
    print(f"Total: {len(TEST_CASES)} | Passed: {passed} | Failed: {failed}")
    print(f"Pass Rate: {passed / len(TEST_CASES) * 100:.1f}%")
    if failed_cases:
        print("\nFAILED CASES:")
        for item in failed_cases:
            if len(item) == 3:
                print(f"  [#{item[0]}] {item[1]}: {item[2]}")
            else:
                print(f"  [#{item[0]}] {item[1]} | expected={item[2]}, actual={item[3]}")
    print("\nCategory Breakdown:")
    for cat in ["structured_db", "unstructured_doc", "edge_case", "complex_db", "complex_doc", "complex_edge"]:
        cr = [r for r in results if r["cat"] == cat]
        if cr:
            print(f"  {cat}: {sum(1 for r in cr if r['match'])}/{len(cr)} passed")
    out = os.path.join(os.path.dirname(__file__), "mid_exec_detect_test_results.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {out}")


if __name__ == "__main__":
    asyncio.run(main())