"""Advanced test suite for skill_search — 50 extra-complex cases with real LLM.

Categories (10 cases each):
- vague: extremely ambiguous intent, users don't know what they want
- noisy: heavy noise with multiple layers of irrelevant details
- near_miss: very close confusion between 2-3 similar skills
- implicit: deep implicit reasoning, the skill is never mentioned
- no_match: borderline cases that look matchable but are outside scope

Run with:
    cd /Users/james/daocloud/code/dac/skill_sdk
    python tests/test_skill_search_advanced.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SDK_ROOT = _HERE.parent
sys.path.insert(0, str(_SDK_ROOT))

os.environ.setdefault("LANGFUSE_SECRET_KEY", "sk-lf-6d416a29-ac3e-45f1-a636-8bceae717f1f")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "pk-lf-3c77eb49-6494-4791-9b6f-799c2e408ad6")
os.environ.setdefault("LANGFUSE_BASE_URL", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_HOST", "http://192.168.3.7:3000")
os.environ.setdefault("LANGFUSE_AUTH_CHECK", "disable")

from skill_sdk.skill.runner import SkillRunner
from model_sdk import ModelManager

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "sk-xxx")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_MODEL = "deepseek-v4-pro"
SKILLS_DIR = _SDK_ROOT / "skills"


def build_llm():
    manager = ModelManager()
    return manager.get_llm(
        provider="openai_compatible",
        api_key=DASHSCOPE_API_KEY,
        base_url=DASHSCOPE_BASE_URL,
        model=LLM_MODEL,
        temperature=0.01,
        extra_body={"enable_thinking": False},
    )


# ---------------------------------------------------------------------------
# Test case definition
# ---------------------------------------------------------------------------

@dataclass
class TestCase:
    id: int
    category: str
    query: str
    expected_skill: str | None
    explanation: str = ""


# ---------------------------------------------------------------------------
# 50 Advanced Test Cases
# ---------------------------------------------------------------------------

TEST_CASES = [
    # =====================================================================
    # Category: vague (模糊意图) — 10 cases
    # Users describe outcomes without naming the tool or skill
    # =====================================================================
    TestCase(
        id=1, category="vague",
        query="帮我处理一下这个数据，我需要统计一些信息，比如最大值最小值还有平均值",
        expected_skill="code_execution",
        explanation="数据统计需求（最大值/最小值/平均值），需要 Python 沙箱计算",
    ),
    TestCase(
        id=2, category="vague",
        query="我有个文本文件，想看看里面到底有多少内容，大概多少行多少字",
        expected_skill="wordcount",
        explanation="统计文件的行数和字数，wordcount 的核心功能",
    ),
    TestCase(
        id=3, category="vague",
        query="帮我查点东西，关于某个技术话题的最新资料，越新越好",
        expected_skill="tavily-search",
        explanation="查找最新资料，需要联网搜索能力",
    ),
    TestCase(
        id=4, category="vague",
        query="帮我看看这个配置里有没有某个字段，我想知道它的值是多少",
        expected_skill="config-reader",
        explanation="读取配置文件中特定字段的值",
    ),
    TestCase(
        id=5, category="vague",
        query="帮我验证一下这个格式对不对，如果不对的话告诉我哪里有问题",
        expected_skill="jsonfmt",
        explanation="验证格式合法性，JSON 是最常见的格式验证需求",
    ),
    TestCase(
        id=6, category="vague",
        query="我需要从网上抓点东西下来，一个网页的内容",
        expected_skill="web_fetch",
        explanation="抓取网页内容，web_fetch 的核心功能",
    ),
    TestCase(
        id=7, category="vague",
        query="帮我生成一些随机的东西，要安全的",
        expected_skill="pwdgen",
        explanation="生成安全的随机字符串，pwdgen 的核心功能",
    ),
    TestCase(
        id=9, category="vague",
        query="这个 PDF 文件我看不懂，你帮我提取一下里面的文本内容",
        expected_skill="extract_pdf",
        explanation="从 PDF 文件中提取文本内容，extract_pdf 的核心功能",
    ),
    TestCase(
        id=10, category="vague",
        query="帮我查一下最近的新闻，关于人工智能的",
        expected_skill="tavily-search",
        explanation="搜索最新新闻，需要联网检索能力",
    ),

    # =====================================================================
    # Category: noisy (干扰噪声) — 10 cases
    # Core intent buried under multiple layers of irrelevant details
    # =====================================================================
    TestCase(
        id=11, category="noisy",
        query="我想统计一下这个文件有多少行，然后顺便看看变量命名有没有问题，再帮我格式化一下代码，对了之前有个 bug 跟这个文件相关",
        expected_skill="wordcount",
        explanation="核心需求是统计行数，其他都是附带干扰。变量命名、代码格式化、bug 都是噪声",
    ),
    TestCase(
        id=12, category="noisy",
        query="帮我生成一个随机密码作为数据库密码，然后用这个密码去连接 PostgreSQL 创建用户，对了数据库现在在 AWS RDS 上，需要先配置安全组吗",
        expected_skill="pwdgen",
        explanation="核心是生成密码，后续的数据库操作、AWS 配置都是噪声",
    ),
    TestCase(
        id=13, category="noisy",
        query="帮我搜索一下 httpx 库的最新用法和最佳实践，我不知道官方文档地址，需要先在搜索引擎里找一找，然后看怎么用异步请求，最后写个脚本测试性能",
        expected_skill="tavily-search",
        explanation="核心是搜索 httpx 最新用法，需要搜索引擎检索，写脚本和性能测试都是后续任务",
    ),
    TestCase(
        id=14, category="noisy",
        query="帮我看看 #336699 是什么颜色，我想用它做我的博客主题色，然后看看在暗色背景下对比度够不够，不够的话帮我推荐一个类似的颜色",
        expected_skill="colorconv",
        explanation="核心是颜色 hex→RGB 转换，主题色、对比度分析都是干扰",
    ),
    TestCase(
        id=15, category="noisy",
        query="帮我把这个 JSON 格式化一下，然后看看有没有语法错误，如果有错误帮我定位到具体行，然后顺便把里面的日期字段转成时间戳，再存到数据库里",
        expected_skill="jsonfmt",
        explanation="核心是 JSON 格式化+验证，时间戳转换和数据库存储是后续任务",
    ),
    TestCase(
        id=16, category="noisy",
        query="帮我生成一个 UUID，然后把它存到数据库里，再去查一下这个用户的其他信息，最后发个邮件通知用户",
        expected_skill="uuidgen",
        explanation="核心是生成 UUID，数据库操作、查用户、发邮件都是噪声",
    ),
    TestCase(
        id=17, category="noisy",
        query="帮我解析这个 URL，看看参数对不对，然后去抓取这个页面内容，如果有表格数据就提取出来，最后存成 CSV 文件",
        expected_skill="urlparse",
        explanation="核心是 URL 解析，页面抓取、数据提取、CSV 存储都是后续步骤",
    ),
    TestCase(
        id=18, category="noisy",
        query="帮我算一下这个文件的 SHA256，然后看看有没有被篡改，如果被篡改了就报警，没被篡改就上传到 S3 存储",
        expected_skill="hashgen",
        explanation="核心是计算 SHA256，篡改检测、报警、S3 上传都是噪声",
    ),
    TestCase(
        id=19, category="noisy",
        query="帮我生成一个 GitHub issue 模板，然后创建到仓库里，记得加上 label 和 milestone，对了还要通知相关人员 review",
        expected_skill="github",
        explanation="核心是 GitHub issue 创建，模板、label、通知都是细节",
    ),
    TestCase(
        id=20, category="noisy",
        query="帮我查一下 base64 编码的原理，然后把我这个字符串编码一下，最后看看能不能用不同的编码表，比如 URL-safe 的",
        expected_skill="base64tool",
        explanation="核心是 base64 编解码，原理查询、不同编码表探索都是围绕 base64 的",
    ),

    # =====================================================================
    # Category: near_miss (近义混淆) — 10 cases
    # Deliberately designed to confuse between 2-3 very similar skills
    # =====================================================================
    TestCase(
        id=21, category="near_miss",
        query="帮我检查一下这个目录下所有文件的内容有没有被修改过，给每个文件算一个 hash 然后汇总",
        expected_skill="bundle-hash",
        explanation="目录级 hash 校验是 bundle-hash（不是 hashgen 单个文件/字符串）",
    ),
    TestCase(
        id=22, category="near_miss",
        query="帮我把这段文本用 base64 编码之后再解码回来，验证一下编码和解码是否正确",
        expected_skill="base64tool",
        explanation="base64 编解码，不是 hashgen 或 urlparse",
    ),
    TestCase(
        id=23, category="near_miss",
        query="帮我查一下这个域名 https://example.com/api/v1/users 的路径结构，看看它有几个层级",
        expected_skill="urlparse",
        explanation="URL 解析（不是 web_fetch 抓取内容）",
    ),
    TestCase(
        id=24, category="near_miss",
        query="帮我从这个网页 https://example.com 上把内容抓下来，我要看里面的文字",
        expected_skill="web_fetch",
        explanation="网页抓取（不是 urlparse 解析 URL 结构）",
    ),
    TestCase(
        id=25, category="near_miss",
        query="帮我生成一个安全的随机 token，长度 32 位，用来做 API 认证",
        expected_skill="pwdgen",
        explanation="随机 token 生成本质是密码生成（不是 uuidgen 生成 UUID）",
    ),
    TestCase(
        id=26, category="near_miss",
        query="帮我搜索一下 Go 语言中 context 包的最新用法和最佳实践",
        expected_skill="tavily-search",
        explanation="搜索最新用法（不是 read-code 在本地代码库搜索）",
    ),
    TestCase(
        id=27, category="near_miss",
        query="帮我在代码库里找一下所有使用 context.WithTimeout 的地方，看看是怎么用的",
        expected_skill="read-code",
        explanation="在本地代码库中搜索代码（不是 tavily-search 联网搜索）",
    ),
    TestCase(
        id=28, category="near_miss",
        query="帮我把 2024-03-19 16:00:00 这个时间转成秒数，就是 Unix 时间戳",
        expected_skill="timestamp",
        explanation="日期时间转 Unix 时间戳（timestamp 的核心功能）",
    ),
    TestCase(
        id=29, category="near_miss",
        query="帮我统计一下这个 Markdown 文档有多少个标题、多少个代码块、总共有多少字",
        expected_skill="wordcount",
        explanation="统计文档内容（不是 read-code 读取代码）",
    ),
    # =====================================================================
    # Category: implicit (隐式意图) — 10 cases
    # The skill is never mentioned; LLM must infer from context clues
    # =====================================================================
    TestCase(
        id=31, category="implicit",
        query="帮我检查一下这个 JSON 配置文件有没有语法问题，比如少了逗号或者括号不匹配",
        expected_skill="jsonfmt",
        explanation="JSON 语法验证，虽然没提到 'jsonfmt' 但语义明确",
    ),
    TestCase(
        id=32, category="implicit",
        query="我有一万多行日志文件，帮我看看前 100 行和后 100 行，我想对比一下它们的格式",
        expected_skill="read-code",
        explanation="读取大文件的部分内容，需要 readline_in_range 能力",
    ),
    TestCase(
        id=33, category="implicit",
        query="帮我用 Python 算一下这些数字的平均值、中位数和标准差：[23, 45, 67, 12, 89, 34, 56, 78, 90, 11]",
        expected_skill="code_execution",
        explanation="数值统计计算，需要 Python 沙箱执行",
    ),
    TestCase(
        id=34, category="implicit",
        query="帮我看看 SkillRunner 这个类在哪个文件里定义的，它的 __init__ 方法是怎么写的",
        expected_skill="read-code",
        explanation="在代码库中搜索类定义和读取代码",
    ),
    TestCase(
        id=35, category="implicit",
        query="帮我生成一个 session token，要求 64 位，包含大小写字母、数字和特殊符号",
        expected_skill="pwdgen",
        explanation="token 生成本质是密码生成，pwdgen 支持长度和字符类型控制",
    ),
    TestCase(
        id=36, category="implicit",
        query="帮我找一下所有包含 TODO 注释的 Python 文件，看看有哪些待办事项",
        expected_skill="read-code",
        explanation="在代码库中搜索 TODO 注释，需要 grep/glob 能力",
    ),
    TestCase(
        id=37, category="implicit",
        query="帮我看看这个十六进制颜色 #2c3e50 在 RGB 里是多少，我要在 CSS 里用",
        expected_skill="colorconv",
        explanation="十六进制颜色转 RGB，colorconv 的核心功能",
    ),
    TestCase(
        id=38, category="implicit",
        query="帮我把整数 1700000000 转成人类可读的时间，我想知道是几月几号",
        expected_skill="timestamp",
        explanation="Unix 时间戳转换，timestamp 的核心功能",
    ),
    TestCase(
        id=39, category="implicit",
        query="帮我看看这个网页的 meta description 和 title 是什么，我需要做 SEO 优化",
        expected_skill="web_fetch",
        explanation="抓取网页元数据，web_fetch 的核心功能",
    ),
    TestCase(
        id=40, category="implicit",
        query="帮我查一下目前 GitHub 上 Kubernetes 最新 release 的版本号是多少",
        expected_skill="github",
        explanation="查询 GitHub release 信息，gh CLI 可以做到",
    ),

    # =====================================================================
    # Category: no_match (不匹配) — 10 cases
    # Borderline cases that look like they could match but are outside scope
    # =====================================================================
    TestCase(
        id=41, category="no_match",
        query="帮我用 Python 画一个折线图，展示今年每个月的销售额变化趋势，横轴是月份纵轴是销售额",
        expected_skill=None,
        explanation="code_execution 明确声明不负责画图（折线图、柱状图等）",
    ),
    TestCase(
        id=42, category="no_match",
        query="帮我写一个 Dockerfile，用于构建一个 Go 微服务镜像，需要多阶段构建",
        expected_skill=None,
        explanation="没有 Docker/镜像构建相关的 skill",
    ),
    TestCase(
        id=43, category="no_match",
        query="帮我配置 Nginx 反向代理，把 /api 请求转发到 127.0.0.1:8080 后端服务",
        expected_skill=None,
        explanation="没有 Nginx/Web 服务器配置相关的 skill",
    ),
    TestCase(
        id=44, category="no_match",
        query="帮我用 TensorFlow 训练一个简单的图像分类模型，用 MNIST 数据集",
        expected_skill=None,
        explanation="没有机器学习/深度学习相关的 skill",
    ),
    TestCase(
        id=45, category="no_match",
        query="帮我写一个 Ansible playbook，自动部署一套 LAMP 环境到三台服务器",
        expected_skill=None,
        explanation="没有 Ansible/自动化运维相关的 skill",
    ),
    TestCase(
        id=46, category="no_match",
        query="帮我用 Redis 实现一个分布式锁，要求支持超时自动释放和可重入",
        expected_skill=None,
        explanation="没有 Redis 相关的 skill",
    ),
    TestCase(
        id=47, category="no_match",
        query="帮我写一个 React 组件，实现一个带搜索功能的下拉选择框，支持多选和远程搜索",
        expected_skill=None,
        explanation="没有前端开发/React 相关的 skill",
    ),
    TestCase(
        id=48, category="no_match",
        query="帮我设计一个 RESTful API 的接口规范，包括用户认证、分页、错误码定义",
        expected_skill=None,
        explanation="没有 API 设计/规范相关的 skill",
    ),
    TestCase(
        id=49, category="no_match",
        query="帮我用 Terraform 写一个 AWS 基础设施的配置文件，包括 VPC、EC2、RDS",
        expected_skill=None,
        explanation="没有 Terraform/基础设施即代码相关的 skill",
    ),
    TestCase(
        id=50, category="no_match",
        query="帮我写一个 Jenkins Pipeline 配置文件（Jenkinsfile），实现自动测试和部署",
        expected_skill=None,
        explanation="没有 CI/CD Pipeline 配置相关的 skill",
    ),
]


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    case_id: int
    category: str
    query: str
    expected: str | None
    actual: str | None
    passed: bool
    candidates: list[str] = field(default_factory=list)
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    score: int = 0
    elapsed_ms: float = 0.0
    explanation: str = ""


def print_section(title: str) -> None:
    line = "=" * 80
    print(f"\n{line}\n  {title}\n{line}")


async def run_single_test(
    runner: SkillRunner,
    tc: TestCase,
    run_id: str,
) -> TestResult:
    trace_id = f"advanced_test_{tc.id:03d}_{int(time.time())}"

    t0 = time.perf_counter()
    result = await runner.skill_search(
        query=tc.query,
        user_id="test_user",
        run_id=run_id,
        trace_id=trace_id,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000

    actual = result.get("selected_skill") if result.get("found") else None
    candidates = [c["name"] for c in result.get("candidates", [])]
    candidate_scores = [
        {"name": c["name"], "score": c.get("score", 0), "reason": c.get("reason", "")}
        for c in result.get("candidates", [])
    ]
    reason = result.get("reason", "")
    score = result.get("score", 0)

    if tc.expected_skill is None:
        passed = actual is None
    else:
        passed = actual == tc.expected_skill

    return TestResult(
        case_id=tc.id,
        category=tc.category,
        query=tc.query,
        expected=tc.expected_skill,
        actual=actual,
        passed=passed,
        candidates=candidates,
        candidate_scores=candidate_scores,
        reason=reason,
        score=score,
        elapsed_ms=elapsed_ms,
        explanation=tc.explanation,
    )


async def load_skills(runner: SkillRunner, *, exclude: set[str] | None = None) -> int:
    skills = []
    exclude = exclude or set()
    for p in sorted(SKILLS_DIR.glob("*.zip"), key=lambda x: x.name.lower()):
        try:
            skill = runner._loader.load(p)
            if skill.name not in exclude:
                skills.append(skill)
        except Exception as e:
            print(f"  Skip {p.name}: {e}")
    runner.set_skills(skills)
    return len(skills)


# ---------------------------------------------------------------------------
# Main test orchestrator
# ---------------------------------------------------------------------------

async def main():
    print_section("skill_search 进阶测试 — 50 个超复杂用例")
    print(f"  LLM: {LLM_MODEL}")
    print(f"  Skills: {SKILLS_DIR}")
    print()

    llm = build_llm()
    runner = SkillRunner(
        llm=llm,
        max_steps=20,
        cmd_timeout_sec=60,
        use_skill_search=True,
        skill_search_batch_size=100,
        skill_search_max_concurrent=5,
        skill_search_max_steps=5,
    )

    skill_count = await load_skills(runner, exclude={"code_execution"})
    print(f"  Loaded {skill_count} skills\n")

    # Skip test cases that expect code_execution when it's excluded
    active_cases = [tc for tc in TEST_CASES if tc.expected_skill != "code_execution"]
    skipped = len(TEST_CASES) - len(active_cases)
    if skipped:
        print(f"  Skipped {skipped} test case(s) expecting code_execution\n")

    # Build a name-to-description map for result analysis
    skill_map = {s.name: s.description for s in runner.lister.skills}

    results: list[TestResult] = []
    total_tests = 0
    run_id_base = f"advanced_{int(time.time())}"

    for tc in active_cases:
        total_tests += 1
        run_id = f"{run_id_base}_{tc.id:03d}"
        label = f"  [{total_tests:2d}] id={tc.id:02d} [{tc.category:10s}]"
        print(f"{label} {tc.query[:60]}...", end=" ", flush=True)

        result = await run_single_test(runner, tc, run_id)
        results.append(result)

        status = "✓ PASS" if result.passed else "✗ FAIL"
        extra = ""
        if not result.passed:
            if result.expected and result.actual:
                extra = f"  expected={result.expected}, got={result.actual}"
            elif result.expected:
                extra = f"  expected={result.expected}, got nothing"
            else:
                extra = f"  expected no match, got={result.actual}"
        score_str = f" score={result.score}" if result.actual else ""
        print(f"{status} ({result.elapsed_ms:.0f}ms){score_str}{extra}")
        if result.candidate_scores:
            for cs in result.candidate_scores:
                print(f"         candidate: {cs['name']} score={cs['score']} reason={cs['reason'][:60]}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print_section("测试结果汇总")

    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)

    # By category
    categories: dict[str, dict[str, int]] = {}
    for r in results:
        cat = categories.setdefault(r.category, {"passed": 0, "failed": 0, "total": 0})
        cat["total"] += 1
        if r.passed:
            cat["passed"] += 1
        else:
            cat["failed"] += 1

    print(f"\n  总用例数: {total_tests}")
    print(f"  通过: {passed}  ({100*passed/total_tests:.1f}%)")
    print(f"  失败: {failed}  ({100*failed/total_tests:.1f}%)")
    print(f"  平均耗时: {sum(r.elapsed_ms for r in results)/len(results):.0f}ms")

    print(f"\n  按类别统计:")
    for cat_name in ["vague", "noisy", "near_miss", "implicit", "no_match"]:
        if cat_name in categories:
            c = categories[cat_name]
            pct = 100 * c["passed"] / c["total"] if c["total"] else 0
            print(f"    {cat_name:12s}: {c['passed']}/{c['total']} passed ({pct:.0f}%)")

    # Detail table
    print(f"\n  {'ID':>3s}  {'类别':10s}  {'预期':20s}  {'实际':20s}  {'分数':>4s}  {'结果':6s}  {'耗时':>6s}  {'说明'}")
    print(f"  {'-'*3}  {'-'*10}  {'-'*20}  {'-'*20}  {'-'*4}  {'-'*6}  {'-'*6}  {'-'*55}")
    for r in results:
        exp = r.expected or "(无匹配)"
        act = r.actual or "(无匹配)"
        status = "PASS" if r.passed else "FAIL"
        detail = ""
        if not r.passed:
            if r.actual and r.expected:
                detail = f"错选 {r.actual}"
            elif r.actual and not r.expected:
                detail = f"不该匹配到 {r.actual}"
            elif not r.actual and r.expected:
                detail = f"未找到 {r.expected}"
        else:
            detail = r.explanation[:55]
        score_str = str(r.score) if r.actual else "-"
        print(f"  {r.case_id:3d}  {r.category:10s}  {exp:20s}  {act:20s}  {score_str:>4s}  {status:6s}  {r.elapsed_ms:5.0f}ms  {detail}")

    # Failed cases detail
    if failed > 0:
        print(f"\n  ⚠ 失败用例详情:")
        for r in results:
            if not r.passed:
                print(f"\n  --- 用例 {r.case_id} [{r.category}] ---")
                print(f"  Query: {r.query}")
                print(f"  Expected: {r.expected}")
                print(f"  Actual: {r.actual} (score={r.score})")
                print(f"  Selector reason: {r.reason}")
                print(f"  Explanation: {r.explanation}")
                if r.candidate_scores:
                    print(f"  Candidates (with scores):")
                    for cs in r.candidate_scores:
                        desc = skill_map.get(cs["name"], "N/A")
                        print(f"    - {cs['name']} (score={cs['score']})")
                        print(f"      batch_reason: {cs['reason'][:100]}")
                        print(f"      description: {desc[:80]}...")

    print_section("测试完成")
    print(f"  最终结果: {passed}/{total_tests} 通过 ({100*passed/total_tests:.1f}%)")

    return passed == total_tests


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)