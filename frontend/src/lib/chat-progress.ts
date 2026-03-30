import type { ChatProgressPayload } from "@/lib/api-types"

/** Progress events that carry no useful status text; we hide them to avoid noisy empty rows. */
const HIDDEN_PROGRESS_EVENTS = new Set(["final_answer_chunk"])

export function shouldShowProgressItem(payload: ChatProgressPayload): boolean {
  const event = payload.event
  if (typeof event !== "string" || event.trim() === "") return true
  return !HIDDEN_PROGRESS_EVENTS.has(event.trim())
}

export interface ProgressRowDisplay {
  agent: string | null
  layer: string | null
  event: string | null
  message: string | null
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0
}

function firstOf(...values: Array<unknown>): string | null {
  for (const v of values) {
    if (nonEmptyString(v)) return (v as string).trim()
  }
  return null
}

/**
 * Builds display fields for one progress row from the API payload.
 * Order for display: agent (leftmost) → layer (e.g. sg_expert / sg_orchestrator) → event → message.
 */
export function getProgressRowDisplay(payload: ChatProgressPayload): ProgressRowDisplay {
  return {
    agent: firstOf(payload.agent_id, payload.agent) ?? null,
    layer: firstOf(payload.layer) ?? null,
    event: firstOf(payload.event) ?? null,
    message: firstOf(payload.message, payload.task) ?? null,
  }
}
