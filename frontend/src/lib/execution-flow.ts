/**
 * Execution Flow helpers: parse EF payloads, build the parent/child tree,
 * and flatten it for the table view. Mirrors skill-agent `execution_flow.py`.
 */

export const EXECUTION_FLOW_SCHEMA_VERSION = "v1"

export type ExecutionFlowRole = "initiator" | "delegatee" | string

export interface ExecutionFlowTask {
  schema_version: string
  execution_id: string
  turn: number
  stage: string
  agent: string
  role: ExecutionFlowRole
  task: string
  result: string
  reason: string
  parent_execution_id: string | null
  delegated_by: string | null
  run_id: string
  trace_id: string
  user_id: string
}

export interface ExecutionFlowTreeNode extends ExecutionFlowTask {
  children: ExecutionFlowTreeNode[]
}

export interface ExecutionFlowTableRow extends ExecutionFlowTask {
  indentLevel: number
}

export type ExecutionNodeStatus = "done" | "unfinished" | "unassigned" | "failed" | "success"

export const EMPTY_EXECUTION_FLOW: readonly ExecutionFlowTask[] = []

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") return value
  if (typeof value === "number" && Number.isFinite(value)) return String(value)
  return fallback
}

function asNullableString(value: unknown): string | null {
  if (value == null) return null
  const s = asString(value).trim()
  return s.length > 0 ? s : null
}

function asTurn(value: unknown): number | null {
  if (typeof value === "number" && Number.isInteger(value)) return value
  if (typeof value === "string" && value.trim() !== "") {
    const n = Number(value)
    if (Number.isInteger(n)) return n
  }
  return null
}

export function parseExecutionFlowTask(raw: unknown): ExecutionFlowTask | null {
  if (!raw || typeof raw !== "object") return null
  const data = raw as Record<string, unknown>
  if (asString(data.schema_version) !== EXECUTION_FLOW_SCHEMA_VERSION) return null

  const execution_id = asString(data.execution_id).trim()
  const turn = asTurn(data.turn)
  const stage = asString(data.stage).trim()
  const agent = asString(data.agent).trim()
  const role = asString(data.role).trim()
  const task = asString(data.task)
  if (!execution_id || turn == null || !stage || !agent || !role) return null

  return {
    schema_version: EXECUTION_FLOW_SCHEMA_VERSION,
    execution_id,
    turn,
    stage,
    agent,
    role,
    task,
    result: asString(data.result),
    reason: asString(data.reason),
    parent_execution_id: asNullableString(data.parent_execution_id),
    delegated_by: asNullableString(data.delegated_by),
    run_id: asString(data.run_id),
    trace_id: asString(data.trace_id),
    user_id: asString(data.user_id),
  }
}

/** Keep last payload per execution_id, preserving first-seen order. */
export function dedupeExecutionFlowTasks(tasks: readonly ExecutionFlowTask[]): ExecutionFlowTask[] {
  const lastById = new Map<string, ExecutionFlowTask>()
  const order: string[] = []
  for (const task of tasks) {
    if (!lastById.has(task.execution_id)) order.push(task.execution_id)
    lastById.set(task.execution_id, task)
  }
  return order.map((id) => lastById.get(id)!)
}

export function upsertExecutionFlowTask(
  list: readonly ExecutionFlowTask[],
  task: ExecutionFlowTask,
): ExecutionFlowTask[] {
  const idx = list.findIndex((item) => item.execution_id === task.execution_id)
  if (idx < 0) return [...list, task]
  const next = [...list]
  next[idx] = task
  return next
}

export function stageSortKey(stage: string): number {
  if (stage === "pre_exec") return 0
  if (stage === "turn_summary") return 10_000
  if (stage === "final_answer") return 10_001
  const mid = /^mid_exec_round_(\d+)$/.exec(stage)
  if (mid) return 100 + Number(mid[1])
  return 5_000
}

/** First time each execution_id appears in the incoming list (emit / execution order). */
export function firstSeenIndex(tasks: readonly ExecutionFlowTask[]): Map<string, number> {
  const index = new Map<string, number>()
  tasks.forEach((task, i) => {
    if (!index.has(task.execution_id)) index.set(task.execution_id, i)
  })
  return index
}

/**
 * Planner task id encoded in execution_id. Do not localeCompare the raw id:
 * SG ids are ``t1-pre-{agent}-{id}`` so "product" would sort before "user".
 */
export function plannerTaskSeq(executionId: string): number | null {
  const skill = /^(?:own|pre|mid-self|mid-del|none)-(\d+)(?:-|$)/.exec(executionId)
  if (skill) return Number(skill[1])
  const sg = /^t\d+-(?:pre|mid\d+)-.+-(\d+)$/.exec(executionId)
  if (sg) return Number(sg[1])
  return null
}

