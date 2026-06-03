#!/usr/bin/env python3
"""E2E: CodeAgent + Gitee clone + read-code skill scheme (real LLM, no agent registry).

Requires:
  - DASHSCOPE_API_KEY (or OPENAI_API_KEY)
  - GITEE_TOKEN (for private repos; public repos may work without)
  - Network to Gitee, skill-hub, LLM API

Optional env:
  - GITEE_REPO_URL (default: https://gitee.com/jamesxiong888/test-code.git)
  - GITEE_BRANCH (default: main)
  - SKILL_HUB_URL (default: http://10.17.0.41:31899)
  - DASHSCOPE_LLM_MODEL (default: deepseek-v4-flash)
  - E2E_QUERY — override the question (single-case mode only)
  - E2E_CASE — run one case id from the built-in suite (see E2E_CASES below)
  - E2E_CASES — comma-separated case ids, or ``all`` (default)
  - GREP_RECALL_SCHEME — ``read_code_skill`` (default) or ``metadata_local`` (方案 B)
  - E2E_ANSWER_MODEL — ``original`` (default) or ``full``

Built-in cases (test-code repo on Gitee):
  Natural language (完整句):
    - db_connection, product_keyword_search, order_transaction_safety,
      order_total_amount, top_level_categories, user_registration_fields
  Casual / orchestrator-style (口语、短问):
    - casual_order_fail — 「下单失败了怎么办？」
    - casual_change_password — 「改密码在哪做的？」
    - casual_order_history — 「怎么查用户买过啥？」

Run:
    cd dac/code-agent
    python scripts/e2e_read_code_skill_gitee.py
    E2E_CASE=casual_order_fail python scripts/e2e_read_code_skill_gitee.py
    GREP_RECALL_SCHEME=metadata_local python scripts/e2e_read_code_skill_gitee.py
    E2E_CASES=casual_order_fail,casual_change_password python scripts/e2e_read_code_skill_gitee.py
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# E2E-only: when skill-hub is unreachable, copy this zip (NOT used in production code).
E2E_READ_CODE_ZIP_FALLBACK = Path(
    os.environ.get(
        "LOCAL_READ_CODE_ZIP_FALLBACK",
        "/Users/james/daocloud/code/dac/skill_sdk/skills/read-code.zip",
    )
).expanduser().resolve()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("e2e_read_code_skill_gitee")

SKILL_HUB = os.environ.get("SKILL_HUB_URL", "http://10.17.0.41:31899")
MODEL = os.environ.get("DASHSCOPE_LLM_MODEL", "deepseek-v4-flash")
BASE_URL = os.environ.get(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
GITEE_REPO = os.environ.get(
    "GITEE_REPO_URL", "https://gitee.com/jamesxiong888/test-code.git"
)
GITEE_BRANCH = os.environ.get("GITEE_BRANCH", "main")


@dataclass(frozen=True)
class E2ECase:
    """One E2E scenario with objective pass/fail checks."""

    id: str
    query: str
    description: str
    expected_files: tuple[str, ...] = ("code.py",)
    # At least min_keyword_hits of these must appear in snippets + step answer (lower-cased).
    expected_keywords: tuple[str, ...] = ()
    min_keyword_hits: int = 1
    min_snippets: int = 1
    tags: tuple[str, ...] = field(default_factory=tuple)


E2E_CASES: tuple[E2ECase, ...] = (
    E2ECase(
        id="db_connection",
        description="自然语言问数据库连接实现（不提及类名）",
        query="这个仓库里的电商后端是怎么连 MySQL 的？连接和断开数据库分别在哪儿实现的，帮我找到对应代码。",
        expected_keywords=("databasemanager", "connect", "mysql"),
        min_keyword_hits=2,
        tags=("natural", "infra"),
    ),
    E2ECase(
        id="product_keyword_search",
        description="自然语言问商品关键词搜索逻辑",
        query="前台用户输入关键词搜商品时，后台是怎么查库的？模糊匹配用的是什么方式？",
        expected_keywords=("search_products", "like", "product_name"),
        min_keyword_hits=2,
        tags=("natural", "sql"),
    ),
    E2ECase(
        id="order_transaction_safety",
        description="自然语言问下单失败时的数据一致性",
        query="用户提交订单时，如果中途出错，已经写入的数据会不会留下脏数据？代码里是怎么处理的？",
        expected_keywords=("place_order", "commit", "rollback"),
        min_keyword_hits=2,
        tags=("natural", "transaction"),
    ),
    E2ECase(
        id="order_total_amount",
        description="自然语言问订单总金额计算",
        query="一笔订单的最终金额是怎么汇总出来的？需要读哪些订单明细、用什么方式加总？",
        expected_keywords=("get_order_total_amount", "sum", "subtotal"),
        min_keyword_hits=2,
        tags=("natural", "aggregation"),
    ),
    E2ECase(
        id="top_level_categories",
        description="自然语言问顶级分类查询",
        query="商品分类有层级关系，怎么查出所有没有上级的顶级分类？",
        expected_keywords=("get_root_categories", "parent_id", "null"),
        min_keyword_hits=2,
        tags=("natural", "sql-edge"),
    ),
    E2ECase(
        id="user_registration_fields",
        description="自然语言问注册用户写入字段",
        query="新用户注册时，系统会把哪些信息存进数据库？",
        expected_keywords=("create_user", "insert", "users"),
        min_keyword_hits=2,
        tags=("natural", "insert"),
    ),
    # --- Casual / orchestrator-style: short, colloquial, no technical terms ---
    E2ECase(
        id="casual_order_fail",
        description="口语短问：下单失败怎么办",
        query="下单失败了怎么办？",
        expected_keywords=("place_order", "rollback", "commit"),
        min_keyword_hits=2,
        tags=("casual", "transaction"),
    ),
    E2ECase(
        id="casual_change_password",
        description="口语短问：改密码在哪实现",
        query="改密码在哪做的？",
        expected_keywords=("change_password", "password", "update"),
        min_keyword_hits=2,
        tags=("casual", "user"),
    ),
    E2ECase(
        id="casual_order_history",
        description="口语短问：查用户历史订单",
        query="怎么查用户买过啥？",
        expected_keywords=("get_user_order_history", "get_orders_by_user", "order"),
        min_keyword_hits=2,
        tags=("casual", "order"),
    ),
)


def resolve_e2e_grep_scheme() -> str:
    """E2E grep recall scheme from env (default read_code_skill)."""
    from agent.tools.skill_read_code_recall import (
        SCHEME_METADATA_LOCAL,
        SCHEME_READ_CODE,
        resolve_grep_recall_scheme,
    )

    raw = (os.environ.get("GREP_RECALL_SCHEME") or SCHEME_READ_CODE).strip()
    scheme = resolve_grep_recall_scheme(explicit=raw)
    if scheme not in (SCHEME_READ_CODE, SCHEME_METADATA_LOCAL):
        raise SystemExit(f"Unsupported GREP_RECALL_SCHEME={raw!r}")
    return scheme


def build_codebase_index_for_e2e(repo_root: Path):
    """E2E-only: build CodebaseIndex from cloned repo AST (no data-services)."""
    from agent.code_agent import CodebaseIndex

    records: list[dict] = []
    for fp in sorted(repo_root.rglob("*.py")):
        if any(part.startswith(".") for part in fp.parts):
            continue
        rel = fp.relative_to(repo_root).as_posix()
        try:
            text = fp.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(fp))
        except (OSError, SyntaxError) as exc:
            logger.warning("E2E index skip %s: %s", rel, exc)
            continue

        entities: list[dict] = []
        global_functions: list[dict] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                funcs: list[dict] = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        start = item.lineno
                        end = getattr(item, "end_lineno", item.lineno)
                        doc = (ast.get_docstring(item) or "").strip()
                        funcs.append(
                            {
                                "name": item.name,
                                "purpose": doc[:300] if doc else item.name,
                                "line_no": f"{start}-{end}",
                            }
                        )
                start = node.lineno
                end = getattr(node, "end_lineno", node.lineno)
                entities.append(
                    {
                        "name": node.name,
                        "business_meaning": (ast.get_docstring(node) or node.name).strip(),
                        "line_no": f"{start}-{end}",
                        "functions": funcs,
                    }
                )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", node.lineno)
                doc = (ast.get_docstring(node) or "").strip()
                global_functions.append(
                    {
                        "name": node.name,
                        "purpose": doc[:300] if doc else node.name,
                        "line_no": f"{start}-{end}",
                    }
                )

        analysis = {
            "file_summary": f"Python module {rel}",
            "file_path": rel,
            "entities": entities,
            "global_functions": global_functions,
            "api_endpoints": [],
        }
        records.append(
            {
                "filepath": rel,
                "code_deep_analysis": json.dumps(analysis, ensure_ascii=False),
            }
        )

    index = CodebaseIndex()
    index.load_from_records(records)
    logger.info(
        "E2E: built local CodebaseIndex from %s (%d files, %d entities)",
        repo_root,
        len(index.file_index),
        len(index.entity_index),
    )
    return index


def _require_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not key.strip() or key.strip() == "sk-xxx":
        raise SystemExit("Set DASHSCOPE_API_KEY (or OPENAI_API_KEY) for live LLM E2E.")
    return key.strip()


def _pick_query_from_repo(repo_root: Path) -> str:
    """Build a concrete question from cloned repo contents."""
    override = (os.environ.get("E2E_QUERY") or "").strip()
    if override:
        return override

    symbol_re = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.MULTILINE)
    for pattern in ("**/*.py", "**/*.go", "**/*.java"):
        for fp in sorted(repo_root.glob(pattern)):
            if any(part.startswith(".") for part in fp.parts):
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = symbol_re.search(text)
            if not m:
                continue
            rel = fp.relative_to(repo_root).as_posix()
            sym = m.group(1)
            return f"这个仓库里和「{sym}」相关的核心逻辑在哪里？请阅读源码后说明其实现。"
    return "这个仓库主要是做什么的？有哪些关键业务代码，请定位并简要说明。"


def resolve_e2e_cases() -> list[E2ECase]:
    """Pick cases from env: E2E_QUERY (single ad-hoc), E2E_CASE, or E2E_CASES."""
    override_query = (os.environ.get("E2E_QUERY") or "").strip()
    if override_query:
        return [
            E2ECase(
                id="custom",
                description="E2E_QUERY override",
                query=override_query,
                expected_keywords=(),
                min_keyword_hits=0,
                min_snippets=0,
            )
        ]

    by_id = {c.id: c for c in E2E_CASES}
    single = (os.environ.get("E2E_CASE") or "").strip()
    if single:
        if single not in by_id:
            known = ", ".join(by_id)
            raise SystemExit(f"Unknown E2E_CASE={single!r}. Known: {known}")
        return [by_id[single]]

    raw = (os.environ.get("E2E_CASES") or "all").strip().lower()
    if raw in ("", "all"):
        return list(E2E_CASES)

    selected: list[E2ECase] = []
    for part in raw.split(","):
        cid = part.strip()
        if not cid:
            continue
        if cid not in by_id:
            known = ", ".join(by_id)
            raise SystemExit(f"Unknown case id {cid!r} in E2E_CASES. Known: {known}")
        selected.append(by_id[cid])
    if not selected:
        raise SystemExit("E2E_CASES is empty after parsing.")
    return selected


def _build_descriptor_types(repo_url: str, branch: str, token: str) -> list[str]:
    payload = [
        {
            "name": "e2e-gitee",
            "descriptorType": "code",
            "codeRepoType": "git",
            "codeRepoPath": repo_url,
            "codeRepoBranch": branch,
            "codeRepoToken": token or "",
        }
    ]
    return [json.dumps(payload, ensure_ascii=False)]


def ensure_read_code_skill_for_e2e(skills_dir: Path, *, skill_hub_url: str, timeout: float) -> list[Path]:
    """Try skill-hub; on failure copy local read-code.zip (E2E test helper only)."""
    from agent.skill_download import download_skills

    paths = download_skills(
        skill_hub_url=skill_hub_url,
        target_dir=str(skills_dir),
        timeout=timeout,
    )
    if paths:
        return paths

    fallback = E2E_READ_CODE_ZIP_FALLBACK
    if not fallback.is_file():
        logger.error(
            "E2E: skill-hub download failed and fallback zip missing: %s",
            fallback,
        )
        return []

    dest = skills_dir / "read-code.zip"
    shutil.copy2(fallback, dest)
    logger.info("E2E: skill-hub unavailable — using local fallback %s -> %s", fallback, dest)
    return [dest]


def _snippet_blob(snippets: list[dict]) -> str:
    parts: list[str] = []
    for s in snippets:
        parts.append(str(s.get("file_path", "")))
        parts.append(str(s.get("name", "")))
        parts.append(str(s.get("code", "")))
        parts.append(str(s.get("code_content", "")))
        parts.append(str(s.get("content", "")))
        parts.append(str(s.get("business_meaning", "")))
    return "\n".join(parts).lower()


def _evaluate_case(
    case: E2ECase,
    *,
    scheme: str,
    expected_scheme: str,
    skill_snippets: list[dict],
    metadata_snippets: list[dict],
    all_snippets: list[dict],
    answer: str,
) -> tuple[bool, list[str]]:
    """Return (passed, failure_reasons)."""
    from agent.tools.skill_read_code_recall import SCHEME_METADATA_LOCAL, SCHEME_READ_CODE

    failures: list[str] = []
    blob = (_snippet_blob(all_snippets) + "\n" + answer).lower()

    if scheme != expected_scheme:
        failures.append(f"grep_recall_scheme={scheme!r}, expected {expected_scheme!r}")

    if expected_scheme == SCHEME_READ_CODE:
        if len(skill_snippets) < case.min_snippets:
            failures.append(
                f"skill_read_code snippets={len(skill_snippets)}, "
                f"expected >= {case.min_snippets}"
            )
    elif expected_scheme == SCHEME_METADATA_LOCAL:
        if len(metadata_snippets) < case.min_snippets:
            failures.append(
                f"metadata/local_grep snippets={len(metadata_snippets)}, "
                f"expected >= {case.min_snippets}"
            )

    if not answer.strip():
        failures.append("empty step() answer")

    if expected_scheme == SCHEME_READ_CODE:
        if "read-code skill" in answer.lower() and "unavailable" in answer.lower():
            failures.append("skill unavailable mentioned in answer")

    if case.expected_files:
        file_hits = sum(1 for fp in case.expected_files if fp.lower() in blob)
        if file_hits == 0:
            failures.append(f"none of expected files {case.expected_files} in snippets/answer")

    if case.expected_keywords:
        hits = [kw for kw in case.expected_keywords if kw.lower() in blob]
        if len(hits) < case.min_keyword_hits:
            failures.append(
                f"keyword hits {len(hits)}/{case.min_keyword_hits}: "
                f"found={hits}, expected_any={list(case.expected_keywords)}"
            )

    grep_snippets = skill_snippets if expected_scheme == SCHEME_READ_CODE else metadata_snippets
    if "code-agent" in answer and len(grep_snippets) == 0:
        if any(x in answer for x in ("agent/code_agent.py", "skill_runner_service")):
            failures.append("answer from wrong workspace (code-agent tree)")

    has_code_signal = (
        len(all_snippets) > 0
        or "===" in answer
        or "```" in answer
        or any(ext in answer for ext in (".py", ".go", ".java"))
    )
    if not has_code_signal and case.min_snippets > 0:
        failures.append("no code-location signal in snippets or answer")

    return (len(failures) == 0, failures)


async def _run_single_case(
    case: E2ECase,
    *,
    agent_factory,
    case_index: int,
    case_total: int,
    expected_scheme: str,
) -> dict:
    """Run grep recall + step for one case; return result dict."""
    from agent.code_agent import CodeAgent
    from agent.tools.skill_read_code_recall import SCHEME_METADATA_LOCAL

    t0 = time.monotonic()
    print(f"\n{'=' * 72}")
    print(f"CASE [{case_index}/{case_total}] {case.id}")
    print(f"    {case.description}")
    print(f"    tags: {', '.join(case.tags) or '-'}")
    print(f"    query: {case.query}")

    agent: CodeAgent = agent_factory(case.query)
    grep_result = await agent.grep_recall_code_segments(max_results=10, use_llm_filter=False)
    scheme = grep_result.get("grep_recall_scheme", "")
    snippets = grep_result.get("code_snippets") or []
    skill_snippets = [s for s in snippets if s.get("source") == "skill_read_code"]
    metadata_snippets = [
        s for s in snippets if s.get("source") in ("metadata", "local_grep")
    ]

    print(f"    grep scheme: {scheme}")
    if expected_scheme == SCHEME_METADATA_LOCAL:
        meta_n = sum(1 for s in metadata_snippets if s.get("source") == "metadata")
        local_n = sum(1 for s in metadata_snippets if s.get("source") == "local_grep")
        print(
            f"    metadata/local snippets: {len(metadata_snippets)} "
            f"(metadata={meta_n}, local_grep={local_n}) / total {len(snippets)}"
        )
        print(
            f"    local_grep_count={grep_result.get('local_grep_count', 0)}, "
            f"keywords={grep_result.get('keywords', {})}"
        )
        preview_snippets = metadata_snippets
    else:
        print(f"    skill snippets: {len(skill_snippets)} / total {len(snippets)}")
        preview_snippets = skill_snippets
    for i, s in enumerate(preview_snippets[:2], 1):
        print(
            f"    snippet[{i}] {s.get('file_path')} "
            f"source={s.get('source')} lines={s.get('line_no')}"
        )

    answer = await agent.step()
    elapsed = time.monotonic() - t0
    passed, failures = _evaluate_case(
        case,
        scheme=scheme,
        expected_scheme=expected_scheme,
        skill_snippets=skill_snippets,
        metadata_snippets=metadata_snippets,
        all_snippets=snippets,
        answer=answer,
    )

    preview = answer if len(answer) <= 800 else answer[:800] + "\n...(truncated)"
    print(f"    elapsed: {elapsed:.1f}s  status: {'PASS' if passed else 'FAIL'}")
    if failures:
        for f in failures:
            print(f"    ✗ {f}")
    print(f"    answer preview:\n{preview}")

    return {
        "case_id": case.id,
        "passed": passed,
        "failures": failures,
        "elapsed_s": round(elapsed, 1),
        "snippet_count": len(preview_snippets),
        "scheme": scheme,
    }


async def run_e2e() -> int:
    from agent.tools.skill_read_code_recall import SCHEME_METADATA_LOCAL, SCHEME_READ_CODE

    api_key = _require_api_key()
    gitee_token = os.environ.get("GITEE_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    grep_scheme = resolve_e2e_grep_scheme()
    os.environ["GREP_RECALL_SCHEME"] = grep_scheme

    work_root = Path(tempfile.mkdtemp(prefix="code-agent-e2e-"))
    code_base = work_root / "code"
    skills_dir = work_root / "skills"
    code_base.mkdir(parents=True)
    skills_dir.mkdir(parents=True)

    os.environ.setdefault("ENABLE_LOCAL_SKILLS", "true")
    os.environ.setdefault("LOCAL_SKILLS_DIR", str(skills_dir))
    os.environ.setdefault("SKILLS_DOWNLOAD_DIR", str(skills_dir))
    os.environ.setdefault("SKILL_HUB_URL", SKILL_HUB)
    os.environ.setdefault("REGISTER_AGENT", "false")

    from agent.code_repo_init import CodeConfig, clone_code_repository
    from agent.code_agent import CodeAgent
    from agent.skill_runner_service import (
        CodeAgentSkillRunnerService,
        configure_skill_runtime_env,
    )

    scheme_label = "metadata+local grep" if grep_scheme == SCHEME_METADATA_LOCAL else "read-code skill"
    print("=" * 72)
    print(f"E2E: CodeAgent + Gitee clone + grep scheme={grep_scheme} ({scheme_label})")
    print("=" * 72)

    # --- 1. Gitee clone ---
    print("\n=== 1. Clone Gitee repository ===")
    print(f"    repo: {GITEE_REPO}")
    print(f"    branch: {GITEE_BRANCH}")
    cfg = CodeConfig.from_dict(
        {
            "name": "e2e-gitee",
            "descriptorType": "code",
            "codeRepoPath": GITEE_REPO,
            "codeRepoBranch": GITEE_BRANCH,
            "codeRepoToken": gitee_token,
        }
    )
    repo_path = clone_code_repository(cfg, base_path=str(code_base))
    if not repo_path or not Path(repo_path).is_dir():
        print("FAIL: Gitee clone failed")
        return 1
    repo_path = str(Path(repo_path).resolve())
    cloned = {"e2e-gitee": repo_path}
    print(f"    cloned to: {repo_path}")
    py_files = list(Path(repo_path).rglob("*.py"))
    print(f"    files (*.py): {len(py_files)}")

    original_cwd = os.getcwd()
    os.chdir(repo_path)
    os.environ["WORKSPACE_FOLDER"] = repo_path
    configure_skill_runtime_env(cloned)

    codebase_index = None
    skill_runner = None
    skill_svc = None

    if grep_scheme == SCHEME_METADATA_LOCAL:
        print("\n=== 2. Build local CodebaseIndex (E2E, no data-services) ===")
        codebase_index = build_codebase_index_for_e2e(Path(repo_path))
        if not codebase_index.file_index:
            print("FAIL: empty CodebaseIndex from cloned repo")
            os.chdir(original_cwd)
            return 1
        print(
            f"    files={len(codebase_index.file_index)}, "
            f"entities={len(codebase_index.entity_index)}, "
            f"functions={len(codebase_index.function_index)}"
        )
        print("\n=== 3. SkillRunner ===")
        print("    skipped (metadata_local scheme does not use read-code skill)")
    else:
        print("\n=== 2. Download read-code skill ===")
        print(f"    hub: {SKILL_HUB}")
        print(f"    E2E fallback: {E2E_READ_CODE_ZIP_FALLBACK}")
        timeout = float(os.environ.get("SKILL_DOWNLOAD_TIMEOUT", "15"))
        skill_paths = ensure_read_code_skill_for_e2e(
            skills_dir, skill_hub_url=SKILL_HUB, timeout=timeout
        )
        if not skill_paths:
            print("FAIL: read-code skill not downloaded")
            os.chdir(original_cwd)
            return 1
        print(f"    skills: {[str(p) for p in skill_paths]}")

        print("\n=== 3. Preload SkillRunner ===")
        print(f"    model: {MODEL}")
        skill_svc = CodeAgentSkillRunnerService(
            provider="openai_compatible",
            api_key=api_key,
            base_url=BASE_URL,
            model=MODEL,
            temperature=0.01,
        )
        skill_runner = skill_svc.preload()
        if skill_runner is None:
            print("FAIL: SkillRunner not initialised")
            os.chdir(original_cwd)
            return 1
        loaded = [
            getattr(s, "name", "")
            for s in (getattr(skill_runner.lister, "skills", []) or [])
        ]
        print(f"    loaded skills: {loaded}")
        if "read-code" not in loaded:
            print("FAIL: read-code skill not loaded")
            os.chdir(original_cwd)
            if skill_svc:
                skill_svc.shutdown()
            return 1

    cases = resolve_e2e_cases()

    print(f"\n=== 4. Test suite ({len(cases)} case(s)) ===")
    print(f"    grep_recall_scheme: {grep_scheme}")
    for c in cases:
        print(f"    - {c.id}: {c.description}")

    answer_model = os.environ.get("E2E_ANSWER_MODEL", "original").strip().lower()
    descriptor_types = _build_descriptor_types(GITEE_REPO, GITEE_BRANCH, gitee_token)

    def make_agent(query: str) -> CodeAgent:
        run_id = f"e2e-{uuid.uuid4().hex[:12]}"
        trace_id = secrets.token_hex(16)
        metadata = {
            "user_id": "e2e-user",
            "run_id": run_id,
            "trace_id": trace_id,
            "answer_model": answer_model if answer_model in ("original", "full") else "original",
        }
        return CodeAgent(
            provider="openai_compatible",
            api_key=api_key,
            base_url=BASE_URL,
            model=MODEL,
            temperature=0.01,
            stream=False,
            descriptor_types=descriptor_types,
            data_descriptors=["e2e-gitee"],
            dd_namespace="e2e",
            data_services_url=os.environ.get(
                "DataServicesURL",
                "http://127.0.0.1:1",  # unreachable — semantic branch fails soft
            ),
            query=query,
            metadata=metadata,
            max_steps=1,
            code_paths=cloned,
            codebase_index=codebase_index,
            codebase_index_loaded=codebase_index is not None,
            skill_runner=skill_runner,
        )

    # --- 5–6. Run each case ---
    print("\n=== 5. Run cases (grep_recall + step) ===")
    results: list[dict] = []
    try:
        for idx, case in enumerate(cases, 1):
            try:
                result = await _run_single_case(
                    case,
                    agent_factory=make_agent,
                    case_index=idx,
                    case_total=len(cases),
                    expected_scheme=grep_scheme,
                )
            except Exception as exc:
                result = {
                    "case_id": case.id,
                    "passed": False,
                    "failures": [f"exception: {exc}"],
                    "elapsed_s": 0,
                    "snippet_count": 0,
                    "scheme": "",
                }
                print(f"    FAIL: {case.id} raised {exc}")
            results.append(result)
    finally:
        os.chdir(original_cwd)
        if skill_svc is not None:
            skill_svc.shutdown()

    # --- 7. Summary ---
    passed_n = sum(1 for r in results if r["passed"])
    total_n = len(results)
    total_elapsed = sum(r.get("elapsed_s", 0) for r in results)

    print(f"\n{'=' * 72}")
    print(f"=== 6. Summary (scheme={grep_scheme}) ===")
    print(f"{'CASE':<28} {'STATUS':<8} {'SNIPPETS':<10} {'TIME':<8} FAILURES")
    print("-" * 72)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        fails = "; ".join(r["failures"]) if r["failures"] else "-"
        print(
            f"{r['case_id']:<28} {status:<8} {r.get('snippet_count', 0):<10} "
            f"{r.get('elapsed_s', 0):<8} {fails}"
        )
    print("-" * 72)
    print(f"Total: {passed_n}/{total_n} passed, {total_elapsed:.1f}s wall time")
    print(f"workdir (kept for inspection): {work_root}")

    if passed_n == total_n:
        print(f"\nPASS: all E2E cases completed (scheme={grep_scheme})")
        return 0
    print(f"\nFAIL: {total_n - passed_n} case(s) failed (scheme={grep_scheme})")
    return 1


def main() -> int:
    try:
        return asyncio.run(run_e2e())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
