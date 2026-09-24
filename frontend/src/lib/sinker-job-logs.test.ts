import { describe, expect, it } from "vitest"

import { canViewSinkerJobLogs, consumeJobLogSse } from "@/lib/sinker-job-logs"

describe("canViewSinkerJobLogs", () => {
  it("shows the button while the sync job has not finished", () => {
    expect(canViewSinkerJobLogs("NotReady")).toBe(true)
    expect(canViewSinkerJobLogs("Syncing")).toBe(true)
    expect(canViewSinkerJobLogs("")).toBe(true)
    expect(canViewSinkerJobLogs(undefined)).toBe(true)
  })

  it("hides the button after the deployment is done or being deleted", () => {
    expect(canViewSinkerJobLogs("Ready")).toBe(false)
    expect(canViewSinkerJobLogs("Active")).toBe(false)
    expect(canViewSinkerJobLogs("Deleting")).toBe(false)
  })
})

describe("consumeJobLogSse", () => {
  it("joins a line that arrives in two chunks", async () => {
    const events: Array<{ event: string; data: string }> = []
    const raw = ["event: log\ndata: hel", "lo world\n\n"]
    await consumeJobLogSse(chunked(raw), (event) => events.push(event))
    expect(events).toEqual([{ event: "log", data: "hello world" }])
  })

  it("emits log lines and ignores comments", async () => {
    const raw = ": keep-alive\nevent: meta\ndata: pod-1\n\nevent: log\ndata: hello\n\nevent: end\ndata: closed\n\n"
    const events: Array<{ event: string; data: string }> = []
    await consumeJobLogSse(streamOf(raw), (event) => events.push(event))
    expect(events).toEqual([
      { event: "meta", data: "pod-1" },
      { event: "log", data: "hello" },
      { event: "end", data: "closed" },
    ])
  })
})

function streamOf(text: string): ReadableStream<Uint8Array> {
  return chunked([text])
}

function chunked(parts: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part))
      controller.close()
    },
  })
}
