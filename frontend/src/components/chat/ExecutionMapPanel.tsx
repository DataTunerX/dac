"use client"

/**
 * Execution map dialog: top 70% tree/graph + bottom 30% DFS table (Q1).
 * All tree nodes stay expanded by default so hierarchy is scannable. Task and
 * answer stay one line until the user clicks 展开. Live updates stick to the
 * bottom only when the user is already there (Q9).
 */
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type UIEvent,
} from "react"
import {
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Flag,
  GitBranch,
  Play,
  X,
  XCircle,
} from "lucide-react"
import { Dialog, DialogClose, DialogContent, DialogTitle } from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import {
  buildExecutionTree,
  flattenTreeForTable,
  layoutExecutionForest,
  nodeStatusOf,
  originAgentOf,
  stageLabel,
  treeRoleLabel,
  type ExecutionFlowTableRow,
  type ExecutionFlowTask,
  type ExecutionFlowTreeNode,
  type ExecutionNodeStatus,
} from "@/lib/execution-flow"

const TABLE_PREVIEW_MAX = 80
const TABLE_PREVIEW_KEYS = new Set<keyof ExecutionFlowTask>(["task", "result", "reason"])

const TABLE_COLUMNS: Array<{ key: keyof ExecutionFlowTask; label: string; minWidth: string }> = [
  { key: "execution_id", label: "execution_id", minWidth: "14rem" },
  { key: "turn", label: "turn", minWidth: "3.5rem" },
  { key: "stage", label: "stage", minWidth: "8rem" },
  { key: "agent", label: "agent", minWidth: "8rem" },
  { key: "role", label: "role", minWidth: "6rem" },
  { key: "task", label: "task", minWidth: "14rem" },
  { key: "result", label: "result", minWidth: "14rem" },
  { key: "reason", label: "reason", minWidth: "12rem" },
  { key: "parent_execution_id", label: "parent_execution_id", minWidth: "12rem" },
  { key: "delegated_by", label: "delegated_by", minWidth: "8rem" },
]

