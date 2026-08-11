"use client"

import React, { useState, useRef, useEffect, useMemo, useCallback, Fragment } from "react"
import type { ReactNode } from "react"
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  BrainCircuit,
  XCircle,
  AlertTriangle,
} from "lucide-react"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { cn } from "@/lib/utils"
import { getProgressRowDisplay, shouldShowProgressItem } from "@/lib/chat-progress"
import type { ChatProgressPayload } from "@/lib/api-types"
import { EMPTY_PROGRESS } from "@/components/chat/chat-message-types"

// 抽到模块级，避免在 ThinkingProcess 内定义导致每次父组件重渲染（如滚动）时被当作新组件 remount、state 丢失
function chevronIcon(open: boolean, className = "w-4 h-4 text-content-muted shrink-0") {
  return open ? <ChevronDown className={className} /> : <ChevronRight className={className} />
}
function CollapsibleSectionInner({
  defaultOpen,
  summary,
  children,
  className,
  summaryClassName,
}: {
  defaultOpen: boolean
  summary: (open: boolean) => ReactNode
  children: ReactNode
  className: string
  summaryClassName: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <details
      className={className}
      open={open}
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
    >
      <summary className={summaryClassName}>{summary(open)}</summary>
      {children}
    </details>
  )
}

/** Remount when defaultOpen changes instead of syncing via useEffect. */
function CollapsibleSection({
  defaultOpen = false,
  summary,
  children,
  className = "",
  summaryClassName = "list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none rounded-md -ml-1 px-1 hover:bg-surface-muted transition-colors",
}: {
  defaultOpen?: boolean
  summary: (open: boolean) => ReactNode
  children: ReactNode
  className?: string
  summaryClassName?: string
}) {
  return (
    <CollapsibleSectionInner
      key={defaultOpen ? "open" : "closed"}
      defaultOpen={defaultOpen}
      summary={summary}
      className={className}
      summaryClassName={summaryClassName}
    >
      {children}
    </CollapsibleSectionInner>
  )
}

function Chip({
  children,
  tone = "neutral",
}: {
  children: ReactNode
  tone?: "neutral" | "success"
}) {
  return (
    <span
      className={
        tone === "success"
          ? "inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200"
          : "inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-surface-muted text-content border border-line"
      }
    >
      {children}
    </span>
  )
}

function AgentChip({ name }: { name: string }) {
  return (
    <Chip>
      <Bot className="w-3 h-3 text-content-muted" />
      <span className="text-[11px] leading-5">{name}</span>
    </Chip>
  )
}

function StatusMark({ state }: { state: "idle" | "running" | "done" | "warn" | "fail" }) {
  if (state === "running") return <Loader2 className="w-3.5 h-3.5 animate-spin text-content-muted" />
  if (state === "done") return <Check className="w-3.5 h-3.5 text-emerald-600" />
  if (state === "warn") return <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
  if (state === "fail") return <XCircle className="w-3.5 h-3.5 text-rose-600" />
  return <span className="w-3.5 h-3.5 inline-block" />
}

function SummaryRow({
  title,
  right,
  tone = "default",
  icon,
}: {
  title: ReactNode
  right?: ReactNode
  tone?: "default" | "success"
  icon?: ReactNode
}) {
  return (
    <div
      className={
        tone === "success"
          ? "flex items-center gap-2 py-1 text-emerald-900"
          : "flex items-center gap-2 py-1 text-content"
      }
    >
      {icon !== undefined ? (
        icon
      ) : (
        <ChevronRight className="w-4 h-4 text-content-muted shrink-0 group-open/section:rotate-90 transition-transform" />
      )}
      <div className="flex-1 text-[12px] font-medium">{title}</div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  )
}

function ShimmerLine({ w = "w-full" }: { w?: string }) {
  return (
    <div className={`relative overflow-hidden h-3 rounded bg-surface-active/60 ${w}`}>
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white to-transparent [animation:dacShimmer_1.5s_ease-in-out_infinite] will-change-transform" />
    </div>
  )
}

// Note: we no longer parse planning logs out of assistant `content` on the frontend.
// The backend is responsible for emitting thought process via `reasoning_content`
// (and conversation history may use `think`, mapped to `reasoning_content` in this page).

