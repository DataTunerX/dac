import { describe, expect, it } from "vitest"

import { parseHistoryThink } from "./history-think"

describe("parseHistoryThink", () => {
  it("extracts DAC progress frames into progressList", () => {
    const parsed = parseHistoryThink(
      [
        '[[DAC_PROGRESS]] {"event":"routing_plan_ready","agent_id":"RoutingAgent","message":"plan ready"}',
        '[[DAC_PROGRESS]] {"event":"task_started","agent_id":"ExpertAgent","message":"working"}',
      ].join("\n")
    )

    expect(parsed.reasoning).toBe("")
    expect(parsed.progressList).toHaveLength(2)
    expect(parsed.progressList[0]?.event).toBe("routing_plan_ready")
    expect(parsed.progressList[1]?.agent_id).toBe("ExpertAgent")
  })

  it("preserves non-frame text as reasoning", () => {
    const parsed = parseHistoryThink(
      [
        "step 1",
        '[[DAC_PROGRESS]] {"event":"task_started","message":"working"}',
        "step 2",
      ].join("\n")
    )

    expect(parsed.reasoning).toBe("step 1\nstep 2")
    expect(parsed.progressList).toHaveLength(1)
  })

  it("keeps malformed progress frames in reasoning", () => {
    const parsed = parseHistoryThink('[[DAC_PROGRESS]] {"event": ')

    expect(parsed.reasoning).toBe('[[DAC_PROGRESS]] {"event":')
    expect(parsed.progressList).toHaveLength(0)
  })

  it("extracts execution-flow frames into executionFlowList without mixing into progress", () => {
    const parsed = parseHistoryThink(
      [
        '[[DAC_PROGRESS]] {"event":"routing_plan_ready","agent_id":"RoutingAgent"}',
        '[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"own-1-user-agent-t1","turn":1,"stage":"pre_exec","agent":"user-agent","role":"initiator","task":"lookup","result":"U001"}',
        "plain reasoning",
      ].join("\n")
    )

    expect(parsed.progressList).toHaveLength(1)
    expect(parsed.progressList[0]?.event).toBe("routing_plan_ready")
    expect(parsed.executionFlowList).toHaveLength(1)
    expect(parsed.executionFlowList[0]?.execution_id).toBe("own-1-user-agent-t1")
    expect(parsed.reasoning).toBe("plain reasoning")
  })

  it("keeps last payload per execution_id so history matches live upsert", () => {
    const parsed = parseHistoryThink(
      [
        '[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"own-1-order-agent-t1","turn":1,"stage":"pre_exec","agent":"order-agent","role":"initiator","task":"lookup","result":"ok","parent_execution_id":null}',
        '[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"pre-2-order-agent-t1","turn":1,"stage":"pre_exec","agent":"order-agent","role":"delegatee","task":"query","result":"ok","delegated_by":"user-agent"}',
        '[[DAC_EXECUTION_FLOW]] {"schema_version":"v1","execution_id":"own-1-order-agent-t1","turn":1,"stage":"pre_exec","agent":"order-agent","role":"initiator","task":"lookup","result":"ok","parent_execution_id":"pre-2-order-agent-t1","delegated_by":"user-agent"}',
      ].join("\n"),
    )

    expect(parsed.executionFlowList).toHaveLength(2)
    const own = parsed.executionFlowList.find((t) => t.execution_id === "own-1-order-agent-t1")
    expect(own?.parent_execution_id).toBe("pre-2-order-agent-t1")
    expect(own?.delegated_by).toBe("user-agent")
  })
})
