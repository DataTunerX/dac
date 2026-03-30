"use client"

// Next.js requires useSearchParams() to be wrapped in Suspense.
// We make this page dynamic to avoid prerender failures in production builds.
export const dynamic = "force-dynamic"

import React, { useState, useRef, useEffect, useMemo, useCallback, Suspense, memo, Fragment } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  ArrowDown,
  Bot,
  Copy,
  Check,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
  RefreshCw,
  BrainCircuit,
} from "lucide-react"
import { toast } from "sonner"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import type { HTMLAttributes, ReactNode } from "react"
import nextDynamic from "next/dynamic"
import { REFRESH_CHAT_LIST_EVENT, NewChatEventDetail } from "@/lib/events"
import type { ChatProgressPayload } from "@/lib/api-types"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import { cn } from "@/lib/utils"
import { getProgressRowDisplay, shouldShowProgressItem } from "@/lib/chat-progress"
import { parseHistoryThink } from "@/lib/history-think"
import { parseChatSSELine } from "@/lib/parse-chat-sse"
import { ChatInput } from "@/components/chat/ChatInput"
import { normalizeMarkdown } from "@/components/markdown"
import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"

const ChartBlock = nextDynamic(
  () => import("@/components/chart-block/index").then((m) => ({ default: m.ChartBlock })),
  { ssr: false }
)
const MermaidBlock = nextDynamic(
  () => import("@/components/mermaid-block/index").then((m) => ({ default: m.MermaidBlock })),
  { ssr: false }
)

type MarkdownCodeProps = HTMLAttributes<HTMLElement> & {
  inline?: boolean
  className?: string
  children?: ReactNode
}

function handleUnauthorized() {
  clearAuthToken()
  if (typeof window !== "undefined") {
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    const next = `${path}${search}${hash}`
    redirectToLogin(next)
  }
}

function normalizeMathDelimiters(input: string) {
  // Models often output \[...\] / \(...\) which remark-math doesn't parse by default.
  // Convert them to $$...$$ / $...$ for KaTeX rendering.
  return input
    .replaceAll("\\[", "$$")
    .replaceAll("\\]", "$$")
    .replaceAll("\\(", "$")
    .replaceAll("\\)", "$")
}

