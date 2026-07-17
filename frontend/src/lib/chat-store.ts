"use client"

import { create } from "zustand"
import { toast } from "sonner"
import type { ChatProgressPayload } from "@/lib/api-types"
import { shouldShowProgressItem } from "@/lib/chat-progress"
import { parseHistoryThink } from "@/lib/history-think"
import { parseChatSSELine } from "@/lib/parse-chat-sse"
import { type ChatMessage, type ConversationHistoryResponse } from "@/components/chat/chat-message-types"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"
import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"
import { REFRESH_CHAT_LIST_EVENT, RUN_ID_RECONCILED_EVENT, type NewChatEventDetail } from "@/lib/events"

type Message = ChatMessage

// ── Types ────────────────────────────────────────────────────────────────────

export interface SessionState {
  messages: Message[]
  input: string
  isLoading: boolean
  isStreaming: boolean
  streamProgressList: ChatProgressPayload[]
  /** Wall-clock ms when the current stream started; survives session switches. */
  streamStartedAt: number | null
  /** Frozen thinking duration (seconds) after stream ends. */
  thinkingElapsedSec: number | null
}

/**
 * Per-session mutable state that the SSE loop reads/writes but does NOT trigger
 * React re-renders. Stored outside the Zustand state tree in a module-level Map.
 */
interface SessionInternals {
  abortController: AbortController | null
  historyAbortController: AbortController | null
  requestSeq: number
  streamPending: { content: string; reasoning: string }
  streamFlushTimer: ReturnType<typeof setTimeout> | null
  streamProgressBacking: ChatProgressPayload[]
}

const EMPTY_STREAM_PENDING: Readonly<SessionInternals["streamPending"]> = Object.freeze({
  content: "",
  reasoning: "",
})

export interface ChatStore {
  sessions: Record<string, SessionState>

  // ── Public actions ──
  /** Ensure a session exists in the store (lazy init). Returns whether created. */
  ensure: (runId: string) => boolean
  /** Remove a session from the store (aborts in-flight requests). */
  remove: (runId: string) => void
  /** Update the input draft for a session. */
  setInput: (runId: string, input: string) => void
  /** Send the current input as a user message and start SSE streaming. */
  send: (runId: string) => Promise<void>
  /** Abort the in-flight SSE stream for a session. */
  stop: (runId: string) => void
  /** Load conversation history from the API into a session. Returns outcome for URL handling. */
  loadHistory: (runId: string) => Promise<"ok" | "not_found" | "skipped">
  /** Regenerate the last assistant response. */
  regenerate: (runId: string) => Promise<void>
  /** Start a brand-new session with an initial user message (new-chat bridge). */
  startNew: (runId: string, userMessage: string) => Promise<void>
}

// ── Internals (not in Zustand state; no re-renders) ─────────────────────────

const internals = new Map<string, SessionInternals>()

/** Client-created run_ids before backend confirms; skip history fetch that would 404. */
const optimisticRunIds = new Set<string>()
/** Prevents history fetch right after stream ends (before React commits isStreaming=false). */
const justFinishedRunIds = new Set<string>()

function handleUnauthorized() {
  clearAuthToken()
  if (typeof window !== "undefined") {
    const path = window.location.pathname || "/"
    const search = window.location.search || ""
    const hash = window.location.hash || ""
    redirectToLogin(`${path}${search}${hash}`)
  }
}

/**
 * Whether navigating to `runId` should fetch conversation history from the API.
 * In-flight or just-finished streams use local store state instead.
 */
export function shouldLoadHistoryForRunId(runId: string): boolean {
  const session = useChatStore.getState().sessions[runId]

  // Prefer in-memory session (multi-tab switching, active streams).
  if (session && session.messages.length > 0) return false

  if (session?.isStreaming) return false
  if (justFinishedRunIds.has(runId)) return false

  if (optimisticRunIds.has(runId)) return false

  return true
}

export function markOptimisticRunId(runId: string) {
  optimisticRunIds.add(runId)
}

export function clearOptimisticRunId(runId: string) {
  optimisticRunIds.delete(runId)
}

function markJustFinishedRunId(runId: string) {
  justFinishedRunIds.add(runId)
  setTimeout(() => {
    justFinishedRunIds.delete(runId)
  }, 0)
}

/** True when any session is currently streaming (for sidebar indicators). */
export function selectAnySessionStreaming(state: ChatStore): boolean {
  for (const session of Object.values(state.sessions)) {
    if (session.isStreaming) return true
  }
  return false
}

