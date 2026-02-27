"use client"

// Next.js requires useSearchParams() to be wrapped in Suspense.
// We make this page dynamic to avoid prerender failures in production builds.
export const dynamic = "force-dynamic"

import React, { useState, useRef, useEffect, Suspense, memo, Fragment } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import {
  ArrowDown,
  ArrowUp,
  Bot,
  StopCircle,
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
import Cookies from "js-cookie"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"
import rehypeKatex from "rehype-katex"
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { HTMLAttributes, ReactNode } from "react"
import { REFRESH_CHAT_LIST_EVENT, NewChatEventDetail } from "@/lib/events"
import { ChartBlock } from "@/components/chart-block/index"
import { MermaidBlock } from "@/components/mermaid-block/index"

type MarkdownCodeProps = HTMLAttributes<HTMLElement> & {
  inline?: boolean
  className?: string
  children?: ReactNode
}

function handleUnauthorized() {
  Cookies.remove("dac_token")
  if (typeof window !== "undefined") {
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    const next = `${path}${search}${hash}`
    window.location.href = `/login?next=${encodeURIComponent(next)}`
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

function normalizeGfmTables(input: string) {
  // GFM tables often fail to parse if they directly follow a non-empty line.
  // Ensure there's a blank line before the table header (but never touch fenced code blocks).
  const lines = input.split("\n")
  const out: string[] = []
  let inFence = false

  const isFence = (line: string) => /^\s*```/.test(line)
  const isSeparator = (line: string) => {
    const t = line.trim()
    if (!t.includes("|") || !t.includes("-")) return false
    return /^[|:\-\s]+$/.test(t)
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const next = i + 1 < lines.length ? lines[i + 1] : ""

    if (isFence(line)) inFence = !inFence

    const looksLikeTableHeader = !inFence && line.includes("|") && isSeparator(next)
    const prev = out.length ? out[out.length - 1] : ""
    const prevNonEmpty = prev.trim().length > 0

    if (looksLikeTableHeader && prevNonEmpty) {
      out.push("")
    }
    out.push(line)
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

interface Message {
  role: "user" | "assistant" | "system"
  content: string
  reasoning_content?: string
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
}: {
  content: string
  isThinking?: boolean
  isLive?: boolean
}) => {
  const [userExpanded, setUserExpanded] = useState(false)
  const startedAtRef = useRef<number | null>(null)
  const [duration, setDuration] = useState(0)

  const parsed = (() => {
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
        // Preserve empty lines inside an ongoing answer capture.
        if (currentTaskKey) {
          const exec = ensureExec(currentTaskKey)
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
        const agent = mAgent?.[2]?.trim()

        const base = `${planEpoch}:${id}`
        const seq = (execKeySeq.get(base) || 0) + 1
        execKeySeq.set(base, seq)
        const key = `${base}:${seq}`

        const exec = ensureExec(key, id)
        exec.text = exec.text || text
        exec.agent = exec.agent || agent
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
  })()

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

  // If we're not thinking and there's no content to show, don't render.
  // While thinking, render a placeholder header even if content is still empty.
  if (!isThinking && !content) return null

  // During live generation, keep it expanded by default.
  const isExpanded = Boolean(isLive) || Boolean(isThinking) ? true : userExpanded
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
          : "inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-50 text-slate-700 border border-slate-200"
      }
    >
      {children}
    </span>
  )

  const AgentChip = ({ name }: { name: string }) => (
    <Chip>
      <Bot className="w-3 h-3 text-slate-500" />
      <span className="text-[11px] leading-5">{name}</span>
    </Chip>
  )

  const StatusMark = ({
    state,
  }: {
    state: "idle" | "running" | "done" | "warn" | "fail"
  }) => {
    if (state === "running") return <Loader2 className="w-3.5 h-3.5 animate-spin text-slate-400" />
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
          : "flex items-center gap-2 py-1 text-slate-900"
      }
    >
      {icon !== undefined ? icon : <ChevronRight className="w-4 h-4 text-slate-400 shrink-0 group-open/section:rotate-90 transition-transform" />}
      <div className="flex-1 text-[12px] font-medium">{title}</div>
      {right ? <div className="shrink-0">{right}</div> : null}
    </div>
  )

  const chevronIcon = (open: boolean, className = "w-4 h-4 text-slate-400 shrink-0") =>
    open ? <ChevronDown className={className} /> : <ChevronRight className={className} />

  const CollapsibleSection = ({
    defaultOpen = false,
    summary,
    children,
    className = "",
    summaryClassName = "list-none [&::-webkit-details-marker]:hidden cursor-pointer select-none rounded-md -ml-1 px-1 hover:bg-slate-50 transition-colors",
  }: {
    defaultOpen?: boolean
    summary: (open: boolean) => ReactNode
    children: ReactNode
    className?: string
    summaryClassName?: string
  }) => {
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

  const ShimmerLine = ({ w = "w-full" }: { w?: string }) => (
    <div className={`relative overflow-hidden h-3 rounded bg-slate-200/60 ${w}`}>
      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/60 to-transparent [animation:dacShimmer_1.2s_infinite] will-change-transform" />
    </div>
  )

  return (
    <div className="mb-3">
      <style jsx global>{`
        @keyframes dacShimmer {
          0% {
            transform: translateX(-100%);
          }
          100% {
            transform: translateX(100%);
          }
        }
      `}</style>
      <button
        type="button"
        className="w-full flex items-center py-2 text-left transition-colors select-none"
        onClick={() => setUserExpanded((v) => !v)}
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2 text-base text-slate-700">
          {isThinking ? (
            <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
          ) : (
            <BrainCircuit className="w-4 h-4 text-blue-600" />
          )}
          <span className="font-medium flex items-center gap-1.5">
            <span>
              {isThinking ? "思考中" : "已思考"}
              {duration > 0 ? <span className="text-slate-500 font-normal">（用时 {duration} 秒）</span> : null}
            </span>
            <span className="text-slate-400">
              {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </span>
          </span>
        </div>
      </button>

      {isExpanded ? (
        <div className="mt-2 pl-3 border-l border-slate-100/80 text-[13px] text-slate-700 leading-6">
          {isThinking && !(parsed.raw || "").trim() ? (
            <div className="mt-1">
              <div className="text-[12px] text-slate-500 flex items-center gap-2">
                <span>正在生成规划与任务过程</span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="inline-block w-1 h-1 rounded-full bg-slate-400 animate-pulse" />
                  <span className="inline-block w-1 h-1 rounded-full bg-slate-400 animate-pulse [animation-delay:150ms]" />
                  <span className="inline-block w-1 h-1 rounded-full bg-slate-400 animate-pulse [animation-delay:300ms]" />
                </span>
              </div>
              <div className="mt-3 space-y-2">
                <ShimmerLine w="w-2/3" />
                <ShimmerLine w="w-5/6" />
                <ShimmerLine w="w-1/2" />
              </div>
            </div>
          ) : null}

          <div className="text-[12px] text-slate-600">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-slate-800">概览</span>
              {parsed.started.plan || (parsed.planBlocks || []).length > 0 ? (
                <Chip>规划 {(parsed.planBlocks || []).length > 0 ? (parsed.planBlocks || []).length : "…"}</Chip>
              ) : null}
              {parsed.started.exec || parsed.exec.length > 0 ? (
                <Chip>任务 {parsed.exec.length > 0 ? parsed.exec.length : "…"}</Chip>
              ) : null}
              {parsed.started.flow || (parsed.flow || []).length > 0 ? (
                <Chip>重规划 {(parsed.flow || []).length > 0 ? (parsed.flow || []).length : "…"}</Chip>
              ) : null}
              {/* "运行日志" 已并入 "执行"；不再单独展示 */}
              {parsed.completions.length > 0 ? <Chip tone="success">已完成</Chip> : null}
            </div>
            <div className="h-px bg-slate-200/70 mt-2" />
          </div>

          <div className="mt-2 space-y-2">
            {/* Plan blocks are part of execution; no separate "计划" section. */}

            {parsed.exec.length > 0 || parsed.started.exec ? (
              <CollapsibleSection
                defaultOpen={!!isLive}
                className="group/section"
                summary={(open) => (
                  <SummaryRow
                    icon={chevronIcon(open)}
                    title={
                      <span className="inline-flex items-center gap-2">
                        <StatusMark
                          state={
                            reasoningActive
                              ? "running"
                              : parsed.exec.length > 0
                                ? "done"
                                : "idle"
                          }
                        />
                        <span>规划</span>
                      </span>
                    }
                  />
                )}
              >
                {/* Reuse the original task UI; show hierarchy by plan blocks.
                    Plan -> (tasks / retries / failure analysis ...) in backend order. */}
                {(parsed.execNodes || []).length > 0 ? (
                  <div className="mt-2 space-y-2">
                    {(() => {
                      const nodes = (parsed.execNodes || []) as Array<
                        | { type: "plan"; planBlockIndex: number }
                        | { type: "flow"; flowIndex: number }
                        | { type: "marker"; text: string }
                        | { type: "task"; taskKey: string }
                      >
                      type Group = { planIdx: number; title: string; items: any[]; nodes: typeof nodes; parentTaskKey?: string }
                      const groups: Group[] = []
                      let current: Group | null = null

                      for (const n of nodes) {
                        if (n.type === "plan") {
                          const b = (parsed.planBlocks || [])[n.planBlockIndex]
                          const title = b?.title || "任务"
                          const items = b?.items || []
                          const parentTaskKey = b?.parentTaskKey
                          current = { planIdx: n.planBlockIndex, title, items, nodes: [], parentTaskKey }
                          groups.push(current)
                          continue
                        }
                        if (!current) {
                          current = { planIdx: -1, title: "任务", items: [], nodes: [] }
                          groups.push(current)
                        }
                        current.nodes.push(n)
                      }

                      const lastNode = nodes[nodes.length - 1] || null
                      const topLevelGroups = groups.filter((gr) => !gr.parentTaskKey)

                      const renderPlanGroup = (g: Group, keyPrefix: string): ReactNode => {
                        const planCount = (g.items || []).length
                        return (
                          <CollapsibleSection
                            key={keyPrefix}
                            defaultOpen={!!isLive}
                            className="group/plan pl-3 border-l border-slate-100/80"
                            summary={(open) => (
                              <div className="flex items-center gap-2">
                                {chevronIcon(open)}
                                <StatusMark state={!isLive && planCount > 0 ? "done" : "idle"} />
                                <span className="text-slate-800 text-[12px] font-medium flex-1 truncate">
                                  {String(g.title || "").replaceAll("新计划", "重规划").replaceAll("新规划", "重规划").replaceAll("任务计划", "任务")}
                                </span>
                              </div>
                            )}
                          >

                            {planCount > 0 ? (
                              <ul className="mt-2 space-y-1">
                                {g.items.map((t: any) => (
                                  <li key={`${g.title}:${t.id}:${t.text}:${t.agent || ""}`} className="flex items-start gap-2">
                                    <span className="text-slate-400 font-mono shrink-0">[{t.id}]</span>
                                    <span className="text-slate-700 flex-1">{t.text}</span>
                                    {t.agent ? <AgentChip name={t.agent} /> : null}
                                  </li>
                                ))}
                              </ul>
                            ) : isLive ? (
                              <div className="mt-2 space-y-2">
                                <ShimmerLine w="w-5/6" />
                                <ShimmerLine w="w-2/3" />
                              </div>
                            ) : (
                              <div className="mt-2 text-[12px] text-slate-500">暂无任务输出</div>
                            )}

                            {g.nodes.length > 0 ? (
                                  <div className="mt-2 space-y-2">
                                    {g.nodes.map((n) => {
                                      if (n.type === "flow") {
                                        const x = (parsed.flow || [])[n.flowIndex]
                                        if (!x) return null
                                        const title = String(x.title || "事件")
                                        const body = String(x.body || "")
                                        const lines = body ? body.split("\n").filter((l) => l.trim().length > 0).length : 0
                                        const isLast = lastNode != null && n === lastNode
                                        const kind = x.kind

                                        const parseFailureAnalysis = (rawText: string) => {
                                          const txt = String(rawText || "").replace(/\r\n/g, "\n")
                                          const ls = txt.split("\n")
                                          const taskLine = ls.find((l) => /^\s*Task\s+\d+\s*\(/i.test(l)) || ""
                                          const queryLine =
                                            ls.find((l) => /\bquery\s*:/i.test(l) && /step\s*\d+\s*\/\s*\d+\s*:/i.test(l)) ||
                                            ls.find((l) => /^\s*query\s*:/i.test(l)) ||
                                            ""
                                          const answerIdx = ls.findIndex((l) => /^\s*answer\s*:\s*/i.test(l))
                                          const answerLines = answerIdx >= 0 ? ls.slice(answerIdx) : []
                                          const answerBody = answerLines
                                            .join("\n")
                                            .replace(/^\s*answer\s*:\s*/i, "")
                                            .trim()
                                          const taskMatch = taskLine.match(
                                            /^\s*Task\s+(\d+)\s*\((.*?)\)\s*assign\s+to\s*([A-Za-z0-9_]+).*?fail\.?/i,
                                          )
                                          return {
                                            taskId: taskMatch?.[1] || "",
                                            taskText: taskMatch?.[2] || "",
                                            agent: taskMatch?.[3] || "",
                                            taskLine: taskLine.trim(),
                                            queryText: String(queryLine || "")
                                              .replace(/^.*?\bquery\s*:\s*/i, "")
                                              .trim(),
                                            answerBody,
                                          }
                                        }

                                        // Failure analysis is always expanded (no fold UI).
                                        if (kind === "analysis") {
                                          const meaningful = String(body || "")
                                            .split("\n")
                                            .filter((l) => !/^\s*失败分析[:：]?\s*$/i.test(l.trim()))
                                            .join("\n")
                                            .trim()
                                          const p = parseFailureAnalysis(meaningful)
                                          return (
                                            <div
                                              key={`flow:${n.flowIndex}:${title}`}
                                              className="pl-3 border-l border-slate-100/80"
                                            >
                                              <div className="flex items-center gap-2 py-1">
                                                <StatusMark state={meaningful ? "fail" : (isLive ? "running" : "idle")} />
                                                <span className="text-slate-800 text-[12px] font-medium flex-1 truncate" title={title}>
                                                  {title}
                                                </span>
                                                {lines > 0 ? <Chip>{lines} 行</Chip> : null}
                                              </div>

                                              {p.taskLine ? (
                                                <div className="mt-1 text-[12px] text-slate-700">
                                                  <div className="flex items-center gap-2">
                                                    {p.taskId ? (
                                                      <span className="text-slate-400 font-mono shrink-0">[{p.taskId}]</span>
                                                    ) : null}
                                                    <span className="flex-1 truncate" title={p.taskText || p.taskLine}>
                                                      {p.taskText || p.taskLine}
                                                    </span>
                                                    {p.agent ? <AgentChip name={p.agent} /> : null}
                                                  </div>
                                                </div>
                                              ) : null}

                                              {p.queryText ? (
                                                <div className="mt-2 pl-3 border-l border-slate-200/80">
                                                  <div className="text-[11px] font-medium text-slate-700">Query</div>
                                                  <div className="mt-1 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                                                    {p.queryText}
                                                  </div>
                                                </div>
                                              ) : null}

                                              {p.answerBody ? (
                                                <div className="mt-2 pl-3 border-l border-blue-200/70">
                                                  <div className="text-[11px] font-medium text-slate-700">输出</div>
                                                  <pre className="mt-1 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                                                    {p.answerBody}
                                                  </pre>
                                                </div>
                                              ) : meaningful ? (
                                                <pre className="mt-2 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                                                  {meaningful}
                                                </pre>
                                              ) : isLive ? (
                                                <div className="mt-2 space-y-2">
                                                  <ShimmerLine w="w-5/6" />
                                                  <ShimmerLine w="w-2/3" />
                                                </div>
                                              ) : (
                                                <div className="mt-2 text-[12px] text-slate-500">暂无输出</div>
                                              )}
                                            </div>
                                          )
                                        }

                                        return (
                                          <CollapsibleSection
                                            key={`flow:${n.flowIndex}:${title}`}
                                            defaultOpen={!!(isLive && isLast)}
                                            className="group/ctl pl-3 border-l border-slate-100/80"
                                            summary={(open) => (
                                              <div className="flex items-center gap-2">
                                                {chevronIcon(open)}
                                                <StatusMark state={reasoningActive && isLast ? "running" : body ? "done" : "idle"} />
                                                <span className="text-slate-800 text-[12px] font-medium flex-1 truncate" title={title}>
                                                  {title}
                                                </span>
                                                {lines > 0 ? <Chip>{lines} 行</Chip> : null}
                                              </div>
                                            )}
                                          >
                                            {body ? (
                                              <div className="mt-2 text-[12px] leading-5 text-slate-700 prose prose-slate max-w-none prose-pre:my-1 prose-pre:p-2 prose-pre:bg-slate-50 prose-pre:rounded prose-code:before:content-none prose-code:after:content-none prose-code:text-[11px]">
                                                <MarkdownAnswer value={wrapReasoningCodeRefs(body)} />
                                              </div>
                                            ) : isLive ? (
                                              <div className="mt-2 space-y-2">
                                                <ShimmerLine w="w-5/6" />
                                                <ShimmerLine w="w-2/3" />
                                              </div>
                                            ) : (
                                              <div className="mt-2 text-[12px] text-slate-500">暂无输出</div>
                                            )}
                                          </CollapsibleSection>
                                        )
                                      }

                                      if (n.type === "marker") {
                                        const title = String(n.text || "").trim()
                                        const isLast = lastNode != null && n === lastNode
                                        if (!title) return null
                                        const lower = title.toLowerCase()
                                        const isWarn =
                                          title.startsWith("⚠️") ||
                                          lower.includes("遇到问题") ||
                                          lower.includes("停止重试") ||
                                          lower.includes("重试")
                                        const isFail =
                                          lower.includes("失败") && !lower.includes("失败分析")
                                        const state =
                                          reasoningActive && isLast
                                            ? "running"
                                            : isFail
                                              ? "fail"
                                              : isWarn
                                                ? "warn"
                                                : "idle"
                                        return (
                                          <div
                                            key={`marker:${title}:${isLast ? "last" : ""}`}
                                            className="pl-3 border-l border-slate-100/80"
                                          >
                                            <div className="flex items-center gap-2 py-1">
                                              <StatusMark state={state} />
                                              <div className="text-[12px] text-slate-700 font-medium flex-1 truncate" title={title}>
                                                {title}
                                              </div>
                                            </div>
                                          </div>
                                        )
                                      }

                                      if (n.type === "task") {
                                        const t = parsed.execMap?.get(n.taskKey)
                                        if (!t) return null
                                        const childGroups = groups.filter((gr) => gr.parentTaskKey === n.taskKey)
                                        return (
                                          <Fragment key={`task-wrap-${t.key}`}>
                                            <CollapsibleSection
                                              key={`task-${t.key}`}
                                              defaultOpen={!!(isLive && parsed.activeTaskKey === t.key)}
                                              className="group/task pl-3 border-l border-slate-100/80"
                                              summary={(open) => (
                                                <div className="flex items-center gap-2">
                                                  {chevronIcon(open)}
                                                  <StatusMark
                                                    state={
                                                      reasoningActive && parsed.activeTaskKey === t.key
                                                        ? "running"
                                                        : !isLive && (t.answers.length > 0 || t.steps.length > 0)
                                                          ? "done"
                                                          : "idle"
                                                    }
                                                  />
                                                  <span className="text-slate-400 font-mono shrink-0">[{t.id}]</span>
                                                  <span className="text-slate-800 text-[12px] font-medium flex-1 truncate">
                                                    {t.text || "-"}
                                                  </span>
                                                  {t.agent ? <AgentChip name={t.agent} /> : null}
                                                  {t.steps.length > 0 ? <Chip>steps {t.steps.length}</Chip> : null}
                                                </div>
                                              )}
                                            >

                                            {(t.query || "").trim() ? (
                                              <div className="mt-2 pl-3 border-l border-slate-200/80">
                                                <div className="text-[11px] font-medium text-slate-700">Query</div>
                                                <div className="mt-1 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                                                  {t.query}
                                                </div>
                                              </div>
                                            ) : null}

                                            {t.answers.length > 0 ||
                                            (t.inProgressAnswer || "").trim() ||
                                            (isLive && parsed.activeTaskKey === t.key) ? (
                                              <div className="mt-2 pl-3 border-l border-blue-200/70">
                                                <div className="text-[11px] font-medium text-slate-700">输出</div>
                                                <div className="mt-1 space-y-2 prose prose-slate max-w-none prose-pre:my-1 prose-code:before:content-none prose-code:after:content-none prose-code:text-[11px]">
                                                  {t.answers.map((a, idx) => (
                                                    <div key={`${t.id}:answer:${idx}`} className="text-[12px] leading-5 text-slate-700">
                                                      <MarkdownAnswer value={wrapReasoningCodeRefs(a)} />
                                                    </div>
                                                  ))}
                                                  {(t.inProgressAnswer || "").trim() ? (
                                                    <div className="text-[12px] leading-5 text-slate-700">
                                                      <MarkdownAnswer value={wrapReasoningCodeRefs(t.inProgressAnswer ?? "")} />
                                                      <div className="mt-2 space-y-1">
                                                        <ShimmerLine w="w-2/3" />
                                                      </div>
                                                    </div>
                                                  ) : isLive && parsed.activeTaskKey === t.key ? (
                                                    <div className="mt-2 space-y-2">
                                                      <ShimmerLine w="w-5/6" />
                                                      <ShimmerLine w="w-2/3" />
                                                    </div>
                                                  ) : null}
                                                </div>
                                              </div>
                                            ) : null}

                                            {t.steps.length > 0 ? (
                                              <ul className="mt-2 space-y-1">
                                                {t.steps.map((s, idx) => (
                                                  <li key={`${t.id}:${idx}:${s.idx}`} className="text-slate-700">
                                                    <span className="text-slate-400 font-mono mr-2">
                                                      {s.idx}/{s.total}
                                                    </span>
                                                    <span className="font-mono text-[12px]">{s.text}</span>
                                                  </li>
                                                ))}
                                              </ul>
                                            ) : isLive && parsed.activeTaskKey === t.key && !(t.query || "").trim() ? (
                                              <div className="mt-2 space-y-2">
                                                <ShimmerLine w="w-1/2" />
                                                <ShimmerLine w="w-2/3" />
                                              </div>
                                            ) : !(t.query || "").trim() ? (
                                              <div className="mt-2 text-[12px] text-slate-500">暂无 step 输出</div>
                                            ) : null}

                                            {t.logs.length > 0 ? (
                                              <CollapsibleSection
                                                defaultOpen={false}
                                                className="group/sub mt-2"
                                                summary={(open) => (
                                                  <div className="flex items-center gap-2 py-1 text-slate-900">
                                                    {chevronIcon(open)}
                                                    <div className="flex-1 text-[12px] font-medium">该任务原始日志</div>
                                                  </div>
                                                )}
                                              >
                                                <pre className="mt-2 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                                                  {t.logs.join("\n")}
                                                </pre>
                                              </CollapsibleSection>
                                            ) : null}
                                            </CollapsibleSection>
                                            {childGroups.length > 0 ? (
                                              <div className="mt-2 pl-3 border-l border-slate-100/80 space-y-2">
                                                {childGroups.map((gr, i) => renderPlanGroup(gr, `plan-${n.taskKey}-${i}`))}
                                              </div>
                                            ) : null}
                                          </Fragment>
                                        )
                                      }
                                      return null
                                    })}
                                  </div>
                                ) : null}
                          </CollapsibleSection>
                        )
                      }

                      return (
                        <div className="space-y-2">
                          {topLevelGroups.map((g, gIdx) => renderPlanGroup(g, `plan-top-${gIdx}`))}
                        </div>
                      )
                    })()}
                  </div>
                ) : parsed.started.exec && isLive ? (
                  <div className="mt-2 space-y-2 pl-3 border-l border-slate-100/80">
                    <ShimmerLine w="w-5/6" />
                    <ShimmerLine w="w-3/4" />
                  </div>
                ) : parsed.started.exec ? (
                  <div className="mt-2 text-[12px] text-slate-500">暂无执行输出</div>
                ) : null}
              </CollapsibleSection>
            ) : null}

            {/* "运行日志" 已并入 "执行"；不再单独渲染 */}

            <CollapsibleSection
              defaultOpen={false}
              className="group/section"
              summary={(open) => <SummaryRow icon={chevronIcon(open)} title="原始日志" />}
            >
              <pre className="mt-2 text-[12px] leading-5 text-slate-700 whitespace-pre-wrap">
                {parsed.raw || ""}
              </pre>
            </CollapsibleSection>
          </div>
        </div>
      ) : null}
    </div>
  )
}

// 代码块组件（带复制功能）
const CodeBlock = ({ language, children }: { language: string, children: string }) => {
  const [copied, setCopied] = useState(false)

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
      <div className="flex items-center justify-between px-3 py-1.5 bg-[#252526] border-b border-slate-700 text-xs text-slate-400 select-none">
        <span className="font-mono">{language || 'text'}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1.5 hover:text-white transition-colors"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-400" /> : <Copy className="w-3.5 h-3.5" />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <SyntaxHighlighter
        language={language}
        style={vscDarkPlus}
        customStyle={{ margin: 0, padding: '1rem', fontSize: '0.875rem', lineHeight: '1.5' }}
        wrapLines={true}
        wrapLongLines={true} 
      >
        {children}
      </SyntaxHighlighter>
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
        className="bg-slate-100 px-1 py-0.5 rounded text-[12px] font-mono text-slate-700 border border-slate-200"
        {...props}
      >
        {children}
      </code>
    )
  },
  p({children}: { children?: ReactNode }) {
    return <p className="text-sm text-slate-700 leading-6 mb-2 last:mb-0">{children}</p>
  },
  ul({children}: { children?: ReactNode }) {
    return <ul className="text-sm text-slate-700 leading-6 list-disc pl-5 space-y-1 my-2">{children}</ul>
  },
  ol({children}: { children?: ReactNode }) {
    return <ol className="text-sm text-slate-700 leading-6 list-decimal pl-5 space-y-1 my-2">{children}</ol>
  },
  li({children}: { children?: ReactNode }) {
    return <li className="pl-1 marker:text-slate-400">{children}</li>
  },
  // 标题（h1-h6）- 渐进式字号和间距
  h1({children}: { children?: ReactNode }) {
    return <h1 className="text-xl font-semibold text-slate-900 mt-6 mb-3">{children}</h1>
  },
  h2({children}: { children?: ReactNode }) {
    return <h2 className="text-lg font-semibold text-slate-900 mt-5 mb-2.5">{children}</h2>
  },
  h3({children}: { children?: ReactNode }) {
    return <h3 className="text-base font-semibold text-slate-900 mt-4 mb-2">{children}</h3>
  },
  h4({children}: { children?: ReactNode }) {
    return <h4 className="text-sm font-semibold text-slate-900 mt-3 mb-2">{children}</h4>
  },
  h5({children}: { children?: ReactNode }) {
    return <h5 className="text-sm font-semibold text-slate-700 mt-3 mb-2">{children}</h5>
  },
  h6({children}: { children?: ReactNode }) {
    return <h6 className="text-sm font-semibold text-slate-600 mt-3 mb-2">{children}</h6>
  },
  // 链接 - 蓝色可点击，外部链接新窗口打开
  a({href, children}: { href?: string; children?: ReactNode }) {
    const isExternal = href?.startsWith('http')
    return (
      <a 
        href={href}
        className="text-blue-600 hover:text-blue-800 underline cursor-pointer transition-colors"
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
      >
        {children}
      </a>
    )
  },
  // 引用块 - 左侧竖线 + 浅色背景
  blockquote({children}: { children?: ReactNode }) {
    return <blockquote className="border-l-4 border-slate-200 pl-4 py-2 my-3 italic text-sm text-slate-600 bg-slate-50 rounded-r">{children}</blockquote>
  },
  // 分隔线
  hr() {
    return <hr className="border-slate-300 my-6" />
  },
  // 强调 - 明确样式
  strong({children}: { children?: ReactNode }) {
    return <strong className="font-bold text-slate-900">{children}</strong>
  },
  em({children}: { children?: ReactNode }) {
    return <em className="italic text-slate-700">{children}</em>
  },
  // 删除线 - GFM 支持
  del({children}: { children?: ReactNode }) {
    return <del className="line-through text-slate-400">{children}</del>
  },
  // 表格 - 使用现代样式
  table({children}: { children?: ReactNode }) {
    return <div className="overflow-x-auto my-4"><table className="min-w-full border-collapse border border-slate-200">{children}</table></div>
  },
  thead({children}: { children?: ReactNode }) {
    return <thead className="bg-slate-50">{children}</thead>
  },
  tbody({children}: { children?: ReactNode }) {
    return <tbody className="bg-white divide-y divide-slate-200">{children}</tbody>
  },
  tr({children}: { children?: ReactNode }) {
    return <tr className="hover:bg-slate-50 transition-colors">{children}</tr>
  },
  th({children}: { children?: ReactNode }) {
    return <th className="border border-slate-200 px-4 py-2 text-left text-sm font-semibold text-slate-700">{children}</th>
  },
  td({children}: { children?: ReactNode }) {
    return <td className="border border-slate-200 px-4 py-2 text-sm text-slate-600">{children}</td>
  }
}

const MarkdownAnswer = memo(function MarkdownAnswer({ value }: { value: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={MARKDOWN_REMARK_PLUGINS}
      rehypePlugins={MARKDOWN_REHYPE_PLUGINS}
      components={MARKDOWN_COMPONENTS}
    >
      {value}
    </ReactMarkdown>
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

  // 加载历史会话
  useEffect(() => {
    const fetchHistory = async () => {
      // Switching conversation: stop any in-flight stream to avoid "cross-thread" appends.
      // IMPORTANT: When creating a brand new chat, we update URL with run_id and start streaming.
      // That run_id change should NOT cancel the in-flight request for the same run_id.
      const nextRunId = runId
      const inFlightRunId = inFlightRunIdRef.current
      const isSameConversation = Boolean(nextRunId && inFlightRunId && nextRunId === inFlightRunId)

      if (!isSameConversation && abortControllerRef.current) {
        abortControllerRef.current.abort()
        abortControllerRef.current = null
        requestSeqRef.current += 1 // invalidate any in-flight stream loops
        setIsStreaming(false)
        setIsLoading(false)
      }

      activeRunIdRef.current = nextRunId

      if (!runId) {
        setMessages([])
        return
      }

      // If we are streaming the very first message for an optimistically created run_id,
      // there is nothing to "load" yet and the backend may transiently 404.
      if (isSameConversation && isStreamingRef.current && messagesRef.current.length > 0) {
        return
      }

      try {
        const token = Cookies.get("dac_token")
        const response = await fetch(`/api/v1/chat/conversations/${runId}`, {
          headers: {
            "Authorization": token ? `Bearer ${token}` : "",
          },
        })

      if (response.status === 401) {
        handleUnauthorized()
        return
      }

        if (!response.ok) {
          if (response.status === 404) {
            // For optimistically created runs, the conversation may not exist yet.
            if (optimisticRunIdsRef.current.has(runId)) {
              return
            }
            // Otherwise, treat as invalid run_id navigation.
            console.warn("Conversation not found, redirecting to new chat")
            router.replace("/")
            return
          }
          console.error("Failed to load history:", response.statusText)
          return
        }

        const data = await response.json()
        if (data && data.messages) {
            // 转换后端消息格式到前端格式
            const rawMessages = Array.isArray(data.messages) ? (data.messages as unknown[]) : []
            const historyMessages: Message[] = rawMessages
              .map((m): Message | null => {
                const r = typeof m === "object" && m !== null ? (m as Record<string, unknown>) : {}
                const role = r.role
                const content = r.content
                if (
                  (role !== "user" && role !== "assistant" && role !== "system") ||
                  typeof content !== "string"
                ) {
                  return null
                }
                const think = typeof r.think === "string" ? r.think : undefined
                const reasoning = typeof r.reasoning_content === "string" ? r.reasoning_content : undefined
                return {
                  role,
                  content,
                  reasoning_content: think || reasoning,
                }
              })
              .filter((x): x is Message => Boolean(x))
            setMessages(historyMessages)
        }
      } catch (error) {
        console.error("Error loading history:", error)
        toast.error("加载历史会话失败")
      }
    }

    fetchHistory()
  }, [runId])

  const scrollToBottom = (behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
  }

  const resumeAutoScroll = (behavior: ScrollBehavior = "auto") => {
    autoScrollRef.current = true
    setShowJumpToBottom(false)
    // Ensure we scroll after DOM paints (important when switching from "new chat" view).
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        scrollToBottom(behavior)
      })
    })
  }

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

  // When messages update, keep following only if user hasn't scrolled up.
  useEffect(() => {
    if (!autoScrollRef.current) return
    // While streaming, don't animate (avoids jitter).
    scrollToBottom(isStreaming ? "auto" : "smooth")
  }, [messages, isStreaming])

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
    setMessages([...messagesHistory, { role: "assistant", content: "", reasoning_content: "" }])
    setIsLoading(true)
    setIsStreaming(true)
    
    await processChatRequest(messagesHistory, runId || undefined)
  }

  const processChatRequest = async (messagesPayload: Message[], currentRunId?: string) => {
    const myReqSeq = ++requestSeqRef.current
    inFlightRunIdRef.current = currentRunId || null
    abortControllerRef.current = new AbortController()

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
      const token = Cookies.get("dac_token")

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

      while (!done) {
        const { value, done: doneReading } = await reader.read()
        done = doneReading
        const chunkValue = value ? decoder.decode(value, { stream: true }) : ""
        textBuffer += chunkValue

        const lines = textBuffer.split("\n")
        textBuffer = lines.pop() || ""

        for (const line of lines) {
          if (line.trim() === "") continue
          if (line.trim().startsWith("data:")) {
            const dataStr = line.trim().replace(/^data:\s*/, "")
            if (dataStr === "[DONE]") {
              done = true
              break
            }
            try {
              const data = JSON.parse(dataStr)
              const delta = data.choices?.[0]?.delta || {}
              const content = delta.content ?? ""
              const reasoning = delta.reasoning_content ?? ""
              // 严格按后端顺序追加：返回啥渲染啥，不重排、不猜测
              if (content || reasoning) {
                streamPendingRef.current.content += content
                streamPendingRef.current.reasoning += reasoning
                scheduleFlush()
              }
            } catch (e) {
              console.error("Error parsing stream data", e)
            }
          }
        }
      }

      // Final flush so UI shows the tail immediately.
      clearFlushTimer()
      flushPending()
    } catch (err: unknown) {
      const e = err as { name?: string }
      if (e?.name === "AbortError") {
        console.log("Stream aborted")
      } else {
        console.error("Chat failed", err)
        toast.error("对话请求失败")
        // 如果出错时还没显示气泡，补一个错误提示
        setMessages((prev) => {
             if (myReqSeq !== requestSeqRef.current) return prev
             // 检查最后一条是不是用户发的，如果是，说明 AI 还没回复就挂了
             if (prev.length > 0 && prev[prev.length - 1].role === 'user') {
                 return [...prev, { role: 'assistant', content: "⚠️ Error: Failed to get response." }]
             }
             return prev
        })
      }
    } finally {
      clearFlushTimer()
      // Don't keep leftover deltas around across requests.
      streamPendingRef.current = { content: "", reasoning: "" }
      if (myReqSeq === requestSeqRef.current) {
        setIsLoading(false)
        setIsStreaming(false)
        abortControllerRef.current = null
        inFlightRunIdRef.current = null
      }
    }
  }

  const handleSend = async () => {
    if (!input.trim()) return

    const userMsg: Message = { role: "user", content: input }
    const newMessages = [...messages, userMsg]
    // Insert an empty assistant placeholder immediately so the message-area "思考中" can show
    // before the backend streams the first token.
    resumeAutoScroll("auto")
    setMessages([...newMessages, { role: "assistant", content: "", reasoning_content: "" }])
    setInput("")
    setIsLoading(true)
    setIsStreaming(true)

    let currentRunId = runId
    // Zero-latency update: Generate ID on client if new chat
    if (!currentRunId) {
      currentRunId = safeUUID()
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

  const renderInputBox = () => (
    <div className="relative bg-white rounded-2xl shadow-sm border border-slate-200 transition-all">
        <textarea 
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                }
            }}
            placeholder={isLoading ? "正在思考中..." : "给 DAC 发送消息"}
            className="w-full min-h-[48px] max-h-[160px] border-0 focus:ring-0 resize-none bg-transparent text-[15px] placeholder:text-slate-400 px-4 pt-3 pb-1 focus-visible:outline-none"
            disabled={isLoading}
            rows={1}
            style={{ height: 'auto', minHeight: '48px' }}
            onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = 'auto';
                target.style.height = `${Math.min(target.scrollHeight, 160)}px`;
            }}
        />
        <div className="flex items-center justify-end px-4 pb-3">

          {isStreaming ? (
            <button
              type="button"
              onClick={handleStop}
              className="h-10 w-10 rounded-full bg-slate-100 text-slate-700 hover:bg-slate-200 transition-colors inline-flex items-center justify-center"
              aria-label="停止生成"
              title="停止生成"
            >
              <StopCircle className="w-5 h-5" />
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSend}
              disabled={!input.trim()}
              className="h-10 w-10 rounded-full bg-blue-600 text-white hover:bg-blue-700 disabled:bg-slate-200 disabled:text-slate-400 transition-colors inline-flex items-center justify-center"
              aria-label="发送"
              title="发送"
            >
              <ArrowUp className="w-5 h-5" />
            </button>
          )}
        </div>
    </div>
  )

  return (
    <div className="h-full flex flex-col relative bg-white">
      {/* 消息区域 */}
      <div className={`flex-1 overflow-hidden relative ${isNewChat ? "hidden" : "block"}`}>
        <ScrollArea ref={scrollRef} className="h-full px-4 py-8 md:px-10 bg-white">
          <div className="space-y-8 pb-6 max-w-4xl mx-auto">
            {messages.map((msg, index) => (
              <div key={index} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`flex flex-col max-w-[92%] md:max-w-[78%] ${msg.role === "user" ? "items-end" : "items-start"}`}>
                  <div
                    className={
                      msg.role === "user"
                        ? "px-5 py-3 rounded-2xl bg-blue-50 text-slate-900 border border-blue-100 text-base leading-7"
                        : "text-slate-900 w-full text-base"
                    }
                  >
                                {msg.role === 'user' ? (
                                    msg.content
                                ) : (
                                    <>
                                        {(() => {
                                          const thinking = (msg.reasoning_content || "").trim()
                                          const answer = msg.content || ""
                                          const isThinkingNow =
                                            index === messages.length - 1 && isStreaming && (msg.content || "") === ""
                                          return (
                                            <>
                                              {/* 思维链可视化（reasoning + planning logs） */}
                                              {(thinking || isThinkingNow) && (
                                                <ThinkingProcess
                                                  content={thinking}
                                                  isThinking={isThinkingNow}
                                                  isLive={index === messages.length - 1 && isStreaming}
                                                />
                                              )}

                                              {/* 正文（把 planning logs 从正文里剔除） */}
                                              <MarkdownAnswer value={normalizeGfmTables(normalizeMathDelimiters(answer))} />
                                            </>
                                          )
                                        })()}
                                        <div className="flex items-center gap-2 mt-3">
                                            <Button 
                                                type="button"
                                                variant="ghost" 
                                                size="icon" 
                                                className="h-6 w-6 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md"
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
                                            >
                                                <Copy className="w-3.5 h-3.5" />
                                            </Button>
                                            {index === messages.length - 1 && !isLoading && (
                                                <Button 
                                                    type="button"
                                                    variant="ghost" 
                                                    size="icon" 
                                                    className="h-6 w-6 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md"
                                                    onClick={handleRegenerate}
                                                    title="重新生成"
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
                        className="h-6 w-6 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-md"
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
              className="h-10 px-3 rounded-full bg-white/90 backdrop-blur border border-slate-200 shadow-sm text-slate-700 hover:bg-white hover:shadow transition flex items-center gap-2"
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
        <div className="flex-1 flex flex-col items-center justify-center p-4 -mt-20">
             <div className="flex items-center gap-3 mb-8">
                 <div className="w-10 h-10 bg-white border border-slate-200 shadow-sm rounded-xl flex items-center justify-center text-blue-600 font-bold text-xl">D</div>
                 <h1 className="text-2xl font-semibold text-slate-900">今天有什么可以帮到你？</h1>
            </div>
            
            <div className="w-full px-4 md:px-10">
              <div className="max-w-4xl mx-auto">
                {renderInputBox()}
              </div>
            </div>
        </div>
      )}

      {/* 底部输入框 (仅在有消息时显示) */}
      {!isNewChat && (
        <div className="w-full px-4 md:px-10 py-6 bg-transparent">
          <div className="max-w-4xl mx-auto">
            {renderInputBox()}
            <div className="text-center mt-3 text-xs text-slate-400">
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
            <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
    }>
        <ChatContent />
    </Suspense>
  )
}
