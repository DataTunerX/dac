#!/usr/bin/env python3
"""
Pre-Make-Plan + select_best_plan 端到端测试 (真实 LLM, 需网络 + API key)。

测试 routing-agent 在 Simple 模式下, 由 LLM 综合比较多个候选 Agent 的
TaskList (规划质量) 与 Capability Check Report (I/D/O/R/C 五维度评分 +
evidence_strength 实据/推算 + checklist 逐项详情), 选出最优根 Agent。
Prompt 与 routing_agent/server.py 的 _llm_select_best_plan() 保持一致。

共 26 个 Case, 覆盖 12 类测试维度:
  1-3   证据强度极致对比      (全推算 vs 全实据 / 混合强度 / 同分下 D/R 实据数决胜)
  4-6   分数边界与接近值      (相同 confidence 不同 handle_score / 阈值临界 / 极接近 handle_score)
  7-9   多步 vs 单步规划      (规划糙但能力强 / can_handle 优先于多贡献 / 规划粒度合理性)
  10-12 TaskList vs Capability (全推测规划应被否决 / 自洽性差应被惩罚 / 规划都好时 Cap 决胜)
  13-14 缺失需求与风险提示    (透明声明缺失 / 风险透明的可信度权重)
  15-17 Contribute-Only       (贡献步骤多的更优 / 低分 handler 优于高分 contributor / 单候选)
  18-19 约束满足 (C 维度)     (约束覆盖决胜 / 同 solid 但约束量不同)
  20-22 复杂查询/真实场景     (多条件筛选 / 歧义简短查询 / 跨系统集成)
  S1    多候选 (3 个)         (证据质量击败最高 confidence, 属 inflated score)
  S2    矛盾信号              (高分低证据 vs 中分高证据, 虚高自评分应让位)
  S3    speculative I 维度    (单个 I 推算不应淘汰 D/R 坚实的候选)
  S4    重复运行稳定性        (接近场景复跑 5 次, 验证选择一致性而非仅准确率)

用法::

    # 方式一: 环境变量 (推荐用于 CI / 容器)
    export DASHSCOPE_API_KEY=sk-xxxx
    python tests/test_pre_make_plan_selection.py

    # 方式二: 启动参数
    python tests/test_pre_make_plan_selection.py --api-key sk-xxxx

    # 只跑部分 Case, 并把报告写盘
    python tests/test_pre_make_plan_selection.py --case 6 --case S1 --out report.md

作为 pytest 运行时, 每个 Case 生成一个参数化用例。真实 LLM 调用较慢
(约 8-10s/case, S4 因复跑 5 次更久), 默认跳过; 需同时设置启用开关和 key::

    ROUTING_LLM_TESTS=1 DASHSCOPE_API_KEY=sk-xxxx pytest tests/test_pre_make_plan_selection.py

安全说明: API key **不写在源码里**。仅通过 ``--api-key`` 参数或环境变量
(默认 ``DASHSCOPE_API_KEY``, 可用 ``--api-key-env`` 改名) 提供; 缺失时会
直接报错退出, 不会用空 key 静默发起请求。
"""

import argparse
import json
import logging
import os
import sys
import time

from openai import OpenAI

# ══════ config
# 密钥不写在代码里: 通过 --api-key 启动参数或环境变量提供。
# 环境变量名可用 --api-key-env 自定义, 便于 CI / 容器注入。
DEFAULT_API_KEY_ENV = "DASHSCOPE_API_KEY"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "deepseek-v4-flash-0731"

# 非敏感配置: 允许环境变量覆盖 (命令行参数优先级更高, 见 _build_parser)。
API_KEY_ENV = os.getenv("DASHSCOPE_API_KEY_ENV", DEFAULT_API_KEY_ENV)
BASE_URL = os.getenv("DASHSCOPE_BASE_URL", DEFAULT_BASE_URL)
MODEL = os.getenv("DASHSCOPE_MODEL", DEFAULT_MODEL)


class MissingApiKeyError(RuntimeError):
    """未提供 API key 时抛出, 避免静默使用空 key 发起请求。"""


def read_api_key(cli_key=None, env_name=None):
    """按优先级解析 API key: 命令行参数 > 环境变量。

    绝不回退到硬编码默认值 --- 密钥不应出现在源码中。
    """
    if cli_key:
        return cli_key
    env_name = env_name or API_KEY_ENV
    key = os.getenv(env_name)
    if key:
        return key
    raise MissingApiKeyError(
        f"缺少 API key: 请通过 --api-key 传入, 或设置环境变量 {env_name}。"
    )


def build_parser():
    """构造命令行参数解析器。"""
    p = argparse.ArgumentParser(
        prog="test_pre_make_plan_selection.py",
        description="Pre-Make-Plan + select_best_plan 端到端测试 (需真实 LLM)。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--api-key",
        default=None,
        help=f"DashScope API key (优先于环境变量 {DEFAULT_API_KEY_ENV})",
    )
    p.add_argument(
        "--api-key-env",
        default=None,
        help=f"读取 API key 的环境变量名 (默认 {DEFAULT_API_KEY_ENV})",
    )
    p.add_argument("--base-url", default=BASE_URL, help="OpenAI 兼容接口 base url")
    p.add_argument("--model", default=MODEL, help="模型名")
    p.add_argument(
        "--case",
        action="append",
        default=None,
        metavar="ID",
        help="只跑指定 Case (可重复, 如 --case 6 --case S1); 默认跑全部",
    )
    p.add_argument(
        "--out",
        default=None,
        help="额外把 Markdown 报告写入该路径 (默认仅打印到 stdout)",
    )
    return p

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

# ═══════ render helpers (mirror server.py logic)
_SL = {"solid": "实据", "speculative": "推算"}
_OL = {1.0: "可直接执行", 0.7: "可组合完成", 0.0: "不能做"}

def _bcd(req, mat):
    if not req: return "无要求"
    ms = set(mat); limit = 5
    ps = [f"\u2705 {x}" if x in ms else f"\u274c {x}" for x in req[:limit]]
    if len(req) > limit: ps.append(f"...(+{len(req)-limit}项)")
    return "  ".join(ps)

def render_capability_report(name, resp):
    L = [f"#### Agent: {name}"]
    vp = [f"can_handle={resp.get('can_handle',False)}",
          f"can_contribute={resp.get('can_contribute',False)}",
          f"confidence={resp.get('confidence',0):.2f}"]
    eg = resp.get("evidence_grade","?"); vp.append(f"证据等级={eg}")
    hs = resp.get("handle_score",0); vp.append(f"handle_score={hs:.3f}")
    cs = resp.get("contributing_steps",[]); 
    if cs: vp.append(f"可贡献步骤={sorted(cs)}")
    L.append(f"**能力小结**: {' | '.join(vp)}")
    if resp.get("contribution"): L.append(f"> 贡献说明: {resp['contribution']}")
    ms = resp.get("missing_requirements",[]); 
    if ms: L.append(f"> 缺失需求: {', '.join(str(m) for m in ms)}")
    rs = resp.get("risks",[]); 
    if rs: L.append(f"> 风险提示: {'; '.join(str(r) for r in rs[:3])}")
    steps = resp.get("steps",[]); total = len(steps)
    for s in steps:
        if not isinstance(s,dict): continue
        sid = s.get("step_id","?"); desc = str(s.get("description") or s.get("operation") or "").strip()
        op = s.get("operation","?"); fl = "**最终输出**" if s.get("is_final") else "中间步骤"
        cks = s.get("checklists",{}) or {}; scs = s.get("scores",{}) or {}
        ssv = float(s.get("step_score",0) or 0); outs = s.get("outputs",[]) or []
        L.append(f"\n##### 步骤 {sid}/{total}: {desc or '(无描述)'}")
        L.append(f"操作 `{op}` | {fl} | 产出: {outs or '(无)'}")
        L.append(""); L.append("| 维度 | 分 | 强度 | 匹配详情 |")
        L.append("|------|-----|------|----------|")
        for dk,dl in [("I","输入"),("D","数据"),("O","操作"),("R","结果"),("C","约束")]:
            ck = cks.get(dk,{}) or {}
            if dk == "O":
                ov = scs.get("O",0); ot = _OL.get(ov,str(ov))
                L.append(f"| {dk} {dl} | {ov:.1f} | 实据 | {ot} |")
            else:
                st = _SL.get(ck.get("evidence_strength",""),"?")
                req = ck.get("required",[]) or []; mat = ck.get("matched",[]) or []
                if dk == "C" and not req: det = "无约束"
                else: det = _bcd(req,mat)
                L.append(f"| {dk} {dl} | {scs.get(dk,0):.2f} | {st} | {det} |")
        cm = " \u2605可贡献" if sid in cs else ""
        L.append(f"\n\u2192 步骤分: **{ssv:.3f}**{cm}")
        for ev in (s.get("evidence",[]) or [])[:2]: L.append(f"  > 依据: {str(ev)[:200]}")
    return "\n".join(L)

def build_candidates_context(candidates):
    blocks = []; names = []
    for idx,(name,desc,resp,plan) in enumerate(candidates):
        tt = json.dumps(plan.get("tasks",[]), ensure_ascii=False, indent=2)
        cr = render_capability_report(name,resp)
        block = (f"### Candidate {idx+1}: {name}\n\n"
                 f"**Agent Description**: {desc or '(无)'}\n\n---\n\n"
                 f"#### Pre-Make-Plan TaskList (该 Agent 自行规划的任务分解):\n{tt}\n\n---\n\n"
                 f"#### Capability Check Report (能力检查五维度评分明细):\n{cr}")
        blocks.append(block); names.append(name)
    return "\n\n" + ("=" * 60) + "\n\n".join(blocks), names

def build_select_prompt(query, ctx):
    return (
        "你是一个路由评估专家。你的任务是：给定一个用户问题，以及多个候选 Agent 的"
        "**规划（TaskList）** 和 **能力检查报告（Capability Check Report）**，"
        "综合比较，选出最合适的根 Agent。\n\n"
        "请按以下步骤推理（思考过程写入 thought 字段）：\n\n"
        "## Step 1 --- 理解问题\n"
        "用户问题的核心意图是什么？要回答这个问题，必须获取哪些数据或完成哪些操作？\n\n"
        "## Step 2 --- 逐个评估\n"
        "对每个候选 Agent，从两个维度交叉评估：\n\n"
        "### 2a) 规划质量（TaskList）\n"
        "- 覆盖度：规划是否覆盖了 Step 1 中识别的核心需求？有无遗漏或冗余？\n"
        "- 合理性：任务划分粒度是否合适？任务之间的依赖关系是否正确？\n"
        "- 自洽性：每个子任务分配的 agent 与该 Agent 的 description 是否匹配？\n\n"
        "### 2b) 能力实证（Capability Check Report）\n"
        "Capability Check Report 展示了每个 Agent 在 I/D/O/R/C 五个维度的分步评分。"
        "重点关注以下信号：\n"
        "- **证据强度（「实据」vs「推算」）**：\n"
        "  \u00b7「实据」表示该维度的评分来自技能正文的明确声明（字段列表、操作命令、输出格式等）\n"
        "  \u00b7「推算」表示该维度没有明确的文本依据，评分来自 Agent 描述或上下文推断，可信度较低\n"
        "  \u00b7 尤其注意 D（数据覆盖）和 R（结果匹配）维度：如果这两个维度是「推算」，"
        "说明该 Agent 可能并不真正拥有所需的数据字段/输出形态，只是基于领域名称做了推测\n"
        "- **操作能力（O 维度）**：1.0=可直接执行、0.7=可组合完成、0.0=不能做\n"
        "  \u00b7 O=0.7 表示没有现成路径，执行存在不确定性\n"
        "- **逐项匹配详情（\u2705/\u274c 清单）**：看到 \u274c 的项是该 Agent 明确无法覆盖的\n"
        "- **can_handle / confidence / handle_score**：Agent 对自己能否独立完成的自评\n"
        "- **证据等级（A/B/C/D）**：A=全部有文本依据，D=缺乏依据\n"
        "- **可贡献步骤**：Agent 具体能完成哪些子步骤（\u2605可贡献 标记）\n\n"
        "## Step 3 --- 比较与选择\n"
        "横向比较各 Agent，综合规划质量和能力实证选出最优。原则：\n"
        "- 如果两个 Agent 的 TaskList 质量接近，优先选择能力实证更强（实据更多、"
        "confidence 更高、证据等级更高）的那个\n"
        "- 如果一个 Agent 的 TaskList 看起来很完整但 Capability Check 显示"
        "关键维度（D/R）都是「推算」，说明这个规划可能基于不准确的前提\n"
        "- 如果一个 Agent 的 TaskList 看起来简单但 Capability Check 显示"
        "所有维度都是「实据」且有明确的 \u2705 清单，这种更可信\n\n"
        f"用户问题：{query}\n\n"
        f"候选 Agent 的规划与能力报告：\n{ctx}\n\n"
        "请调用 select_best_plan 工具输出你的选择。"
    )

# ═══════ tool-call
SELECT_TOOL = {"type":"function","function":{"name":"select_best_plan",
    "description":"输出最佳 Agent 选择及推理过程",
    "parameters":{"type":"object","properties":{
        "thought":{"type":"string","description":"按 Step1-Step2-Step3 完整推理过程"},
        "selected_agent_index":{"type":"integer","description":"选中的 Agent 编号(1-based)"},
        "reason":{"type":"string","description":"选择理由，一句话总结"}},
        "required":["thought","selected_agent_index","reason"]}}}

def parse_tool_call(resp):
    if not resp or not resp.choices: return None
    msg = resp.choices[0].message
    if not msg.tool_calls: return None
    args = msg.tool_calls[0].function.arguments
    if isinstance(args,str):
        try: return json.loads(args)
        except: return None
    return args if isinstance(args,dict) else {}

