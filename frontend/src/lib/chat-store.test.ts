import { beforeEach, describe, expect, it } from "vitest"
import {
  clearOptimisticRunId,
  markOptimisticRunId,
  safeUUID,
  shouldLoadHistoryForRunId,
  useChatStore,
} from "@/lib/chat-store"

describe("safeUUID", () => {
  it("does not throw when crypto.randomUUID is unavailable", () => {
    const original = globalThis.crypto
    Object.defineProperty(globalThis, "crypto", {
      configurable: true,
      value: undefined,
    })
    try {
      expect(() => safeUUID()).not.toThrow()
      expect(safeUUID()).toMatch(/^r_/)
    } finally {
      Object.defineProperty(globalThis, "crypto", {
        configurable: true,
        value: original,
      })
    }
  })
})

describe("shouldLoadHistoryForRunId", () => {
  beforeEach(() => {
    useChatStore.setState({ sessions: {} })
    clearOptimisticRunId("run-a")
    clearOptimisticRunId("run-b")
    clearOptimisticRunId("run-c")
  })

  it("loads when session is missing", () => {
    expect(shouldLoadHistoryForRunId("run-a")).toBe(true)
  })

  it("skips when session already has messages", () => {
    useChatStore.setState({
      sessions: {
        "run-a": {
          messages: [{ id: "1", role: "user", content: "hi" }],
          input: "",
          isLoading: false,
          isStreaming: false,
          streamProgressList: [],
          streamStartedAt: null,
          thinkingElapsedSec: null,
        },
      },
    })
    expect(shouldLoadHistoryForRunId("run-a")).toBe(false)
  })

  it("skips optimistic run ids", () => {
    markOptimisticRunId("run-b")
    expect(shouldLoadHistoryForRunId("run-b")).toBe(false)

    useChatStore.setState({
      sessions: {
        "run-b": {
          messages: [],
          input: "",
          isLoading: false,
          isStreaming: false,
          streamProgressList: [],
          streamStartedAt: null,
          thinkingElapsedSec: null,
        },
      },
    })
    expect(shouldLoadHistoryForRunId("run-b")).toBe(false)
  })

  it("skips while session is streaming", () => {
    useChatStore.setState({
      sessions: {
        "run-c": {
          messages: [],
          input: "",
          isLoading: true,
          isStreaming: true,
          streamProgressList: [],
          streamStartedAt: null,
          thinkingElapsedSec: null,
        },
      },
    })
    expect(shouldLoadHistoryForRunId("run-c")).toBe(false)
  })
})