const EMPTY_STREAMING_IDS: ReadonlySet<string> = new Set()
let streamingIdsCacheKey = ""
let streamingIdsCache: ReadonlySet<string> = EMPTY_STREAMING_IDS

/** Stable Set reference for the same streaming id set (required by useSyncExternalStore). */
export function selectStreamingRunIds(state: ChatStore): ReadonlySet<string> {
  const ids: string[] = []
  for (const [runId, session] of Object.entries(state.sessions)) {
    if (session.isStreaming) ids.push(runId)
  }
  ids.sort()
  const key = ids.join("\0")
  if (key === streamingIdsCacheKey) return streamingIdsCache
  streamingIdsCacheKey = key
  streamingIdsCache = ids.length === 0 ? EMPTY_STREAMING_IDS : new Set(ids)
  return streamingIdsCache
}

function getInternals(runId: string): SessionInternals {
  let s = internals.get(runId)
  if (!s) {
    s = {
      abortController: null,
      historyAbortController: null,
      requestSeq: 0,
      streamPending: { content: "", reasoning: "" },
      streamFlushTimer: null,
      streamProgressBacking: [],
    }
    internals.set(runId, s)
  }
  return s
}

function clearInternalsTimer(s: SessionInternals) {
  if (s.streamFlushTimer != null) {
    clearTimeout(s.streamFlushTimer)
    s.streamFlushTimer = null
  }
}

// ── Store ────────────────────────────────────────────────────────────────────

const EMPTY_SESSION: SessionState = {
  messages: [],
  input: "",
  isLoading: false,
  isStreaming: false,
  streamProgressList: [],
  streamStartedAt: null,
  thinkingElapsedSec: null,
}

