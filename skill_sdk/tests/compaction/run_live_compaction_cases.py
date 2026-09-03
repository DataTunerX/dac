"""10 live cases for compaction stability + summary accuracy (deepseek-v4-flash).

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk python tests/compaction/run_live_compaction_cases.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

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

from skill_sdk.api.base import Skill
from skill_sdk.compaction.guard import CompactionGuard
from skill_sdk.compaction.messages import is_compaction_summary_message
from skill_sdk.compaction.prepare import compact, prepare_compaction
from skill_sdk.compaction.settings import CompactionConfig, CompactionSettings
from skill_sdk.skill.runner import SkillRunner

DASHSCOPE_API_KEY = os.environ.get(
    "DASHSCOPE_API_KEY",
    os.environ.get("OPENAI_API_KEY", "sk-xxx"),
)
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = os.environ.get("LLM_MODEL", "deepseek-v4-flash")

SETTINGS_COMPACT = CompactionSettings(enabled=True, reserve_tokens=6_000, keep_recent_tokens=1_200)
PAD = ("填充段落用于撑开上下文预算，确保切点不会落在对话开头。\n" * 40)


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
    """Record an assertion failure without aborting the whole case early."""
    if not cond:
        errors.append(msg)


def _contains_any(text: str, needles: list[str]) -> bool:
    """Case-insensitive substring check for any needle."""
    low = text.lower()
    return any(n.lower() in low for n in needles)


def _ai(content: str, tool_name: str, args: dict[str, Any], call_id: str, tokens: int) -> AIMessage:
    """Build an assistant tool-call message with usage metadata."""
    return AIMessage(
        content=content,
        tool_calls=[{"name": tool_name, "args": args, "id": call_id, "type": "tool_call"}],
        usage_metadata={
            "input_tokens": tokens,
            "output_tokens": 100,
            "total_tokens": tokens + 100,
        },
    )


def build_bugfix_dialog() -> list[Any]:
    """Multi-turn dialog about fixing NullPointer in OrderService."""
    msgs: list[Any] = [
        SystemMessage(content="You are a coding agent. Prefer tools then finish."),
        HumanMessage(content="修复 OrderService.checkout 的 NullPointerException（cart 可能为 null）。约束：不要改动 PaymentGateway 接口签名。"),
    ]
    steps = [
        ("src/shop/service/OrderService.java", "cart.getItems(); // NPE", "定位 NPE"),
        ("src/shop/cart/Cart.java", "getItems may return null", "确认 Cart"),
        ("tests/OrderServiceTest.java", "checkout(null) throws NPE", "复现单测"),
        ("src/shop/service/OrderService.java", "if (cart == null) throw ...", "已加判空"),
        ("src/shop/payment/PaymentGateway.java", "interface unchanged", "确认未改签名"),
        ("README.md", "PaymentGateway must stay stable", "文档约束"),
    ]
    for i, (path, excerpt, note) in enumerate(steps):
        msgs.append(
            _ai(
                f"第{i+1}步：{note}",
                "readline_in_range",
                {"file_path": path, "start_line": 1, "end_line": 40},
                f"bf_{i}",
                8_000 + i * 4_000,
            )
        )
        msgs.append(ToolMessage(content=f"FILE {path}\n{excerpt}\n{PAD}", tool_call_id=f"bf_{i}"))
    msgs.append(HumanMessage(content="继续：确认 PaymentGateway 未被改动，给出最终修复结论。"))
    return msgs


def build_chinese_refactor_dialog() -> list[Any]:
    """Chinese refactor dialog with unique identifiers for accuracy checks."""
    marker = "REFACTOR-TOKEN-QZ9"
    msgs: list[Any] = [
        SystemMessage(content="你是代码助手。"),
        HumanMessage(
            content=f"请把 UserController 里的 validateEmail 抽到 EmailValidator。标记：{marker}。不要改动数据库 schema。"
        ),
    ]
    files = [
        ("app/controllers/UserController.py", "def validateEmail(s): return '@' in s"),
        ("app/validators/EmailValidator.py", "class EmailValidator: ..."),
        ("app/controllers/UserController.py", "from validators.EmailValidator import EmailValidator"),
        ("app/tests/test_email.py", "assert EmailValidator().validate('a@b.c')"),
        ("docs/constraints.md", f"MUST keep DB schema unchanged. marker={marker}"),
        ("app/controllers/UserController.py", "email_validator = EmailValidator()"),
    ]
    for i, (path, excerpt) in enumerate(files):
        msgs.append(
            _ai(
                f"处理 {path}",
                "grep",
                {"path": path, "pattern": "validateEmail"},
                f"rf_{i}",
                10_000 + i * 5_000,
            )
        )
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{marker}\n{PAD}", tool_call_id=f"rf_{i}"))
    return msgs


def build_split_turn_dialog() -> list[Any]:
    """One huge turn (many tool rounds) to force split-turn compaction."""
    msgs: list[Any] = [
        SystemMessage(content="coding agent"),
        HumanMessage(content="请完整阅读 pipeline 模块并总结 DAG 调度策略 UNIQUE-DAG-77。"),
    ]
    for i in range(8):
        path = f"pipeline/stage_{i}.py"
        msgs.append(
            _ai(
                f"读取 stage_{i}",
                "readline_in_range",
                {"file_path": path, "start_line": 1, "end_line": 100},
                f"st_{i}",
                15_000 + i * 2_500,
            )
        )
        msgs.append(
            ToolMessage(
                content=f"# {path}\ndef run():\n    schedule('UNIQUE-DAG-77')\n{PAD}",
                tool_call_id=f"st_{i}",
            )
        )
    return msgs


def build_multi_goal_dialog() -> list[Any]:
    """Dialog that expands goals mid-way (accuracy of iterative update)."""
    msgs: list[Any] = [
        SystemMessage(content="agent"),
        HumanMessage(content="目标A：实现 /healthz 接口返回 ok。"),
    ]
    steps = [
        ("api/routes.py", "@app.get('/healthz')\ndef healthz(): return {'status':'ok'}", "healthz"),
        ("api/routes.py", "healthz registered", "verify healthz"),
    ]
    for i, (path, excerpt, note) in enumerate(steps):
        msgs.append(
            _ai(note, "readline_in_range", {"file_path": path, "start_line": 1, "end_line": 50}, f"mg_{i}", 9_000 + i * 5_000)
        )
        msgs.append(ToolMessage(content=excerpt + "\n" + PAD, tool_call_id=f"mg_{i}"))
    msgs.append(HumanMessage(content="目标B追加：再给 /readyz 返回依赖检查结果 READY-FLAG-42。"))
    for i, (path, excerpt, note) in enumerate(
        [
            ("api/ready.py", "READY-FLAG-42 dependency check stub", "readyz"),
            ("api/ready.py", "readyz wired", "verify readyz"),
            ("api/routes.py", "healthz+readyz", "both endpoints"),
        ],
        start=2,
    ):
        msgs.append(
            _ai(note, "readline_in_range", {"file_path": path, "start_line": 1, "end_line": 50}, f"mg_{i}", 12_000 + i * 5_000)
        )
        msgs.append(ToolMessage(content=excerpt + "\n" + PAD, tool_call_id=f"mg_{i}"))
    return msgs


class _CountingLLM:
    """Wrapper that counts ainvoke calls while delegating to a real LLM."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.calls = 0

    async def ainvoke(self, messages: Any, config: Any = None) -> Any:
        """Delegate and count."""
        self.calls += 1
        return await self.inner.ainvoke(messages, config=config)

    def bind(self, **kwargs: Any) -> "_CountingLLM":
        """Preserve bind(max_tokens=...) used by summarizer."""
        bound = self.inner.bind(**kwargs) if hasattr(self.inner, "bind") else self.inner
        wrapped = _CountingLLM(bound)
        wrapped.calls = self.calls
        # share counter
        parent = self

        async def counted(messages: Any, config: Any = None) -> Any:
            parent.calls += 1
            return await bound.ainvoke(messages, config=config)

        wrapped.ainvoke = counted  # type: ignore[method-assign]
        return wrapped