def call_dashscope(client, prompt, label=""):
    logger.info("[%s] sending...", label); t0=time.monotonic()
    resp = client.chat.completions.create(model=MODEL,
        messages=[{"role":"system","content":"你是一个路由评估专家。请严格按照要求调用 select_best_plan 工具。"},
                  {"role":"user","content":prompt}],
        tools=[SELECT_TOOL], tool_choice={"type":"function","function":{"name":"select_best_plan"}}, temperature=0.1)
    el=time.monotonic()-t0; r=parse_tool_call(resp)
    if r is None:
        c=resp.choices[0].message.content or ""; logger.warning("[%s] no tool! %s",label,c[:200])
        return {"thought":c,"selected_agent_index":-1,"reason":"LLM未调用tool"}
    logger.info("[%s] %.1fs | idx=%s | %s",label,el,r.get("selected_agent_index"),r.get("reason",""))
    return r

# ═══════ data builders
def mks(sid,desc,op,scores,cks,ss,outs,isf=False,ev=None):
    return {"step_id":sid,"description":desc,"operation":op,"scores":scores,
            "checklists":cks,"step_score":ss,"outputs":outs,"is_final":isf,"evidence":ev or []}
def mkck(req,mat,st="solid"): return {"required":req,"matched":mat,"evidence_strength":st}

# ═══════════════════════════════════════════════════════════════════════════
# Case 1-22: 主套件 --- 8 大类测试维度
# ═══════════════════════════════════════════════════════════════════════════

CASES = []

# ═══ D1: Evidence Strength 极致对比 (1-3) ═══

# Case 1: 全推算 vs 全实据
CASES.append({"id":1, "dim":"证据强度 --- 全推算 vs 全实据",
    "query":"查询供应商列表及联系方式",
    "winner":"SupplierAgent",
    "wreason":"SupplierAgent 全维度 solid, 数据字段及联系方式都有明确声明; VendorAgent D/R 全 speculative 且字段不全, 不可靠.",
    "candidates":[
        ("VendorAgent","供应商管理, 支持查询供应商基本信息",
         {"can_handle":True,"can_contribute":True,"confidence":0.72,"evidence_grade":"C",
          "handle_score":0.576,"contributing_steps":[1],
          "contribution":"可查询供应商列表","missing_requirements":[],
          "risks":["供应商联系方式字段可能不在 Skill 声明中"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"查询供应商列表","list_vendors",
                  {"I":0.8,"D":0.4,"O":1.0,"R":0.5,"C":0.8},
                  {"I":mkck(["查询请求"],["查询请求"]),
                   "D":mkck(["供应商名称","联系人","电话","邮箱","地址"],["供应商名称"],"speculative"),
                   "R":mkck(["供应商列表"],["供应商列表"],"speculative"),
                   "C":mkck(["无特殊约束"],[],"solid")},
                  0.576,["供应商列表(字段不全)"],True,
                  ["Skill 文档未明确列出联系方式字段"])]},
         {"tasks":[{"task_name":"获取供应商列表","agent":"VendorAgent","description":"查询所有供应商及联系方式"}]}),
        ("SupplierAgent","供应商全量数据查询, 包含完整联系方式字段",
         {"can_handle":True,"can_contribute":True,"confidence":0.88,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"直接查询供应商完整信息含联系方式","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"查询供应商完整信息","get_suppliers",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["查询请求"],["查询请求"]),
                   "D":mkck(["供应商名称","联系人","电话","邮箱","地址"],["供应商名称","联系人","电话","邮箱","地址"]),
                   "R":mkck(["供应商列表(含完整联系方式)"],["供应商列表(含完整联系方式)"]),
                   "C":mkck(["无特殊约束"],[])},
                  0.960,["供应商列表(含完整联系方式)"],True,
                  ["Skill 文档明确声明 get_suppliers 返回 name/contact/phone/email/address 全字段"])]},
         {"tasks":[{"task_name":"查询供应商","agent":"SupplierAgent","description":"查询所有供应商及完整联系方式"}]})]}),

# Case 2: 混合强度 --- I/O 实据但 D/R/C 推算 vs I/D/R/C 全实据但 O=0.7
CASES.append({"id":2, "dim":"证据强度 --- 混合强度对比",
    "query":"统计各大区的销售额排名",
    "winner":"RegionSalesAgent",
    "wreason":"RegionSalesAgent 虽然 O=0.7, 但 D/R 全是实据, 能明确告诉你有没有大区维度和榜单输出格式; AreaAgent 的 D/R/C 全部推算, 数据可靠性存疑.",
    "candidates":[
        ("AreaAgent","区域销售数据查询",
         {"can_handle":True,"can_contribute":True,"confidence":0.80,"evidence_grade":"B",
          "handle_score":0.640,"contributing_steps":[1],
          "contribution":"可查询区域销售数据","missing_requirements":[],
          "risks":["大区维度字段未确认"],"score_version":"capability-chain-v1","steps":[
              mks(1,"统计各大区销售额","area_sales",
                  {"I":1.0,"D":0.4,"O":1.0,"R":0.4,"C":0.5},
                  {"I":mkck(["时间段"],["时间段"]),
                   "D":mkck(["大区ID","大区名称","销售额","订单量"],["大区ID"],"speculative"),
                   "R":mkck(["按大区排名列表"],["列表"],"speculative"),
                   "C":mkck(["按销售额降序"],["按销售额降序"],"speculative")},
                  0.640,["销售额列表(字段不确定)"],True,
                  ["Skill 未列出大区维度的具体字段和排名逻辑"])]},
         {"tasks":[{"task_name":"查询大区销售","agent":"AreaAgent","description":"查询各大区销售额数据并排名"}]}),
        ("RegionSalesAgent","大区销售额统计与排行, 包含完整区域维度和榜单输出",
         {"can_handle":True,"can_contribute":True,"confidence":0.75,"evidence_grade":"A",
          "handle_score":0.700,"contributing_steps":[1],
          "contribution":"可按大区维度排序输出销售额榜单","missing_requirements":[],
          "risks":["需要组合 ranking 子模块来排序"],"score_version":"capability-chain-v1","steps":[
              mks(1,"统计各大区销售额排名","region_sales_rank",
                  {"I":1.0,"D":1.0,"O":0.7,"R":1.0,"C":0.8},
                  {"I":mkck(["时间段"],["时间段"]),
                   "D":mkck(["大区ID","大区名称","销售额","订单量"],["大区ID","大区名称","销售额","订单量"]),
                   "R":mkck(["按大区排名列表(降序)","榜单图表"],["按大区排名列表(降序)","榜单图表"]),
                   "C":mkck(["按销售额降序","TOP10"],["按销售额降序","TOP10"])},
                  0.700,["大区销售额排名榜单","榜单图表"],True,
                  ["Skill 明确声明 region_sales_rank 方法, 输入 time_range, 返回 region_id/name/sales/orders 及 ranking 列表, 但需组合 ranking 子模块(O=0.7)"])]},
         {"tasks":[{"task_name":"大区销售统计","agent":"RegionSalesAgent","description":"查询大区销售数据并调用 ranking 模块按销售额降序排列"}]})]}),

# Case 3: 同 confidence 同 evidence_grade, D/R 实据数不同
CASES.append({"id":3, "dim":"证据强度 --- 同分下 D/R 实据数决胜",
    "query":"列出所有客户的信用等级",
    "winner":"CreditAgent",
    "wreason":"两个 Agent 都是 can_handle/confidence=0.80/evidence=B, 但 CreditAgent 的 D/R 全是 solid(4项字段/输出全 \u2705), CustomerAgent D/R 都是 speculative(不确认是否有信用字段), handle_score 差距不大但数据可靠性差异明显.",
    "candidates":[
        ("CustomerAgent","客户信息管理, 支持查询客户基本信息和状态",
         {"can_handle":True,"can_contribute":True,"confidence":0.80,"evidence_grade":"B",
          "handle_score":0.640,"contributing_steps":[1],
          "contribution":"可查询客户列表","missing_requirements":[],
          "risks":["信用等级字段不确定"],"score_version":"capability-chain-v1","steps":[
              mks(1,"列出客户信用等级","list_customer_credit",
                  {"I":1.0,"D":0.4,"O":1.0,"R":0.5,"C":0.8},
                  {"I":mkck(["查询请求"],["查询请求"]),
                   "D":mkck(["客户名称","客户ID","信用等级","信用额度"],["客户名称","客户ID"],"speculative"),
                   "R":mkck(["客户信用等级列表"],["列表"],"speculative"),
                   "C":mkck(["无特殊约束"],[])},
                  0.640,["客户列表(信用字段不确定)"],True,
                  ["Skill 声明客户查询功能但信用等级字段未明确列出"])]},
         {"tasks":[{"task_name":"查询客户","agent":"CustomerAgent","description":"获取所有客户及其信用等级"}]}),
        ("CreditAgent","客户信用等级管理, 持有完整的信用评分和等级数据",
         {"can_handle":True,"can_contribute":True,"confidence":0.80,"evidence_grade":"B",
          "handle_score":0.800,"contributing_steps":[1],
          "contribution":"直接查询客户信用等级含完整字段","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"列出客户信用等级","get_credit_ratings",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["查询请求"],["查询请求"]),
                   "D":mkck(["客户名称","客户ID","信用等级","信用额度"],["客户名称","客户ID","信用等级","信用额度"]),
                   "R":mkck(["客户信用等级列表(含等级和额度)"],["客户信用等级列表(含等级和额度)"]),
                   "C":mkck(["无特殊约束"],[])},
                  0.800,["客户信用等级列表(完整字段)"],True,
                  ["Skill 明确声明 get_credit_ratings 返回 customer_name/id/rating/credit_limit"])]},
         {"tasks":[{"task_name":"信用查询","agent":"CreditAgent","description":"获取所有客户信用等级和信用额度"}]})]}),

# ═══ D2: 分数边界与接近值 (4-6) ═══

# Case 4: 相同 confidence 不同 handle_score
CASES.append({"id":4, "dim":"分数边界 --- 相同 confidence 不同 handle_score",
    "query":"导出上季度的财务报表",
    "winner":"FinanceReportAgent",
    "wreason":"两个 Agent confidence 相同(0.82), 但 FinanceReportAgent handle_score=0.950 >> ReportHubAgent 0.656, 且 D/C 全 solid, \u2705 覆盖更多, 应按 handle_score 和证据质量决胜.",
    "candidates":[
        ("ReportHubAgent","报表中心, 支持多种报表模板导出",
         {"can_handle":True,"can_contribute":True,"confidence":0.82,"evidence_grade":"B",
          "handle_score":0.656,"contributing_steps":[1],
          "contribution":"可导出报表","missing_requirements":[],
          "risks":["金融科目字段不全"],"score_version":"capability-chain-v1","steps":[
              mks(1,"导出上季度财务报表","export_report",
                  {"I":1.0,"D":0.4,"O":1.0,"R":0.6,"C":0.5},
                  {"I":mkck(["时间范围(上季度)"],["时间范围(上季度)"]),
                   "D":mkck(["营收","成本","利润","现金流","资产负债"],["营收","利润"],"speculative"),
                   "R":mkck(["财务报表 PDF/Excel"],["财务报表"],"speculative"),
                   "C":mkck(["符合会计准则格式"],[],"speculative")},
                  0.656,["财务报表(字段不全)"],True,
                  ["Skill 支持报表导出但财务科目字段不完整"])]},
         {"tasks":[{"task_name":"导出报表","agent":"ReportHubAgent","description":"按上季度导出财务报表"}]}),
        ("FinanceReportAgent","财务报表专用生成器, 涵盖全部会计科目和准则格式",
         {"can_handle":True,"can_contribute":True,"confidence":0.82,"evidence_grade":"A",
          "handle_score":0.950,"contributing_steps":[1],
          "contribution":"一站式生成符合会计准则的完整财务报表","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"导出上季度财务报表","gen_finance_report",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["时间范围(上季度)"],["时间范围(上季度)"]),
                   "D":mkck(["营收","成本","利润","现金流","资产负债"],["营收","成本","利润","现金流","资产负债"]),
                   "R":mkck(["财务报表 PDF/Excel(含三张表)"],["财务报表 PDF/Excel(含三张表)"]),
                   "C":mkck(["符合会计准则格式"],["符合会计准则格式"])},
                  0.950,["财务报表 PDF/Excel(含资产负债表/利润表/现金流量表)"],True,
                  ["Skill 明确声明 gen_finance_report 方法, 输出 BS/IS/CF 三张表, 符合 IFRS/GAAP 格式"])]},
         {"tasks":[{"task_name":"生成财报","agent":"FinanceReportAgent","description":"生成上季度的三张财务报表并导出"}]})]}),