export const useChatStore = create<ChatStore>((set, get) => {
  // ── Low-level state helpers ──────────────────────────────────────────────

  function migrateSessionRunId(oldId: string, newId: string) {
    if (oldId === newId) return

    set((state) => {
      if (!(oldId in state.sessions)) return state
      const sessions = { ...state.sessions }
      sessions[newId] = sessions[oldId]
      delete sessions[oldId]
      return { sessions }
    })

    const oldInt = internals.get(oldId)
    if (oldInt) {
      internals.set(newId, oldInt)
      internals.delete(oldId)
    }

    optimisticRunIds.delete(oldId)
    optimisticRunIds.add(newId)

    const optimisticTitle = safeLocalStorageGet(`dac_title_${oldId}`)
    if (optimisticTitle) {
      safeLocalStorageSet(`dac_title_${newId}`, optimisticTitle)
      safeLocalStorageRemove(`dac_title_${oldId}`)
    }

    safeDispatchEvent(
      new CustomEvent<NewChatEventDetail>(REFRESH_CHAT_LIST_EVENT, {
        detail: {
          id: newId,
          title: optimisticTitle || "",
          created_at: new Date().toISOString(),
          replace_id: oldId,
        },
      })
    )

    safeDispatchEvent(
      new CustomEvent(RUN_ID_RECONCILED_EVENT, {
        detail: { oldId, newId },
      })
    )
  }

  function patchSession(runId: string, patch: Partial<SessionState>) {
    set((state) => {
      const prev = state.sessions[runId] ?? EMPTY_SESSION
      const next = { ...prev, ...patch }
      if (shallowEq(prev, next)) return state // avoid useless re-render
      return { sessions: { ...state.sessions, [runId]: next } }
    })
  }

  function updateMessages(runId: string, fn: (prev: Message[]) => Message[]) {
    set((state) => {
      const prev = state.sessions[runId] ?? EMPTY_SESSION
      const messages = fn(prev.messages)
      return { sessions: { ...state.sessions, [runId]: { ...prev, messages } } }
    })
  }

  // ── Public actions ───────────────────────────────────────────────────────

  function ensure(runId: string): boolean {
    const exists = runId in get().sessions
    if (!exists) {
      set((state) => ({
        sessions: { ...state.sessions, [runId]: { ...EMPTY_SESSION } },
      }))
    }
    return !exists
  }

  function removeSession(runId: string) {
    const s = internals.get(runId)
    if (s) {
      s.abortController?.abort()
      s.abortController = null
      s.historyAbortController?.abort()
      s.historyAbortController = null
      clearInternalsTimer(s)
      internals.delete(runId)
    }
    set((state) => {
      if (!(runId in state.sessions)) return state
      const next = { ...state.sessions }
      delete next[runId]
      return { sessions: next }
    })
  }

  function setInput(runId: string, input: string) {
    ensure(runId)
    patchSession(runId, { input })
  }

  async function send(runId: string) {
    ensure(runId)
    const session = get().sessions[runId]
    if (!session || !session.input.trim()) return
    if (session.isLoading || session.isStreaming) return

    const userMsg: Message = { id: safeUUID(), role: "user", content: session.input }
    const assistantMsg: Message = { id: safeUUID(), role: "assistant", content: "", reasoning_content: "" }

    updateMessages(runId, (prev) => [...prev, userMsg, assistantMsg])
    patchSession(runId, {
      input: "",
      isLoading: true,
      isStreaming: true,
      streamProgressList: [],
      streamStartedAt: Date.now(),
      thinkingElapsedSec: null,
    })

    const int = getInternals(runId)
    int.streamProgressBacking = []
    int.streamPending = { content: "", reasoning: "" }

    await processChatRequest(runId, [...session.messages, userMsg])
  }

  function stop(runId: string) {
    const int = internals.get(runId)
    if (int?.abortController) {
      int.abortController.abort()
      int.abortController = null
    }
    const prev = get().sessions[runId] ?? EMPTY_SESSION
    const thinkingElapsedSec =
      prev.streamStartedAt != null
        ? Math.max(0, Math.floor((Date.now() - prev.streamStartedAt) / 1000))
        : prev.thinkingElapsedSec
    patchSession(runId, { isLoading: false, isStreaming: false, thinkingElapsedSec })
  }

  async function loadHistory(runId: string): Promise<"ok" | "not_found" | "skipped"> {
    if (!shouldLoadHistoryForRunId(runId)) return "skipped"

    const int = getInternals(runId)
    int.historyAbortController?.abort()
    const controller = new AbortController()
    int.historyAbortController = controller

    try {
      const token = getAuthToken()
      const response = await fetch(`/api/v1/chat/conversations/${runId}`, {
        headers: { Authorization: token ? `Bearer ${token}` : "" },
        signal: controller.signal,
      })
      if (response.status === 401) {
        handleUnauthorized()
        return "skipped"
      }
      if (!response.ok) {
        if (response.status === 404) {
          if (optimisticRunIds.has(runId)) return "skipped"
          console.warn("Conversation not found")
          return "not_found"
        }
        console.error("Failed to load history:", response.statusText)
        return "skipped"
      }
      const data = (await response.json()) as ConversationHistoryResponse
      if (controller.signal.aborted) return "skipped"
      const rawMessages = Array.isArray(data?.messages) ? data.messages : []
      const historyMessages: Message[] = rawMessages
        .map((m, i): Message | null => {
          const r = typeof m === "object" && m !== null ? (m as Record<string, unknown>) : {}
          const role = r.role
          const content = r.content
          if ((role !== "user" && role !== "assistant" && role !== "system") || typeof content !== "string")
            return null
          const think = typeof r.think === "string" ? r.think : undefined
          const reasoning = typeof r.reasoning_content === "string" ? r.reasoning_content : undefined
          const rawProgress = r.progress_list
          const progressList: ChatProgressPayload[] | undefined =
            Array.isArray(rawProgress) && rawProgress.length > 0
              ? (rawProgress as ChatProgressPayload[])
              : undefined
          const parsedThink = parseHistoryThink(think)
          return {
            id: `${runId}-${i}`,
            role,
            content: stripModelLeakTags(content),
            reasoning_content: parsedThink.reasoning || reasoning || "",
            ...((progressList && progressList.length > 0)
              ? { progressList }
              : (parsedThink.progressList.length > 0 ? { progressList: parsedThink.progressList } : {})),
          }
        })
        .filter((x): x is Message => Boolean(x))
      if (controller.signal.aborted) return "skipped"
      // Do not overwrite if user started streaming while history was in flight.
      if (!shouldLoadHistoryForRunId(runId)) return "skipped"
      patchSession(runId, { messages: historyMessages })
      return "ok"
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return "skipped"
      console.error("Error loading history:", error)
      toast.error("加载历史会话失败")
      return "skipped"
    }
  }

  async function regenerate(runId: string) {
    const session = get().sessions[runId]
    if (!session || session.messages.length === 0) return

    const lastUserIdx = (() => {
      const msgs = session.messages
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i]?.role === "user") return i
      }
      return -1
    })()
    if (lastUserIdx === -1) return

    const messagesHistory = session.messages.slice(0, lastUserIdx + 1)
    const assistantMsg: Message = { id: safeUUID(), role: "assistant", content: "", reasoning_content: "" }

    updateMessages(runId, () => [...messagesHistory, assistantMsg])
    patchSession(runId, {
      isLoading: true,
      isStreaming: true,
      streamProgressList: [],
      streamStartedAt: Date.now(),
      thinkingElapsedSec: null,
    })

    const int = getInternals(runId)
    int.streamProgressBacking = []
    int.streamPending = { content: "", reasoning: "" }

    await processChatRequest(runId, messagesHistory)
  }

  async function startNew(runId: string, userMessage: string) {
    ensure(runId)
    const userMsg: Message = { id: safeUUID(), role: "user", content: userMessage }
    const assistantMsg: Message = { id: safeUUID(), role: "assistant", content: "", reasoning_content: "" }

    patchSession(runId, {
      messages: [userMsg, assistantMsg],
      isLoading: true,
      isStreaming: true,
      streamProgressList: [],
      streamStartedAt: Date.now(),
      thinkingElapsedSec: null,
    })

    const int = getInternals(runId)
    int.streamProgressBacking = []
    int.streamPending = { content: "", reasoning: "" }

    await processChatRequest(runId, [userMsg])
  }

  // ── Core: SSE streaming ─────────────────────────────────────────────────

  async function processChatRequest(initialRunId: string, messagesPayload: Message[]) {
    let activeRunId = initialRunId
    const int = getInternals(activeRunId)
    const myReqSeq = ++int.requestSeq

    int.historyAbortController?.abort()
    int.historyAbortController = null
    int.abortController = new AbortController()
    clearInternalsTimer(int)

    function sessionKey() {
      return activeRunId
    }

    function flushPending() {
      if (myReqSeq !== getInternals(sessionKey()).requestSeq) return
      const pending = int.streamPending
      if (!pending.content && !pending.reasoning) return
      const content = pending.content
      const reasoning = pending.reasoning
      int.streamPending = { content: "", reasoning: "" }

      const runId = sessionKey()
      set((state) => {
        if (myReqSeq !== getInternals(runId).requestSeq) return state
        const prev = state.sessions[runId] ?? EMPTY_SESSION
        const msgs = [...prev.messages]
        const last = msgs[msgs.length - 1]
        if (last?.role !== "assistant") {
          msgs.push({ role: "assistant", content: "", reasoning_content: "" })
        }
        const idx = msgs.length - 1
        const a = msgs[idx]
        if (a.role === "assistant") {
          msgs[idx] = {
            ...a,
            content: stripModelLeakTags((a.content || "") + content),
            reasoning_content: stripModelLeakTags((a.reasoning_content || "") + reasoning),
          }
        }
        return { sessions: { ...state.sessions, [runId]: { ...prev, messages: msgs } } }
      })
    }

    function scheduleFlush() {
      if (int.streamFlushTimer != null) return
      int.streamFlushTimer = setTimeout(() => {
        int.streamFlushTimer = null
        flushPending()
      }, 40)
    }

    function pushProgress(payload: ChatProgressPayload) {
      int.streamProgressBacking = [...int.streamProgressBacking, payload]
      patchSession(sessionKey(), { streamProgressList: int.streamProgressBacking })
    }

    try {
      const token = getAuthToken()
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: token ? `Bearer ${token}` : "",
        },
        body: JSON.stringify({
          messages: messagesPayload,
          stream: true,
          run_id: activeRunId,
        }),
        signal: int.abortController!.signal,
      })

      if (!response.ok) {
        if (response.status === 401) {
          handleUnauthorized()
          return
        }
        throw new Error(response.statusText)
      }

      if (myReqSeq !== getInternals(sessionKey()).requestSeq) return

      const returnedRunId = response.headers.get("x-run-id") || response.headers.get("X-Run-Id")
      if (returnedRunId && returnedRunId !== activeRunId) {
        console.warn(
          `Run ID mismatch. Client: ${activeRunId}, Backend: ${returnedRunId}. Updating to backend ID.`
        )
        migrateSessionRunId(activeRunId, returnedRunId)
        activeRunId = returnedRunId
      }

      if (myReqSeq !== getInternals(sessionKey()).requestSeq) return

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
            if (myReqSeq === getInternals(sessionKey()).requestSeq && shouldShowProgressItem(result.payload)) {
              pushProgress(result.payload)
            }
            continue
          }
          if (result.kind === "done") {
            done = true
            break
          }
          if (result.kind === "chunk") {
            if (lastEventType.length > 0) lastEventType = ""
            if (result.content || result.reasoning) {
              int.streamPending.content += result.content
              int.streamPending.reasoning += result.reasoning
              scheduleFlush()
            }
          }
        }
      }

      // Final flush + freeze progress
      clearInternalsTimer(int)
      const pendingContent = int.streamPending.content
      const pendingReasoning = int.streamPending.reasoning
      int.streamPending = { content: "", reasoning: "" }
      const frozen = [...int.streamProgressBacking]

      const runId = sessionKey()
      set((state) => {
        if (myReqSeq !== getInternals(runId).requestSeq) return state
        const prev = state.sessions[runId] ?? EMPTY_SESSION
        const msgs = [...prev.messages]
        const last = msgs[msgs.length - 1]
        if (last?.role === "assistant") {
          msgs[msgs.length - 1] = {
            ...last,
            content: stripModelLeakTags((last.content || "") + pendingContent),
            reasoning_content: stripModelLeakTags(
              (last.reasoning_content || "") + pendingReasoning
            ),
            ...(frozen.length > 0 ? { progressList: frozen } : {}),
          }
        }
        return {
          sessions: {
            ...state.sessions,
            [runId]: { ...prev, messages: msgs, streamProgressList: [] },
          },
        }
      })
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") {
        console.log("Stream aborted")
        return
      }
      console.error("Chat failed", err)
      toast.error("对话请求失败")
      if (myReqSeq === getInternals(sessionKey()).requestSeq) {
        updateMessages(sessionKey(), (prev) => {
          if (prev.length > 0 && prev[prev.length - 1].role === "user") {
            return [...prev, { id: safeUUID(), role: "assistant", content: "⚠️ Error: Failed to get response." }]
          }
          return prev
        })
      }
    } finally {
      clearInternalsTimer(int)
      int.streamPending = { content: "", reasoning: "" }
      const finishedRunId = sessionKey()
      if (myReqSeq === getInternals(finishedRunId).requestSeq) {
        markJustFinishedRunId(finishedRunId)
        clearOptimisticRunId(finishedRunId)
        const prev = get().sessions[finishedRunId] ?? EMPTY_SESSION
        const thinkingElapsedSec =
          prev.streamStartedAt != null
            ? Math.max(0, Math.floor((Date.now() - prev.streamStartedAt) / 1000))
            : prev.thinkingElapsedSec
        patchSession(finishedRunId, {
          isLoading: false,
          isStreaming: false,
          thinkingElapsedSec,
        })
        int.abortController = null
      }
    }
  }

  return {
    sessions: {},
    ensure,
    remove: removeSession,
    setInput,
    send,
    stop,
    loadHistory,
    regenerate,
    startNew,
  }
})

