import type { ChatProgressPayload } from "@/lib/api-types"
import {
  dedupeExecutionFlowTasks,
  parseExecutionFlowTask,
  type ExecutionFlowTask,
} from "@/lib/execution-flow"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"

const DAC_PROGRESS_PREFIX = "[[DAC_PROGRESS]] "
const DAC_EXECUTION_FLOW_PREFIX = "[[DAC_EXECUTION_FLOW]] "

export interface ParsedHistoryThink {
  reasoning: string
  progressList: ChatProgressPayload[]
  executionFlowList: ExecutionFlowTask[]
}

/**
 * History `think` may contain raw `[[DAC_PROGRESS]]` and `[[DAC_EXECUTION_FLOW]]`
 * frames persisted by routing-agent (keyed by run_id in data-services).
 * Extract them so historical messages render like live streaming.
 */
export function parseHistoryThink(rawThink: string | undefined | null): ParsedHistoryThink {
  const text = typeof rawThink === "string" ? rawThink : ""
  if (!text.trim()) {
    return { reasoning: "", progressList: [], executionFlowList: [] }
  }

  const reasoningLines: string[] = []
  const progressList: ChatProgressPayload[] = []
  const executionFlowList: ExecutionFlowTask[] = []

  for (const line of text.split(/\r?\n/)) {
    const trimmedStart = line.trimStart()
    if (trimmedStart.startsWith(DAC_PROGRESS_PREFIX)) {
      const payloadText = trimmedStart.slice(DAC_PROGRESS_PREFIX.length).trim()
      if (!payloadText) continue
      try {
        progressList.push(JSON.parse(payloadText) as ChatProgressPayload)
      } catch {
        reasoningLines.push(line)
      }
      continue
    }
    if (trimmedStart.startsWith(DAC_EXECUTION_FLOW_PREFIX)) {
      const payloadText = trimmedStart.slice(DAC_EXECUTION_FLOW_PREFIX.length).trim()
      if (!payloadText) continue
      try {
        const parsed = parseExecutionFlowTask(JSON.parse(payloadText) as unknown)
        if (parsed) {
          executionFlowList.push(parsed)
        } else {
          reasoningLines.push(line)
        }
      } catch {
        reasoningLines.push(line)
      }
      continue
    }
    reasoningLines.push(line)
  }

  return {
    reasoning: stripModelLeakTags(reasoningLines.join("\n").trim()),
    progressList,
    executionFlowList: dedupeExecutionFlowTasks(executionFlowList),
  }
}
