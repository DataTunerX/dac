from routing_agent.server import RoutingAgent

EF = '[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"own-1"}'
PROGRESS = '[[DAC_PROGRESS]] {"event":"routing_plan_ready"}'


def test_is_execution_flow_frame():
    assert RoutingAgent.is_execution_flow_frame(EF) is True
    assert RoutingAgent.is_execution_flow_frame(PROGRESS) is False
    assert RoutingAgent.is_execution_flow_frame("hello") is False


def test_execution_flow_is_internal_and_must_be_checked_first():
    """EF frames also match is_internal_dac_frame; callers must check EF first."""
    assert RoutingAgent.is_internal_dac_frame(EF) is True
    assert RoutingAgent.is_progress_frame(EF) is False


def test_strip_execution_flow_lines_does_not_touch_progress_or_answer():
    mixed = "\n".join([EF, PROGRESS, "hello", EF])
    assert RoutingAgent.strip_execution_flow_lines(mixed) == f"{PROGRESS}\nhello"


def test_peel_execution_flow_text_keeps_prefix_body():
    clean, ef = RoutingAgent.peel_execution_flow_text("answer text " + EF)
    assert clean == "answer text"
    assert ef is not None and ef.lstrip().startswith("[[DAC_EXECUTION_FLOW]] ")
    whole_clean, whole_ef = RoutingAgent.peel_execution_flow_text(EF)
    assert whole_clean == ""
    assert whole_ef is not None
