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

/**
 * Fields that are transport plumbing rather than anything a reader wants.
 * Everything else in a progress payload is worth showing.
 */
const PLUMBING_FIELDS = new Set([
  "schema_version",
  "run_id",
  "user_id",
  "task_id",
  "agent_id",
  "agent",
  "layer",
  "event",
  "message",
  "task",
])

/**
 * Substantive fields: the planning and reasoning text the agents actually
 * produce. These render inline, as wrapped blocks, because they are the point
 * of the log -- a planner thought truncated to one line is not worth showing.
 * Order here is the order they appear in.
 */
const PRIMARY_FIELDS: readonly string[] = [
  "planner_thought",
  "plan_outline",
  "plan_tasks_summary",
  "dependency_summary",
  "phase_order_hint",
  "strategy_human",
  "current_task",
  "step_query",
  "query_preview",
  "original_query",
  "best_path",
  "selected_root",
  "plan_tasks_agents",
  "parallel_agents",
  "downstream_agents",
  "execution_order",
  "context_from",
  "selection_reason",
  "skill_candidates",
  "root_plans",
  "route_path_details",
  "answer_preview",
  "attempt_detail",
]

/** Readable labels; anything unlisted falls back to its raw key. */
const FIELD_LABELS: Record<string, string> = {
  planner_thought: "规划思路",
  plan_outline: "执行计划",
  plan_tasks_summary: "任务列表",
  dependency_summary: "阶段依赖",
  phase_order_hint: "阶段顺序",
  strategy_human: "路由策略",
  current_task: "当前任务",
  step_query: "步骤查询",
  query_preview: "查询",
  original_query: "原始问题",
  best_path: "最佳路径",
  selected_root: "选定根节点",
  plan_tasks_agents: "任务分配",
  parallel_agents: "并行智能体",
  downstream_agents: "下游智能体",
  execution_order: "执行顺序",
  context_from: "上下文来源",
  step: "步骤",
  max_steps: "最大步数",
  phase: "阶段",
  total_phases: "总阶段数",
  task_count: "任务数",
  agent_count: "智能体数",
  phase_count: "阶段数",
  ok_count: "成功数",
  round: "轮次",
  retry_count: "重试次数",
  max_retries: "最大重试",
  result_chars: "结果长度",
  answer_chars: "回答长度",
  task_status: "任务状态",
  task_agent: "执行智能体",
  status: "状态",
  mode: "模式",
  strategy: "策略",
  route_paths: "路由路径数",
  selected_skill: "选中技能",
  selection_reason: "选择理由",
  selection_score: "匹配分数",
  candidate_count: "候选数量",
  skill_candidates: "候选技能",
  skill_name: "技能",
  skill_status: "技能状态",
  skill_attempts: "尝试次数",
  attempt_statuses: "各次尝试状态",
  skill_query: "技能查询",
  reason_code: "原因码",
  elapsed_ms: "耗时(ms)",
  answer_preview: "回答预览",
  root_plans: "候选根节点",
  root_count: "候选数",
  route_path_details: "路由路径明细",
  selection_path: "选择方式",
  attempt_detail: "选择过程",
}

export interface ProgressDetail {
  key: string
  label: string
  value: string
  /** Long-form reasoning/planning text, rendered as a wrapped block. */
  primary: boolean
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return ""
  if (typeof value === "string") return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

/**
 * Flattens one progress payload into displayable detail rows.
 *
 * Layers disagree on shape: routing and the sg_* layers put their extras
 * directly on the payload, while sd_orchestrator and sd_expert nest them under
 * `extra`. Both are flattened here so the UI does not have to care.
 */
export function getProgressDetails(payload: ChatProgressPayload): ProgressDetail[] {
  const flat: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(payload)) {
    if (k === "extra" && v && typeof v === "object" && !Array.isArray(v)) {
      Object.assign(flat, v as Record<string, unknown>)
      continue
    }
    flat[k] = v
  }

  const details: ProgressDetail[] = []
  const seen = new Set<string>()

  const push = (key: string, primary: boolean) => {
    if (seen.has(key) || PLUMBING_FIELDS.has(key)) return
    const value = renderValue(flat[key])
    if (!value.trim()) return
    seen.add(key)
    details.push({ key, label: FIELD_LABELS[key] ?? key, value, primary })
  }

  for (const key of PRIMARY_FIELDS) push(key, true)
  for (const key of Object.keys(flat)) push(key, false)

  return details
}
