from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import time as _time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.prompts.chat import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.tools import tool
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, Field

from skill_sdk.api.base import Skill
from skill_sdk.plugin.registry import ToolRegistry
from skill_sdk.skill.lister import SkillLister
from skill_sdk.skill.loader import SkillLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

logger = logging.getLogger(__name__)

langfuse = get_client()

if os.getenv("LANGFUSE_AUTH_CHECK", "disable") == "enable":
    if langfuse.auth_check():
        logger.info("Langfuse client is authenticated and ready!")
    else:
        logger.error("Langfuse authentication failed. Please check credentials and host.")

langfuse_handler = CallbackHandler()


def _now_context() -> str:
    """Localized 'now' string injected into prompts so the LLM has a time anchor.

    Example: `2026-04-18 17:42:03 +0800 (CST, 周六)`
    """
    now = datetime.now().astimezone()
    tz_name = _time.strftime("%Z") or now.tzname() or ""
    weekday_zh = "一二三四五六日"[now.weekday()]
    return (
        f"{now.strftime('%Y-%m-%d %H:%M:%S %z')}"
        f" ({tz_name}, 周{weekday_zh})"
    )


PLANNER_INSTRUCTIONS_ZH = """# 角色：Skill Planner

## 使命
根据用户问题，从「可用技能」中选择最合适的一个 skill。

## 当前时间
{current_time}
> 所有对"现在"、"今天"、"最近 N 天"等相对时间的理解都以此为基准。

## 可用技能
{skills}

## 规则
1. 严格基于 skill 的 name 和 description 做语义匹配。
2. **必须**二选一调用下面两个工具之一，**不要**直接输出文本/JSON：
   - `select_skill`：选中一个合适的 skill；`skill` 字段必须**严格等于**上面列表中某个 name（区分度不依赖大小写，但拼写必须一致）。
   - `no_suitable_skill`：当列表中确实没有任何 skill 能胜任当前问题时，用它明确拒绝；请在 `reason` 里写明为什么都不合适。
3. 不要把 `select_skill` 的 `skill` 字段设为空字符串来表示拒绝——请改用 `no_suitable_skill`。
4. 不要选择明显和用户问题无关的 skill 来凑数；宁可调用 `no_suitable_skill`。
5. `reason` 简要说明选择理由或拒绝理由。
"""

RUNNER_INSTRUCTIONS_ZH = """# 角色：Skill Runner

## 使命
根据给定 skill 的说明和用户问题，通过工具完成任务。

## 当前时间
{current_time}
> 所有对"现在"、"今天"、"最近 N 天"、日志/返回里时间戳的理解都以此为基准；**不要**用模型自带的知识截止时间替代它。

## 当前 skill
- name: {skill_name}
- description: {skill_description}

## skill 详细说明（来自 SKILL.md）
{skill_detail}

## skill 目录布局与资源
{skill_scripts}

> 调用脚本时**优先复用上方 `invocation` 字段**（已包含推荐解释器）。
> 若 `interpreter` 为 `(unknown interpreter)`，先用 `read_file` 读脚本头几行或用 `<path> --help` 试探，不要瞎猜。
> 脚本可能依赖 `scripts_dir` 里的同目录资源，必要时把 `plan_cmd.cwd` 设为 `scripts_dir` 或 `skill_dir`。
> SKILL.md / 脚本里若出现相对路径（例如 `./references/xxx.md`、`assets/yyy.json`），**请以上面列出的 `skill_dir` 为基准拼成绝对路径**再用 `read_file` 读取；不要直接传相对路径。
> `resource_dirs` 列出的每个目录（如 `assets/`、`references/`、`hooks/`）都已经和 `scripts/` 解压在同一 `skill_dir` 下，可直接访问。

## 工具使用规则
1. **生成命令用 `plan_cmd`**：`cmd` 字段写你想执行的完整 CLI 命令，`rationale` 写为什么这么写。
   - 你不需要自己执行命令，`plan_cmd` 的返回值就是真实执行结果（由 runner 在本地代跑）。
   - 每次只建议一条命令；如需多步，等上一条返回后再继续建议。
   - 优先使用 skill 说明/脚本里给出的命令模式，不要主观臆造；避免破坏性操作。
   - **`rationale` 必须包含两段内容**：
     1. **参照**：本次是首次尝试，还是承接上一次失败？若承接，写出上一条 cmd 与 stderr 的关键首行。
     2. **改动**：这次在 cmd 上具体改了什么（换子命令 / 加参数 / 改路径 / 换 skill 脚本 / 改探测方向）。
   - **禁止的命令（runner 会在执行前直接拦截，返回 `{{"blocked_by_policy": true}}`）**：
     - 文件/目录删除与移动：`rm`, `rmdir`, `unlink`, `mv`, `shred`, `truncate`
       —— 查看文件请用 `ls` / `stat` / `cat` / `head` / `read_file`。
     - 磁盘与系统级：`dd`, `mkfs*`, `fdisk`, `parted`, `mkswap`, `shutdown`, `reboot`, `halt`, `poweroff`, `init`。
     - 进程杀伤：`kill`, `pkill`, `killall`。
     - 就地编辑：`sed -i`, `perl -i`。如需看差异，先 `cat` / `diff`。
     - 仓库破坏性子命令：`git reset --hard`, `git clean -f`, `git push --force`, `git checkout -- <path>`。
     用 `sudo` / `env` 包一层、改别名、拼 `&&` / `|` 都不会绕过拦截；命中后请改成只读探测或直接 `finish`，
     在 `final_answer` 里把需要用户亲自执行的命令列出来。
2. **读取文件用 `read_file`**；**解析 PDF（路径或 URL，提取文本/可选整页图）用 `extract_pdf`**。
3. **完成任务时调用 `finish`**：`final_answer` 写给用户的最终答复。
4. **禁止以纯文本答复**：只要 query 合理且落在当前 skill 能力范围内（由 planner 已经匹配），**必须先用 `plan_cmd` 探测/执行**，不得直接在 content 里写自然语言回答而不调用任何工具；即使你认为 skill 不适用，也应先用 `plan_cmd` 做一次候选探测，再在 `finish.final_answer` 中说明结论。

## 观察与决策规则（每次 plan_cmd 返回后必须执行）
1. 解析返回 JSON：关注 `returncode`、`stdout`、`stderr`。
2. 判定成功：`returncode == 0` 且 `stdout` 能回答用户问题 → 调用 `finish` 汇总。
3. 判定失败：`returncode != 0` 或 `stderr` 含明显错误时：
   - 先执行下面「从失败中学习」的全部步骤，再调用 `plan_cmd`。
   - 同一错误原因重试**不超过 2 次**；仍失败则调用 `finish`，在 `final_answer` 中说明原因与建议。
4. 信息不足时：不要猜测，调用 `read_file` 或用新的 `plan_cmd` 去探测（例如 `gh --help`、`ls`）。
5. 禁止：
   - 在 `finish` 的 `final_answer` 里编造未经 `plan_cmd` 验证的输出；
   - 对已经 `returncode == 0` 的命令反复重跑；
   - 一次发多条 `plan_cmd`（只允许一条）。
6. 若 ToolMessage 返回里出现 `"must_finish": true`，下一轮**必须**调用 `finish`，`final_answer` 中参考 `observation_hint` 说明原因，禁止再发 `plan_cmd`。

## 从失败中学习（生成下一条 plan_cmd 前必须执行）
1. **回顾历史**：查看当前会话里所有历史 `plan_cmd` 的返回：
   - 列出已经尝试过的 cmd 与各自的 `returncode`、`stderr` 首行；
   - 把错误归类为：命令不存在 / 参数无效 / 认证或权限失败 / 路径错误 / 超时 / 其他。
2. **禁止原样重发**：若即将生成的 cmd 字符串已经在历史中失败过（逐字符相同，或仅空白差异），必须改写；不得原样再发一次。
3. **更换思路**：若同一错误类别已经重试过 1 次且仍失败，**换思路**而不是只改参数：
   - 参数错误 → 先用 `<command> --help` 或 skill 文档中的原始样例；
   - 认证/权限错误 → 用 `gh auth status`、`whoami` 或 `read_file` 查配置；
   - 路径错误 → 用 `ls`、`read_file` 核实存在性；
   - 命令不存在 → 检查 skill 可用脚本，或在 `finish` 中告知用户缺失依赖。
4. **不要盲目拼接**：不要把多条已失败的命令用 `&&` / `;` 拼在一起再跑，这只会让所有错误再来一次。
5. **在 rationale 里写出学习结论**：按「工具使用规则」第 1 条要求，明确写「参照上一次失败 XXX，本次改动 YYY」。
"""