async def case_01(llm: Any) -> CaseResult:
    """Summary must retain NPE goal and PaymentGateway constraint."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_bugfix_dialog()
    prep = prepare_compaction(msgs, SETTINGS_COMPACT)
    _must(prep is not None, "prepare returned None", errors)
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must(_contains_any(s, ["NullPointer", "NPE", "checkout", "OrderService"]), "missing bug goal", errors)
    _must(_contains_any(s, ["PaymentGateway", "接口签名", "不要改动"]), "missing constraint", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    _must(any(is_compaction_summary_message(m) for m in result.messages), "no summary msg", errors)
    return CaseResult(1, "bugfix_goal_constraint_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_02(llm: Any) -> CaseResult:
    """Compaction details / summary tags should list read files."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_bugfix_dialog()
    prep = prepare_compaction(msgs, SETTINGS_COMPACT)
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    reads = result.details.get("readFiles") or []
    _must(any("OrderService" in p for p in reads), f"OrderService not in readFiles={reads}", errors)
    _must("<read-files>" in result.summary, "missing <read-files> tag", errors)
    return CaseResult(2, "file_ops_read_files_accuracy", not errors, time.time() - t0, f"reads={reads}", errors)


async def case_03(llm: Any) -> CaseResult:
    """Chinese dialog: unique marker and EmailValidator should survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_chinese_refactor_dialog()
    prep = prepare_compaction(msgs, SETTINGS_COMPACT)
    _must(prep is not None, "prepare returned None", errors)
    if prep is None:
        return CaseResult(3, "chinese_marker_accuracy", False, time.time() - t0, "", errors)
    result = await compact(prep, llm, reason="threshold")
    s = result.summary
    _must("REFACTOR-TOKEN-QZ9" in s or "QZ9" in s, "unique marker lost", errors)
    _must(_contains_any(s, ["EmailValidator", "validateEmail", "UserController"]), "key symbols lost", errors)
    _must(_contains_any(s, ["schema", "数据库"]), "schema constraint lost", errors)
    return CaseResult(3, "chinese_marker_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_04(llm: Any) -> CaseResult:
    """Huge single turn must compact via split-turn path without crashing."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_split_turn_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=800)
    prep = prepare_compaction(msgs, settings)
    _must(prep is not None, "prepare None", errors)
    _must(bool(prep and prep.is_split_turn), "expected split turn", errors)
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must(len(result.messages) < len(msgs), "not reduced", errors)
    _must(_contains_any(s, ["UNIQUE-DAG-77", "DAG", "pipeline", "stage"]), "DAG marker/context lost", errors)
    _must("Turn Context" in s or "Original Request" in s or "## Goal" in s, "unexpected summary shape", errors)
    return CaseResult(4, "split_turn_stability", not errors, time.time() - t0, f"split={getattr(prep, 'is_split_turn', None)}", errors)


