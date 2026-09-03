"""Focused tests for LLM-based capability checks at the SD Orchestrator."""

import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestrator_agent import orchestrator_agent_semantic_domain as domain
from orchestrator_agent.dataservices_client import DataServicesClient


def _signature(tables_detail: str = "", **extra):
    value = {
        "metadata_content": {"tables_detail": tables_detail} if tables_detail else {},
        "dd_namespace": "shop",
        "dd_name": "orders",
    }
    value.update(extra)
    return value


def test_capability_context_is_type_agnostic_for_code_and_docs():
    context = domain._build_member_capability_context(
        [
            {
                "descriptor_type": "code",
                "semantic_domain": "支付网关服务代码",
                "metadata_content": {
                    "summary": "timeout retry policy in payment-gateway",
                    "file_summary": "TimeoutPolicy.java",
                },
            },
            {
                "descriptor_type": "unstructured",
                "semantic_domain": "报销审批文档",
                "metadata_content": {
                    "document_summary": "员工报销需部门经理审批",
                    "topics": ["报销", "审批流程"],
                },
            },
        ],
        descriptor_type="code",
    )

    assert "支付网关服务代码" in context
    assert "TimeoutPolicy.java" in context
    assert "报销审批文档" in context
    assert "员工报销需部门经理审批" in context


def test_capability_context_prioritizes_domain_prose_over_bulky_schema():
    bulky_tables = "table " + ("orders " * 2000)
    context = domain._build_member_capability_context(
        [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "全渠道零售与电商中台，覆盖会员与交易",
                "agent_card": {"description": "Omnichannel retail platform"},
                "metadata_content": {
                    "tables_detail": bulky_tables,
                    "summary": "会员等级与折扣策略",
                },
            }
        ],
        descriptor_type="structured-mysql",
        max_chars=2500,
    )

    assert "全渠道零售与电商中台，覆盖会员与交易" in context
    assert "Omnichannel retail platform" in context
    assert "会员等级与折扣策略" in context
    assert "knowledge_prose" in context
    assert "agent_card_description" in context


