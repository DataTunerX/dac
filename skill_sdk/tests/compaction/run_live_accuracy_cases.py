"""10 more live cases focused on summary accuracy with deepseek-v4-flash.

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk python tests/compaction/run_live_accuracy_cases.py
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
# Use a smaller keep_recent_tokens so the cut point falls inside the dialog
# rather than at index 0, giving prepare_compaction real spans to summarize.
SETTINGS = CompactionSettings(enabled=True, reserve_tokens=6_000, keep_recent_tokens=400)


@dataclass
class CaseResult:
    case_id: int; name: str; ok: bool; latency_s: float
    detail: str = ""; errors: list[str] = field(default_factory=list)


def build_llm() -> Any:
    return ModelManager().get_llm(
        provider="openai_compatible", api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL, model=LLM_MODEL,
        temperature=0.01, extra_body={"enable_thinking": False},
    )


def _must(cond: bool, msg: str, errors: list[str]) -> None:
    if not cond: errors.append(msg)


def _ai(content: str, tool_name: str, args: dict, cid: str, tokens: int) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[{"name": tool_name, "args": args, "id": cid, "type": "tool_call"}],
        usage_metadata={"input_tokens": tokens, "output_tokens": 100, "total_tokens": tokens + 100},
    )


# =============================================================================
# Dialog builders
# =============================================================================

def build_version_number_dialog() -> list[Any]:
    """Probe: semantic version 3.17.2-rc4 and commit hash abc123def must survive."""
    msgs = [
        SystemMessage(content="coding agent"),
        HumanMessage(content="升级到版本 3.17.2-rc4，commit abc123def。不要改 LICENSE。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("pyproject.toml", 'version = "3.17.2-rc4"'),
        ("CHANGELOG.md", "## 3.17.2-rc4 — abc123def"),
        ("src/__init__.py", "__version__ = '3.17.2-rc4'"),
        ("LICENSE", "MIT License — must not change"),
        ("tests/test_version.py", "assert __version__ == '3.17.2-rc4'"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"v_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"v_{i}"))
    msgs.append(HumanMessage(content="确认 3.17.2-rc4 和 abc123def 都已在 CHANGELOG 中。"))
    return msgs


def build_error_message_dialog() -> list[Any]:
    """Probe: exact error message must survive."""
    err = "FATAL-ERR-7B: connection pool exhausted at tcp://10.42.1.99:5432 after 30000ms"
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content=f"排查数据库连接错误：{err}"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/db.yaml", "pool: {max: 20, timeout: 30000}"),
        ("logs/error.log", err),
        ("src/db/pool.py", "class PoolManager max_connections=20"),
        ("config/db.yaml", "pool: {max: 50, timeout: 60000}"),
        ("tests/test_pool.py", "assert pool.max == 50"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"e_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"e_{i}"))
    return msgs


def build_multi_constraint_dialog() -> list[Any]:
    """Probe: 4 orthogonal constraints must all survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content=(
            "重构 PaymentService。约束：1) 不碰 DB schema（MUST-NOT-TOUCH-DB）；"
            "2) 必须兼容 Python 3.9+；3) 日志级别统一用 WARN-LOG-LEVEL；"
            "4) 异常必须继承自 BasePaymentError。"
        )),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/payment/service.py", "class PaymentService"),
        ("migrations/schema.sql", "CREATE TABLE payments — MUST-NOT-TOUCH-DB"),
        ("setup.cfg", "python_requires = >=3.9"),
        ("src/payment/logging.py", "logger.setLevel('WARN-LOG-LEVEL')"),
        ("src/payment/errors.py", "class BasePaymentError"),
        ("src/payment/service.py", "raise StripeGatewayError from BasePaymentError"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"mc_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"mc_{i}"))
    return msgs


def build_nested_directory_dialog() -> list[Any]:
    """Probe: deep paths must survive."""
    paths = [
        "src/domain/order/aggregate/OrderAggregate.java",
        "src/domain/order/service/CheckoutService.java",
        "src/domain/order/repository/PostgresOrderRepo.java",
        "src/infrastructure/messaging/KafkaOrderPublisher.java",
        "src/interfaces/rest/OrderController.java",
        "src/domain/order/event/OrderPlacedEvent.java",
    ]
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="将 OrderAggregate 的 placeOrder 拆成 validate + submit 两步。"),
    ]
    for i, path in enumerate(paths):
        msgs.append(_ai(f"read {path}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"nd_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\nclass ...\n{PAD}", tool_call_id=f"nd_{i}"))
    return msgs


def build_code_snippet_dialog() -> list[Any]:
    """Probe: exact function signature and code fragment must survive."""
    snippet = "def process_batch(items: list[dict], *, chunk_size: int = 256, timeout_ms: int = 5000) -> BatchResult:"
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content=f"优化 process_batch，签名：{snippet}"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/batch/processor.py", snippet),
        ("src/batch/processor.py", "chunk_size=256  # CODE-IDENT-8X"),
        ("tests/test_batch.py", "assert result.chunk_size == 256"),
        ("src/batch/types.py", "class BatchResult(NamedTuple)"),
        ("src/batch/processor.py", "timeout_ms=5000  # CODE-IDENT-8X"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"cs_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"cs_{i}"))
    return msgs


def build_tool_output_dialog() -> list[Any]:
    """Probe: grep output with file:line:match format must preserve paths."""
    grep_output = (
        "src/auth/login.py:42:def authenticate(TOKEN-X9Z):\n"
        "src/auth/middleware.py:118:TOKEN-X9Z = request.headers.get('Authorization')\n"
        "src/auth/token.py:7:TOKEN-ID = 'TOKEN-X9Z'\n"
        "tests/test_auth.py:15:assert token == 'TOKEN-X9Z'\n"
    )
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="找出所有引用 TOKEN-X9Z 的位置，不要改动 token.py 的 TOKEN-ID 定义。"),
    ]
    msgs.append(_ai("grep for TOKEN-X9Z", "grep", {"path": "src", "pattern": "TOKEN-X9Z"}, "gr_0", 10_000))
    msgs.append(ToolMessage(content=grep_output + PAD, tool_call_id="gr_0"))
    msgs.append(_ai("read login.py", "readline_in_range", {"file_path": "src/auth/login.py", "start_line":40,"end_line":50}, "gr_1", 14_000))
    msgs.append(ToolMessage(content="def authenticate(token: str) -> bool:\n    return token == 'TOKEN-X9Z'\n" + PAD, tool_call_id="gr_1"))
    msgs.append(_ai("read token.py", "readline_in_range", {"file_path": "src/auth/token.py", "start_line":1,"end_line":30}, "gr_2", 18_000))
    msgs.append(ToolMessage(content="TOKEN-ID = 'TOKEN-X9Z'  # must not change\n" + PAD, tool_call_id="gr_2"))
    msgs.append(HumanMessage(content="确认 TOKEN-X9Z 的所有引用位置，但不要改 token.py。"))
    return msgs


def build_large_codebase_explore_dialog() -> list[Any]:
    """Probe: large exploration with many read files; cumulative file tracking."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="排查整个 payment 模块中所有使用 StripeGateway 和 PayPalGateway 的地方。"),
    ]
    paths = [
        "src/payment/gateways/StripeGateway.py",
        "src/payment/gateways/PayPalGateway.py",
        "src/payment/service/CheckoutService.py",
        "src/payment/service/RefundService.py",
        "src/payment/webhook/StripeWebhook.py",
        "src/payment/webhook/PayPalWebhook.py",
        "src/payment/config.py",
        "src/payment/tests/test_gateways.py",
    ]
    for i, path in enumerate(paths):
        msgs.append(_ai(f"read {path}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":60}, f"lb_{i}", 8_000 + i * 3_500))
        msgs.append(ToolMessage(content=f"{path}\n# StripeGateway / PayPalGateway usage\n{PAD}", tool_call_id=f"lb_{i}"))
    return msgs


def build_three_compactions_dialog() -> list[Any]:
    """Probe: three successive compactions must not lose ANCHOR-V1."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="实现 ANCHOR-V1 功能：为用户画像系统添加兴趣标签聚类。约束：不要改 ProfileSchema。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/profile/models.py", "class ProfileSchema # must not change"),
        ("src/profile/cluster.py", "def cluster_tags(ANCHOR-V1)"),
        ("src/profile/store.py", "save_cluster(ANCHOR-V1)"),
        ("src/profile/models.py", "ProfileSchema unchanged"),
        ("src/profile/cluster.py", "kmeans for ANCHOR-V1"),
        ("src/profile/store.py", "postgres cluster ANCHOR-V1"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"tc_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"tc_{i}"))
    return msgs


def build_decision_tracking_dialog() -> list[Any]:
    """Probe: key design decisions should survive compaction."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="为消息队列选型。约束：延迟 < 10ms DECISION-LATENCY，吞吐 > 100k msg/s DECISION-TPS。"),
    ]
    decisions = [
        "选型 RabbitMQ — 延迟 5ms，满足 DECISION-LATENCY",
        "排除 Kafka — 吞吐 200k 但延迟 25ms，不满足 DECISION-LATENCY",
        "配置持久化队列 — 保证 at-least-once，吞吐降至 80k 仍满足 DECISION-TPS",
        "最终：RabbitMQ + 持久化 + 批量确认",
    ]
    for i, (path, note) in enumerate([
        ("docs/architecture.md", decisions[0]),
        ("docs/architecture.md", decisions[1]),
        ("docs/architecture.md", decisions[2]),
        ("docs/architecture.md", decisions[3]),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"dt_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{note}\n{PAD}", tool_call_id=f"dt_{i}"))
    return msgs


# =============================================================================
# Case functions
# =============================================================================

async def case_11_version_and_hash(llm: Any) -> CaseResult:
    """version 3.17.2-rc4 and commit abc123def survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_version_number_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(11, "version+hash_accuracy", False, 0, "prepare returned None (dialog too small?)", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("3.17.2-rc4" in s, "version lost", errors)
    _must("abc123def" in s, "commit hash lost", errors)
    _must("LICENSE" in s or "license" in s.lower(), "LICENSE constraint lost", errors)
    return CaseResult(11, "version+hash_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_12_error_message(llm: Any) -> CaseResult:
    """exact error message details survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_error_message_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(12, "error_message_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must(any(w in s.lower() for w in ["pool", "tcp", "30000", "30s", "timeout", "connection", "10.42"]), "connection details lost", errors)
    return CaseResult(12, "error_message_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_13_multi_constraint(llm: Any) -> CaseResult:
    """4 orthogonal constraints survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_multi_constraint_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(13, "multi_constraint_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    checks = [
        ("MUST-NOT-TOUCH-DB" in s or "DB schema" in s or "schema" in s.lower(), "DB constraint"),
        ("3.9" in s or "Python 3.9" in s, "Python version"),
        ("WARN-LOG-LEVEL" in s or "WARN" in s, "log level"),
        ("BasePaymentError" in s, "exception base"),
    ]
    for ok, label in checks:
        _must(ok, f"constraint '{label}' lost", errors)
    return CaseResult(13, "multi_constraint_accuracy", not errors, time.time() - t0, s[:300], errors)


async def case_14_deep_paths(llm: Any) -> CaseResult:
    """At least 3 of 6 deep paths survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_nested_directory_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(14, "deep_paths_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    hits = sum(1 for p in ["OrderAggregate", "CheckoutService", "OrderController", "OrderPlacedEvent", "PostgresOrderRepo", "KafkaOrderPublisher"] if p in s)
    _must(hits >= 3, f"only {hits}/6 deep paths found", errors)
    return CaseResult(14, "deep_paths_accuracy", not errors, time.time() - t0, f"paths_hit={hits}/6", errors)


async def case_15_code_signature(llm: Any) -> CaseResult:
    """function signature and code identifier survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_code_snippet_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(15, "code_snippet_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("process_batch" in s, "function name lost", errors)
    _must("chunk_size" in s or "256" in s, "chunk_size lost", errors)
    _must("CODE-IDENT-8X" in s, "code identifier lost", errors)
    return CaseResult(15, "code_snippet_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_16_grep_output(llm: Any) -> CaseResult:
    """grep output paths and token marker survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_tool_output_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(16, "grep_output_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("TOKEN-X9Z" in s, "token marker lost", errors)
    _must(any(p in s for p in ["login.py", "auth/login", "middleware.py", "token.py"]), "source paths lost", errors)
    _must("TOKEN-ID" in s or "not change" in s.lower(), "token constraint lost", errors)
    return CaseResult(16, "grep_output_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_17_large_file_tracking(llm: Any) -> CaseResult:
    """8 file reads; at least 5 paths found in readFiles."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_large_codebase_explore_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(17, "large_file_tracking", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    reads = result.details.get("readFiles") or []
    _must(len(reads) >= 5, f"readFiles count={len(reads)} < 5", errors)
    _must(any("StripeGateway" in p for p in reads), "StripeGateway path missing", errors)
    _must(any("PayPalGateway" in p for p in reads), "PayPalGateway path missing", errors)
    return CaseResult(17, "large_file_tracking", not errors, time.time() - t0, f"reads={len(reads)}", errors)


async def case_18_three_compactions(llm: Any) -> CaseResult:
    """Three successive compactions keep ANCHOR-V1 and ProfileSchema."""
    errors: list[str] = []
    t0 = time.time()
    config = CompactionConfig(
        context_window=15_000,
        settings=CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=800),
        summarizer_llm=llm,
    )
    guard = CompactionGuard(config, llm)
    msgs = build_three_compactions_dialog()
    out = await guard.before_invoke(msgs)
    _must(len(out) < len(msgs), "first compact failed", errors)
    grown = list(out) + [
        HumanMessage(content="继续完善 ANCHOR-V1 的聚类逻辑"),
        _ai("a", "readline_in_range", {"file_path": "src/profile/cluster.py", "start_line":1,"end_line":40}, "tc_a", 14_000),
        ToolMessage(content="ANCHOR-V1 kmeans++\n" + PAD, tool_call_id="tc_a"),
        _ai("b", "readline_in_range", {"file_path": "src/profile/cluster.py", "start_line":1,"end_line":40}, "tc_b", 18_000),
        ToolMessage(content="ANCHOR-V1 dbscan\n" + PAD, tool_call_id="tc_b"),
    ]
    out2 = await guard.before_invoke(grown)
    _must(len(out2) < len(grown), "second compact failed", errors)
    grown2 = list(out2) + [
        HumanMessage(content="最终确认 ANCHOR-V1 和 ProfileSchema"),
        _ai("c", "readline_in_range", {"file_path": "src/profile/models.py", "start_line":1,"end_line":40}, "tc_c", 22_000),
        ToolMessage(content="ProfileSchema — must not change\n" + PAD, tool_call_id="tc_c"),
    ]
    out3 = await guard.before_invoke(grown2)
    _must(len(out3) < len(grown2), "third compact failed", errors)
    summary_text = " ".join(str(getattr(m, "content", "")) for m in out3 if is_compaction_summary_message(m))
    _must("ANCHOR-V1" in summary_text, "ANCHOR-V1 lost after 3 compactions", errors)
    _must("ProfileSchema" in summary_text, "ProfileSchema lost after 3 compactions", errors)
    return CaseResult(18, "three_compactions_accuracy", not errors, time.time() - t0, summary_text[:240], errors)


async def case_19_decision_tracking(llm: Any) -> CaseResult:
    """Key decisions RabbitMQ and decision markers survive."""
    errors: list[str] = []
    t0 = time.time()
    msgs = build_decision_tracking_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None:
        return CaseResult(19, "decision_tracking_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("RabbitMQ" in s or "rabbitmq" in s.lower(), "RabbitMQ decision lost", errors)
    _must(any(w in s.lower() for w in ["latency", "decide", "10ms", "tps", "100k"]), "decision markers lost", errors)
    _must("Kafka" in s or "kafka" in s.lower(), "Kafka exclusion lost", errors)
    return CaseResult(19, "decision_tracking_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_20_small_dialog_noop(llm: Any) -> CaseResult:
    """Small dialog below threshold must NOT compact (no false positive)."""
    errors: list[str] = []
    t0 = time.time()
    settings = CompactionSettings(enabled=True, reserve_tokens=1_000, keep_recent_tokens=500)
    config = CompactionConfig(context_window=128_000, settings=settings, summarizer_llm=llm)
    guard = CompactionGuard(config, llm)
    small = [
        SystemMessage(content="agent"),
        HumanMessage(content="hello"),
        AIMessage(content="hi", usage_metadata={"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}),
    ]
    out = await guard.before_invoke(small)
    _must(len(out) == len(small), "small dialog compacted", errors)
    _must(not guard.boundaries, "boundary created for small dialog", errors)
    return CaseResult(20, "small_dialog_noop", not errors, time.time() - t0, f"size={len(out)}", errors)


CASES: list[tuple[int, str, Callable[[Any], Any]]] = [
    (11, "version+hash survive", case_11_version_and_hash),
    (12, "error message survive", case_12_error_message),
    (13, "multi-constraint (4)", case_13_multi_constraint),
    (14, "deep paths survive", case_14_deep_paths),
    (15, "code signature survive", case_15_code_signature),
    (16, "grep output accuracy", case_16_grep_output),
    (17, "large file tracking", case_17_large_file_tracking),
    (18, "3 successive compactions", case_18_three_compactions),
    (19, "decision tracking", case_19_decision_tracking),
    (20, "small dialog noop", case_20_small_dialog_noop),
]


async def main() -> None:
    print(f"model={LLM_MODEL} base={DASHSCOPE_BASE_URL} key=***{DASHSCOPE_API_KEY[-8:]}")
    llm = build_llm()
    results: list[CaseResult] = []
    for case_id, title, fn in CASES:
        print("\n" + "=" * 72)
        print(f"CASE {case_id}/20: {title}")
        print("=" * 72)
        try:
            res = await fn(llm)
        except Exception as exc:
            res = CaseResult(case_id, title, False, 0.0, "", errors=[f"exception: {exc}", traceback.format_exc(limit=3)])
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