# Case 5: 阈值临界 --- confidence 0.71 vs 0.69
CASES.append({"id":5, "dim":"分数边界 --- 阈值临界值对比",
    "query":"更新商品的促销价格",
    "winner":"PriceMgmtAgent",
    "wreason":"PriceMgmtAgent 虽然 confidence 仅 0.71(刚过阈值), 但 D/O/R 全 solid; PromoAgent confidence 0.69 且 D/R 都是 speculative(不确认批量更新能力). handle_score 0.710 >> 0.069(因 speculative D/R 权重降低到0.1).",
    "candidates":[
        ("PromoAgent","促销管理, 支持促销活动配置",
         {"can_handle":True,"can_contribute":True,"confidence":0.69,"evidence_grade":"C",
          "handle_score":0.069,"contributing_steps":[1],
          "contribution":"可配置促销活动","missing_requirements":[],
          "risks":["批量更新价格的能力不明确","促销价格字段可能不包含在 Skill 数据模型中"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"更新商品促销价格","set_promo_price",
                  {"I":1.0,"D":0.1,"O":0.7,"R":0.1,"C":0.5},
                  {"I":mkck(["商品ID","促销价格"],["商品ID","促销价格"]),
                   "D":mkck(["商品信息","原价","促销价","促销时段"],["商品信息"],"speculative"),
                   "R":mkck(["更新确认"],["确认"],"speculative"),
                   "C":mkck(["促销价格 < 原价"],[],"speculative")},
                  0.069,["更新结果(不确定)"],True,
                  ["Skill 声明促销配置但数据模型不含价格字段, D/R 均为推测"])]},
         {"tasks":[{"task_name":"设定促销价","agent":"PromoAgent","description":"为指定商品设置促销价格"}]}),
        ("PriceMgmtAgent","商品价格管理系统, 支持单品/批量调价含验证逻辑",
         {"can_handle":True,"can_contribute":True,"confidence":0.71,"evidence_grade":"B",
          "handle_score":0.710,"contributing_steps":[1],
          "contribution":"可直接更新商品价格含验证","missing_requirements":[],
          "risks":["批量操作锁粒度待确认"],"score_version":"capability-chain-v1","steps":[
              mks(1,"更新商品促销价格","update_price",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.5},
                  {"I":mkck(["商品ID","促销价格"],["商品ID","促销价格"]),
                   "D":mkck(["商品信息","原价","促销价","促销时段"],["商品信息","原价","促销价"]),
                   "R":mkck(["更新确认","操作日志"],["更新确认","操作日志"]),
                   "C":mkck(["促销价格 < 原价"],["促销价格 < 原价"])},
                  0.710,["价格更新确认 + 操作日志"],True,
                  ["Skill 声明 update_price 方法, 支持验证促销价<原价"])]},
         {"tasks":[{"task_name":"更新价格","agent":"PriceMgmtAgent","description":"更新指定商品的促销价格并验证"}]})]}),

# Case 6: 极接近 handle_score --- 0.855 vs 0.850
CASES.append({"id":6, "dim":"分数边界 --- 极接近的 handle_score",
    "query":"查询物流单号的实时位置",
    "winner":"LogisticsAgent",
    "wreason":"handle_score 极接近(0.855 vs 0.850), 但 LogisticsAgent 证据等级 A > B, 且 D(物流节点字段)全部 \u2705(含时间戳/位置/状态), TrackAgent 缺揽收时间. TaskList 相当的情况下证据等级和 checklist 覆盖决胜.",
    "candidates":[
        ("TrackAgent","物流追踪, 支持查询包裹状态",
         {"can_handle":True,"can_contribute":True,"confidence":0.85,"evidence_grade":"B",
          "handle_score":0.850,"contributing_steps":[1],
          "contribution":"可查询物流轨迹","missing_requirements":[],
          "risks":["实时位置更新频率待确认"],"score_version":"capability-chain-v1","steps":[
              mks(1,"查询物流实时位置","track_package",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["物流单号"],["物流单号"]),
                   "D":mkck(["当前位置","运输节点","时间戳","揽收时间","预计到达"],["当前位置","运输节点","时间戳","预计到达"]),
                   "R":mkck(["物流轨迹地图","节点列表"],["物流轨迹地图","节点列表"]),
                   "C":mkck(["实时数据"],["实时数据"])},
                  0.850,["物流轨迹地图 + 节点列表"],True,
                  ["Skill 声明 track_package, D 缺揽收时间字段"])]},
         {"tasks":[{"task_name":"物流追踪","agent":"TrackAgent","description":"根据单号查询包裹实时位置和轨迹"}]}),
        ("LogisticsAgent","全链路物流查询平台, 含实时位置和全节点时间线",
         {"can_handle":True,"can_contribute":True,"confidence":0.85,"evidence_grade":"A",
          "handle_score":0.855,"contributing_steps":[1],
          "contribution":"查询物流全轨迹含实时位置和完整时间线","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"查询物流实时位置","get_logistics_trace",
                  {"I":1.0,"D":1.0,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["物流单号"],["物流单号"]),
                   "D":mkck(["当前位置","运输节点","时间戳","揽收时间","预计到达"],["当前位置","运输节点","时间戳","揽收时间","预计到达"]),
                   "R":mkck(["物流轨迹地图","节点列表","实时推送"],["物流轨迹地图","节点列表"]),
                   "C":mkck(["实时数据"],["实时数据"])},
                  0.855,["物流轨迹地图 + 节点列表(实时)"],True,
                  ["Skill 明确声明 get_logistics_trace, full node timeline with pickup_time/estimated_arrival"])]},
         {"tasks":[{"task_name":"物流追踪","agent":"LogisticsAgent","description":"根据单号获取实时位置和完整轨迹"}]})]}),

# ═══ D3: 多步 vs 单步规划 (7-9) ═══

# Case 7: 多步规划质量好 + 能力中 vs 单步规划糙 + 能力高
CASES.append({"id":7, "dim":"多步 vs 单步 --- 规划糙但能力强应胜",
    "query":"统计本月每个客服的工单处理量和满意度评分",
    "winner":"CSDashboardAgent",
    "wreason":"ServiceAgent 规划了 3 步看起来很完善, 但 D/R 都是 speculative(不确认有没有满意度字段); CSDashboardAgent 规划只有 1 步但全维度 solid、handle_score=0.96. 规划不可靠(推测数据)比规划简单更危险.",
    "candidates":[
        ("ServiceAgent","客服工单管理, 支持工单查询和统计",
         {"can_handle":True,"can_contribute":True,"confidence":0.74,"evidence_grade":"C",
          "handle_score":0.525,"contributing_steps":[1,2],
          "contribution":"可统计工单量","missing_requirements":["满意度评分数据可能不在工单表中"],
          "risks":["满意度字段未明确声明"],"score_version":"capability-chain-v1","steps":[
              mks(1,"统计各客服工单量","count_tickets",
                  {"I":1.0,"D":0.6,"O":1.0,"R":0.6,"C":0.8},
                  {"I":mkck(["时间段(本月)","客服维度"],["时间段(本月)","客服维度"]),
                   "D":mkck(["客服ID","客服名称","工单数","满意度"],["客服ID","客服名称","工单数"],"speculative"),
                   "R":mkck(["按客服统计表"],["统计表"],"speculative"),
                   "C":mkck(["本月数据"],["本月数据"])},
                  0.750,["工单量统计表"],False,["Skill 声明工单统计但满意度字段未确认"]),
              mks(2,"统计满意度评分","calc_satisfaction",
                  {"I":0.8,"D":0.1,"O":0.7,"R":0.1,"C":0.5},
                  {"I":mkck(["工单数据"],["工单数据"]),
                   "D":mkck(["满意度评分","评分时间"],[],"speculative"),
                   "R":mkck(["满意度评分汇总"],[],"speculative"),
                   "C":mkck(["含评分完成时间"],[],"speculative")},
                  0.003,["(不能产出)"],True,["Skill 无满意度数据源, D/R 均为推测"])]},
         {"tasks":[
             {"task_name":"统计工单量","agent":"ServiceAgent","description":"按客服维度统计本月工单处理量"},
             {"task_name":"统计满意度","agent":"ServiceAgent","description":"按客服统计满意度平均分"},
             {"task_name":"汇总输出","agent":"ServiceAgent","description":"合并工单量和满意度为最终报表"}]}),
        ("CSDashboardAgent","客服数据看板, 集成工单量/满意度/响应时间等全维度指标",
         {"can_handle":True,"can_contribute":True,"confidence":0.92,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"一站式输出客服绩效看板含工单量和满意度","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"统计客服绩效","cs_dashboard",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["时间段(本月)","客服维度"],["时间段(本月)","客服维度"]),
                   "D":mkck(["客服ID","客服名称","工单数","满意度","响应时间"],["客服ID","客服名称","工单数","满意度","响应时间"]),
                   "R":mkck(["客服绩效看板(含工单量和满意度)"],["客服绩效看板(含工单量和满意度)"]),
                   "C":mkck(["本月数据"],["本月数据"])},
                  0.960,["客服绩效看板"],True,
                  ["Skill 声明 cs_dashboard 方法集成 ticket_count/satisfaction/response_time 全指标"])]},
         {"tasks":[{"task_name":"客服看板","agent":"CSDashboardAgent","description":"生成本月客服绩效看板(工单量+满意度)"}]})]}),

# Case 8: can_handle 单步 vs can_contribute 多步
CASES.append({"id":8, "dim":"多步 vs 单步 --- can_handle 优先于多贡献",
    "query":"批量导入用户数据并校验格式",
    "winner":"DataImportAgent",
    "wreason":"DataImportAgent can_handle=True 可直接完成导入+校验; ETLAgent can_handle=False 只能 contribute 步骤1(解析), 步骤2(校验) O=0.0 不能做. can_handle 优于多步 can_contribute.",
    "candidates":[
        ("ETLAgent","数据 ETL 工具, 支持数据解析和格式转换",
         {"can_handle":False,"can_contribute":True,"confidence":0.72,"evidence_grade":"B",
          "handle_score":0.0,"contributing_steps":[1],
          "contribution":"可解析 CSV/Excel 数据","missing_requirements":["数据校验规则引擎(步骤2)"],
          "risks":["校验能力不足"],"score_version":"capability-chain-v1","steps":[
              mks(1,"解析导入文件","parse_file",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["文件路径","文件格式"],["文件路径","文件格式"]),
                   "D":mkck(["CSV/Excel 列名和数据行"],["CSV/Excel 列名和数据行"]),
                   "R":mkck(["解析后的数据表"],["解析后的数据表"]),
                   "C":mkck(["文件大小<100MB"],["文件大小<100MB"])},
                  0.850,["解析后的数据表"],False,["Skill 支持 CSV/Excel 解析"]),
              mks(2,"校验数据格式","validate_data",
                  {"I":1.0,"D":0.2,"O":0.0,"R":0.1,"C":0.3},
                  {"I":mkck(["数据表"],["数据表"]),
                   "D":mkck(["校验规则","字段类型定义"],[],"speculative"),
                   "R":mkck(["校验报告","有效数据","异常数据"],[],"speculative"),
                   "C":mkck(["必填字段校验","格式校验","唯一性校验"],[],"speculative")},
                  0.001,["(不能产出)"],True,["Skill 不具备数据校验能力"])]},
         {"tasks":[
             {"task_name":"解析文件","agent":"ETLAgent","description":"解析上传的 CSV/Excel 文件"},
             {"task_name":"校验数据","agent":"ValidationAgent","description":"调用校验引擎验证数据格式和字段"}]}),
        ("DataImportAgent","数据导入平台, 含文件解析+格式校验+入库全流程",
         {"can_handle":True,"can_contribute":True,"confidence":0.88,"evidence_grade":"A",
          "handle_score":0.920,"contributing_steps":[1],
          "contribution":"一站式完成文件解析、格式校验和数据入库","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"批量导入并校验数据","import_with_validation",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["文件路径","文件格式","目标表"],["文件路径","文件格式","目标表"]),
                   "D":mkck(["文件内容"],["文件内容"]),
                   "R":mkck(["导入报告(含校验结果和入库统计)"],["导入报告(含校验结果和入库统计)"]),
                   "C":mkck(["必填字段校验","格式校验","唯一性校验","文件大小<100MB"],["必填字段校验","格式校验","唯一性校验","文件大小<100MB"])},
                  0.920,["导入报告(解析+校验+入库全流程)"],True,
                  ["Skill 声明 import_with_validation 方法集成 parse/validate/insert 全流程, 含字段类型/唯一性/必填校验"])]},
         {"tasks":[{"task_name":"导入数据","agent":"DataImportAgent","description":"批量导入用户数据并自动校验格式后入库"}]})]}),

# Case 9: 规划粒度合理性对比
CASES.append({"id":9, "dim":"多步 vs 单步 --- 规划粒度合理性对比",
    "query":"发送营销邮件给所有 VIP 客户",
    "winner":"CampaignAgent",
    "wreason":"CampaignAgent 规划 2 步(筛选+发送), 粒度合理且自洽; MassMailAgent 规划 5 步但在步骤3分配给了一个不存在的 TemplateAgent, 自洽性差; 且 MassMailAgent 的 D/R speculative, 不确认模板和追踪字段.",
    "candidates":[
        ("MassMailAgent","批量邮件发送, 支持模板和追踪",
         {"can_handle":True,"can_contribute":True,"confidence":0.72,"evidence_grade":"C",
          "handle_score":0.504,"contributing_steps":[1],
          "contribution":"可发送批量邮件","missing_requirements":[],
          "risks":["邮件模板系统不确定","打开率追踪字段未确认"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"发送营销邮件","send_campaign_email",
                  {"I":0.8,"D":0.3,"O":1.0,"R":0.4,"C":0.6},
                  {"I":mkck(["客户列表","邮件内容"],["客户列表","邮件内容"]),
                   "D":mkck(["客户邮箱","姓名","VIP标识"],["客户邮箱","姓名"],"speculative"),
                   "R":mkck(["发送报告","打开率"],["发送报告"],"speculative"),
                   "C":mkck(["仅VIP客户"],["仅VIP客户"],"speculative")},
                  0.504,["发送报告(缺少追踪)"],True,
                  ["Skill 声明邮件发送但未列出 VIP 筛选和追踪字段"])]},
         {"tasks":[
             {"task_name":"获取客户列表","agent":"MassMailAgent","description":"获取所有客户信息"},
             {"task_name":"筛选VIP客户","agent":"MassMailAgent","description":"筛选 VIP 标签客户"},
             {"task_name":"生成邮件模板","agent":"TemplateAgent","description":"生成营销邮件模板"},
             {"task_name":"批量发送","agent":"MassMailAgent","description":"向 VIP 客户批量发送邮件"},
             {"task_name":"统计效果","agent":"MassMailAgent","description":"统计发送成功率和打开率"}]}),
        ("CampaignAgent","营销活动管理平台, 集成客户分群、模板渲染、批量发送和效果追踪",
         {"can_handle":True,"can_contribute":True,"confidence":0.90,"evidence_grade":"A",
          "handle_score":0.950,"contributing_steps":[1],
          "contribution":"一站式完成 VIP 筛选、模板生成、批量发送和效果追踪","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"发送营销邮件给 VIP","campaign_send",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["客户群体(VIP)","邮件内容"],["客户群体(VIP)","邮件内容"]),
                   "D":mkck(["客户邮箱","姓名","VIP标识","模板ID","追踪ID"],["客户邮箱","姓名","VIP标识","模板ID","追踪ID"]),
                   "R":mkck(["发送报告","打开率","点击率","退订率"],["发送报告","打开率","点击率","退订率"]),
                   "C":mkck(["仅VIP客户","发送频率限制"],["仅VIP客户","发送频率限制"])},
                  0.950,["营销邮件发送报告(含效果追踪)"],True,
                  ["Skill 声明 campaign_send 方法, 集成 segment/template/send/track 全链路"])]},
         {"tasks":[
             {"task_name":"筛选并发送","agent":"CampaignAgent","description":"筛选VIP客户后生成模板并发送营销邮件"},
             {"task_name":"效果追踪","agent":"CampaignAgent","description":"统计打开率和点击率"}]})]}),

