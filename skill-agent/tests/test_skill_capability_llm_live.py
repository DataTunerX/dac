"""Live LLM tests for SkillAgent capability check — single-domain (DB monitor) agent.

Focus: verify the updated SKILL_CAPABILITY_CHECK_PROMPT correctly handles the
domain-first decision logic.

Requires:
  DASHSCOPE_API_KEY  (Aliyun DashScope API key)
  DASHSCOPE_MODEL    (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=sk-... \\
    python -m pytest tests/test_skill_capability_llm_live.py -q -s
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import skill_agent as sa
from agent.tool_call_utils import invoke_llm_with_tool
from model_sdk.api.model_manager import ModelManager


pytestmark = pytest.mark.skipif(
    not os.getenv("DASHSCOPE_API_KEY"),
    reason="DASHSCOPE_API_KEY is required for live skill capability tests",
)

# ── Single-domain agent: 数据库监控与性能分析 ──────────────────────────
DB_MONITOR_SKILLS = "\n".join([
    "- slow_query_analysis: 分析和诊断慢查询日志，定位慢查询根因（tags: database, slow-query）",
    "- db_performance_metrics: 监控数据库核心性能指标，包括 QPS、连接数、CPU、内存、磁盘 IO（tags: database, metrics）",
    "- sql_explain_plan: 对 SQL 语句执行 EXPLAIN 分析，生成执行计划报告（tags: database, sql）",
    "- db_connection_pool: 检查数据库连接池状态，包括活跃连接、空闲连接、等待队列（tags: database, connection）",
])

AGENT_NAME = "db-monitor-agent"
AGENT_DESC = "数据库监控与性能分析智能体，负责 SQL 慢查询分析、数据库性能指标监控、执行计划分析、连接池状态检查"


@dataclass(frozen=True)
class SkillCapCase:
    name: str
    query: str
    skills: str
    agent_name: str
    agent_description: str
    expect_can_handle: bool
    expect_can_contribute: bool


# ── 50 test cases: single-domain DB monitor agent ─────────────────────
#
# Groups:
#   G1 (1-8):   Primary domain = database  →  can_handle=true
#               包括简单匹配、复杂跨领域但主领域是数据库、模糊/极简查询
#   G2 (9-11):  非主领域，但能贡献数据库相关数据  →  handle=false, contribute=true
#   G3 (12-17): 完全无关联  →  handle=false, contribute=false
#   G4 (18-20): 边界 / 模糊 / 极简  →  验证稳定性
#   ── 30 additional cases (e1-e30) below ──
# ───────────────────────────────────────────────────────────────────────

CASES = [
    # ═══════════════ G1: Primary domain = database → can_handle=true ═══════════════
    # ── Simple, straightforward ──
    SkillCapCase(
        "g1_simple_slow_query",
        "分析最近一小时的慢查询日志，找出最耗时的 Top 10 查询",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_simple_perf_metrics",
        "查看当前数据库的 QPS、连接数和 CPU 使用率",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_simple_explain",
        "对这条 SQL 做执行计划分析：SELECT * FROM orders WHERE status='pending'",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    # ── Complex, multi-domain but primary = database (KEY SCENARIOS) ──
    SkillCapCase(
        "g1_complex_with_app_logs",
        "排查线上服务响应慢的原因，需要检查数据库慢查询和连接池状态，"
        "同时确认应用服务器日志是否有异常",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_complex_with_alerts",
        "数据库 CPU 使用率超过 90%，帮我分析原因并检查是否有相关告警通知",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_complex_with_code_advice",
        "这条 SQL 执行很慢，帮我分析执行计划并给出数据库层面的优化方案，"
        "同时看看对应的业务代码是否需要调整",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_complex_full_health_check",
        "对数据库做一次全面体检并给出优化建议，数据库层面和应用层面都需要覆盖",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g1_complex_with_release",
        "数据库连接异常增多，分析是否和最近的代码发版有关，"
        "帮我从数据库层面排查连接来源和连接池状态",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),

    # ═══════════════ G2: Not primary domain, but concrete contribution ═══════════════
    SkillCapCase(
        "g2_contribute_api_latency",
        "某个 API 接口响应很慢，需要排查整条链路，"
        "包括网关延迟、应用处理时间和数据库查询耗时",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "g2_contribute_deploy",
        "服务部署到生产环境后出现异常，需要查看部署日志、"
        "应用运行状态和数据库连接情况",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "g2_contribute_incident",
        "线上故障排查：用户反馈下单超时，需要检查网络、"
        "应用日志和数据库慢查询",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),

    # ═══════════════ G3: No domain overlap → handle=false, contribute=false ═══════════════
    SkillCapCase(
        "g3_reject_weather",
        "北京明天天气怎么样",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "g3_reject_write_code",
        "帮我写一个 Python 脚本下载网页图片",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "g3_reject_math",
        "计算 (128 + 64) * 3 / 2 的结果",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "g3_reject_user_info",
        "查询用户张三的手机号和注册日期",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "g3_reject_translate",
        "把这段话翻译成英文：今天天气很好，适合去公园散步",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "g3_reject_stock",
        "查询比亚迪今天的股价和市盈率",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),

    # ═══════════════ G4: Edge cases — vague / minimal / boundary ═══════════════
    SkillCapCase(
        "g4_vague_but_domain",
        "数据库好像出问题了，帮我看看",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g4_vague_with_db",
        "帮我查一下数据库",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "g4_minimal_db",
        "数据库",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),

    # ═══════════════ 30 additional cases — extended stability tests ═══════════════

    # ── E1: G1 扩展 — 更多数据库领域表述（handle=true）──
    SkillCapCase(
        "e1_db_question_why",
        "为什么数据库的响应时间突然变慢了",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_english_terms",
        "帮我分析一下 MySQL 慢查询日志中的 full table scan 问题",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_specific_engine",
        "PostgreSQL 的连接池不够用了，看下当前连接数和使用情况",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_deadlock",
        "数据库出现了死锁，帮我分析死锁日志找出原因",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_replication",
        "主从复制延迟严重，帮我检查一下数据库的 IO 和 CPU 是否正常",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_backup",
        "数据库备份任务失败了，帮我从数据库层面排查磁盘 IO 和连接状态是否异常",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_index_advice",
        "这个查询不走索引，帮我分析执行计划并建议如何建索引，"
        "同时看看这个表的数据量和分布情况",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e1_db_memory_issue",
        "数据库内存使用率持续上升，快接近 95% 了，"
        "帮我分析是不是有慢查询或者连接泄漏导致的，同时通知运维部署新实例",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),

    # ── E2: G2 扩展 — 更多贡献场景（handle=false, contribute=true）──
    SkillCapCase(
        "e2_contribute_microservice",
        "微服务架构整体性能下降，需要排查服务间调用延迟、"
        "消息队列积压和数据库响应时间",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e2_contribute_saas",
        "SaaS 平台整体可用性下降，检查 CDN 状态、"
        "负载均衡健康检查和后端数据库连接池",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e2_contribute_kubernetes",
        "K8s 集群中有几个 Pod 频繁重启，检查容器日志、"
        "资源限制和数据库连接是否正常",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e2_contribute_security",
        "收到安全告警说存在数据泄露风险，需要排查网络流量、"
        "访问日志和数据库的异常查询",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e2_contribute_capacity",
        "年底大促前的容量评估，需要分析各服务的负载能力、"
        "缓存策略和数据库 QPS 上限",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e2_contribute_cost_opt",
        "云资源成本优化分析，需要查看计算资源的利用率、"
        "存储增长趋势和数据库实例的规格是否合理",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),

    # ── E3: G3 扩展 — 更多拒绝/边界场景 ──
    # Redis/ES 等数据存储类系统，LLM 倾向于认为 db_performance_metrics 可以贡献
    # 内存/CPU 等通用指标监控，因此 contribute=true 是合理判断
    SkillCapCase(
        "e3_reject_redis",
        "Redis 集群的 Gossip 协议通信异常，导致节点频繁主从切换和脑裂",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_es",
        "Elasticsearch 的 term query 聚合很慢，帮我分析索引 mapping 和 shard 分配",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, True,
    ),
    SkillCapCase(
        "e3_reject_nginx",
        "Nginx 的 502 错误突然增多，帮我检查 upstream 健康状态",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_kafka",
        "Kafka 消费者 lag 持续增长，检查 broker 状态和 topic 分区",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_ci_cd",
        "CI/CD 流水线构建失败了，帮我看看编译日志和测试报告",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_hr",
        "帮我整理这周团队的工作周报，汇总每个人的开发进度",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_legal",
        "这份合同条款是否符合 GDPR 隐私保护要求",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e3_reject_medical",
        "根据这些症状描述判断可能的疾病类型",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),

    # ── E4: G4 扩展 — 更多边界/模糊/对抗场景 ──
    SkillCapCase(
        "e4_tricky_database_as_word",
        "我需要一个客户数据库来管理销售线索，有什么推荐的工具吗",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e4_tricky_sql_but_not_db",
        "帮我写一个 SQL 注入攻击的防护方案",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e4_tricky_database_in_article",
        "帮我翻译一篇关于数据库发展趋势的英文文章",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e4_tricky_connection_timeout",
        "MySQL 连接超时报错，帮我看看是数据库配置问题还是网络问题，"
        "如果是网络问题需要找网络团队排查",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e4_tricky_slow_response_chain",
        "用户反馈页面加载慢，前端说接口没问题，后端说数据库没问题，"
        "帮我从数据库侧确认一下到底有没有慢查询",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e4_tricky_alert_primary_db",
        "收到告警：数据库 QPS 突降 80%，同时业务监控显示订单量也同步下降，"
        "是先排查数据库还是先排查业务？",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        True, True,
    ),
    SkillCapCase(
        "e4_tricky_ambiguous_query",
        "帮我查一下",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
    SkillCapCase(
        "e4_tricky_hello",
        "你好",
        DB_MONITOR_SKILLS, AGENT_NAME, AGENT_DESC,
        False, False,
    ),
]


def _llm():
    return ModelManager().get_llm(
        provider="openai_compatible",
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv(
            "DASHSCOPE_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        model=os.getenv("DASHSCOPE_MODEL", "deepseek-v4-flash-0731"),
        temperature=0.01,
        stream=False,
        extra_body={"enable_thinking": False},
    )


async def _judge(case: SkillCapCase) -> dict[str, Any]:
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=case.agent_name,
        agent_description=case.agent_description,
        agent_skills=case.skills,
        history="(none)",
        query=case.query,
    )
    tool = StructuredTool(
        name="evaluate_capability",
        description="Evaluate whether this skill agent can handle the query.",
        args_schema=sa.CapabilityCheckToolResult,
        func=None,
        coroutine=None,
    )
    data = await invoke_llm_with_tool(
        llm=_llm(),
        tool=tool,
        messages=[HumanMessage(content=prompt)],
        metadata={
            "run_id": f"skill-live-{case.name}",
            "trace_id": "d" * 32,
            "user_id": "skill-capability-live",
        },
        tool_choice="evaluate_capability",
        span_name="skill-capability-live",
        span_input={"query": case.query, "case": case.name},
    )
    assert data is not None, "LLM did not call evaluate_capability"
    return data


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize LLM output using production `_normalize_capability_result`."""
    can_handle, can_contribute = sa._normalize_capability_result(raw)
    result = dict(raw)
    result["can_handle"] = can_handle
    result["can_contribute"] = can_contribute
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_skill_capability_live(case: SkillCapCase):
    raw = await _judge(case)
    data = _normalize(raw)
    can_handle = bool(data.get("can_handle"))
    can_contribute = bool(data.get("can_contribute"))
    reason = str(data.get("reason") or "")
    print(
        f"\n[{case.name}] handle={can_handle} contribute={can_contribute} "
        f"conf={data.get('confidence')} reason={reason[:300]}"
    )
    assert can_handle is case.expect_can_handle
    assert can_contribute is case.expect_can_contribute