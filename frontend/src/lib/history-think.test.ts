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
})