# ═══ D4: TaskList 质量 vs Capability 权重 (10-12) ═══

# Case 10: 全推测规划应被否决
CASES.append({"id":10, "dim":"TaskList vs Cap --- 全推测规划应被否决",
    "query":"分析网站流量来源分布并给出优化建议",
    "winner":"AnalyticsProAgent",
    "wreason":"TrafficAgent 规划了 4 步看起来很专业(采集-清洗-分析-建议), 但 D/R 全是 speculative(不确认有流量来源字段和 AI 建议能力)---本质是一份基于猜测的规划; AnalyticsProAgent 规划只有 1 步但全 solid, 明确有渠道/来源/转化等字段和 AI 分析引擎.",
    "candidates":[
        ("TrafficAgent","网站流量分析工具, 支持数据统计",
         {"can_handle":True,"can_contribute":True,"confidence":0.68,"evidence_grade":"D",
          "handle_score":0.038,"contributing_steps":[1],
          "contribution":"可做基础流量统计","missing_requirements":["流量来源维度数据","AI分析引擎"],
          "risks":["数据字段不完整","无优化建议能力"],"score_version":"capability-chain-v1","steps":[
              mks(1,"采集流量数据","collect_traffic",
                  {"I":0.8,"D":0.2,"O":1.0,"R":0.2,"C":0.6},
                  {"I":mkck(["站点ID","时间范围"],["站点ID","时间范围"]),
                   "D":mkck(["PV","UV","来源渠道","地域"],["PV","UV"],"speculative"),
                   "R":mkck(["流量数据表"],["数据表"],"speculative"),
                   "C":mkck(["近30天"],["近30天"])},
                  0.150,["流量数据表(字段不全)"],False,["Skill 声明基础统计但缺少来源渠道字段"]),
              mks(2,"清洗和分类","classify_traffic",
                  {"I":1.0,"D":0.1,"O":0.7,"R":0.1,"C":0.3},
                  {"I":mkck(["流量数据"],["流量数据"]),
                   "D":mkck(["渠道分类规则","来源标签"],[],"speculative"),
                   "R":mkck(["分类后数据"],[],"speculative"),
                   "C":mkck(["标准渠道分类"],[],"speculative")},
                  0.003,["(不能产出)"],False,["Skill 无渠道分类能力"]),
              mks(3,"分析来源分布","analyze_source",
                  {"I":0.8,"D":0.1,"O":0.0,"R":0.1,"C":0.3},
                  {"I":mkck(["分类数据"],[],"speculative"),
                   "D":mkck(["来源占比","转化率","跳出率"],[],"speculative"),
                   "R":mkck(["来源分布报告"],[],"speculative"),
                   "C":mkck(["含可视化图表"],[],"speculative")},
                  0.000,["(不能产出)"],True,["Skill 完全不支持来源分析"])]},
         {"tasks":[
             {"task_name":"数据采集","agent":"TrafficAgent","description":"采集近30天网站流量数据"},
             {"task_name":"数据清洗","agent":"TrafficAgent","description":"清洗和标准化流量数据"},
             {"task_name":"来源分析","agent":"TrafficAgent","description":"分析各渠道流量占比和转化"},
             {"task_name":"优化建议","agent":"TrafficAgent","description":"基于分析结果给出流量优化建议"}]}),
        ("AnalyticsProAgent","专业网站分析平台, 集成全维度流量追踪和 AI 分析引擎",
         {"can_handle":True,"can_contribute":True,"confidence":0.92,"evidence_grade":"A",
          "handle_score":0.950,"contributing_steps":[1],
          "contribution":"一站式完成流量来源分析和优化建议生成","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"分析流量来源并给出建议","traffic_insight",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["站点ID","时间范围"],["站点ID","时间范围"]),
                   "D":mkck(["PV","UV","来源渠道","地域","设备","转化率","跳出率"],["PV","UV","来源渠道","地域","设备","转化率","跳出率"]),
                   "R":mkck(["来源分布报告","AI优化建议"],["来源分布报告","AI优化建议"]),
                   "C":mkck(["近30天","含可视化图表"],["近30天","含可视化图表"])},
                  0.950,["流量来源分布报告 + AI优化建议"],True,
                  ["Skill 声明 traffic_insight 方法, 集成 GA/GTM 数据源和 AI suggestion engine"])]},
         {"tasks":[{"task_name":"流量分析","agent":"AnalyticsProAgent","description":"分析近30天网站流量来源并生成优化建议"}]})]}),

# Case 11: 自洽性差的规划应被惩罚
CASES.append({"id":11, "dim":"TaskList vs Cap --- 自洽性差的规划应被惩罚",
    "query":"处理退款申请并更新库存",
    "winner":"RefundMgmtAgent",
    "wreason":"OrderAgent 规划中把更新库存分配给自己, 但 Cap Check 显示 D/R speculative(不确认是否关联库存表), 自洽性差; RefundMgmtAgent 集成退款+库存回滚全流程且全部 solid, evidence=A.",
    "candidates":[
        ("OrderAgent","订单管理, 支持退款处理",
         {"can_handle":True,"can_contribute":True,"confidence":0.72,"evidence_grade":"C",
          "handle_score":0.640,"contributing_steps":[1],
          "contribution":"可处理退款","missing_requirements":[],
          "risks":["库存回滚字段不确认"],"score_version":"capability-chain-v1","steps":[
              mks(1,"处理退款","process_refund",
                  {"I":1.0,"D":0.5,"O":1.0,"R":0.6,"C":0.8},
                  {"I":mkck(["订单ID","退款原因"],["订单ID","退款原因"]),
                   "D":mkck(["订单详情","支付信息","库存量","SKU"],["订单详情","支付信息"],"speculative"),
                   "R":mkck(["退款确认","库存更新确认"],["退款确认"],"speculative"),
                   "C":mkck(["退款金额=实付金额"],["退款金额=实付金额"])},
                  0.640,["退款确认(库存不确定)"],True,
                  ["Skill 声明退款处理但库存表关联未确认"])]},
         {"tasks":[
             {"task_name":"处理退款","agent":"OrderAgent","description":"审核退款申请并执行退款"},
             {"task_name":"更新库存","agent":"OrderAgent","description":"退款后将商品库存+1"}]}),
        ("RefundMgmtAgent","退款管理系统, 集成退款审批、支付回退和库存回滚",
         {"can_handle":True,"can_contribute":True,"confidence":0.90,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"一站式完成退款+库存回滚","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"处理退款并更新库存","full_refund",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["订单ID","退款原因"],["订单ID","退款原因"]),
                   "D":mkck(["订单详情","支付信息","库存量","SKU","退款金额"],["订单详情","支付信息","库存量","SKU","退款金额"]),
                   "R":mkck(["退款确认","库存更新确认","退款流水号"],["退款确认","库存更新确认","退款流水号"]),
                   "C":mkck(["退款金额=实付金额","库存+商品数量"],["退款金额=实付金额","库存+商品数量"])},
                  0.960,["退款处理结果 + 库存回滚确认"],True,
                  ["Skill 声明 full_refund 方法集成 refund/inventory_rollback, 操作退款表+库存表"])]},
         {"tasks":[{"task_name":"退款处理","agent":"RefundMgmtAgent","description":"处理退款申请并同步回滚库存"}]})]}),

# Case 12: 规划都好时 Cap 决胜
CASES.append({"id":12, "dim":"TaskList vs Cap --- 规划都好时 Cap 决胜",
    "query":"对用户上传的图片进行内容审核和安全检查",
    "winner":"SafetyScanAgent",
    "wreason":"两个 Agent 的 TaskList 都合理(接收-审核-返回), 但 SafetyScanAgent C 维度 5 项全部 \u2705(含敏感词/色情/暴力/政治/违规图文), ImageModAgent C 维度 5 项只有 2 项 \u2705. handle_score 0.96 >> 0.576.",
    "candidates":[
        ("ImageModAgent","图片内容审核, 支持基础违规检测",
         {"can_handle":True,"can_contribute":True,"confidence":0.72,"evidence_grade":"B",
          "handle_score":0.576,"contributing_steps":[1],
          "contribution":"可做基础图片审核","missing_requirements":[],
          "risks":["审核维度不全面, 仅覆盖部分违规类型"],"score_version":"capability-chain-v1","steps":[
              mks(1,"审核图片内容","moderate_image",
                  {"I":1.0,"D":0.6,"O":1.0,"R":0.6,"C":0.4},
                  {"I":mkck(["图片文件"],["图片文件"]),
                   "D":mkck(["图片元信息","OCR文本","特征向量"],["图片元信息"]),
                   "R":mkck(["审核结果(通过/违规)"],["审核结果(通过/违规)"]),
                   "C":mkck(["敏感词检测","色情识别","暴力识别","政治敏感","违规图文"],["色情识别","暴力识别"],"speculative")},
                  0.576,["审核结果(覆盖不全)"],True,
                  ["Skill 声明基础审核但违规类型仅部分覆盖"])]},
         {"tasks":[
             {"task_name":"接收图片","agent":"ImageModAgent","description":"接收并预处理用户上传的图片"},
             {"task_name":"内容审核","agent":"ImageModAgent","description":"对图片进行 OCR 和特征检测"},
             {"task_name":"返回结果","agent":"ImageModAgent","description":"返回审核结果和违规详情"}]}),
        ("SafetyScanAgent","全维度内容安全扫描平台, 覆盖文本/图片/视频多模态审核",
         {"can_handle":True,"can_contribute":True,"confidence":0.92,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"全维度图片内容安全审核","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"图片内容安全审核","safety_scan",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["图片文件"],["图片文件"]),
                   "D":mkck(["图片元信息","OCR文本","特征向量","相似度"],["图片元信息","OCR文本","特征向量","相似度"]),
                   "R":mkck(["审核报告(含违规类型和置信度)"],["审核报告(含违规类型和置信度)"]),
                   "C":mkck(["敏感词检测","色情识别","暴力识别","政治敏感","违规图文"],["敏感词检测","色情识别","暴力识别","政治敏感","违规图文"])},
                  0.960,["审核报告(全维度)"],True,
                  ["Skill 声明 safety_scan 集成 5 类违规检测引擎"])]},
         {"tasks":[
             {"task_name":"接收图片","agent":"SafetyScanAgent","description":"接收用户上传的图片"},
             {"task_name":"安全扫描","agent":"SafetyScanAgent","description":"对图片进行全维度内容安全审核"},
             {"task_name":"返回报告","agent":"SafetyScanAgent","description":"返回审核报告含违规类型和置信度"}]})]}),

# ═══ D5: 缺失需求与风险提示 (13-14) ═══

# Case 13: 有明确 missing_requirements vs 没有但 confidence 低
CASES.append({"id":13, "dim":"缺失需求 --- 透明声明 vs 悄悄隐藏",
    "query":"生成员工的月度考勤报表",
    "winner":"HRAgent",
    "wreason":"AttendanceAgent 虽然 confidence 0.78 但明确 missing_requirements 包含假期/加班数据, 无法独立完成; HRAgent 集成考勤+假期+加班全维度, confidence 0.9 且全部 solid. 透明声明缺失不一定就要被选, 但说明其能力缺口确实存在.",
    "candidates":[
        ("AttendanceAgent","考勤管理, 支持打卡记录查询",
         {"can_handle":False,"can_contribute":True,"confidence":0.78,"evidence_grade":"B",
          "handle_score":0.0,"contributing_steps":[1],
          "contribution":"可统计打卡记录","missing_requirements":["假期/加班数据(步骤2)","报表格式化引擎"],
          "risks":["无法区分请假缺勤和旷工"],"score_version":"capability-chain-v1","steps":[
              mks(1,"统计打卡记录","attendance_stats",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["员工ID","月份"],["员工ID","月份"]),
                   "D":mkck(["打卡时间","迟到次数","早退次数"],["打卡时间","迟到次数","早退次数"]),
                   "R":mkck(["打卡统计表"],["打卡统计表"]),
                   "C":mkck(["本月数据"],["本月数据"])},
                  0.850,["打卡统计表"],False,["Skill 声明打卡统计但无假期/加班数据"]),
              mks(2,"汇总考勤报表","attendance_report",
                  {"I":0.8,"D":0.2,"O":0.0,"R":0.1,"C":0.3},
                  {"I":mkck(["打卡数据","假期数据","加班数据"],["打卡数据"],"solid"),
                   "D":mkck(["出勤天数","请假天数","加班时长","迟到次数"],["迟到次数"],"speculative"),
                   "R":mkck(["月度考勤报表"],[],"speculative"),
                   "C":mkck(["按部门分组"],[],"speculative")},
                  0.001,["(不能产出)"],True,["Skill 完全不具备报表生成和假期/加班数据"])]},
         {"tasks":[
             {"task_name":"统计打卡","agent":"AttendanceAgent","description":"统计员工本月打卡记录"},
             {"task_name":"获取假期数据","agent":"LeaveAgent","description":"获取员工请假/加班数据"},
             {"task_name":"生成报表","agent":"AttendanceAgent","description":"汇总打卡+假期+加班生成考勤报表"}]}),
        ("HRAgent","HR管理平台, 集成考勤打卡、假期审批、加班统计和报表输出",
         {"can_handle":True,"can_contribute":True,"confidence":0.90,"evidence_grade":"A",
          "handle_score":0.950,"contributing_steps":[1],
          "contribution":"一站式输出全维度考勤报表","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"生成月度考勤报表","monthly_attendance_report",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["员工ID","月份"],["员工ID","月份"]),
                   "D":mkck(["出勤天数","请假天数","加班时长","迟到次数","早退次数","旷工天数"],["出勤天数","请假天数","加班时长","迟到次数","早退次数","旷工天数"]),
                   "R":mkck(["月度考勤报表(按部门分组)"],["月度考勤报表(按部门分组)"]),
                   "C":mkck(["本月数据","按部门分组"],["本月数据","按部门分组"])},
                  0.950,["月度考勤报表(含全部考勤维度)"],True,
                  ["Skill 声明 monthly_attendance_report 集成 attendance/leave/overtime 三表"])]},
         {"tasks":[{"task_name":"考勤报表","agent":"HRAgent","description":"生成本月员工考勤报表含打卡/假期/加班"}]})]}),

