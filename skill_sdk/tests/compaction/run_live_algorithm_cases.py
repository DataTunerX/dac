"""10 live cases targeting specific compaction algorithm paths (deepseek-v4-flash).

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk python tests/compaction/run_live_algorithm_cases.py
"""

from __future__ import annotations

import asyncio, os, sys, time, traceback, uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent.parent
_MODEL_SDK = _SDK_ROOT.parent / "model_sdk"
sys.path.insert(0, str(_SDK_ROOT))
if _MODEL_SDK.is_dir():
    sys.path.insert(0, str(_MODEL_SDK))

os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from model_sdk import ModelManager

from skill_sdk.compaction.guard import CompactionGuard
from skill_sdk.compaction.messages import is_compaction_summary_message
from skill_sdk.compaction.prepare import compact, prepare_compaction
from skill_sdk.compaction.settings import CompactionConfig, CompactionSettings

DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
    os.environ.get("OPENAI_API_KEY", "sk-xxx"),
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

PAD = ("padding-line\n" * 200)
SETTINGS = CompactionSettings(enabled=True, reserve_tokens=6_000, keep_recent_tokens=400)


@dataclass
class CaseResult:
    """Outcome of one live case."""

    case_id: int
    name: str
    ok: bool
    latency_s: float
    detail: str = ""
    errors: list[str] = field(default_factory=list)


def build_llm() -> Any:
    """Build DashScope OpenAI-compatible chat model (thinking off)."""
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


def _must(cond: bool, msg: str, errors: list[str]) -> None:
    """Record an assertion failure without aborting."""
    if not cond:
        errors.append(msg)


def _ai(content: str, tool_name: str, args: dict, cid: str, tokens: int) -> AIMessage:
    """Build an assistant tool-call message with usage metadata."""
    return AIMessage(
        content=content,
        tool_calls=[{"name": tool_name, "args": args, "id": cid, "type": "tool_call"}],
        usage_metadata={"input_tokens": tokens, "output_tokens": 100, "total_tokens": tokens + 100},
    )


# =============================================================================
# Dialog builders
# =============================================================================

def build_tool_trailing_dialog() -> list[Any]:
    """Dialog with trailing ToolMessages that should not be cut points."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="读取所有 config 文件，然后跑测试。不要改 schema。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/db.yaml", "host: DB-HOST-9K"),
        ("config/redis.yaml", "host: REDIS-HOST-9K"),
        ("config/app.yaml", "port: APP-PORT-9K"),
        ("tests/test_config.py", "assert DB-HOST-9K"),
        ("tests/test_config.py", "assert REDIS-HOST-9K"),
        ("tests/test_config.py", "assert APP-PORT-9K"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"tt_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"tt_{i}"))
    # Add trailing ToolMessages (no AI before them) -- algorithm must not cut here
    msgs.append(ToolMessage(content="extra trailing result\n" + PAD, tool_call_id="tt_extra"))
    msgs.append(ToolMessage(content="another trailing result\n" + PAD, tool_call_id="tt_extra2"))
    return msgs


def build_no_system_dialog() -> list[Any]:
    """Dialog with no leading SystemMessage -- verify compaction still works."""
    msgs: list[Any] = [
        HumanMessage(content="实现 JWT 认证中间件，标记 JWT-TOKEN-5P。不要改 User 模型。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/auth/jwt.py", "class JWTAuthMiddleware: JWT-TOKEN-5P"),
        ("src/auth/jwt.py", "decode_jwt(JWT-TOKEN-5P)"),
        ("src/models/user.py", "class User unchanged"),
        ("src/main.py", "app.add_middleware(JWTAuthMiddleware)"),
        ("tests/test_jwt.py", "assert JWT-TOKEN-5P in headers"),
        ("src/auth/jwt.py", "expiry = 3600"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ns_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ns_{i}"))
    return msgs


def build_multi_tool_dialog() -> list[Any]:
    """Dialog using grep, glob, lsp, write, edit -- all tool types."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="重构 auth 模块：把所有 TOKEN-BADGE-3M 替换为 API-KEY-BADGE-3M。约束：不要改 VaultService。"),
    ]
    ops = [
        ("grep", "src/auth", "TOKEN-BADGE-3M"),
        ("glob", "src/auth/**/*.py", "*.py"),
        ("readline_in_range", "src/auth/handler.py", 1, 40),
        ("lsp", "src/auth/handler.py", "def authenticate"),
        ("readline_in_range", "src/auth/vault.py", 1, 40),
        ("write_file", "src/auth/handler.py", "API-KEY-BADGE-3M"),
        ("edit_file", "src/auth/validator.py", "API-KEY-BADGE-3M"),
        ("grep", "src/auth", "API-KEY-BADGE-3M"),
    ]
    for i, (tool, path, *rest) in enumerate(ops):
        if tool in ("grep", "glob"):
            msgs.append(_ai(f"op {i}", tool, {"path": path, "pattern": rest[0]}, f"mt_{i}", 8_000 + i * 3_000))
        elif tool == "lsp":
            msgs.append(_ai(f"op {i}", tool, {"file_path": path, "symbol": rest[0]}, f"mt_{i}", 8_000 + i * 3_000))
        else:
            msgs.append(_ai(f"op {i}", tool, {"file_path": path, "start_line": rest[0] if rest else 1, "end_line": rest[1] if len(rest) > 1 else 40}, f"mt_{i}", 8_000 + i * 3_000))
        msgs.append(ToolMessage(content=f"{tool} {path}: TOKEN-BADGE-3M / API-KEY-BADGE-3M\n{PAD}", tool_call_id=f"mt_{i}"))
    return msgs