def test_capability_context_uses_tables_detail_not_full_schema_dump():
    context = domain._build_member_capability_context(
        [
            {
                "descriptor_type": "structured-mysql",
                "semantic_domain": "银行分支机构财务数据",
                "agent_card": json.dumps(
                    {
                        "name": "BankFinancialDataAgent",
                        "description": "银行业分支机构财务数据领域专家",
                        "skills": [
                            {
                                "id": "deposit",
                                "name": "存款业务",
                                "description": "覆盖对公和零售存款查询与分析",
                                "tags": ["deposit", "存款"],
                                "inputModes": None,
                                "outputModes": None,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                "metadata_content": {
                    "tables_detail": (
                        "1. table name: deposit_data(存款数据)，table description: 记录存款明细"
                    ),
                    "tables_schema_md_list": [
                        {
                            "table_name": "deposit_data",
                            "table_schema": "## Table: `deposit_data`\n| Column | Type |\n| id | int |",
                        }
                    ],
                    "tables_relationship": "deposit_data.branch_id -> branch.id",
                },
            }
        ],
        descriptor_type="structured-mysql",
        max_chars=20000,
    )

    assert "银行分支机构财务数据" in context
    assert "银行业分支机构财务数据领域专家" in context
    assert "agent_card_description" in context
    assert "agent_card_skills" in context
    assert "存款业务" in context
    assert "覆盖对公和零售存款查询与分析" in context
    assert "BankFinancialDataAgent" not in context
    assert "inputModes" not in context
    assert "deposit_data(存款数据)" in context
    assert "tables_detail" in context
    assert "tables_schema_md_list" not in context
    assert "## Table: `deposit_data`" not in context
    assert domain._capability_context_max_chars() >= 50000


def test_format_file_summaries_prefers_path_and_caps_text():
    text = domain._format_file_summaries_for_capability(
        [
            {
                "file_name": "reimburse.pdf",
                "minio_path": "minio://docs/hr/reimburse.pdf",
                "file_summary": "员工报销需部门经理审批，超过五千需财务复核。",
            },
            {
                "file_name": "empty.md",
                "minio_path": "docs/empty.md",
                "file_summary": "",
            },
            {"file_name": "", "minio_path": "", "file_summary": "skip me"},
        ],
        summary_chars=80,
    )
    assert "1. file: reimburse.pdf，summary: 员工报销需部门经理审批" in text
    assert "2. file: empty.md" in text
    assert "skip me" not in text


def test_capability_context_uses_file_summaries_inventory():
    context = domain._build_member_capability_context(
        [
            {
                "descriptor_type": "unstructured",
                "semantic_domain": "报销审批文档",
                "agent_card": {"description": "公司报销制度文档专家"},
                "file_summaries": (
                    "1. file: reimburse.pdf，summary: 员工报销需部门经理审批"
                ),
                "metadata_content": {
                    "document_summary": "报销制度总览",
                    "topics": ["报销", "审批流程"],
                },
            }
        ],
        descriptor_type="unstructured",
        max_chars=20000,
    )

    assert "报销审批文档" in context
    assert "公司报销制度文档专家" in context
    assert "file_summaries" in context
    assert "reimburse.pdf" in context
    assert "员工报销需部门经理审批" in context
    assert "报销制度总览" in context


@pytest.mark.asyncio
async def test_dataservices_list_unstructured_files_paginates():
    class FakeResponse:
        def __init__(self, payload):
            self.status = 200
            self._payload = payload

        async def text(self):
            return json.dumps(self._payload)

        async def json(self):
            return self._payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

    class FakeSession:
        closed = False

        def __init__(self):
            self.calls = []

        def get(self, url, params=None):
            self.calls.append((url, params))
            offset = int((params or {}).get("offset") or 0)
            if offset == 0:
                return FakeResponse(
                    {
                        "status": "success",
                        "data": [
                            {
                                "file_name": "a.pdf",
                                "minio_path": "a.pdf",
                                "file_summary": "alpha",
                            }
                        ],
                    }
                )
            return FakeResponse(
                {
                    "status": "success",
                    "data": [
                        {
                            "file_name": "b.pdf",
                            "minio_path": "b.pdf",
                            "file_summary": "beta",
                        }
                    ],
                }
            )

        async def close(self):
            pass

    client = DataServicesClient(base_url="http://data-services")
    client.session = FakeSession()

    result = await client.list_unstructured_files_by_dd(
        "shop", "docs", page_size=1, max_rows=2
    )

    assert [row["file_name"] for row in result] == ["a.pdf", "b.pdf"]
    assert client.session.calls == [
        (
            "http://data-services/unstructured-files",
            {
                "dd_namespace": "shop",
                "dd_name": "docs",
                "limit": 1,
                "offset": 0,
            },
        ),
        (
            "http://data-services/unstructured-files",
            {
                "dd_namespace": "shop",
                "dd_name": "docs",
                "limit": 1,
                "offset": 1,
            },
        ),
    ]


@pytest.mark.asyncio
async def test_doc_capability_check_attaches_file_summaries(monkeypatch):
    class DocClient:
        def __init__(self, **_kwargs):
            pass

        async def search_signatures_by_dd(self, _namespace, _name):
            return [
                {
                    "dd_namespace": "shop",
                    "dd_name": "docs",
                    "descriptor_type": "unstructured",
                    "metadata_content": {"document_summary": "报销制度总览"},
                }
            ]

        async def search_semantic_domains_by_dd(self, _namespace, _name):
            return [
                {
                    "semantic_domain": "报销审批文档",
                    "descriptor_type": "unstructured",
                    "agent_card": {"description": "公司报销制度文档专家"},
                }
            ]

        async def list_unstructured_files_by_dd(self, _namespace, _name, **_kwargs):
            return [
                {
                    "file_name": "reimburse.pdf",
                    "minio_path": "hr/reimburse.pdf",
                    "file_summary": "员工报销需部门经理审批",
                }
            ]

        async def close(self):
            pass

    captured = {}

    async def fake_judge(_self, **kwargs):
        captured["signatures"] = kwargs["signatures"]
        captured["descriptor_type"] = kwargs["descriptor_type"]
        return domain._normalize_member_capability_judgment(
            {
                "domain_match": True,
                "can_handle": True,
                "can_contribute": True,
                "confidence": 0.9,
                "reason": "文档清单覆盖报销审批",
                "matched_evidence": ["reimburse.pdf"],
                "missing_requirements": [],
            },
            agent_name="DocsAgent",
            agent_url="http://docs:10100",
            descriptor_type="unstructured",
        )

    _FakeUpdater.instances.clear()
    monkeypatch.setattr(domain, "DataServicesClient", DocClient)
    monkeypatch.setattr(domain, "TaskUpdater", _FakeUpdater)
    monkeypatch.setattr(domain, "new_agent_text_message", lambda *_a, **_k: None)
    monkeypatch.setattr(
        domain.OrchestratorAgentExecutorSemanticDomain,
        "_judge_member_capability_with_llm",
        fake_judge,
    )

    executor = domain.OrchestratorAgentExecutorSemanticDomain(
        data_descriptors=["docs"],
        dd_namespace="shop",
        descriptor_types=["docs:unstructured"],
        data_services_url="http://data-services",
        agent_id="DocsAgent",
        agent_card=SimpleNamespace(name="DocsAgent", url="http://docs:10100"),
    )
    await executor.execute(_FakeContext("报销审批要找谁签字？"), SimpleNamespace())

    assert captured["descriptor_type"] == "unstructured"
    summaries = captured["signatures"][0]["file_summaries"]
    assert "reimburse.pdf" in summaries
    assert "员工报销需部门经理审批" in summaries
    context = domain._build_member_capability_context(
        captured["signatures"],
        descriptor_type="unstructured",
    )
    assert "file_summaries" in context
    assert "员工报销需部门经理审批" in context


def test_normalize_llm_judgment_maps_compatible_response_shape():
    response = domain._normalize_member_capability_judgment(
        {
            "domain_match": True,
            "can_handle": True,
            "can_contribute": True,
            "confidence": 0.91,
            "reason": "营销活动元数据可覆盖该问题",
            "matched_evidence": ["营销活动", "campaign_code"],
            "missing_requirements": [],
        },
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )

    assert response["can_handle"] is True
    assert response["can_contribute"] is True
    assert response["domain_match"] is True
    assert response["evidence_mode"] == "llm"
    assert response["matched_evidence"] == ["营销活动", "campaign_code"]
    assert response["matched_entities"] == ["营销活动", "campaign_code"]
    assert response["missing_requirements"] == []


@pytest.mark.asyncio
async def test_dataservices_signature_lookup_posts_dd_payload():
    class FakeResponse:
        status = 200

        async def text(self):
            return '{"status":"success"}'

        async def json(self):
            return {"status": "success", "data": [{"sig_id": "sig-1"}]}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

    class FakeSession:
        closed = False

        def __init__(self):
            self.calls = []

        def post(self, url, json):
            self.calls.append((url, json))
            return FakeResponse()

    client = DataServicesClient(base_url="http://data-services")
    client.session = FakeSession()

    result = await client.search_signatures_by_dd("shop", "orders")

    assert result == [{"sig_id": "sig-1"}]
    assert client.session.calls == [
        (
            "http://data-services/signatures/search/by-dd",
            {"dd_namespace": "shop", "dd_name": "orders"},
        )
    ]


class _FakeUpdater:
    instances = []

    def __init__(self, _event_queue, _task_id, _context_id):
        self.artifacts = []
        self.completed = False
        self.__class__.instances.append(self)

    async def add_artifact(self, parts, name=None):
        self.artifacts.append((parts, name))

    async def complete(self, message=None):
        self.completed = True


class _FakeContext:
    def __init__(self, query):
        self.metadata = {"message_type": "member_capability_check"}
        self.current_task = SimpleNamespace(id="task", context_id="context")
        self.message = SimpleNamespace()
        self._query = query

    def get_user_input(self):
        return self._query


def _executor():
    return domain.OrchestratorAgentExecutorSemanticDomain(
        data_descriptors=["orders"],
        dd_namespace="shop",
        descriptor_types=["orders:structured-mysql"],
        data_services_url="http://data-services",
        agent_id="OrdersAgent",
        agent_card=SimpleNamespace(
            name="OrdersAgent",
            url="http://orders:10100",
        ),
    )


@pytest.mark.asyncio
async def test_fast_path_uses_llm_judge_without_expert_execution(monkeypatch):
    class SuccessfulClient:
        def __init__(self, **_kwargs):
            pass

        async def search_signatures_by_dd(self, _namespace, _name):
            return [
                _signature(
                    "1. table name: orders(订单)，table description: 订单主表",
                    semantic_domain="电商订单域",
                )
            ]

        async def search_semantic_domains_by_dd(self, _namespace, _name):
            return [{"semantic_domain": "电商订单域", "descriptor_type": "structured-mysql"}]

        async def list_unstructured_files_by_dd(self, _namespace, _name, **_kwargs):
            return []

        async def close(self):
            pass

    _FakeUpdater.instances.clear()
    monkeypatch.setattr(domain, "DataServicesClient", SuccessfulClient)
    monkeypatch.setattr(domain, "TaskUpdater", _FakeUpdater)
    monkeypatch.setattr(domain, "new_agent_text_message", lambda *_a, **_k: None)
    monkeypatch.setattr(
        domain.OrchestratorAgentExecutorSemanticDomain,
        "_judge_member_capability_with_llm",
        AsyncMock(
            return_value=domain._normalize_member_capability_judgment(
                {
                    "domain_match": True,
                    "can_handle": True,
                    "can_contribute": True,
                    "confidence": 0.93,
                    "reason": "订单元数据可覆盖该问题",
                    "matched_evidence": ["orders", "订单"],
                    "missing_requirements": [],
                },
                agent_name="OrdersAgent",
                agent_url="http://orders:10100",
                descriptor_type="structured-mysql",
            )
        ),
    )
    monkeypatch.setattr(
        domain.OrchestratorAgentExecutorSemanticDomain,
        "_ensure_skill_runner",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("normal orchestrator path was invoked")
        ),
    )

    await _executor().execute(_FakeContext("查询 orders"), SimpleNamespace())

    updater = _FakeUpdater.instances[-1]
    payload = json.loads(updater.artifacts[0][0][0].text)
    assert updater.completed is True
    assert payload["can_handle"] is True
    assert payload["evidence_mode"] == "llm"
    assert payload["matched_evidence"] == ["orders", "订单"]


@pytest.mark.asyncio
async def test_metadata_fetch_failure_is_distinct_and_stays_read_only(monkeypatch):
    class FailingClient:
        def __init__(self, **_kwargs):
            pass

        async def search_signatures_by_dd(self, _namespace, _name):
            raise ConnectionError("data services unavailable")

        async def close(self):
            pass

    _FakeUpdater.instances.clear()
    monkeypatch.setattr(domain, "DataServicesClient", FailingClient)
    monkeypatch.setattr(domain, "TaskUpdater", _FakeUpdater)
    monkeypatch.setattr(domain, "new_agent_text_message", lambda *_a, **_k: None)
    judge = AsyncMock()
    monkeypatch.setattr(
        domain.OrchestratorAgentExecutorSemanticDomain,
        "_judge_member_capability_with_llm",
        judge,
    )

    await _executor().execute(_FakeContext("查询 orders"), SimpleNamespace())

    payload = json.loads(_FakeUpdater.instances[-1].artifacts[0][0][0].text)
    assert payload["can_handle"] is False
    assert payload["confidence"] == 0.0
    assert payload["missing_requirements"] == ["capability_metadata_unavailable"]
    judge.assert_not_awaited()


@pytest.mark.asyncio
async def test_llm_judge_prompt_receives_metadata_context(monkeypatch):
    executor = _executor()
    captured = {}

    async def fake_invoke_llm_with_tool(**kwargs):
        captured["messages"] = kwargs["messages"]
        captured["tool_choice"] = kwargs["tool_choice"]
        return {
            "domain_match": True,
            "can_handle": False,
            "can_contribute": True,
            "confidence": 0.55,
            "reason": "仅部分相关",
            "matched_evidence": ["支付网关"],
            "missing_requirements": ["库存扣减"],
        }

    monkeypatch.setattr(
        domain.OrchestratorAgentExecutorSemanticDomain,
        "_build_capability_judge_llm",
        lambda self: object(),
    )
    monkeypatch.setattr(domain, "invoke_llm_with_tool", fake_invoke_llm_with_tool)

    result = await executor._judge_member_capability_with_llm(
        query="支付网关超时重试和库存扣减怎么实现？",
        signatures=[
            {
                "descriptor_type": "code",
                "semantic_domain": "支付网关超时重试代码",
                "metadata_content": {"summary": "payment-gateway retry"},
            }
        ],
        agent_name="CodeAgent",
        agent_url="http://code:10100",
        descriptor_type="code",
        request_metadata={"run_id": "r1"},
    )

    assert captured["tool_choice"] == "judge_member_capability"
    joined = "\n".join(str(getattr(m, "content", m)) for m in captured["messages"])
    assert "支付网关超时重试代码" in joined
    assert "payment-gateway retry" in joined
    assert result["can_handle"] is False
    assert result["can_contribute"] is True
    assert result["missing_requirements"] == ["库存扣减"]
    assert result["evidence_mode"] == "llm"
    assert "repository/file coverage" in joined or "code" in joined.lower()


def test_normalize_keeps_can_handle_when_secondary_requirements_missing():
    response = domain._normalize_member_capability_judgment(
        {
            "domain_match": True,
            "can_handle": True,
            "can_contribute": True,
            "confidence": 0.88,
            "reason": "主实体为订单，缺用户姓名需跨域",
            "matched_evidence": ["orders", "order_shipping"],
            "missing_requirements": ["下单用户姓名/users"],
        },
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert response["can_handle"] is True
    assert response["can_contribute"] is True
    assert response["missing_requirements"] == ["下单用户姓名/users"]


def test_normalize_rejects_contribute_when_domain_mismatch():
    response = domain._normalize_member_capability_judgment(
        {
            "domain_match": False,
            "can_handle": False,
            "can_contribute": True,
            "confidence": 0.9,
            "reason": "无关领域",
            "matched_evidence": [],
            "missing_requirements": ["火箭发动机推力曲线数据"],
        },
        agent_name="OrdersAgent",
        agent_url="http://orders:10100",
        descriptor_type="structured-mysql",
    )
    assert response["domain_match"] is False
    assert response["can_handle"] is False
    assert response["can_contribute"] is False


def test_capability_prompt_defines_primary_entity_can_handle():
    prompt = domain._capability_judge_system_template("structured-mysql")
    assert "PRIMARY" in prompt or "anchoring subject" in prompt
    assert "Decision order" in prompt
    assert "must NOT by themselves force can_handle=false" in prompt
    assert "Do NOT require end-to-end completeness" in prompt
    assert "One anchor + related attribute/metric" in prompt
    assert "is NOT peer anchors" in prompt
    assert "never downgrade that case to" in prompt
    assert "and the corresponding Y attribute" in prompt
    assert "walking instances of X" in prompt
    assert "domain_match may still be true" in domain._capability_judge_system_template(
        "unstructured"
    )
    # No hardcoded business samples or domain-category exemplars in the judge prompt.
    for banned in (
        "ORD-2025",
        "inventory_logs",
        "payment_records",
        "张三",
        "SN-900",
        "C-VIP",
        "差旅报销",
        "Example: query",
        "order counts",
        "sales qty",
        "store/user",
        "coverage/mapping",
        "Swagger",
    ):
        assert banned not in prompt, f"prompt must not hardcode sample: {banned}"


def test_capability_prompt_peer_primary_vs_related_attribute():
    prompt = domain._capability_judge_system_template("structured-mysql")
    assert "Peer anchors = two or more independent anchoring subjects" in prompt
    assert "can_handle MUST be false" in prompt
    assert "can_handle=true is reserved for the anchor owner" in prompt
    assert "Both may be true when this agent owns the anchor" in prompt
    assert "Independently decide can_contribute" in prompt


def test_code_and_docs_prompts_have_no_hardcoded_samples():
    code_prompt = domain._capability_judge_system_template("code")
    docs_prompt = domain._capability_judge_system_template("unstructured")
    assert "repository/file coverage" in code_prompt
    assert "not database tables" in code_prompt
    assert "corpus coverage" in docs_prompt
    assert "file_summaries" in docs_prompt
    assert "not database tables" in docs_prompt
    for kind, prompt in (("code", code_prompt), ("unstructured", docs_prompt)):
        for banned in (
            "ORD-2025",
            "Example:",
            "差旅",
            "timeout-retry",
            "Swagger",
            "order counts",
            "sales qty",
            "store/user",
        ):
            assert banned not in prompt, f"{kind} prompt hardcoded sample: {banned}"


def test_partial_status_and_summary_keeps_structured_control():
    agent = domain.OrchestratorAgent.__new__(domain.OrchestratorAgent)
    control = {
        "reason_code": "data_sovereignty_gap",
        "outcome": "partial",
        "join_keys": {"user_id": ["1"]},
        "unfulfilled_needs": [{"missing_table": "users"}],
    }
    raw = (
        "sql query result: [{\"user_id\": 1, \"receiver_phone\": \"13800001001\"}]\n"
        f"structured_control: {json.dumps(control, ensure_ascii=False)}"
    )
    assert agent._is_partial_structured_control(control) is True
    formatted = agent._format_task_knowledge(1, "q", "order-dd", raw, "partial")
    assert "部分完成" in formatted
    assert "不可作为事实引用" not in formatted
    summary = domain.OrchestratorAgent._append_structured_control_to_summary(
        "无法完整回答，缺下单用户姓名。",
        [formatted],
    )
    assert "structured_control:" in summary
    assert "user_id" in summary
