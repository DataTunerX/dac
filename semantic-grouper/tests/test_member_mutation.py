from semantic_grouper.semantic_group import SemanticGrouper


def _grouper() -> SemanticGrouper:
    grouper = SemanticGrouper.__new__(SemanticGrouper)
    grouper.vector_client = None
    grouper.collection_name = "semantic_groups"
    return grouper


def test_refresh_incremental_uses_current_members():
    refresh_calls = []

    class GroupClient:
        def get_semantic_group_by_id(self, group_id):
            return {
                "data": {
                    "id": group_id,
                    "group_name": "Commerce",
                    "description": "old desc",
                    "agent_card": "{}",
                    "version": "1",
                }
            }

        def get_relations_by_group_id(self, _group_id):
            return {"data": [{"id": 1, "sd_id": "sd-new", "group_id": "group-1"}]}

        def create_dd_group_relation(self, _relation):
            raise AssertionError("refresh must not write membership")

        def delete_dd_group_relation(self, _relation_id):
            raise AssertionError("refresh must not delete membership")

    class DomainClient:
        def get_semantic_domain_by_id(self, domain_id):
            return {
                "data": {
                    "semantic_domain_id": domain_id,
                    "semantic_domain": "payments analysis",
                    "agent_card": '{"name":"Pay"}',
                    "dd_namespace": "ns",
                    "dd_name": "payments-dd",
                }
            }

    grouper = _grouper()
    grouper.semantic_group_client = GroupClient()
    grouper.semantic_domain_client = DomainClient()
    grouper._refresh_semantic_group_after_member_resync = (
        lambda group_id, domain, before: refresh_calls.append((group_id, domain, before))
        or True
    )
    grouper.reconcile_group_metadata = lambda _gid: (
        (_ for _ in ()).throw(AssertionError("incremental should not fall back"))
    )

    result = grouper.refresh_group_metadata("group-1", mode="incremental")

    assert result["status"] == "success"
    assert result["action"] == "REFRESHED"
    assert result["remaining_member_count"] == 1
    assert len(refresh_calls) == 1
    assert refresh_calls[0][0] == "group-1"
    assert refresh_calls[0][1]["semantic_domain_id"] == "sd-new"


def test_refresh_incremental_skips_empty_group():
    class GroupClient:
        def get_semantic_group_by_id(self, group_id):
            return {"data": {"id": group_id, "group_name": "G", "description": "", "agent_card": ""}}

        def get_relations_by_group_id(self, _group_id):
            return {"data": []}

    grouper = _grouper()
    grouper.semantic_group_client = GroupClient()
    grouper.semantic_domain_client = None
    grouper._refresh_semantic_group_after_member_resync = lambda *_a, **_k: (
        (_ for _ in ()).throw(AssertionError("empty group should not refresh"))
    )

    result = grouper.refresh_group_metadata("group-1", mode="incremental")

    assert result["status"] == "success"
    assert result["action"] == "SKIPPED"


def test_refresh_decremental_reuses_reconcile():
    reconciled = []

    grouper = _grouper()
    grouper.semantic_group_client = object()
    grouper.reconcile_group_metadata = lambda group_id: (
        reconciled.append(group_id)
        or {
            "status": "success",
            "action": "REINDUCT_SCHEDULED",
            "group_id": group_id,
            "remaining_member_count": 1,
        }
    )

    result = grouper.refresh_group_metadata("group-1", mode="decremental")

    assert result["action"] == "REINDUCT_SCHEDULED"
    assert reconciled == ["group-1"]


def test_refresh_rejects_unknown_mode():
    grouper = _grouper()
    result = grouper.refresh_group_metadata("group-1", mode="merge")
    assert result["status"] == "error"
    assert "unsupported refresh mode" in result["message"]