async def case_05(llm: Any) -> CaseResult:
    """Guard.before_invoke reduces context when over threshold."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=18_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=6_000, keep_recent_tokens=1_000),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_bugfix_dialog()
    out = await guard.before_invoke(msgs)
    _must(len(out) < len(msgs), f"size {len(msgs)}->{len(out)}", errors)
    _must(isinstance(out[0], SystemMessage), "system not preserved", errors)
    _must(any(is_compaction_summary_message(m) for m in out), "no summary injection", errors)
    _must(bool(guard.boundaries), "no boundary recorded", errors)
    return CaseResult(5, "threshold_guard_stability", not errors, time.time() - t0, f"{len(msgs)}->{len(out)}", errors)


async def case_06(llm: Any) -> CaseResult:
    """Overflow recovers once; second overflow fails deterministically."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=18_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=6_000, keep_recent_tokens=1_000),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_bugfix_dialog()
    exc = RuntimeError("Your input exceeds the context window of this model")
    r1 = await guard.on_invoke_error(msgs, exc)
    _must(r1 is not None and bool(r1.will_retry) and not r1.failed, "first recovery failed", errors)
    _must(r1 is not None and r1.messages is not None and len(r1.messages) < len(msgs), "not compacted", errors)
    r2 = await guard.on_invoke_error(r1.messages if r1 and r1.messages else msgs, exc)  # type: ignore[arg-type]
    _must(r2 is not None and r2.failed, "second should fail", errors)
    _must(r2 is not None and "compact-and-retry" in (r2.error_message or ""), "bad fail message", errors)
    return CaseResult(6, "overflow_retry_stability", not errors, time.time() - t0, "retry-once ok", errors)