MAX_STEPS_SUMMARY_SYSTEM_ZH = """# 角色：步数耗尽后的总结助手

一次 skill 执行已达到**单轮最大步数**上限，模型没有在耗尽前调用 `finish` 正式结束。

## 当前时间
{current_time}
> 写总结时若涉及"现在/今天/最近"等相对时间，请以此为基准。

## 你的任务
根据下面提供的**完整会话转写**（含 System 指令片段、用户问题、各轮 Assistant 与 Tool 返回），写一份给**最终用户**的中文答复。

## 写作要求
1. 开头明确：本回合因「步数上限」结束，下面是**阶段性总结**，不等同于任务已完整交付。
2. 如实概括已经执行了什么、工具返回里有哪些**可核验**的关键事实或输出；**禁止编造**转写中未出现的内容。
3. 若存在失败、超时、策略拦截、缺依赖/API key、权限等问题，说明原因与对结果的影响。
4. 若仍不足以完整回答用户的原始问题，写清**还缺什么信息或条件**，并给出可操作的下一步建议。
5. 结构清晰、语气专业，篇幅以说明白为准（通常不超过约 2000 字）。"""


class PlannerStep(BaseModel):
    """Structured planner result."""

    original_query: str = Field(description="The original user query.")
    skill: str = Field(description="Chosen skill name; empty string if no match.")
    reason: str = Field(default="", description="Short reason for the selection.")
    declined: bool = Field(
        default=False,
        description=(
            "True when the planner explicitly declined via `no_suitable_skill`. "
            "Callers should stop replanning in that case."
        ),
    )


class SelectSkillInput(BaseModel):
    skill: str = Field(description="选择的 skill 名称，必须严格等于「可用技能」中的 name")
    reason: str = Field(default="", description="选择原因，简洁一句")


class NoSuitableSkillInput(BaseModel):
    reason: str = Field(
        default="",
        description="明确说明为什么可用技能列表里没有任何一个能胜任当前问题",
    )


class PlanCmdInput(BaseModel):
    cmd: str = Field(description="要执行的完整 CLI 命令行文本")
    rationale: str = Field(default="", description="为什么要执行这条命令")
    cwd: str | None = Field(default=None, description="命令执行目录，可空")


class ReadFileInput(BaseModel):
    path: str = Field(description="要读取的文件路径")
    max_chars: int = Field(default=8000, ge=1, le=40000, description="最多返回字符数")


class CodeExecInput(BaseModel):
    """``code_exec`` 工具入参（被 runner 拦截真正执行）。

    为了兼容各种 LLM 对"结构化参数"的支持差异，``context_data`` 统一接受
    **字符串**：
      * 传 JSON 文本（``"[1,2,3]"`` / ``'{"k":1}'``）时，runner 会 ``json.loads`` 还原；
      * 传普通字符串（不是合法 JSON），runner 会把它作为 ``str`` 直接喂给沙箱；
      * 不传或空串，等价于 ``context_data=None``，沙箱中 ``data is None``。

    也保留一个 ``max_chars`` 控制**本工具返回**结果摘要（不是 CodeExecution 内部
    ``context_max_chars``）——防止把几 MB 的 ``result`` 原样塞回对话上下文。
    """

    query: str = Field(
        description=(
            "用自然语言描述的 Python 计算任务：应告诉代码该返回什么结果到 ``result``。"
        ),
    )
    context_data: str = Field(
        default="",
        description=(
            "可选上下文数据（JSON 字符串优先；非 JSON 时当作纯字符串；空串视为无数据）。"
        ),
    )
    max_chars: int = Field(
        default=4000,
        ge=100,
        le=40000,
        description="返回结果 JSON 中对 ``result``/``reason``/``code`` 字段的字符截断上限",
    )


class FinishInput(BaseModel):
    final_answer: str = Field(description="任务最终答复")


def _trim_text(text: str, *, max_chars: int = 8000) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...(truncated {len(text) - max_chars} chars)"


def _short(text: Any, *, max_len: int = 200) -> str:
    """Collapse long text into a compact one-line snippet for logging."""
    if text is None:
        return ""
    s = str(text).replace("\n", " ⏎ ")
    if len(s) > max_len:
        s = f"{s[:max_len]}...(+{len(s) - max_len})"
    return s


def _stderr_head(stderr: str | None) -> str:
    if not stderr:
        return ""
    first = stderr.splitlines()[0] if stderr.splitlines() else ""
    return _short(first, max_len=160)


def _tool_result_line_for_summary(tool_name: str, tool_args: dict[str, Any], raw: str) -> str:
    """One markdown-ish line for max-steps summary (best-effort JSON parse)."""
    prefix = f"- **{tool_name}**"
    if tool_name == "plan_cmd":
        cmd = str(tool_args.get("cmd", "") or "")
        prefix += f" `{_short(cmd, max_len=140)}`"
    elif tool_name == "read_file":
        prefix += f" `{_short(tool_args.get('path', ''), max_len=140)}`"
    elif tool_name == "extract_pdf":
        p = tool_args.get("pdf") or ""
        u = (tool_args.get("pdfs") or [""])[0] if isinstance(tool_args.get("pdfs"), list) else ""
        prefix += f" `{_short(p or u, max_len=140)}`"
    elif tool_name == "web_fetch":
        prefix += f" `{_short(tool_args.get('url', ''), max_len=140)}`"
    elif tool_name == "tavily_search":
        prefix += f" `{_short(tool_args.get('query', ''), max_len=1000)}`"
    elif tool_name == "tavily_extract":
        urls = tool_args.get("urls")
        u = urls[0] if isinstance(urls, list) and urls else ""
        prefix += f" `{_short(u, max_len=1000)}`"
    elif tool_name == "code_exec":
        prefix += f" `{_short(tool_args.get('query', ''), max_len=140)}`"

    parsed: Any = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return f"{prefix} {_short(raw, max_len=320)}"

    if not isinstance(parsed, dict):
        return f"{prefix} {_short(raw, max_len=320)}"

    if tool_name == "tavily_search" and parsed.get("provider") == "tavily":
        n = parsed.get("count")
        cached = parsed.get("cached")
        parts = [f"count={n}"]
        if cached:
            parts.append("cached=True")
        if isinstance(parsed.get("results"), list):
            parts.append(f"results={len(parsed['results'])}")
        return f"{prefix} " + ", ".join(parts)

    if tool_name == "tavily_extract" and parsed.get("provider") == "tavily":
        n = parsed.get("count")
        failed = parsed.get("failedResults")
        parts = [f"count={n}"]
        if isinstance(failed, list) and failed:
            parts.append(f"failed={len(failed)}")
        return f"{prefix} " + ", ".join(parts)

    if tool_name == "web_fetch" and "status" in parsed:
        status = parsed.get("status")
        extractor = parsed.get("extractor")
        cached = parsed.get("cached")
        took = parsed.get("took_ms")
        title = _short(str(parsed.get("title") or ""), max_len=80)
        content_snip = _short(
            _trim_text(str(parsed.get("content") or ""), max_chars=400),
            max_len=280,
        )
        parts = [f"status={status}", f"extractor={extractor}"]
        if cached:
            parts.append("cached=True")
        if took is not None:
            parts.append(f"took_ms={took}")
        if title:
            parts.append(f"title: {title}")
        if content_snip:
            parts.append(f"content: {content_snip}")
        return f"{prefix} " + ", ".join(parts)

    if tool_name == "extract_pdf" and isinstance(parsed.get("items"), list):
        n = len(parsed["items"])
        parts = [f"pdfs={n}"]
        if parsed.get("vision_backend_used"):
            parts.append("vision=yes")
        elif "vision_backend_used" in parsed:
            parts.append("vision=no")
        if parsed.get("_truncated"):
            parts.append("truncated")
        if parsed.get("_images_omitted"):
            parts.append("images_omitted")
        return f"{prefix} " + ", ".join(parts)

    if tool_name == "code_exec" and (
        "status" in parsed or "conclusion" in parsed or "result" in parsed
    ):
        status = parsed.get("status")
        conclusion = parsed.get("conclusion")
        aborted = parsed.get("aborted")
        attempts = parsed.get("attempts")
        result_snip = _short(
            _trim_text(str(parsed.get("result") or ""), max_chars=400),
            max_len=280,
        )
        parts: list[str] = []
        if status is not None:
            parts.append(f"status={status}")
        if conclusion is not None:
            parts.append(f"conclusion={conclusion}")
        if aborted:
            parts.append("aborted=True")
        if attempts is not None:
            parts.append(f"attempts={attempts}")
        if result_snip:
            parts.append(f"result: {result_snip}")
        if parsed.get("reason"):
            parts.append(
                f"reason: {_short(str(parsed.get('reason')), max_len=180)}"
            )
        return f"{prefix} " + ", ".join(parts)

    if "returncode" in parsed:
        rc = parsed.get("returncode")
        err = _stderr_head(str(parsed.get("stderr") or ""))
        out = str(parsed.get("stdout") or "")
        out_snip = _short(_trim_text(out, max_chars=500), max_len=360)
        parts = [f"returncode={rc}"]
        if err:
            parts.append(f"stderr 首行: {err}")
        if out_snip:
            parts.append(f"stdout 摘录: {out_snip}")
        return f"{prefix} " + ", ".join(parts)

    if parsed.get("error"):
        return f"{prefix} error={_short(parsed.get('error'), max_len=220)}"

    if "path" in parsed and "content" in parsed:
        return f"{prefix} 内容摘录: {_short(str(parsed.get('content') or ''), max_len=420)}"

    if parsed.get("blocked_by_policy"):
        return f"{prefix} policy={_short(parsed.get('reason') or raw, max_len=240)}"

    if parsed.get("must_finish"):
        return f"{prefix} must_finish hint={_short(parsed.get('observation_hint') or raw, max_len=280)}"

    return f"{prefix} {_short(raw, max_len=320)}"


