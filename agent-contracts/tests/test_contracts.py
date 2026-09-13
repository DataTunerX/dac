from __future__ import annotations

from copy import deepcopy

import pytest
from agent_contracts import (
    MAX_INLINE_TASK_CONTEXT_BYTES,
    PROTOCOL_VERSION,
    AnswerContract,
    AnswerRequirement,
    ArtifactReference,
    CapabilityManifest,
    CapabilityReportV2,
    ContributorDescriptor,
    ExecutionBudget,
    ExecutionEventV2,
    ExecutionState,
    ExpectedOutput,
    ParticipantTask,
    SchemaConflictError,
    SchemaDataValidationError,
    SchemaDescriptor,
    SchemaRegistry,
    TaskNode,
    TaskOutput,
    TaskResult,
    adapt_legacy_capability_response,
    core_schema_registry,
    validate_capability_report,
    validate_dag,
    validate_event_transition,
    validate_task_result,
)
from pydantic import ValidationError


def capability_payload() -> dict:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "agent_id": "agent://museum",
        "agent_name": "Museum-Agent",
        "capability_manifest_version": "manifest-1",
        "runtime_status_ref": {"readiness_generation": 2},
        "lead": {
            "eligible": True,
            "ownership": "primary",
            "owned_requirements": ["r1"],
            "reason": "Owns the museum collection corpus.",
        },
        "contributions": [
            {
                "contribution_id": "museum-lookup",
                "requirement_ids": ["r1"],
                "operations": ["lookup"],
                "produced_output_schemas": ["dac.claim-evidence/v1"],
                "data_domains": ["wwybsj"],
                "required_tools": ["tdb_query"],
            }
        ],
        "fit_score": 0.94,
    }


def participant_task() -> ParticipantTask:
    return ParticipantTask(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id="collab-1",
        task_id="task-1",
        objective="Return the supported claim.",
        operation="retrieve",
        expected_outputs=[
            ExpectedOutput(name="claims", schema_id="dac.claim-evidence/v1")
        ],
    )


def valid_claims() -> list[dict]:
    return [
        {
            "claim": "The object is registered as jade.",
            "source_id": "museum:42",
            "status": "Established",
        }
    ]


def test_messages_require_protocol_version() -> None:
    payload = capability_payload()
    payload.pop("protocol_version")
    with pytest.raises(ValidationError, match="protocol_version"):
        CapabilityReportV2.model_validate(payload)


def test_compatible_minor_and_unknown_optional_field_are_accepted() -> None:
    payload = capability_payload()
    payload["protocol_version"] = "multi-agent-v2.7"
    payload["future_optional_field"] = {"safe": True}
    report = CapabilityReportV2.model_validate(payload)
    assert report.protocol_version == "multi-agent-v2.7"
    assert not hasattr(report, "future_optional_field")

    payload["protocol_version"] = " multi-agent-v2 "
    assert (
        CapabilityReportV2.model_validate(payload).protocol_version == PROTOCOL_VERSION
    )


@pytest.mark.parametrize("version", ["multi-agent-v1", "multi-agent-v3", "v2", ""])
def test_unsupported_or_malformed_protocol_versions_fail(version: str) -> None:
    payload = capability_payload()
    payload["protocol_version"] = version
    with pytest.raises(ValidationError, match="protocol"):
        CapabilityReportV2.model_validate(payload)


def test_capability_report_is_intersected_with_runtime_manifest() -> None:
    report = CapabilityReportV2.model_validate(capability_payload())
    manifest = CapabilityManifest(
        agent_id="agent://museum",
        manifest_version="manifest-1",
        lead_supported=True,
        operations=["lookup"],
        output_schemas=["dac.claim-evidence/v1"],
        data_domains=["wwybsj"],
        ready_tools=[],
    )
    issues = validate_capability_report(report, manifest)
    assert [(issue.code, issue.path) for issue in issues] == [
        ("undeclared_capability", "contributions[0].required_tools")
    ]


def test_legacy_capability_adapter_is_explicitly_degraded() -> None:
    report = adapt_legacy_capability_response(
        {"can_handle": True, "confidence": 0.8, "reason": "legacy"},
        agent_id="agent://legacy",
        agent_name="Legacy-Agent",
    )
    assert report.degraded_legacy_adapter is True
    assert report.lead.eligible is True
    assert "legacy" in report.capability_manifest_version
    assert report.limitations


def test_schema_registry_is_immutable_and_validates_data() -> None:
    registry = SchemaRegistry()
    descriptor = SchemaDescriptor(
        schema_id="example.text/v1",
        owner="test",
        schema={"type": "string", "minLength": 2},
    )
    assert registry.register(descriptor).schema_digest
    registry.register(descriptor)
    registry.validate_data("example.text/v1", "ok")
    with pytest.raises(SchemaDataValidationError, match="shorter"):
        registry.validate_data("example.text/v1", "x")
    with pytest.raises(SchemaConflictError):
        registry.register(
            SchemaDescriptor(
                schema_id="example.text/v1",
                owner="test",
                schema={"type": "integer"},
            )
        )


def test_core_claim_schema_requires_source_and_status() -> None:
    registry = core_schema_registry()
    registry.validate_data("dac.claim-evidence/v1", valid_claims())
    broken = deepcopy(valid_claims())
    del broken[0]["source_id"]
    with pytest.raises(SchemaDataValidationError, match="source_id"):
        registry.validate_data("dac.claim-evidence/v1", broken)