// 简单的思维链/多任务折叠组件
// Note: "isThinking" is different from the overall message streaming state.
// We only show the spinner while the assistant is still "thinking" (i.e., before answer content starts).
export const ThinkingProcess = ({
  content,
  isThinking,
  isLive,
  progressList = EMPTY_PROGRESS,
  startedAt,
  elapsedSec,
}: {
  content: string
  isThinking?: boolean
  isLive?: boolean
  /** Progress events shown under "思考中" (cards with event · agent · message). */
  progressList?: readonly ChatProgressPayload[]
  /** Session-level stream start (ms); survives conversation switches. */
  startedAt?: number | null
  /** Frozen duration (seconds) after stream ends. */
  elapsedSec?: number | null
}) => {
  const [userExpanded, setUserExpanded] = useState(false)
  const wasThinkingOrLiveRef = useRef(false)
  useEffect(() => {
    const now = Boolean(isLive || isThinking)
    if (now && !wasThinkingOrLiveRef.current) setUserExpanded(true)
    wasThinkingOrLiveRef.current = now
  }, [isThinking, isLive])
  const [duration, setDuration] = useState(() =>
    elapsedSec != null && elapsedSec > 0 ? elapsedSec : 0
  )
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null)
  const [openProgressSteps, setOpenProgressSteps] = useState<string[]>([])
  const previousProgressCountRef = useRef(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const scrollThinkingToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: "auto" })
  }, [])
  useEffect(() => {
    setOpenProgressSteps((prev) => {
      const validOpenSteps = prev.filter((value) => {
        const index = Number(value)
        return Number.isInteger(index) && index >= 0 && index < progressList.length
      })

      if (progressList.length <= previousProgressCountRef.current) {
        previousProgressCountRef.current = progressList.length
        return validOpenSteps
      }

      const next = [...validOpenSteps]
      for (let i = previousProgressCountRef.current; i < progressList.length; i += 1) {
        next.push(String(i))
      }
      previousProgressCountRef.current = progressList.length
      return next
    })
  }, [progressList.length])

  // Wait until the panel and accordion content finish laying out, then pin to bottom.
  useEffect(() => {
    if (!userExpanded || !scrollRef.current) return

    let raf1 = 0
    let raf2 = 0

    raf1 = window.requestAnimationFrame(() => {
      raf2 = window.requestAnimationFrame(() => {
        scrollThinkingToBottom()
      })
    })

    return () => {
      window.cancelAnimationFrame(raf1)
      window.cancelAnimationFrame(raf2)
    }
  }, [userExpanded, isThinking, isLive, content, progressList.length, scrollThinkingToBottom])

  const parsed = useMemo(() => {
    const raw = (content || "").replace(/\r\n/g, "\n")
    const lines = raw.split("\n")
    // 后端顺序：plan 的 allTask 可能有多个 task；每个 task 可能独立再带 allTask（如子智能体），按返回顺序解析，不猜测
    const allTasksHeaderRe = /^All Tasks:\s*$/i
    const planTaskLineRe = /^\[(\d+)\]:\s*(.*?)(?:\s*-\s*\[([^\]]+)\])?\s*$/
    const taskHeaderRe = /^Task\s*\[(\d+)\]:\s*(.*)$/i
    const stepRe = /^step\s+(\d+)\/(\d+):\s*(.*)$/i
    const answerStartRe = /^answer:\s*(.*)$/i
    const reasonStartRe = /^reason:\s*(.*)$/i
    const headingRe = /^===+\s*(.*?)\s*===+\s*$/
    const completeRe = /^[✅✔]/
    // Replan / retry markers that are often emitted as plain lines (not === headings).
    const retryLineRe = /(计划执行遇到问题.*?正在进行第\s*(\d+)\s*次重试|正在进行第\s*(\d+)\s*次重试)/i
    const failureAnalysisRe = /^失败分析[:：]/i
    const replanLineRe = /(重新规划成功|重新规划失败|新计划如下|重新规划)/i
    const maxRetryRe = /^⚠️\s*已达到最大重试次数/i

    const planById = new Map<string, { id: string; text: string; agent?: string }>()
    const planBlocks: Array<{ title: string; items: Array<{ id: string; text: string; agent?: string }>; parentTaskKey?: string }> = []
    let currentPlanBlock: { title: string; items: Array<{ id: string; text: string; agent?: string }>; parentTaskKey?: string } | null = null
    let pendingPlanTitle: string | null = null
    type ExecNode =
      | { type: "plan"; planBlockIndex: number }
      | { type: "flow"; flowIndex: number }
      | { type: "marker"; text: string }
      | { type: "task"; taskKey: string }
    const execNodes: ExecNode[] = []
    type ExecTask = {
      key: string
      id: string
      text?: string
      agent?: string
      query?: string
      steps: { idx: number; total: number; text: string }[]
      answers: string[]
      inProgressAnswer?: string
      logs: string[]
      _cap?: { mode: "answer"; buf: string[] } | null
    }

    const execByKey = new Map<string, ExecTask>()
    const execOrder: string[] = []
    const execKeySeq = new Map<string, number>() // `${planEpoch}:${id}` -> seq
    const completions: string[] = []
    const flow: { title: string; body: string; kind: "replan" | "retry" | "analysis" }[] = []
    const timeline: { title: string; body: string }[] = []

    type TimelineSection = { title: string; buf: string[] }
    // Use a ref-like wrapper to avoid TS control-flow issues on captured variables.
    const currentSectionRef: { current: TimelineSection | null } = { current: null }
    const currentBucketRef: { current: "timeline" | "flow" } = { current: "timeline" }
    const currentKindRef: { current: "replan" | "retry" | "analysis" | null } = { current: null }
    const currentEntryIndexRef: { current: number | null } = { current: null }
    let inPlan = false
    let currentTaskKey: string | null = null
    let planEpoch = 0
    // Backend-driven phase markers:
    // We only reveal sections after their corresponding markers appear in logs.
    let planStarted = false
    let execStarted = false
    let flowStarted = false
    let timelineStarted = false

    const flushSection = () => {
      const s = currentSectionRef.current
      if (!s) return
      const body = s.buf.join("\n").trim()
      const idx = currentEntryIndexRef.current
      if (idx != null) {
        if (currentBucketRef.current === "flow") {
          const x = flow[idx]
          if (x) x.body = body
        } else {
          const x = timeline[idx]
          if (x) x.body = body
        }
      } else if (s.title || body) {
        // Fallback (should rarely happen): push as a new entry.
        if (currentBucketRef.current === "flow") {
          const kind = currentKindRef.current || "replan"
          flow.push({ title: s.title, body, kind })
        } else {
          timeline.push({ title: s.title, body })
        }
      }
      currentSectionRef.current = null
      currentKindRef.current = null
      currentBucketRef.current = "timeline"
      currentEntryIndexRef.current = null
    }

    const startSection = (
      bucket: "timeline" | "flow",
      title: string,
      firstLine?: string,
      kind?: "replan" | "retry" | "analysis",
    ) => {
      if (bucket === "flow") flowStarted = true
      if (bucket === "timeline") timelineStarted = true
      // Flush any in-progress answer capture.
      if (currentTaskKey) {
        const exec = ensureExec(currentTaskKey)
        const cap = exec._cap
        if (cap && cap.mode === "answer") {
          const body = cap.buf.join("\n").trim()
          if (body) exec.answers.push(body)
        }
        exec._cap = null
      }
      flushSection()
      currentSectionRef.current = { title: title || "日志", buf: [] }
      currentBucketRef.current = bucket
      currentKindRef.current = bucket === "flow" ? kind || "replan" : null
      if (bucket === "flow") {
        const idx =
          flow.push({ title: title || "事件", body: "", kind: kind || "replan" }) - 1
        currentEntryIndexRef.current = idx
        execNodes.push({ type: "flow", flowIndex: idx })
      } else {
        const idx = timeline.push({ title: title || "日志", body: "" }) - 1
        currentEntryIndexRef.current = idx
      }
      if (firstLine) currentSectionRef.current.buf.push(firstLine)
      inPlan = false
      currentTaskKey = null
    }

    const ensureExec = (key: string, displayId?: string): ExecTask => {
      const existing = execByKey.get(key)
      if (existing) return existing
      const created: ExecTask = {
        key,
        id: displayId || key,
        steps: [] as { idx: number; total: number; text: string }[],
        answers: [] as string[],
        logs: [] as string[],
        _cap: null as { mode: "answer"; buf: string[] } | null,
      }
      execByKey.set(key, created)
      execOrder.push(key)
      return created
    }

    for (const line of lines) {
      const t = line.trim()
      if (!t) {
        currentSectionRef.current?.buf.push("")
        if (currentTaskKey) {
          const exec = ensureExec(currentTaskKey)
          exec.logs.push(line)
          const cap = exec._cap
          if (cap && cap.mode === "answer") cap.buf.push("")
        }
        continue
      }

      if (allTasksHeaderRe.test(t)) {
        // Treat All Tasks as an execution node (initial plan / replan plan).
        // 层级：若当前在某个 task 下（如子智能体【智能体 N】里的 All Tasks），记录 parentTaskKey 便于前端嵌套渲染
        flushSection()
        planEpoch += 1
        const isReplan = planStarted && planBlocks.length > 0
        const pending = (pendingPlanTitle || "").trim()
        const title =
          pending && /(新计划如下)/.test(pending)
            ? "重规划"
            : pending || (isReplan ? "重规划" : "任务")
        pendingPlanTitle = null
        const parentTaskKey = currentTaskKey ?? undefined
        currentPlanBlock = { title, items: [], parentTaskKey }
        const planBlockIndex = planBlocks.length
        planBlocks.push(currentPlanBlock)
        execNodes.push({ type: "plan", planBlockIndex })
        planById.clear()
        inPlan = true
        planStarted = true
        currentTaskKey = null
        continue
      }

      const h = t.match(headingRe)
      if (h) {
        const title = (h[1] || "日志").trim()
        // If backend says "新计划如下", we treat it as the upcoming plan-block title.
        if (/(新计划如下)/.test(title)) {
          pendingPlanTitle = title
          // This marker is now represented by the plan block itself; don't create an extra node.
          flushSection()
        } else {
          execNodes.push({ type: "marker", text: title })
          execStarted = true
          flushSection()
        }
        continue
      }

      // Plain-text markers: retry / replan / failure analysis.
      if (failureAnalysisRe.test(t)) {
        startSection("flow", "失败分析", line, "analysis")
        continue
      }
      const rm = t.match(retryLineRe)
      if (rm) {
        // Backend marker line; show as a plain node (no fold + no "暂无输出").
        execNodes.push({ type: "marker", text: t })
        execStarted = true
        flushSection()
        continue
      }
      if (replanLineRe.test(t) && !inPlan) {
        // Avoid starting a new section for every plan task line; `All Tasks:` will handle that.
        // If this line is a "新计划如下" marker, promote it to the next plan-block title.
        if (/(新计划如下)/.test(t)) {
          pendingPlanTitle = t
          flushSection()
        } else {
          execNodes.push({ type: "marker", text: t })
          execStarted = true
          flushSection()
        }
        continue
      }

      if (maxRetryRe.test(t)) {
        execNodes.push({ type: "marker", text: t })
        execStarted = true
        flushSection()
        continue
      }

      const p = t.match(planTaskLineRe)
      if (p && inPlan) {
        const [, id, text, agent] = p
        // Always take the latest value (replanning can update the same id).
        const item = { id, text: text.trim(), agent: agent?.trim() }
        planById.set(id, item)
        if (currentPlanBlock) currentPlanBlock.items.push(item)
        currentSectionRef.current?.buf.push(line)
        continue
      }

      const th = t.match(taskHeaderRe)
      if (th) {
        execStarted = true
        // Flush previous task's answer capture (if any).
        if (currentTaskKey) {
          const prev = ensureExec(currentTaskKey)
          const cap = prev._cap
          if (cap && cap.mode === "answer") {
            const body = cap.buf.join("\n").trim()
            if (body) prev.answers.push(body)
          }
          prev._cap = null
        }

        const [, id, rest0] = th
        const rest = rest0.trim()
        const mAgent = rest.match(/^(.*?)(?:\s*-\s*\[([^\]]+)\])?\s*;?\s*$/)
        const text = (mAgent?.[1] || rest).trim()
        let agent = mAgent?.[2]?.trim()
        if (!agent) {
          const planItem = planById.get(id)
          if (planItem?.agent) agent = planItem.agent
        }

        const base = `${planEpoch}:${id}`
        const seq = (execKeySeq.get(base) || 0) + 1
        execKeySeq.set(base, seq)
        const key = `${base}:${seq}`

        const exec = ensureExec(key, id)
        exec.text = exec.text || text
        exec.agent = exec.agent || agent
        exec.logs.push(line)
        currentTaskKey = key
        inPlan = false
        execNodes.push({ type: "task", taskKey: key })
        currentSectionRef.current?.buf.push(line)
        continue
      }

      const s = t.match(stepRe)
      if (s) {
        const [, idxRaw, totalRaw, rest] = s
        const idx = Number(idxRaw)
        const total = Number(totalRaw)
        const exec = currentTaskKey ? ensureExec(currentTaskKey) : null
        if (exec) {
          // Stop capturing answer when we enter a new step.
          const cap = exec._cap
          if (cap && cap.mode === "answer") {
            const body = cap.buf.join("\n").trim()
            if (body) exec.answers.push(body)
            exec._cap = null
          }
          const stepText = rest.trim()
          if (/^query\s*:/i.test(stepText)) {
            exec.query = stepText.replace(/^query\s*:\s*/i, "").trim()
          } else {
            exec.steps.push({
              idx: Number.isFinite(idx) ? idx : 0,
              total: Number.isFinite(total) ? total : 0,
              text: stepText,
            })
          }
          exec.logs.push(line)
        }
        currentSectionRef.current?.buf.push(line)
        continue
      }

      // Capture "answer:" blocks inside a task. This is the per-agent output we want to show.
      if (currentTaskKey) {
        const exec = ensureExec(currentTaskKey)
        const a = t.match(answerStartRe)
        if (a) {
          // Flush previous capture if exists.
          const cap = exec._cap
          if (cap && cap.mode === "answer") {
            const body = cap.buf.join("\n").trim()
            if (body) exec.answers.push(body)
          }
          exec._cap = { mode: "answer", buf: [a[1] || ""] }
          exec.logs.push(line)
          currentSectionRef.current?.buf.push(line)
          continue
        }

        // End answer capture when we reach "reason:" or other markers.
        const cap = exec._cap
        if (cap && cap.mode === "answer") {
          if (reasonStartRe.test(t) || completeRe.test(t) || taskHeaderRe.test(t) || allTasksHeaderRe.test(t)) {
            const body = cap.buf.join("\n").trim()
            if (body) exec.answers.push(body)
            exec._cap = null
          } else {
            cap.buf.push(line)
            exec.logs.push(line)
            currentSectionRef.current?.buf.push(line)
            continue
          }
        }
      }

      if (completeRe.test(t)) {
        completions.push(t)
        currentSectionRef.current?.buf.push(line)
        continue
      }

      if (currentTaskKey) {
        const exec = ensureExec(currentTaskKey)
        exec.logs.push(line)
      }
      currentSectionRef.current?.buf.push(line)
    }
    flushSection()

    // Final flush: any in-progress answer capture at EOF.
    for (const exec of execByKey.values()) {
      const cap = exec._cap
      if (cap && cap.mode === "answer") {
        const body = cap.buf.join("\n").trimEnd()
        if (isThinking) {
          if (body.trim()) exec.inProgressAnswer = body
        } else {
          if (body.trim()) exec.answers.push(body.trim())
        }
      }
      exec._cap = null
    }

    const exec = execOrder
      .map((key) => execByKey.get(key))
      .filter(
        (x): x is NonNullable<typeof x> =>
          Boolean(x),
      )
      .map((t) => ({
        ...t,
        steps: [...t.steps].sort((a, b) => a.idx - b.idx),
        answers: [...(t.answers || [])],
        inProgressAnswer: t.inProgressAnswer,
      }))

    const activeTaskKey = currentTaskKey
    const execMap = new Map(exec.map((t) => [t.key, t] as const))
    return {
      raw,
      planBlocks,
      execNodes,
      exec,
      execMap,
      activeTaskKey,
      completions,
      flow,
      timeline,
      started: { plan: planStarted, exec: execStarted, flow: flowStarted, timeline: timelineStarted },
    }
  }, [content, isThinking])

  useEffect(() => {
    if (!isThinking) {
      if (elapsedSec != null && elapsedSec > 0) {
        setDuration(elapsedSec)
      }
      return
    }

    const anchor = startedAt ?? Date.now()
    const tick = () => {
      setDuration(Math.max(0, Math.floor((Date.now() - anchor) / 1000)))
    }
    tick()
    const timer = setInterval(tick, 1000)
    return () => clearInterval(timer)
  }, [isThinking, startedAt, elapsedSec])

  // IMPORTANT: Don't "guess" reasoning lifecycle on the frontend.
  // The backend decides when reasoning ends; on UI we treat reasoning as "running"
  // only before answer content starts (i.e. while msg.content is still empty).
  const reasoningActive = Boolean(isLive && isThinking)

  const hasProgress = progressList.length > 0
  const hasReasoning = content.trim().length > 0

  // Keep the panel visible after streaming if we have frozen progress cards,
  // even when the backend didn't emit textual reasoning_content.
  if (!isThinking && !hasReasoning && !hasProgress) return null

  const isExpanded = userExpanded

  return (
    <div className="mb-3 min-w-0 overflow-hidden">
      <style jsx global>{`
        @keyframes dacShimmer {
          0% { transform: translateX(-100%); }
          50% { transform: translateX(0%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
      <button
        type="button"
        className="w-full flex items-center py-2 text-left transition-colors select-none cursor-pointer"
        onClick={() => setUserExpanded((v) => !v)}
        aria-expanded={isExpanded}
        aria-label={isExpanded ? "收起思考过程" : "展开思考过程"}
      >
        <div className="flex items-center gap-2 text-base text-content">
          {isThinking ? (
            <Loader2 className="w-4 h-4 animate-spin text-cta" />
          ) : (
            <BrainCircuit className="w-4 h-4 text-cta" />
          )}
          <span className="font-medium flex items-center gap-1.5">
            <span>
              {isThinking ? "思考中" : "已思考"}
              {duration > 0 ? <span className="text-content-muted font-normal">（用时 {duration} 秒）</span> : null}
            </span>
            <span className="text-content-muted">
              {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </span>
          </span>
        </div>
      </button>

      {isExpanded ? (
        <div ref={scrollRef} className="mt-2 max-h-[60vh] overflow-y-auto rounded-lg border border-line/60 bg-surface-muted/20 p-3">
          <div className="border-l border-line/80 pl-2 min-w-0 overflow-hidden">
          {progressList.length > 0 ? (
            <Accordion
              type="multiple"
              className="space-y-2"
              value={openProgressSteps}
              onValueChange={setOpenProgressSteps}
            >
              {progressList.map((payload, i) => {
                const { agent, layer, event, message } = getProgressRowDisplay(payload)
                const isLast = i === progressList.length - 1
                const showShimmerOnRow = isLast && isThinking
                const triggerParts: ReactNode[] = []
                if (agent)
                  triggerParts.push(
                    <span key="a" className="font-medium text-content">
                      {agent}
                    </span>
                  )
                if (layer)
                  triggerParts.push(
                    <span key="l" className="text-content-muted text-[12px]">
                      {layer}
                    </span>
                  )
                if (event)
                  triggerParts.push(
                    <span key="e" className="text-content-muted text-[12px]">
                      {event}
                    </span>
                  )
                const triggerLabel = (
                  <>
                    {triggerParts.map((node, j) => (
                      <span key={j}>
                        {j > 0 ? (
                          <span className="text-content-muted mx-1.5">·</span>
                        ) : null}
                        {node}
                      </span>
                    ))}
                  </>
                )
                return (
                  <AccordionItem
                    key={i}
                    value={String(i)}
                    className="rounded-lg border border-line bg-surface shadow-sm overflow-hidden last:border-b"
                  >
                    <AccordionTrigger
                      className={cn(
                        "px-3 py-2.5 hover:no-underline hover:bg-surface-muted/50 rounded-t-lg [&[data-state=open]]:rounded-b-none",
                        showShimmerOnRow && "relative overflow-hidden"
                      )}
                    >
                      {triggerLabel}
                      {showShimmerOnRow ? (
                        <div
                          className="absolute inset-0 pointer-events-none bg-gradient-to-r from-transparent via-white to-transparent [animation:dacShimmer_1.5s_ease-in-out_infinite] will-change-transform rounded-t-lg opacity-90"
                          aria-hidden
                        />
                      ) : null}
                    </AccordionTrigger>
                    <AccordionContent className="px-3 pb-3 pt-0">
                      <div className="rounded-b-lg border-t border-line/60 bg-surface-muted/30 py-2 px-2.5">
                        {message ? (
                          <span className="font-mono text-[12px] text-content leading-relaxed whitespace-pre-wrap break-words">
                            {message}
                          </span>
                        ) : (
                          <span className="text-content-muted text-[12px]">—</span>
                        )}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                )
              })}
            </Accordion>
          ) : isThinking ? (
            <div className="space-y-2">
              <ShimmerLine w="w-4/5" />
              <ShimmerLine w="w-full" />
              <ShimmerLine w="w-3/4" />
            </div>
          ) : null}
          </div>

          <div className="mt-2 pl-3 border-l border-line/80 text-[13px] text-content leading-6 min-w-0 overflow-hidden">
          <div className="mt-2 space-y-2">
            {(() => {
              const agentToTasks = new Map<string, string[]>()
              const addTask = (agent: string, text: string) => {
                if (!agent) return
                const t = (text || "").trim()
                if (!t) return
                if (!agentToTasks.has(agent)) agentToTasks.set(agent, [])
                const list = agentToTasks.get(agent)!
                if (!list.includes(t)) list.push(t)
              }
              for (const block of parsed.planBlocks || []) {
                for (const item of block.items || []) {
                  if (item.agent) addTask(String(item.agent), item.text)
                }
              }
              for (const t of parsed.exec || []) {
                if (t.agent && t.text) addTask(String(t.agent), t.text)
              }
              const agents = [...agentToTasks.keys()]
              const getWhat = (agent: string) => {
                const list = agentToTasks.get(agent)
                if (!list || list.length === 0) return null
                return list.length === 1 ? list[0] : list.map((s, i) => `${i + 1}. ${s}`).join("\n")
              }
              const getAgentRawLog = (agent: string) => {
                const tasks = (parsed.exec || []).filter((t) => t.agent === agent)
                const lines = tasks.flatMap((t) => t.logs || [])
                return lines.join("\n")
              }
              const allTasksItems: { id: string; text: string; agent?: string }[] = []
              for (const block of parsed.planBlocks || []) {
                for (const item of block.items || []) {
                  allTasksItems.push({
                    id: item.id,
                    text: (item.text || "").trim(),
                    agent: item.agent?.trim(),
                  })
                }
              }
              return (
                <div className="flex flex-col gap-2">
                  {allTasksItems.length > 0 ? (
                    <div className="rounded-lg border border-line bg-surface-muted/50 px-4 py-3">
                      <p className="text-[11px] font-medium text-content-muted mb-2">任务列表</p>
                      <ul className="space-y-2">
                        {allTasksItems.map((item) => (
                          <li key={`${item.id}-${item.text}-${item.agent || ""}`} className="flex items-start gap-2 text-[12px] text-content">
                            <span className="text-content-muted font-mono shrink-0">[{item.id}]</span>
                            <span className="flex-1 min-w-0">{item.text}</span>
                            {item.agent ? (
                              <span className="shrink-0 text-[11px] text-content-muted bg-surface-muted px-1.5 py-0.5 rounded">
                                {item.agent}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {agents.map((agent) => {
                    const what = getWhat(agent)
                    const rawLog = getAgentRawLog(agent)
                    const isOpen = expandedAgent === agent
                    const hasLog = !!(rawLog && rawLog.trim())
                    const showShimmer = isThinking && !hasLog
                    return (
                      <div
                        key={agent}
                        className="rounded-lg border border-line bg-surface overflow-hidden"
                      >
                        <button
                          type="button"
                          onClick={() => setExpandedAgent((a) => (a === agent ? null : agent))}
                          className="w-full px-4 py-3 text-left flex items-start gap-3 hover:bg-surface-muted/50 transition-colors cursor-pointer"
                          aria-label={expandedAgent === agent ? "收起智能体" : "展开智能体"}
                        >
                          <span className="text-content-muted mt-0.5 shrink-0">
                            {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                          </span>
                          <div className="flex-1 min-w-0">
                            {showShimmer ? (
                              <div className="space-y-2">
                                <ShimmerLine w="w-3/4" />
                                <ShimmerLine w="w-full" />
                                <ShimmerLine w="w-4/5" />
                              </div>
                            ) : (
                              <>
                                <div className="text-[13px] font-medium text-content">{agent}</div>
                                {what ? (
                                  <div className="mt-2 text-[12px] text-content whitespace-pre-wrap">
                                    <span className="text-[11px] text-content-muted font-medium">任务：</span>
                                    {what}
                                  </div>
                                ) : null}
                              </>
                            )}
                          </div>
                        </button>
                        {isOpen ? (
                          <div className="border-t border-line bg-surface-muted/50">
                            <pre className="px-4 py-3 max-h-64 overflow-auto text-[11px] leading-5 text-content whitespace-pre-wrap break-all">
                              {(rawLog.trim() || "暂无该智能体执行日志").replace(/answer:\s*\n\s*(?=【智能体\s*\d+】)/gi, "answer: ")}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              )
            })()}
          </div>
        </div>
        </div>
      ) : null}
    </div>
  )
}