# Case 14: 风险透明的 Agent 更有可信度
CASES.append({"id":14, "dim":"缺失需求 --- 风险透明的 Agent 更有可信度",
    "query":"同步多个平台的商品库存数据",
    "winner":"SyncCenterAgent",
    "wreason":"InventorySyncAgent confidence 0.84 但没有 risks 声明---它 D/R 都是 speculative(不确认是否支持多平台同步), 实际上隐藏了风险; SyncCenterAgent 明确写出 risks 但全维度 solid、handle_score=0.92. 透明度是加分项, 但能力差距太大时仍应选更强的.",
    "candidates":[
        ("InventorySyncAgent","库存同步工具, 支持多平台数据同步",
         {"can_handle":True,"can_contribute":True,"confidence":0.84,"evidence_grade":"C",
          "handle_score":0.448,"contributing_steps":[1],
          "contribution":"可同步库存数据","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"同步多平台库存","sync_inventory",
                  {"I":1.0,"D":0.2,"O":1.0,"R":0.3,"C":0.5},
                  {"I":mkck(["平台列表","商品SKU"],["平台列表","商品SKU"]),
                   "D":mkck(["淘宝库存","京东库存","拼多多库存","抖音库存"],["淘宝库存"],"speculative"),
                   "R":mkck(["同步结果(各平台库存对比)"],["同步结果"],"speculative"),
                   "C":mkck(["实时同步","库存一致性保证"],["实时同步"],"speculative")},
                  0.448,["同步结果(覆盖不全)"],True,
                  ["Skill 声明库存同步但多平台数据字段不全"])]},
         {"tasks":[
             {"task_name":"连接平台","agent":"InventorySyncAgent","description":"连接淘宝/京东/拼多多等平台API"},
             {"task_name":"同步库存","agent":"InventorySyncAgent","description":"拉取各平台库存数据并同步"}]}),
        ("SyncCenterAgent","多平台数据同步中心, 集成主流电商平台 API 和冲突解决引擎",
         {"can_handle":True,"can_contribute":True,"confidence":0.86,"evidence_grade":"A",
          "handle_score":0.920,"contributing_steps":[1],
          "contribution":"完成多平台库存实时同步含冲突解决","missing_requirements":[],
          "risks":["多平台 API 限流可能导致同步延迟","库存冲突需人工确认"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"同步多平台库存","multi_platform_sync",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["平台列表","商品SKU"],["平台列表","商品SKU"]),
                   "D":mkck(["淘宝库存","京东库存","拼多多库存","抖音库存","唯品会库存"],["淘宝库存","京东库存","拼多多库存","抖音库存","唯品会库存"]),
                   "R":mkck(["同步报告(含各平台对比和冲突标记)"],["同步报告(含各平台对比和冲突标记)"]),
                   "C":mkck(["实时同步","库存一致性保证"],["实时同步","库存一致性保证"])},
                  0.920,["同步报告(含冲突标记)"],True,
                  ["Skill 声明 multi_platform_sync, 集成淘宝/京东/拼多多/抖音/唯品会 API, 含 conflict_resolver"])]},
         {"tasks":[{"task_name":"多平台同步","agent":"SyncCenterAgent","description":"同步淘宝/京东/拼多多等平台的商品库存"}]})]}),

# ═══ D6: Contribute-Only 场景 (15-17) ═══

# Case 15: 两个 contribute-only, 贡献步骤多的更优
CASES.append({"id":15, "dim":"Contribute-Only --- 贡献步骤多的更优",
    "query":"分析竞品定价策略并给出我方定价建议",
    "winner":"PricingIntelAgent",
    "wreason":"PriceSpiderAgent 只能贡献步骤1(抓取), 步骤2(分析) O=0.0; PricingIntelAgent 贡献步骤1(抓取+分析)且全部 solid. 即使都只是 contribute, 贡献覆盖面不同.",
    "candidates":[
        ("PriceSpiderAgent","竞品价格爬虫, 支持定时抓取",
         {"can_handle":False,"can_contribute":True,"confidence":0.75,"evidence_grade":"B",
          "handle_score":0.0,"contributing_steps":[1],
          "contribution":"可抓取竞品价格数据","missing_requirements":["定价分析引擎(步骤2)","建议生成模型"],
          "risks":["爬虫可能被反爬限制"],"score_version":"capability-chain-v1","steps":[
              mks(1,"抓取竞品价格","crawl_prices",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["竞品URL列表"],["竞品URL列表"]),
                   "D":mkck(["商品名称","价格","促销信息","库存状态"],["商品名称","价格"]),
                   "R":mkck(["竞品价格数据表"],["竞品价格数据表"]),
                   "C":mkck(["每日更新"],["每日更新"])},
                  0.850,["竞品价格数据"],False,["Skill 声明价格爬虫"]),
              mks(2,"分析定价策略","analyze_pricing",
                  {"I":1.0,"D":0.1,"O":0.0,"R":0.1,"C":0.2},
                  {"I":mkck(["价格数据"],["价格数据"]),
                   "D":mkck(["历史价格趋势","促销规律"],[],"speculative"),
                   "R":mkck(["定价分析报告"],[],"speculative"),
                   "C":mkck(["含可视化"],[],"speculative")},
                  0.000,["(不能产出)"],True,["Skill 完全不支持定价分析"])]},
         {"tasks":[
             {"task_name":"价格抓取","agent":"PriceSpiderAgent","description":"抓取竞品最新价格"},
             {"task_name":"策略分析","agent":"AnalysisAgent","description":"分析竞品定价策略"}]}),
        ("PricingIntelAgent","定价情报平台, 集成爬虫+分析+建议引擎",
         {"can_handle":False,"can_contribute":True,"confidence":0.88,"evidence_grade":"A",
          "handle_score":0.0,"contributing_steps":[1],
          "contribution":"抓取竞品价格并分析定价策略","missing_requirements":["建议生成模型(步骤2)"],
          "risks":["建议模型对长尾品类准确度有限"],"score_version":"capability-chain-v1","steps":[
              mks(1,"抓取并分析竞品定价","pricing_intel",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["竞品URL列表"],["竞品URL列表"]),
                   "D":mkck(["商品名称","价格","促销信息","库存状态","历史价格"],["商品名称","价格","促销信息","库存状态","历史价格"]),
                   "R":mkck(["竞品价格+定价策略分析"],["竞品价格+定价策略分析"]),
                   "C":mkck(["每日更新","含趋势图"],["每日更新","含趋势图"])},
                  0.950,["竞品价格数据 + 定价策略分析"],False,["Skill 声明 pricing_intel 集成爬虫+分析引擎"]),
              mks(2,"生成定价建议","generate_advice",
                  {"I":1.0,"D":0.3,"O":0.0,"R":0.2,"C":0.3},
                  {"I":mkck(["定价分析结果"],["定价分析结果"]),
                   "D":mkck(["成本数据","利润率模型"],[],"speculative"),
                   "R":mkck(["定价建议方案"],[],"speculative"),
                   "C":mkck(["ROI>0"],[],"speculative")},
                  0.002,["(不能产出)"],True,["Skill 无建议生成能力"])]},
         {"tasks":[
             {"task_name":"情报分析","agent":"PricingIntelAgent","description":"抓取竞品价格并进行策略分析"},
             {"task_name":"生成建议","agent":"OtherAgent","description":"基于分析结果生成定价建议"}]})]}),

# Case 16: handler(低分) 仍优于 contributor(高分)
CASES.append({"id":16, "dim":"Contribute-Only --- 低分 handler 仍优于高分 contributor",
    "query":"查询仓库中即将过期的商品",
    "winner":"WarehouseAgent",
    "wreason":"WarehouseAgent can_handle=True(虽然 confidence 仅 0.65), 能独立完成过期预警查询; ExpiryAlertAgent can_handle=False 只能 contribute 过期检测逻辑, 需要额外数据. 即使 handler 分低, 也比依赖外部输入的 contributor 可靠.",
    "candidates":[
        ("ExpiryAlertAgent","过期预警服务, 支持保质期计算和提醒",
         {"can_handle":False,"can_contribute":True,"confidence":0.82,"evidence_grade":"B",
          "handle_score":0.0,"contributing_steps":[2],
          "contribution":"可计算过期时间和生成预警","missing_requirements":["仓库库存数据(步骤1)"],
          "risks":["依赖外部库存数据源"],"score_version":"capability-chain-v1","steps":[
              mks(1,"获取库存数据","fetch_inventory",
                  {"I":0.8,"D":0.1,"O":0.0,"R":0.1,"C":0.5},
                  {"I":mkck(["仓库ID"],["仓库ID"]),
                   "D":mkck(["商品列表","库存量","生产日期","保质期"],[],"speculative"),
                   "R":mkck(["库存数据"],[],"speculative"),
                   "C":mkck(["实时数据"],[],"speculative")},
                  0.001,["(不能产出)"],False,["Skill 自身无库存数据, 依赖外部"]),
              mks(2,"计算即将过期商品","calc_expiry",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["库存数据"],["库存数据"]),
                   "D":mkck(["生产日期","保质期天数"],["生产日期","保质期天数"]),
                   "R":mkck(["即将过期商品列表(含剩余天数)"],["即将过期商品列表(含剩余天数)"]),
                   "C":mkck(["剩余天数<30"],["剩余天数<30"])},
                  0.950,["即将过期商品预警列表"],True,["Skill 声明过期计算引擎"])]},
         {"tasks":[
             {"task_name":"获取库存","agent":"WarehouseAgent","description":"获取仓库当前库存"},
             {"task_name":"过期预警","agent":"ExpiryAlertAgent","description":"计算哪些商品即将过期"}]}),
        ("WarehouseAgent","仓库管理系统, 包含库存查询和保质期管理",
         {"can_handle":True,"can_contribute":True,"confidence":0.65,"evidence_grade":"B",
          "handle_score":0.817,"contributing_steps":[1],
          "contribution":"直接查询即将过期商品","missing_requirements":[],
          "risks":["保质期数据可能不完整(部分商品未录入)"],"score_version":"capability-chain-v1","steps":[
              mks(1,"查询即将过期商品","query_expiring_goods",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.8},
                  {"I":mkck(["仓库ID"],["仓库ID"]),
                   "D":mkck(["商品名称","SKU","库存量","生产日期","保质期天数","剩余天数"],["商品名称","SKU","库存量","生产日期","保质期天数","剩余天数"]),
                   "R":mkck(["即将过期商品列表"],["即将过期商品列表"]),
                   "C":mkck(["剩余天数<30"],["剩余天数<30"])},
                  0.817,["即将过期商品列表"],True,
                  ["Skill 声明 query_expiring_goods, 内置保质期计算逻辑"])]},
         {"tasks":[{"task_name":"过期查询","agent":"WarehouseAgent","description":"查询仓库中剩余保质期不足30天的商品"}]})]}),

