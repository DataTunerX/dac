"""End-to-end smoke test for skill_sdk.skill.runner.SkillRunner.

Run with:

    python3 test.py

Before running, put real skill zip packages under ``./skills/``
and replace the ``api_key`` below with a valid credential.

For PDF multimodal via ``extract_pdf``, replace the placeholder values in the
``PDF_VISION_*`` env vars (see below ``os.environ.setdefault(...)`` block).
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

# -----------------------------------------------------------------------------
# PDF 多模态（extract_pdf → extract_local_pdfs_with_vision）：runner 从环境读取，pdf.py 再判是否可调 Vision。
# 占位值请按需改成真实的 model / provider / key；不配全则只走本地 PyMuPDF。
# 测试 extract_pdf skill的时候需要设置
# -----------------------------------------------------------------------------
os.environ.setdefault("PDF_VISION_MODEL", "qwen-vl-ocr-latest")
os.environ.setdefault("PDF_VISION_PROVIDER", "dashscope")
os.environ.setdefault("PDF_VISION_API_KEY", "sk-xxx")
os.environ.setdefault(
    "PDF_VISION_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)
os.environ.setdefault("PDF_VISION_MAX_TOKENS", "8192")
os.environ.setdefault("PDF_VISION_PROMPT", "请用中文描述这一页的所有内容。")


# TAVILY_API_KEY , 测试 tavily-search skill的时候需要设置
os.environ.setdefault("TAVILY_API_KEY", "xxx")


from langchain_core.messages import HumanMessage
from model_sdk import ModelManager
from skill_sdk.skill.runner import SkillRunner
from skill_sdk.tool.code_execution import CodeExecution

# from skill_sdk import SkillRunner


HERE = Path(__file__).parent.resolve()
SKILLS_DIR = HERE / "skills"


DASHSCOPE_API_KEY = os.environ.get(
    "OPENAI_API_KEY", "sk-xxx"
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-flash"


def build_llm():
    manager = ModelManager()
    return manager.get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        # model="deepseek-v3.2",
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def build_code_execution(llm) -> CodeExecution:
    """构造一个 ``CodeExecution`` 实例供 ``SkillRunner`` 注入。

    与 ``SkillRunner`` **共用同一份** ``llm``，避免 ``CodeExecution`` 里再
    ``get_llm`` 一次（重复建连接与配置）。

    仅当 ``SkillRunner(..., code_execution=...)`` 时才会把 ``code_exec`` 绑给
    模型。``metadata.trace_id`` 用 32 位 hex，满足 Langfuse 对 trace_id 的格式要求。
    """
    return CodeExecution(
        llm=llm,
        max_retries=3,
    )


def print_section(title: str) -> None:
    line = "=" * max(60, len(title) + 4)
    print(f"\n{line}\n{title}\n{line}")


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


async def demo_smoke(llm) -> None:
    print_section("Smoke: single LLM call")
    result = await llm.ainvoke([HumanMessage(content="Hello, reply one word.")])
    print(result.content)


async def demo_make_plan(runner: SkillRunner, query: str) -> None:
    print_section(f"make_plan: {query}")
    step = await runner.make_plan(query=query)
    print(dump(step.model_dump()))


async def demo_plan_and_run(runner: SkillRunner, query: str) -> None:
    print_section(f"plan_and_run: {query}")
    result = await runner.plan_and_run(query=query, user_id="user01", run_id="run01", trace_id="abcdef1234567890abcdef1234567890")
    print(dump(result))


async def main() -> None:
    llm = build_llm()

    runner = SkillRunner(
        llm=llm,
        max_steps=100,
        cmd_timeout_sec=60,
        same_cmd_fail_budget=2,
        total_fail_budget=3,
        make_plan_max_attempts=3,
        code_execution=build_code_execution(llm),
    )

    if not SKILLS_DIR.is_dir():
        raise SystemExit(
            f"Skills directory not found: {SKILLS_DIR}. "
            "Put *.zip skill packages there before running the test."
        )

    skills = runner.load_from_dir(SKILLS_DIR)
    print_section("Loaded skills")
    print(runner.lister.list_skills())
    print(f"Total: {len(skills)} skill(s)")

    try:
        
        # 00-weather
        # await demo_plan_and_run(runner, "帮我查一下上海现在的天气，用一行简短输出")

        # 01-github
        # await demo_plan_and_run(runner, "看看https://github.com/DataTunerX/dac 这个仓库的分支有哪些")

        # 02-hashgen
        # await demo_plan_and_run(runner, "帮我算一下字符串 'hello world' 的 sha256 值。")

        # 03-wordcount
        # await demo_plan_and_run(runner, "这段话里有多少个单词、多少行、多少字符？\nThe quick brown fox jumps over the lazy dog.\nSphinx of black quartz, judge my vow.")

        # 04-uuidgen
        await demo_plan_and_run(runner, "帮我生成 3 个 UUID。")

        # 05-timestamp
        # await demo_plan_and_run(runner, "把 unix 时间戳 1700000000 转换成对应的 UTC 人类可读时间。")

        # 06-jsonfmt
        # await demo_plan_and_run(runner, "校验这段 JSON 是否合法，如果合法就帮我美化一下：{\"a\":1,\"b\":[2,3],\"c\":{\"d\":true}}")

        # 07-base64tool
        # await demo_plan_and_run(runner, "把字符串 'open sesame' 做 base64 编码。")

        # 08-urlparse
        # await demo_plan_and_run(runner, "解析这个 URL：https://alice:s3cret@example.com:8443/a/b?x=1&y=2#frag")

        # 09-pwdgen
        # await demo_plan_and_run(runner, "生成一个长度为 16、不包含符号的随机密码。")

        # 10-regextest
        # await demo_plan_and_run(runner, "在字符串 'call 555-1212 or 555-3434 today' 里，用正则 \\d{3}-\\d{4} 找出所有匹配的电话号码。")

        # 11-colorconv
        # await demo_plan_and_run(runner, "把十六进制颜色 #ff8800 转换成 RGB。")

        # 12-faq-lookup
        # await demo_plan_and_run(runner, "在 faq-lookup skill 自带的 FAQ 里，查一下跟 'reset password' 相关的问答。")

        # 13-template-renderer
        # await demo_plan_and_run(runner, "用 template-renderer 的 greeting 模板，把 name=Alice、product=Clawdbot、date=2026-05-01 代入，输出最终问候语。")

        # 14-bundle-hash
        # await demo_plan_and_run(runner, "用 bundle-hash 计算它自带 assets 目录下所有文件合并后的 sha256，同时告诉我文件数量和总字节数。")

        # # 15-config-reader
        # await demo_plan_and_run(runner, "用 config-reader 从自带的 config.json 里取出 database.credentials.user 的值。")

        # 16-doc-finder
        # await demo_plan_and_run(runner, "在 doc-finder 自带的参考文档里，忽略大小写找出所有包含 'tenant' 的行，告诉我每条命中的文件名、行号和内容。")

        # 17-web-fetch
        # await demo_plan_and_run(runner, "在https://www.python.org/downloads/release/python-3120/ 这个地址中有哪些 New features")

        # 18-code-execution
        # await demo_plan_and_run(runner, "从 1 到 100 所有奇数的平方和是多少")

        # 19-tavily-search
        # 测试前要设置env ， TAVILY_BASE_URL='https://api.tavily.com' TAVILY_API_KEY='xxx'
        # await demo_plan_and_run(runner, "通过TAVILY，查询一下golang有哪些特性")

        # 20-file-search
        # await demo_plan_and_run(runner, "在 /Users/james/daocloud/code/dac/orchestrator-agent 目录下查找所有以 .md 结尾的文件,并读取其中任意一个文件")

        # 21-pdf-extractor
        # await demo_plan_and_run(runner, "分析一下dac/tests-data/files/laws.pdf 这个文件")
        # await demo_plan_and_run(runner, "分析一下dac/tests-data/files/manual-1page.pdf 这个文件， 看看有没有使用到chatopenai这个python库")
        # await demo_plan_and_run(runner, "分析一下dac/tests-data/files/manual-2pages.pdf 这个文件， 看看有没有使用到chatopenai这个python库")
        # await demo_plan_and_run(runner, "分析一下https://arxiv.org/pdf/2401.00001.pdf 这个文件")
        # await demo_plan_and_run(runner, "读取这个https://arxiv.org/pdf/2401.00001.pdf pdf文件，分析一下这个文件在干什么？")

        # 22 lsp
        # await demo_plan_and_run(runner, "分析一下/Users/james/daocloud/code/dac/dac-apiserver这个repo，看看SendMessageStreaming的代码块是什么")

        # await demo_plan_and_run(runner, "看看/Users/james/daocloud/code/dac/skill_sdk/skill_sdk/tool/lsp_plugin.py里_get_or_create_manager调用了哪个方法，它的代码是什么")

    finally:
        runner.close()

if __name__ == "__main__":
    asyncio.run(main())
        