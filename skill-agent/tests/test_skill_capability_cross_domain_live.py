"""Live LLM tests for SkillAgent capability check — cross-domain multi-agent scenarios.

Focus: verify the updated SKILL_CAPABILITY_CHECK_PROMPT correctly handles complex
cross-domain queries where multiple agents could be involved. Tests whether the
domain-first logic correctly identifies the primary domain owner even when the
query spans multiple domains.

Requires:
  DASHSCOPE_API_KEY  (Aliyun DashScope API key)
  DASHSCOPE_MODEL    (optional, default deepseek-v4-flash-0731)
  DASHSCOPE_BASE_URL (optional)

Run:
  DASHSCOPE_API_KEY=sk-... \\
    python -m pytest tests/test_skill_capability_cross_domain_live.py -q -s
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


# ── Agent 定义 ──────────────────────────────────────────────────────────

# Agent A: 数据库监控（主领域）
DB_MONITOR_SKILLS = "\n".join([
    "- slow_query_analysis: 分析和诊断慢查询日志，定位慢查询根因（tags: database, slow-query）",
    "- db_performance_metrics: 监控数据库核心性能指标（QPS、连接数、CPU、内存、磁盘 IO）（tags: database, metrics）",
    "- sql_explain_plan: 对 SQL 语句执行 EXPLAIN 分析，生成执行计划报告（tags: database, sql）",
    "- db_connection_pool: 检查数据库连接池状态（活跃连接、空闲连接、等待队列）（tags: database, connection）",
])
DB_MONITOR_NAME = "db-monitor-agent"
DB_MONITOR_DESC = "数据库监控与性能分析智能体，负责 SQL 慢查询分析、数据库性能指标监控、执行计划分析、连接池状态检查"

# Agent B: 部署与运维（主领域）
DEPLOY_OPS_SKILLS = "\n".join([
    "- deployment_status: 查看服务部署状态、版本信息和回滚记录（tags: deploy, release）",
    "- app_log_analysis: 分析应用服务器日志，定位错误和异常堆栈（tags: logs, app）",
    "- service_health_check: 检查服务健康状态、探活、资源使用率（tags: ops, health）",
    "- config_diff: 对比不同环境/版本的配置差异（tags: config, deploy）",
])
DEPLOY_OPS_NAME = "deploy-ops-agent"
DEPLOY_OPS_DESC = "部署与运维智能体，负责服务部署、版本管理、应用日志分析、服务健康检查、配置管理"

# Agent C: 网络与基础设施（主领域）
NETWORK_INFRA_SKILLS = "\n".join([
    "- network_latency: 测量网络延迟、丢包率和带宽使用情况（tags: network, latency）",
    "- dns_resolution: 检查 DNS 解析状态和解析链路（tags: network, dns）",
    "- load_balancer_status: 检查负载均衡器健康状态和后端节点可用性（tags: network, lb）",
    "- firewall_rules: 查询防火墙规则和安全组配置（tags: network, security）",
])
NETWORK_INFRA_NAME = "network-infra-agent"
NETWORK_INFRA_DESC = "网络与基础设施智能体，负责网络延迟监控、DNS 解析、负载均衡状态、防火墙规则管理"

# Agent D: 业务监控与告警（主领域）
BIZ_MONITOR_SKILLS = "\n".join([
    "- business_metrics: 查询业务核心指标，包括订单量、GMV、转化率、用户活跃度（tags: business, metrics）",
    "- alert_dashboard: 查看当前告警列表、告警历史和告警收敛状态（tags: alert, monitoring）",
    "- sla_report: 生成 SLA 达标率报告和可用性统计（tags: business, sla）",
    "- user_behavior: 分析用户行为路径和漏斗转化（tags: business, user）",
])
BIZ_MONITOR_NAME = "biz-monitor-agent"
BIZ_MONITOR_DESC = "业务监控与告警智能体，负责业务指标查询、告警管理、SLA 报告、用户行为分析"

# Agent E: 安全与风控（主领域）
SECURITY_SKILLS = "\n".join([
    "- vulnerability_scan: 扫描系统漏洞和配置风险，生成安全评估报告（tags: security, scan）",
    "- attack_detection: 检测 SQL 注入、XSS、DDoS 等攻击行为，分析攻击源和攻击模式（tags: security, attack）",
    "- access_audit: 审计用户访问日志，检测异常登录和权限越界（tags: security, audit）",
    "- compliance_check: 检查系统配置是否符合安全合规要求（等级保护、GDPR 等）（tags: security, compliance）",
])
SECURITY_NAME = "security-agent"
SECURITY_DESC = "安全与风控智能体，负责漏洞扫描、攻击检测、访问审计、安全合规检查"

# Agent F: 日志与链路追踪（主领域）
LOG_TRACE_SKILLS = "\n".join([
    "- log_aggregation: 聚合多服务日志，按时间线关联分析（tags: logs, aggregation）",
    "- trace_analysis: 追踪分布式调用链，定位慢请求和错误节点（tags: trace, distributed）",
    "- error_pattern: 识别日志中的错误模式、异常堆栈和重复错误（tags: logs, error）",
    "- log_search: 按关键字、时间范围、服务名搜索日志（tags: logs, search）",
])
LOG_TRACE_NAME = "log-trace-agent"
LOG_TRACE_DESC = "日志与链路追踪智能体，负责日志聚合分析、分布式链路追踪、错误模式识别、日志搜索"

# Agent G: CDN 与边缘加速（主领域）
CDN_SKILLS = "\n".join([
    "- cdn_cache_hit: 查询 CDN 缓存命中率、回源率和带宽使用（tags: cdn, cache）",
    "- edge_node_status: 检查边缘节点健康状态和可用性（tags: cdn, edge）",
    "- origin_shield: 分析源站防护策略和回源流量（tags: cdn, origin）",
    "- cdn_config: 检查 CDN 加速域名配置、HTTPS 证书和缓存规则（tags: cdn, config）",
])
CDN_NAME = "cdn-agent"
CDN_DESC = "CDN 与边缘加速智能体，负责 CDN 缓存命中率监控、边缘节点状态、源站防护、CDN 配置管理"

# Agent H: 订单与交易（主领域）
ORDER_TRADE_SKILLS = "\n".join([
    "- order_status: 查询订单状态、流转记录和异常订单（tags: order, status）",
    "- payment_flow: 追踪支付流水、对账状态和退款记录（tags: payment, reconciliation）",
    "- transaction_audit: 审计交易记录，检测异常交易和重复支付（tags: transaction, audit）",
    "- order_volume: 查询订单量趋势、支付转化率和客单价（tags: order, metrics）",
])
ORDER_TRADE_NAME = "order-trade-agent"
ORDER_TRADE_DESC = "订单与交易智能体，负责订单状态查询、支付流水追踪、交易审计、订单量趋势分析"

# Agent I: 大促与营销（主领域）
PROMO_SKILLS = "\n".join([
    "- campaign_status: 查看营销活动状态、预算消耗和投放效果（tags: marketing, campaign）",
    "- coupon_usage: 查询优惠券发放量、核销率和薅羊毛检测（tags: marketing, coupon）",
    "- flash_sale: 监控秒杀活动库存、瞬时流量和限流状态（tags: marketing, flash-sale）",
    "- traffic_source: 分析流量来源渠道、转化效果和 ROI（tags: marketing, traffic）",
])
PROMO_NAME = "promo-agent"
PROMO_DESC = "大促与营销智能体，负责营销活动管理、优惠券分析、秒杀监控、流量来源分析"

# Agent J: 客服与工单（主领域）
TICKET_SKILLS = "\n".join([
    "- ticket_query: 查询工单状态、处理进度和 SLA 超时情况（tags: ticket, query）",
    "- customer_complaint: 分析用户投诉内容、分类和趋势（tags: ticket, complaint）",
    "- ticket_escalation: 查看工单升级记录和处理人变更（tags: ticket, escalation）",
    "- knowledge_base: 搜索知识库文章和常见问题解答（tags: ticket, knowledge）",
])
TICKET_NAME = "ticket-agent"
TICKET_DESC = "客服与工单智能体，负责工单查询、用户投诉分析、工单升级管理、知识库搜索"


@dataclass(frozen=True)
class CrossDomainCase:
    """A cross-domain test case for a specific agent.

    Each case asks: given a cross-domain query, should THIS specific agent
    handle it or contribute to it?
    """
    name: str
    query: str
    agent_skills: str
    agent_name: str
    agent_description: str
    expect_can_handle: bool
    expect_can_contribute: bool


# ── 20 cross-domain test cases ─────────────────────────────────────────
#
# Each case is run against ONE specific agent, testing domain-first logic
# in multi-domain queries.
#
# Groups:
#   C1 (1-6):  DB agent is primary domain owner (handle=true)
#              even when other domains are involved
#   C2 (7-10): DB agent is NOT primary, but can contribute (contribute=true)
#   C3 (11-16): Non-DB agents tested in cross-domain scenarios
#   C4 (17-20): Peer domain / hybrid scenarios — tricky boundary cases
# ───────────────────────────────────────────────────────────────────────

CASES = [
    # ═══════════════ C1: DB agent is primary domain owner (handle=true) ═══════════════
    # 即使涉及部署、网络、业务等领域，只要主领域是数据库就应该 handle
    CrossDomainCase(
        "c1_db_primary_with_deploy",
        "今天凌晨数据库版本升级后，QPS 下降了 30%，"
        "需要排查是数据库配置变更导致的还是新版本有性能回退，"
        "同时查看部署记录确认升级过程是否有异常",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c1_db_primary_with_network",
        "部分服务连接到数据库的主库出现超时，"
        "需要排查数据库连接池状态和主库负载，"
        "同时确认网络链路是否正常",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c1_db_primary_with_biz",
        "数据库慢查询突然增多，导致订单创建接口超时，"
        "帮我分析慢查询日志找出根因，同时查看业务侧订单创建成功率是否下降",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c1_db_primary_with_all",
        "线上出现大规模故障：数据库 CPU 打满、服务大量重启、"
        "用户投诉无法下单。先从数据库侧排查，"
        "分析是否因为数据库性能问题引发了连锁反应",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c1_db_primary_post_incident",
        "昨天数据库宕机 30 分钟，需要对数据库做一次完整的根因分析，"
        "包括宕机前的慢查询、连接数变化、内存使用趋势，"
        "同时参考运维侧的事件时间线和告警时序",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c1_db_primary_optimization",
        "数据库查询性能持续下降，需要进行全面的数据库优化，"
        "包括索引优化、SQL 改写、连接池调参，"
        "同时评估优化后对业务查询响应时间的影响",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),

    # ═══════════════ C2: DB agent is NOT primary, but can contribute ═══════════════
    CrossDomainCase(
        "c2_db_contribute_full_incident",
        "服务刚完成大规模部署升级后，系统出现大面积故障，"
        "重点排查部署变更记录、配置差异和应用日志异常，"
        "同时确认数据库连接池是否因部署变更出现异常连接",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c2_db_contribute_new_release",
        "新版本发布后不到 10 分钟，服务开始出现 5xx 错误，"
        "需要排查：部署日志中的异常、应用日志中的错误堆栈、"
        "数据库连接是否有异常、用户反馈的错误率",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c2_db_contribute_capacity_planning",
        "双十一大促前需要做全链路容量评估："
        "网关带宽、各服务实例数、缓存容量、"
        "数据库最大 QPS 和连接数上限",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c2_db_contribute_user_complaint",
        "用户投诉 APP 首页加载很慢，需要排查："
        "CDN 缓存命中率、API 网关延迟、后端服务处理时间、"
        "以及数据库查询耗时",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),

    # ═══════════════ C3: Non-DB agents in cross-domain scenarios ═══════════════
    # 部署运维智能体
    CrossDomainCase(
        "c3_deploy_primary_with_db",
        "新版本发布后数据库连接数异常增长，"
        "需要排查部署流程是否有配置变更导致连接池配置错误，"
        "同时查看数据库侧实际的连接池状态",
        DEPLOY_OPS_SKILLS, DEPLOY_OPS_NAME, DEPLOY_OPS_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c3_deploy_contribute_db_heavy",
        "数据库 CPU 突然飙升到 100%，导致服务大面积超时，"
        "需要排查数据库慢查询和分析执行计划，"
        "同时查看服务侧是否有部署或配置变更触发了异常流量",
        DEPLOY_OPS_SKILLS, DEPLOY_OPS_NAME, DEPLOY_OPS_DESC,
        False, True,
    ),
    # 网络基础设施智能体
    CrossDomainCase(
        "c3_network_primary_with_db",
        "网络监控发现主从数据库之间的链路延迟突然增大，导致主从同步延迟，"
        "需要排查网络链路的延迟和带宽瓶颈，"
        "同时确认数据库侧主从复制状态",
        NETWORK_INFRA_SKILLS, NETWORK_INFRA_NAME, NETWORK_INFRA_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c3_network_contribute_db_heavy",
        "数据库连接池频繁出现连接超时，"
        "需要排查数据库连接池配置和慢查询，"
        "同时检查网络链路质量和防火墙规则是否有异常",
        NETWORK_INFRA_SKILLS, NETWORK_INFRA_NAME, NETWORK_INFRA_DESC,
        False, True,
    ),
    # 业务监控智能体
    CrossDomainCase(
        "c3_biz_primary_with_db",
        "订单成功率突然下降 20%，需要排查业务指标异常，"
        "同时查看数据库是否有慢查询或连接异常导致的超时",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c3_biz_contribute_db_heavy",
        "数据库慢查询日志中频繁出现订单查询相关的 SQL，"
        "需要分析慢查询根因并优化 SQL，"
        "同时查看业务侧订单量的变化趋势以判断是否业务量突增",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        False, True,
    ),

    # ═══════════════ C4: Peer domain / hybrid / boundary scenarios ═══════════════
    # 两个领域同等重要，每个 agent 都应该 handle 自己的部分
    CrossDomainCase(
        "c4_peer_db_and_deploy_db",
        "数据库连接数异常增长和部署配置变更同时发生，"
        "需要同时排查数据库侧的连接来源和部署侧的配置差异",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c4_peer_db_and_deploy_deploy",
        "数据库连接数异常增长和部署配置变更同时发生，"
        "需要同时排查数据库侧的连接来源和部署侧的配置差异",
        DEPLOY_OPS_SKILLS, DEPLOY_OPS_NAME, DEPLOY_OPS_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c4_peer_network_and_db_network",
        "网络链路出现间歇性丢包，同时数据库侧也出现连接异常，"
        "需要分别排查网络链路质量和数据库连接状态",
        NETWORK_INFRA_SKILLS, NETWORK_INFRA_NAME, NETWORK_INFRA_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c4_peer_network_and_db_db",
        "网络链路出现间歇性丢包，同时数据库侧也出现连接异常，"
        "需要分别排查网络链路质量和数据库连接状态",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),

    # ═══════════════ C5: 安全与风控跨领域场景 ═══════════════
    CrossDomainCase(
        "c5_security_primary_db_attack",
        "收到安全告警：数据库被 SQL 注入攻击，大量异常查询导致数据库负载飙升，"
        "需要排查攻击来源和攻击模式，同时分析数据库侧慢查询日志确认攻击影响范围",
        SECURITY_SKILLS, SECURITY_NAME, SECURITY_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c5_security_contribute_db_leak",
        "数据库慢查询日志中发现大量非业务时段的敏感数据查询，"
        "需要排查数据库慢查询和连接来源，同时从安全审计角度分析是否数据泄露",
        SECURITY_SKILLS, SECURITY_NAME, SECURITY_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c5_db_primary_security_incident",
        "收到安全告警：数据库被 SQL 注入攻击，大量异常查询导致数据库负载飙升，"
        "需要排查攻击来源和攻击模式，同时分析数据库侧慢查询日志确认攻击影响范围",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c5_db_contribute_security_audit",
        "用户权限审计发现异常登录行为，需要排查访问日志和权限变更记录，"
        "同时检查数据库连接池是否有异常连接来自可疑 IP",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),

    # ═══════════════ C6: 日志与链路追踪跨领域场景 ═══════════════
    CrossDomainCase(
        "c6_logtrace_primary_x_domain",
        "用户反馈下单超时，需要追踪完整的分布式调用链定位慢节点，"
        "同时关联数据库慢查询日志和网关延迟日志",
        LOG_TRACE_SKILLS, LOG_TRACE_NAME, LOG_TRACE_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c6_logtrace_contribute_db",
        "数据库查询性能突然下降，需要分析慢查询日志和执行计划，"
        "同时从分布式链路追踪角度确认哪些服务调用链受数据库慢查询影响",
        LOG_TRACE_SKILLS, LOG_TRACE_NAME, LOG_TRACE_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c6_db_primary_trace",
        "用户反馈下单超时，需要追踪完整的分布式调用链定位慢节点，"
        "同时关联数据库慢查询日志和网关延迟日志",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),

    # ═══════════════ C7: CDN 与边缘加速跨领域场景 ═══════════════
    CrossDomainCase(
        "c7_cdn_primary_x_domain",
        "大促期间用户投诉页面加载慢，需要排查 CDN 缓存命中率和回源率，"
        "同时确认源站数据库是否有慢查询导致回源响应慢",
        CDN_SKILLS, CDN_NAME, CDN_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c7_db_contribute_cdn",
        "大促期间用户投诉页面加载慢，需要排查 CDN 缓存命中率和回源率，"
        "同时确认源站数据库是否有慢查询导致回源响应慢",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c7_biz_primary_cdn_impact",
        "大促期间 GMV 环比下降 30%，需要排查业务转化率和用户行为，"
        "同时检查 CDN 加速是否正常，页面加载慢是否导致用户流失",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        True, True,
    ),

    # ═══════════════ C8: 订单与交易跨领域场景 ═══════════════
    CrossDomainCase(
        "c8_order_primary_x_domain",
        "用户反馈支付成功但订单状态未更新，需要排查订单状态流转和支付流水，"
        "同时检查数据库是否有事务锁等待或连接超时导致状态更新失败",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c8_db_contribute_order",
        "用户反馈支付成功但订单状态未更新，需要排查订单状态流转和支付流水，"
        "排查过程中需要检查数据库事务锁和连接状态以确认是否因数据库问题导致更新失败",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        False, True,
    ),
    CrossDomainCase(
        "c8_biz_primary_order_anomaly",
        "订单量突然下降 40% 但支付成功率正常，需要排查订单创建流程和用户行为，"
        "同时检查数据库是否有性能瓶颈导致订单入库失败",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        True, True,
    ),

    # ═══════════════ C9: 大促与营销跨领域场景 ═══════════════
    CrossDomainCase(
        "c9_promo_primary_x_domain",
        "秒杀活动开始后瞬间涌入大量用户，需要监控秒杀库存和瞬时流量，"
        "同时检查数据库 QPS 是否超出上限导致数据库连接池耗尽",
        PROMO_SKILLS, PROMO_NAME, PROMO_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c9_db_contribute_flash_sale",
        "秒杀活动开始后瞬间涌入大量用户，需要监控秒杀库存和瞬时流量，"
        "同时检查数据库 QPS 是否超出上限导致数据库连接池耗尽",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c9_promo_primary_coupon_fraud",
        "优惠券核销率异常飙升，需要排查薅羊毛行为和优惠券使用模式，"
        "同时检查订单系统是否有异常重复下单和支付记录",
        PROMO_SKILLS, PROMO_NAME, PROMO_DESC,
        True, True,
    ),

    # ═══════════════ C10: 客服与工单跨领域场景 ═══════════════
    CrossDomainCase(
        "c10_ticket_primary_x_domain",
        "大量用户投诉无法下单，需要分析投诉内容和分类趋势，"
        "同时从数据库侧排查是否有慢查询或连接异常导致下单失败",
        TICKET_SKILLS, TICKET_NAME, TICKET_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c10_db_contribute_ticket",
        "大量用户投诉无法下单，需要分析投诉内容和分类趋势，"
        "同时从数据库侧排查是否有慢查询或连接异常导致下单失败",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c10_order_primary_ticket",
        "客服反馈大量订单状态异常工单，需要排查订单状态流转和异常订单，"
        "同时分析工单趋势和用户投诉分类",
        ORDER_TRADE_SKILLS, ORDER_TRADE_NAME, ORDER_TRADE_DESC,
        True, True,
    ),

    # ═══════════════ C11: 多领域 peer 联合场景 ═══════════════
    CrossDomainCase(
        "c11_peer_security_deploy",
        "安全扫描发现生产环境存在高危漏洞，运维需要对漏洞进行紧急修复部署，"
        "同时安全侧需要评估漏洞影响范围和攻击路径",
        SECURITY_SKILLS, SECURITY_NAME, SECURITY_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c11_peer_security_deploy_ops",
        "安全扫描发现生产环境存在高危漏洞，运维需要对漏洞进行紧急修复部署，"
        "同时安全侧需要评估漏洞影响范围和攻击路径",
        DEPLOY_OPS_SKILLS, DEPLOY_OPS_NAME, DEPLOY_OPS_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c11_peer_promo_db_network",
        "双十一零点大促，需要同时监控：营销活动效果和秒杀流量、"
        "数据库 QPS 和连接数、网络带宽、CDN 缓存命中率",
        PROMO_SKILLS, PROMO_NAME, PROMO_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c11_peer_promo_db_network_db",
        "双十一零点大促，需要同时监控：营销活动效果和秒杀流量、"
        "数据库 QPS 和连接数、网络带宽、CDN 缓存命中率",
        DB_MONITOR_SKILLS, DB_MONITOR_NAME, DB_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c11_peer_promo_db_network_network",
        "双十一零点大促，需要同时监控：营销活动效果和秒杀流量、"
        "数据库 QPS 和连接数、网络带宽、CDN 缓存命中率",
        NETWORK_INFRA_SKILLS, NETWORK_INFRA_NAME, NETWORK_INFRA_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c11_peer_promo_db_network_cdn",
        "双十一零点大促，需要同时监控：营销活动效果和秒杀流量、"
        "数据库 QPS 和连接数、网络带宽、CDN 缓存命中率",
        CDN_SKILLS, CDN_NAME, CDN_DESC,
        True, True,
    ),

    # ═══════════════ C12: 业务场景边界/对抗用例 ═══════════════
    CrossDomainCase(
        "c12_biz_refund_chain",
        "退款率突然上升 50%，需要排查退款原因和用户行为，"
        "同时检查是否有商品质量问题或物流异常导致的集中退款",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c12_deploy_emergency_rollback",
        "紧急回滚操作执行后，需要确认回滚是否成功和部署状态，"
        "同时检查数据库连接数和业务指标是否恢复正常",
        DEPLOY_OPS_SKILLS, DEPLOY_OPS_NAME, DEPLOY_OPS_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c12_security_ddos_db",
        "DDoS 攻击导致数据库连接池被异常流量耗尽，"
        "需要从安全侧追踪攻击源和攻击流量，同时从数据库侧确认连接池恢复状态",
        SECURITY_SKILLS, SECURITY_NAME, SECURITY_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c12_biz_order_peer",
        "订单量和 GMV 同时出现异常下降，需要排查业务指标异常趋势和用户行为，"
        "同时检查订单系统是否有异常订单状态或支付失败集中出现",
        BIZ_MONITOR_SKILLS, BIZ_MONITOR_NAME, BIZ_MONITOR_DESC,
        True, True,
    ),
    CrossDomainCase(
        "c12_network_security_peer",
        "网络入侵检测发现异常流量模式，需要排查防火墙规则和网络流量，"
        "同时安全侧需要分析攻击类型和入侵路径",
        NETWORK_INFRA_SKILLS, NETWORK_INFRA_NAME, NETWORK_INFRA_DESC,
        True, True,
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


async def _judge(case: CrossDomainCase) -> dict[str, Any]:
    prompt = sa.SKILL_CAPABILITY_CHECK_PROMPT.format(
        agent_name=case.agent_name,
        agent_description=case.agent_description,
        agent_skills=case.agent_skills,
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
            "run_id": f"cross-domain-{case.name}",
            "trace_id": "d" * 32,
            "user_id": "skill-cross-domain-live",
        },
        tool_choice="evaluate_capability",
        span_name="skill-cross-domain-live",
        span_input={"query": case.query, "case": case.name},
    )
    assert data is not None, "LLM did not call evaluate_capability"
    return data


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    can_handle, can_contribute = sa._normalize_capability_result(raw)
    result = dict(raw)
    result["can_handle"] = can_handle
    result["can_contribute"] = can_contribute
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
async def test_skill_capability_cross_domain_live(case: CrossDomainCase):
    raw = await _judge(case)
    data = _normalize(raw)
    can_handle = bool(data.get("can_handle"))
    can_contribute = bool(data.get("can_contribute"))
    reason = str(data.get("reason") or "")
    print(
        f"\n[{case.name}] agent={case.agent_name} "
        f"handle={can_handle} contribute={can_contribute} "
        f"conf={data.get('confidence')} reason={reason[:300]}"
    )
    assert can_handle is case.expect_can_handle
    assert can_contribute is case.expect_can_contribute