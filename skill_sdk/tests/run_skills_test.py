#!/usr/bin/env python3
"""Comprehensive test suite for ALL skills — stability, edge cases, and ToolResult pipeline.

Covers all 19 skills. Each skill has 2-4 scenarios: normal, edge/boundary, error handling,
multi-step, ToolResult interpretation, and stagnation.

Usage:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH="/Users/james/daocloud/code/dac/model_sdk:$PYTHONPATH" \
    /tmp/venv_skill/bin/python3 tests/run_skills_test.py
"""

from __future__ import annotations

import asyncio, json, os, sys, uuid
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))
sys.path.insert(0, "/Users/james/daocloud/code/dac/model_sdk")

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-test")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://localhost:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://localhost:3000")

from langchain_openai import ChatOpenAI
from skill_sdk.skill.runner import SkillRunner
from skill_sdk.skill.loader import SkillLoader

DASHSCOPE_API_KEY = "sk-xxx"
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-flash-0731"
SKILLS_DIR = _SDK_ROOT / "skills"


def build_llm():
    return ChatOpenAI(
        model=LLM_MODEL, openai_api_key=DASHSCOPE_API_KEY,
        openai_api_base=DASHSCOPE_BASE_URL, temperature=0.01,
        model_kwargs={"extra_body": {"enable_thinking": False}},
    )


def load_flat_skill(d):
    meta = SkillLoader.read_meta_json(str(d))
    md = SkillLoader.read_skill_md(str(d))
    return meta, SkillLoader.build_skill(meta, md, base_dir=str(d))


def load_zip_skill(p):
    return SkillLoader().load(str(p))


def _parse_r(r):
    try:
        p = json.loads(str(r.get("result", "")))
        return p if isinstance(p, dict) and "tool_name" in p else None
    except Exception:
        return None


def _count(th, key, val):
    return sum(1 for e in th if (_p := _parse_r(e)) and _p.get(key) == val)


def _stag(th):
    return any(_parse_r(e) and "WARNING:" in (_parse_r(e) or {}).get("content", "")
               for e in th)


def sep(t):
    print(f"\n{'='*70}\n  {t}\n{'='*70}")


def pr(r, h=True):
    print(f"  Status: {r.get('status')}")
    fa = r.get("final_answer", "")
    print(f"  Final answer ({len(fa)}c): {fa[:400]}{'...' if len(fa)>400 else ''}")
    th = r.get("tool_history", [])
    b, e, s = _count(th, "status", "blocked"), _count(th, "is_error", True), _count(th, "status", "success")
    print(f"  Tool calls: {len(th)} (ok{s} err{e} blk{b})  Stag: {'WARN' if _stag(th) else 'none'}")
    if h and len(th) <= 10:
        for i, en in enumerate(th):
            tn = en.get("tool", "?")
            p = _parse_r(en)
            if p:
                print(f"    [{i}] {tn} [{p.get('status','?')}]: {p.get('content','')[:120]}")
            else:
                print(f"    [{i}] {tn}: {str(en.get('result',''))[:100]}")


async def run(skill, q, rid, ms=8, **kw):
    llm = build_llm()
    runner = SkillRunner(llm=llm, skills=[skill], max_steps=ms, cmd_timeout_sec=15,
                         allow_destructive_commands=False, use_skill_search=False, **kw)
    print(f"  Skill: {skill.name}  |  Tools: {skill.allowed_tools or 'all'}")
    print(f"  Query: {q}")
    r = await runner.run(query=q, skill=skill, user_id="ts", run_id=rid, trace_id=uuid.uuid4().hex)
    pr(r)
    return r


async def mk_skill(tools=None):
    """Create a skill with given allowed_tools."""
    return SkillLoader.build_skill(
        {"version": "1.0.0", "allowed_tools": tools or ["plan_cmd", "finish"]},
        SkillLoader.read_skill_md(str(SKILLS_DIR / "read-code")),
        base_dir=str(SKILLS_DIR / "read-code"),
    )


# ══════════════════════════════════════════════════════════════════════════════
# A: read-code
# ══════════════════════════════════════════════════════════════════════════════

async def A1():
    sep("A1: read-code — normal")
    _, s = load_flat_skill(SKILLS_DIR / "read-code")
    return await run(s, "分析 skill_sdk/skill/stagnation.py 中 StagnationDetector 类的核心逻辑，包括检测层级和阈值。", "A1", 10)