def _summarize_max_steps_state(
    tool_history: list[dict[str, Any]],
    *,
    max_steps: int,
    total_fails: int,
    max_answer_chars: int = 12000,
) -> str:
    """User-facing summary when the ReAct loop exhausts `max_steps` without `finish`."""
    lines: list[str] = [
        f"本回合已达到单轮最大步数（{max_steps} 步），模型未在步数耗尽前调用 `finish`。"
        "下面是根据当前已执行工具与返回整理的摘要，便于判断进展与下一步。",
    ]
    if total_fails:
        lines.append(f"（全程 `plan_cmd` 失败累计：{total_fails} 次）")

    tool_names = [e["tool"] for e in tool_history if "tool" in e]
    if tool_names:
        lines.append("")
        lines.append(f"**已调用工具序列**：{' → '.join(tool_names)}")

    last_thought = ""
    last_reasoning = ""
    for e in reversed(tool_history):
        if "thought" not in e:
            continue
        t = str(e.get("thought") or "").strip()
        r = str(e.get("reasoning") or "").strip()
        if t or r:
            last_thought, last_reasoning = t, r
            break
    if last_thought or last_reasoning:
        lines.append("")
        lines.append("**模型最后一轮思考摘要**")
        if last_reasoning:
            lines.append(f"- reasoning: {_trim_text(last_reasoning, max_chars=1400)}")
        if last_thought:
            lines.append(f"- content: {_trim_text(last_thought, max_chars=1400)}")

    tool_entries = [e for e in tool_history if "tool" in e]
    if tool_entries:
        lines.append("")
        lines.append("**近期工具结果摘录**（最多 5 条，从新到旧）")
        for e in reversed(tool_entries[-5:]):
            lines.append(
                _tool_result_line_for_summary(
                    str(e.get("tool", "")),
                    (e.get("args") or {}) if isinstance(e.get("args"), dict) else {},
                    str(e.get("result", "")),
                )
            )

    body = "\n".join(lines)
    if len(body) > max_answer_chars:
        body = _trim_text(body, max_chars=max_answer_chars)
    return body


def _format_conversation_for_max_steps_summary(
    messages: Sequence[Any],
    *,
    per_block_max: int = 8000,
    transcript_max: int = 100_000,
) -> str:
    """Flatten ReAct messages into text for the max-steps summarizer LLM."""
    parts: list[str] = []
    for i, m in enumerate(messages):
        if isinstance(m, SystemMessage):
            label = "System"
            body = _trim_text(str(m.content), max_chars=per_block_max)
        elif isinstance(m, HumanMessage):
            label = "Human"
            body = _trim_text(str(m.content), max_chars=per_block_max)
        elif isinstance(m, AIMessage):
            label = "Assistant"
            text = _trim_text(str(getattr(m, "content", "") or ""), max_chars=per_block_max)
            tool_calls = getattr(m, "tool_calls", None) or []
            try:
                tc_raw = json.dumps(tool_calls, ensure_ascii=False, default=str)
            except TypeError:
                tc_raw = str(tool_calls)
            tc_raw = _trim_text(tc_raw, max_chars=min(per_block_max, 6000))
            body = f"{text}\n[tool_calls]\n{tc_raw}"
        elif isinstance(m, ToolMessage):
            label = "Tool"
            body = _trim_text(str(m.content), max_chars=per_block_max)
        else:
            label = type(m).__name__
            body = _trim_text(str(getattr(m, "content", "")), max_chars=per_block_max)
        parts.append(f"### [{i}] {label}\n{body}")
    return _trim_text("\n\n".join(parts), max_chars=transcript_max)


# ---------------------------------------------------------------------------
# Destructive-command guardrail
# ---------------------------------------------------------------------------
#
# `plan_cmd` is executed for real by the runner, so we must refuse commands
# that mutate the user's environment (delete/overwrite files, disks, processes,
# git history, etc.). The check is a best-effort static scan of the command
# string — it is NOT a security sandbox, just a safety net against LLM slips.
#
# Operators can extend/override the defaults by passing ``blocked_commands`` /
# ``extra_destructive_patterns`` / ``allow_destructive_commands=True`` to
# :class:`SkillRunner`.

DESTRUCTIVE_COMMAND_NAMES: frozenset[str] = frozenset({
    # File/dir mutation
    "rm", "rmdir", "unlink", "mv", "shred", "truncate",
    # Disk / filesystem / system
    "dd", "mkfs", "fdisk", "parted", "mkswap",
    "shutdown", "reboot", "halt", "poweroff", "init",
    # Process kill
    "kill", "pkill", "killall",
})

# "Looks benign but has a destructive flag" — matched on the whole command.
DESTRUCTIVE_FLAG_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bsed\b[^|;&]*\s-i\b"), "sed -i (in-place edit)"),
    (re.compile(r"\bperl\b[^|;&]*\s-i\b"), "perl -i (in-place edit)"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\s+-[A-Za-z]*[fx]"), "git clean -f"),
    (
        re.compile(r"\bgit\s+push\b[^|;&]*\s(?:--force\b|-f\b)"),
        "git push --force",
    ),
    (re.compile(r"\bgit\s+checkout\s+--\s"), "git checkout -- <path>"),
    (re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "fork bomb"),
)

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELL_SEPARATORS_RE = re.compile(r"\|\||&&|;|\||\n")
_CMD_WRAPPERS = frozenset({"sudo", "env", "time", "nice", "ionice", "stdbuf"})


def _check_destructive_cmd(
    cmd: str,
    *,
    blocked_names: frozenset[str] = DESTRUCTIVE_COMMAND_NAMES,
    flag_patterns: Sequence[tuple[re.Pattern[str], str]] = DESTRUCTIVE_FLAG_PATTERNS,
) -> str | None:
    """Return a reason string if ``cmd`` looks destructive, else ``None``.

    The scan splits the command on shell separators (``|``, ``||``, ``&&``,
    ``;``, newline), peels leading env-var assignments and ``sudo``/``env``
    wrappers, then checks the head token against ``blocked_names``. Path
    prefixes are stripped (``/usr/bin/rm`` → ``rm``). ``flag_patterns`` are
    run against the raw command to catch ``sed -i`` / ``git reset --hard`` etc.

    It is intentionally conservative — false negatives are possible (e.g.
    shell-quoted trickery) — but catches the shapes an LLM typically emits.
    """
    if not cmd or not cmd.strip():
        return None

    for segment in _SHELL_SEPARATORS_RE.split(cmd):
        tokens = segment.strip().split()
        while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
            tokens.pop(0)
        while tokens and tokens[0] in _CMD_WRAPPERS:
            tokens.pop(0)
            while tokens and _ENV_ASSIGN_RE.match(tokens[0]):
                tokens.pop(0)
        if not tokens:
            continue
        base = tokens[0].rsplit("/", 1)[-1]
        # Normalize ``mkfs.ext4`` → ``mkfs`` so the whole family is covered.
        base_family = base.split(".", 1)[0]
        if base in blocked_names or base_family in blocked_names:
            return f"command `{base}` is blocked as destructive"

    for pat, reason in flag_patterns:
        if pat.search(cmd):
            return f"blocked pattern: {reason}"

    return None