def test_dag_rejects_cycle_scope_and_unknown_schema() -> None:
    tasks = [
        TaskNode(
            task_id="a",
            objective="first",
            operation="retrieve",
            assigned_agent_id="http://outside",
            assigned_agent_name="Outside-Agent",
            execution_target="participant",
            depends_on=["b"],
            expected_outputs=[ExpectedOutput(name="x", schema_id="unknown.data/v1")],
        ),
        TaskNode(
            task_id="b",
            objective="second",
            operation="synthesize",
            assigned_agent_id="http://lead",
            assigned_agent_name="Lead-Agent",
            execution_target="local",
            depends_on=["a"],
            expected_outputs=[
                ExpectedOutput(name="claims", schema_id="dac.claim-evidence/v1")
            ],
        ),
    ]
    issues = validate_dag(
        tasks,
        contributors=[],
        schema_registry=core_schema_registry(),
        budget=ExecutionBudget(),
        lead_agent_id="http://lead",
    )
    assert {issue.code for issue in issues} >= {
        "unknown_output_schema",
        "agent_out_of_scope",
        "dag_cycle",
    }


def test_dag_rejects_unadvertised_schema_and_missing_answer_producer() -> None:
    contributor = ContributorDescriptor(
        agent_id="http://history",
        agent_name="History-Agent",
        agent_url="http://history",
        capability_manifest_version="manifest-1",
        readiness_generation=1,
        allowed_operations=["retrieve"],
        allowed_output_schemas=["example.text/v1"],
    )
    task = TaskNode(
        task_id="a",
        objective="claims",
        operation="retrieve",
        assigned_agent_id="http://history",
        assigned_agent_name="History-Agent",
        execution_target="participant",
        expected_outputs=[
            ExpectedOutput(name="claims", schema_id="dac.claim-evidence/v1")
        ],
    )
    answer = AnswerContract(
        protocol_version=PROTOCOL_VERSION,
        requirements=[
            AnswerRequirement(component_id="final-claims", description="claims")
        ],
    )
    issues = validate_dag(
        [task],
        contributors=[contributor],
        schema_registry=core_schema_registry(),
        budget=ExecutionBudget(),
        answer_contract=answer,
    )
    assert {issue.code for issue in issues} == {
        "participant_schema_not_advertised",
        "missing_answer_producer",
    }


def test_task_result_validation_binds_ids_names_and_schema() -> None:
    task = participant_task()
    digest = core_schema_registry().resolve("dac.claim-evidence/v1").schema_digest
    result = TaskResult(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id=task.collaboration_id,
        task_id=task.task_id,
        agent_name="Museum-Agent",
        status="success",
        outputs=[
            TaskOutput(
                name="claims",
                schema_id="dac.claim-evidence/v1",
                schema_digest=digest,
                data=valid_claims(),
            )
        ],
    )
    assert validate_task_result(result, task, core_schema_registry()) == []

    wrong = result.model_copy(update={"task_id": "other", "outputs": []})
    assert {
        issue.code
        for issue in validate_task_result(wrong, task, core_schema_registry())
    } == {
        "task_id_mismatch",
        "missing_mandatory_output",
    }


def test_terminal_failure_requires_a_normalized_error() -> None:
    task = participant_task()
    with pytest.raises(ValidationError, match="must include an error code"):
        TaskResult(
            protocol_version=PROTOCOL_VERSION,
            collaboration_id=task.collaboration_id,
            task_id=task.task_id,
            agent_name="Museum-Agent",
            status="failed",
        )


def test_event_state_machine_rejects_invalid_transition() -> None:
    valid = ExecutionEventV2(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id="collab-1",
        sequence=0,
        event_type="received",
        current_state=ExecutionState.RECEIVED,
    )
    assert validate_event_transition(valid) == []
    invalid = ExecutionEventV2(
        protocol_version=PROTOCOL_VERSION,
        collaboration_id="collab-1",
        sequence=1,
        event_type="completed",
        previous_state=ExecutionState.RECEIVED,
        current_state=ExecutionState.COMPLETED,
    )
    assert [issue.code for issue in validate_event_transition(invalid)] == [
        "invalid_state_transition"
    ]


def test_oversized_inline_task_context_is_rejected() -> None:
    with pytest.raises(ValidationError, match="inline task context"):
        ParticipantTask(
            protocol_version=PROTOCOL_VERSION,
            collaboration_id="collab-large",
            task_id="large",
            objective="large input",
            operation="transform",
            inputs={"payload": "x" * (MAX_INLINE_TASK_CONTEXT_BYTES + 1)},
            expected_outputs=[
                ExpectedOutput(name="claims", schema_id="dac.claim-evidence/v1")
            ],
        )


def test_dag_rejects_undeclared_operation_and_exhausted_attempt() -> None:
    contributor = ContributorDescriptor(
        agent_id="http://history",
        agent_name="History-Agent",
        agent_url="http://history",
        capability_manifest_version="manifest-1",
        readiness_generation=1,
        allowed_operations=["retrieve"],
        allowed_output_schemas=["dac.claim-evidence/v1"],
    )
    task = TaskNode(
        task_id="task-1",
        objective="interpret the evidence",
        operation="interpret",
        assigned_agent_id="http://history",
        assigned_agent_name="History-Agent",
        execution_target="participant",
        expected_outputs=[
            ExpectedOutput(name="claims", schema_id="dac.claim-evidence/v1")
        ],
        attempt=2,
    )
    issues = validate_dag(
        [task],
        contributors=[contributor],
        schema_registry=core_schema_registry(),
        budget=ExecutionBudget(max_attempts_per_task=2),
    )
    assert {issue.code for issue in issues} == {
        "attempt_budget_exhausted",
        "participant_operation_not_advertised",
    }


def test_artifacts_reject_inline_data_uris() -> None:
    with pytest.raises(ValidationError, match="referenced"):
        ArtifactReference(
            artifact_id="inline",
            uri="data:application/octet-stream;base64,AA==",
        )
