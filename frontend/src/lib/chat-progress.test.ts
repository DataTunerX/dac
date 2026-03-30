import { describe, it, expect } from "vitest"
import { getProgressRowDisplay, shouldShowProgressItem } from "./chat-progress"

describe("getProgressRowDisplay", () => {
  it("returns event, agent, message from payload as-is", () => {
    const payload = {
      event: "root_selected",
      message: "RoutingAgent selected root group X",
      agent_id: "RoutingAgent",
    }
    const row = getProgressRowDisplay(payload)
    expect(row.event).toBe("root_selected")
    expect(row.agent).toBe("RoutingAgent")
    expect(row.message).toBe("RoutingAgent selected root group X")
  })

  it("prefers agent_id then agent", () => {
    expect(getProgressRowDisplay({ agent_id: "A" }).agent).toBe("A")
    expect(getProgressRowDisplay({ agent: "B" }).agent).toBe("B")
    expect(getProgressRowDisplay({ agent_id: "A", agent: "B" }).agent).toBe("A")
  })

  it("prefers message then task", () => {
    expect(getProgressRowDisplay({ message: "m" }).message).toBe("m")
    expect(getProgressRowDisplay({ task: "t" }).message).toBe("t")
    expect(getProgressRowDisplay({ message: "m", task: "t" }).message).toBe("m")
  })

  it("returns layer from payload", () => {
    expect(getProgressRowDisplay({ layer: "sg_orchestrator" }).layer).toBe("sg_orchestrator")
    expect(getProgressRowDisplay({ layer: "sg_expert" }).layer).toBe("sg_expert")
  })

  it("returns null for missing or empty fields", () => {
    const row = getProgressRowDisplay({})
    expect(row.agent).toBeNull()
    expect(row.layer).toBeNull()
    expect(row.event).toBeNull()
    expect(row.message).toBeNull()
  })

  it("trims whitespace", () => {
    const row = getProgressRowDisplay({
      agent: "  Agent  ",
      layer: "  sg_expert  ",
      event: "  task_started  ",
      message: "  msg  ",
    })
    expect(row.agent).toBe("Agent")
    expect(row.layer).toBe("sg_expert")
    expect(row.event).toBe("task_started")
    expect(row.message).toBe("msg")
  })
})

describe("shouldShowProgressItem", () => {
  it("hides final_answer_chunk", () => {
    expect(shouldShowProgressItem({ event: "final_answer_chunk" })).toBe(false)
    expect(shouldShowProgressItem({ event: "final_answer_chunk", agent_id: "RoutingAgent" })).toBe(false)
  })

  it("shows other events", () => {
    expect(shouldShowProgressItem({ event: "routing_final_answer_ready" })).toBe(true)
    expect(shouldShowProgressItem({ event: "group_final_answer_ready", message: "Final answer is ready" })).toBe(true)
    expect(shouldShowProgressItem({})).toBe(true)
  })
})