/** 将思考过程里类似 code.py :: func (line 1-2) 或 === code.py :: ... === 的纯文本行包成 markdown 行内代码，便于正确展示 */
function wrapReasoningCodeRefs(text: string): string {
  const lines = text.split("\n")
  let inFence = false
  const out: string[] = []
  const isFence = (line: string) => /^\s*```/.test(line)
  const looksLikeCodeRef = (line: string) => {
    const t = line.trim()
    if (!t) return false
    if (/^\s*===+\s*.+\s*===+\s*$/.test(line)) return true
    if (/\S+\.(py|ts|tsx|js|jsx|go|java)\s*::\s*.+/.test(t)) return true
    return false
  }
  for (const line of lines) {
    if (isFence(line)) inFence = !inFence
    if (!inFence && looksLikeCodeRef(line)) {
      const t = line.trim()
      const delim = t.includes("`") ? "``" : "`"
      out.push(`${delim}${t}${delim}`)
    } else {
      out.push(line)
    }
  }
  return out.join("\n")
}

function findLastUserIndex(msgs: Message[]) {
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i]?.role === "user") return i
  }
  return -1
}

function safeUUID() {
  // Prefer crypto.randomUUID when available.
  try {
    const c = globalThis.crypto
    if (c && typeof c.randomUUID === "function") return c.randomUUID()
    if (c && typeof c.getRandomValues === "function") {
      // RFC4122 v4
      const bytes = new Uint8Array(16)
      c.getRandomValues(bytes)
      bytes[6] = (bytes[6] & 0x0f) | 0x40
      bytes[8] = (bytes[8] & 0x3f) | 0x80
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"))
      return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`
    }
  } catch {
    // fall through
  }
  return `r_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

function safeLocalStorageGet(key: string) {
  try {
    return typeof window !== "undefined" ? window.localStorage.getItem(key) : null
  } catch {
    return null
  }
}

function safeLocalStorageSet(key: string, value: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

function safeLocalStorageRemove(key: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.removeItem(key)
  } catch {
    // ignore
  }
}

function safeDispatchEvent<T>(event: CustomEvent<T>) {
  try {
    if (typeof window !== "undefined") window.dispatchEvent(event)
  } catch {
    // ignore
  }
}

/**
 * Single message in the conversation. Assistant messages may carry frozen progress
 * (progressList) once the stream ends so progress cards remain visible.
 */
interface Message {
  id?: string
  role: "user" | "assistant" | "system"
  content: string
  reasoning_content?: string
  /** Progress events for this assistant reply; set when stream ends so cards stay visible. */
  progressList?: readonly ChatProgressPayload[]
}

/** Stable empty array for progress list to avoid unnecessary re-renders (rerender-best-practice). */
const EMPTY_PROGRESS: readonly ChatProgressPayload[] = []

/** API response shape for GET /api/v1/chat/conversations/:runId (history). */
interface ConversationHistoryResponse {
  messages?: Array<{
    role?: string
    content?: string
    think?: string
    reasoning_content?: string
    /** 后端返回的进度事件列表，用于在历史消息中还原 ThinkingProcess 的进度卡片展示 */
    progress_list?: Array<Record<string, unknown>>
  }>
}

function isAbortError(err: unknown): err is Error & { name: "AbortError" } {
  return err instanceof Error && err.name === "AbortError"
}

async function copyToClipboard(text: string) {
  // Prefer async clipboard API when available (requires secure context in most browsers)
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && typeof window !== "undefined" && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return
    }
  } catch {
    // fall through to legacy fallback
  }

  // Legacy fallback for HTTP / non-secure contexts
  if (typeof document === "undefined") throw new Error("clipboard unavailable")
  const el = document.createElement("textarea")
  el.value = text
  el.setAttribute("readonly", "true")
  el.style.position = "fixed"
  el.style.top = "0"
  el.style.left = "0"
  el.style.opacity = "0"
  document.body.appendChild(el)
  el.focus()
  el.select()
  const ok = document.execCommand("copy")
  document.body.removeChild(el)
  if (!ok) throw new Error("copy failed")
}

// 抽到模块级，避免在 ThinkingProcess 内定义导致每次父组件重渲染（如滚动）时被当作新组件 remount、state 丢失
function chevronIcon(open: boolean, className = "w-4 h-4 text-content-muted shrink-0") {
  return open ? <ChevronDown className={className} /> : <ChevronRight className={className} />
}
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
  const [open, setOpen] = useState(defaultOpen)
  useEffect(() => {
    setOpen(defaultOpen)
  }, [defaultOpen])
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

// Note: we no longer parse planning logs out of assistant `content` on the frontend.
// The backend is responsible for emitting thought process via `reasoning_content`
// (and conversation history may use `think`, mapped to `reasoning_content` in this page).

// 简单的思维链/多任务折叠组件
// Note: "isThinking" is different from the overall message streaming state.
// We only show the spinner while the assistant is still "thinking" (i.e., before answer content starts).
const ThinkingProcess = ({
  content,
  isThinking,
  isLive,
  progressList = EMPTY_PROGRESS,
}: {
  content: string
  isThinking?: boolean
  isLive?: boolean
  /** Progress events shown under "思考中" (cards with event · agent · message). */
  progressList?: readonly ChatProgressPayload[]
}) => {
  const [userExpanded, setUserExpanded] = useState(false)
  const wasThinkingOrLiveRef = useRef(false)
  useEffect(() => {
    const now = Boolean(isLive || isThinking)
    if (now && !wasThinkingOrLiveRef.current) setUserExpanded(true)
    wasThinkingOrLiveRef.current = now
  }, [isThinking, isLive])
  const startedAtRef = useRef<number | null>(null)
  const [duration, setDuration] = useState(0)
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
    if (isThinking) {
      startedAtRef.current = Date.now()
      return
    }
    startedAtRef.current = null
  }, [isThinking])

  useEffect(() => {
    if (!isThinking) return

    // Avoid setState synchronously inside effect body (eslint rule).
    setTimeout(() => setDuration(0), 0)

    const timer = setInterval(() => {
      const startedAt = startedAtRef.current
      if (!startedAt) return
      const secs = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      setDuration(secs)
    }, 1000)
    return () => clearInterval(timer)
  }, [isThinking])

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
  const Chip = ({
    children,
    tone = "neutral",
  }: {
    children: ReactNode
    tone?: "neutral" | "success"
  }) => (
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

  const AgentChip = ({ name }: { name: string }) => (
    <Chip>
      <Bot className="w-3 h-3 text-content-muted" />
      <span className="text-[11px] leading-5">{name}</span>
    </Chip>
  )

  const StatusMark = ({
    state,
  }: {
    state: "idle" | "running" | "done" | "warn" | "fail"
  }) => {
    if (state === "running") return <Loader2 className="w-3.5 h-3.5 animate-spin text-content-muted" />
    if (state === "done") return <Check className="w-3.5 h-3.5 text-emerald-600" />
    if (state === "warn") return <AlertTriangle className="w-3.5 h-3.5 text-amber-600" />
    if (state === "fail") return <XCircle className="w-3.5 h-3.5 text-rose-600" />
    return <span className="w-3.5 h-3.5 inline-block" />
  }

  const SummaryRow = ({
    title,
    right,
    tone = "default",
    icon,
  }: {
    title: ReactNode
    right?: ReactNode
    tone?: "default" | "success"
    /** 传入则用该图标，否则用默认 ChevronRight + group-open；与 CollapsibleSection 配合可实现展开/闭合与图标一致 */
    icon?: ReactNode
  }) => (
    <div
      className={
        tone === "success"
          ? "flex items-center gap-2 py-1 text-emerald-900"
          : "flex items-center gap-2 py-1 text-content"
      }
    >
      {icon !== undefined ? icon : <ChevronRight className="w-4 h-4 text-content-muted shrink-0 group-open/section:rotate-90 transition-transform" />}
      <div className="flex-1 text-[12px] font-medium">{title}</div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  )

  const ShimmerLine = ({ w = "w-full" }: { w?: string }) => (
    <div className={`relative overflow-hidden h-3 rounded bg-surface-active/60 ${w}`}>
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white to-transparent [animation:dacShimmer_1.5s_ease-in-out_infinite] will-change-transform" />
    </div>
  )

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

// 代码块组件（带复制功能）。SyntaxHighlighter 按需动态加载以减小主 chunk（Vercel React Best Practices 2.4）
const CodeBlock = ({ language, children }: { language: string, children: string }) => {
  const [copied, setCopied] = useState(false)
  const [Highlighter, setHighlighter] = useState<typeof import("react-syntax-highlighter").Prism | null>(null)
  const [highlightStyle, setHighlightStyle] = useState<Record<string, React.CSSProperties> | null>(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      import("react-syntax-highlighter").then((m) => m.Prism),
      import("react-syntax-highlighter/dist/esm/styles/prism").then((m) => m.vscDarkPlus),
    ]).then(([Prism, vscDarkPlus]) => {
      if (!cancelled) {
        setHighlighter(() => Prism)
        setHighlightStyle(vscDarkPlus)
      }
    }).catch(() => { if (!cancelled) setHighlightStyle({}) })
    return () => { cancelled = true }
  }, [])

  const handleCopy = async () => {
    try {
      await copyToClipboard(children)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (e) {
      console.error("Copy code block failed", e)
      toast.error("复制失败（浏览器限制）")
    }
  }

  return (
    <div className="rounded-lg overflow-hidden my-3 border border-slate-700 bg-[#1e1e1e] shadow-sm group">
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-slate-700 text-xs text-content-muted select-none">
        <span className="font-mono">{language || "text"}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-content-inverse transition-colors cursor-pointer"
          aria-label={copied ? "已复制" : "复制代码"}
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? "Copied" : "Copy"}</span>
        </button>
      </div>
      {Highlighter && highlightStyle ? (
        <Highlighter
          language={language}
          style={highlightStyle}
          customStyle={{ margin: 0, padding: "1rem", fontSize: "0.875rem", lineHeight: "1.5" }}
          wrapLines={true}
          wrapLongLines={true}
        >
          {children}
        </Highlighter>
      ) : (
        <pre className="m-0 p-4 text-sm leading-relaxed overflow-x-auto">
          <code>{children}</code>
        </pre>
      )}
    </div>
  )
}

const MARKDOWN_REMARK_PLUGINS = [remarkGfm, remarkMath]
const MARKDOWN_REHYPE_PLUGINS = [rehypeKatex]

const MARKDOWN_COMPONENTS = {
  code({
    inline,
    className,
    children,
    ...props
  }: MarkdownCodeProps) {
    const match = /language-(\w+)/.exec(className || '')
    const language = match?.[1] || ""
    const raw = String(children).replace(/\n$/, "")

    if (!inline && language === "chart") {
      return <ChartBlock value={raw} className="my-3" />
    }
    if (!inline && language === "mermaid") {
      return <MermaidBlock value={raw} className="my-3" />
    }

    return !inline && match ? (
      <CodeBlock language={language}>{raw}</CodeBlock>
    ) : (
      <code
        className="bg-surface-muted px-1 py-0.5 rounded text-[12px] font-mono text-content border border-line"
        {...props}
      >
        {children}
      </code>
    )
  },
  p({children}: { children?: ReactNode }) {
    return <p className="text-sm text-content leading-6 mb-2 last:mb-0">{children}</p>
  },
  ul({children}: { children?: ReactNode }) {
    return <ul className="text-sm text-content leading-6 list-disc pl-5 space-y-1 my-2">{children}</ul>
  },
  ol({children}: { children?: ReactNode }) {
    return <ol className="text-sm text-content leading-6 list-decimal pl-5 space-y-1 my-2">{children}</ol>
  },
  li({children}: { children?: ReactNode }) {
    return <li className="pl-1 marker:text-content-muted">{children}</li>
  },
  // 标题（h1-h6）- 渐进式字号和间距
  h1({children}: { children?: ReactNode }) {
    return <h1 className="text-xl font-semibold text-content mt-6 mb-3">{children}</h1>
  },
  h2({children}: { children?: ReactNode }) {
    return <h2 className="text-lg font-semibold text-content mt-5 mb-2.5">{children}</h2>
  },
  h3({children}: { children?: ReactNode }) {
    return <h3 className="text-base font-semibold text-content mt-4 mb-2">{children}</h3>
  },
  h4({children}: { children?: ReactNode }) {
    return <h4 className="text-sm font-semibold text-content mt-3 mb-2">{children}</h4>
  },
  h5({children}: { children?: ReactNode }) {
    return <h5 className="text-sm font-semibold text-content mt-3 mb-2">{children}</h5>
  },
  h6({children}: { children?: ReactNode }) {
    return <h6 className="text-sm font-semibold text-content mt-3 mb-2">{children}</h6>
  },
  // 链接 - 蓝色可点击，外部链接新窗口打开
  a({href, children}: { href?: string; children?: ReactNode }) {
    const isExternal = href?.startsWith('http')
    return (
      <a 
        href={href}
        className="text-cta hover:text-cta/90 underline cursor-pointer transition-colors"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
      >
        {children}
      </a>
    )
  },
  // 引用块 - 左侧竖线 + 浅色背景
  blockquote({children}: { children?: ReactNode }) {
    return <blockquote className="border-l-4 border-line pl-4 py-2 my-3 italic text-sm text-content bg-surface-muted rounded-r">{children}</blockquote>
  },
  // 分隔线
  hr() {
    return <hr className="border-line-hover my-6" />
  },
  // 强调 - 明确样式
  strong({children}: { children?: ReactNode }) {
    return <strong className="font-bold text-content">{children}</strong>
  },
  em({children}: { children?: ReactNode }) {
    return <em className="italic text-content">{children}</em>
  },
  // 删除线 - GFM 支持
  del({children}: { children?: ReactNode }) {
    return <del className="line-through text-content-muted">{children}</del>
  },
  // 表格 - 使用现代样式
  table({children}: { children?: ReactNode }) {
    return <div className="overflow-x-auto my-4"><table className="min-w-full border-collapse border border-line">{children}</table></div>
  },
  thead({children}: { children?: ReactNode }) {
    return <thead className="bg-surface-muted">{children}</thead>
  },
  tbody({children}: { children?: ReactNode }) {
    return <tbody className="bg-surface divide-y divide-line">{children}</tbody>
  },
  tr({children}: { children?: ReactNode }) {
    return <tr className="hover:bg-surface-muted transition-colors">{children}</tr>
  },
  th({children}: { children?: ReactNode }) {
    return <th className="border border-line px-4 py-2 text-left text-sm font-semibold text-content">{children}</th>
  },
  td({children}: { children?: ReactNode }) {
    return <td className="border border-line px-4 py-2 text-sm text-content">{children}</td>
  }
}

const MarkdownAnswer = memo(function MarkdownAnswer({ value }: { value: string }) {
  return (
    <div className="min-w-0 overflow-hidden">
      <ReactMarkdown
        remarkPlugins={MARKDOWN_REMARK_PLUGINS}
        rehypePlugins={MARKDOWN_REHYPE_PLUGINS}
        components={MARKDOWN_COMPONENTS}
      >
        {value}
      </ReactMarkdown>
    </div>
  )
})

/** Props for the assistant message body (progress cards + thinking + answer). */
interface AssistantMessageBodyProps {
  readonly msg: Message
  readonly index: number
  readonly messagesLength: number
  readonly isStreaming: boolean
  readonly streamProgressList: readonly ChatProgressPayload[]
}

/** Renders one assistant message: progress list (append-only), thinking block, then answer. */
const AssistantMessageBody = memo(function AssistantMessageBody({
  msg,
  index,
  messagesLength,
  isStreaming,
  streamProgressList,
}: AssistantMessageBodyProps) {
  const thinking = (msg.reasoning_content ?? "").trim()
  const answer = msg.content ?? ""
  const isLastMessage = index === messagesLength - 1
  // Treat whitespace-only chunks as "not visible yet" so we don't collapse the
  // thinking block before the user can actually see answer content.
  const hasVisibleAnswer = answer.trim().length > 0
  const isThinkingNow = isLastMessage && isStreaming && !hasVisibleAnswer

  const progressList = useMemo<readonly ChatProgressPayload[]>(() => {
    // 非最后一条消息：使用冻结在 msg 上的 progressList（来自历史或流式结束时的快照）
    if (!isLastMessage) return msg.progressList ?? EMPTY_PROGRESS
    // 最后一条消息：优先使用冻结数据，其次使用实时流数据
    if (msg.progressList && msg.progressList.length > 0) return msg.progressList
    if (streamProgressList.length > 0) return streamProgressList
    return EMPTY_PROGRESS
  }, [isLastMessage, msg.progressList, streamProgressList])

  const hasProgress = progressList.length > 0
  // 任何有 reasoning 或 progress 的消息都展示 ThinkingProcess；仅最后一条消息在流式中展示"思考中"动画
  const showThinking = thinking.length > 0 || hasProgress || (isThinkingNow && isLastMessage)

  return (
    <>
      {showThinking ? (
        <ThinkingProcess
          content={thinking}
          isThinking={isThinkingNow}
          isLive={isLastMessage && isStreaming}
          progressList={progressList}
        />
      ) : null}
      <MarkdownAnswer value={normalizeMarkdown(normalizeMathDelimiters(answer))} />
    </>
  )
})

function ChatContent() {
  const router = useRouter()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isStreaming, setIsStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoScrollRef = useRef(true)
  const [showJumpToBottom, setShowJumpToBottom] = useState(false)
  const abortControllerRef = useRef<AbortController | null>(null)
  const activeRunIdRef = useRef<string | null>(null)
  const requestSeqRef = useRef(0)
  const inFlightRunIdRef = useRef<string | null>(null)
  const optimisticRunIdsRef = useRef<Set<string>>(new Set())
  const messagesRef = useRef<Message[]>([])
  const isStreamingRef = useRef(false)
  const isLoadingRef = useRef(false)

  // Streaming perf: batch tiny SSE deltas into a single React update every ~40ms.
  const streamPendingRef = useRef<{ content: string; reasoning: string }>({ content: "", reasoning: "" })
  const streamFlushTimerRef = useRef<number | null>(null)
  // Progress from SSE `event: progress`; append each event, clear when starting a new request or after freezing into message.
  const [streamProgressList, setStreamProgressList] = useState<ChatProgressPayload[]>([])
  const streamProgressListRef = useRef<ChatProgressPayload[]>([])
  /** 当前进行中的历史拉取：发消息开始流式时会 abort，避免返回后覆盖当前会话 */
  const historyAbortControllerRef = useRef<AbortController | null>(null)
  /**
   * 刚完成流式的 runId，用于防止 finally 清理 ref 后、React 提交 isStreaming=false 之前的时间窗口内
   * shouldLoadHistoryForRunId 误判为 true 而触发历史拉取覆盖本地消息。
   * 在 finally 中设置，下一个事件循环 tick 清除。
   */
  const justFinishedRunIdRef = useRef<string | null>(null)

  // 获取 URL 参数
  const searchParams = useSearchParams()
  const runId = searchParams.get('run_id')

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    isStreamingRef.current = isStreaming
  }, [isStreaming])

  useEffect(() => {
    isLoadingRef.current = isLoading
  }, [isLoading])

  /**
   * 是否应当为当前 runId 拉取历史？
   * 只有「用户导航到某会话」时才拉取；若 runId 是我们刚创建或正在流式回复的会话，则用本地 state 即可，不覆盖。
   * @param id - run_id from URL (or null for new chat)
   * @returns true if we should fetch and apply history for this id
   */
  const shouldLoadHistoryForRunId = useCallback((id: string | null): boolean => {
    if (!id) return false
    // 我们正在为此会话流式回复 → 不拉历史，用本地 state
    if (inFlightRunIdRef.current === id && isStreamingRef.current && messagesRef.current.length > 0)
      return false
    // 流刚结束、React 尚未提交 isStreaming=false → 不拉历史，避免旧数据覆盖本地消息
    if (justFinishedRunIdRef.current === id) return false
    // 我们刚创建的会话（乐观 run_id）：setMessages 可能尚未提交，不能依赖 messagesRef.length，一律不拉
    if (optimisticRunIdsRef.current.has(id)) return false
    return true
  }, [])

  /**
   * 历史拉取：仅在「导航到某会话」时拉取并应用；若用户在该会话里发消息（开始流式），
   * 会取消本次拉取，避免请求返回后用旧数据覆盖当前对话。
   */
  useEffect(() => {
    const nextRunId = runId
    const isSameConversation =
      Boolean(nextRunId && inFlightRunIdRef.current && nextRunId === inFlightRunIdRef.current)

    if (!isSameConversation && abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
      requestSeqRef.current += 1
      setIsStreaming(false)
      setIsLoading(false)
    }
    activeRunIdRef.current = nextRunId ?? null

    if (!nextRunId) {
      setMessages([])
      return
    }
    if (!shouldLoadHistoryForRunId(nextRunId)) return

    historyAbortControllerRef.current?.abort()
    const controller = new AbortController()
    historyAbortControllerRef.current = controller

    const fetchHistory = async () => {
      try {
        const token = getAuthToken()
        const response = await fetch(`/api/v1/chat/conversations/${nextRunId}`, {
          headers: { Authorization: token ? `Bearer ${token}` : "" },
          signal: controller.signal,
        })
        if (response.status === 401) {
          handleUnauthorized()
          return
        }
        if (!response.ok) {
          if (response.status === 404) {
            if (optimisticRunIdsRef.current.has(nextRunId)) return
            console.warn("Conversation not found, redirecting to new chat")
            router.replace("/")
            return
          }
          console.error("Failed to load history:", response.statusText)
          return
        }
        const data = (await response.json()) as ConversationHistoryResponse
        if (!data?.messages) return
        if (controller.signal.aborted) return
        if (activeRunIdRef.current !== nextRunId) return
        const rawMessages = Array.isArray(data.messages) ? data.messages : []
        const historyMessages: Message[] = rawMessages
          .map((m, i): Message | null => {
            const r = typeof m === "object" && m !== null ? (m as Record<string, unknown>) : {}
            const role = r.role
            const content = r.content
            if (
              (role !== "user" && role !== "assistant" && role !== "system") ||
              typeof content !== "string"
            )
              return null
            const think = typeof r.think === "string" ? r.think : undefined
            const reasoning =
              typeof r.reasoning_content === "string" ? r.reasoning_content : undefined
            const rawProgress = r.progress_list
            const progressList: ChatProgressPayload[] | undefined =
              Array.isArray(rawProgress) && rawProgress.length > 0
                ? (rawProgress as ChatProgressPayload[])
                : undefined
            const parsedThink = parseHistoryThink(think)
            return {
              id: `${nextRunId}-${i}`,
              role,
              content,
              reasoning_content: parsedThink.reasoning || reasoning || "",
              ...((progressList && progressList.length > 0)
                ? { progressList }
                : (parsedThink.progressList.length > 0 ? { progressList: parsedThink.progressList } : {})),
            }
          })
          .filter((x): x is Message => Boolean(x))
        if (controller.signal.aborted) return
        if (activeRunIdRef.current !== nextRunId) return
        setMessages(historyMessages)
      } catch (error) {
        if (isAbortError(error)) return
        console.error("Error loading history:", error)
        toast.error("加载历史会话失败")
      }
    }
    fetchHistory()
    return () => {
      controller.abort()
      if (historyAbortControllerRef.current === controller) historyAbortControllerRef.current = null
    }
  }, [runId, shouldLoadHistoryForRunId])

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
  }, [])

  const resumeAutoScroll = useCallback((behavior: ScrollBehavior = "auto") => {
    autoScrollRef.current = true
    setShowJumpToBottom(false)
    // Ensure we scroll after DOM paints (important when switching from "new chat" view).
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        scrollToBottom(behavior)
      })
    })
  }, [scrollToBottom])

  // "粘底"滚动：用户在底部时自动跟随；用户上翻则暂停并显示“回到底部”
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return

    const THRESHOLD_PX = 64
    let rafId: number | null = null

    const compute = () => {
      rafId = null
      const distanceToBottom =
        el.scrollHeight - (el.scrollTop + el.clientHeight)
      const isNearBottom = distanceToBottom <= THRESHOLD_PX
      autoScrollRef.current = isNearBottom
      setShowJumpToBottom(!isNearBottom)
    }

    const onScroll = () => {
      if (rafId != null) return
      rafId = window.requestAnimationFrame(compute)
    }

    // Initialize state on mount / conversation switch
    compute()
    el.addEventListener("scroll", onScroll, { passive: true })

    return () => {
      if (rafId != null) window.cancelAnimationFrame(rafId)
      el.removeEventListener("scroll", onScroll)
    }
  }, [runId])

  // When messages or progress list update, keep following only if user hasn't scrolled up.
  // Defer scroll to after layout so scrollHeight includes new content (fixes "answer not in view").
  useEffect(() => {
    if (!autoScrollRef.current) return
    const behavior = isStreaming ? "auto" : "smooth"
    let rafId2: number | undefined
    const rafId1 = window.requestAnimationFrame(() => {
      rafId2 = window.requestAnimationFrame(() => {
        if (!autoScrollRef.current) return
        scrollToBottom(behavior)
      })
    })
    return () => {
      window.cancelAnimationFrame(rafId1)
      if (typeof rafId2 === "number") window.cancelAnimationFrame(rafId2)
    }
  }, [messages, isStreaming, streamProgressList.length, scrollToBottom])

  const handleRegenerate = async () => {
    if (isLoading || messages.length === 0) return
    
    // 找到最后一条用户消息
    const lastUserIndex = findLastUserIndex(messages)
    if (lastUserIndex === -1) return

    // 保留到该用户消息为止的历史记录
    const messagesHistory = messages.slice(0, lastUserIndex + 1)
    
    // 更新状态：移除后续的 AI 回复（如果有）
    // Insert an empty assistant placeholder immediately so the message-area "思考中" can show
    // before the backend streams the first token.
    resumeAutoScroll("auto")
    setMessages([...messagesHistory, { id: safeUUID(), role: "assistant", content: "", reasoning_content: "" }])
    setIsLoading(true)
    setIsStreaming(true)
    
    await processChatRequest(messagesHistory, runId || undefined)
  }

  const processChatRequest = async (messagesPayload: Message[], currentRunId?: string) => {
    const myReqSeq = ++requestSeqRef.current
    inFlightRunIdRef.current = currentRunId || null
    historyAbortControllerRef.current?.abort()
    historyAbortControllerRef.current = null
    abortControllerRef.current = new AbortController()
    setStreamProgressList([])
    streamProgressListRef.current = []

    const clearFlushTimer = () => {
      if (streamFlushTimerRef.current != null) {
        window.clearTimeout(streamFlushTimerRef.current)
        streamFlushTimerRef.current = null
      }
    }

    const flushPending = () => {
      // Ignore late timer flushes after conversation switch.
      if (myReqSeq !== requestSeqRef.current) return
      const pending = streamPendingRef.current
      if (!pending.content && !pending.reasoning) return
      const content = pending.content
      const reasoning = pending.reasoning
      streamPendingRef.current = { content: "", reasoning: "" }

      setMessages((prev) => {
        if (myReqSeq !== requestSeqRef.current) return prev
        const next = [...prev]
        const last = next[next.length - 1]
        if (last?.role !== "assistant") {
          next.push({ role: "assistant", content: "", reasoning_content: "" })
        }
        const idx = next.length - 1
        const a = next[idx]
        if (a.role === "assistant") {
          next[idx] = {
            ...a,
            content: (a.content || "") + content,
            reasoning_content: (a.reasoning_content || "") + reasoning,
          }
        }
        return next
      })
    }

    const scheduleFlush = () => {
      if (streamFlushTimerRef.current != null) return
      streamFlushTimerRef.current = window.setTimeout(() => {
        streamFlushTimerRef.current = null
        flushPending()
      }, 40)
    }

    try {
      const token = getAuthToken()

      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({
          messages: messagesPayload,
          stream: true,
          run_id: currentRunId, // 传递 run_id
        }),
        signal: abortControllerRef.current.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          handleUnauthorized()
          return
        }
        throw new Error(response.statusText)
      }

      // If user switched conversations while this request was in-flight, ignore it entirely.
      if (myReqSeq !== requestSeqRef.current) {
        return
      }

      // If this is a brand new chat (no run_id in URL), persist the run_id returned by backend.
      const returnedRunId = response.headers.get("x-run-id") || response.headers.get("X-Run-Id")
      // Fallback: if we somehow didn't have a runID yet (shouldn't happen with client-gen), use backend's
      if (!currentRunId && returnedRunId) {
        router.replace(`/?run_id=${encodeURIComponent(returnedRunId)}`)
        activeRunIdRef.current = returnedRunId
        inFlightRunIdRef.current = returnedRunId
      } else if (currentRunId && returnedRunId && currentRunId !== returnedRunId) {
        // ID Reconciliation: If backend returned a different ID, update to use backend's ID
        console.warn(`Run ID mismatch. Client: ${currentRunId}, Backend: ${returnedRunId}. Updating to backend ID.`)
        router.replace(`/?run_id=${encodeURIComponent(returnedRunId)}`)
        activeRunIdRef.current = returnedRunId
        inFlightRunIdRef.current = returnedRunId

        // Keep sidebar + localStorage consistent (avoid "ghost conversation" selectable but 404).
        const optimisticTitle = safeLocalStorageGet(`dac_title_${currentRunId}`)
        if (optimisticTitle) {
          safeLocalStorageSet(`dac_title_${returnedRunId}`, optimisticTitle)
          safeLocalStorageRemove(`dac_title_${currentRunId}`)
        }
        const event = new CustomEvent<NewChatEventDetail>(REFRESH_CHAT_LIST_EVENT, {
          detail: {
            id: returnedRunId,
            title: optimisticTitle || "",
            created_at: new Date().toISOString(),
            replace_id: currentRunId,
          },
        })
        safeDispatchEvent(event)
      }

      if (!response.body) throw new Error("No response body")

      const reader = response.body.getReader()
      const decoder = new TextDecoder("utf-8")
      let done = false
      let textBuffer = ""
      let lastEventType = ""

      while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        const chunkValue = value ? decoder.decode(value, { stream: true }) : ""
        textBuffer += chunkValue

        const lines = textBuffer.split("\n")
        textBuffer = lines.pop() || ""

        for (const line of lines) {
          const result = parseChatSSELine(line, lastEventType)
          if (result === null) continue
          if (result.kind === "event") {
            lastEventType = result.eventType
            continue
          }
          if (result.kind === "progress") {
            lastEventType = ""
            if (myReqSeq === requestSeqRef.current && shouldShowProgressItem(result.payload)) {
              const payload = result.payload
              setStreamProgressList((prev) => [...prev, payload])
              streamProgressListRef.current = [...streamProgressListRef.current, payload]
            }
            continue
          }
          if (result.kind === "done") {
            done = true
            break
          }
          if (result.kind === "chunk") {
            // 消费完带 event 的 data 行后重置，避免后续无 event 前缀的 data 行被误判
            if (lastEventType.length > 0) lastEventType = ""
            if (result.content || result.reasoning) {
              streamPendingRef.current.content += result.content
              streamPendingRef.current.reasoning += result.reasoning
              scheduleFlush()
            }
          }
        }
      }

      // Single atomic update: flush any remaining pending content AND freeze progressList.
      // (Two separate setMessages would be batched in React 18; the second updater would see
      // stale prev and overwrite the last message without the final flush content.)
      clearFlushTimer()
      const pendingContent = streamPendingRef.current.content
      const pendingReasoning = streamPendingRef.current.reasoning
      streamPendingRef.current = { content: "", reasoning: "" }
      const frozen = streamProgressListRef.current
      const frozenCopy: ChatProgressPayload[] = frozen.length > 0 ? [...frozen] : []

      setMessages((prev) => {
        if (myReqSeq !== requestSeqRef.current) return prev
        const next = [...prev]
        const last = next[next.length - 1]
        if (last?.role === "assistant") {
          next[next.length - 1] = {
            ...last,
            content: (last.content || "") + pendingContent,
            reasoning_content: (last.reasoning_content || "") + pendingReasoning,
            ...(frozenCopy.length > 0 ? { progressList: frozenCopy } : {}),
          }
        }
        return next
      })
      setStreamProgressList([])
      streamProgressListRef.current = []
    } catch (err: unknown) {
      if (isAbortError(err)) {
        console.log("Stream aborted")
        return
      }
      console.error("Chat failed", err)
      toast.error("对话请求失败")
      setMessages((prev) => {
        if (myReqSeq !== requestSeqRef.current) return prev
        if (prev.length > 0 && prev[prev.length - 1].role === "user") {
          return [
            ...prev,
            { id: safeUUID(), role: "assistant", content: "⚠️ Error: Failed to get response." },
          ]
        }
        return prev
      })
    } finally {
      clearFlushTimer()
      streamPendingRef.current = { content: "", reasoning: "" }
      if (myReqSeq === requestSeqRef.current) {
        const finishedRunId = inFlightRunIdRef.current
        // 先标记 justFinishedRunIdRef，防止 shouldLoadHistoryForRunId 在 isStreamingRef 异步更新前误判
        if (finishedRunId) {
          justFinishedRunIdRef.current = finishedRunId
          // 下一个事件循环 tick 清除（此时 React 已提交 isStreaming=false，isStreamingRef useEffect 已执行）
          const captured = finishedRunId
          setTimeout(() => {
            if (justFinishedRunIdRef.current === captured) {
              justFinishedRunIdRef.current = null
            }
          }, 0)
        }
        setIsLoading(false)
        setIsStreaming(false)
        abortControllerRef.current = null
        inFlightRunIdRef.current = null
        if (finishedRunId) optimisticRunIdsRef.current.delete(finishedRunId)
      }
    }
  }

  const handleSend = async () => {
    if (!input.trim()) return

    const userMsg: Message = { id: safeUUID(), role: "user", content: input }
    const newMessages = [...messages, userMsg]
    setMessages([...newMessages, { id: safeUUID(), role: "assistant", content: "", reasoning_content: "" }])
    resumeAutoScroll("auto")
    setInput("")
    setIsLoading(true)
    setIsStreaming(true)

    let currentRunId = runId
    if (!currentRunId) {
      currentRunId = safeUUID()
      // 先设 ref 再改 URL，这样 runId 变化触发的 effect 里 shouldLoadHistoryForRunId 会跳过拉取
      inFlightRunIdRef.current = currentRunId
      activeRunIdRef.current = currentRunId
      optimisticRunIdsRef.current.add(currentRunId)

      // 1. Update URL immediately
      router.replace(`/?run_id=${encodeURIComponent(currentRunId)}`)
      
      const title = input.slice(0, 30) || "New Chat"
      // Persist title to localStorage to survive page refreshes
      safeLocalStorageSet(`dac_title_${currentRunId}`, title)

      // 2. Notify sidebar immediately
      const event = new CustomEvent<NewChatEventDetail>(REFRESH_CHAT_LIST_EVENT, {
        detail: {
          id: currentRunId,
          title: title,
          created_at: new Date().toISOString()
        }
      })
      safeDispatchEvent(event)
    }

    // 关键修复：发送时附带 runId，以确保追加到同一会话
    await processChatRequest(newMessages, currentRunId || undefined)
  }

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      setIsStreaming(false)
      setIsLoading(false)
    }
  }

  const isNewChat = messages.length === 0

  return (
    <div className="h-full flex flex-col relative bg-surface">
      {/* 消息区域 */}
      <div className={`flex-1 overflow-hidden relative ${isNewChat ? "hidden" : "block"}`}>
        <ScrollArea ref={scrollRef} className="h-full px-4 py-8 md:px-10 bg-surface">
          <div className="space-y-8 pb-6 max-w-4xl mx-auto">
            {messages.map((msg, index) => (
              <div key={msg.id ?? index} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`flex flex-col min-w-0 max-w-[92%] md:max-w-[78%] ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div
                    className={
                      msg.role === "user"
                        ? "px-5 py-3 rounded-2xl bg-cta/10 text-content text-base leading-7"
                        : "text-content w-full min-w-0 overflow-hidden text-base"
                    }
                  >
                                {msg.role === 'user' ? (
                                    msg.content
                                ) : (
                                    <>
                                        <AssistantMessageBody
                                          msg={msg}
                                          index={index}
                                          messagesLength={messages.length}
                                          isStreaming={isStreaming}
                                          streamProgressList={streamProgressList}
                                        />
                                        <div className="flex items-center gap-2 mt-3">
                                            <Button 
                                                type="button"
                                                variant="ghost" 
                                                size="icon" 
                                                className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                                                onClick={async () => {
                                                  try {
                                                    await copyToClipboard(msg.content || "")
                                                    toast.success("已复制到剪贴板")
                                                  } catch (e) {
                                                    console.error("Copy failed", e)
                                                    toast.error("复制失败（浏览器限制）")
                                                  }
                                                }}
                                                title="复制内容"
                                                aria-label="复制内容"
                                            >
                                                <Copy className="w-3.5 h-3.5" />
                                            </Button>
                                            {index === messages.length - 1 && !isLoading && (
                                                <Button 
                                                    type="button"
                                                    variant="ghost" 
                                                    size="icon" 
                                                    className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                                                    onClick={handleRegenerate}
                                                    title="重新生成"
                                                    aria-label="重新生成"
                                                >
                                                    <RefreshCw className="w-3.5 h-3.5" />
                                                </Button>
                                            )}
                                        </div>
                                    </>
                                )}
                  </div>

                  {msg.role === "user" && (
                    <div className="flex items-center gap-2 mt-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                        onClick={async () => {
                          try {
                            await copyToClipboard(msg.content || "")
                            toast.success("已复制到剪贴板")
                          } catch (e) {
                            console.error("Copy failed", e)
                            toast.error("复制失败（浏览器限制）")
                          }
                        }}
                        title="复制内容"
                        aria-label="复制内容"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </Button>
                    </div>
                  )}
                </div>
              </div>
            ))}
                
                {/* Thinking 状态由 ThinkingProcess 统一承载（避免重复的小气泡提示） */}
          </div>
        </ScrollArea>

        {/* 回到底部（用户上翻时出现） */}
        {showJumpToBottom && (
          <div className="absolute left-1/2 -translate-x-1/2 bottom-6 z-10">
            <button
              type="button"
              onClick={() => {
                autoScrollRef.current = true
                setShowJumpToBottom(false)
                scrollToBottom("smooth")
              }}
              className="min-h-[44px] h-10 px-4 py-2 rounded-full bg-surface/90 backdrop-blur border border-line shadow-sm text-content hover:bg-surface hover:shadow transition flex items-center gap-2 cursor-pointer touch-manipulation"
              aria-label="回到底部"
              title="回到底部"
            >
              <ArrowDown className="w-4 h-4" />
              <span className="text-sm">回到底部</span>
            </button>
          </div>
        )}
      </div>

      {/* 新对话居中视图 */}
      {isNewChat && (
        <div className="flex-1 flex flex-col items-center justify-center p-4 sm:-mt-20">
             <div className="flex items-center gap-3 mb-8">
                 <div className="w-10 h-10 bg-surface border border-line shadow-sm rounded-xl flex items-center justify-center text-cta font-bold text-xl" aria-hidden="true">D</div>
                 <h1 className="text-2xl font-semibold text-content">今天有什么可以帮到你？</h1>
            </div>
            
            <div className="w-full px-4 md:px-10">
              <div className="max-w-4xl mx-auto">
                <ChatInput
                  value={input}
                  onChange={setInput}
                  onSend={handleSend}
                  onStop={handleStop}
                  isLoading={isLoading}
                  isStreaming={isStreaming}
                />
              </div>
            </div>
        </div>
      )}

      {/* 底部输入框 (仅在有消息时显示) */}
      {!isNewChat && (
        <div className="w-full px-4 md:px-10 py-6 bg-transparent">
          <div className="max-w-4xl mx-auto">
            <ChatInput
              value={input}
              onChange={setInput}
              onSend={handleSend}
              onStop={handleStop}
              isLoading={isLoading}
              isStreaming={isStreaming}
            />
            <div className="text-center mt-3 text-xs text-content-muted">
              内容由 AI 生成，请仔细甄别
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default function ChatPage() {
  return (
    <Suspense fallback={
        <div className="flex h-full items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-content-muted" />
        </div>
    }>
        <ChatContent />
    </Suspense>
  )
}