export function ExecutionMapPanel({
  open,
  onOpenChange,
  tasks,
  isLive = false,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  tasks: readonly ExecutionFlowTask[]
  isLive?: boolean
}) {
  const tree = useMemo(() => buildExecutionTree(tasks), [tasks])
  const forest = useMemo(() => layoutExecutionForest(tree), [tree])
  const rows = useMemo(() => flattenTreeForTable(tree), [tree])
  const originAgent = useMemo(() => originAgentOf(tasks), [tasks])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [splitRatio, setSplitRatio] = useState(0.7)
  const [expandedText, setExpandedText] = useState<Set<string>>(() => new Set())
  const treeScrollRef = useRef<HTMLDivElement>(null)
  const tableBodyRef = useRef<HTMLDivElement>(null)
  const splitRef = useRef<HTMLDivElement>(null)
  const stickTreeBottomRef = useRef(true)
  const stickTableBottomRef = useRef(true)

  // Q9: follow the live tail only while the user is already at the bottom.
  const onTreeScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget
    stickTreeBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }, [])
  const onTableScroll = useCallback((event: UIEvent<HTMLDivElement>) => {
    const el = event.currentTarget
    stickTableBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48
  }, [])
  useEffect(() => {
    if (!isLive) return
    const treeEl = treeScrollRef.current
    if (treeEl && stickTreeBottomRef.current) treeEl.scrollTop = treeEl.scrollHeight
    const tableEl = tableBodyRef.current
    if (tableEl && stickTableBottomRef.current) tableEl.scrollTop = tableEl.scrollHeight
  }, [isLive, rows.length, tree])

  const selectNode = useCallback((id: string) => {
    setSelectedId(id)
    const root = tableBodyRef.current
    if (!root) return
    const el = Array.from(root.querySelectorAll<HTMLElement>("[data-ef-row]")).find(
      (node) => node.dataset.efRow === id,
    )
    el?.scrollIntoView({ block: "nearest", behavior: "smooth" })
  }, [])

  const toggleCollapsed = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleText = useCallback((id: string, field: "task" | "result") => {
    const key = `${id}:${field}`
    setExpandedText((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const onSplitterPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.preventDefault()
    const container = splitRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const onMove = (moveEvent: PointerEvent) => {
      const y = moveEvent.clientY - rect.top
      const next = Math.min(0.85, Math.max(0.4, y / rect.height))
      setSplitRatio(next)
    }
    const onUp = () => {
      window.removeEventListener("pointermove", onMove)
      window.removeEventListener("pointerup", onUp)
    }
    window.addEventListener("pointermove", onMove)
    window.addEventListener("pointerup", onUp)
  }

  const runId = tasks[0]?.run_id || ""

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="w-[min(95vw,1400px)] h-[min(90vh,900px)] max-w-none flex flex-col p-0 gap-0 overflow-hidden">
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-line shrink-0">
          <DialogTitle className="flex items-center gap-2 text-base">
            <GitBranch className="w-4 h-4 text-cta" />
            执行地图
            <span className="text-sm font-normal text-content-muted">({tasks.length})</span>
            {isLive ? <span className="text-[11px] text-cta font-normal">实时更新中</span> : null}
          </DialogTitle>
          <div className="flex items-center gap-3">
            {runId ? (
              <span className="text-[11px] font-mono text-content-muted truncate max-w-[28rem]" title={runId}>
                {runId}
              </span>
            ) : null}
            <DialogClose asChild>
              <button
                type="button"
                className="h-8 w-8 inline-flex items-center justify-center rounded-md text-content-muted hover:bg-surface-muted hover:text-content"
                aria-label="关闭执行地图"
              >
                <X className="w-4 h-4" />
              </button>
            </DialogClose>
          </div>
        </div>

        <div ref={splitRef} className="flex-1 min-h-0 flex flex-col">
          <div
            ref={treeScrollRef}
            className="min-h-0 overflow-auto px-5 py-4"
            style={{ flex: splitRatio }}
            onScroll={onTreeScroll}
          >
            {tree.length === 0 ? (
              <p className="text-sm text-content-muted">暂无执行记录</p>
            ) : (
              <div>
                <FlowAnchor kind="start" />
                <div className="ml-4 border-l-2 border-dashed border-cta/50 pl-5 py-3 space-y-3">
                  {forest.turnGroups.map((group) => (
                    <div key={group.turn} className="space-y-1.5">
                      <div className="text-[11px] font-medium text-content-muted">第 {group.turn} 轮</div>
                      {group.nodes.map((node) => (
                        <TreeNodeView
                          key={node.execution_id}
                          node={node}
                          originAgent={originAgent}
                          selectedId={selectedId}
                          collapsed={collapsed}
                          expandedText={expandedText}
                          onSelect={selectNode}
                          onToggle={toggleCollapsed}
                          onToggleText={toggleText}
                        />
                      ))}
                    </div>
                  ))}
                  {forest.finalAnswers.length > 0 ? (
                    <div className="space-y-1.5">
                      <div className="text-[11px] font-medium text-content-muted">最终答案</div>
                      {forest.finalAnswers.map((node) => (
                        <TreeNodeView
                          key={node.execution_id}
                          node={node}
                          originAgent={originAgent}
                          selectedId={selectedId}
                          collapsed={collapsed}
                          expandedText={expandedText}
                          onSelect={selectNode}
                          onToggle={toggleCollapsed}
                          onToggleText={toggleText}
                        />
                      ))}
                    </div>
                  ) : null}
                </div>
                <FlowAnchor kind="end" pending={isLive && forest.finalAnswers.length === 0} />
              </div>
            )}
          </div>

          <div
            role="separator"
            aria-orientation="horizontal"
            className="h-2 shrink-0 cursor-row-resize flex items-center justify-center bg-surface-muted/40 hover:bg-surface-muted"
            onPointerDown={onSplitterPointerDown}
          >
            <div className="w-12 h-1 rounded-full bg-line" />
          </div>

          <div className="min-h-0 flex flex-col border-t border-line" style={{ flex: 1 - splitRatio }}>
            <div className="px-5 py-2 text-[11px] text-content-muted shrink-0">
              表格顺序与树上深度优先遍历一致
            </div>
            <div
              ref={tableBodyRef}
              className="flex-1 min-h-0 overflow-auto px-3 pb-3"
              onScroll={onTableScroll}
            >
              <table className="w-full text-[11px] border-collapse min-w-[72rem]">
                <thead className="sticky top-0 bg-surface z-10">
                  <tr>
                    <th className="text-left font-medium text-content-muted px-2 py-1.5 border-b border-line w-8">#</th>
                    {TABLE_COLUMNS.map((col) => (
                      <th
                        key={col.key}
                        className="text-left font-medium text-content-muted px-2 py-1.5 border-b border-line whitespace-nowrap"
                        style={{ minWidth: col.minWidth }}
                      >
                        {col.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => (
                    <TableRowView
                      key={row.execution_id}
                      row={row}
                      index={index}
                      selected={selectedId === row.execution_id}
                      onSelect={selectNode}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function TreeNodeView({
  node,
  originAgent,
  selectedId,
  collapsed,
  expandedText,
  onSelect,
  onToggle,
  onToggleText,
}: {
  node: ExecutionFlowTreeNode
  originAgent: string | null
  selectedId: string | null
  collapsed: Set<string>
  expandedText: Set<string>
  onSelect: (id: string) => void
  onToggle: (id: string) => void
  onToggleText: (id: string, field: "task" | "result") => void
}) {
  const status = nodeStatusOf(node)
  const hasChildren = node.children.length > 0
  const isCollapsed = collapsed.has(node.execution_id)
  const selected = selectedId === node.execution_id

  return (
    <div>
      <div className="flex items-start gap-2">
        <AgentNodeIcon status={status} unassigned={node.agent === "NONE"} />
        <div
          className={cn(
            "min-w-0 flex-1 rounded-lg border px-2.5 py-1.5 cursor-pointer transition-colors shadow-sm",
            selected ? "border-cta bg-cta/5" : "border-line bg-surface hover:bg-surface-muted/40",
          )}
          onClick={() => onSelect(node.execution_id)}
        >
          <div className="flex flex-wrap items-center gap-1.5 text-[12px] leading-5">
            {hasChildren ? (
              <button
                type="button"
                className="h-5 w-5 shrink-0 inline-flex items-center justify-center rounded text-content-muted hover:bg-surface-muted"
                onClick={(e) => {
                  e.stopPropagation()
                  onToggle(node.execution_id)
                }}
                aria-label={isCollapsed ? "展开子树" : "折叠子树"}
              >
                {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </button>
            ) : null}
            <span className="font-medium text-content">{node.agent === "NONE" ? "未派发" : node.agent}</span>
            <span className="text-content-muted">· {treeRoleLabel(node, originAgent)}</span>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-surface-muted text-content-muted">
              {stageLabel(node.stage)}
            </span>
            {node.delegated_by ? (
              <span className="text-[11px] text-content-muted">← {node.delegated_by}</span>
            ) : null}
            {node.reason.trim() ? (
              <span className="text-[11px] text-content-muted" title={node.reason}>
                · 原因 {node.reason.trim()}
              </span>
            ) : null}
            {hasChildren && isCollapsed ? (
              <span className="text-[11px] text-content-muted">展开内部执行 ({node.children.length})</span>
            ) : null}
          </div>
          <ExpandableLine
            label="问题"
            text={node.task}
            expanded={expandedText.has(`${node.execution_id}:task`)}
            onToggle={() => onToggleText(node.execution_id, "task")}
          />
          <ExpandableLine
            label="答案"
            text={node.result}
            expanded={expandedText.has(`${node.execution_id}:result`)}
            onToggle={() => onToggleText(node.execution_id, "result")}
            muted
          />
        </div>
      </div>
      {hasChildren && !isCollapsed ? (
        <div className="ml-4 mt-1.5 space-y-1.5 border-l-2 border-cta/40 pl-5">
          {node.children.map((child) => (
            <TreeNodeView
              key={child.execution_id}
              node={child}
              originAgent={originAgent}
              selectedId={selectedId}
              collapsed={collapsed}
              expandedText={expandedText}
              onSelect={onSelect}
              onToggle={onToggle}
              onToggleText={onToggleText}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function FlowAnchor({ kind, pending = false }: { kind: "start" | "end"; pending?: boolean }) {
  const isStart = kind === "start"
  return (
    <div className="flex items-center gap-2.5">
      <div
        className={cn(
          "h-8 w-8 shrink-0 rounded-full inline-flex items-center justify-center border-2",
          isStart
            ? "bg-cta text-white border-cta"
            : pending
              ? "bg-surface-muted text-content-muted border-dashed border-line"
              : "bg-emerald-600 text-white border-emerald-600",
        )}
        aria-hidden
      >
        {isStart ? <Play className="h-3.5 w-3.5 fill-current" /> : <Flag className="h-3.5 w-3.5" />}
      </div>
      <div>
        <div className="text-[12px] font-medium text-content">{isStart ? "起点" : pending ? "终点（生成中）" : "终点"}</div>
        <div className="text-[11px] text-content-muted">{isStart ? "开始执行" : pending ? "等待最终答案" : "执行结束"}</div>
      </div>
    </div>
  )
}

function AgentNodeIcon({
  status,
  unassigned = false,
}: {
  status: ExecutionNodeStatus
  unassigned?: boolean
}) {
  return (
    <div className="relative h-8 w-8 shrink-0 mt-0.5" title="智能体节点">
      <div
        className={cn(
          "h-8 w-8 rounded-lg inline-flex items-center justify-center border shadow-sm",
          unassigned
            ? "bg-amber-50 border-amber-200 text-amber-700"
            : status === "failed"
              ? "bg-rose-50 border-rose-200 text-rose-700"
              : status === "unfinished"
                ? "bg-surface-muted border-line text-content-muted"
                : "bg-cta/10 border-cta/30 text-cta",
        )}
      >
        <Bot className="h-4 w-4" />
      </div>
      <span className="absolute -right-1 -bottom-1 rounded-full bg-surface p-px leading-none">
        <StatusIcon status={status} />
      </span>
    </div>
  )
}

function ExpandableLine({
  label,
  text,
  expanded,
  onToggle,
  muted = false,
}: {
  label: string
  text: string
  expanded: boolean
  onToggle: () => void
  muted?: boolean
}) {
  const textRef = useRef<HTMLParagraphElement>(null)
  const [overflows, setOverflows] = useState(false)

  useLayoutEffect(() => {
    const el = textRef.current
    if (!el) return
    if (expanded) {
      setOverflows(true)
      return
    }
    const check = () => setOverflows(el.scrollWidth > el.clientWidth + 1)
    check()
    const observer = new ResizeObserver(check)
    observer.observe(el)
    return () => observer.disconnect()
  }, [text, expanded])

  if (!text.trim()) return null

  const showToggle = expanded || overflows

  return (
    <div className="mt-0.5 min-w-0">
      {expanded ? (
        <div className="min-w-0">
          <div className="flex items-start gap-1.5 min-w-0">
            <span className="w-8 shrink-0 pt-px text-[11px] text-content-muted">{label}</span>
            <p
              className={cn(
                "min-w-0 flex-1 text-[12px] whitespace-pre-wrap break-words",
                muted ? "text-content-muted" : "text-content",
              )}
            >
              {text}
            </p>
          </div>
          <button
            type="button"
            className="ml-9 mt-0.5 text-[11px] text-cta hover:underline"
            onClick={(e) => {
              e.stopPropagation()
              onToggle()
            }}
          >
            收起
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="w-8 shrink-0 text-[11px] text-content-muted">{label}</span>
          <p
            ref={textRef}
            className={cn(
              "min-w-0 flex-1 truncate text-[12px]",
              muted ? "text-content-muted" : "text-content",
            )}
            title={overflows ? text : undefined}
          >
            {text}
          </p>
          {showToggle ? (
            <button
              type="button"
              className="shrink-0 text-[11px] text-cta hover:underline"
              onClick={(e) => {
                e.stopPropagation()
                onToggle()
              }}
            >
              展开
            </button>
          ) : null}
        </div>
      )}
    </div>
  )
}

function TableRowView({
  row,
  index,
  selected,
  onSelect,
}: {
  row: ExecutionFlowTableRow
  index: number
  selected: boolean
  onSelect: (id: string) => void
}) {
  return (
    <tr
      data-ef-row={row.execution_id}
      className={cn("cursor-pointer", selected ? "bg-cta/10" : "hover:bg-surface-muted/50")}
      onClick={() => onSelect(row.execution_id)}
    >
      <td className="px-2 py-1.5 border-b border-line/70 text-content-muted align-top">{index + 1}</td>
      {TABLE_COLUMNS.map((col) => {
        const raw = formatCell(row[col.key])
        const display = TABLE_PREVIEW_KEYS.has(col.key) ? truncateCell(raw, TABLE_PREVIEW_MAX) : raw
        const padded = col.key === "execution_id" ? `${"\u00a0".repeat(row.indentLevel * 2)}${display}` : display
        return (
          <td
            key={col.key}
            className={cn(
              "px-2 py-1.5 border-b border-line/70 text-content align-top font-mono",
              TABLE_PREVIEW_KEYS.has(col.key)
                ? "whitespace-nowrap overflow-hidden text-ellipsis max-w-[16rem]"
                : "whitespace-pre-wrap break-words max-w-[20rem]",
            )}
            title={raw || undefined}
          >
            {padded || <span className="text-content-muted">—</span>}
          </td>
        )
      })}
    </tr>
  )
}

function formatCell(value: ExecutionFlowTask[keyof ExecutionFlowTask]): string {
  if (value == null) return ""
  return String(value)
}

function truncateCell(text: string, max: number): string {
  const compact = text.replace(/\s+/g, " ").trim()
  if (compact.length <= max) return compact
  return `${compact.slice(0, max)}...`
}

function StatusIcon({ status }: { status: ExecutionNodeStatus }) {
  if (status === "unfinished") return <span className="inline-block w-3.5 h-3.5 rounded-full border border-content-muted" />
  if (status === "unassigned") return <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
  if (status === "failed") return <XCircle className="w-3.5 h-3.5 text-rose-600" />
  if (status === "success") return <Check className="w-3.5 h-3.5 text-emerald-600" />
  return <Check className="w-3.5 h-3.5 text-emerald-600" />
}