def build_single_turn_dialog() -> list[Any]:
    """One turn with many tool calls -- must split the turn."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="排查 SINGLE-TURN-KEY-22 在所有模块中的引用。"),
    ]
    for i in range(10):
        path = f"module/{chr(65+i)}.py"
        msgs.append(_ai(f"read {path}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"st_{i}", 10_000 + i * 3_000))
        msgs.append(ToolMessage(content=f"{path}\nSINGLE-TURN-KEY-22 used here\n{PAD}", tool_call_id=f"st_{i}"))
    return msgs


def build_custom_instructions_dialog() -> list[Any]:
    """Dialog where custom_instructions should focus summary on specific detail."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="阅读 payment 模块代码。注意：EMERGENCY-HOTFIX-X1 和常规改动。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/payment/gateway.py", "EMERGENCY-HOTFIX-X1: 紧急修复回调超时"),
        ("src/payment/invoice.py", "常规：生成 PDF 发票"),
        ("src/payment/refund.py", "EMERGENCY-HOTFIX-X1: 退款金额校验"),
        ("src/payment/config.py", "REGULAR-CHANGE-72: 配置项"),
        ("src/payment/webhook.py", "EMERGENCY-HOTFIX-X1: webhook 重试"),
        ("src/payment/CONSTANTS.py", "EMERGENCY-HOTFIX-X1 service flag"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ci_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ci_{i}"))
    return msgs


def build_mixed_read_write_dialog() -> list[Any]:
    """Dialog with both read and write operations -- verify modifiedFiles tracking."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="给所有服务添加 health check 端点 HEALTH-PROBE-66。只要修改 service 文件，不要改 proto 文件。"),
    ]
    ops = [
        ("readline_in_range", "src/service_a.py", "class ServiceA"),
        ("readline_in_range", "src/service_b.py", "class ServiceB"),
        ("write_file", "src/service_a.py", "HEALTH-PROBE-66"),
        ("readline_in_range", "proto/service.proto", "DO NOT MODIFY"),
        ("write_file", "src/service_b.py", "HEALTH-PROBE-66"),
        ("edit_file", "src/service_a.py", "HEALTH-PROBE-66 alive"),
        ("readline_in_range", "src/service_c.py", "class ServiceC"),
        ("write_file", "src/service_c.py", "HEALTH-PROBE-66"),
    ]
    for i, (tool, path, *rest) in enumerate(ops):
        msgs.append(_ai(f"op {i}", tool, {"file_path": path, "start_line":1,"end_line":40}, f"rw_{i}", 8_000 + i * 3_000))
        msgs.append(ToolMessage(content=f"{tool} {path}\n{rest[0] if rest else 'content'}\n{PAD}", tool_call_id=f"rw_{i}"))
    return msgs


def build_compaction_resume_dialog() -> list[Any]:
    """After compaction, new user messages resume correctly without losing prior summary."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="实现 RESUME-TASK-A1：用户注册功能。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/register/controller.py", "RESUME-TASK-A1 register endpoint"),
        ("src/register/validator.py", "RESUME-TASK-A1 validation"),
        ("src/register/model.py", "class UserRegistration"),
        ("src/register/controller.py", "@app.post('/register')"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"rs_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"rs_{i}"))
    return msgs


def build_very_small_keep_dialog() -> list[Any]:
    """Dialog with tiny keep_recent_tokens -- forces aggressive cut."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="TINY-WINDOW-KEY: 排查 rate limiter 配置。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/rate_limit.yaml", "max_per_second: TINY-WINDOW-KEY"),
        ("src/rate_limiter.py", "TINY-WINDOW-KEY threshold"),
        ("tests/test_limiter.py", "assert TINY-WINDOW-KEY"),
        ("config/rate_limit.yaml", "burst: TINY-WINDOW-KEY"),
        ("src/rate_limiter.py", "TINY-WINDOW-KEY reset"),
        ("tests/test_limiter.py", "TINY-WINDOW-KEY passes"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"tw_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"tw_{i}"))
    return msgs


def build_cut_point_boundary_dialog() -> list[Any]:
    """Dialog that tests cut point at the exact boundary of keep_recent_tokens."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="边界测试 CUT-POINT-TEST: 实现一个简单的排序函数。"),
    ]
    for i in range(6):
        path = f"src/sort_{i}.py"
        msgs.append(_ai(f"read {path}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"bp_{i}", 5_000 + i * 2_000))
        msgs.append(ToolMessage(content=f"{path}\nCUT-POINT-TEST\n{PAD}", tool_call_id=f"bp_{i}"))
    return msgs


# =============================================================================
# Case functions
# =============================================================================

async def case_21_tool_trailing(llm: Any) -> CaseResult:
    """Cut point algorithm must not cut at trailing ToolMessages."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_tool_trailing_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=500)
    prep = prepare_compaction(msgs, settings)
    if prep is None:
        return CaseResult(21, "tool_trailing_cut", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("DB-HOST-9K" in s or "db.yaml" in s.lower(), "DB host lost", errors)
    _must("REDIS-HOST-9K" in s or "redis" in s.lower(), "Redis host lost", errors)
    _must("APP-PORT-9K" in s or "app.yaml" in s.lower(), "App port lost", errors)
    _must("schema" in s.lower(), "don't-modify-schema constraint lost", errors)
    # Verify the kept messages don't start with a ToolMessage
    summary_idx = next((i for i, m in enumerate(result.messages) if is_compaction_summary_message(m)), -1)
    _must(summary_idx >= 0, "no summary message found", errors)
    kept = result.messages[summary_idx + 1:]
    for m in kept:
        _must(not isinstance(m, ToolMessage), f"kept message starts with ToolMessage: {type(m).__name__}", errors)
        break
    return CaseResult(21, "tool_trailing_cut", not errors, time.time() - t0, s[:240], errors)


async def case_22_no_system_message(llm: Any) -> CaseResult:
    """Compaction works without leading SystemMessage."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_no_system_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(22, "no_system_message", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("JWT-TOKEN-5P" in s, "JWT token marker lost", errors)
    _must("User" in s, "User model constraint lost", errors)
    _must("middleware" in s.lower() or "jwt" in s.lower(), "middleware context lost", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    return CaseResult(22, "no_system_message", not errors, time.time() - t0, s[:240], errors)


async def case_23_multi_tool_types(llm: Any) -> CaseResult:
    """All tool types (grep/glob/lsp/write/edit) are tracked correctly."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_multi_tool_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(23, "multi_tool_types", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    reads = result.details.get("readFiles") or []
    modified = result.details.get("modifiedFiles") or []
    _must(len(reads) >= 3, f"readFiles count={len(reads)} < 3", errors)
    _must(len(modified) >= 2, f"modifiedFiles count={len(modified)} < 2", errors)
    _must("TOKEN-BADGE-3M" in s or "API-KEY-BADGE-3M" in s, "badge marker lost", errors)
    _must("VaultService" in s or "vault" in s.lower(), "vault constraint lost", errors)
    return CaseResult(23, "multi_tool_types", not errors, time.time() - t0, f"reads={len(reads)} mods={len(modified)}", errors)


async def case_24_single_turn_split(llm: Any) -> CaseResult:
    """Single large turn must split into history + turn_prefix summaries."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_single_turn_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=4_000, keep_recent_tokens=300)
    prep = prepare_compaction(msgs, settings)
    if prep is None:
        return CaseResult(24, "single_turn_split", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    _must(prep.is_split_turn, "expected split_turn=True", errors)
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("SINGLE-TURN-KEY-22" in s, "unique key lost after split", errors)
    _must("Turn Context" in s or "Original Request" in s, "split turn format missing", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    return CaseResult(24, "single_turn_split", not errors, time.time() - t0, s[:240], errors)


async def case_25_custom_instructions(llm: Any) -> CaseResult:
    """Custom instructions focus the summary on EMERGENCY-HOTFIX-X1."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_custom_instructions_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=500)
    prep = prepare_compaction(msgs, settings)
    if prep is None:
        return CaseResult(25, "custom_instructions", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold", custom_instructions="Focus on EMERGENCY-HOTFIX-X1 changes only. Omit regular changes.")
    s = result.summary
    _must("EMERGENCY-HOTFIX-X1" in s, "emergency hotfix marker lost", errors)
    hotfix_count = s.count("EMERGENCY-HOTFIX-X1")
    _must(hotfix_count >= 2, f"EMERGENCY-HOTFIX-X1 only mentioned {hotfix_count} times", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    return CaseResult(25, "custom_instructions", not errors, time.time() - t0, f"hotfix_count={hotfix_count}", errors)


async def case_26_manual_compact(llm: Any) -> CaseResult:
    """compact_manual() works even when settings.enabled=False."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=100_000,
        settings=CompactionSettings(enabled=False, reserve_tokens=5_000, keep_recent_tokens=500),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_no_system_dialog()
    result = await guard.compact_manual(msgs, custom_instructions="Focus on JWT-TOKEN-5P")
    if result is None:
        return CaseResult(26, "manual_compact", False, 0, "compact_manual returned None", errors=["compact_manual returned None"])
    s = result.summary
    _must("JWT-TOKEN-5P" in s, "JWT marker lost in manual compaction", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    _must(any(is_compaction_summary_message(m) for m in result.messages), "no summary msg", errors)
    return CaseResult(26, "manual_compact", not errors, time.time() - t0, s[:240], errors)


async def case_27_mixed_read_write(llm: Any) -> CaseResult:
    """readFiles and modifiedFiles are tracked separately."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_mixed_read_write_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(27, "mixed_read_write", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    reads = result.details.get("readFiles") or []
    modified = result.details.get("modifiedFiles") or []
    _must(len(reads) >= 2, f"readFiles count={len(reads)} < 2", errors)
    _must(len(modified) >= 2, f"modifiedFiles count={len(modified)} < 2", errors)
    _must("<read-files>" in result.summary, "missing <read-files>", errors)
    _must("<modified-files>" in result.summary, "missing <modified-files>", errors)
    _must("HEALTH-PROBE-66" in result.summary, "health probe marker lost", errors)
    _must(any("proto" in p for p in reads), "proto file not in readFiles", errors)
    _must(not any("proto" in p for p in modified), "proto file incorrectly in modifiedFiles", errors)
    return CaseResult(27, "mixed_read_write", not errors, time.time() - t0, f"reads={len(reads)} mods={len(modified)}", errors)


async def case_28_compaction_resume(llm: Any) -> CaseResult:
    """After compaction, a new user message correctly resumes the task."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=15_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=4_000, keep_recent_tokens=500),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_compaction_resume_dialog()
    out = await guard.before_invoke(msgs)
    _must(len(out) < len(msgs), "first compact failed", errors)
    _must(any(is_compaction_summary_message(m) for m in out), "no summary after first compact", errors)
    resumed = list(out) + [
        HumanMessage(content="继续 RESUME-TASK-A1：添加邮箱验证。约束：不要改 User 模型。"),
        _ai("read", "readline_in_range", {"file_path": "src/register/email.py", "start_line":1,"end_line":40}, "rs_a", 18_000),
        ToolMessage(content="RESUME-TASK-A1 email verification\n" + PAD, tool_call_id="rs_a"),
        _ai("read", "readline_in_range", {"file_path": "src/register/email.py", "start_line":1,"end_line":40}, "rs_b", 22_000),
        ToolMessage(content="RESUME-TASK-A1 send_verification_email\n" + PAD, tool_call_id="rs_b"),
    ]
    out2 = await guard.before_invoke(resumed)
    _must(len(out2) < len(resumed), "second compact failed", errors)
    summary_msgs = [m for m in out2 if is_compaction_summary_message(m)]
    _must(bool(summary_msgs), "no summary after second compact", errors)
    text = str(getattr(summary_msgs[-1], "content", "")) if summary_msgs else ""
    _must("RESUME-TASK-A1" in text, "resume task marker lost", errors)
    _must("User" in text or "register" in text.lower(), "registration context lost", errors)
    return CaseResult(28, "compaction_resume", not errors, time.time() - t0, text[:240], errors)


async def case_29_very_small_keep(llm: Any) -> CaseResult:
    """Tiny keep_recent_tokens forces aggressive cut -- summary must still be coherent."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_very_small_keep_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=3_000, keep_recent_tokens=100)
    prep = prepare_compaction(msgs, settings)
    if prep is None:
        return CaseResult(29, "very_small_keep", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("TINY-WINDOW-KEY" in s, "tiny window key lost", errors)
    _must("rate" in s.lower() or "limiter" in s.lower(), "rate limiter context lost", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    _must(result.estimated_tokens_after < result.tokens_before, "tokens not reduced", errors)
    return CaseResult(29, "very_small_keep", not errors, time.time() - t0, f"before={result.tokens_before} after={result.estimated_tokens_after}", errors)


async def case_30_cut_point_boundary(llm: Any) -> CaseResult:
    """Cut point at exact boundary -- verify no crash and correct cut."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_cut_point_boundary_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=4_000, keep_recent_tokens=600)
    prep = prepare_compaction(msgs, settings)
    if prep is None:
        return CaseResult(30, "cut_point_boundary", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("CUT-POINT-TEST" in s, "cut point marker lost", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    _must(any(is_compaction_summary_message(m) for m in result.messages), "no summary msg", errors)
    summary_idx = next((i for i, m in enumerate(result.messages) if is_compaction_summary_message(m)), -1)
    kept = result.messages[summary_idx + 1:]
    if kept:
        _must(not isinstance(kept[0], ToolMessage), f"first kept is ToolMessage (invalid cut point)", errors)
    return CaseResult(30, "cut_point_boundary", not errors, time.time() - t0, s[:240], errors)


CASES: list[tuple[int, str, Callable[[Any], Any]]] = [
    (21, "tool trailing cut point", case_21_tool_trailing),
    (22, "no system message", case_22_no_system_message),
    (23, "multi tool types", case_23_multi_tool_types),
    (24, "single turn split", case_24_single_turn_split),
    (25, "custom instructions", case_25_custom_instructions),
    (26, "manual compact (disabled)", case_26_manual_compact),
    (27, "mixed read + write tracking", case_27_mixed_read_write),
    (28, "compaction resume", case_28_compaction_resume),
    (29, "very small keep tokens", case_29_very_small_keep),
    (30, "cut point boundary", case_30_cut_point_boundary),
]


async def main() -> None:
    """Execute all 10 live cases and print a scoreboard."""
    print(f"model={LLM_MODEL} base={DASHSCOPE_BASE_URL} key=***{DASHSCOPE_API_KEY[-8:]}")
    llm = build_llm()
    results: list[CaseResult] = []
    for case_id, title, fn in CASES:
        print("\n" + "=" * 72)
        print(f"CASE {case_id}/30: {title}")
        print("=" * 72)
        try:
            res = await fn(llm)
        except Exception as exc:
            res = CaseResult(
                case_id, title, False, 0.0, "",
                errors=[f"exception: {exc}", traceback.format_exc(limit=3)],
            )
        results.append(res)
        status = "PASS" if res.ok else "FAIL"
        print(f"[{status}] {res.name} ({res.latency_s:.2f}s)")
        if res.detail:
            print(f"  detail: {res.detail[:300]}")
        for err in res.errors:
            print(f"  ERROR: {err}")

    passed = sum(1 for r in results if r.ok)
    print("\n" + "#" * 72)
    print(f"SCOREBOARD: {passed}/{len(results)} passed")
    for r in results:
        print(f"  {'OK' if r.ok else 'NG'}  #{r.case_id:<2} {r.name}  ({r.latency_s:.2f}s)")
    print("#" * 72)
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())