async def case_07(llm: Any) -> CaseResult:
    """Second compaction with previous summary should keep goal A and add goal B."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=16_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=900),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_multi_goal_dialog()
    out1 = await guard.before_invoke(msgs)
    _must(any(is_compaction_summary_message(m) for m in out1), "first compact missing", errors)
    grown = list(out1)
    for i in range(5):
        grown.append(HumanMessage(content=f"补充说明{i}: keep READY-FLAG-42 and healthz"))
        grown.append(
            _ai(
                f"ack {i}",
                "grep",
                {"path": "api", "pattern": "healthz|readyz"},
                f"it_{i}",
                22_000 + i * 4_000,
            )
        )
        grown.append(ToolMessage(content="healthz ok / readyz READY-FLAG-42\n" + PAD, tool_call_id=f"it_{i}"))
    out2 = await guard.before_invoke(grown)
    summary_msgs = [m for m in out2 if is_compaction_summary_message(m)]
    _must(bool(summary_msgs), "second compact missing summary", errors)
    text = str(getattr(summary_msgs[-1], "content", "")) if summary_msgs else ""
    _must(_contains_any(text, ["healthz", "/healthz", "目标A"]), "goal A lost after update", errors)
    _must(_contains_any(text, ["readyz", "READY-FLAG-42", "目标B"]), "goal B lost after update", errors)
    return CaseResult(7, "iterative_update_accuracy", not errors, time.time() - t0, text[:240], errors)


async def case_08(llm: Any) -> CaseResult:
    """enabled=False must never call summarizer / change messages."""
    errors: list[str] = []
    t0 = time.time()
    counter = _CountingLLM(llm)
    config = CompactionConfig(
        context_window=1_000,
        settings=CompactionSettings(enabled=False, reserve_tokens=100, keep_recent_tokens=100),
        summarizer_llm=counter,
    )
    guard = CompactionGuard(config, counter)
    msgs = build_bugfix_dialog()
    out = await guard.before_invoke(msgs)
    _must(len(out) == len(msgs), "messages mutated while disabled", errors)
    recovery = await guard.on_invoke_error(msgs, RuntimeError("exceeds the context window"))
    _must(recovery is None, "overflow handled while disabled", errors)
    _must(counter.calls == 0, f"summarizer called {counter.calls} times", errors)
    return CaseResult(8, "disabled_noop_stability", not errors, time.time() - t0, "noop", errors)


async def case_09(llm: Any) -> CaseResult:
    """SkillRunner returns context_overflow after failed recovery."""
    errors: list[str] = []
    t0 = time.time()

    class AlwaysOverflowLLM:
        """LLM that always raises overflow on tool-bound invokes."""

        def bind_tools(self, tools: Any) -> Any:
            return self

        async def ainvoke(self, messages: Any, config: Any = None) -> Any:
            raise RuntimeError("prompt is too long: 999999 tokens > 8000 maximum")

    config = CompactionConfig(
        context_window=200_000,  # avoid threshold before overflow recovery
        settings=CompactionSettings(enabled=True, reserve_tokens=4_000, keep_recent_tokens=800),
        summarizer_llm=llm,
    )
    runner = SkillRunner(
        llm=AlwaysOverflowLLM(),
        max_steps=2,
        compaction=config,
        use_skill_search=False,
    )
    template = runner._compaction_template
    assert template is not None
    real_new = template.new_run_guard

    def seeded() -> CompactionGuard:
        guard = real_new()
        real_before = guard.before_invoke

        async def before(messages: Any) -> list[Any]:
            msgs = list(messages)
            if len(msgs) < 8:
                msgs.extend(build_bugfix_dialog()[2:])
            return await real_before(msgs)

        guard.before_invoke = before  # type: ignore[method-assign]
        return guard

    skill = Skill(
        name="overflow-demo",
        description="demo",
        detail="调用 finish 即可",
        version="0.0.1",
        allowed_tools=["finish"],
    )
    with patch.object(template, "new_run_guard", side_effect=seeded):
        with patch.object(runner, "_tools_for_skill", return_value=runner._runner_tools):
            result = await runner.run(
                "请完成",
                skill,
                user_id="u",
                run_id=str(uuid.uuid4()),
                trace_id=uuid.uuid4().hex,
            )
    ans = str(result.get("final_answer") or "")
    _must(result.get("status") == "context_overflow", f"status={result.get('status')}", errors)
    _must(
        ("compact-and-retry" in ans) or ("Context overflow" in ans),
        f"unexpected final_answer={ans!r}",
        errors,
    )
    return CaseResult(9, "runner_context_overflow_status", not errors, time.time() - t0, ans[:160], errors)


async def case_10(llm: Any) -> CaseResult:
    """Normal short run with compaction enabled still completes via finish."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=128_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=16_384, keep_recent_tokens=20_000),
        summarizer_llm=llm,
    )
    runner = SkillRunner(
        llm=llm,
        max_steps=4,
        compaction=config,
        use_skill_search=False,
    )
    skill = Skill(
        name="hello-compact",
        description="打招呼并 finish",
        detail="用户问好时立刻调用 finish，final_answer 必须包含短语 LIVE-CASE-10-OK。不要用其它工具。",
        version="0.0.1",
        allowed_tools=["finish"],
    )
    result = await runner.run(
        "你好",
        skill,
        user_id="u",
        run_id=str(uuid.uuid4()),
        trace_id=uuid.uuid4().hex,
    )
    ans = str(result.get("final_answer") or "")
    _must(result.get("status") == "completed", f"status={result.get('status')}", errors)
    _must("LIVE-CASE-10-OK" in ans, f"marker missing in answer={ans!r}", errors)
    return CaseResult(10, "runner_completed_with_compaction", not errors, time.time() - t0, ans[:200], errors)


CASES: list[tuple[int, str, Callable[[Any], Any]]] = [
    (1, "bugfix goal+constraint accuracy", case_01),
    (2, "file ops readFiles accuracy", case_02),
    (3, "chinese unique marker accuracy", case_03),
    (4, "split-turn stability", case_04),
    (5, "threshold guard stability", case_05),
    (6, "overflow retry-once stability", case_06),
    (7, "iterative update accuracy", case_07),
    (8, "disabled noop stability", case_08),
    (9, "runner context_overflow status", case_09),
    (10, "runner completed + compaction on", case_10),
]


async def main() -> None:
    """Execute all 10 live cases and print a scoreboard."""
    print(f"model={LLM_MODEL} base={DASHSCOPE_BASE_URL} key=***{DASHSCOPE_API_KEY[-8:]}")
    llm = build_llm()
    results: list[CaseResult] = []
    for case_id, title, fn in CASES:
        print("\n" + "=" * 72)
        print(f"CASE {case_id}/10: {title}")
        print("=" * 72)
        try:
            res = await fn(llm)
        except Exception as exc:  # noqa: BLE001
            res = CaseResult(
                case_id,
                title,
                False,
                0.0,
                "",
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