# Case 17: 仅一个候选的特殊验证
CASES.append({"id":17, "dim":"Contribute-Only --- 单候选直接验证",
    "query":"解析合同中的关键条款并提取金额和日期",
    "winner":"ContractParserAgent",
    "wreason":"ContractParserAgent can_handle=True, 全维度 solid, 整合 OCR+NLP 解析, 明显优于只能 OCR 的 DocScannerAgent.",
    "candidates":[
        ("ContractParserAgent","合同智能解析平台, 集成 OCR 识别和 NLP 条款提取",
         {"can_handle":True,"can_contribute":True,"confidence":0.88,"evidence_grade":"A",
          "handle_score":0.920,"contributing_steps":[1],
          "contribution":"一站式完成合同 OCR 识别和关键条款提取","missing_requirements":[],
          "risks":["手写体识别精度有限"],"score_version":"capability-chain-v1","steps":[
              mks(1,"解析合同条款","parse_contract",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["合同文件"],["合同文件"]),
                   "D":mkck(["合同文本","条款分类","金额实体","日期实体","签署方"],["合同文本","条款分类","金额实体","日期实体","签署方"]),
                   "R":mkck(["关键条款摘要","金额列表","日期列表","签署方信息"],["关键条款摘要","金额列表","日期列表","签署方信息"]),
                   "C":mkck(["PDF/图片格式","中文合同"],["PDF/图片格式","中文合同"])},
                  0.920,["合同解析结果(条款+金额+日期+签署方)"],True,
                  ["Skill 声明 parse_contract, 集成 OCR+NLP 合同解析引擎"])]},
         {"tasks":[{"task_name":"合同解析","agent":"ContractParserAgent","description":"OCR 识别合同并提取关键条款、金额和日期"}]}),
        ("DocScannerAgent","文档扫描工具, 仅支持 PDF 转文本",
         {"can_handle":False,"can_contribute":True,"confidence":0.45,"evidence_grade":"C",
          "handle_score":0.0,"contributing_steps":[1],
          "contribution":"可提取合同文本","missing_requirements":["NLP条款解析引擎","实体识别模型"],
          "risks":["无法识别手写体","无条款分类能力"],"score_version":"capability-chain-v1","steps":[
              mks(1,"OCR识别","ocr_scan",
                  {"I":1.0,"D":0.6,"O":1.0,"R":0.6,"C":0.8},
                  {"I":mkck(["合同文件"],["合同文件"]),
                   "D":mkck(["图片/PDF"],["图片/PDF"]),
                   "R":mkck(["纯文本"],["纯文本"]),
                   "C":mkck(["PDF/图片格式"],["PDF/图片格式"])},
                  0.750,["合同纯文本"],False,["Skill 仅支持 OCR 转文本"]),
              mks(2,"提取条款","extract_clauses",
                  {"I":1.0,"D":0.1,"O":0.0,"R":0.1,"C":0.2},
                  {"I":mkck(["合同文本"],["合同文本"]),
                   "D":mkck(["条款分类模型","实体标注"],[],"speculative"),
                   "R":mkck(["条款摘要"],[],"speculative"),
                   "C":mkck(["中文NLP"],[],"speculative")},
                  0.000,["(不能产出)"],True,["Skill 完全无 NLP 解析能力"])]},
         {"tasks":[
             {"task_name":"OCR扫描","agent":"DocScannerAgent","description":"扫描合同并提取文本"},
             {"task_name":"条款解析","agent":"NLPEngine","description":"用 NLP 引擎提取关键条款和实体"}]})]}),

# ═══ D7: 约束满足(C维度)专项 (18-19) ═══

# Case 18: C 维度决定胜负 --- 约束多且全 \u2705 vs 约束少但有 \u274c
CASES.append({"id":18, "dim":"约束满足 --- 约束覆盖决定胜负",
    "query":"为海外用户计算含税价格并显示当地货币",
    "winner":"GlobalPricingAgent",
    "wreason":"LocalPricingAgent C 维度 5 项约束有 3 项 \u274c(不确认欧盟VAT、汇率实时、币种本地化); GlobalPricingAgent 5 项全部 \u2705, handle_score 0.96 >> 0.45. 约束覆盖是关键决策因素.",
    "candidates":[
        ("LocalPricingAgent","本地化价格计算, 支持多币种显示",
         {"can_handle":True,"can_contribute":True,"confidence":0.68,"evidence_grade":"C",
          "handle_score":0.454,"contributing_steps":[1],
          "contribution":"可做基础价格换算","missing_requirements":[],
          "risks":["税率规则不全","汇率来源不确定"],"score_version":"capability-chain-v1","steps":[
              mks(1,"计算含税价格","calc_tax_price",
                  {"I":1.0,"D":0.5,"O":0.7,"R":0.4,"C":0.3},
                  {"I":mkck(["商品原价","用户地区"],["商品原价","用户地区"]),
                   "D":mkck(["税率表","汇率"],["税率表"],"speculative"),
                   "R":mkck(["含税价格","当地货币金额"],["含税价格"],"speculative"),
                   "C":mkck(["适用当地税率","实时汇率","含税计算","币种符号本地化","欧盟VAT规则"],["适用当地税率","含税计算"],"speculative")},
                  0.454,["含税价格(汇率/币种不确定)"],True,
                  ["Skill 声明基础价格计算但约束覆盖不全"])]},
         {"tasks":[
             {"task_name":"税率查询","agent":"LocalPricingAgent","description":"查询用户所在地税率"},
             {"task_name":"汇率换算","agent":"LocalPricingAgent","description":"按实时汇率换算为当地货币"},
             {"task_name":"计算总价","agent":"LocalPricingAgent","description":"计算含税总价并显示本地货币"}]}),
        ("GlobalPricingAgent","全球定价引擎, 集成多国税率和实时汇率",
         {"can_handle":True,"can_contribute":True,"confidence":0.90,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"精准计算全球含税价格并本地化显示","missing_requirements":[],
          "risks":["汇率波动可能导致价格微调"],"score_version":"capability-chain-v1","steps":[
              mks(1,"计算含税当地价格","global_calc",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["商品原价","用户地区"],["商品原价","用户地区"]),
                   "D":mkck(["税率表","汇率","币种信息"],["税率表","汇率","币种信息"]),
                   "R":mkck(["含税价格","当地货币金额","税费明细"],["含税价格","当地货币金额","税费明细"]),
                   "C":mkck(["适用当地税率","实时汇率","含税计算","币种符号本地化","欧盟VAT规则"],["适用当地税率","实时汇率","含税计算","币种符号本地化","欧盟VAT规则"])},
                  0.960,["含税价格 + 当地货币 + 税费明细"],True,
                  ["Skill 声明 global_calc 集成 200+ 国家税率表和实时外汇 API"])]},
         {"tasks":[{"task_name":"全球定价","agent":"GlobalPricingAgent","description":"按当地税率和实时汇率计算含税价格"}]})]}),

# Case 19: C 维度都 solid 但约束数量不同
CASES.append({"id":19, "dim":"约束满足 --- 同 solid 但约束量不同",
    "query":"根据用户偏好推荐个性化商品列表",
    "winner":"PersonalRecAgent",
    "wreason":"两个 Agent 都 solid, 但 PersonalRecAgent 的 C 维度 5 项全 \u2705(含多样性/冷启动/时效性/去重), BasicRecAgent 仅 3 项 \u2705. handle_score 0.96 >> 0.64. 推荐系统对约束敏感度高.",
    "candidates":[
        ("BasicRecAgent","基础推荐引擎, 支持协同过滤",
         {"can_handle":True,"can_contribute":True,"confidence":0.74,"evidence_grade":"B",
          "handle_score":0.640,"contributing_steps":[1],
          "contribution":"可做基础商品推荐","missing_requirements":[],
          "risks":["冷启动用户推荐质量差"],"score_version":"capability-chain-v1","steps":[
              mks(1,"推荐商品","basic_recommend",
                  {"I":1.0,"D":0.8,"O":1.0,"R":0.8,"C":0.4},
                  {"I":mkck(["用户ID"],["用户ID"]),
                   "D":mkck(["用户行为","商品标签"],["用户行为"]),
                   "R":mkck(["推荐商品列表"],["推荐商品列表"]),
                   "C":mkck(["个性化排序","多样性保证","冷启动兜底","时效性加权","已购去重"],["个性化排序","已购去重"],"solid")},
                  0.640,["推荐列表(约束覆盖不全)"],True,
                  ["Skill 声明基础推荐但约束逻辑不完整"])]},
         {"tasks":[
             {"task_name":"用户画像","agent":"BasicRecAgent","description":"获取用户偏好和行为数据"},
             {"task_name":"商品召回","agent":"BasicRecAgent","description":"基于协同过滤召回候选商品"},
             {"task_name":"排序输出","agent":"BasicRecAgent","description":"按个性化排序输出推荐列表"}]}),
        ("PersonalRecAgent","个性化推荐平台, 集成深度学习召回和精细化排序策略",
         {"can_handle":True,"can_contribute":True,"confidence":0.92,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"全链路个性化推荐含完整约束策略","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"个性化推荐","personal_recommend",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["用户ID"],["用户ID"]),
                   "D":mkck(["用户行为","商品标签","实时特征","上下文"],["用户行为","商品标签","实时特征","上下文"]),
                   "R":mkck(["个性化推荐列表(含推荐理由)"],["个性化推荐列表(含推荐理由)"]),
                   "C":mkck(["个性化排序","多样性保证","冷启动兜底","时效性加权","已购去重"],["个性化排序","多样性保证","冷启动兜底","时效性加权","已购去重"])},
                  0.960,["个性化推荐列表(含推荐理由和约束标记)"],True,
                  ["Skill 声明 personal_recommend 集成 DNN 召回和 5 项精细化排序策略"])]},
         {"tasks":[{"task_name":"推荐商品","agent":"PersonalRecAgent","description":"基于用户偏好和行为生成个性化商品推荐"}]})]}),

# ═══ D8: 复杂查询/真实场景多样性 (20-22) ═══

# Case 20: 多条件组合筛选
CASES.append({"id":20, "dim":"复杂查询 --- 多条件筛选",
    "query":"查找上海地区、过去7天内下单、订单金额超过500元且未发货的订单",
    "winner":"OrderFilterAgent",
    "wreason":"OrderFilterAgent 全部维度 solid 且 D 维度明确覆盖上海地区/时间范围/金额/发货状态四个筛选条件; SimpleOrderAgent D 维度缺地区字段, C 维度缺金额阈值, 多项 \u274c. 复杂多条件查询对数据字段覆盖要求极高.",
    "candidates":[
        ("SimpleOrderAgent","订单查询, 支持基础筛选",
         {"can_handle":True,"can_contribute":True,"confidence":0.66,"evidence_grade":"C",
          "handle_score":0.350,"contributing_steps":[1],
          "contribution":"可做基础订单筛选","missing_requirements":[],
          "risks":["地区筛选字段不确定","金额阈值筛选可能不支持"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"筛选订单","filter_orders",
                  {"I":0.8,"D":0.2,"O":0.7,"R":0.3,"C":0.3},
                  {"I":mkck(["筛选条件"],["筛选条件"]),
                   "D":mkck(["订单ID","地区","下单时间","订单金额","发货状态"],["订单ID","下单时间","发货状态"],"speculative"),
                   "R":mkck(["筛选后订单列表"],["列表"],"speculative"),
                   "C":mkck(["上海地区","过去7天","金额>500","未发货"],["过去7天","未发货"],"speculative")},
                  0.350,["订单列表(筛选不全)"],True,
                  ["Skill 缺少地区/金额字段声明"])]},
         {"tasks":[{"task_name":"查询订单","agent":"SimpleOrderAgent","description":"筛选上海地区近7日未发货的大额订单"}]}),
        ("OrderFilterAgent","高级订单筛选引擎, 支持多维度组合筛选",
         {"can_handle":True,"can_contribute":True,"confidence":0.92,"evidence_grade":"A",
          "handle_score":0.950,"contributing_steps":[1],
          "contribution":"精确多条件组合筛选订单","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"多条件筛选订单","advanced_filter",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["筛选条件集合"],["筛选条件集合"]),
                   "D":mkck(["订单ID","收货地区","下单时间","订单金额","发货状态","支付状态"],["订单ID","收货地区","下单时间","订单金额","发货状态","支付状态"]),
                   "R":mkck(["筛选结果列表(含分页和总数)"],["筛选结果列表(含分页和总数)"]),
                   "C":mkck(["上海地区","过去7天","金额>500","未发货"],["上海地区","过去7天","金额>500","未发货"])},
                  0.950,["筛选结果列表(满足全部条件)"],True,
                  ["Skill 声明 advanced_filter 支持 region/time_range/amount_range/status 多维度组合"])]},
         {"tasks":[{"task_name":"高级筛选","agent":"OrderFilterAgent","description":"组合条件筛选: 上海+7天+500元+未发货"}]})]}),

# Case 21: 歧义/简短查询
CASES.append({"id":21, "dim":"复杂查询 --- 歧义/简短查询",
    "query":"查一下订单",
    "winner":"OrderQueryAgent",
    "wreason":"简短模糊查询, OrderQueryAgent 的 I 维度支持模糊输入(用户名/订单号/手机号均有匹配路径), D 维度覆盖订单全字段, evidence=A. OrderSearchAgent D/R speculative, 不确认能处理模糊匹配.",
    "candidates":[
        ("OrderSearchAgent","订单搜索, 支持关键词检索",
         {"can_handle":True,"can_contribute":True,"confidence":0.70,"evidence_grade":"C",
          "handle_score":0.560,"contributing_steps":[1],
          "contribution":"可搜索订单","missing_requirements":[],
          "risks":["模糊匹配逻辑不确定","搜索结果排序规则不明确"],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"搜索订单","search_orders",
                  {"I":0.6,"D":0.4,"O":1.0,"R":0.5,"C":0.6},
                  {"I":mkck(["搜索关键词"],["模糊词"],"speculative"),
                   "D":mkck(["订单号","用户名","金额","状态","时间"],["订单号"],"speculative"),
                   "R":mkck(["搜索结果列表"],["列表"],"speculative"),
                   "C":mkck(["相关性排序"],[],"speculative")},
                  0.560,["搜索结果(不确定)"],True,
                  ["Skill 声明搜索但模糊匹配和数据字段不明确"])]},
         {"tasks":[{"task_name":"搜索","agent":"OrderSearchAgent","description":"搜索最近的订单"}]}),
        ("OrderQueryAgent","智能订单查询, 支持多维度自然语言理解和精准匹配",
         {"can_handle":True,"can_contribute":True,"confidence":0.82,"evidence_grade":"A",
          "handle_score":0.880,"contributing_steps":[1],
          "contribution":"可通过用户名/订单号/手机号/模糊关键词等多种方式查询订单","missing_requirements":[],
          "risks":["超简短查询(1-2字)可能匹配范围过大"],"score_version":"capability-chain-v1","steps":[
              mks(1,"智能查询订单","smart_query",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["查询关键词(支持用户名/订单号/手机号/模糊文本)"],["查询关键词"]),
                   "D":mkck(["订单号","用户名","手机号","金额","状态","时间","商品"],["订单号","用户名","手机号","金额","状态","时间","商品"]),
                   "R":mkck(["订单列表(含匹配度排序)"],["订单列表(含匹配度排序)"]),
                   "C":mkck(["最多返回20条","按时间倒序","高亮匹配字段"],["最多返回20条","按时间倒序","高亮匹配字段"])},
                  0.880,["订单列表(智能匹配 + 排序)"],True,
                  ["Skill 声明 smart_query 集成 NLU 意图理解和多字段模糊匹配, 支持 user_name/order_id/phone 三重匹配路径"])]},
         {"tasks":[{"task_name":"智能查询","agent":"OrderQueryAgent","description":"理解查询意图并搜索最近订单"}]})]}),

