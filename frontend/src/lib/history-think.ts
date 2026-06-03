import type { ChatProgressPayload } from "@/lib/api-types"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"

const DAC_PROGRESS_PREFIX = "[[DAC_PROGRESS]] "

export interface ParsedHistoryThink {
  reasoning: string
  progressList: ChatProgressPayload[]
}

/**
 * History `think` may contain raw `[[DAC_PROGRESS]] {json}` frames persisted by the backend.
 * Extract them into structured progress rows so historical messages render like live streaming.
 */
export function parseHistoryThink(rawThink: string | undefined | null): ParsedHistoryThink {
  const text = typeof rawThink === "string" ? rawThink : ""
  if (!text.trim()) {
    return { reasoning: "", progressList: [] }
  }

  const reasoningLines: string[] = []
  const progressList: ChatProgressPayload[] = []

  for (const line of text.split(/\r?\n/)) {
    const trimmedStart = line.trimStart()
    if (!trimmedStart.startsWith(DAC_PROGRESS_PREFIX)) {
      reasoningLines.push(line)
      continue
    }

    const payloadText = trimmedStart.slice(DAC_PROGRESS_PREFIX.length).trim()
    if (!payloadText) continue

    try {
      const payload = JSON.parse(payloadText) as ChatProgressPayload
      progressList.push(payload)
    } catch {
      reasoningLines.push(line)
    }
  }

  return {
    reasoning: stripModelLeakTags(reasoningLines.join("\n").trim()),
    progressList,
  }
}
