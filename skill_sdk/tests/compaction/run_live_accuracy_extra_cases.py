"""20 additional live accuracy cases for compaction (deepseek-v4-flash).

Covers content types and edge cases not yet tested in the first 30 cases.

Run:
  cd /Users/james/daocloud/code/dac/skill_sdk
  PYTHONPATH=.:../model_sdk python tests/compaction/run_live_accuracy_extra_cases.py
"""

from __future__ import annotations

import asyncio, os, sys, time, traceback
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
# Dialog builders -- 20 distinct accuracy probes
# =============================================================================

def build_api_key_dialog() -> list[Any]:
    """Probe: API key sk-xxx format must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="配置阿里云 OSS 客户端，API key: sk-7f3a2b1c4d5e6f7g8h9i0j。不要提交到 git。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/oss.yaml", "oss_access_key: sk-7f3a2b1c4d5e6f7g8h9i0j"),
        ("src/oss/client.py", "SK-7F3A2B1C (oss client)"),
        ("config/oss.yaml", "bucket: my-bucket"),
        (".gitignore", "*.yaml"),
        ("src/oss/client.py", "def upload_file"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ak_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ak_{i}"))
    return msgs


def build_url_dialog() -> list[Any]:
    """Probe: exact URLs and query params must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="配置监控告警：webhook https://hooks.example.com/v2/alerts?env=prod&region=cn-shanghai，间隔 300s。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/monitor.yaml", "webhook: https://hooks.example.com/v2/alerts?env=prod&region=cn-shanghai"),
        ("config/monitor.yaml", "interval: 300"),
        ("src/monitor/alerter.py", "def send_alert(webhook_url)"),
        ("config/monitor.yaml", "retry: 3"),
        ("tests/test_monitor.py", "assert webhook == 'https://hooks.example.com/v2/alerts'"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ur_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ur_{i}"))
    return msgs


def build_stack_trace_dialog() -> list[Any]:
    """Probe: stack trace frame with file:line must survive."""
    trace = '  File "src/worker/task.py", line 142, in process\n    result = pipeline.run(data)\nTypeError: STACK-TRACE-7Z: expected str, got NoneType'
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content=f"排查 TypeError：{trace}"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/worker/task.py", "line 142: result = pipeline.run(data)"),
        ("logs/error.log", trace),
        ("src/worker/pipeline.py", "def run(data: str) -> STACK-TRACE-7Z"),
        ("src/worker/task.py", "line 140: data = get_input()"),
        ("tests/test_task.py", "assert pipeline.run('ok') == 'STACK-TRACE-7Z'"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"st_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"st_{i}"))
    return msgs


def build_port_config_dialog() -> list[Any]:
    """Probe: port numbers and service endpoints must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="部署微服务：gateway 8080, user 8081, order 8082, payment 8083。db 5432, redis 6379, mq 5672。约束：gateway 端口不能改。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("docker-compose.yml", "gateway: 8080, user: 8081, order: 8082, payment: 8083"),
        ("config/db.yaml", "db: 5432, redis: 6379, mq: 5672"),
        ("src/gateway/main.py", "PORT=8080 # must not change"),
        ("src/user/main.py", "PORT=8081"),
        ("src/order/main.py", "PORT=8082"),
        ("src/payment/main.py", "PORT=8083"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"pt_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"pt_{i}"))
    return msgs


def build_multilingual_dialog() -> list[Any]:
    """Probe: Chinese, English, Japanese mixed content must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="国际化：添加日语翻译。キーワード: ユーザー認証。English: user authentication. 中文：用户认证。标记 LANG-MIX-99。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("locales/ja.json", '{"login": "ログイン", "logout": "ログアウト", "LANG-MIX-99": true}'),
        ("locales/en.json", '{"login": "login", "logout": "logout", "LANG-MIX-99": true}'),
        ("locales/zh.json", '{"login": "登录", "logout": "登出", "LANG-MIX-99": true}'),
        ("src/i18n/manager.py", "def get_locale(lang)"),
        ("tests/test_i18n.py", "assert ja['login'] == 'ログイン'"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ml_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ml_{i}"))
    return msgs


def build_numerical_precision_dialog() -> list[Any]:
    """Probe: exact numerical values (pi, large numbers, small rates) must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="调优参数：pi=3.1415926535, discount=99.99%, users=1234567890, rate=0.0001, max_retry=3, timeout_ms=15000。约束：pi 必须精确到小数点后 10 位。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/params.yaml", "pi: 3.1415926535, discount: 99.99%, users: 1234567890"),
        ("config/params.yaml", "rate: 0.0001, max_retry: 3, timeout_ms: 15000"),
        ("src/calculator.py", "PI = 3.1415926535"),
        ("tests/test_calc.py", "assert pi == 3.1415926535"),
        ("src/limiter.py", "rate = 0.0001, retry = 3"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"np_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"np_{i}"))
    return msgs


def build_multi_tool_per_turn_dialog() -> list[Any]:
    """Probe: one assistant message with multiple tool calls (multi-tool turn)."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="同时读取 config/db.yaml, config/redis.yaml, config/mq.yaml 三个文件，标记 MULTI-TOOL-4A。"),
    ]
    msgs.append(AIMessage(
        content="批量读取配置",
        tool_calls=[
            {"name": "readline_in_range", "args": {"file_path": "config/db.yaml", "start_line": 1, "end_line": 40}, "id": "mt_0", "type": "tool_call"},
            {"name": "readline_in_range", "args": {"file_path": "config/redis.yaml", "start_line": 1, "end_line": 40}, "id": "mt_1", "type": "tool_call"},
            {"name": "readline_in_range", "args": {"file_path": "config/mq.yaml", "start_line": 1, "end_line": 40}, "id": "mt_2", "type": "tool_call"},
        ],
        usage_metadata={"input_tokens": 12_000, "output_tokens": 200, "total_tokens": 12_200},
    ))
    msgs.append(ToolMessage(content="db: host=db-host MULTI-TOOL-4A\n" + PAD, tool_call_id="mt_0"))
    msgs.append(ToolMessage(content="redis: host=redis-host MULTI-TOOL-4A\n" + PAD, tool_call_id="mt_1"))
    msgs.append(ToolMessage(content="mq: host=mq-host MULTI-TOOL-4A\n" + PAD, tool_call_id="mt_2"))
    msgs.append(_ai("继续读取", "readline_in_range", {"file_path": "config/app.yaml", "start_line": 1, "end_line": 40}, "mt_3", 14_000))
    msgs.append(ToolMessage(content="app: port=8080 MULTI-TOOL-4A\n" + PAD, tool_call_id="mt_3"))
    return msgs


def build_special_char_paths_dialog() -> list[Any]:
    """Probe: paths with special chars (spaces, brackets, unicode) must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="阅读特殊路径：'src/[my app]/test file.py', 'src/中文/测试.py', 'src/(temp)/data.json'。标记 SPECIAL-PATH-5B。"),
    ]
    paths = [
        ("src/[my app]/test file.py", "class TestFile"),
        ("src/中文/测试.py", "def 测试函数"),
        ("src/(temp)/data.json", '{"temp": true, "SPECIAL-PATH-5B": true}'),
        ("src/[my app]/test file.py", "assert SPECIAL-PATH-5B"),
        ("src/中文/测试.py", "结果 = 测试函数()"),
    ]
    for i, (path, excerpt) in enumerate(paths):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"sp_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"sp_{i}"))
    return msgs


def build_code_block_dialog() -> list[Any]:
    """Probe: code block / function definition must survive."""
    code = "def fibonacci(n: int, memo: dict | None = None) -> int:\n    if n <= 1: return n\n    if memo is None: memo = {}\n    if n not in memo: memo[n] = fibonacci(n-1, memo) + fibonacci(n-2, memo)\n    return memo[n]"
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="优化 fibonacci 函数，标记 CODE-BLOCK-6C。确保递归版本和 memo 缓存。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/fib.py", code),
        ("src/fib.py", "CODE-BLOCK-6C: fibonacci with memo"),
        ("tests/test_fib.py", "assert fib(10) == 55"),
        ("src/fib.py", "fib(100) # CODE-BLOCK-6C"),
        ("src/fib.py", "def fibonacci_optimized"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"cb_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"cb_{i}"))
    return msgs


def build_dependency_version_dialog() -> list[Any]:
    """Probe: package==version pins must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="更新依赖：fastapi==0.115.0, pydantic==2.10.0, sqlalchemy==2.0.35, redis==5.2.0。约束：不要动 pytest 版本。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("requirements.txt", "fastapi==0.115.0\npydantic==2.10.0\nsqlalchemy==2.0.35\nredis==5.2.0"),
        ("requirements.txt", "pytest==8.3.0  # must not change"),
        ("src/main.py", "from fastapi import FastAPI"),
        ("src/db.py", "from sqlalchemy import create_engine"),
        ("tests/test_deps.py", "DEP-VERIFY-7D"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"dv_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"dv_{i}"))
    return msgs


def build_env_var_dialog() -> list[Any]:
    """Probe: environment variable names and values must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="配置环境变量。DATABASE_URL=postgresql://user:pass@localhost:5432/db。REDIS_URL=redis://localhost:6379/0。约束：ENV-KEY-8E 必须保留。"),
    ]
    for i, (path, excerpt) in enumerate([
        (".env.example", "DATABASE_URL=postgresql://user:pass@localhost:5432/db"),
        (".env.example", "REDIS_URL=redis://localhost:6379/0"),
        (".env.example", "ENV-KEY-8E=production"),
        ("src/config.py", "DATABASE_URL = os.getenv('DATABASE_URL')"),
        ("src/config.py", "ENV-KEY-8E = os.getenv('ENV-KEY-8E')"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ev_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ev_{i}"))
    return msgs


def build_similar_tokens_dialog() -> list[Any]:
    """Probe: multiple similar tokens must be distinguished."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="项目有 3 个版本参数：VER-V1 用于 API，VER-V2 用于 DB，VER-V3 用于 CACHE。把 VER-V1 升级到 2.0.0，VER-V2 升级到 3.0.0，VER-V3 保持不动。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/api/version.py", "VER-V1 = '1.5.0'  # API version"),
        ("src/db/version.py", "VER-V2 = '2.5.0'  # DB version"),
        ("src/cache/version.py", "VER-V3 = '1.0.0'  # CACHE version (keep)"),
        ("src/api/version.py", "VER-V1 = '2.0.0'  # upgraded"),
        ("src/db/version.py", "VER-V2 = '3.0.0'  # upgraded"),
        ("src/cache/version.py", "VER-V3 = '1.0.0'  # unchanged"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"sv_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"sv_{i}"))
    return msgs


def build_negative_constraints_dialog() -> list[Any]:
    """Probe: multiple negative constraints (don't do X) must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="重构 UserService。约束：不要改 UserSchema，不要删 login()，不要动 db/migrations，不要改 public API 签名。标记 NEG-CON-9F。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/user/schema.py", "class UserSchema # MUST NOT CHANGE"),
        ("src/user/service.py", "def login()  # DO NOT DELETE"),
        ("db/migrations/001_init.py", "DO NOT TOUCH this directory"),
        ("src/user/api.py", "def get_user(id)  # public API, keep signature"),
        ("src/user/service.py", "def register()"),
        ("README.md", "NEG-CON-9F constraints"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"nc_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"nc_{i}"))
    return msgs


def build_priority_order_dialog() -> list[Any]:
    """Probe: P0/P1/P2 priority ordering must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="发布计划：P0 - 修复 PAYMENT-BLOCKER-0P（支付阻塞），P1 - 添加日志，P2 - 优化性能。P0 必须在 P1 之前完成。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("docs/release-plan.md", "P0: PAYMENT-BLOCKER-0P - 支付阻塞修复"),
        ("docs/release-plan.md", "P1: 添加结构化日志"),
        ("docs/release-plan.md", "P2: 性能优化"),
        ("src/payment/blocker.py", "PAYMENT-BLOCKER-0P fix"),
        ("src/logging.py", "P1: 结构化日志"),
        ("src/optimizer.py", "P2: 性能优化"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"po_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"po_{i}"))
    return msgs


def build_timestamp_dialog() -> list[Any]:
    """Probe: ISO 8601 timestamps must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="配置定时任务：2026-07-27T15:30:00Z 触发 backup，2026-07-28T00:00:00Z 触发 cleanup。约束：backup 时间不能晚于 cleanup。标记 TIMESTAMP-0T。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("config/scheduler.yaml", "backup: 2026-07-27T15:30:00Z"),
        ("config/scheduler.yaml", "cleanup: 2026-07-28T00:00:00Z"),
        ("src/scheduler.py", "def backup_job()  # TIMESTAMP-0T"),
        ("src/scheduler.py", "def cleanup_job()  # TIMESTAMP-0T"),
        ("tests/test_scheduler.py", "assert backup < cleanup"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ts_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ts_{i}"))
    return msgs


def build_file_permission_dialog() -> list[Any]:
    """Probe: file permission values must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="设置权限：config file 644, script 755, private key 600, directory 755。约束：private key 权限必须最小。标记 PERM-1P。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("scripts/deploy.sh", "chmod 755 scripts/deploy.sh"),
        ("config/app.yaml", "chmod 644 config/app.yaml"),
        ("secrets/id_rsa", "chmod 600 secrets/id_rsa"),
        ("scripts/deploy.sh", "mkdir -p /app && chmod 755 /app"),
        ("README.md", "PERM-1P: permission rules"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"pf_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"pf_{i}"))
    return msgs


def build_docker_config_dialog() -> list[Any]:
    """Probe: Dockerfile EXPOSE and ENV must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="容器化：EXPOSE 3000, ENV NODE_ENV=production, 镜像 node:20-alpine, 健康检查 http://localhost:3000/health。标记 DOCKER-2D。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("Dockerfile", "FROM node:20-alpine\nEXPOSE 3000\nENV NODE_ENV=production"),
        ("Dockerfile", "HEALTHCHECK curl http://localhost:3000/health"),
        ("docker-compose.yml", "image: node:20-alpine (DOCKER-2D)"),
        ("docker-compose.yml", "ports: 3000:3000"),
        ("src/health.py", "DOCKER-2D health endpoint"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"dk_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"dk_{i}"))
    return msgs


def build_ci_cd_config_dialog() -> list[Any]:
    """Probe: CI/CD workflow config (GitHub Actions) must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="配置 GitHub Actions：python 3.11, 运行 pytest, 上传 coverage 到 codecov。workflow 名称 CI-CD-3C。约束：不要改 deploy 步骤。"),
    ]
    for i, (path, excerpt) in enumerate([
        (".github/workflows/ci.yml", "name: CI-CD-3C"),
        (".github/workflows/ci.yml", "python-version: '3.11'"),
        (".github/workflows/ci.yml", "run: pytest --cov=src"),
        (".github/workflows/ci.yml", "uses: codecov/codecov-action@v4"),
        (".github/workflows/deploy.yml", "DO NOT CHANGE"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"ci_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"ci_{i}"))
    return msgs


def build_sql_migration_dialog() -> list[Any]:
    """Probe: SQL migration statements must survive."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="数据库迁移：ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE。ALTER TABLE orders ADD INDEX idx_created_at。标记 SQL-MIG-4M。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("db/migrations/002_add_email_verified.sql", "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT FALSE;"),
        ("db/migrations/003_add_order_index.sql", "ALTER TABLE orders ADD INDEX idx_created_at (created_at);"),
        ("src/models/user.py", "email_verified = Column(Boolean, default=False)"),
        ("src/models/order.py", "SQL-MIG-4M index on created_at"),
        ("tests/test_migration.py", "assert email_verified is False"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"sq_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"sq_{i}"))
    return msgs


def build_similar_file_discrimination_dialog() -> list[Any]:
    """Probe: similar files in different directories must be distinguished."""
    msgs = [
        SystemMessage(content="agent"),
        HumanMessage(content="项目有 v1 和 v2 两个版本的 handler。读 v1 的 handler.py 和 v2 的 handler.py。标记 DIFF-VERSION-5N。约束：v1 的不要改，只改 v2。"),
    ]
    for i, (path, excerpt) in enumerate([
        ("src/api/v1/handler.py", "class HandlerV1: DIFF-VERSION-5N - DO NOT MODIFY"),
        ("src/api/v2/handler.py", "class HandlerV2: DIFF-VERSION-5N - needs update"),
        ("src/api/v1/handler.py", "def process_v1(data)"),
        ("src/api/v2/handler.py", "def process_v2(data)"),
        ("src/api/v2/handler.py", "MODIFIED: process_v2 updated"),
    ]):
        msgs.append(_ai(f"step {i}", "readline_in_range", {"file_path": path, "start_line":1,"end_line":40}, f"sf_{i}", 8_000 + i * 4_000))
        msgs.append(ToolMessage(content=f"{path}\n{excerpt}\n{PAD}", tool_call_id=f"sf_{i}"))
    return msgs


# =============================================================================
# Case functions
# =============================================================================

async def case_31_api_key(llm: Any) -> CaseResult:
    """API key sk-xxx format must survive compaction."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_api_key_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(31, "api_key_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("sk-7f3a2b1c" in s.lower(), "API key sk-xxx lost", errors)
    _must("git" in s.lower() or ".gitignore" in s, "gitignore constraint lost", errors)
    return CaseResult(31, "api_key_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_32_url_endpoint(llm: Any) -> CaseResult:
    """Exact URL and endpoint must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_url_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(32, "url_endpoint_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("hooks.example.com" in s or "example.com" in s or "webhook" in s.lower(), "webhook URL lost", errors)
    _must("300" in s or "300s" in s or "interval" in s.lower(), "interval value lost", errors)
    return CaseResult(32, "url_endpoint_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_33_stack_trace(llm: Any) -> CaseResult:
    """Stack trace frame with file:line must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_stack_trace_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(33, "stack_trace_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("STACK-TRACE-7Z" in s or "task.py" in s or "worker" in s.lower(), "trace marker/context lost", errors)
    _must("TypeError" in s or "NoneType" in s or "142" in s or "pipeline" in s.lower(), "error type/context lost", errors)
    return CaseResult(33, "stack_trace_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_34_port_numbers(llm: Any) -> CaseResult:
    """Port numbers and service endpoints must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_port_config_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(34, "port_numbers_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("8080" in s, "gateway port 8080 lost", errors)
    _must("5432" in s or "6379" in s or "5672" in s, "db/redis/mq port lost", errors)
    hits = sum(1 for p in ["8080", "8081", "8082", "8083"] if p in s)
    _must(hits >= 3, f"only {hits}/4 service ports found", errors)
    return CaseResult(34, "port_numbers_accuracy", not errors, time.time() - t0, f"ports={hits}/4", errors)


async def case_35_multilingual(llm: Any) -> CaseResult:
    """Chinese, English, Japanese mixed content must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_multilingual_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(35, "multilingual_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("LANG-MIX-99" in s, "lang marker lost", errors)
    _must("ログイン" in s or "ログ" in s or "ユーザ" in s or "ja" in s.lower() or "Japanese" in s.lower(), "Japanese content lost", errors)
    _must("登录" in s or "用户认证" in s or "认证" in s or "zh" in s.lower() or "Chinese" in s.lower(), "Chinese content lost", errors)
    return CaseResult(35, "multilingual_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_36_numerical_precision(llm: Any) -> CaseResult:
    """Exact numerical values must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_numerical_precision_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(36, "numerical_precision_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("3.1415926535" in s or "3.14159" in s, "pi value lost", errors)
    _must("99.99%" in s or "99.99" in s, "discount percentage lost", errors)
    _must("1234567890" in s or "1234567" in s, "large number lost", errors)
    return CaseResult(36, "numerical_precision_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_37_multi_tool_per_turn(llm: Any) -> CaseResult:
    """One assistant message with multiple tool calls must compact correctly."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_multi_tool_per_turn_dialog()
    settings = CompactionSettings(enabled=True, reserve_tokens=5_000, keep_recent_tokens=500)
    prep = prepare_compaction(msgs, settings)
    if prep is None: return CaseResult(37, "multi_tool_per_turn_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("MULTI-TOOL-4A" in s, "multi-tool marker lost", errors)
    _must("db" in s.lower() or "redis" in s.lower() or "mq" in s.lower(), "config host context lost", errors)
    _must(len(result.messages) < len(msgs), "messages not reduced", errors)
    return CaseResult(37, "multi_tool_per_turn_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_38_special_char_paths(llm: Any) -> CaseResult:
    """Paths with special chars (spaces, brackets, unicode) must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_special_char_paths_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(38, "special_char_paths_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("SPECIAL-PATH-5B" in s, "special path marker lost", errors)
    _must("测试" in s or "中文" in s, "Chinese path lost", errors)
    _must("[my app]" in s or "my app" in s.lower(), "bracket path lost", errors)
    return CaseResult(38, "special_char_paths_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_39_code_block(llm: Any) -> CaseResult:
    """Code block / function definition must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_code_block_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(39, "code_block_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("CODE-BLOCK-6C" in s, "code block marker lost", errors)
    _must("fibonacci" in s, "function name lost", errors)
    _must("memo" in s, "memo parameter lost", errors)
    return CaseResult(39, "code_block_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_40_dependency_versions(llm: Any) -> CaseResult:
    """Package==version pins must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_dependency_version_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(40, "dependency_versions_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("fastapi" in s.lower() or "0.115.0" in s, "fastapi version lost", errors)
    _must("pydantic" in s.lower() or "2.10.0" in s, "pydantic version lost", errors)
    _must("pytest" in s.lower(), "pytest constraint lost", errors)
    return CaseResult(40, "dependency_versions_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_41_env_vars(llm: Any) -> CaseResult:
    """Environment variable names and values must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_env_var_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(41, "env_var_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("DATABASE_URL" in s or "database_url" in s.lower(), "DATABASE_URL env var lost", errors)
    _must("REDIS_URL" in s or "redis_url" in s.lower(), "REDIS_URL env var lost", errors)
    _must("ENV-KEY-8E" in s, "ENV-KEY-8E marker lost", errors)
    return CaseResult(41, "env_var_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_42_similar_tokens(llm: Any) -> CaseResult:
    """Multiple similar tokens must be distinguished."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_similar_tokens_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(42, "similar_tokens_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("VER-V1" in s, "VER-V1 token lost", errors)
    _must("VER-V2" in s, "VER-V2 token lost", errors)
    _must("2.0.0" in s or "3.0.0" in s, "version numbers lost", errors)
    return CaseResult(42, "similar_tokens_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_43_negative_constraints(llm: Any) -> CaseResult:
    """Multiple negative constraints (don't do X) must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_negative_constraints_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(43, "negative_constraints_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("NEG-CON-9F" in s, "negative constraint marker lost", errors)
    _must("UserSchema" in s or "schema" in s.lower(), "UserSchema constraint lost", errors)
    _must("public API" in s or "API" in s, "public API constraint lost", errors)
    return CaseResult(43, "negative_constraints_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_44_priority_order(llm: Any) -> CaseResult:
    """P0/P1/P2 priority ordering must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_priority_order_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(44, "priority_order_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("PAYMENT-BLOCKER-0P" in s, "P0 blocker marker lost", errors)
    _must("P0" in s or "P1" in s or "P2" in s, "priority labels lost", errors)
    return CaseResult(44, "priority_order_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_45_timestamps(llm: Any) -> CaseResult:
    """ISO 8601 timestamps must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_timestamp_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(45, "timestamp_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("TIMESTAMP-0T" in s, "timestamp marker lost", errors)
    _must("2026-07-27" in s or "2026-07-28" in s, "ISO date lost", errors)
    _must("backup" in s.lower() or "cleanup" in s.lower(), "backup/cleanup context lost", errors)
    return CaseResult(45, "timestamp_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_46_file_permissions(llm: Any) -> CaseResult:
    """File permission values must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_file_permission_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(46, "file_permissions_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("PERM-1P" in s, "permission marker lost", errors)
    _must("755" in s or "644" in s or "600" in s, "permission values lost", errors)
    return CaseResult(46, "file_permissions_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_47_docker_config(llm: Any) -> CaseResult:
    """Dockerfile EXPOSE and ENV must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_docker_config_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(47, "docker_config_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("DOCKER-2D" in s, "docker marker lost", errors)
    _must("3000" in s, "EXPOSE 3000 lost", errors)
    _must("node:20-alpine" in s or "node" in s, "base image lost", errors)
    _must("NODE_ENV" in s or "production" in s, "ENV value lost", errors)
    return CaseResult(47, "docker_config_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_48_ci_cd_config(llm: Any) -> CaseResult:
    """CI/CD workflow config must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_ci_cd_config_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(48, "ci_cd_config_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("CI-CD-3C" in s, "CI/CD marker lost", errors)
    _must("3.11" in s or "python" in s.lower(), "python version lost", errors)
    _must("pytest" in s.lower() or "coverage" in s.lower(), "pytest/coverage context lost", errors)
    return CaseResult(48, "ci_cd_config_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_49_sql_migration(llm: Any) -> CaseResult:
    """SQL migration statements must survive."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_sql_migration_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(49, "sql_migration_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("SQL-MIG-4M" in s, "SQL migration marker lost", errors)
    _must("email_verified" in s.lower(), "column name lost", errors)
    _must("ALTER TABLE" in s or "ADD COLUMN" in s or "ADD INDEX" in s or "migration" in s.lower() or "users" in s.lower(), "SQL context lost", errors)
    return CaseResult(49, "sql_migration_accuracy", not errors, time.time() - t0, s[:240], errors)


async def case_50_similar_file_discrimination(llm: Any) -> CaseResult:
    """Similar files in different directories must be distinguished."""
    errors: list[str] = []; t0 = time.time()
    msgs = build_similar_file_discrimination_dialog()
    prep = prepare_compaction(msgs, SETTINGS)
    if prep is None: return CaseResult(50, "similar_file_discrimination_accuracy", False, 0, "prepare returned None", errors=["prepare_compaction returned None"])
    result = await compact(prep, llm, reason="threshold")  # type: ignore[arg-type]
    s = result.summary
    _must("DIFF-VERSION-5N" in s, "version discrimination marker lost", errors)
    _must("v1" in s.lower() or "v2" in s.lower() or "HandlerV1" in s or "HandlerV2" in s, "version distinction lost", errors)
    _must("DO NOT MODIFY" in s or "not modify" in s.lower(), "v1 constraint lost", errors)
    return CaseResult(50, "similar_file_discrimination_accuracy", not errors, time.time() - t0, s[:240], errors)


CASES: list[tuple[int, str, Callable[[Any], Any]]] = [
    (31, "API key accuracy", case_31_api_key),
    (32, "URL endpoint accuracy", case_32_url_endpoint),
    (33, "stack trace accuracy", case_33_stack_trace),
    (34, "port numbers accuracy", case_34_port_numbers),
    (35, "multilingual accuracy", case_35_multilingual),
    (36, "numerical precision accuracy", case_36_numerical_precision),
    (37, "multi-tool per turn accuracy", case_37_multi_tool_per_turn),
    (38, "special char paths accuracy", case_38_special_char_paths),
    (39, "code block accuracy", case_39_code_block),
    (40, "dependency versions accuracy", case_40_dependency_versions),
    (41, "env var accuracy", case_41_env_vars),
    (42, "similar tokens accuracy", case_42_similar_tokens),
    (43, "negative constraints accuracy", case_43_negative_constraints),
    (44, "priority order accuracy", case_44_priority_order),
    (45, "timestamp accuracy", case_45_timestamps),
    (46, "file permissions accuracy", case_46_file_permissions),
    (47, "Docker config accuracy", case_47_docker_config),
    (48, "CI/CD config accuracy", case_48_ci_cd_config),
    (49, "SQL migration accuracy", case_49_sql_migration),
    (50, "similar file discrimination accuracy", case_50_similar_file_discrimination),
]


async def main() -> None:
    print(f"model={LLM_MODEL} base={DASHSCOPE_BASE_URL} key=***{DASHSCOPE_API_KEY[-8:]}")
    llm = build_llm()
    results: list[CaseResult] = []
    for case_id, title, fn in CASES:
        print("\n" + "=" * 72)
        print(f"CASE {case_id}/50: {title}")
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