/**
 * SSE line parsing for chat stream: event type, progress JSON, chunk delta, [DONE].
 * Caller tracks lastEventType; any non-empty event means the next data line is progress JSON,
 * EXCEPT for `final_answer` events which carry the complete answer in `payload.text`.
 */

import type { ChatProgressPayload } from "@/lib/api-types"

export type ParseSSELineResult =
  | { kind: "event"; eventType: string }
  | { kind: "progress"; payload: ChatProgressPayload }
  | { kind: "chunk"; content: string; reasoning: string }
  | { kind: "done" }
  | null

interface ChatCompletionChunkPayload {
  choices?: Array<{ delta?: { content?: string; reasoning_content?: string } }>
}

/** Payload shape for `event: final_answer` SSE events from the backend. */
interface FinalAnswerPayload {
  payload?: { text?: string; presentation?: string }
  [key: string]: unknown
}

/**
 * 需要从 payload.text 中提取最终回复内容的事件类型。
 * 这些事件的 data 行不是 progress，而是包含完整回复文本。
 */
const FINAL_ANSWER_EVENTS = new Set(["final_answer"])

export function parseChatSSELine(
  line: string,
  lastEventType: string
): ParseSSELineResult {
  const trimmed = line.trim()
  if (trimmed === "") return null

  if (trimmed.startsWith("event:")) {
    const eventType = trimmed.replace(/^event:\s*/, "").trim()
    return { kind: "event", eventType }
  }

  if (trimmed.startsWith("data:")) {
    const dataStr = trimmed.replace(/^data:\s*/, "")
    if (dataStr === "[DONE]") return { kind: "done" }

    // final_answer 事件：从 payload.text 提取完整回复内容
    if (FINAL_ANSWER_EVENTS.has(lastEventType)) {
      return parseFinalAnswerDataLine(dataStr)
    }

    if (lastEventType.length > 0) {
      return parseProgressDataLine(dataStr)
    }
    return parseChunkDataLine(dataStr)
  }

  return null
}

/**
 * 解析 `event: final_answer` 的 data 行，提取 payload.text 作为 content chunk。
 * 如果解析失败或没有 payload.text，回退到普通 chunk 解析。
 */
function parseFinalAnswerDataLine(dataStr: string): ParseSSELineResult {
  try {
    const data = JSON.parse(dataStr) as FinalAnswerPayload
    const text = data.payload?.text
    if (typeof text === "string" && text.length > 0) {
      return { kind: "chunk", content: text, reasoning: "" }
    }
    // 没有 payload.text，尝试作为普通 chunk 解析（兼容 finish_reason: "stop" 等）
    return parseChunkDataLine(dataStr)
  } catch {
    return null
  }
}

function parseProgressDataLine(dataStr: string): ParseSSELineResult {
  try {
    const payload = JSON.parse(dataStr) as ChatProgressPayload
    return { kind: "progress", payload }
  } catch {
    return null
  }
}

function parseChunkDataLine(dataStr: string): ParseSSELineResult {
  try {
    const data = JSON.parse(dataStr) as ChatCompletionChunkPayload
    const delta = data.choices?.[0]?.delta ?? {}
    const content = delta.content ?? ""
    const reasoning = delta.reasoning_content ?? ""
    return { kind: "chunk", content, reasoning }
  } catch {
    return null
  }
}