# Case 22: 跨系统集成查询
CASES.append({"id":22, "dim":"复杂查询 --- 跨系统集成",
    "query":"查询用户的会员等级并计算本单应享受的折扣",
    "winner":"MemberServiceAgent",
    "wreason":"MemberServiceAgent 集成会员查询+折扣计算, O=1.0 可直接执行, 全维度 solid; DiscountCalcAgent 只能 contribute 折扣计算步骤, 需要外部会员数据. 跨系统场景优先选能一站式完成的.",
    "candidates":[
        ("DiscountCalcAgent","折扣计算引擎, 根据会员等级计算折扣",
         {"can_handle":False,"can_contribute":True,"confidence":0.78,"evidence_grade":"B",
          "handle_score":0.0,"contributing_steps":[2],
          "contribution":"可计算会员折扣","missing_requirements":["会员等级数据(步骤1)"],
          "risks":["依赖外部会员系统"],"score_version":"capability-chain-v1","steps":[
              mks(1,"查询会员等级","query_member",
                  {"I":0.8,"D":0.1,"O":0.0,"R":0.1,"C":0.5},
                  {"I":mkck(["用户ID"],["用户ID"]),
                   "D":mkck(["会员等级","积分","注册时间"],[],"speculative"),
                   "R":mkck(["会员等级"],[],"speculative"),
                   "C":mkck(["实时数据"],[],"speculative")},
                  0.001,["(不能产出)"],False,["Skill 自身无会员数据"]),
              mks(2,"计算折扣","calc_discount",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["会员等级","订单金额"],["会员等级","订单金额"]),
                   "D":mkck(["等级折扣表"],["等级折扣表"]),
                   "R":mkck(["折扣金额","折后价格"],["折扣金额","折后价格"]),
                   "C":mkck(["折扣范围0-50%","不与其他优惠叠加"],["折扣范围0-50%","不与其他优惠叠加"])},
                  0.950,["折扣计算结果"],True,["Skill 声明折扣计算引擎"])]},
         {"tasks":[
             {"task_name":"查询会员","agent":"MemberServiceAgent","description":"查询用户会员等级"},
             {"task_name":"计算折扣","agent":"DiscountCalcAgent","description":"根据等级计算折扣金额"}]}),
        ("MemberServiceAgent","会员服务中台, 集成等级查询、积分管理、折扣计算",
         {"can_handle":True,"can_contribute":True,"confidence":0.90,"evidence_grade":"A",
          "handle_score":0.960,"contributing_steps":[1],
          "contribution":"一站式查询会员等级并计算折扣","missing_requirements":[],"risks":[],
          "score_version":"capability-chain-v1","steps":[
              mks(1,"查询会员等级并计算折扣","member_discount",
                  {"I":1.0,"D":1.0,"O":1.0,"R":1.0,"C":0.8},
                  {"I":mkck(["用户ID","订单金额"],["用户ID","订单金额"]),
                   "D":mkck(["会员等级","积分","等级折扣表","当前优惠"],["会员等级","积分","等级折扣表","当前优惠"]),
                   "R":mkck(["会员等级","折扣金额","折后价格","可用积分"],["会员等级","折扣金额","折后价格","可用积分"]),
                   "C":mkck(["折扣范围0-50%","不与其他优惠叠加","积分可同时使用"],["折扣范围0-50%","不与其他优惠叠加","积分可同时使用"])},
                  0.960,["会员等级 + 折扣计算结果 + 积分信息"],True,
                  ["Skill 声明 member_discount 集成会员查询和折扣计算, 一次调用返回等级+折扣+积分"])]},
         {"tasks":[{"task_name":"会员折扣","agent":"MemberServiceAgent","description":"查询会员等级并计算本单折扣金额"}]})]}),

# ═══════════════════════════════════════════════════════════════════════════
# Case S1-S4: 补充维度 (多候选 / 矛盾信号 / speculative I / 重复稳定性)
# ═══════════════════════════════════════════════════════════════════════════
# 这些场景用于填补主套件 (Case 1-22) 未覆盖的 4 个缺口。

# ── S1: 3 个候选 --- 证据质量应击败更高 confidence ──
# 缺口: 主套件全部只有 2 个候选。此 case 有 3 个, 且 winner 的 confidence
#       在三人中排第 2 (0.80 < 0.88), 必须靠 evidence 才能胜出。
CASES.append({
    "id": "S1", "dim": "3候选 --- 证据质量击败更高 confidence",
    "query": "查询客户的历史投诉记录",
    "winner": "ComplaintCenterAgent",
    "wreason": "ComplaintCenterAgent confidence 仅 0.80 (低于 ComplaintQuickAgent 的 0.88), 但证据等级 A、全维度 solid、D/R 明确覆盖投诉时间/类型/处理结果; ComplaintQuickAgent 虽然 confidence 最高但 grade C、D/R 全推算, 属 inflated score; ComplaintMiniAgent 完全不能做 (O=0.0)。LLM 不应被最高 confidence 迷惑。",
    "candidates": [
        # C1: confidence 最高, 但证据最弱 (inflated)
        ("ComplaintQuickAgent", "投诉快捷查询, 提供投诉基础检索入口",
         {"can_handle": True, "can_contribute": True, "confidence": 0.88, "evidence_grade": "C",
          "handle_score": 0.600, "contributing_steps": [1],
          "contribution": "可检索投诉记录", "missing_requirements": [],
          "risks": ["投诉字段未在 Skill 中声明", "处理结果字段可能不存在"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询投诉记录", "quick_complaint_query",
                  {"I": 1.0, "D": 0.4, "O": 1.0, "R": 0.5, "C": 0.6},
                  {"I": mkck(["客户标识"], ["客户标识"]),
                   "D": mkck(["投诉时间", "投诉类型", "投诉内容", "处理结果"], ["投诉时间", "投诉类型"], "speculative"),
                   "R": mkck(["投诉记录列表"], ["列表"], "speculative"),
                   "C": mkck(["按时间倒序"], ["按时间倒序"], "speculative")},
                  0.600, ["投诉记录列表(字段不全)"], True,
                  ["Skill 仅声明投诉检索入口, 未列出完整字段"])]},
         {"tasks": [{"task_name": "查询投诉", "agent": "ComplaintQuickAgent",
                     "description": "查询客户的历史投诉记录"}]}),
        # C2: confidence 居中, 证据最强 → WINNER
        ("ComplaintCenterAgent", "投诉管理中枢, 持有完整投诉工单表含处理结果",
         {"can_handle": True, "can_contribute": True, "confidence": 0.80, "evidence_grade": "A",
          "handle_score": 0.940, "contributing_steps": [1],
          "contribution": "可直接返回客户完整投诉历史含处理结果", "missing_requirements": [], "risks": [],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询客户投诉历史", "get_complaint_history",
                  {"I": 1.0, "D": 1.0, "O": 1.0, "R": 1.0, "C": 0.8},
                  {"I": mkck(["客户标识"], ["客户标识"]),
                   "D": mkck(["投诉时间", "投诉类型", "投诉内容", "处理结果", "处理人"], ["投诉时间", "投诉类型", "投诉内容", "处理结果", "处理人"]),
                   "R": mkck(["投诉记录列表(含处理结果)"], ["投诉记录列表(含处理结果)"]),
                   "C": mkck(["按时间倒序", "含已关闭工单"], ["按时间倒序", "含已关闭工单"])},
                  0.940, ["投诉记录列表(含完整字段和处理结果)"], True,
                  ["Skill 正文明确声明 get_complaint_history 返回 complaint_time/type/content/result/handler 全字段"])]},
         {"tasks": [{"task_name": "投诉历史", "agent": "ComplaintCenterAgent",
                     "description": "查询客户全部历史投诉及处理结果"}]}),
        # C3: 明显不能做 (O=0.0)
        ("ComplaintMiniAgent", "极简投诉入口, 仅记录新投诉",
         {"can_handle": False, "can_contribute": False, "confidence": 0.35, "evidence_grade": "D",
          "handle_score": 0.0, "contributing_steps": [],
          "contribution": "", "missing_requirements": ["投诉查询能力", "历史数据"],
          "risks": ["仅支持写入不支持查询"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询投诉记录", "mini_query",
                  {"I": 1.0, "D": 0.0, "O": 0.0, "R": 0.0, "C": 0.2},
                  {"I": mkck(["客户标识"], ["客户标识"]),
                   "D": mkck(["投诉记录"], [], "speculative"),
                   "R": mkck(["投诉列表"], [], "speculative"),
                   "C": mkck(["历史数据"], [], "speculative")},
                  0.000, ["(不能产出)"], True,
                  ["Skill 仅支持写入新投诉, 不支持任何查询"])]},
         {"tasks": [{"task_name": "记录投诉", "agent": "ComplaintMiniAgent",
                     "description": "记录一条新投诉"}]}),
    ],
})

# ─ S2: 矛盾信号 --- 高分低证据 vs 中分高证据 ──
# 缺口: 主套件从未出现 evidence_grade 与 handle_score 矛盾的情况。
#       C1 的 handle_score (0.90) 远高于 C2 (0.68), 但 C1 的 grade=D
#       且 D/R 全为「推算」--- 典型 inflated score。按 prompt 的引导原则,
#       应优先相信证据而非虚高的自评分。
CASES.append({
    "id": "S2", "dim": "矛盾信号 --- inflated handle_score 应让位于证据",
    "query": "查询产品的销量趋势",
    "winner": "SalesTrendAgent",
    "wreason": "DataDashAgent 的 handle_score (0.90) 和 confidence (0.90) 都明显更高, 但 evidence_grade=D 且 D/R/C 全部是「推算」--- 它并不确认自己拥有销量趋势字段和趋势输出; SalesTrendAgent 虽然 handle_score 仅 0.68、O=0.7, 但全维度 solid、grade A, D/R 明确声明了销量字段和时间维度。LLM 应以证据可信度而非虚高自评分做判断。",
    "candidates": [
        # C1: 高分但证据全推算 (inflated)
        ("DataDashAgent", "数据看板, 声称支持多维度业务指标展示",
         {"can_handle": True, "can_contribute": True, "confidence": 0.90, "evidence_grade": "D",
          "handle_score": 0.900, "contributing_steps": [1],
          "contribution": "可展示业务指标趋势", "missing_requirements": [],
          "risks": ["销量趋势字段未在 Skill 中声明", "趋势图输出形态未确认"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询销量趋势", "dash_sales_trend",
                  {"I": 1.0, "D": 0.9, "O": 1.0, "R": 0.9, "C": 0.7},
                  {"I": mkck(["产品标识", "时间范围"], ["产品标识", "时间范围"]),
                   "D": mkck(["销量", "销量时间序列", "同比环比"], ["销量"], "speculative"),
                   "R": mkck(["销量趋势图", "趋势数据表"], ["销量趋势图"], "speculative"),
                   "C": mkck(["按天聚合", "含同比环比"], ["按天聚合"], "speculative")},
                  0.900, ["销量趋势图(字段未验证)"], True,
                  ["Skill 仅泛泛声明支持业务指标展示, 未列出任何具体趋势字段"])]},
         {"tasks": [{"task_name": "销量趋势", "agent": "DataDashAgent",
                     "description": "展示产品销量趋势图"}]}),
        # C2: 分数中等但证据全实据 → WINNER
        ("SalesTrendAgent", "销量分析专用代理, 持有逐日销量表和趋势计算模块",
         {"can_handle": True, "can_contribute": True, "confidence": 0.72, "evidence_grade": "A",
          "handle_score": 0.680, "contributing_steps": [1],
          "contribution": "可输出销量趋势数据表 (趋势图需组合图表模块)", "missing_requirements": [],
          "risks": ["趋势图渲染需组合图表模块 (O=0.7)"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询销量趋势", "sales_trend",
                  {"I": 1.0, "D": 1.0, "O": 0.7, "R": 1.0, "C": 0.8},
                  {"I": mkck(["产品标识", "时间范围"], ["产品标识", "时间范围"]),
                   "D": mkck(["销量", "销量时间序列", "同比环比"], ["销量", "销量时间序列", "同比环比"]),
                   "R": mkck(["销量趋势数据表", "趋势数据"], ["销量趋势数据表", "趋势数据"]),
                   "C": mkck(["按天聚合", "含同比环比"], ["按天聚合", "含同比环比"])},
                  0.680, ["销量趋势数据表"], True,
                  ["Skill 明确声明 sales_trend 方法, 返回 daily_sales/series/yoy/mom, 趋势图需组合 chart 模块"])]},
         {"tasks": [{"task_name": "销量趋势", "agent": "SalesTrendAgent",
                     "description": "查询产品逐日销量并计算趋势"}]}),
    ],
})