async def _execute_cmd_async(
    cmd: str,
    *,
    cwd: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    """Runner-internal async command executor. NOT exposed to the LLM as a tool.

    Uses :func:`asyncio.create_subprocess_shell` so the event loop is never blocked
    while the child process runs (important for concurrent orchestrator requests).
    """
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_sec
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
            return {
                "cmd": cmd,
                "cwd": cwd or "",
                "timeout_sec": timeout_sec,
                "error": f"Command timed out after {timeout_sec}s",
            }
        return {
            "cmd": cmd,
            "cwd": cwd or "",
            "returncode": proc.returncode,
            "stdout": _trim_text((stdout_b or b"").decode("utf-8", errors="replace")),
            "stderr": _trim_text((stderr_b or b"").decode("utf-8", errors="replace")),
        }
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        raise
    except Exception as exc:  # noqa: BLE001
        return {"cmd": cmd, "cwd": cwd or "", "error": f"Command execution failed: {exc}"}


@tool("select_skill", args_schema=SelectSkillInput)
def select_skill_tool(skill: str, reason: str = "") -> str:
    """选择一个 skill 名作为规划结果。"""
    return json.dumps({"skill": skill, "reason": reason}, ensure_ascii=False)


@tool("no_suitable_skill", args_schema=NoSuitableSkillInput)
def no_suitable_skill_tool(reason: str = "") -> str:
    """明确拒绝选择：当「可用技能」列表中没有任何一个能胜任当前问题时调用。"""
    return json.dumps({"declined": True, "reason": reason}, ensure_ascii=False)


@tool("plan_cmd", args_schema=PlanCmdInput)
def plan_cmd_tool(cmd: str, rationale: str = "", cwd: str | None = None) -> str:
    """规划一条要执行的 CLI 命令（真实执行由 runner 接管）。"""
    return json.dumps({"cmd": cmd, "rationale": rationale, "cwd": cwd}, ensure_ascii=False)


@tool("read_file", args_schema=ReadFileInput)
def read_file_tool(path: str, max_chars: int = 8000) -> str:
    """读取文件内容（截断返回）。"""
    try:
        file_path = Path(path).expanduser().resolve()
        if not file_path.is_file():
            return json.dumps({"path": str(file_path), "error": "File not found"}, ensure_ascii=False)
        content = file_path.read_text(encoding="utf-8")
        return json.dumps(
            {"path": str(file_path), "content": _trim_text(content, max_chars=max_chars)},
            ensure_ascii=False,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"path": path, "error": f"Read file failed: {exc}"}, ensure_ascii=False)




@tool("code_exec", args_schema=CodeExecInput)
def code_exec_tool(query: str, context_data: str = "", max_chars: int = 4000) -> str:
    """在受限 Python 沙箱里"让 LLM 写代码 + 执行 + 自检"完成一次数据/计算任务。

    这里只是向 ``bind_tools`` 声明参数 schema；真实执行由 ``SkillRunner`` 在
    ``_dispatch_tool`` 中拦截，原因是 ``CodeExecution.run`` 是 ``async``，而
    ``@tool`` 的 ``invoke`` 是同步路径——在已有事件循环里再 ``asyncio.run``
    会报错。拦截方式与 ``plan_cmd`` 一致。
    """
    return json.dumps(
        {"query": query, "context_data": context_data, "max_chars": max_chars},
        ensure_ascii=False,
    )


@tool("finish", args_schema=FinishInput)
def finish_tool(final_answer: str) -> str:
    """结束任务并返回最终答复。"""
    return final_answer