// ── Selectors ────────────────────────────────────────────────────────────────

/** Select a single session's state. Returns undefined if not in store. */
export function selectSession(runId: string): (state: ChatStore) => SessionState | undefined {
  return (state) => state.sessions[runId]
}

/** Default session for new-chat or empty states. */
export const EMPTY_SESSION_STATE: Readonly<SessionState> = Object.freeze({
  messages: [],
  input: "",
  isLoading: false,
  isStreaming: false,
  streamProgressList: [],
  streamStartedAt: null,
  thinkingElapsedSec: null,
})

// ── Helpers ──────────────────────────────────────────────────────────────────

function shallowEq(a: SessionState, b: SessionState): boolean {
  return (
    a.messages === b.messages &&
    a.input === b.input &&
    a.isLoading === b.isLoading &&
    a.isStreaming === b.isStreaming &&
    a.streamProgressList === b.streamProgressList &&
    a.streamStartedAt === b.streamStartedAt &&
    a.thinkingElapsedSec === b.thinkingElapsedSec
  )
}

// ── Utility (used by page and store) ─────────────────────────────────────────

export function safeUUID() {
  try {
    const c = globalThis.crypto
    if (c && typeof c.randomUUID === "function") return c.randomUUID()
    if (c && typeof c.getRandomValues === "function") {
      const bytes = new Uint8Array(16)
      c.getRandomValues(bytes)
      bytes[6] = (bytes[6] & 0x0f) | 0x40
      bytes[8] = (bytes[8] & 0x3f) | 0x80
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"))
      return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`
    }
  } catch { /* fall through */ }
  return `r_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

export function safeLocalStorageGet(key: string) {
  try {
    return typeof window !== "undefined" ? window.localStorage.getItem(key) : null
  } catch {
    return null
  }
}

export function safeLocalStorageSet(key: string, value: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.setItem(key, value)
  } catch { /* ignore */ }
}

export function safeLocalStorageRemove(key: string) {
  try {
    if (typeof window !== "undefined") window.localStorage.removeItem(key)
  } catch { /* ignore */ }
}

export function safeDispatchEvent<T>(event: CustomEvent<T>) {
  try {
    if (typeof window !== "undefined") window.dispatchEvent(event)
  } catch { /* ignore */ }
}