# ─ S3: speculative I 维度 --- 输入匹配未验证 ──
# 缺口: 主套件 I 维度恒为 solid。此 case 中 C1 仅 I 维度为「推算」
#       (连接方式/输入参数未声明), 但 D/R/C 全是实据; C2 的 I 是实据,
#       但决定成败的 D/R 全是「推算」。目标是验证 LLM 不会因单个 I 维度
#       的推算就淘汰 D/R 坚实的候选, 反而应淘汰 D/R 不可靠的那个。
CASES.append({
    "id": "S3", "dim": "speculative I --- 单个 I 推算不应淘汰 D/R 坚实的候选",
    "query": "执行数据库慢查询分析",
    "winner": "QueryInsightAgent",
    "wreason": "QueryInsightAgent 只有 I(输入匹配) 是「推算」--- 连接方式未明文声明属可控风险; 其 D/R/C 全部实据, 明确拥有慢查询日志字段和执行计划字段。SlowLogAgent 的 I 虽然是实据 (明确接受日志文件), 但核心的 D/R 全是「推算」--- 不确定能否解析慢查询和执行计划, 对分析任务更致命。",
    "candidates": [
        # C1: 仅 I 推算, D/R 实据 → WINNER
        ("QueryInsightAgent", "数据库性能诊断, 持有慢查询日志和执行计划解析器",
         {"can_handle": True, "can_contribute": True, "confidence": 0.79, "evidence_grade": "B",
          "handle_score": 0.760, "contributing_steps": [1],
          "contribution": "可分析慢查询并输出执行计划", "missing_requirements": [],
          "risks": ["数据库连接方式未在 Skill 中明文声明, 需运行时确认 (I 维度推算)"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "分析慢查询", "analyze_slow_query",
                  {"I": 0.7, "D": 1.0, "O": 1.0, "R": 1.0, "C": 0.8},
                  {"I": mkck(["数据库连接", "慢查询阈值"], ["慢查询阈值"], "speculative"),
                   "D": mkck(["SQL文本", "执行时长", "执行计划", "扫描行数"], ["SQL文本", "执行时长", "执行计划", "扫描行数"]),
                   "R": mkck(["慢查询列表", "执行计划详情", "优化建议"], ["慢查询列表", "执行计划详情", "优化建议"]),
                   "C": mkck(["按执行时长排序", "阈值可配置"], ["按执行时长排序", "阈值可配置"])},
                  0.760, ["慢查询列表 + 执行计划 + 优化建议"], True,
                  ["Skill 明确声明 analyze_slow_query 返回 sql/duration/plan/rows_scanned/advice, 但连接参数未明文声明"])]},
         {"tasks": [{"task_name": "慢查询分析", "agent": "QueryInsightAgent",
                     "description": "分析数据库慢查询并给出执行计划和优化建议"}]}),
        # C2: I 实据但 D/R 推算
        ("SlowLogAgent", "慢日志读取工具, 支持读取日志文件",
         {"can_handle": True, "can_contribute": True, "confidence": 0.74, "evidence_grade": "C",
          "handle_score": 0.550, "contributing_steps": [1],
          "contribution": "可读取慢日志文本", "missing_requirements": [],
          "risks": ["不确认能否解析执行计划", "分析能力未声明"],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "分析慢查询", "slow_log_read",
                  {"I": 1.0, "D": 0.4, "O": 1.0, "R": 0.4, "C": 0.8},
                  {"I": mkck(["日志文件路径"], ["日志文件路径"]),
                   "D": mkck(["SQL文本", "执行时长", "执行计划", "扫描行数"], ["SQL文本", "执行时长"], "speculative"),
                   "R": mkck(["慢查询列表", "执行计划详情"], ["慢查询列表"], "speculative"),
                   "C": mkck(["按执行时长排序"], ["按执行时长排序"])},
                  0.550, ["慢日志文本(无执行计划)"], True,
                  ["Skill 仅声明读取慢日志文本, 执行计划解析与分析能力未声明"])]},
         {"tasks": [{"task_name": "读取慢日志", "agent": "SlowLogAgent",
                     "description": "读取数据库慢日志文件"}]}),
    ],
})

# ── S4: 重复运行稳定性 --- 接近场景复跑 5 次 ──
# 缺口: 主套件每个 case 只跑一次, 只测了「准确率」没测「稳定性」。
#       复用主套件 Case 6 (LogisticsAgent vs TrackAgent, hs 0.855 vs 0.850)
#       --- 一个刻意设计成接近的 case --- 复跑 5 次, 验证选择是否恒定。
CASES.append({
    "id": "S4", "dim": "稳定性 --- 接近场景复跑 5 次",
    "query": "查询物流单号的实时位置",
    "winner": "LogisticsAgent",
    "repeat": 5,
    "wreason": "接近场景 (hs 0.855 vs 0.850) 复跑 5 次, 预期恒选 LogisticsAgent (grade A / D 全 ✅)。若出现翻转说明接近场景不稳定。",
    "candidates": [
        ("TrackAgent", "物流追踪, 支持查询包裹状态",
         {"can_handle": True, "can_contribute": True, "confidence": 0.85, "evidence_grade": "B",
          "handle_score": 0.850, "contributing_steps": [1],
          "contribution": "可查询物流轨迹", "missing_requirements": [],
          "risks": ["实时位置更新频率待确认"], "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询物流实时位置", "track_package",
                  {"I": 1.0, "D": 0.8, "O": 1.0, "R": 0.8, "C": 0.8},
                  {"I": mkck(["物流单号"], ["物流单号"]),
                   "D": mkck(["当前位置", "运输节点", "时间戳", "揽收时间", "预计到达"], ["当前位置", "运输节点", "时间戳", "预计到达"]),
                   "R": mkck(["物流轨迹地图", "节点列表"], ["物流轨迹地图", "节点列表"]),
                   "C": mkck(["实时数据"], ["实时数据"])},
                  0.850, ["物流轨迹地图 + 节点列表"], True,
                  ["Skill 声明 track_package, D 缺揽收时间字段"])]},
         {"tasks": [{"task_name": "物流追踪", "agent": "TrackAgent",
                     "description": "根据单号查询包裹实时位置和轨迹"}]}),
        ("LogisticsAgent", "全链路物流查询平台, 含实时位置和全节点时间线",
         {"can_handle": True, "can_contribute": True, "confidence": 0.85, "evidence_grade": "A",
          "handle_score": 0.855, "contributing_steps": [1],
          "contribution": "查询物流全轨迹含实时位置和完整时间线", "missing_requirements": [], "risks": [],
          "score_version": "capability-chain-v1", "steps": [
              mks(1, "查询物流实时位置", "get_logistics_trace",
                  {"I": 1.0, "D": 1.0, "O": 1.0, "R": 0.8, "C": 0.8},
                  {"I": mkck(["物流单号"], ["物流单号"]),
                   "D": mkck(["当前位置", "运输节点", "时间戳", "揽收时间", "预计到达"], ["当前位置", "运输节点", "时间戳", "揽收时间", "预计到达"]),
                   "R": mkck(["物流轨迹地图", "节点列表", "实时推送"], ["物流轨迹地图", "节点列表"]),
                   "C": mkck(["实时数据"], ["实时数据"])},
                  0.855, ["物流轨迹地图 + 节点列表(实时)"], True,
                  ["Skill 明确声明 get_logistics_trace, full node timeline with pickup_time/estimated_arrival"])]},
         {"tasks": [{"task_name": "物流追踪", "agent": "LogisticsAgent",
                     "description": "根据单号获取实时位置和完整轨迹"}]}),
    ],
})

# ═══════════════════════════════════════════════════════════════════════════
# Case 执行器
# ═══════════════════════════════════════════════════════════════════════════

# S4 需要复跑, 其余单跑。
_RUN_LIVE = os.getenv("ROUTING_LLM_TESTS", "").strip().lower() in ("1", "true", "yes")


def _new_client(api_key=None, base_url=None):
    """构造 DashScope (OpenAI-compatible) client。

    ``api_key`` 为空时回退到环境变量 (见 :func:`read_api_key`)。
    """
    return OpenAI(
        api_key=read_api_key(api_key),
        base_url=base_url or BASE_URL,
    )


def run_case(case, client=None):
    """执行单个 Case (若带 ``repeat`` 则复跑 N 次)。

    返回 dict: ``{case, picks, names, elapsed, consistent, ok}``。
    """
    client = client or _new_client()
    reps = int(case.get("repeat", 1))
    ctx, names = build_candidates_context(case["candidates"])
    prompt = build_select_prompt(case["query"], ctx)

    logger.info("[Case %s] %s | candidates=%d | prompt=%d chars",
                case["id"], case["query"][:60], len(names), len(prompt))

    picks, reasons, elapsed = [], [], 0.0
    for i in range(reps):
        label = f"{case['id']}" + (f".{i + 1}" if reps > 1 else "")
        t0 = time.monotonic()
        r = call_dashscope(client, prompt, label=label)
        elapsed += time.monotonic() - t0
        si = r.get("selected_agent_index", -1)
        picks.append(names[si - 1] if 1 <= si <= len(names) else f"INVALID({si})")
        reasons.append(r.get("reason", ""))

    consistent = len(set(picks)) == 1
    ok = all(p == case["winner"] for p in picks) and consistent

    if ok:
        logger.info("[Case %s] \u2705 PASS -> %s%s", case["id"], picks[0],
                    f" (一致 x{reps})" if reps > 1 else "")
    else:
        logger.error("[Case %s] \u274c FAIL -> expected=%s got=%s consistent=%s",
                     case["id"], case["winner"], picks, consistent)

    return {"case": case, "picks": picks, "names": names, "reasons": reasons,
            "elapsed": elapsed, "reps": reps, "consistent": consistent, "ok": ok}


def main(argv=None):
    """命令行入口: 按参数执行 Case 并输出 Markdown 报告。

    API key 通过 ``--api-key`` 或环境变量提供, 不落代码。
    """
    args = build_parser().parse_args(argv)

    # 命令行参数覆盖模块级默认配置 (model / base_url 会体现在报告中)。
    global MODEL
    MODEL = args.model
    api_key_env = args.api_key_env or API_KEY_ENV

    try:
        api_key = read_api_key(args.api_key, api_key_env)
    except MissingApiKeyError as e:
        logger.error("%s", e)
        return 2

    selected = _select_cases(args.case)
    if not selected:
        logger.error("--case 指定的 ID 均不存在; 可用: %s",
                     ", ".join(str(c["id"]) for c in CASES))
        return 2

    logger.info("=" * 60)
    logger.info("Pre-Make-Plan + select_best_plan 端到端测试 | %d cases | model=%s",
                len(selected), MODEL)
    logger.info("=" * 60)

    client = _new_client(api_key, args.base_url)
    results = []
    total_elapsed = 0.0
    for case in selected:
        res = run_case(case, client)
        results.append(res)
        total_elapsed += res["elapsed"]

    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed

    logger.info("=" * 60)
    logger.info("Done | Passed=%d | Failed=%d | %.1fs", passed, failed, total_elapsed)
    logger.info("=" * 60)

    report = _format_report(results, passed, failed, total_elapsed)
    print("\n" + report)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        logger.info("报告已写入: %s", args.out)

    if failed:
        sys.exit(1)
    logger.info("\U0001f389 全部 %d 个 Case 通过!", passed)
    return 0


def _select_cases(case_ids):
    """按 ``--case`` 指定的 ID 过滤 Case; 未指定则返回全部。"""
    if not case_ids:
        return list(CASES)
    wanted = {str(x) for x in case_ids}
    return [c for c in CASES if str(c["id"]) in wanted]


def _format_report(results, passed, failed, total_elapsed):
    """生成 Markdown 测试报告 (仅 stdout, 不落盘)。"""
    total = len(results)
    L = ["# Pre-Make-Plan + select_best_plan 测试报告", "",
         f"**测试时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"**测试模型**: `{MODEL}` (via DashScope)",
         f"**用例数**: {total} | **通过**: {passed} \u2705 | **失败**: {failed} \u274c",
         f"**总耗时**: {total_elapsed:.1f}s (平均 {total_elapsed / total:.1f}s/case)", "",
         "## 结果明细", "",
         "| # | 维度 | Query | 预期 | 实际 | 复跑 | 结果 |",
         "|---|------|-------|------|------|------|------|"]
    for r in results:
        c = r["case"]
        picks = ", ".join(sorted(set(r["picks"])))
        st = "\u2705" if r["ok"] else "\u274c"
        L.append(f"| {c['id']} | {c['dim']} | {c['query'][:60]} | {c['winner']} | {picks} | "
                 f"\u00d7{r['reps']} | {st} |")
    if failed:
        L.extend(["", "## 失败详情", ""])
        for r in results:
            if not r["ok"]:
                c = r["case"]
                L.extend([f"### Case {c['id']}: {c['dim']}",
                          f"- **Query**: {c['query']}",
                          f"- **预期**: `{c['winner']}` | **实际**: {r['picks']}",
                          f"- **预期理由**: {c.get('wreason', '')}",
                          f"- **LLM 理由**: {r['reasons'][0] if r['reasons'] else '(无)'}", ""])
    return "\n".join(L)


# ── pytest 集成 ─────────────────────────────────────────────────────────────
# 真实 LLM 调用较慢 (约 8-10s/case), 默认跳过; 需 ROUTING_LLM_TESTS=1
# 且环境中提供 DASHSCOPE_API_KEY (或 DASHSCOPE_API_KEY_ENV 指定名)。
try:
    import pytest
except ImportError:  # pragma: no cover
    pytest = None

_HAS_KEY = bool(os.getenv(API_KEY_ENV))

if pytest is not None:

    @pytest.mark.skipif(
        not _RUN_LIVE or not _HAS_KEY,
        reason="需真实 LLM 调用; 设置 ROUTING_LLM_TESTS=1 且提供 "
               f"{API_KEY_ENV} 环境变量后启用",
    )
    @pytest.mark.parametrize("case", CASES, ids=[str(c["id"]) for c in CASES])
    def test_pre_make_plan_selects_expected_agent(case):
        """每个 Case 必须选出预期 winner, 且复跑时保持稳定。"""
        res = run_case(case)
        assert res["consistent"], f"Case {case['id']} 复跑结果不一致: {res['picks']}"
        assert res["picks"][0] == case["winner"], (
            f"Case {case['id']} 预期 {case['winner']}, 实际 {res['picks'][0]}"
        )


if __name__ == "__main__":
    sys.exit(main())