export function compareExecutionFlowTasks(
  a: ExecutionFlowTask,
  b: ExecutionFlowTask,
  orderIndex?: ReadonlyMap<string, number>,
): number {
  if (a.turn !== b.turn) return a.turn - b.turn
  const stageDiff = stageSortKey(a.stage) - stageSortKey(b.stage)
  if (stageDiff !== 0) return stageDiff
  const seqA = plannerTaskSeq(a.execution_id)
  const seqB = plannerTaskSeq(b.execution_id)
  if (seqA != null && seqB != null && seqA !== seqB) return seqA - seqB
  if (orderIndex) {
    const ai = orderIndex.get(a.execution_id)
    const bi = orderIndex.get(b.execution_id)
    if (ai != null && bi != null && ai !== bi) return ai - bi
  }
  return a.execution_id.localeCompare(b.execution_id)
}

export function groupByTurnAndStage(
  tasks: readonly ExecutionFlowTask[],
): Array<{ turn: number; stage: string; tasks: ExecutionFlowTask[] }> {
  const orderIndex = firstSeenIndex(tasks)
  const sorted = [...tasks].sort((a, b) => compareExecutionFlowTasks(a, b, orderIndex))
  const groups: Array<{ turn: number; stage: string; tasks: ExecutionFlowTask[] }> = []
  for (const task of sorted) {
    const last = groups[groups.length - 1]
    if (last && last.turn === task.turn && last.stage === task.stage) {
      last.tasks.push(task)
    } else {
      groups.push({ turn: task.turn, stage: task.stage, tasks: [task] })
    }
  }
  return groups
}

/** Build a forest from parent_execution_id only (Q12: no heuristic parent inference).
 * Sibling order is plan order (planner task id, then emit order). Do not group
 * every node of the delegating agent ahead of delegatees — a later own-task
 * (#3) must stay after an in-between delegation (#2). */
export function buildExecutionTree(tasks: readonly ExecutionFlowTask[]): ExecutionFlowTreeNode[] {
  // History persists both the original parent=null frame and the reparented
  // rewrite. Live upserts by execution_id; replay must do the same or the
  // first copy becomes an extra root (multiple 发起者 / extra summaries).
  const unique = dedupeExecutionFlowTasks(tasks)
  const orderIndex = firstSeenIndex(unique)
  const nodes: ExecutionFlowTreeNode[] = unique.map((task) => ({ ...task, children: [] }))
  const byId = new Map<string, ExecutionFlowTreeNode>()
  for (const node of nodes) byId.set(node.execution_id, node)

  const roots: ExecutionFlowTreeNode[] = []
  for (const node of nodes) {
    const parentId = node.parent_execution_id
    const parent = parentId ? byId.get(parentId) : undefined
    if (parent && parent !== node) parent.children.push(node)
    else roots.push(node)
  }
  return sortExecutionTree(roots, orderIndex)
}

function sortExecutionTree(
  nodes: ExecutionFlowTreeNode[],
  orderIndex: ReadonlyMap<string, number>,
): ExecutionFlowTreeNode[] {
  return [...nodes]
    .sort((a, b) => compareExecutionFlowTasks(a, b, orderIndex))
    .map((node) => ({ ...node, children: sortExecutionTree(node.children, orderIndex) }))
}

export interface ExecutionForestLayout {
  turnGroups: Array<{ turn: number; nodes: ExecutionFlowTreeNode[] }>
  finalAnswers: ExecutionFlowTreeNode[]
}

/**
 * Display order (Q8): each turn's execution tree first, that turn's
 * ``turn_summary`` at the tail, then all root ``final_answer`` nodes after
 * every turn. Nested summaries under a delegate wrapper stay in that subtree.
 */
export function layoutExecutionForest(
  roots: readonly ExecutionFlowTreeNode[],
): ExecutionForestLayout {
  const bodyByTurn = new Map<number, ExecutionFlowTreeNode[]>()
  const summaryByTurn = new Map<number, ExecutionFlowTreeNode[]>()
  const finalAnswers: ExecutionFlowTreeNode[] = []

  for (const node of roots) {
    if (node.stage === "final_answer") {
      finalAnswers.push(node)
      continue
    }
    if (node.stage === "turn_summary") {
      const list = summaryByTurn.get(node.turn) ?? []
      list.push(node)
      summaryByTurn.set(node.turn, list)
      continue
    }
    const list = bodyByTurn.get(node.turn) ?? []
    list.push(node)
    bodyByTurn.set(node.turn, list)
  }

  const turns = [...new Set([...bodyByTurn.keys(), ...summaryByTurn.keys()])].sort((a, b) => a - b)
  return {
    turnGroups: turns.map((turn) => ({
      turn,
      nodes: [...(bodyByTurn.get(turn) ?? []), ...(summaryByTurn.get(turn) ?? [])],
    })),
    finalAnswers,
  }
}