class SkillRunner:
    def __init__(
        self,
        llm: Any,
        *,
        skills: Sequence[Skill] | None = None,
        max_steps: int = 20,
        cmd_timeout_sec: int = 30,
        same_cmd_fail_budget: int = 2,
        total_fail_budget: int = 3,
        make_plan_max_attempts: int = 3,
        empty_tool_retry: int = 1,
        plan_and_run_max_attempts: int = 3,
        max_concurrency: int = 0,
        code_execution: Any | None = None,
        allow_destructive_commands: bool = False,
        blocked_commands: frozenset[str] | None = None,
        extra_destructive_patterns: Sequence[tuple[re.Pattern[str], str]] | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.cmd_timeout_sec = cmd_timeout_sec
        self.same_cmd_fail_budget = same_cmd_fail_budget
        self.total_fail_budget = total_fail_budget
        self.make_plan_max_attempts = max(1, make_plan_max_attempts)
        self.empty_tool_retry = max(0, empty_tool_retry)
        self.plan_and_run_max_attempts = max(1, plan_and_run_max_attempts)
        self.max_concurrency = max(0, int(max_concurrency))
        self.allow_destructive_commands = bool(allow_destructive_commands)
        self.blocked_commands: frozenset[str] = (
            blocked_commands if blocked_commands is not None else DESTRUCTIVE_COMMAND_NAMES
        )
        self.destructive_flag_patterns: tuple[tuple[re.Pattern[str], str], ...] = (
            tuple(extra_destructive_patterns)
            if extra_destructive_patterns is not None
            else DESTRUCTIVE_FLAG_PATTERNS
        )
        self._loader = SkillLoader()
        self.lister = SkillLister(skills or [])
        self._planner_tools = [select_skill_tool, no_suitable_skill_tool]
        # ``code_execution`` 是可选能力：注入一个已构造好的 ``CodeExecution`` 实例
        # 才会把 ``code_exec`` 工具暴露给 LLM。保持 SkillRunner 与模型/key 解耦。
        self.code_execution = code_execution
        self._runner_tools = [
            plan_cmd_tool,
            read_file_tool,
            finish_tool,
        ]
        if self.code_execution is not None:
            # 插在 finish 之前，便于最终回答时仍以 ``finish`` 收口。
            self._runner_tools.insert(-1, code_exec_tool)
        # 注入 plugin 工具（也插在 finish 之前）
        # 如果调用方未传入 tool_registry，自动扫描 skill_sdk.tool 包发现插件
        if tool_registry is None:
            auto_registry = ToolRegistry()
            try:
                auto_registry.discover_package("skill_sdk.tool")
            except Exception:
                logger.debug("Auto-discovery of tool plugins failed", exc_info=True)
            tool_registry = auto_registry

        existing_names = {t.name for t in self._runner_tools}
        plugin_tools = [
            t for t in tool_registry.to_langchain_tools()
            if t.name not in existing_names
        ]
        if plugin_tools:
            self._runner_tools[-1:-1] = plugin_tools
            logger.info(
                "Registered %d plugin tool(s): %s",
                len(plugin_tools),
                [t.name for t in plugin_tools],
            )
        # Lazy-init the semaphore so it binds to the event loop that actually runs it.
        self._cmd_sem: asyncio.Semaphore | None = None
        self._cmd_sem_initialized = False

    def _get_cmd_semaphore(self) -> asyncio.Semaphore | None:
        """Return the concurrency-limiting semaphore (or ``None`` if unlimited).

        Constructed lazily on first use so that it binds to the running event loop
        rather than whichever loop happened to be active at construction time.
        """
        if self.max_concurrency <= 0:
            return None
        if not self._cmd_sem_initialized:
            self._cmd_sem = asyncio.Semaphore(self.max_concurrency)
            self._cmd_sem_initialized = True
        return self._cmd_sem

    def close(self) -> None:
        self._loader.close()

    def set_skills(self, skills: Sequence[Skill]) -> None:
        self.lister.set_skills(skills)

    def load_from_dir(self, skills_dir: str | Path) -> list[Skill]:
        loaded = self._loader.from_dir_load_skills(skills_dir)
        self.set_skills(loaded)
        return loaded

    async def _ainvoke(
        self,
        runnable: Any,
        payload: Any,
        *,
        config: dict[str, Any] | None = None,
    ) -> Any:
        if hasattr(runnable, "ainvoke"):
            return await runnable.ainvoke(payload, config=config)
        return await asyncio.to_thread(runnable.invoke, payload, config)

    @staticmethod
    def _render_skill_scripts(skill: Skill) -> str:
        """Render ``skill_dir`` / ``scripts_dir`` / ``resource_dirs`` / scripts for the LLM."""
        base_dir = str(skill.base_dir or "").strip()
        scripts_dir = ""
        if skill.scripts:
            common = os.path.commonpath([s.script_path for s in skill.scripts])
            scripts_dir = common if common.rstrip("/").endswith("scripts") else str(
                Path(skill.scripts[0].script_path).parent
            )
        if not scripts_dir and base_dir:
            candidate = str(Path(base_dir) / "scripts")
            if Path(candidate).is_dir():
                scripts_dir = candidate

        header: list[str] = []
        if base_dir:
            header.append(f"skill_dir: {base_dir}")
        if scripts_dir:
            header.append(f"scripts_dir: {scripts_dir}")
        if skill.resource_dirs:
            header.append("resource_dirs:")
            for rd in skill.resource_dirs:
                abs_path = str(Path(base_dir) / rd) if base_dir else rd
                header.append(f"  - {rd}/  (abs: {abs_path})")

        if not skill.scripts:
            body = "scripts: (none)"
        else:
            body_lines = ["scripts:"]
            for s in skill.scripts:
                interp = s.interpreter or "(unknown interpreter)"
                body_lines.append(
                    f"- {s.script_name}\n"
                    f"    path: {s.script_path}\n"
                    f"    interpreter: {interp}\n"
                    f"    invocation: {s.invocation}"
                )
            body = "\n".join(body_lines)

        return ("\n".join(header) + "\n\n" + body) if header else body

    async def make_plan(
        self,
        query: str,
        *,
        user_id: str,
        run_id: str,
        trace_id: str,
        exclude_skills: Sequence[str] | None = None,
        failure_notes: str = "",
    ) -> PlannerStep:
        """Select a skill via tool-calling, with up to ``make_plan_max_attempts`` retries.

        An attempt is considered successful only when the model emits either:
        - ``select_skill`` with a ``skill`` that maps to a currently loaded skill and
          is not in ``exclude_skills``; or
        - ``no_suitable_skill`` to explicitly decline.

        Anything else (no tool call, empty skill, unknown skill name, or a skill in
        ``exclude_skills``) is treated as a failed attempt; we nudge the model with
        the valid skill list (and any ``failure_notes``) and try again up to the
        configured limit.
        """
        logger.info(
            "make_plan ENTER query=%r user_id=%s run_id=%s trace_id=%s exclude=%s",
            _short(query),
            user_id,
            run_id,
            trace_id,
            list(exclude_skills or []),
        )
        skills_text = self.lister.list_skills()
        logger.info(
            "make_plan skills_count=%d skills_preview=%r",
            len(self.lister.skills),
            _short(skills_text, max_len=240),
        )
        if not skills_text:
            logger.warning("make_plan EARLY-EXIT no_loaded_skills")
            return PlannerStep(original_query=str(query), skill="", reason="No loaded skills.")

        excluded_lower = {str(n).strip().lower() for n in (exclude_skills or []) if str(n).strip()}

        system_text = PLANNER_INSTRUCTIONS_ZH.format(
            skills=skills_text,
            current_time=_now_context(),
        )
        messages: list[Any] = [
            SystemMessage(content=system_text),
            HumanMessage(content=query),
        ]
        if failure_notes.strip():
            messages.append(
                HumanMessage(
                    content=(
                        "## 上一轮 / 历次尝试反馈\n"
                        f"{failure_notes.strip()}\n\n"
                        "请根据上述反馈重新在「可用技能」中挑选；"
                        "若确实都不合适，请调用 `no_suitable_skill` 并说明原因。"
                    )
                )
            )
        if excluded_lower:
            messages.append(
                HumanMessage(
                    content=(
                        "以下 skill 在本次会话中**已经尝试且失败**，**不要**再选它们：\n"
                        + "\n".join(f"- {n}" for n in (exclude_skills or []))
                        + "\n若剩余技能里没有合适的，请调用 `no_suitable_skill`。"
                    )
                )
            )

        llm_with_tools = self.llm.bind_tools(self._planner_tools)

        chosen_skill_name = ""
        chosen_reason = ""
        declined = False

        with langfuse.start_as_current_span(
            name="skill_sdk-make_plan",
            trace_context={"trace_id": trace_id} if trace_id else None,
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={
                    "query": query,
                    "exclude_skills": list(exclude_skills or []),
                    "failure_notes": failure_notes,
                },
            )

            for attempt in range(1, self.make_plan_max_attempts + 1):
                logger.info(
                    "make_plan llm_invoke attempt=%d/%d messages=%d",
                    attempt,
                    self.make_plan_max_attempts,
                    len(messages),
                )
                answer = await self._ainvoke(
                    llm_with_tools,
                    messages,
                    config={"callbacks": [langfuse_handler]},
                )
                messages.append(answer)
                tool_calls = getattr(answer, "tool_calls", None) or []
                logger.info(
                    "make_plan llm_reply attempt=%d tool_calls=%s content=%r",
                    attempt,
                    [c.get("name") for c in tool_calls],
                    _short(getattr(answer, "content", "")),
                )

                if not tool_calls:
                    logger.warning(
                        "make_plan attempt %s/%s: no tool call, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你上一次没有调用工具。请**必须**二选一：\n"
                                "- 调用 `select_skill`，`skill` 字段严格等于下列可用技能的某个 name；\n"
                                "- 或调用 `no_suitable_skill` 并在 `reason` 中说明为什么都不合适。\n"
                                "不要直接输出文本或 JSON。\n\n"
                                f"可用技能：\n{skills_text}"
                            )
                        )
                    )
                    continue

                call = next(
                    (c for c in tool_calls if c.get("name") in ("select_skill", "no_suitable_skill")),
                    tool_calls[0],
                )
                name = call.get("name") or ""
                args = call.get("args", {}) or {}

                if name == "no_suitable_skill":
                    chosen_reason = str(args.get("reason", "") or "No suitable skill.").strip()
                    declined = True
                    logger.info(
                        "make_plan DECLINED attempt=%d reason=%r",
                        attempt,
                        _short(chosen_reason),
                    )
                    break

                if name != "select_skill":
                    logger.warning(
                        "make_plan attempt %s/%s: unknown tool=%r, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                        name,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                f"你调用了未知工具 `{name}`。请只使用 `select_skill` 或 `no_suitable_skill`。"
                            )
                        )
                    )
                    continue

                raw_skill = str(args.get("skill", "") or "").strip()
                reason = str(args.get("reason", "") or "").strip()

                if not raw_skill:
                    logger.warning(
                        "make_plan attempt %s/%s: select_skill with empty skill, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                "你刚才调用 `select_skill` 但 `skill` 字段为空。"
                                "若确实没有合适技能，请改调 `no_suitable_skill` 并说明原因；"
                                "否则请从下列可用技能中重选一个（`skill` 字段必须**严格等于** name）：\n"
                                f"{skills_text}"
                            )
                        )
                    )
                    continue

                candidates = self.lister.find_by_name(
                    raw_skill, match="exact", case_insensitive=True
                )
                if not candidates:
                    logger.warning(
                        "make_plan attempt %s/%s: skill %r not in loaded list, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                        raw_skill,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                f"你选择的 skill `{raw_skill}` **不在**可用技能列表中。"
                                "请在下列列表里重选，`skill` 字段必须严格等于其中某个 name；"
                                "若确实都不合适，请改调 `no_suitable_skill`：\n"
                                f"{skills_text}"
                            )
                        )
                    )
                    continue

                canonical_name = candidates[0].name
                if canonical_name.lower() in excluded_lower:
                    logger.warning(
                        "make_plan attempt %s/%s: skill %r already excluded, nudging.",
                        attempt,
                        self.make_plan_max_attempts,
                        canonical_name,
                    )
                    messages.append(
                        HumanMessage(
                            content=(
                                f"skill `{canonical_name}` 在本次会话中已尝试并失败，请**换一个**。"
                                "若剩余技能都不合适，请调用 `no_suitable_skill`。"
                            )
                        )
                    )
                    continue

                chosen_skill_name = canonical_name
                chosen_reason = reason
                logger.info(
                    "make_plan SELECTED attempt=%d skill=%r reason=%r",
                    attempt,
                    chosen_skill_name,
                    _short(chosen_reason, max_len=160),
                )
                break

            span.update_trace(
                output={
                    "skill": chosen_skill_name,
                    "reason": chosen_reason,
                    "declined": declined,
                }
            )

        langfuse.flush()

        if not chosen_skill_name and not declined:
            logger.warning(
                "make_plan EXIT no_valid_selection after %s attempts.",
                self.make_plan_max_attempts,
            )
            return PlannerStep(
                original_query=str(query),
                skill="",
                reason=(
                    f"Planner failed to produce a valid skill selection "
                    f"after {self.make_plan_max_attempts} attempts."
                ),
                declined=False,
            )

        step = PlannerStep(
            original_query=str(query),
            skill=chosen_skill_name,
            reason=chosen_reason,
            declined=declined,
        )
        logger.info(
            "make_plan EXIT skill=%r declined=%s reason=%r",
            step.skill,
            step.declined,
            _short(step.reason, max_len=160),
        )
        return step

    async def _summarize_max_steps_with_llm(
        self,
        *,
        query: str,
        skill: Skill,
        messages: list[Any],
        tool_history: list[dict[str, Any]],
        total_fails: int,
    ) -> str:
        """One plain LLM call to produce a user-facing summary when the loop hits max_steps."""
        transcript = _format_conversation_for_max_steps_summary(messages)
        human_blob = (
            "## 元信息\n"
            f"- skill: {skill.name}\n"
            f"- max_steps: {self.max_steps}\n"
            f"- plan_cmd 失败累计: {total_fails}\n"
            f"- 用户原始问题:\n{query}\n\n"
            "## 会话转写（含工具返回，可能被截断）\n"
            f"{transcript}"
        )
        summarizer_messages: list[Any] = [
            SystemMessage(
                content=MAX_STEPS_SUMMARY_SYSTEM_ZH.format(current_time=_now_context())
            ),
            HumanMessage(content=human_blob),
        ]
        try:
            resp = await self._ainvoke(
                self.llm,
                summarizer_messages,
                config={"callbacks": [langfuse_handler]},
            )
            text = str(getattr(resp, "content", "") or "").strip()
            if text:
                return text
            logger.warning("max_steps LLM summary returned empty content, using heuristic fallback")
        except Exception:
            logger.exception("max_steps LLM summary failed, using heuristic fallback")
        return _summarize_max_steps_state(
            tool_history,
            max_steps=self.max_steps,
            total_fails=total_fails,
        )

    async def run(
        self,
        query: str,
        skill: Skill,
        *,
        user_id: str,
        run_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Run the given skill using a tool-calling loop."""
        system_text = RUNNER_INSTRUCTIONS_ZH.format(
            skill_name=skill.name,
            skill_description=skill.description,
            skill_detail=skill.detail,
            skill_scripts=self._render_skill_scripts(skill),
            current_time=_now_context(),
        )
        messages: list[Any] = [
            SystemMessage(content=system_text),
            HumanMessage(content=query),
        ]
        llm_with_tools = self.llm.bind_tools(self._runner_tools)
        tool_history: list[dict[str, Any]] = []
        fail_counts: dict[str, int] = {}
        counters: dict[str, int] = {"total_fails": 0}
        empty_tool_retry_left = self.empty_tool_retry

        with langfuse.start_as_current_span(
            name="skill_sdk-run_skill",
            trace_context={"trace_id": trace_id} if trace_id else None,
        ) as span:
            span.update_trace(
                user_id=user_id,
                session_id=run_id,
                input={"query": query, "skill": skill.name},
            )

            for step_idx in range(self.max_steps):
                step_no = step_idx + 1
                logger.info(
                    "run STEP=%d/%d llm_invoke messages=%d",
                    step_no,
                    self.max_steps,
                    len(messages),
                )
                ai_msg = await self._ainvoke(
                    llm_with_tools,
                    messages,
                    config={"callbacks": [langfuse_handler]},
                )
                messages.append(ai_msg)

                thought_text = str(getattr(ai_msg, "content", "") or "").strip()
                reasoning_text = ""
                extra = getattr(ai_msg, "additional_kwargs", None) or {}
                if isinstance(extra, dict):
                    reasoning_text = str(extra.get("reasoning_content") or "").strip()
                if thought_text or reasoning_text:
                    tool_history.append(
                        {
                            "step": step_no,
                            "thought": thought_text,
                            "reasoning": reasoning_text,
                        }
                    )
                    logger.info(
                        "run STEP=%d thought=%r reasoning=%r",
                        step_no,
                        _short(thought_text),
                        _short(reasoning_text),
                    )

                tool_calls = getattr(ai_msg, "tool_calls", None) or []
                logger.info(
                    "run STEP=%d tool_calls=%s",
                    step_no,
                    [c.get("name") for c in tool_calls],
                )
                if not tool_calls:
                    if empty_tool_retry_left > 0:
                        empty_tool_retry_left -= 1
                        logger.warning(
                            "run STEP=%d empty tool_calls, nudging LLM to use tools "
                            "(retry_left=%d)",
                            step_no,
                            empty_tool_retry_left,
                        )
                        messages.append(
                            HumanMessage(
                                content=(
                                    "你上一次没有调用任何工具，仅输出了文字。请严格遵守工具使用规则："
                                    "必须先通过 `plan_cmd` 发出一条命令进行探测/执行，或者通过 "
                                    "`read_file` / `extract_pdf` 获取信息；完成任务时使用 `finish` 工具输出最终答复。"
                                    "不要再直接用纯文本回答。"
                                )
                            )
                        )
                        continue

                    result = {
                        "status": "completed_without_finish",
                        "skill": skill.name,
                        "final_answer": getattr(ai_msg, "content", ""),
                        "tool_history": tool_history,
                    }
                    logger.warning(
                        "run EXIT status=completed_without_finish step=%d",
                        step_no,
                    )
                    span.update_trace(output=result)
                    langfuse.flush()
                    return result

                plan_cmd_seen = False
                for idx, call in enumerate(tool_calls):
                    tool_name = call.get("name", "")
                    tool_args = call.get("args", {}) or {}
                    tool_id = call.get("id") or f"tc_{uuid.uuid4().hex[:12]}"
                    if not call.get("id"):
                        call["id"] = tool_id
                        logger.warning(
                            "run STEP=%d tool=%s missing id, assigned=%s",
                            step_no,
                            tool_name,
                            tool_id,
                        )

                    logger.info(
                        "run STEP=%d dispatch #%d tool=%s args=%r id=%s",
                        step_no,
                        idx + 1,
                        tool_name,
                        _short(tool_args),
                        tool_id,
                    )

                    if tool_name == "plan_cmd" and plan_cmd_seen:
                        logger.warning(
                            "run STEP=%d BLOCK second plan_cmd in same turn",
                            step_no,
                        )
                        tool_result = json.dumps(
                            {
                                "blocked_by_policy": True,
                                "reason": "Only one plan_cmd per turn is allowed.",
                            },
                            ensure_ascii=False,
                        )
                    else:
                        if tool_name == "plan_cmd":
                            plan_cmd_seen = True
                        tool_result = await self._dispatch_tool(
                            tool_name,
                            tool_args,
                            user_id=user_id,
                            run_id=run_id,
                            trace_id=trace_id,
                            fail_counts=fail_counts,
                            counters=counters,
                        )

                    tool_history.append(
                        {"tool": tool_name, "args": tool_args, "result": tool_result}
                    )
                    messages.append(
                        ToolMessage(content=str(tool_result), tool_call_id=tool_id)
                    )
                    logger.info(
                        "run STEP=%d dispatch #%d tool=%s result=%r",
                        step_no,
                        idx + 1,
                        tool_name,
                        _short(tool_result),
                    )

                    if tool_name == "finish":
                        result = {
                            "status": "completed",
                            "skill": skill.name,
                            "final_answer": tool_args.get("final_answer", str(tool_result)),
                            "tool_history": tool_history,
                        }
                        logger.info(
                            "run EXIT status=completed step=%d final_answer=%r",
                            step_no,
                            _short(result["final_answer"], max_len=240),
                        )
                        span.update_trace(output=result)
                        langfuse.flush()
                        return result

            final_answer = await self._summarize_max_steps_with_llm(
                query=query,
                skill=skill,
                messages=messages,
                tool_history=tool_history,
                total_fails=counters["total_fails"],
            )
            result = {
                "status": "max_steps_exceeded",
                "skill": skill.name,
                "final_answer": final_answer,
                "tool_history": tool_history,
            }
            logger.warning(
                "run EXIT status=max_steps_exceeded max_steps=%d total_fails=%d",
                self.max_steps,
                counters["total_fails"],
            )
            span.update_trace(output=result)
            langfuse.flush()
            return result

    async def _dispatch_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        *,
        user_id: str,
        run_id: str,
        trace_id: str,
        fail_counts: dict[str, int],
        counters: dict[str, int],
    ) -> str:
        """Dispatch LLM tool calls. `plan_cmd` is intercepted and really executed here."""
        if tool_name == "plan_cmd":
            cmd = str(tool_args.get("cmd", "")).strip()
            cwd = tool_args.get("cwd")
            rationale = tool_args.get("rationale", "")
            logger.info(
                "_dispatch plan_cmd cmd=%r cwd=%r rationale=%r total_fails=%d same_cmd_fails=%d",
                _short(cmd),
                cwd,
                _short(rationale),
                counters["total_fails"],
                fail_counts.get(cmd, 0),
            )
            if not cmd:
                logger.warning("_dispatch plan_cmd rejected: empty cmd")
                return json.dumps({"error": "Empty cmd in plan_cmd"}, ensure_ascii=False)

            if not self.allow_destructive_commands:
                destructive_reason = _check_destructive_cmd(
                    cmd,
                    blocked_names=self.blocked_commands,
                    flag_patterns=self.destructive_flag_patterns,
                )
                if destructive_reason:
                    fail_counts[cmd] = fail_counts.get(cmd, 0) + 1
                    counters["total_fails"] += 1
                    logger.warning(
                        "_dispatch plan_cmd BLOCKED destructive reason=%r cmd=%r "
                        "same_cmd_fails=%d total_fails=%d",
                        destructive_reason,
                        _short(cmd),
                        fail_counts[cmd],
                        counters["total_fails"],
                    )
                    payload: dict[str, Any] = {
                        "blocked_by_policy": True,
                        "cmd": cmd,
                        "reason": (
                            f"Destructive command refused by runner policy: "
                            f"{destructive_reason}. Rewrite your plan_cmd to be "
                            "read-only / non-destructive (e.g. use `ls`/`cat`/"
                            "`stat` instead of `rm`/`mv`; avoid `sed -i`, "
                            "`git reset --hard`, etc.). If the task truly "
                            "needs to mutate state, call `finish` and tell "
                            "the user to run the command themselves."
                        ),
                    }
                    if (
                        fail_counts[cmd] >= self.same_cmd_fail_budget
                        or counters["total_fails"] >= self.total_fail_budget
                    ):
                        payload["must_finish"] = True
                        payload["observation_hint"] = (
                            "Destructive attempts exhausted the failure budget; "
                            "stop retrying and call finish with a read-only "
                            "summary or an instruction for the user."
                        )
                    return json.dumps(payload, ensure_ascii=False)

            if counters["total_fails"] >= self.total_fail_budget:
                logger.warning(
                    "_dispatch plan_cmd HARD-BLOCK total_fails=%d >= budget=%d",
                    counters["total_fails"],
                    self.total_fail_budget,
                )
                return json.dumps(
                    {
                        "blocked_by_policy": True,
                        "must_finish": True,
                        "reason": (
                            f"Total failures {counters['total_fails']} >= budget "
                            f"{self.total_fail_budget}; plan_cmd is rejected. "
                            "You must call finish now."
                        ),
                    },
                    ensure_ascii=False,
                )
            if fail_counts.get(cmd, 0) >= self.same_cmd_fail_budget:
                logger.warning(
                    "_dispatch plan_cmd HARD-BLOCK same_cmd_fails=%d >= budget=%d cmd=%r",
                    fail_counts[cmd],
                    self.same_cmd_fail_budget,
                    _short(cmd),
                )
                return json.dumps(
                    {
                        "blocked_by_policy": True,
                        "must_finish": True,
                        "cmd": cmd,
                        "reason": (
                            f"Cmd already failed {fail_counts[cmd]} times "
                            f"(budget {self.same_cmd_fail_budget}); do NOT retry. "
                            "You must call finish now."
                        ),
                    },
                    ensure_ascii=False,
                )

            exec_cwd = cwd if isinstance(cwd, str) and cwd else None
            logger.info(
                "_dispatch exec_cmd START cmd=%r cwd=%r timeout=%d max_concurrency=%d",
                _short(cmd),
                exec_cwd,
                self.cmd_timeout_sec,
                self.max_concurrency,
            )
            sem = self._get_cmd_semaphore()
            if sem is not None:
                # Log when the semaphore is saturated so operators can tell a
                # slow response apart from "LLM slow" vs "waiting for a slot".
                if sem.locked():
                    logger.info(
                        "[concurrency] plan_cmd waiting for semaphore slot "
                        "(max=%d) cmd=%r",
                        self.max_concurrency,
                        _short(cmd),
                    )
                wait_t0 = _time.perf_counter()
                async with sem:
                    wait_ms = int((_time.perf_counter() - wait_t0) * 1000)
                    if wait_ms >= 10:
                        logger.info(
                            "[concurrency] plan_cmd acquired slot after %dms cmd=%r",
                            wait_ms,
                            _short(cmd),
                        )
                    exec_payload = await _execute_cmd_async(
                        cmd,
                        cwd=exec_cwd,
                        timeout_sec=self.cmd_timeout_sec,
                    )
            else:
                exec_payload = await _execute_cmd_async(
                    cmd,
                    cwd=exec_cwd,
                    timeout_sec=self.cmd_timeout_sec,
                )
            exec_payload["rationale"] = rationale

            rc = exec_payload.get("returncode")
            stderr_head = _stderr_head(exec_payload.get("stderr"))
            stdout_head = _short(exec_payload.get("stdout", ""), max_len=160)
            logger.info(
                "_dispatch exec_cmd END cmd=%r returncode=%s stdout_head=%r stderr_head=%r error=%r",
                _short(cmd),
                rc,
                stdout_head,
                stderr_head,
                _short(exec_payload.get("error", "")),
            )

            if rc == 0:
                fail_counts[cmd] = 0
            else:
                fail_counts[cmd] = fail_counts.get(cmd, 0) + 1
                counters["total_fails"] += 1
                hints: list[str] = []
                if fail_counts[cmd] >= self.same_cmd_fail_budget:
                    hints.append(
                        f"Same cmd failed {fail_counts[cmd]} times; do NOT retry this cmd."
                    )
                if counters["total_fails"] >= self.total_fail_budget:
                    hints.append(
                        f"Total {counters['total_fails']} failures reached; stop exploring new cmds."
                    )
                if hints:
                    exec_payload["must_finish"] = True
                    exec_payload["observation_hint"] = " ".join(hints)
                    logger.warning(
                        "_dispatch plan_cmd SOFT-HINT must_finish=true hint=%r",
                        _short(exec_payload["observation_hint"]),
                    )
                else:
                    logger.info(
                        "_dispatch plan_cmd fail_counts[cmd]=%d total_fails=%d",
                        fail_counts[cmd],
                        counters["total_fails"],
                    )
            return json.dumps(exec_payload, ensure_ascii=False)

        if tool_name == "code_exec":
            return await self._dispatch_code_exec(tool_args,user_id=user_id, run_id=run_id, trace_id=trace_id)

        target = next((t for t in self._runner_tools if t.name == tool_name), None)
        if target is None:
            logger.warning("_dispatch unknown tool=%s args=%r", tool_name, _short(tool_args))
            return json.dumps({"error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)
        logger.info("_dispatch tool=%s args=%r", tool_name, _short(tool_args))
        try:
            result = str(target.invoke(tool_args))
            logger.info(
                "_dispatch tool=%s result=%r",
                tool_name,
                _short(result, max_len=240),
            )
            return result
        except Exception as exc:  # noqa: BLE001
            logger.exception("_dispatch tool=%s invocation failed", tool_name)
            return json.dumps(
                {"tool": tool_name, "error": f"Tool invocation failed: {exc}"},
                ensure_ascii=False,
            )

    async def _dispatch_code_exec(
        self, tool_args: dict[str, Any],
        user_id: str,
        run_id: str,
        trace_id: str,
    ) -> str:
        """真实执行 ``code_exec``：调用已注入的 ``CodeExecution.run``。

        把结果压缩成紧凑 JSON 回塞给 LLM：
        * 只带 ``status``/``conclusion``/``aborted``/``reason``/``result``；
        * 所有文本字段按 ``max_chars`` 截断，避免把大 dataframe/dict 原样
          泵进对话上下文；
        * 任何异常都捕获并返回 ``error`` 字段，不抛出——让 agent 循环继续。
        """
        if self.code_execution is None:
            return json.dumps(
                {"error": "code_exec tool is not enabled on this runner"},
                ensure_ascii=False,
            )

        query = str(tool_args.get("query", "") or "").strip()
        if not query:
            return json.dumps(
                {"error": "Empty query in code_exec"},
                ensure_ascii=False,
            )

        raw_ctx = tool_args.get("context_data", "")
        if raw_ctx is None or (isinstance(raw_ctx, str) and not raw_ctx.strip()):
            context_data: Any = None
        elif isinstance(raw_ctx, str):
            # 优先当 JSON 解，失败了再按纯字符串透传——LLM 经常混用这两种写法。
            try:
                context_data = json.loads(raw_ctx)
            except json.JSONDecodeError:
                context_data = raw_ctx
        else:
            context_data = raw_ctx

        try:
            max_chars = int(tool_args.get("max_chars", 4000) or 4000)
        except (TypeError, ValueError):
            max_chars = 4000
        max_chars = max(100, min(max_chars, 40000))

        logger.info(
            "_dispatch code_exec START query=%r ctx_type=%s max_chars=%d",
            _short(query, max_len=160),
            type(context_data).__name__,
            max_chars,
        )

        try:
            exec_result = await self.code_execution.run(query, context_data, user_id=user_id, run_id=run_id, trace_id=trace_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("_dispatch code_exec run() failed")
            return json.dumps(
                {"tool": "code_exec", "error": f"code_exec run failed: {exc}"},
                ensure_ascii=False,
            )

        # ``CodeExecution.run`` 的返回结构可能随实现演进；这里做宽松抽取。
        if not isinstance(exec_result, dict):
            return json.dumps(
                {
                    "tool": "code_exec",
                    "status": "unknown",
                    "result": _trim_text(str(exec_result), max_chars=max_chars),
                },
                ensure_ascii=False,
            )

        def _stringify(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            try:
                return json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                return str(value)

        payload: dict[str, Any] = {
            "tool": "code_exec",
            "status": exec_result.get("status"),
            "conclusion": exec_result.get("conclusion"),
        }
        if exec_result.get("aborted") is not None:
            payload["aborted"] = bool(exec_result.get("aborted"))
        if exec_result.get("attempts") is not None:
            payload["attempts"] = exec_result.get("attempts")

        for key in ("reason", "error", "stdout", "stderr"):
            if exec_result.get(key):
                payload[key] = _trim_text(_stringify(exec_result.get(key)), max_chars=max_chars)

        if "result" in exec_result:
            payload["result"] = _trim_text(_stringify(exec_result.get("result")), max_chars=max_chars)

        if exec_result.get("code"):
            # 代码回显主要给 LLM/运维复盘用，单独给一个更紧的上限。
            payload["code"] = _trim_text(
                _stringify(exec_result.get("code")),
                max_chars=min(max_chars, 2000),
            )

        logger.info(
            "_dispatch code_exec END status=%r conclusion=%r aborted=%s result_head=%r",
            payload.get("status"),
            payload.get("conclusion"),
            payload.get("aborted"),
            _short(payload.get("result", ""), max_len=200),
        )
        return json.dumps(payload, ensure_ascii=False)

    async def plan_and_run(
        self,
        query: str,
        *,
        user_id: str,
        run_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        """Select a skill and run it, with up to ``plan_and_run_max_attempts`` replans.

        Replans happen when:
        - ``make_plan`` fails to produce a valid selection (but did not explicitly
          decline via ``no_suitable_skill``);
        - the selected skill name cannot be resolved against loaded skills; or
        - ``run()`` returns a non-``completed`` status such as
          ``completed_without_finish`` or ``max_steps_exceeded``.

        Previously-tried skills are excluded from subsequent picks and the reason
        for the previous failure is fed back into ``make_plan`` as failure notes.
        An explicit ``no_suitable_skill`` decline ends the loop immediately.
        """
        logger.info(
            "plan_and_run ENTER query=%r user_id=%s run_id=%s trace_id=%s max_attempts=%d",
            _short(query),
            user_id,
            run_id,
            trace_id,
            self.plan_and_run_max_attempts,
        )

        tried_skills: list[str] = []
        failure_notes_parts: list[str] = []
        attempts_log: list[dict[str, Any]] = []
        last_planner_dump: dict[str, Any] | None = None
        last_run_result: dict[str, Any] | None = None

        for attempt in range(1, self.plan_and_run_max_attempts + 1):
            failure_notes = "\n".join(failure_notes_parts)
            logger.info(
                "plan_and_run attempt=%d/%d tried_skills=%s",
                attempt,
                self.plan_and_run_max_attempts,
                tried_skills,
            )

            planner_step = await self.make_plan(
                query=query,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
                exclude_skills=tried_skills,
                failure_notes=failure_notes,
            )
            planner_dump = planner_step.model_dump()
            last_planner_dump = planner_dump

            if planner_step.declined:
                logger.warning(
                    "plan_and_run attempt=%d status=no_suitable_skill reason=%r",
                    attempt,
                    _short(planner_step.reason),
                )
                attempts_log.append(
                    {"attempt": attempt, "planner": planner_dump, "status": "no_suitable_skill"}
                )
                failure_notes_parts.append(
                    f"- 第 {attempt} 次规划失败：planner 认为没有合适的 skill"
                    f"（{_short(planner_step.reason, max_len=200) or 'no reason'}）。"
                    "请检查是否实际上有可用的 skill 能处理。"
                )
                if attempt >= self.plan_and_run_max_attempts:
                    return {
                        "status": "no_suitable_skill",
                        "planner": planner_dump,
                        "attempts": attempts_log,
                        "final_answer": (
                            planner_step.reason
                            or "Planner declined: no suitable skill for this query."
                        ),
                    }
                continue

            if not planner_step.skill:
                logger.warning(
                    "plan_and_run attempt=%d status=no_skill_selected reason=%r",
                    attempt,
                    _short(planner_step.reason),
                )
                attempts_log.append(
                    {"attempt": attempt, "planner": planner_dump, "status": "no_skill_selected"}
                )
                failure_notes_parts.append(
                    f"- 第 {attempt} 次规划失败：planner 未产生有效选择"
                    f"（{_short(planner_step.reason, max_len=200) or 'no reason'}）。"
                )
                if attempt >= self.plan_and_run_max_attempts:
                    return {
                        "status": "no_skill_selected",
                        "planner": planner_dump,
                        "attempts": attempts_log,
                        "final_answer": (
                            planner_step.reason
                            or "Planner did not select a skill."
                        ),
                    }
                continue

            candidates = self.lister.find_by_name(
                planner_step.skill, match="exact", case_insensitive=True
            )
            if not candidates:
                logger.warning(
                    "plan_and_run attempt=%d status=skill_not_found requested=%r",
                    attempt,
                    planner_step.skill,
                )
                tried_skills.append(planner_step.skill)
                failure_notes_parts.append(
                    f"- 第 {attempt} 次规划失败：选中的 skill `{planner_step.skill}` "
                    f"未在已加载技能列表中，请换一个。"
                )
                attempts_log.append(
                    {"attempt": attempt, "planner": planner_dump, "status": "skill_not_found"}
                )
                if attempt >= self.plan_and_run_max_attempts:
                    return {
                        "status": "skill_not_found",
                        "planner": planner_dump,
                        "attempts": attempts_log,
                        "final_answer": (
                            f"Skill '{planner_step.skill}' not found in loaded skills."
                        ),
                    }
                continue

            skill_obj = candidates[0]
            logger.info(
                "plan_and_run attempt=%d selected skill=%s, handing off to run()",
                attempt,
                skill_obj.name,
            )
            run_result = await self.run(
                query=query,
                skill=skill_obj,
                user_id=user_id,
                run_id=run_id,
                trace_id=trace_id,
            )
            run_result["planner"] = planner_dump
            last_run_result = run_result
            status = run_result.get("status")
            attempts_log.append(
                {
                    "attempt": attempt,
                    "planner": planner_dump,
                    "skill": skill_obj.name,
                    "status": status,
                }
            )

            if status == "completed":
                run_result["attempts"] = attempts_log
                logger.info(
                    "plan_and_run EXIT status=completed attempt=%d skill=%s",
                    attempt,
                    skill_obj.name,
                )
                return run_result

            tried_skills.append(skill_obj.name)
            if status == "completed_without_finish":
                hint = "模型未调用 `finish` 就停止输出工具调用"
            elif status == "max_steps_exceeded":
                hint = f"达到单轮最大步数（{self.max_steps}）仍未完成任务"
            else:
                hint = f"run() 返回 status={status}"
            failure_notes_parts.append(
                f"- 第 {attempt} 次执行：skill `{skill_obj.name}` 未能完成任务（{hint}）。"
                "这通常意味着该 skill 其实不适合当前问题，请换一个；"
                "若剩余技能都不合适，请调用 `no_suitable_skill`。"
            )

            if attempt >= self.plan_and_run_max_attempts:
                run_result["attempts"] = attempts_log
                logger.warning(
                    "plan_and_run EXIT status=%s skill=%s attempts_exhausted=%d",
                    status,
                    skill_obj.name,
                    attempt,
                )
                return run_result

            logger.warning(
                "plan_and_run attempt=%d status=%s skill=%s -> will replan",
                attempt,
                status,
                skill_obj.name,
            )

        # Should not reach here; fall back defensively.
        if last_run_result is not None:
            last_run_result["attempts"] = attempts_log
            return last_run_result
        return {
            "status": "no_skill_selected",
            "planner": last_planner_dump,
            "attempts": attempts_log,
            "final_answer": "plan_and_run exhausted without producing a result.",
        }
