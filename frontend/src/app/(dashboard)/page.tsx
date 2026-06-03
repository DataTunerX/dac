"use client"

// Next.js requires useSearchParams() to be wrapped in Suspense.
// We make this page dynamic to avoid prerender failures in production builds.
export const dynamic = "force-dynamic"

import React, { useState, useRef, useEffect, useMemo, useCallback, Suspense } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { ArrowDown, Copy, Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { REFRESH_CHAT_LIST_EVENT, NewChatEventDetail } from "@/lib/events"
import type { ChatProgressPayload } from "@/lib/api-types"
import { cn } from "@/lib/utils"
import { shouldShowProgressItem } from "@/lib/chat-progress"
import { parseHistoryThink } from "@/lib/history-think"
import { parseChatSSELine } from "@/lib/parse-chat-sse"
import { ChatInput } from "@/components/chat/ChatInput"
import { AssistantMessageBody } from "@/components/chat/AssistantMessageBody"
import {
  type ChatMessage,
  type ConversationHistoryResponse,
  EMPTY_PROGRESS,
} from "@/components/chat/chat-message-types"
import { stripModelLeakTags } from "@/lib/strip-model-leak-tags"
import { clearAuthToken, getAuthToken, redirectToLogin } from "@/lib/auth-session"

type Message = ChatMessage

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
              content: stripModelLeakTags(content),
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
            content: stripModelLeakTags((a.content || "") + content),
            reasoning_content: stripModelLeakTags((a.reasoning_content || "") + reasoning),
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
            content: stripModelLeakTags((last.content || "") + pendingContent),
            reasoning_content: stripModelLeakTags((last.reasoning_content || "") + pendingReasoning),
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
              <div
                key={msg.id ?? index}
                className={`flex [content-visibility:auto] ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={cn(
                    "flex flex-col min-w-0",
                    msg.role === "user"
                      ? "max-w-[92%] md:max-w-[78%] items-end"
                      : "w-full items-start"
                  )}
                >
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
                                          isStreaming={
                                            isStreaming &&
                                            index === messages.length - 1 &&
                                            msg.role === "assistant"
                                          }
                                          streamProgressList={
                                            index === messages.length - 1
                                              ? streamProgressList
                                              : EMPTY_PROGRESS
                                          }
                                        />
                                        <div className="flex items-center gap-2 mt-3">
                                            <Button 
                                                type="button"
                                                variant="ghost" 
                                                size="icon" 
                                                className="h-6 w-6 text-content-muted hover:text-content hover:bg-surface-muted rounded-md"
                                                onClick={async () => {
                                                  try {
                                                    await copyToClipboard(stripModelLeakTags(msg.content || ""))
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