async def A2():
    sep("A2: read-code — stagnation")
    _, s = load_flat_skill(SKILLS_DIR / "read-code")
    return await run(s, "在 skill_sdk 目录下找到 nonexistent_xyz_12345.py 文件，然后用 readline_in_range 读取它的全部内容。", "A2", 8)

async def A3():
    sep("A3: read-code — multi-file")
    _, s = load_flat_skill(SKILLS_DIR / "read-code")
    return await run(s, "简要说明 skill_sdk/skill/tool_result.py 和 skill_sdk/skill/stagnation.py 两个模块各是什么用途，它们如何协作。不要逐行分析，只需要一两句话概括。", "A3", 6)

async def A4():
    sep("A4: read-code — search pattern")
    _, s = load_flat_skill(SKILLS_DIR / "read-code")
    return await run(s, "在 skill_sdk 目录下，找出所有 import 了 ToolResult 的文件，列出文件名。", "A4", 6)

# ══════════════════════════════════════════════════════════════════════════════
# B: code_execution
# ══════════════════════════════════════════════════════════════════════════════

async def B1():
    sep("B1: code_execution — normal")
    _, s = load_flat_skill(SKILLS_DIR / "code_execution")
    return await run(s, "计算 1 到 100 所有整数的和", "B1")

async def B2():
    sep("B2: code_execution — bad input")
    _, s = load_flat_skill(SKILLS_DIR / "code_execution")
    return await run(s, "读取 /tmp/nonexistent_xyz_12345.json 文件，计算其中 sales 的总和", "B2", 8)

async def B3():
    sep("B3: code_execution — complex")
    _, s = load_flat_skill(SKILLS_DIR / "code_execution")
    return await run(s, "用 Python 生成前 20 个斐波那契数列，计算它们的均值、中位数和标准差。", "B3", 10)

async def B4():
    sep("B4: code_execution — pipeline")
    _, s = load_flat_skill(SKILLS_DIR / "code_execution")
    return await run(s, "生成 100 个随机整数(1-1000)，计算最大值和最小值，以及前3个出现次数最多的数。", "B4", 8)

# ══════════════════════════════════════════════════════════════════════════════
# C: extract_pdf
# ══════════════════════════════════════════════════════════════════════════════

async def C1():
    sep("C1: extract_pdf — normal")
    _, s = load_flat_skill(SKILLS_DIR / "extract_pdf")
    return await run(s, "列出 extract_pdf 技能支持的功能和使用方法", "C1")

async def C2():
    sep("C2: extract_pdf — missing file")
    _, s = load_flat_skill(SKILLS_DIR / "extract_pdf")
    return await run(s, "提取 /tmp/nonexistent_xyz_12345.pdf 中的文本内容", "C2", 6)

async def C3():
    sep("C3: extract_pdf — features")
    _, s = load_flat_skill(SKILLS_DIR / "extract_pdf")
    return await run(s, "extract_pdf 支持哪些输入来源（本地路径/URL/bytes）？每种来源的典型用法是什么？", "C3", 8)

# ══════════════════════════════════════════════════════════════════════════════
# D: tavily-search
# ══════════════════════════════════════════════════════════════════════════════

async def D1():
    sep("D1: tavily-search — normal")
    _, s = load_flat_skill(SKILLS_DIR / "tavily-search")
    return await run(s, "搜索 DeepSeek v4 的最新信息", "D1", 6)

async def D2():
    sep("D2: tavily-search — multi-topic")
    _, s = load_flat_skill(SKILLS_DIR / "tavily-search")
    return await run(s, "搜索以下两个主题并对比：1) Python 3.14 新特性，2) Rust 2026 最新更新。", "D2", 10)

async def D3():
    sep("D3: tavily-search — edge")
    _, s = load_flat_skill(SKILLS_DIR / "tavily-search")
    return await run(s, "搜索一个空字符串", "D3", 4)

# ══════════════════════════════════════════════════════════════════════════════
# E: web_fetch
# ══════════════════════════════════════════════════════════════════════════════

async def E1():
    sep("E1: web_fetch — normal")
    _, s = load_flat_skill(SKILLS_DIR / "web_fetch")
    return await run(s, "列出 web_fetch 技能支持的功能和使用方法", "E1")

async def E2():
    sep("E2: web_fetch — URL")
    _, s = load_flat_skill(SKILLS_DIR / "web_fetch")
    return await run(s, "抓取 https://example.com 的网页内容，提取标题和主要文本", "E2", 6)