/** Depth-first pre-order flatten; table row order matches the tree layout. */
export function flattenTreeForTable(roots: readonly ExecutionFlowTreeNode[]): ExecutionFlowTableRow[] {
  const { turnGroups, finalAnswers } = layoutExecutionForest(roots)
  const ordered = [...turnGroups.flatMap((group) => group.nodes), ...finalAnswers]
  const rows: ExecutionFlowTableRow[] = []
  const walk = (nodes: readonly ExecutionFlowTreeNode[], indentLevel: number) => {
    for (const node of nodes) {
      const { children, ...task } = node
      rows.push({ ...task, indentLevel })
      if (children.length > 0) walk(children, indentLevel + 1)
    }
  }
  walk(ordered, 0)
  return rows
}

export function nodeStatusOf(task: ExecutionFlowTask): ExecutionNodeStatus {
  if (task.agent === "NONE") return "unassigned"
  if (task.stage === "turn_summary") {
    const result = task.result.trim().toLowerCase()
    if (result === "fail" || result === "failed") return "failed"
    if (result === "success" || result === "ok" || result === "done") return "success"
  }
  if (!task.result.trim()) return "unfinished"
  return "done"
}

export function stageLabel(stage: string): string {
  if (stage === "turn_summary") return "轮次总结"
  if (stage === "final_answer") return "最终答案"
  return stage
}

export function roleLabel(role: string): string {
  if (role === "delegatee") return "被委派"
  if (role === "initiator") return "发起者"
  return role
}

/**
 * The agent that started this run: first non-summary root initiator.
 * Peer own-tasks often arrive as extra roots (parent still null) while live.
 */
export function originAgentOf(tasks: readonly ExecutionFlowTask[]): string | null {
  for (const task of tasks) {
    if (task.stage === "turn_summary" || task.stage === "final_answer") continue
    if (task.role === "delegatee") continue
    if (task.parent_execution_id || task.delegated_by) continue
    if (!task.agent || task.agent === "NONE") continue
    return task.agent
  }
  return null
}

/**
 * Unified-tree role: protocol ``initiator`` is per-agent-layer, so a delegated
 * agent's own task is also tagged initiator. In the combined tree only the
 * originating agent's roots are 「发起者」.
 */
export function treeRoleLabel(task: ExecutionFlowTask, originAgent?: string | null): string {
  if (task.role === "delegatee") return "被委派"
  if (task.parent_execution_id || task.delegated_by) return "内部执行"
  if (task.role === "initiator" && originAgent && task.agent !== originAgent) return "内部执行"
  return roleLabel(task.role)
}

/** Markdown of the same processed tree the execution map panel renders. */
export function renderExecutionMapMarkdown(
  tasks: readonly ExecutionFlowTask[],
  isLive = false,
): string {
  const tree = buildExecutionTree(tasks)
  const forest = layoutExecutionForest(tree)
  const originAgent = originAgentOf(tasks)
  const runId = tasks[0]?.run_id?.trim() || ""
  const lines: string[] = ["# 执行地图", ""]
  if (runId) {
    lines.push(`Run ID: \`${runId}\``, "")
  }
  if (tree.length === 0) {
    lines.push("暂无执行记录", "")
    return lines.join("\n")
  }

  lines.push("- 起点 · 开始执行", "")
  for (const group of forest.turnGroups) {
    lines.push(`## 第 ${group.turn} 轮`, "")
    for (const node of group.nodes) {
      lines.push(...renderMapNodeMarkdown(node, originAgent, 0))
    }
    lines.push("")
  }
  if (forest.finalAnswers.length > 0) {
    lines.push("## 最终答案", "")
    for (const node of forest.finalAnswers) {
      lines.push(...renderMapNodeMarkdown(node, originAgent, 0))
    }
    lines.push("")
  }
  lines.push(
    isLive && forest.finalAnswers.length === 0
      ? "- 终点（生成中） · 等待最终答案"
      : "- 终点 · 执行结束",
    "",
  )
  return lines.join("\n")
}

function renderMapNodeMarkdown(
  node: ExecutionFlowTreeNode,
  originAgent: string | null,
  depth: number,
): string[] {
  const pad = "  ".repeat(depth)
  const agent = node.agent === "NONE" ? "未派发" : node.agent
  const delegated = node.delegated_by ? ` ← ${node.delegated_by}` : ""
  const reason = node.reason.trim() ? ` · 原因 ${node.reason.trim().replace(/\s+/g, " ")}` : ""
  const lines = [
    `${pad}- **${agent}** · ${treeRoleLabel(node, originAgent)} · ${stageLabel(node.stage)}${delegated}${reason}`,
  ]
  if (node.task.trim()) lines.push(...markdownField("问题", node.task, `${pad}  `))
  if (node.result.trim()) lines.push(...markdownField("答案", node.result, `${pad}  `))
  for (const child of node.children) {
    lines.push(...renderMapNodeMarkdown(child, originAgent, depth + 1))
  }
  return lines
}

function markdownField(label: string, text: string, indent: string): string[] {
  const parts = text.trim().split(/\r?\n/)
  return [`${indent}- ${label}：${parts[0]}`, ...parts.slice(1).map((line) => `${indent}  ${line}`)]
}
