import { describe, it, expect } from "vitest"
import { parseChatSSELine } from "./parse-chat-sse"

describe("parseChatSSELine", () => {
  it("treats event: progress then data: json as progress", () => {
    const eventLine = parseChatSSELine("event: progress", "")
    expect(eventLine?.kind).toBe("event")
    expect(eventLine?.kind === "event" && eventLine.eventType).toBe("progress")

    const dataLine = parseChatSSELine('data: {"event":"routing_plan_ready"}', "progress")
    expect(dataLine?.kind).toBe("progress")
    expect(dataLine?.kind === "progress" && dataLine.payload.event).toBe("routing_plan_ready")
  })

  it("treats data: chunk (no prior progress event) as chunk", () => {
    const line = parseChatSSELine(
      'data: {"choices":[{"delta":{"content":"hi","reasoning_content":""}}]}',
      ""
    )
    expect(line?.kind).toBe("chunk")
    expect(line?.kind === "chunk" && line.content).toBe("hi")
    expect(line?.kind === "chunk" && line.reasoning).toBe("")
  })

  it("treats data: [DONE] as done", () => {
    const line = parseChatSSELine("data: [DONE]", "")
    expect(line?.kind).toBe("done")
  })

  it("after event: progress, next data: is progress not chunk", () => {
    const progressData = parseChatSSELine('data: {"event":"task_started"}', "progress")
    expect(progressData?.kind).toBe("progress")
    expect(progressData?.kind === "progress" && progressData.payload.event).toBe("task_started")
  })

  it("after any non-empty event, data: line is parsed as progress JSON", () => {
    const progress = parseChatSSELine('data: {"event":"routing_plan_ready"}', "routing_plan_ready")
    expect(progress?.kind).toBe("progress")
    expect(progress?.kind === "progress" && progress.payload.event).toBe("routing_plan_ready")
  })

  it("treats event: final_answer data as chunk with payload.text content", () => {
    const eventLine = parseChatSSELine("event: final_answer", "")
    expect(eventLine?.kind).toBe("event")
    expect(eventLine?.kind === "event" && eventLine.eventType).toBe("final_answer")

    const dataLine = parseChatSSELine(
      'data: {"schema_version":"v1","frame_type":"answer","event":"final_answer","payload":{"text":"这是最终回复","presentation":"text"}}',
      "final_answer"
    )
    expect(dataLine?.kind).toBe("chunk")
    expect(dataLine?.kind === "chunk" && dataLine.content).toBe("这是最终回复")
    expect(dataLine?.kind === "chunk" && dataLine.reasoning).toBe("")
  })

  it("final_answer data without payload.text falls back to chunk parsing", () => {
    const dataLine = parseChatSSELine(
      'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
      "final_answer"
    )
    expect(dataLine?.kind).toBe("chunk")
    expect(dataLine?.kind === "chunk" && dataLine.content).toBe("")
    expect(dataLine?.kind === "chunk" && dataLine.reasoning).toBe("")
  })

  it("progress payload with message and agent_id is parsed as progress", () => {
    const dataLine = parseChatSSELine(
      'data: {"event":"root_selected","message":"RoutingAgent selected root group X","agent_id":"RoutingAgent"}',
      "progress"
    )
    expect(dataLine?.kind).toBe("progress")
    expect(dataLine?.kind === "progress" && dataLine.payload.message).toBe("RoutingAgent selected root group X")
  })
})