async def E3():
    sep("E3: web_fetch — unreachable")
    _, s = load_flat_skill(SKILLS_DIR / "web_fetch")
    return await run(s, "抓取 https://nonexistent-domain-xyz-12345.invalid/ 的内容", "E3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# F: base64tool
# ══════════════════════════════════════════════════════════════════════════════

async def F1():
    sep("F1: base64tool — normal")
    s = load_zip_skill(SKILLS_DIR / "base64tool-1.0.0.zip")
    return await run(s, "将 'Hello World' Base64 编码，再解码回来验证", "F1")

async def F2():
    sep("F2: base64tool — URL-safe")
    s = load_zip_skill(SKILLS_DIR / "base64tool-1.0.0.zip")
    return await run(s, "将 'a?b=c&d+e' 进行 URL-safe Base64 编码，然后解码回来验证", "F2")

async def F3():
    sep("F3: base64tool — invalid decode")
    s = load_zip_skill(SKILLS_DIR / "base64tool-1.0.0.zip")
    return await run(s, "解码 Base64 字符串 '!!!not-valid-base64!!!' 并报告结果", "F3", 6)

async def F4():
    sep("F4: base64tool — stagnation")
    s = load_zip_skill(SKILLS_DIR / "base64tool-1.0.0.zip")
    return await run(s, "使用 base64tool.py 的 --mode invalid-mode 编码 'hello'，如果失败就一直重试直到成功", "F4", 8)

# ══════════════════════════════════════════════════════════════════════════════
# G: bundle-hash
# ══════════════════════════════════════════════════════════════════════════════

async def G1():
    sep("G1: bundle-hash — normal")
    s = load_zip_skill(SKILLS_DIR / "bundle-hash-1.0.0.zip")
    return await run(s, "计算 bundle-hash 技能 assets 目录中所有文件的 sha256 组合摘要", "G1")

async def G2():
    sep("G2: bundle-hash — verify")
    s = load_zip_skill(SKILLS_DIR / "bundle-hash-1.0.0.zip")
    return await run(s, "先计算 assets 目录的组合 sha256，再用 verify.py 验证这个摘要值是否正确", "G2", 10)

async def G3():
    sep("G3: bundle-hash — missing dir")
    s = load_zip_skill(SKILLS_DIR / "bundle-hash-1.0.0.zip")
    return await run(s, "计算 /tmp/nonexistent_dir_xyz_12345 的组合 sha256", "G3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# H: colorconv
# ══════════════════════════════════════════════════════════════════════════════

async def H1():
    sep("H1: colorconv — normal")
    s = load_zip_skill(SKILLS_DIR / "colorconv-1.0.0.zip")
    return await run(s, "将 #ff8800 转 RGB，再将 RGB(255,136,0) 转回 hex 验证。", "H1")

async def H2():
    sep("H2: colorconv — shorthand")
    s = load_zip_skill(SKILLS_DIR / "colorconv-1.0.0.zip")
    return await run(s, "将 f80 转为 RGB，验证它和 #ff8800 是否相同。", "H2")

async def H3():
    sep("H3: colorconv — edge")
    s = load_zip_skill(SKILLS_DIR / "colorconv-1.0.0.zip")
    return await run(s, "将 '#xyz999' 转换为 RGB，如果失败请报告错误原因。", "H3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# I: config-reader
# ══════════════════════════════════════════════════════════════════════════════

async def I1():
    sep("I1: config-reader — normal")
    s = load_zip_skill(SKILLS_DIR / "config-reader-1.0.0.zip")
    return await run(s, "读取 config-reader 技能自带配置文件中 database.host 的值。", "I1")

async def I2():
    sep("I2: config-reader — missing key")
    s = load_zip_skill(SKILLS_DIR / "config-reader-1.0.0.zip")
    return await run(s, "读取配置文件中 nonexistent.key.path 的值，如果不存在请报告。", "I2", 6)

async def I3():
    sep("I3: config-reader — nested")
    s = load_zip_skill(SKILLS_DIR / "config-reader-1.0.0.zip")
    return await run(s, "读取配置文件中 database 相关的所有键值，列出所有以 database 开头的配置项。", "I3", 8)

# ══════════════════════════════════════════════════════════════════════════════
# J: github
# ══════════════════════════════════════════════════════════════════════════════

async def J1():
    sep("J1: github — normal")
    s = load_zip_skill(SKILLS_DIR / "github-1.0.0.zip")
    return await run(s, "列出 github 技能支持的功能和典型用法", "J1")

async def J2():
    sep("J2: github — status")
    s = load_zip_skill(SKILLS_DIR / "github-1.0.0.zip")
    return await run(s, "检查 gh CLI 是否已安装和认证，输出 gh version 和 gh auth status 的结果", "J2", 6)

async def J3():
    sep("J3: github — edge")
    s = load_zip_skill(SKILLS_DIR / "github-1.0.0.zip")
    return await run(s, "列出 GitHub 仓库 octocat/hello-world 最近的 3 个 issue", "J3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# K: hashgen
# ══════════════════════════════════════════════════════════════════════════════

async def K1():
    sep("K1: hashgen — normal")
    s = load_zip_skill(SKILLS_DIR / "hashgen-1.0.0.zip")
    return await run(s, "计算 'Hello World' 的 sha256 哈希值", "K1")

async def K2():
    sep("K2: hashgen — md5+sha1")
    s = load_zip_skill(SKILLS_DIR / "hashgen-1.0.0.zip")
    return await run(s, "计算 'Hello World' 的 md5 和 sha1 哈希值，对比它们长度。", "K2")

async def K3():
    sep("K3: hashgen — file mode")
    s = load_zip_skill(SKILLS_DIR / "hashgen-1.0.0.zip")
    return await run(s, "计算 hashgen 技能目录下 hashgen.py 脚本本身的 sha256 哈希值。", "K3", 8)

async def K4():
    sep("K4: hashgen — edge")
    s = load_zip_skill(SKILLS_DIR / "hashgen-1.0.0.zip")
    return await run(s, "计算 /tmp/nonexistent_xyz_12345.bin 的 sha256，如果失败请报告。", "K4", 6)

# ══════════════════════════════════════════════════════════════════════════════
# L: jsonfmt
# ══════════════════════════════════════════════════════════════════════════════

async def L1():
    sep("L1: jsonfmt — normal")
    s = load_zip_skill(SKILLS_DIR / "jsonfmt-1.0.0.zip")
    return await run(s, "验证并格式化 JSON '{\"name\":\"test\",\"items\":[1,2,3]}'", "L1")

async def L2():
    sep("L2: jsonfmt — indent")
    s = load_zip_skill(SKILLS_DIR / "jsonfmt-1.0.0.zip")
    return await run(s, "验证 JSON '{\"a\":1,\"b\":{\"c\":[1,2,3]}}'，用 4 空格缩进格式化。", "L2")

async def L3():
    sep("L3: jsonfmt — stagnation")
    s = load_zip_skill(SKILLS_DIR / "jsonfmt-1.0.0.zip")
    return await run(s, "验证 JSON '{invalid json content!!!}' 是否有效，如果无效就一直重试直到成功。", "L3", 6)

async def L4():
    sep("L4: jsonfmt — edge")
    s = load_zip_skill(SKILLS_DIR / "jsonfmt-1.0.0.zip")
    return await run(s, "读取并格式化 /tmp/nonexistent_json_xyz_12345.json 文件。", "L4", 6)

# ══════════════════════════════════════════════════════════════════════════════
# M: pwdgen
# ══════════════════════════════════════════════════════════════════════════════

async def M1():
    sep("M1: pwdgen — normal")
    s = load_zip_skill(SKILLS_DIR / "pwdgen-1.0.0.zip")
    return await run(s, "生成一个长度 20 的随机密码，包含字母、数字和符号。", "M1")

async def M2():
    sep("M2: pwdgen — flags")
    s = load_zip_skill(SKILLS_DIR / "pwdgen-1.0.0.zip")
    return await run(s, "生成两个密码：1) 长度16 不含符号 2) 长度12 不含数字。对比字符组成。", "M2", 10)

async def M3():
    sep("M3: pwdgen — edge")
    s = load_zip_skill(SKILLS_DIR / "pwdgen-1.0.0.zip")
    return await run(s, "生成一个长度 3 的密码（如果长度无效，请报告错误并说明有效范围）。", "M3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# N: sql-toolkit
# ══════════════════════════════════════════════════════════════════════════════

async def N1():
    sep("N1: sql-toolkit — normal")
    s = load_zip_skill(SKILLS_DIR / "sql-toolkit-1.0.0.zip")
    return await run(s, "列出 sql-toolkit 支持的功能和典型用法", "N1")

async def N2():
    sep("N2: sql-toolkit — practical")
    s = load_zip_skill(SKILLS_DIR / "sql-toolkit-1.0.0.zip")
    return await run(s, "创建一个 SQLite 内存数据库，定义 users 表(id,name,email)，插入 3 条测试数据，然后查询所有用户。", "N2", 10)

async def N3():
    sep("N3: sql-toolkit — edge")
    s = load_zip_skill(SKILLS_DIR / "sql-toolkit-1.0.0.zip")
    return await run(s, "对比 SQLite、PostgreSQL、MySQL 三种数据库在创建自增主键时的语法差异，并给出示例。", "N3", 8)

# ══════════════════════════════════════════════════════════════════════════════
# O: timestamp
# ══════════════════════════════════════════════════════════════════════════════

async def O1():
    sep("O1: timestamp — normal")
    s = load_zip_skill(SKILLS_DIR / "timestamp-1.0.0.zip")
    return await run(s, "将 Unix 时间戳 1700000000 转换为 ISO-8601，再转换回来验证。", "O1")

async def O2():
    sep("O2: timestamp — UTC vs local")
    s = load_zip_skill(SKILLS_DIR / "timestamp-1.0.0.zip")
    return await run(s, "将时间戳 1700000000 分别用 UTC 和 local 时区转换，对比差异。", "O2")

async def O3():
    sep("O3: timestamp — edge")
    s = load_zip_skill(SKILLS_DIR / "timestamp-1.0.0.zip")
    return await run(s, "将 'not-a-timestamp' 转换为日期时间，如果失败请报告错误原因。", "O3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# P: urlparse
# ══════════════════════════════════════════════════════════════════════════════

async def P1():
    sep("P1: urlparse — normal")
    s = load_zip_skill(SKILLS_DIR / "urlparse-1.0.0.zip")
    return await run(s, "解析 URL 'https://user:pass@example.com:8080/path?q=hello&lang=en#section' 并列出所有组成部分。", "P1")

async def P2():
    sep("P2: urlparse — simple")
    s = load_zip_skill(SKILLS_DIR / "urlparse-1.0.0.zip")
    return await run(s, "解析 URL 'https://example.com' 并列出所有组成部分（包括空值字段）。", "P2")

async def P3():
    sep("P3: urlparse — edge")
    s = load_zip_skill(SKILLS_DIR / "urlparse-1.0.0.zip")
    return await run(s, "解析 URL 'example.com:8080/path?q=1#frag'（没有 scheme 前缀），看看解析结果是什么。", "P3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# Q: uuidgen
# ══════════════════════════════════════════════════════════════════════════════

async def Q1():
    sep("Q1: uuidgen — normal")
    s = load_zip_skill(SKILLS_DIR / "uuidgen-1.0.0.zip")
    return await run(s, "生成 5 个 v4 UUID 并输出。", "Q1")

async def Q2():
    sep("Q2: uuidgen — uppercase")
    s = load_zip_skill(SKILLS_DIR / "uuidgen-1.0.0.zip")
    return await run(s, "生成 3 个大写的 v4 UUID（使用 --upper 标志）。", "Q2")

async def Q3():
    sep("Q3: uuidgen — edge")
    s = load_zip_skill(SKILLS_DIR / "uuidgen-1.0.0.zip")
    return await run(s, "生成 0 个 UUID（如果 count=0 无效，请报告错误并说明有效范围）。", "Q3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# R: weather
# ══════════════════════════════════════════════════════════════════════════════

async def R1():
    sep("R1: weather — normal")
    s = load_zip_skill(SKILLS_DIR / "weather-1.0.0.zip")
    return await run(s, "查询北京市当前的天气，包括温度、湿度和风速。", "R1", 6)

async def R2():
    sep("R2: weather — format")
    s = load_zip_skill(SKILLS_DIR / "weather-1.0.0.zip")
    return await run(s, "查询伦敦的天气，使用 wttr.in 的 format=3 格式（简洁一行输出）。", "R2", 6)

async def R3():
    sep("R3: weather — edge")
    s = load_zip_skill(SKILLS_DIR / "weather-1.0.0.zip")
    return await run(s, "查询城市 'Xyzzy-Not-A-Real-City-12345' 的天气，如果失败请报告。", "R3", 6)

# ══════════════════════════════════════════════════════════════════════════════
# S: wordcount
# ══════════════════════════════════════════════════════════════════════════════

async def S1():
    sep("S1: wordcount — normal")
    s = load_zip_skill(SKILLS_DIR / "wordcount-1.0.0.zip")
    return await run(s, "统计 'Hello World! This is a test string with several words.' 的单词数、行数和字符数。", "S1")

async def S2():
    sep("S2: wordcount — empty")
    s = load_zip_skill(SKILLS_DIR / "wordcount-1.0.0.zip")
    return await run(s, "统计空字符串 '' 的单词数、行数和字符数。", "S2")

async def S3():
    sep("S3: wordcount — multiline")
    s = load_zip_skill(SKILLS_DIR / "wordcount-1.0.0.zip")
    return await run(s, "统计以下多行文本的单词数、行数和字符数：\n第一行：Hello World\n第二行：This is a test\n第三行：Goodbye!", "S3")

# ══════════════════════════════════════════════════════════════════════════════
# T: Cross-cutting
# ══════════════════════════════════════════════════════════════════════════════

async def T1():
    sep("T1: plan_cmd repeated failure")
    s = await mk_skill(["plan_cmd", "finish"])
    return await run(s, "执行 'python3 --invalid-flag-xyz-test-12345' 并报告结果。", "T1", 10)

async def T2():
    sep("T2: destructive blocked + adaptation")
    s = await mk_skill(["plan_cmd", "finish"])
    return await run(s, "删除 /tmp/old_logs 目录。如果删除被拦截，改用 ls 列出目录内容，并告诉我如何手动删除。", "T2", 6)

async def T3():
    sep("T3: non-existent tool")
    s = await mk_skill(["plan_cmd", "finish"])
    return await run(s, "使用 upload_file 工具上传一个文件到服务器。", "T3", 4)

async def T4():
    sep("T4: concurrent plan_cmd")
    s = await mk_skill(["plan_cmd", "finish"])
    return await run(s, "同时执行以下两条命令：1) ls -la /tmp，2) whoami。", "T4", 6)

async def T5():
    sep("T5: ambiguous query")
    s = await mk_skill(["plan_cmd", "finish"])
    return await run(s, "?", "T5", 4)


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

async def main():

    results = []
    for name, fn in TESTS:
        try:
            r = await fn()
            results.append((name, "PASSED", r))
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            results.append((name, "FAILED", None))

    sep("SUMMARY")
    for name, st, r in results:
        f = "✅" if st == "PASSED" else "❌"
        if r:
            th = r.get("tool_history", [])
            fa = r.get("final_answer", "")
            b, e = _count(th, "status", "blocked"), _count(th, "is_error", True)
            extra = (f" blk{b}" if b else "") + (f" err{e}" if e else "") + (" stag" if _stag(th) else "")
            print(f"  {f} {name}: {len(th)} steps{extra} | {fa[:80]}{'...' if len(fa)>80 else ''}")
        else:
            print(f"  {f} {name}: error")

    p = sum(1 for _, s, _ in results if s == "PASSED")
    print(f"\n  Total: {p}/{len(results)} passed ({p*100//len(results)}%)")

    sep("GROUP BREAKDOWN")
    for g in [
        ("A:read-code", "A1 A2 A3 A4"), ("B:code_exec", "B1 B2 B3 B4"),
        ("C:extract_pdf", "C1 C2 C3"), ("D:tavily", "D1 D2 D3"),
        ("E:web_fetch", "E1 E2 E3"), ("F:base64tool", "F1 F2 F3 F4"),
        ("G:bundle-hash", "G1 G2 G3"), ("H:colorconv", "H1 H2 H3"),
        ("I:config-reader", "I1 I2 I3"), ("J:github", "J1 J2 J3"),
        ("K:hashgen", "K1 K2 K3 K4"), ("L:jsonfmt", "L1 L2 L3 L4"),
        ("M:pwdgen", "M1 M2 M3"), ("N:sql-toolkit", "N1 N2 N3"),
        ("O:timestamp", "O1 O2 O3"), ("P:urlparse", "P1 P2 P3"),
        ("Q:uuidgen", "Q1 Q2 Q3"), ("R:weather", "R1 R2 R3"),
        ("S:wordcount", "S1 S2 S3"), ("T:cross-cutting", "T1 T2 T3 T4 T5"),
    ]:
        ids = g[1].split()
        pg = sum(1 for n, s, _ in results if any(n.startswith(i) for i in ids) and s == "PASSED")
        print(f"  {g[0]}: {pg}/{len(ids)}")


# ══════════════════════════════════════════════════════════════════════════════
# Batch mode — run subsets of tests from CLI
TESTS = [
("A1:read-code", A1), ("A2:read-code stag", A2), ("A3:read-code multi", A3), ("A4:read-code search", A4),
("B1:code_exec", B1), ("B2:code_exec bad", B2), ("B3:code_exec complex", B3), ("B4:code_exec pipe", B4),
("C1:extract_pdf", C1), ("C2:extract_pdf missing", C2), ("C3:extract_pdf features", C3),
("D1:tavily", D1), ("D2:tavily multi", D2), ("D3:tavily edge", D3),
("E1:web_fetch", E1), ("E2:web_fetch URL", E2), ("E3:web_fetch unreachable", E3),
("F1:base64tool", F1), ("F2:base64tool url-safe", F2), ("F3:base64tool invalid", F3), ("F4:base64tool stag", F4),
("G1:bundle-hash", G1), ("G2:bundle-hash verify", G2), ("G3:bundle-hash missing", G3),
("H1:colorconv", H1), ("H2:colorconv short", H2), ("H3:colorconv edge", H3),
("I1:config-reader", I1), ("I2:config-reader missing", I2), ("I3:config-reader nested", I3),
("J1:github", J1), ("J2:github status", J2), ("J3:github edge", J3),
("K1:hashgen", K1), ("K2:hashgen md5", K2), ("K3:hashgen file", K3), ("K4:hashgen edge", K4),
("L1:jsonfmt", L1), ("L2:jsonfmt indent", L2), ("L3:jsonfmt stag", L3), ("L4:jsonfmt edge", L4),
("M1:pwdgen", M1), ("M2:pwdgen flags", M2), ("M3:pwdgen edge", M3),
("N1:sql-toolkit", N1), ("N2:sql-toolkit practical", N2), ("N3:sql-toolkit edge", N3),
("O1:timestamp", O1), ("O2:timestamp utc", O2), ("O3:timestamp edge", O3),
("P1:urlparse", P1), ("P2:urlparse simple", P2), ("P3:urlparse edge", P3),
("Q1:uuidgen", Q1), ("Q2:uuidgen upper", Q2), ("Q3:uuidgen edge", Q3),
("R1:weather", R1), ("R2:weather format", R2), ("R3:weather edge", R3),
("S1:wordcount", S1), ("S2:wordcount empty", S2), ("S3:wordcount multi", S3),
("T1:plan_cmd stag", T1), ("T2:destructive", T2), ("T3:tool not found", T3), ("T4:concurrent", T4), ("T5:ambiguous", T5),
]

# ══════════════════════════════════════════════════════════════════════════════

BATCHES = {
    "1": ["A1", "A2", "B1", "B2", "C1", "C2"],                     # 6  Dir-based fast
    "2": ["A3", "A4", "B3", "B4", "C3", "D1", "D2", "D3"],         # 8  Dir-based slow
    "3": ["E1", "E2", "E3", "J1", "J2", "J3", "R1", "R2", "R3"],   # 9  Network
    "4": ["F1", "F2", "F3", "F4", "K1", "K2", "K3", "K4"],         # 8  CLI tools 1
    "5": ["L1", "L2", "L3", "L4", "M1", "M2", "M3", "O1", "O2", "O3", "Q1", "Q2", "Q3"],  # 13 CLI tools 2
    "6": ["G1", "G2", "G3", "H1", "H2", "H3", "I1", "I2", "I3", "P1", "P2", "P3", "S1", "S2", "S3"],  # 15 CLI tools 3
    "7": ["N1", "N2", "N3"],                                        # 3  SQL
    "8": ["T1", "T2", "T3", "T4", "T5"],                            # 5  Cross-cutting
    "stag": ["A2", "B2", "F4", "L3", "T1"],                          # 5  Stagnation only
    "net": ["D1", "D2", "D3", "E1", "E2", "E3", "J1", "J2", "J3", "R1", "R2", "R3"],  # 12 Network
    "cli": ["F1","F2","F3","F4","G1","G2","G3","H1","H2","H3","I1","I2","I3","K1","K2","K3","K4","L1","L2","L3","L4","M1","M2","M3","O1","O2","O3","P1","P2","P3","Q1","Q2","Q3","S1","S2","S3"],  # 36 CLI
    "dir": ["A1","A2","A3","A4","B1","B2","B3","B4","C1","C2","C3"],  # 11 Dir-based
    "zips": ["F1","F2","F3","F4","G1","G2","G3","H1","H2","H3","I1","I2","I3","J1","J2","J3","K1","K2","K3","K4","L1","L2","L3","L4","M1","M2","M3","N1","N2","N3","O1","O2","O3","P1","P2","P3","Q1","Q2","Q3","R1","R2","R3","S1","S2","S3"],  # 45 Zip
    "cross": ["T1","T2","T3","T4","T5"],                             # 5  Cross-cutting
}


def _name_to_fn(name: str):
    """Map test prefix to function."""
    mapping = {}
    for n, fn in TESTS:
        mapping[n.split(":")[0]] = fn
    for prefix in list(mapping.keys()):
        for n, fn in TESTS:
            if n.startswith(prefix):
                mapping[prefix] = fn
                break
    return mapping.get(name.split(":")[0])


async def run_batch(batch_id: str):
    """Run a single batch of tests."""
    if batch_id not in BATCHES:
        print(f"Unknown batch: {batch_id}. Available: {sorted(BATCHES.keys())}")
        return

    prefixes = BATCHES[batch_id]
    # Collect matching tests
    to_run = [(n, fn) for n, fn in TESTS if any(n.startswith(p) for p in prefixes)]

    if not to_run:
        print(f"No tests matched for batch {batch_id}")
        return

    print(f"\n{'='*70}")
    print(f"  BATCH {batch_id}: {len(to_run)} tests")
    print(f"{'='*70}")

    results = []
    for name, fn in to_run:
        try:
            r = await fn()
            results.append((name, "PASSED", r))
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            results.append((name, "FAILED", None))

    sep(f"BATCH {batch_id} SUMMARY")
    for name, st, r in results:
        f = "✅" if st == "PASSED" else "❌"
        if r:
            th = r.get("tool_history", [])
            fa = r.get("final_answer", "")
            b = _count(th, "status", "blocked")
            extra = (f" blk{b}" if b else "") + (" stag" if _stag(th) else "")
            print(f"  {f} {name}: {len(th)} steps{extra} | {fa[:80]}{'...' if len(fa)>80 else ''}")
        else:
            print(f"  {f} {name}: error")

    p = sum(1 for _, s, _ in results if s == "PASSED")
    print(f"\n  Batch {batch_id}: {p}/{len(results)} passed ({p*100//len(results)}%)")


async def run_all():
    """Run all tests in order."""
    results = []
    for name, fn in TESTS:
        try:
            r = await fn()
            results.append((name, "PASSED", r))
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            results.append((name, "FAILED", None))

    sep("SUMMARY")
    for name, st, r in results:
        f = "✅" if st == "PASSED" else "❌"
        if r:
            th = r.get("tool_history", [])
            fa = r.get("final_answer", "")
            b, e = _count(th, "status", "blocked"), _count(th, "is_error", True)
            extra = (f" blk{b}" if b else "") + (f" err{e}" if e else "") + (" stag" if _stag(th) else "")
            print(f"  {f} {name}: {len(th)} steps{extra} | {fa[:80]}{'...' if len(fa)>80 else ''}")
        else:
            print(f"  {f} {name}: error")

    p = sum(1 for _, s, _ in results if s == "PASSED")
    print(f"\n  Total: {p}/{len(results)} passed ({p*100//len(results)}%)")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run skill stability tests")
    parser.add_argument(
        "batch", nargs="?", default="all",
        help=f"Batch ID or 'all'. Available: {sorted(BATCHES.keys())} (plus 'all')"
    )
    parser.add_argument(
        "--list", action="store_true", help="List available batches and their tests"
    )
    args = parser.parse_args()

    if args.list:
        print("Available batches:")
        for bid, prefixes in sorted(BATCHES.items()):
            count = len([n for n, _ in TESTS if any(n.startswith(p) for p in prefixes)])
            print(f"  {bid}: {count} tests — {', '.join(prefixes)}")
        print(f"\n  all: {len(TESTS)} tests — all")
        sys.exit(0)

    if args.batch == "all":
        asyncio.run(run_all())
    else:
        asyncio.run(run_batch(args.batch))