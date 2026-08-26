import json

from semantic_grouper.semantic_group import SemanticGrouper


def _grouper() -> SemanticGrouper:
    return SemanticGrouper.__new__(SemanticGrouper)


def _card(name, description, *skills):
    return {
        "name": name,
        "description": description,
        "skills": [
            {
                "id": skill_id,
                "name": skill_name,
                "description": f"Handles {skill_name} records and analysis",
                "tags": [skill_name.lower()],
                "examples": [],
            }
            for skill_id, skill_name in skills
        ],
    }


def _domain(card, domain_id="domain"):
    return {
        "semantic_domain_id": domain_id,
        "semantic_domain": card["description"],
        "agent_card": json.dumps(card),
        "dd_name": domain_id,
        "dd_namespace": "tests",
    }


def test_add_safe_fallback_preserves_old_capability():
    grouper = _grouper()
    old = _card("CommerceAgent", "Orders " * 20, ("orders", "Orders"))
    member = _card("PaymentsAgent", "Payments " * 20, ("payments", "Payments"))

    merged = grouper.safe_merge_agent_card(old, member)
    result = grouper.validate_semantic_coverage(
        old, merged, member_cards=[member], mode="incremental"
    )

    assert result["pass"] is True
    assert {skill["id"] for skill in merged["skills"]} == {"orders", "payments"}


def test_add_validation_requires_new_member_capability():
    grouper = _grouper()
    old = _card("CommerceAgent", "Orders " * 20, ("orders", "Orders"))
    member = _card("PaymentsAgent", "Payments " * 20, ("payments", "Payments"))

    result = grouper.validate_semantic_coverage(
        old, old, member_cards=[member], mode="incremental"
    )

    assert result["pass"] is False
    assert "payments" in result["missing_capabilities"]


def test_delete_card_does_not_restore_removed_unique_skill():
    grouper = _grouper()
    remaining = _card(
        "RemainingAgent",
        "Shared ordering and inventory " * 10,
        ("shared", "Shared"),
        ("inventory", "Inventory"),
    )
    removed = _card(
        "RemovedAgent", "Fraud-only operations " * 10, ("fraud", "Fraud")
    )
    old = grouper.safe_merge_agent_card(remaining, removed)

    rebuilt = grouper._deterministic_card_from_members([_domain(remaining)])
    result = grouper.validate_semantic_coverage(
        old, rebuilt, member_cards=[remaining], mode="decremental"
    )

    assert result["pass"] is True
    assert result["missing_requirements"] == []
    assert {skill["id"] for skill in rebuilt["skills"]} == {"shared", "inventory"}
    assert "fraud" not in rebuilt["description"].lower()


def test_delete_deterministic_card_retains_shared_and_remaining_skills():
    grouper = _grouper()
    first = _card(
        "RemainingAgent",
        "Ordering and shared records " * 10,
        ("shared", "Shared"),
        ("orders", "Orders"),
    )
    second = _card(
        "WarehouseAgent",
        "Inventory and shared records " * 10,
        ("shared", "Shared"),
        ("inventory", "Inventory"),
    )

    rebuilt = grouper._deterministic_card_from_members(
        [_domain(first, "first"), _domain(second, "second")]
    )

    assert {skill["id"] for skill in rebuilt["skills"]} == {
        "shared",
        "orders",
        "inventory",
    }


def test_validation_rejects_severe_description_shrink():
    grouper = _grouper()
    old = _card(
        "CommerceAgent",
        "Complete commerce ordering, fulfillment, returns, and reporting. " * 8,
        ("orders", "Orders"),
    )
    candidate = _card("CommerceAgent", "Orders only.", ("orders", "Orders"))

    result = grouper.validate_semantic_coverage(old, candidate)

    assert result["pass"] is False
    assert "description_severe_shrink" in result["missing_requirements"]


def test_single_remaining_member_reconcile_projects_card_without_llm():
    remaining = _card(
        "InventoryAgent",
        "Inventory availability and warehouse operations " * 8,
        ("inventory", "Inventory"),
    )
    old = _card(
        "OldGroupAgent",
        "Inventory and removed fraud operations " * 8,
        ("inventory", "Inventory"),
        ("fraud", "Fraud"),
    )

    class GroupClient:
        updated = None

        def get_semantic_group_by_id(self, _group_id):
            return {
                "data": {
                    "id": "group-1",
                    "group_name": "OldGroupAgent",
                    "description": old["description"],
                    "agent_card": json.dumps(old),
                    "version": "1",
                }
            }

        def get_relations_by_group_id(self, _group_id):
            return {"data": [{"sd_id": "remaining"}]}

        def update_semantic_group(self, group_id, semantic_group):
            self.updated = (group_id, semantic_group)

    class DomainClient:
        def get_semantic_domain_by_id(self, _domain_id):
            return {"data": _domain(remaining, "remaining")}

    grouper = _grouper()
    grouper.semantic_group_client = GroupClient()
    grouper.semantic_domain_client = DomainClient()
    grouper.vector_client = None
    grouper.collection_name = "semantic_groups"
    grouper.consolidate_semantic_domains_into_semantic_group = lambda **_: (
        (_ for _ in ()).throw(AssertionError("LLM must not be called"))
    )

    result = grouper.reconcile_group_metadata("group-1")

    assert result["status"] == "success"
    persisted = json.loads(grouper.semantic_group_client.updated[1].agent_card)
    assert persisted == remaining
